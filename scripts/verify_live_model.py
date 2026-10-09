"""独立的必跑真实模型步骤，不允许把缺凭据当 skip。"""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent-server"))
import runtime_boundary
published = runtime_boundary.enforce_binary_runtime()
for package in published:
    importlib.import_module(package)
runtime_boundary.assert_binary_runtime(published)
if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
    raise SystemExit("真实模型验收缺少 Jenkins 凭据 DEEPSEEK_API_KEY")
os.environ["RUN_LIVE_MODEL"] = "1"
os.environ.setdefault("RAG_EMBED", "hash")
import pytest
raise SystemExit(pytest.main(["-q", "--import-mode=importlib", str(ROOT / "scripts/tests/test_live_cmrc.py"),
                             "--junitxml=reports/live-model.xml"]))
