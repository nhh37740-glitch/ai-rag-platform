"""Regression tests for linked Issue formatting."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("GITHUB_REPOSITORY", "example/repository")
os.environ.setdefault("PR_NUMBER", "1")
os.environ.setdefault("GH_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_guard


def example_issue():
    return {
        "title": "fix: restore authorization checks",
        "body": (
            "## 问题\n权限判断错误，某些账号无法使用。\n\n"
            "## 影响\n已登录用户无法访问笔记本。\n\n"
            "## 验收标准\n- [ ] 禁用用户请求返回 403\n\n"
            "## 涉及模块\nmodules-src/auth-facade\n\n"
            "## 作者\n@developer\n"
        ),
    }


class IssueFormatTests(unittest.TestCase):
    def setUp(self):
        pr_guard.FAIL.clear()

    def test_valid_issue_passes(self):
        pr_guard.validate_issue_format(example_issue(), 20)
        self.assertEqual(pr_guard.FAIL, [])

    def test_missing_heading_reports_specific_error(self):
        issue = example_issue()
        issue["body"] = issue["body"].replace("## 影响\n", "")
        pr_guard.validate_issue_format(issue, 20)
        self.assertTrue(any("## 影响" in error for error in pr_guard.FAIL))

    def test_duplicate_problem_heading_fails(self):
        issue = example_issue()
        issue["body"] += "\n## 问题\n第二个问题\n"
        pr_guard.validate_issue_format(issue, 20)
        self.assertTrue(any("## 问题" in error for error in pr_guard.FAIL))

    def test_unmodified_template_placeholder_fails(self):
        issue = example_issue()
        issue["body"] = issue["body"].replace(
            "## 影响\n已登录用户无法访问笔记本。",
            "## 影响\n描述影响范围、用户行为和优先级。",
        )
        pr_guard.validate_issue_format(issue, 20)
        self.assertTrue(any("## 影响" in error for error in pr_guard.FAIL))

    def test_missing_checklist_fails(self):
        issue = example_issue()
        issue["body"] = issue["body"].replace("- [ ] 禁用用户请求返回 403", "禁用用户请求返回 403")
        pr_guard.validate_issue_format(issue, 20)
        self.assertTrue(any("checkbox" in error for error in pr_guard.FAIL))

    def test_wrong_order_fails(self):
        issue = example_issue()
        issue["body"] = issue["body"].replace(
            "## 影响\n已登录用户无法访问笔记本。\n\n"
            "## 验收标准\n- [ ] 禁用用户请求返回 403\n\n",
            "## 验收标准\n- [ ] 禁用用户请求返回 403\n\n"
            "## 影响\n已登录用户无法访问笔记本。\n\n",
        )
        pr_guard.validate_issue_format(issue, 20)
        self.assertTrue(any("order" in error for error in pr_guard.FAIL))


if __name__ == "__main__":
    unittest.main()
