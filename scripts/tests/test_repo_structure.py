import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("structure_check", ROOT / "scripts/check_repo_structure.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class RepoStructureTests(unittest.TestCase):
    def test_current_repository_structure(self):
        self.assertEqual(checker.check(), [])

    def test_every_schema_module_has_one_domain(self):
        import json

        schema = json.loads((ROOT / "specifications/API_SCHEMA.json").read_text(encoding="utf-8"))
        registered = [module for members in checker.MODULE_GROUPS.values() for module in members]
        self.assertEqual(len(registered), len(set(registered)), "模块在业务域中重复登记")
        self.assertEqual(set(registered), set(schema["modules"]))


if __name__ == "__main__":
    unittest.main()
