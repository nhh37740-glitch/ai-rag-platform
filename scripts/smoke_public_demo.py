"""Check the public RAGnotebook guest boundary and one retrieval trace."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def request(base, path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + "/" + path.lstrip("/"), data=data,
                                 method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=100) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        return error.code, None


def smoke(base, expected_provider="openrouter", *, metadata_only=False):
    assert expected_provider in ("mock", "deepseek", "openrouter")
    status, demo = request(base, "api/demo")
    assert status == 200 and demo["public_demo"] and demo["read_only"]
    assert demo["provider"] == expected_provider
    assert demo["embedding"] == "hash"
    quota = demo["quota"]
    assert quota["scope"] == "site" and quota["limit"] == 100
    assert 0 <= quota["used"] <= 100 and quota["remaining"] == 100 - quota["used"]

    status, session = request(base, "api/auth/session")
    assert status == 200 and session["role"] == "guest"
    assert session["permissions"] == ["read", "query"]
    assert session["allowed_notebook_ids"] == ["cmrc2018-demo"]
    assert request(base, "api/auth/register", "POST", {})[0] == 403
    assert request(base, "api/auth/login", "POST", {})[0] == 403

    status, notebooks = request(base, "api/notebooks")
    assert status == 200 and [item["id"] for item in notebooks["notebooks"]] == ["cmrc2018-demo"]
    status, documents = request(base, "api/notebooks/cmrc2018-demo/documents")
    assert status == 200 and documents["documents"]
    assert request(base, "api/notebooks/private/documents")[0] == 403
    assert request(base, "api/trace/private-unknown")[0] == 404
    assert request(base, "api/chat", "POST", {"message": " "})[0] == 422

    status, config = request(base, "api/llm/config")
    assert status == 200 and config["provider"] == expected_provider
    if expected_provider == "openrouter":
        assert config["model"] == "openrouter/free" and config["free_models_only"]

    if metadata_only:
        print(json.dumps({"public_smoke": "passed", "provider": expected_provider,
                          "metadata_only": True, "quota": quota}, ensure_ascii=False))
        return

    question = demo["suggested_questions"][0]["question"]
    status, result = request(base, "api/chat", "POST", {
        "message": question, "knowledge_base_ids": ["cmrc2018-demo"],
    })
    assert status == 200 and result["answer"], f"guest chat failed with HTTP {status}"
    assert result["knowledge_base_ids"] == ["cmrc2018-demo"]
    assert result["conversation_id"] is None
    status, trace = request(base, "api/trace/" + result["trace_id"])
    assert status == 200 and trace
    retrievals = [event for event in trace if event["span"] == "rag" and event["status"] == "ok"]
    assert retrievals and any(event["meta"].get("hit_count", 0) > 0 for event in retrievals)
    print(json.dumps({"public_smoke": "passed", "provider": expected_provider,
                      "trace_id": result["trace_id"], "spans": len(trace),
                      "quota": result.get("quota")}, ensure_ascii=False))


if __name__ == "__main__":
    smoke(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "openrouter",
          metadata_only="--metadata-only" in sys.argv[3:])
