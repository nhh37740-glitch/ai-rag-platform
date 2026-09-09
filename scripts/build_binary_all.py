from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "modules-src"
ART = ROOT / "artifacts"


def main() -> None:
    built = 0
    for mod in sorted(SRC.iterdir()):
        py = mod / "pyproject.toml"
        if not py.exists():
            continue
        with open(py, "rb") as f:
            proj = tomllib.load(f).get("project", {})
        name = proj.get("name")
        version = proj.get("version", "0.1.0")
        if not name:
            continue
        pkg = name.replace("-", "_")
        init = mod / pkg / "__init__.py"
        if not init.exists():
            continue
        print(f"[cythonize] {pkg}@{version}")
        subprocess.run(["cythonize", "-i", str(init)], cwd=ROOT, check=True)
        out = ART / pkg / version / pkg
        out.mkdir(parents=True, exist_ok=True)
        for pyd in glob.glob(str(mod / pkg / "__init__*.pyd")):
            shutil.copy2(pyd, out / Path(pyd).name)
        built += 1
    print(f"built {built} compiled packages; .pyd under artifacts/<pkg>/<version>/<pkg>/")


if __name__ == "__main__":
    main()
