"""Offline contract tests: no vendor calls or API tokens required."""
import base64
from io import BytesIO
import json

import httpx
from fastapi.testclient import TestClient
from PIL import Image

import ai_pipeline
from app import app


def png_bytes():
    out=BytesIO()
    Image.new("RGB",(96,64),"#abccee").save(out,"PNG")
    return out.getvalue()


def story_fixture(names, count=4):
    return {
        "outline":"司机连续迟到，大小姐发现真相。",
        "panels":[
            {"sequence":i+1,"scene":f"别墅门前，二人对话，镜头{i+1}。","camera":"中景",
             "dialogues":[{"speaker_name": names[i%len(names)], "text":f"第{i+1}格：发生什么事了？"}]}
            for i in range(count)
        ]
    }


def test_story_review_apply_and_no_overwrite(monkeypatch):
    monkeypatch.setenv("STORY_API_BASE_URL","http://example.test/v1")
    monkeypatch.setenv("STORY_MODEL","offline-model")
    monkeypatch.setenv("STORY_API_KEY","secret-stays-on-server")
    fake=story_fixture(["大小姐","大橘司机"])
    calls=[]
    def mock_post(url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(fake,ensure_ascii=False)}}]})
    monkeypatch.setattr(ai_pipeline.httpx,"post",mock_post)
    with TestClient(app) as client:
        project=client.post('/api/projects',json={'title':'大小姐和司机','premise':'迟到','panel_count':4}).json()
        pid=project['id']
        for name in ("大小姐","大橘司机"):
            assert client.post(f'/api/projects/{pid}/characters',json={'name':name}).status_code==201
        status=client.get('/api/ai/status').json()
        assert status['story']['ready'] is True
        assert "secret" not in json.dumps(status)
        response=client.post(f'/api/projects/{pid}/story:ai')
        assert response.status_code==201, response.text
        proposed=response.json()
        assert proposed['draft']==fake
        assert client.get(f'/api/projects/{pid}').json()['panels'][0]['dialogues']==[]
        assert client.post(f'/api/story-drafts/{proposed["id"]}/apply').status_code==200
        panels=client.get(f'/api/projects/{pid}').json()['panels']
        assert panels[0]['dialogues'][0]['text']==fake['panels'][0]['dialogues'][0]['text']
        assert client.post(f'/api/story-drafts/{proposed["id"]}/apply').status_code==409
        latest=client.post(f'/api/projects/{pid}/story:ai').json()
        assert client.post(f'/api/story-drafts/{latest["id"]}/apply').status_code==409
        assert client.get(f'/api/projects/{pid}').json()['panels'][0]['dialogues'][0]['text']==fake['panels'][0]['dialogues'][0]['text']
        assert calls[0][1]['headers']['Authorization']=="Bearer secret-stays-on-server"
        other=client.post('/api/projects',json={'title':'手工分镜不可覆盖','panel_count':4}).json()
        panel_id=client.get(f'/api/projects/{other["id"]}').json()['panels'][0]['id']
        assert client.patch(f'/api/panels/{panel_id}',json={'scene':'原创故事：不能覆盖'}).status_code==200
        changed_story=story_fixture(["大小姐","大橘司机"])
        # No characters created in the second project; use all-null cast for valid generated draft.
        changed_story["panels"]=[{**entry,"dialogues":[{"speaker_name":None,"text":"原始分镜保护"}]} for entry in changed_story["panels"]]
        def manual_story_post(url,**kwargs):
            return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(changed_story,ensure_ascii=False)}}]})
        monkeypatch.setattr(ai_pipeline.httpx,"post",manual_story_post)
        draft2=client.post(f'/api/projects/{other["id"]}/story:ai').json()
        assert client.post(f'/api/story-drafts/{draft2["id"]}/apply').status_code==409
        assert client.get(f'/api/projects/{other["id"]}').json()['panels'][0]['scene']=='原创故事：不能覆盖'


def test_image_generation_candidate_and_reference_edits(monkeypatch):
    monkeypatch.setenv("IMAGE_API_BASE_URL","http://example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL","offline-image")
    monkeypatch.setenv("IMAGE_REFERENCE_MODE","edits")
    img=png_bytes()
    calls=[]
    def mock_post(url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json={"data":[{"b64_json":base64.b64encode(img).decode("ascii")}]})
    monkeypatch.setattr(ai_pipeline.httpx,"post",mock_post)
    with TestClient(app) as client:
        project=client.post('/api/projects',json={'title':'布偶猫日常','panel_count':4}).json()
        pid=project['id']
        ch=client.post(f'/api/projects/{pid}/characters',json={'name':'布偶猫','appearance':'蓝眼睛粉色裙子'}).json()
        panel=client.get(f'/api/projects/{pid}').json()['panels'][0]
        reference=client.post(f'/api/characters/{ch["id"]}/reference',files={'file':('reference.png',img,'image/png')})
        assert reference.status_code==201,reference.text
        result=client.post(f'/api/panels/{panel["id"]}/generate:ai',json={'character_ids':[ch['id']]})
        assert result.status_code==201,result.text
        asset=result.json()
        assert asset['reference_count']==1 and not asset['approved']
        assert calls[0][0].endswith("/images/edits")
        assert 'files' in calls[0][1]
        assert '不要出现任何中文' in calls[0][1]['data']['prompt'] or '绝对不要出现任何中文' in calls[0][1]['data']['prompt']
        assert client.get(f'/api/projects/{pid}').json()['panels'][0]['approved_asset_id'] is None
        candidates=client.get(f'/api/panels/{panel["id"]}/candidates').json()
        assert candidates[0]['id']==asset['id']
        approved=client.post(f'/api/panels/{panel["id"]}/approve/{asset["id"]}')
        assert approved.status_code==200
        assert client.get(f'/api/projects/{pid}').json()['panels'][0]['approved_asset_id']==asset['id']


def test_image_mode_without_reference_or_invalid_response(monkeypatch):
    monkeypatch.setenv("IMAGE_API_BASE_URL","http://example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL","offline-image")
    monkeypatch.setenv("IMAGE_REFERENCE_MODE","off")
    def bad_post(url,**kwargs):
        return httpx.Response(200,json={"data":[{"url":"https://untrusted.example/image.png"}]})
    monkeypatch.setattr(ai_pipeline.httpx,"post",bad_post)
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'title':'测试','panel_count':4}).json()['id']
        panel=client.get(f'/api/projects/{pid}').json()['panels'][0]
        bad=client.post(f'/api/panels/{panel["id"]}/generate:ai',json={})
        assert bad.status_code==502
        assert 'b64_json' in bad.text
        assert client.get(f'/api/panels/{panel["id"]}/candidates').json()==[]
    monkeypatch.setenv("IMAGE_REFERENCE_MODE","edits")
    data=ai_pipeline._parse_story(json.dumps(story_fixture(["甲"]),ensure_ascii=False),4,["甲"])
    assert data['panels'][0]['dialogues'][0]['text']=="第1格：发生什么事了？"
    invalid=story_fixture(["甲"])
    invalid["panels"][0]["sequence"]=2
    try:
        ai_pipeline._parse_story(json.dumps(invalid,ensure_ascii=False),4,["甲"])
        assert False,"should have rejected invalid sequence"
    except ai_pipeline.AIProviderError:
        pass
