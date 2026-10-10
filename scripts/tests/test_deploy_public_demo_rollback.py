"""Candidate and post-switch failures must preserve the separate private deployment."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy_public_demo.sh'
DOCKER = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['PUBLIC_STATE']); s=json.loads(p.read_text()); a=sys.argv[1:]
s['calls'].append(a); out=''; code=0
if a[0]=='build': s['tags'][a[a.index('--tag')+1]]='sha256:new-public'
elif a[:2]==['image','tag']: s['tags'][a[3]]=s['tags'].get(a[2],a[2])
elif a[:2]==['image','inspect']: out=s['tags'][a[2]]
elif a[0]=='run': out='quota-init' if '--user' in a else 'candidate-public'
elif a[0]=='port': out='127.0.0.1:19000'
elif a[0]=='inspect':
 if '{{.Image}}' in a: out=s['active']
 elif any('public-provider' in x for x in a): out=s['previous_provider']
 elif any('public-env-file' in x for x in a): out=s['previous_env_file']
 else: out='healthy'
elif a[0]=='compose':
 assert a[a.index('--project-name')+1]=='ai-rag-public'
 action=a[a.index('--project-name')+2]
 if action=='ps': out='active-public'
 elif action=='up':
  s['active']=s['tags']['ai-rag-public:local']
  s['runtime_provider']=os.environ['PUBLIC_DEMO_PROVIDER']
  s['runtime_env_file']=os.environ['PUBLIC_DEMO_ENV_FILE']
elif a[0] not in ('rm','volume'): code=2
p.write_text(json.dumps(s)); print(out) if out else None; sys.exit(code)
'''
PYTHON = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['PUBLIC_STATE']); s=json.loads(p.read_text()); s['smokes']+=1
s['smoke_modes'].append(sys.argv[3])
p.write_text(json.dumps(s)); sys.exit(1 if s['smokes']==s['fail_smoke'] else 0)
'''
SUDO = r'''#!/usr/bin/env python3
import os,sys
# Match sudo's environment reset; env NAME=value must explicitly reintroduce values.
env={k:v for k,v in os.environ.items() if k not in ('PUBLIC_DEMO_PROVIDER','PUBLIC_DEMO_ENV_FILE','PUBLIC_DEMO_MOCK_ENV_FILE')}
os.execvpe(sys.argv[1],sys.argv[1:],env)
'''


def prepare(tmp_path, fail_smoke, candidate_provider, previous_provider):
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    for name, code in {'docker': DOCKER, 'python3': PYTHON, 'sudo': SUDO}.items():
        code = code.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1)
        target = bin_dir / name; target.write_text(code); target.chmod(0o755)
    env_file = tmp_path / 'provider.env'; env_file.write_text('DEMO_TEST=1\n')
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'tags': {'ai-rag-public:local': 'sha256:old-public',
                                         'ai-rag-platform:local': 'sha256:private'},
                                 'active': 'sha256:old-public', 'smokes': 0, 'smoke_modes': [],
                                 'previous_provider': previous_provider, 'previous_env_file': str(env_file),
                                 'runtime_provider': previous_provider, 'runtime_env_file': str(env_file),
                                 'fail_smoke': fail_smoke, 'calls': []}))
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
           'PUBLIC_STATE': str(state), 'PUBLIC_DEMO_ENV_FILE': str(env_file), 'BUILD_NUMBER': '18',
           'PUBLIC_DEMO_PROVIDER': candidate_provider,
           'PUBLIC_DEMO_MOCK_ENV_FILE': str(tmp_path / 'provider-mock.env')}
    return env, state


@pytest.mark.parametrize('fail_smoke', [1, 2])
@pytest.mark.parametrize('candidate_provider', ['deepseek', 'mock', 'openrouter'])
@pytest.mark.parametrize('previous_provider', ['deepseek', 'openrouter'])
def test_public_candidate_failure_preserves_private_and_restores_public(tmp_path, fail_smoke, candidate_provider, previous_provider):
    env, state_path = prepare(tmp_path, fail_smoke, candidate_provider, previous_provider)
    result = subprocess.run(['sh', str(SCRIPT)], env=env, capture_output=True, text=True)
    state = json.loads(state_path.read_text())
    assert result.returncode != 0
    assert state['active'] == 'sha256:old-public'
    assert state['tags']['ai-rag-platform:local'] == 'sha256:private'
    assert state['runtime_provider'] == previous_provider
    assert state['runtime_env_file'] == env['PUBLIC_DEMO_ENV_FILE']
    assert Path(env['PUBLIC_DEMO_ENV_FILE']).read_text() == 'DEMO_TEST=1\n'
    assert all('ai-rag-platform' not in ' '.join(call) for call in state['calls'])
    if fail_smoke == 1:
        assert not any('up' in call for call in state['calls'])
    else:
        assert state['smokes'] == 3, 'rollback must be smoke tested too'
    assert state['smoke_modes'] == ([candidate_provider] if fail_smoke == 1 else [candidate_provider, candidate_provider, previous_provider])
    runs = [call for call in state['calls'] if call[0] == 'run' and '--user' not in call]
    assert 'DEMO_PROVIDER=' + candidate_provider in runs[0]
    expected_env_file = env['PUBLIC_DEMO_MOCK_ENV_FILE'] if candidate_provider == 'mock' else env['PUBLIC_DEMO_ENV_FILE']
    assert runs[0][runs[0].index('--env-file') + 1] == expected_env_file
    assert 'ai-rag-web-quota:/opt/agent/web-quota' in runs[0]
    assert 'LLM_PROVIDER=' + candidate_provider in runs[0]
    removed_volumes = [call[-1] for call in state['calls'] if call[:2] == ['volume', 'rm']]
    assert removed_volumes == ['ai-rag-public-smoke-18']
