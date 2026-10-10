"""Only the isolated owner services may switch; every failed release preserves data."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy_admin_workspace.sh"
DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['ADMIN_TEST_STATE'])
s = json.loads(p.read_text()); a = sys.argv[1:]
s['calls'].append(a); out = ''; code = 0
if a[0] == 'build': s['tags'][a[a.index('--tag') + 1]] = 'sha256:new-admin'
elif a[:2] == ['image', 'tag']: s['tags'][a[3]] = s['tags'].get(a[2], a[2])
elif a[:2] == ['image', 'inspect']: out = a[-1]
elif a[0] == 'run':
 if '--user' in a: out = 'quota-init'
 else:
  s['runs'] += 1; out = 'candidate-agent' if s['runs'] == 1 else 'candidate-login'
elif a[0] == 'port': out = '127.0.0.1:19108' if a[1] == 'candidate-agent' else '127.0.0.1:19107'
elif a[0] == 'inspect':
 if '{{.Image}}' in a: out = s['active']
 elif any('admin-env-file' in value for value in a): out = s['previous_env_file']
 elif any('admin-model-env-file' in value for value in a): out = s['previous_model_file']
 else: out = 'healthy'
elif a[0] == 'compose':
 assert a[a.index('--project-name') + 1] == 'ai-rag-admin'
 action = a[a.index('--project-name') + 2]
 if action == 'ps': out = 'old-admin-' + a[-1]
 elif action == 'up':
  s['active'] = s['tags']['ai-rag-admin:local']
  s['active_env_file'] = os.environ['RAG_ADMIN_ENV_FILE']
  s['active_model_file'] = os.environ['RAG_MODEL_ENV_FILE']
elif a[0] not in ('rm', 'volume'): code = 2
p.write_text(json.dumps(s))
if out: print(out)
sys.exit(code)
'''
PYTHON = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['ADMIN_TEST_STATE']); s = json.loads(p.read_text())
s['smokes'] += 1; s['smoke_writes'].append('--write' in sys.argv)
p.write_text(json.dumps(s)); sys.exit(1 if s['smokes'] == s['fail_smoke'] else 0)
'''
SUDO = r'''#!/usr/bin/env python3
import os, sys
env = {key: value for key, value in os.environ.items() if key not in ('RAG_ADMIN_ENV_FILE', 'RAG_MODEL_ENV_FILE')}
os.execvpe(sys.argv[1], sys.argv[1:], env)
'''


@pytest.mark.parametrize("fail_smoke", [0, 1, 2])
@pytest.mark.parametrize("reuse_verified", [False, True])
def test_admin_release_candidate_and_rollback_preserve_original_and_public_services(tmp_path, fail_smoke, reuse_verified):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, code in {"docker": DOCKER, "python3": PYTHON, "sudo": SUDO}.items():
        target = bin_dir / name
        target.write_text(code.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
        target.chmod(0o755)
    env_file = tmp_path / "new-admin.env"
    previous = tmp_path / "old-admin.env"
    env_file.write_text("TEST_ADMIN_CONFIG=new\n")
    previous.write_text("TEST_ADMIN_CONFIG=old\n")
    model_file = tmp_path / "new-model.env"
    previous_model = tmp_path / "old-model.env"
    model_file.write_text("LLM_PROVIDER=openrouter\n")
    previous_model.write_text("LLM_PROVIDER=mock\n")
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "tags": {"ai-rag-admin:local": "sha256:old-admin", "ai-rag-platform:local": "sha256:original-private", "ai-rag-public:local": "sha256:public"},
        "active": "sha256:old-admin", "previous_env_file": str(previous),
        "active_env_file": str(previous), "active_model_file": str(previous_model),
        "previous_model_file": str(previous_model), "runs": 0, "smokes": 0,
        "smoke_writes": [], "fail_smoke": fail_smoke, "calls": [],
    }))
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "BUILD_NUMBER": "14", "ADMIN_TEST_STATE": str(state_path), "RAG_ADMIN_ENV_FILE": str(env_file), "RAG_MODEL_ENV_FILE": str(model_file)}
    verified = "sha256:" + "a" * 64
    if reuse_verified:
        env["RAG_ADMIN_VERIFIED_IMAGE"] = verified
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    state = json.loads(state_path.read_text())
    assert (result.returncode == 0) == (fail_smoke == 0), result.stdout + result.stderr
    expected = verified if reuse_verified else "sha256:new-admin"
    assert state["active"] == (expected if fail_smoke == 0 else "sha256:old-admin")
    assert any(call[0] == "build" for call in state["calls"]) == (not reuse_verified)
    assert state["active_env_file"] == (str(env_file) if fail_smoke == 0 else str(previous))
    assert state["active_model_file"] == (str(model_file) if fail_smoke == 0 else str(previous_model))
    assert model_file.read_text() == "LLM_PROVIDER=openrouter\n"
    assert previous_model.read_text() == "LLM_PROVIDER=mock\n"
    assert state["tags"]["ai-rag-platform:local"] == "sha256:original-private"
    assert state["tags"]["ai-rag-public:local"] == "sha256:public"
    assert all("ai-rag-platform" not in " ".join(call) and "ai-rag-public" not in " ".join(call) for call in state["calls"])
    assert previous.read_text() == "TEST_ADMIN_CONFIG=old\n"
    assert env_file.read_text() == "TEST_ADMIN_CONFIG=new\n"
    if fail_smoke == 1:
        assert not any("up" in call for call in state["calls"])
        assert state["smoke_writes"] == [True]
    else:
        assert state["smoke_writes"] == ([True, False] if fail_smoke == 0 else [True, False, False])
    assert [call[-1] for call in state["calls"] if call[:2] == ["volume", "rm"]] == ["ai-rag-admin-smoke-14"]
    runs = [call for call in state["calls"] if call[0] == "run" and "--user" not in call]
    assert "RAG_ADMIN_AUTH=proxy" in runs[0]
    assert "--add-host" in runs[1] and "host.docker.internal:host-gateway" in runs[1]
    assert "admin_login:app_factory" in runs[1] and "--factory" in runs[1]
    assert all(call[call.index("--env-file") + 1] == str(env_file) for call in runs)
    assert str(model_file) in runs[0] and 'ai-rag-web-quota:/opt/agent/web-quota' in runs[0]
