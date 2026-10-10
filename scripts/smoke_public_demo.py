"""Exercise the deployed public boundary and a real retrieval trace; no secrets logged."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote


def request(base, path, method="GET", payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + "/" + path.lstrip("/"), data=data,
                                 method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=100) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        return error.code, None


def smoke(base, expected_provider="deepseek"):
    assert expected_provider in ("mock", "deepseek")
    status, demo = request(base, "api/demo")
    assert status == 200 and demo["public_demo"] and demo["read_only"]
    assert demo["provider"] == expected_provider, "provider must match the explicit release mode"
    assert demo["embedding"] == "hash", "hash baseline must be labeled honestly"
    question = demo["suggested_questions"][0]["question"]
    for path in ("api/chat", "api/notebooks", "api/files", "api/evaluate"):
        assert request(base, path, "POST", {})[0] in (403, 405), path
    assert request(base, "api/demo/chat", "POST", {"question": question, "user_id": "private"})[0] == 422
    assert request(base, "api/demo/chat", "POST", {"question": " "})[0] == 422
    status, session = request(base, "api/auth/session")
    assert status == 200 and session["role"] == "guest" and session["permissions"] == ["read", "query"]
    assert "proof" not in session and session["allowed_notebook_ids"] == ["cmrc2018-demo"]
    status, notebooks = request(base, "api/notebooks")
    assert status == 200 and [item["id"] for item in notebooks["notebooks"]] == ["cmrc2018-demo"]
    status, documents = request(base, "api/notebooks/cmrc2018-demo/documents")
    assert status == 200 and documents["documents"]
    document_id = documents["documents"][0]["source_id"].split("/", 1)[1]
    status, document = request(base, "api/demo/documents/" + quote(document_id, safe=""))
    assert status == 200 and document["contexts"] and len(document["contexts"]) <= 20
    assert document["source_id"].startswith("cmrc2018-demo/")
    assert request(base, "api/notebooks/private/documents")[0] == 403
    assert request(base, "api/demo/chat", "POST", {"question": question}, {"x-deepseek-api-key": "blocked-test-value"})[0] == 403
    status, unknown = request(base, "api/trace/private-unknown")
    assert status == 200 and unknown == []
    status, result = request(base, "api/demo/chat", "POST", {"question": question})
    assert status == 200, f"curated model request failed with HTTP {status}"
    assert result["provider"] == expected_provider and result["read_only"] and result["answer"]
    assert result["knowledge_base_ids"] == ["cmrc2018-demo"]
    status, trace = request(base, "api/trace/" + result["trace_id"])
    assert status == 200 and trace, "answer must have an actual trace"
    retrievals = [event for event in trace if event["span"] == "rag" and event["status"] == "ok"]
    assert retrievals, "answer must include successful retrieval"
    assert any(event["meta"].get("hit_count", 0) > 0 and event["meta"].get("knowledge_base_ids") == ["cmrc2018-demo"] for event in retrievals)
    status, free = request(base, "api/demo/chat", "POST", {"question": "请查询公开文档，什么是静电感应？"})
    assert status == 200 and free["cache_hit"] is False and free["knowledge_base_ids"] == ["cmrc2018-demo"]
    print(json.dumps({"public_smoke": "passed", "provider": result["provider"],
                      "embedding": result["embedding"], "trace_id": result["trace_id"],
                      "spans": len(trace), "cache_hit": result.get("cache_hit", False)}, ensure_ascii=False))


if __name__ == "__main__":
    smoke(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "deepseek")
