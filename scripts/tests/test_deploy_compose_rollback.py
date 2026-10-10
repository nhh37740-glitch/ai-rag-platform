from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy_compose.sh"


DOCKER_STUB = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["DOCKER_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
state["calls"].append(args)
result = ""
code = 0

def save():
    state_path.write_text(json.dumps(state))

if args[:2] == ["image", "inspect"]:
    image = args[-1]
    if image not in state["tags"]:
        code = 1
    else:
        result = state["tags"][image]
elif args[:2] == ["image", "tag"]:
    source, target = args[2:4]
    image_id = state["tags"].get(source, source)
    state["tags"][target] = image_id
elif args[:2] == ["image", "rm"]:
    state["tags"].pop(args[-1], None)
elif args[:1] == ["build"]:
    tag = args[args.index("--tag") + 1]
    state["tags"][tag] = "sha256:candidate"
elif args[:1] == ["compose"]:
    action = args[args.index("--project-name") + 2]
    tail = args[args.index("--project-name") + 3:]
    if action == "up":
        state["container_image"] = state["tags"]["ai-rag-platform:local"]
        state["container_health"] = state["health"].get(state["container_image"], "healthy")
        state["container_running"] = True
    elif action == "ps":
        if state.get("container_running"):
            result = "agent-container"
    elif action == "logs":
        result = "fake container logs"
    elif action == "stop":
        state["container_running"] = False
elif args[:1] == ["inspect"]:
    if "{{.Image}}" in args:
        result = state["container_image"]
    elif any('model-env-file' in value for value in args):
        result = os.environ['RAG_MODEL_ENV_FILE']
    else:
        result = state["container_health"]
elif args[:1] == ["run"]:
    result = 'candidate-private'
elif args[:1] == ["port"]:
    result = '127.0.0.1:19180'
elif args[:1] in (["rm"], ["volume"]):
    pass
else:
    code = 2

save()
if result:
    print(result)
sys.exit(code)
'''


SUDO_STUB = "#!/bin/sh\nexec \"$@\"\n"


@pytest.fixture
def deploy_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    assert shutil.which("sh"), "POSIX sh is required to exercise the deployment script"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB, encoding="utf-8")
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/bin/sh\nif [ "$1" = python3 ]; then exit 0; fi\nexec "$@"\n', encoding="utf-8")
    docker.chmod(0o755)
    sudo.chmod(0o755)

    state_path = tmp_path / "docker-state.json"
    state_path.write_text(
        json.dumps(
            {
                "tags": {"ai-rag-platform:local": "sha256:old"},
                "health": {"sha256:old": "healthy", "sha256:candidate": "healthy"},
                "container_image": "sha256:old",
                "container_health": "healthy",
                "container_running": True,
                "calls": [],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    model_file = tmp_path / 'runtime.env'
    model_file.write_text('LLM_PROVIDER=openrouter\n')
    env.update({"PATH": f"{bin_dir}{os.pathsep}{env['PATH']}", "DOCKER_STATE": str(state_path), "BUILD_NUMBER": "17", "RAG_MODEL_ENV_FILE": str(model_file)})
    return env, state_path


def run_deploy(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)


def read_state(state_path: Path) -> dict:
    return json.loads(state_path.read_text(encoding="utf-8"))


def test_healthy_candidate_keeps_deployed_image_and_does_not_remove_volumes(deploy_env):
    env, state_path = deploy_env
    result = run_deploy(env)
    state = read_state(state_path)

    assert result.returncode == 0, result.stderr
    assert state["tags"]["ai-rag-platform:local"] == "sha256:candidate"
    assert state["container_image"] == "sha256:candidate"
    assert not any("down" in call for call in state["calls"])
    assert [call[-1] for call in state["calls"] if call[:2] == ["volume", "rm"]] == ['ai-rag-private-smoke-17']
    candidate = [call for call in state['calls'] if call[0] == 'run' and '--user' not in call][0]
    assert 'ai-rag-web-quota:/opt/agent/web-quota' in candidate


def test_unhealthy_candidate_restores_previous_image_without_touching_volumes(deploy_env):
    env, state_path = deploy_env
    state = read_state(state_path)
    state["health"]["sha256:candidate"] = "unhealthy"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = run_deploy(env)
    state = read_state(state_path)

    assert result.returncode != 0
    assert "rolling back" in result.stderr
    assert state["tags"]["ai-rag-platform:local"] == "sha256:old"
    assert state["container_image"] == "sha256:old"
    assert state["container_health"] == "healthy"
    assert not any("down" in call for call in state["calls"])
    assert [call[-1] for call in state["calls"] if call[:2] == ["volume", "rm"]] == ['ai-rag-private-smoke-17']
