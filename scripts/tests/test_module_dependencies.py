import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("dependency_check", ROOT / "scripts/check_module_dependencies.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ModuleDependencyTests(unittest.TestCase):
    def test_current_domains_and_app_imports_obey_boundaries(self):
        self.assertEqual(checker.violations(), [])

    def check_fixture(self, files):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "specifications/API_SCHEMA.json"
            destination.parent.mkdir(parents=True)
            destination.write_bytes((ROOT / "specifications/API_SCHEMA.json").read_bytes())
            for relative, code in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(code, encoding="utf-8")
            return checker.violations(root)

    def test_app_cannot_import_leaf_inside_function(self):
        failures = self.check_fixture({"apps/agent-server/server.py": "def run():\n    from rag_core import RagClient\n"})
        self.assertTrue(any("app 不允许依赖 rag_core" in failure for failure in failures))

    def test_database_cannot_dynamically_import_rag(self):
        failures = self.check_fixture({"modules-src/storage/storage/__init__.py": "import importlib\nimportlib.import_module('rag_core')\n"})
        self.assertTrue(any("storage 不允许依赖 rag_core" in failure for failure in failures))

    def test_same_domain_cycle_is_rejected(self):
        failures = self.check_fixture({
            "modules-src/rag-core/rag_core/__init__.py": "import ingestion\n",
            "modules-src/ingestion/ingestion/__init__.py": "import rag_core\n",
        })
        self.assertTrue(any("模块循环依赖" in failure for failure in failures))

    def test_leaf_cannot_depend_on_upper_facade(self):
        failures = self.check_fixture({"modules-src/agent-runtime/agent_runtime/__init__.py": "import agent_facade\n"})
        self.assertTrue(any("agent_runtime 不允许依赖 agent_facade" in failure for failure in failures))

    def test_auth_cannot_import_public_business_module_or_third_party(self):
        for package in ("observability", "agent_runtime", "rag_core", "memory", "data_facade", "httpx"):
            with self.subTest(package=package):
                failures = self.check_fixture({
                    "modules-src/auth-runtime/auth_runtime/__init__.py": f"import {package}\n",
                })
                self.assertTrue(any(f"auth_runtime 不允许依赖 {package}" in failure for failure in failures))

    def test_auth_can_import_shared_specifications_and_standard_library(self):
        failures = self.check_fixture({
            "modules-src/auth-runtime/auth_runtime/__init__.py": (
                "from __future__ import annotations\n"
                "from core_specifications import AuthPrincipal\n"
                "import hashlib, hmac, secrets, re, typing\n"
                "from dataclasses import dataclass\n"
                "import importlib as loader\nloader.import_module('json')\n"
            ),
        })
        self.assertEqual(failures, [])

    def test_auth_cannot_dynamically_import_business_via_alias_or_keyword(self):
        for code in (
            "import importlib as loader\nloader.import_module('observability')\n",
            "from importlib import import_module as load\nload('memory')\n",
            "import importlib\nimportlib.import_module(name='httpx')\n",
            "__import__('rag_core')\n",
        ):
            failures = self.check_fixture({"modules-src/auth-runtime/auth_runtime/__init__.py": code})
            self.assertTrue(any("auth_runtime 不允许依赖" in failure for failure in failures))

    def test_auth_rejects_variable_dynamic_imports_and_parent_package_escape(self):
        for code in (
            "import importlib\nimportlib.import_module(module_name)\n",
            "from importlib import import_module\nimport_module(module_name)\n",
            "__import__(module_name)\n",
            "import importlib\nimportlib.import_module('.memory', package='parent')\n",
            "from ..memory import MemoryStore\n",
        ):
            failures = self.check_fixture({"modules-src/auth-runtime/auth_runtime/__init__.py": code})
            self.assertTrue(any("auth_runtime" in failure for failure in failures))

    def test_auth_project_can_only_declare_shared_specifications_dependency(self):
        for dependency, valid in (("core_specifications", True), ("core-specifications>=0.2", True),
                                  ("observability", False), ("httpx>=0.27", False), ("rag_core", False)):
            with self.subTest(dependency=dependency):
                failures = self.check_fixture({
                    "modules-src/auth-runtime/pyproject.toml":
                        "[project]\nname = 'auth_runtime'\ndependencies = [" + repr(dependency) + "]\n",
                })
                self.assertEqual(bool(failures), not valid)
