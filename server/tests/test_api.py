import os
from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO

ROOT=TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite:///'+str(Path(ROOT.name)/'test.sqlite')
os.environ['ASSET_DIR']=str(Path(ROOT.name)/'assets')

from fastapi.testclient import TestClient
from PIL import Image
from app import app


def test_story_panel_text_export_isolation():
    with TestClient(app) as client:
        p=client.post('/api/projects',json={'title':'大小姐和司机','premise':'迟到的故事','panel_count':4}).json()
        pid=p['id']
        c=client.post(f'/api/projects/{pid}/characters',json={'name':'大小姐','appearance':'布偶猫','personality':'傲娇'}).json()
        plan=client.post(f'/api/projects/{pid}/story:mock').json()
        assert len(plan['panels'])==4
        panel=plan['panels'][2]
        d=client.post(f'/api/panels/{panel["id"]}/dialogues',json={'text':'今天怎么又迟到了？','speaker_id':c['id']}).json()
        assert client.post(f'/api/dialogues/{d["id"]}/lock').status_code==200
        assert client.patch(f'/api/dialogues/{d["id"]}',json={'text':'我昨天就出发了！'}).status_code==409
        img=Image.new('RGB',(128,128),(60,120,210));buffer=BytesIO();img.save(buffer,format='PNG')
        a=client.post(f'/api/panels/{panel["id"]}/assets',files={'file':('art.png',buffer.getvalue(),'image/png')}).json()
        client.post(f'/api/panels/{panel["id"]}/approve/{a["id"]}')
        before=client.get(f'/api/projects/{pid}').json()
        assert before['panels'][2]['approved_asset_id']==a['id']
        assert client.get(f'/api/projects/{pid}/validate').json()['valid']
        result=client.get(f'/api/projects/{pid}/export.svg')
        assert result.status_code==200 and '今天怎么又迟到了？' in result.text
        client.post(f'/api/dialogues/{d["id"]}/unlock')
        edited=client.patch(f'/api/dialogues/{d["id"]}',json={'text':'我昨天就出发了！'}).json()
        after=client.get(f'/api/projects/{pid}').json()
        assert edited['version']==2
        assert [p['approved_asset_id'] for p in before['panels']]==[p['approved_asset_id'] for p in after['panels']]
        assert '我昨天就出发了！' in client.get(f'/api/projects/{pid}/export.svg').text
        png=client.get(f'/api/projects/{pid}/export.png')
        assert png.status_code==200 and png.content[:8]==b'\x89PNG\r\n\x1a\n'
        assert client.get(f'/api/projects/{pid}/export.json').json()['panels'][2]['dialogues'][0]['text']=='我昨天就出发了！'


def test_validation_and_authorization_constraints():
    with TestClient(app) as client:
        p=client.post('/api/projects',json={'title':'异常检查','panel_count':6}).json()
        other=client.post('/api/projects',json={'title':'另一个项目','panel_count':4}).json()
        panel=client.get(f'/api/projects/{p["id"]}').json()['panels'][0]
        cross=client.post(f'/api/projects/{other["id"]}/characters',json={'name':'其他项目角色'}).json()
        assert client.post(f'/api/panels/{panel["id"]}/dialogues',json={'text':'错误绑定','speaker_id':cross['id']}).status_code==422
        assert client.post(f'/api/panels/{panel["id"]}/dialogues',json={'text':'位置越界','x':.8,'w':.3}).status_code==422
        d=client.post(f'/api/panels/{panel["id"]}/dialogues',json={'text':'正确的中文。'}).json()
        assert client.patch(f'/api/dialogues/{d["id"]}',json={'text':'错字检查：中文，精准！'}).status_code==200
        assert '错字检查：中文，精准！' in client.get(f'/api/projects/{p["id"]}/export.svg').text
        assert client.post(f'/api/panels/{panel["id"]}/assets',files={'file':('test.txt',b'not image','text/plain')}).status_code==415
