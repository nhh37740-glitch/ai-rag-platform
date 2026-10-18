#!/usr/bin/env python3
"""Trusted PR metadata guard. Run from base branch only; never execute PR code."""
import base64
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

REPO = os.environ["GITHUB_REPOSITORY"]
NUMBER = int(os.environ["PR_NUMBER"])
TOKEN = os.environ["GH_TOKEN"]
API = "https://api.github.com/repos/" + REPO
FAIL = []


def get(url):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-rag-pr-guard",
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def pages(path):
    result = []
    for page in range(1, 101):
        batch = get(API + path + ("&" if "?" in path else "?") + "per_page=100&page=" + str(page))
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError("GitHub pagination limit exceeded")


def file_at(sha, path):
    quoted = urllib.parse.quote(path, safe="/")
    try:
        data = get(API + "/contents/" + quoted + "?ref=" + sha)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if data.get("encoding") != "base64":
        raise RuntimeError("Unexpected content encoding for " + path)
    return base64.b64decode(data["content"]).decode("utf-8")


def issue_number(body):
    matches = re.findall(r"(?im)^\s*(?:fixes|closes|resolves)\s+#(\d+)\s*$", body)
    if len(matches) != 1:
        FAIL.append("Exactly one standalone 'Fixes #N' closing line is required")
        return None
    if len(re.findall(r"(?i)\b(?:fixes|closes|resolves)\s+#\d+", body)) != 1:
        FAIL.append("PR must have exactly one closing issue")
    return int(matches[0])


ISSUE_SECTIONS = ("问题", "影响", "验收标准", "涉及模块", "作者")
MAX_PROBLEM_CHARS = 200
# 仅拦截高确定性的辱骂/臆测性归责；客观性与“同一问题”的语义仍需人审。
HOSTILE_EXPRESSIONS = re.compile(
    r"脑残|傻逼|蠢货|废物|垃圾代码|垃圾系统|烂透了|一坨屎|故意坑人|毫无能力"
)


def validate_problem_description(contents, number):
    """One concise, observable phenomenon; length counts visible characters."""
    readable = re.sub(r"\s+", " ", contents).strip()
    if len(readable) > MAX_PROBLEM_CHARS:
        FAIL.append(
            f"Issue #{number}：『问题』为 {len(readable)} 字，超出 {MAX_PROBLEM_CHARS} 字上限。"
            "请只描述一个能观察到的现象。"
        )
    paragraphs = [p for p in re.split(r"\n\s*\n", contents) if p.strip()]
    if len(paragraphs) > 1 or re.search(r"(?m)^\s*(?:[-*+]\s+|\d+[.)]\s+|#{1,6}\s+)", contents):
        FAIL.append(
            f"Issue #{number}：『问题』只能写一个自然段，禁止分段、清单或小标题。"
            "不同问题现象请分开创建 Issue。"
        )
    if re.search(r"另一个问题|另外一个问题|第二个问题|第三个问题", contents):
        FAIL.append(
            f"Issue #{number}：『问题』包含另一个问题，请拆分为不同 Issue。"
        )



ISSUE_TEMPLATE_PLACEHOLDERS = {
    "问题": ("只描述一个问题，并提供复现步骤。",),
    "影响": ("描述影响范围、用户行为和优先级。",),
    "验收标准": (
        "- [ ] 定义可以机器/人工验证的完成条件。",
        "- [ ] 定义可以由人直接观察到的修复结果。",
    ),
    "涉及模块": ("写明预期涉及的模块和跨模块原因。",),
    "作者": ("填写负责人及使用的 AI 工具（如适用）。",),
}


def validate_issue_format(issue, number):
    """检查关联 Issue 正文，而非只检查 PR 是否填写 Fixes #N。"""
    if not (issue.get("title") or "").strip():
        FAIL.append(f"Issue #{number}: title cannot be empty")
    body = issue.get("body") or ""
    headers = list(re.finditer(r"(?m)^##\s+([^\r\n]+?)\s*$", body))
    names = [match.group(1).strip() for match in headers]
    for required in ISSUE_SECTIONS:
        count = names.count(required)
        if count != 1:
            FAIL.append(
                f"Issue #{number}: expected exactly one '## {required}' heading; "
                f"found {count}. Edit the Issue body to match .github/ISSUE_TEMPLATE/problem.md"
            )
    if all(names.count(key) == 1 for key in ISSUE_SECTIONS):
        ordered = [names.index(key) for key in ISSUE_SECTIONS]
        if ordered != sorted(ordered):
            FAIL.append(
                f"Issue #{number}: headings must appear in this order: "
                + " → ".join(ISSUE_SECTIONS)
            )
    for index, match in enumerate(headers):
        name = match.group(1).strip()
        if name not in ISSUE_SECTIONS:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
        contents = re.sub(r"<!--.*?-->", "", body[match.end():end], flags=re.S).strip()
        if not contents or contents in ISSUE_TEMPLATE_PLACEHOLDERS[name]:
            FAIL.append(
                f"Issue #{number}: '## {name}' is empty or still contains only the template text"
            )
        if name == "问题" and contents:
            validate_problem_description(contents, number)
        if name == "验收标准" and not re.search(
            r"(?m)^\s*[-*]\s*\[[ xX]\]\s+\S+", contents
        ):
            FAIL.append(
                f"Issue #{number}: '## 验收标准' must include at least one '- [ ] ...' checkbox"
            )

    clean_body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    flagged = HOSTILE_EXPRESSIONS.search(clean_body)
    if flagged:
        FAIL.append(
            f"Issue #{number}：发现贬损或主观归责词语「{flagged.group()}」。"
            "请只描述客观现象，不要黑化人或系统。"
        )




def changed_modules(paths):
    return {parts[1] for path in paths if (parts := path.split("/")) and
            len(parts) >= 3 and parts[0] == "modules-src"}


def version_tuple(text):
    if not re.fullmatch(r"\d+\.\d+\.\d+", text):
        raise ValueError("Expected X.Y.Z: " + text)
    return tuple(map(int, text.split(".")))


def verify_module_version(module, paths, pr):
    prefix = "modules-src/" + module + "/"
    code = any(p.startswith(prefix) and p.endswith(".py") and
               "/tests/" not in p and not p.endswith("/test_specification.py") for p in paths)
    if not code:
        return
    project = prefix + "pyproject.toml"
    version = prefix + "VERSION"
    changelog = prefix + "CHANGELOG.md"
    required = {project, version, changelog}
    if not required.issubset(paths):
        FAIL.append(module + ": implementation changed: must update pyproject.toml, VERSION, CHANGELOG.md")
        return
    base, head = pr["base"]["sha"], pr["head"]["sha"]
    try:
        oldp = tomllib.loads(file_at(base, project))["project"]["version"]
        newp = tomllib.loads(file_at(head, project))["project"]["version"]
        current = file_at(head, version).strip()
        log = file_at(head, changelog) or ""
        if version_tuple(newp) <= version_tuple(oldp):
            FAIL.append(module + ": new version must increase from " + oldp)
        if newp != current:
            FAIL.append(module + ": VERSION does not match pyproject.toml")
        if not re.search(r"(?m)^#{1,3}\s+\[?" + re.escape(newp) + r"(?:\]|\b)", log):
            FAIL.append(module + ": CHANGELOG missing a heading for " + newp)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        FAIL.append(module + ": invalid version metadata: " + str(e))


def main():
    pr = get(API + "/pulls/" + str(NUMBER))
    body = pr.get("body") or ""
    head_name = pr["head"]["ref"]
    n = issue_number(body)
    if n is not None:
        if not re.fullmatch(r"ai/" + str(n) + r"-[a-z0-9][a-z0-9-]*", head_name):
            FAIL.append("Branch must match ai/" + str(n) + "-short-description")
        try:
            issue = get(API + "/issues/" + str(n))
            if "pull_request" in issue:
                FAIL.append("Linked number must refer to an Issue, not a PR")
            else:
                validate_issue_format(issue, n)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                FAIL.append("Linked Issue does not exist")
            else:
                raise
    if not re.match(r"^(feat|fix|docs|test|build|chore|refactor|ci|perf)(\([a-z0-9-]+\))?!?: .{4,}", pr["title"]):
        FAIL.append("PR title must follow Conventional Commits")
    for heading in ("目的", "问题", "改动", "验证", "作者"):
        if not re.search(r"(?m)^#{2,4}\s*" + heading + r"\s*$", body):
            FAIL.append("PR body missing heading: " + heading)
    files = pages("/pulls/" + str(NUMBER) + "/files?")
    paths = {f["filename"] for f in files}
    modules = changed_modules(paths)
    if len(modules) > 1:
        if not re.search(r"(?m)^#{2,4}\s*跨模块原因\s*$", body):
            FAIL.append("Multi-module PR must explain under '## 跨模块原因'")
    if len(files) > 20 and not re.search(r"(?m)^#{2,4}\s*大范围改动原因\s*$", body):
        FAIL.append("Changes to >20 files require '## 大范围改动原因'")
    for module in sorted(modules):
        verify_module_version(module, paths, pr)
    print("Guard checked", len(files), "files;", len(modules), "modules")
    for failure in FAIL:
        print("::error::" + failure)
    if FAIL:
        sys.exit(1)
    print("PR governance checks passed")


if __name__ == "__main__":
    main()
