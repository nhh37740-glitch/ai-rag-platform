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
        if not re.search(r"(?m)^#{1,3}\s+(?:\\[)?" + re.escape(newp) + r"\b", log):
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
