from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "modules-src"
ART = ROOT / "artifacts"
SCHEMA = ROOT / "contracts" / "API_SCHEMA.json"


def main() -> None:
    built = 0
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    module_ids = {
        spec["package"]: module_id
        for module_id, spec in schema.get("modules", {}).items()
    }
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
        module_id = module_ids.get(pkg)
        if module_id is None:
            continue
        init = mod / pkg / "__init__.py"
        if not init.exists():
            continue
        print(f"[cythonize] {pkg}@{version}")
        subprocess.run(["cythonize", "-i", str(init)], cwd=ROOT, check=True)
        out = ART / module_id / version / pkg
        out.mkdir(parents=True, exist_ok=True)
        for pyd in glob.glob(str(mod / pkg / "__init__*.pyd")):
            shutil.copy2(pyd, out / Path(pyd).name)
        built += 1
    print(f"built {built} compiled packages; .pyd under artifacts/<module-id>/<version>/<pkg>/")


if __name__ == "__main__":
    main()
