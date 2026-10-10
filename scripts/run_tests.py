"""Run source or compiled behavior tests with an explicit import boundary."""
from __future__ import annotations

import argparse
import importlib
import importlib.abc
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SourcePackages(importlib.abc.MetaPathFinder):
    """Force source tests to ignore stale extensions beside __init__.py."""
    def __init__(self):
        self.packages = {
            spec["package"]: ROOT / "modules-src" / mid / spec["package"]
            for mid, spec in json.loads((ROOT / "specifications/API_SCHEMA.json").read_text(encoding="utf-8"))["modules"].items()
        }

    def find_spec(self, fullname, path=None, target=None):
        directory = self.packages.get(fullname)
        if directory and (directory / "__init__.py").is_file():
            return importlib.util.spec_from_file_location(
                fullname, directory / "__init__.py", submodule_search_locations=[str(directory)]
            )
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["source", "binary"], required=True)
    parser.add_argument("--group", choices=["leaf", "facade", "scripts", "app", "specification", "domain"], required=True)
    parser.add_argument("--junitxml")
    args = parser.parse_args(argv)
    os.environ.setdefault("RAG_EMBED", "hash")
    sys.path.insert(0, str(ROOT / "specifications"))
    sys.path.insert(0, str(ROOT))
    if args.mode == "source":
        if args.group == "app":
            parser.error("application tests require compiled modules")
        sys.meta_path.insert(0, SourcePackages())
        os.environ["SPEC_STATIC_ONLY"] = "1"
    elif args.group not in {"app", "specification"}:
        sys.path.insert(0, str(ROOT / "apps/agent-server"))
        import runtime_boundary
        published = runtime_boundary.enforce_binary_runtime()
        for package in published:
            importlib.import_module(package)
        runtime_boundary.assert_binary_runtime(published)
        print(f"Behavior tests use {len(published)} published extensions")
    if args.mode == "binary" and args.group == "specification":
        os.environ["SPEC_STRICT"] = "1"
    if args.group in {"leaf", "facade"}:
        paths = [str(p / "tests") for p in sorted((ROOT / "modules-src").iterdir())
                 if (p / "tests").is_dir() and (p.name.endswith("-facade") == (args.group == "facade"))]
    else:
        paths = {"scripts": ["scripts/tests"], "app": ["apps/agent-server/tests"],
                 "specification": ["specifications/test_specification.py"],
                 "domain": ["scripts/tests/test_domain_integration.py", "scripts/tests/test_module_dependencies.py"]}[args.group]
    import pytest
    options = ["-q", "--import-mode=importlib", *paths]
    if args.junitxml:
        options.append(f"--junitxml={args.junitxml}")
    # Application boot never reads private local state during tests.
    if args.group == "app":
        import tempfile
        with tempfile.TemporaryDirectory(prefix="agent-app-tests-") as temporary:
            os.environ.update(STATE_DIR=temporary, DB_PATH=str(Path(temporary) / "memory.sqlite"),
                              VECTOR_DB_PATH=str(Path(temporary) / "vectors.sqlite"),
                              INDEX_PATH=str(Path(temporary) / "no-index.json"), DEEPSEEK_API_KEY="")
            # The server must establish the boundary before auth middleware tests
            # import extensions. Boot only after allocating isolated test state.
            sys.path.insert(0, str(ROOT / "apps/agent-server"))
            server = importlib.import_module("server")
            import runtime_boundary
            published = runtime_boundary.load_published_modules()
            for package in published:
                importlib.import_module(package)
            runtime_boundary.assert_binary_runtime(published)
            print(f"Application tests use {len(published)} published extensions")
            result = pytest.main(options)
            server = sys.modules.get("server")
            if server is not None:
                import asyncio
                asyncio.run(server.runtime.aclose(server.BOOT_CONTEXT))
                server.data_service.close(server.BOOT_CONTEXT)
            return result
    return pytest.main(options)


if __name__ == "__main__":
    raise SystemExit(main())
