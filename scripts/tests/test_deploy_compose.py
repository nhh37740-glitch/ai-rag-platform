"""The unified release keeps volumes and never restores legacy containers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy_compose.sh"

DOCKER = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['DOCKER_STATE']); s=json.loads(p.read_text()); a=sys.argv[1:]
s['calls'].append(a); out=''; code=0
if a[:2]==['image','tag']:
 s['tags'][a[3]]=s['tags'].get(a[2],a[2])
elif a[:2]==['image','rm']:
 s['tags'].pop(a[-1],None)
elif a[:2]==['volume','rm']:
 pass
elif a[0]=='build':
 s['tags'][a[a.index('--tag')+1]]='sha256:candidate'
elif a[0]=='run':
 out='candidate-private'
elif a[0]=='port':
 out='127.0.0.1:19180'
elif a[:2]==['container','inspect']:
 code=0 if a[-1] in s['legacy'] else 1
elif a[0]=='inspect':
 out=s['candidate_health'] if a[-1]=='candidate-private' else s['deployed_health']
elif a[0]=='compose':
 action=a[a.index('--project-name')+2]
 if action=='up':
  s['up']+=1; s['running']=True; s['active']=s['tags']['ai-rag-platform:local']
 elif action=='ps':
  out='agent-container' if s['running'] else ''
 elif action=='stop':
  s['running']=False
 elif action=='logs':
  out='synthetic logs'
elif a[:2]==['rm','-f']:
 if a[-1] in s['legacy']: s['legacy'].remove(a[-1])
else: code=2
p.write_text(json.dumps(s))
if out: print(out)
sys.exit(code)
'''

@pytest.fixture
def release_env(tmp_path: Path):
    assert shutil.which('sh')
    bin_dir=tmp_path/'bin'; bin_dir.mkdir()
    docker=bin_dir/'docker'; docker.write_text(DOCKER); docker.chmod(0o755)
    sudo=bin_dir/'sudo'
    sudo.write_text('#!/bin/sh\nif [ "$1" = python3 ]; then exit 0; fi\nexec "$@"\n')
    sudo.chmod(0o755)
    model=tmp_path/'model.env'; model.write_text('LLM_PROVIDER=openrouter\n')
    admin=tmp_path/'bootstrap.env'; admin.write_text('RAG_BOOTSTRAP_ADMIN_USERNAME=administrator\n')
    state=tmp_path/'state.json'
    state.write_text(json.dumps({'tags':{'ai-rag-platform:local':'sha256:old'},
        'legacy':['ai-rag-public-agent-1','ai-rag-admin-agent-1','ai-rag-admin-login-1'],
        'candidate_health':'healthy','deployed_health':'healthy','running':True,
        'active':'sha256:old','up':0,'calls':[]}))
    env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],
         'DOCKER_STATE':str(state),'BUILD_NUMBER':'17',
         'RAG_MODEL_ENV_FILE':str(model),'RAG_BOOTSTRAP_ENV_FILE':str(admin)}
    return env,state

def run(env):
    return subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True)

def load(path):
    return json.loads(path.read_text())

def test_success_replaces_main_service_and_retires_legacy_without_deleting_data(release_env):
    env,path=release_env; result=run(env); state=load(path)
    assert result.returncode==0,result.stderr
    assert state['active']=='sha256:candidate' and state['running']
    assert state['legacy']==[] and state['up']==1
    assert not any(call[:2]==['image','tag'] and 'rollback' in ' '.join(call) for call in state['calls'])
    assert [call[-1] for call in state['calls'] if call[:2]==['volume','rm']]==['ai-rag-private-smoke-17']
    candidate=next(call for call in state['calls'] if call[0]=='run')
    assert 'ai-rag-private-smoke-17:/opt/agent/state' in candidate
    assert 'ai-rag_model-cache:/opt/agent/models/fastembed_cache' in candidate
    assert all('ai-rag-web-quota' not in ' '.join(call) for call in state['calls'])

def test_candidate_failure_does_not_switch_or_retire_containers(release_env):
    env,path=release_env; state=load(path); state['candidate_health']='unhealthy'; path.write_text(json.dumps(state))
    result=run(env); state=load(path)
    assert result.returncode!=0
    assert state['active']=='sha256:old' and state['up']==0
    assert len(state['legacy'])==3
    assert not any(call[:2]==['volume','rm'] and call[-1]!='ai-rag-private-smoke-17' for call in state['calls'])

def test_new_service_failure_stops_it_without_restoring_old_image(release_env):
    env,path=release_env; state=load(path); state['deployed_health']='unhealthy'; path.write_text(json.dumps(state))
    result=run(env); state=load(path)
    assert result.returncode!=0
    assert state['active']=='sha256:candidate' and not state['running']
    assert state['up']==1 and len(state['legacy'])==3
    assert 'no old service was restored' in result.stderr
    assert not any(call[:2]==['volume','rm'] and call[-1]!='ai-rag-private-smoke-17' for call in state['calls'])
