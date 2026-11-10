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

    def test_render_loads_complete_always_skill(self):
        d = _tmp_dir()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sdir = os.path.join(str(d), "skills", "rag-retrieval")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: rag-retrieval\n"
                "description: RAG 检索\n"
                "version: 1.0.0\n"
                "always: true\n"
                "---\n"
                "# 完整指令\n\n必须根据检索结果回答。\n"
            )

        reg = SkillRegistry()
        reg.load_dir(os.path.join(str(d), "skills"))

        rendered = reg.render(None, "你好")
        self.assertIn("# 完整指令", rendered)
        self.assertIn("必须根据检索结果回答", rendered)

    def test_render_selects_triggered_skill_only_on_match(self):
        d = _tmp_dir()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        skills_dir = os.path.join(str(d), "skills")
        sdir = os.path.join(skills_dir, "incident-analysis")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: incident-analysis\n"
                "description: 故障分析\n"
                "version: 1.0.0\n"
                "triggers:\n"
                "  - 故障\n"
                "  - incident\n"
                "---\n"
                "# 故障处理指令\n"
            )

        reg = SkillRegistry()
        reg.load_dir(skills_dir)

        self.assertIn("故障处理指令", reg.render(None, "请分析这个故障"))
        self.assertEqual(reg.render(None, "今天天气如何"), "")

    def test_render_supports_inline_triggers(self):
        d = _tmp_dir()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        skills_dir = os.path.join(str(d), "skills")
        sdir = os.path.join(skills_dir, "notes")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: notes\n"
                "description: 笔记\n"
                "triggers: [笔记, notebook]\n"
                "---\n"
                "# 笔记指令\n"
            )

        reg = SkillRegistry()
        reg.load_dir(skills_dir)

        self.assertIn("笔记指令", reg.render(None, "保存到 notebook"))


if __name__ == "__main__":
    unittest.main()
