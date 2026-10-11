"""Compiled HTTP permission tests never use real accounts or model credentials."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKEN = "test-only-notebook-proof-1234567890123456789"
ORIGIN = "https://notebook.test"

CHECKS = r"""
import asyncio, json, os
from pathlib import Path
import httpx
import server as s
from core_specifications import ToolCall

TOKEN = os.environ['RAG_ADMIN_PROXY_TOKEN']
ORIGIN = os.environ['RAG_ADMIN_ORIGIN']
def headers(user='owner', role='admin'):
    return {'x-rag-proxy-token':TOKEN, 'x-rag-user-id':user, 'x-rag-role':role, 'origin':ORIGIN}
owner, alice, bob = headers(), headers('alice','user'), headers('bob','user')
requests = []
class Provider:
    async def generate(self, ctx, messages, tools=None):
        requests.append((ctx, messages[0].content, [tool.name for tool in tools or []]))
        if not any(message.role=='tool' for message in messages):
            user_text = next(message.content for message in reversed(messages) if message.role=='user')
            if 'attack' in user_text: return '', [ToolCall('evil','create_file',{'filename':'evil.md','content':'bad'})]
            return '', [ToolCall('search','search_knowledge_base', {'query': user_text})]
        return '已根据当前笔记本回答。', []
s.request_provider._default = Provider()

async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=ORIGIN) as client:
        a=(await client.post('/api/notebooks',headers=owner,json={'name':'甲笔记本'})).json()['id']
        b=(await client.post('/api/notebooks',headers=owner,json={'name':'乙笔记本'})).json()['id']
        Path(os.environ['STATE_DIR'],'test-notebook.json').write_text(json.dumps([a,b]))
        p=f'/api/notebooks/{a}'
        async def set_member(user,role,actor=owner):
            return await client.put(p+'/members/'+user, headers=actor,json={'role':role})
        async def upload(actor,progress,nb=a):
            return await client.post(f'/api/notebooks/{nb}/files?upload_id={progress}',headers=actor,files={'files':('说明.md',('# 项目\n紫杉项目由Jenkins发布。任务：'+progress).encode(),'text/markdown')})
        assert (await client.get('/',headers=alice)).status_code==200
        assert (await client.post('/api/notebooks',headers=alice,json={'name':'越权'})).status_code==403
        assert [v['id'] for v in (await client.get('/api/notebooks',headers=alice)).json()['notebooks']]==[s.DEMO_KB_ID]
        assert (await set_member('alice','viewer')).status_code==200
        assert (await set_member('bob','viewer')).status_code==200
        assert (await set_member('owner','viewer')).status_code==422
        assert (await client.put(p+'/members/alice',headers={**owner,'origin':'https://attacker.test'},json={'role':'manager'})).status_code==403
        assert (await client.put(p+'/members/alice',headers=owner,json={'role':'manager','user_id':'owner'})).status_code==422
        assert (await set_member('alice','admin')).status_code==422
        assert (await client.get('/api/notebooks/'+s.DEMO_KB_ID+'/members',headers=owner)).status_code==403
        books=(await client.get('/api/notebooks',headers=alice)).json()['notebooks']
        assert {v['id'] for v in books}=={s.DEMO_KB_ID,a}
        assert not next(v for v in books if v['id']==a)['writable']
        assert (await client.get(p+'/documents',headers=alice)).status_code==200
        assert (await client.get('/api/notebooks/'+b+'/documents',headers=alice)).status_code==403
        assert (await client.get('/api/notebooks/'+b+'/suggestions',headers=alice)).status_code==403
        assert (await upload(alice,'denied-upload')).status_code==403
        assert (await client.get(p+'/members',headers=alice)).status_code==403
        assert (await set_member('other','viewer',alice)).status_code==403
        assert (await upload(owner,'owner-progress')).status_code==201
        assert (await client.get('/api/uploads/owner-progress',headers=bob)).status_code==404
        response=await client.post('/api/chat',headers=alice,json={'message':'请查询紫杉项目的发布方式','session_id':'same','user_id':'owner','knowledge_base_ids':[a]})
        assert response.status_code==200,response.text
        assert all(ctx.user_id=='alice' for ctx,_,_ in requests)
        assert all('create_file' not in names for _,_,names in requests)
        trace_id=response.json()['trace_id']
        trace=await client.get('/api/trace/'+trace_id,headers=alice)
        assert trace.status_code==200
        hits=[hit for span in trace.json() if span['span']=='rag' for hit in span['meta'].get('hits',[])]
        assert hits and all(hit['source_id'].startswith(a+'/') for hit in hits),trace.text
        assert (await client.get('/api/trace/'+trace_id,headers=bob)).status_code==404
        assert (await client.post('/api/chat',headers=alice,json={'message':'x','knowledge_base_ids':[a,b]})).status_code==403
        assert (await client.get('/api/chat/stream',headers=alice,params={'message':'x','knowledge_base_ids':b})).status_code==403
        before=s.AGENT_FILES_DIR.exists()
        assert (await client.post('/api/chat',headers=alice,json={'message':'attack','knowledge_base_ids':[a]})).status_code==200
        assert s.AGENT_FILES_DIR.exists()==before and not (s.AGENT_FILES_DIR/'evil.md').exists()
        assert (await set_member('alice','editor')).status_code==200
        assert (await upload(alice,'alice-progress')).status_code==201
        assert (await client.get('/api/uploads/alice-progress',headers=alice)).status_code==200
        assert (await client.get('/api/uploads/alice-progress',headers=bob)).status_code==404
        assert (await upload(alice,'owner-progress')).status_code==409
        assert (await set_member('alice','manager')).status_code==200
        assert (await set_member('carol','editor',alice)).status_code==200
        assert (await client.put('/api/notebooks/'+b+'/members/bob',headers=alice,json={'role':'manager'})).status_code==403
        # User+session+scope cannot reuse previous private history or user memory.
        s.runtime._runtime._histories[('alice',s._scoped_session('same',[a]))].append(s.ChatMessage('assistant','NOTEBOOK_A_PRIVATE_MARKER'))
        assert (await client.post('/api/chat',headers=alice,json={'message':'公开问题','session_id':'same','knowledge_base_ids':[s.DEMO_KB_ID]})).status_code==200
        assert 'NOTEBOOK_A_PRIVATE_MARKER' not in requests[-1][1]
        assert (await client.delete(p+'/members/alice',headers=owner)).status_code==200
        assert (await client.get(p+'/documents',headers=alice)).status_code==403
        assert (await client.get('/api/trace/'+trace_id,headers=alice)).status_code==403
        assert (await client.get('/api/uploads/alice-progress',headers=alice)).status_code==403
        assert (await client.get('/api/chat/stream',headers=alice,params={'message':'x','knowledge_base_ids':a})).status_code==403
        assert (await client.post('/api/chat',headers=alice,json={'message':'x','knowledge_base_ids':[a]})).status_code==403
        forged={**alice,'x-rag-proxy-token':'forged'}
        assert (await client.get('/api/notebooks',headers=forged)).status_code==403
        assert (await client.get('/api/notebooks',headers={**alice,'x-rag-role':'admin'})).status_code==403
asyncio.run(main())
s.data_service.close(s.BOOT_CONTEXT)
"""

REOPEN = r"""
import os,json
from pathlib import Path
import server as s
a,b=json.loads(Path(os.environ['STATE_DIR'],'test-notebook.json').read_text())
ctx=s.BOOT_CONTEXT
token=os.environ['RAG_ADMIN_PROXY_TOKEN']
bob=s.auth_service.authenticate_proxy(ctx,token,'bob','user')
carol=s.auth_service.authenticate_proxy(ctx,token,'carol','user')
alice=s.auth_service.authenticate_proxy(ctx,token,'alice','user')
assert s.auth_service.notebook_permissions(ctx,bob,a)==['read','query']
assert 'import_document' in s.auth_service.notebook_permissions(ctx,carol,a)
assert s.auth_service.notebook_permissions(ctx,alice,a)==[]
assert s.auth_service.notebook_permissions(ctx,bob,b)==[]
s.data_service.close(ctx)
"""

class NotebookHTTPTests(unittest.TestCase):
    def test_members_roles_scope_revocation_and_real_restart_persistence(self):
        with tempfile.TemporaryDirectory(prefix='rag-acl-http-') as directory:
            env=dict(os.environ,PYTHONPATH=str(ROOT/'apps/agent-server'),PUBLIC_DEMO='0',RAG_ADMIN_AUTH='proxy',RAG_ADMIN_PROXY_TOKEN=TOKEN,RAG_ADMIN_OWNER_ID='owner',RAG_ADMIN_ORIGIN=ORIGIN,LLM_PROVIDER='mock',OPENROUTER_API_KEY='',DEEPSEEK_API_KEY='',RAG_LLM_ENV_FILE='',RAG_EMBED='hash',STATE_DIR=directory,DB_PATH=str(Path(directory)/'memory.sqlite'),VECTOR_DB_PATH=str(Path(directory)/'vectors.sqlite'),INDEX_PATH=str(Path(directory)/'absent.json'),RAG_NOTEBOOKS_DIR=str(Path(directory)/'notebooks'))
            for code in [CHECKS,REOPEN]:
                result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
