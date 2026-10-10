"""Verify guarded private ingress and Media reachability without logging secrets.

Pass --write only for the disposable candidate container, never live private data.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from smoke_model_config import check as check_model_config


def request(base, path, *, method="GET", body=None, headers=None):
    req = urllib.request.Request(base.rstrip("/") + path, data=body, method=method, headers=headers or {})
    try:
        response = urllib.request.urlopen(req, timeout=90)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        data = response.read()
        try:
            result = json.loads(data)
        except ValueError:
            result = data.decode("utf-8", errors="replace")
        return response.code, result, response.headers


def smoke(private_base, login_base, env_file, *, write=False, model_env_file=None):
    config = {}
    for line in Path(env_file).read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and not key.startswith("#"):
            config[key.strip()] = value.strip()
    proof = config["RAG_ADMIN_PROXY_TOKEN"]
    owner = config["RAG_ADMIN_OWNER_ID"]
    headers = {"X-Rag-Proxy-Token": proof, "X-Rag-User-Id": owner, "X-Rag-Role": "admin", "Origin": config["RAG_ADMIN_ORIGIN"]}
    assert request(private_base, "/api/demo")[0] == 200
    status, guest, _ = request(private_base, "/api/auth/session")
    assert status == 200 and guest["role"] == "guest" and guest["permissions"] == ["read", "query"]
    assert guest["allowed_notebook_ids"] == ["cmrc2018-demo"] and "proof" not in guest
    status, notebooks, _ = request(private_base, "/api/notebooks")
    assert status == 200 and [item["id"] for item in notebooks["notebooks"]] == ["cmrc2018-demo"]
    assert all(not item["writable"] for item in notebooks["notebooks"])
    for path in ["/", "/api/admin/session", "/api/notebooks/private/documents", "/api/uploads/private", "/api/trace/private", "/static/knowledge_demo.js", "/docs"]:
        assert request(private_base, path)[0] == 403, path
    assert request(private_base, "/api/notebooks", method="POST", body=b'{}')[0] == 403
    assert request(private_base, "/api/notebooks/private/files", method="POST", body=b'')[0] == 403
    status, session, response_headers = request(private_base, "/api/admin/session", headers=headers)
    assert status == 200 and session["mode"] == "proxy" and session["administrator"] and session["user_id"] == owner
    assert response_headers["Cache-Control"] == "no-store" and proof not in json.dumps(session)
    status, model, _ = request(private_base, "/api/llm/config", headers=headers)
    assert status == 200
    if model_env_file:
        check_model_config(model, model_env_file)
    if model["provider"] == "openrouter":
        assert model["model"] == "openrouter/free" and model["free_models_only"] is True
        assert model["quota"]["scope"] == "site" and model["quota"]["limit"] == 20
    assert request(private_base, "/api/notebooks", headers={**headers, "X-Rag-User-Id": "other-account"})[0] == 403
    assert request(private_base, "/api/notebooks", method="POST", body=b'{}', headers={**headers, "Origin": "https://attacker.invalid"})[0] == 403
    assert request(login_base, "/health")[0] == 200
    status, page, _ = request(login_base, "/")
    assert status == 200 and 'id="login-form"' in page and proof not in page
    assert request(login_base, "/verify")[0] == 403
    assert request(login_base, "/verify", headers={"X-Rag-Proxy-Token": proof})[0] == 401
    status, _, verify_headers = request(login_base, "/verify", headers={"X-Rag-Proxy-Token": proof, "Cookie": "rag_admin_session=invalid-test-session"})
    assert status == 403 and "X-Rag-User-Id" not in verify_headers
    # This is a real network request to the already deployed Media auth service.
    status, csrf, csrf_headers = request(login_base, "/csrf")
    assert status == 200 and csrf["headerName"] == "X-CSRF-TOKEN" and csrf["token"]
    cookie = csrf_headers.get("Set-Cookie", "")
    assert cookie.startswith("rag_admin_session=")
    assert all(value in cookie for value in ["Secure", "HttpOnly", "SameSite=strict", "Path=/projects/apps/rag/admin/"])
    if write:
        json_headers = {**headers, "Content-Type": "application/json"}
        status, notebook, _ = request(private_base, "/api/notebooks", method="POST", body=json.dumps({"name": "候选管理员导入验收"}).encode(), headers=json_headers)
        assert status == 201
        notebook_id = notebook["id"]
        boundary = "RagCandidateSmokeBoundary"
        content = "# 紫杉项目\n紫杉项目由 Jenkins 验证模块测试后交付 Docker 镜像。\n"
        body = ("--" + boundary + '\r\nContent-Disposition: form-data; name="files"; filename="candidate.md"\r\nContent-Type: text/markdown\r\n\r\n' + content + "\r\n--" + boundary + "--\r\n").encode()
        status, imported, _ = request(private_base, "/api/notebooks/" + notebook_id + "/files", method="POST", body=body, headers={**headers, "Content-Type": "multipart/form-data; boundary=" + boundary})
        assert status == 201 and len(imported["imported"]) == 1
        status, answer, _ = request(private_base, "/api/chat", method="POST", body=json.dumps({"message": "请查询文档，紫杉项目如何发布？", "knowledge_base_ids": [notebook_id], "session_id": "candidate-smoke"}).encode(), headers=json_headers)
        assert status == 200 and answer["knowledge_base_ids"] == [notebook_id]
        status, trace, _ = request(private_base, "/api/trace/" + answer["trace_id"], headers=headers)
        hits = [hit for span in trace if span["span"] == "rag" for hit in span["meta"].get("hits", [])]
        assert status == 200 and hits and all(hit["source_id"].startswith(notebook_id + "/") for hit in hits)
    print(json.dumps({"admin_smoke": "passed", "candidate_import": write, "media_auth_reachable": True,
                      "provider": model["provider"], "model": model["model"], "quota": model.get("quota")}))


if __name__ == "__main__":
    model_file = sys.argv[sys.argv.index('--model-env-file') + 1] if '--model-env-file' in sys.argv else None
    smoke(sys.argv[1], sys.argv[2], sys.argv[3], write="--write" in sys.argv[4:], model_env_file=model_file)
