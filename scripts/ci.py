from __future__ import annotations

import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(cmd: list[str], check: bool = True) -> None:
    print(f"\n===== {' '.join(cmd)} =====")
    env = {**os.environ, "DEEPSEEK_API_KEY": "", "RAG_EMBED": "hash"}  # CI 离线确定性
    p = subprocess.run(cmd, cwd=ROOT, env=env)
    if check and p.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd)}")


def main() -> None:
    run([PY, "-m", "pytest", "modules-src", "-q", "-p", "no:cacheprovider"])
    run([PY, "-X", "utf8", "scripts/integration_test.py"])
    run([PY, "-X", "utf8", "scripts/eval_run.py"])
    run([PY, "-X", "utf8", "scripts/build_artifacts.py"])
    pyd = sorted(ROOT.glob("artifacts/observability/0.1.0/observability/*.pyd"))
    if pyd:
        run([PY, "-X", "utf8", "scripts/binary_demo.py"])
    else:
        print("\n[skip] binary_demo（先运行 Cython 编译 observability 生成 .pyd）")
    print("\nCI CHECKPOINT: ALL GREEN")


if __name__ == "__main__":
    main()
