import os
import pathlib
import shutil
import uuid
import unittest

from skill_runtime import SkillRegistry


def _tmp_dir() -> pathlib.Path:
    base = pathlib.Path("data/_tests")
    base.mkdir(parents=True, exist_ok=True)
    d = base / ("t" + uuid.uuid4().hex[:8])
    d.mkdir(parents=True, exist_ok=False)
    return d


class TestSkillRuntime(unittest.TestCase):
    def test_load_dir(self):
        d = _tmp_dir()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sdir = os.path.join(str(d), "skills", "incident-analysis")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: incident-analysis\ndescription: 故障分析\nversion: 1.0.0\n---\n# 指令\n")
        reg = SkillRegistry()
        reg.load_dir(os.path.join(str(d), "skills"))
        self.assertEqual(len(reg.list()), 1)
        self.assertEqual(reg.list()[0].name, "incident-analysis")
        loaded = reg.load(None, "incident-analysis")
        self.assertIsNotNone(loaded.load)

    def test_load_missing_raises(self):
        reg = SkillRegistry()
        with self.assertRaises(KeyError):
            reg.load(None, "nope")


if __name__ == "__main__":
    unittest.main()
