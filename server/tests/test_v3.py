"""v0.3 contract tests for immutable character assets, queue and SVG layout."""
from io import BytesIO
import os
import json

from fastapi.testclient import TestClient
from PIL import Image

import ai_pipeline
import worker
from app import app, ASSET_DIR, SessionLocal, GenerationJob


def tiny_image(color="orange"):
    out=BytesIO()
    Image.new("RGB",(96,64),color).save(out,"PNG")
    return out.getvalue()


def test_reference_history_and_active_switch():
    with TestClient(app) as client:
        p=client.post('/api/projects',json={'title':'连续漫画','panel_count':4}).json()
        ch=client.post(f'/api/projects/{p["id"]}/characters',json={'name':'大橘','appearance':'橘色虎斑'}).json()
        a=client.post(f'/api/characters/{ch["id"]}/references?angle=front&note=v1',files={'file':('front.png',tiny_image(),'image/png')})
        b=client.post(f'/api/characters/{ch["id"]}/references?angle=side&note=v2',files={'file':('side.png',tiny_image('blue'),'image/png')})
        assert a.status_code==b.status_code==201, (a.text,b.text)
        ref_a,ref_b=a.json(),b.json()
        assert ref_a['asset_id']!=ref_b['asset_id']
        before=client.get(f'/api/projects/{p["id"]}').json()['characters'][0]
        assert before['reference_asset_id']==ref_a['asset_id']
        switch=client.post(f'/api/characters/{ch["id"]}/references/{ref_b["id"]}/activate')
        assert switch.status_code==200
        latest=client.get(f'/api/projects/{p["id"]}').json()['characters'][0]
        assert latest['reference_asset_id']==ref_b['asset_id']
        assert len(client.get(f'/api/characters/{ch["id"]}/references').json())==2
        assert client.get(f'/api/assets/{ref_a["asset_id"]}').status_code==200
        other=client.post('/api/projects',json={'title':'别人的角色','panel_count':4}).json()
        outsider=client.post(f'/api/projects/{other["id"]}/characters',json={'name':'别人'}).json()
        assert client.post(f'/api/characters/{outsider["id"]}/references/{ref_a["id"]}/activate').status_code==422


def test_durable_mock_queue_and_text_lock(monkeypatch):
    monkeypatch.setattr(worker.MockImageProvider,"generate",lambda self,*args:tiny_image())
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'title':'精准中文四格','panel_count':4}).json()['id']
        p=client.get(f'/api/projects/{pid}').json()['panels'][2]
        d=client.post(f'/api/panels/{p["id"]}/dialogues',json={'text':'这是锁定的中文！'}).json()
        client.post(f'/api/dialogues/{d["id"]}/lock')
        layout=client.patch(f'/api/dialogues/{d["id"]}',json={'x':.1,'y':.11,'w':.8,'h':.3})
        assert layout.status_code==200, layout.text
        assert layout.json()['text']=='这是锁定的中文！'
        assert client.patch(f'/api/dialogues/{d["id"]}',json={'text':'篡改'}).status_code==409
        first=client.post(f'/api/panels/{p["id"]}/jobs',json={'provider':'mock','request_key':'v3-test-key'})
        assert first.status_code==202, first.text
        again=client.post(f'/api/panels/{p["id"]}/jobs',json={'provider':'mock','request_key':'v3-test-key'})
        assert again.json()['id']==first.json()['id']
        result=worker.process_one()
        assert result and result['status']=='succeeded',result
        job=client.get('/api/jobs/'+first.json()['id']).json()
        assert job['candidate_asset_id'] and job['status']=='succeeded'
        assert client.get(f'/api/projects/{pid}').json()['panels'][2]['approved_asset_id'] is None
        client.post(f'/api/panels/{p["id"]}/approve/{job["candidate_asset_id"]}')
        approved=client.get(f'/api/projects/{pid}').json()['panels'][2]
        assert approved['approved_asset_id']==job['candidate_asset_id']
        assert approved['dialogues'][0]['text']=='这是锁定的中文！'
        svg=client.get(f'/api/projects/{pid}/export.svg')
        assert svg.status_code==200 and '这是锁定的中文！' in svg.text


def test_cancel_retry_and_frozen_prompt(monkeypatch):
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'title':'任务保护','panel_count':4}).json()['id']
        panel=client.get(f'/api/projects/{pid}').json()['panels'][0]
        client.patch(f'/api/panels/{panel["id"]}',json={'scene':'原始镜头：看着蓝色天空'})
        queued=client.post(f'/api/panels/{panel["id"]}/jobs',json={'provider':'mock','request_key':'cancel-01'}).json()
        assert client.post('/api/jobs/'+queued['id']+'/cancel').json()['status']=='cancelled'
        assert client.post('/api/jobs/'+queued['id']+'/retry').status_code==409
        assert worker.process_one() is None

        monkeypatch.setenv("IMAGE_API_BASE_URL","http://example.test/v1")
        monkeypatch.setenv("IMAGE_MODEL","test-model")
        observed=[]
        def fail_once(prompt,refs):
            observed.append(prompt)
            if len(observed)==1:raise ai_pipeline.AIProviderError("test unavailable")
            return tiny_image('green')
        monkeypatch.setattr(ai_pipeline,"image_candidate",fail_once)
        queued=client.post(f'/api/panels/{panel["id"]}/jobs',json={'provider':'ai','request_key':'retry-01'}).json()
        client.patch(f'/api/panels/{panel["id"]}',json={'scene':'新内容：地面下雨'})
        assert worker.process_one()['status']=='failed'
        failed=client.get('/api/jobs/'+queued['id']).json()
        assert failed['attempt']==1 and failed['error_code']=='AIProviderError'
        assert client.post('/api/jobs/'+queued['id']+'/retry').json()['status']=='queued'
        assert worker.process_one()['status']=='succeeded'
        final=client.get('/api/jobs/'+queued['id']).json()
        assert final['attempt']==2 and final['candidate_asset_id']
        assert '原始镜头' in observed[0] and '新内容' not in observed[0]
        assert observed[0]==observed[1]
        assert client.post('/api/jobs/'+queued['id']+'/retry').status_code==409
