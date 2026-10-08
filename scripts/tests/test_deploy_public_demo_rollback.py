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
elif a[0]=='run': out='candidate-public'
elif a[0]=='port': out='127.0.0.1:19000'
elif a[0]=='inspect': out=s['active'] if '{{.Image}}' in a else 'healthy'
elif a[0]=='compose':
 assert a[a.index('--project-name')+1]=='ai-rag-public'
 action=a[a.index('--project-name')+2]
 if action=='ps': out='active-public'
 elif action=='up': s['active']=s['tags']['ai-rag-public:local']
elif a[0] not in ('rm','volume'): code=2
p.write_text(json.dumps(s)); print(out) if out else None; sys.exit(code)
'''
PYTHON = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['PUBLIC_STATE']); s=json.loads(p.read_text()); s['smokes']+=1
p.write_text(json.dumps(s)); sys.exit(1 if s['smokes']==s['fail_smoke'] else 0)
'''


def prepare(tmp_path, fail_smoke):
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    for name, code in {'docker': DOCKER, 'python3': PYTHON, 'sudo': '#!/bin/sh\nexec "$@"\n'}.items():
        code = code.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1)
        target = bin_dir / name; target.write_text(code); target.chmod(0o755)
    env_file = tmp_path / 'provider.env'; env_file.write_text('DEMO_TEST=1\n')
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'tags': {'ai-rag-public:local': 'sha256:old-public',
                                         'ai-rag-platform:local': 'sha256:private'},
                                 'active': 'sha256:old-public', 'smokes': 0,
                                 'fail_smoke': fail_smoke, 'calls': []}))
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
           'PUBLIC_STATE': str(state), 'PUBLIC_DEMO_ENV_FILE': str(env_file), 'BUILD_NUMBER': '18'}
    return env, state


@pytest.mark.parametrize('fail_smoke', [1, 2])
def test_public_candidate_failure_preserves_private_and_restores_public(tmp_path, fail_smoke):
    env, state_path = prepare(tmp_path, fail_smoke)
    result = subprocess.run(['sh', str(SCRIPT)], env=env, capture_output=True, text=True)
    state = json.loads(state_path.read_text())
    assert result.returncode != 0
    assert state['active'] == 'sha256:old-public'
    assert state['tags']['ai-rag-platform:local'] == 'sha256:private'
    assert all('ai-rag-platform' not in ' '.join(call) for call in state['calls'])
    if fail_smoke == 1:
        assert not any('up' in call for call in state['calls'])
    else:
        assert state['smokes'] == 3, 'rollback must be smoke tested too'
    removed_volumes = [call[-1] for call in state['calls'] if call[:2] == ['volume', 'rm']]
    assert removed_volumes == ['ai-rag-public-smoke-18']
