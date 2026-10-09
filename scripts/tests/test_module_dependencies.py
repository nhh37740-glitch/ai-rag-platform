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
