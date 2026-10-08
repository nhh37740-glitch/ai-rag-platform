"""Exercise the deployed public boundary and a real retrieval trace; no secrets logged."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


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


def smoke(base):
    status, demo = request(base, "api/demo")
    assert status == 200 and demo["public_demo"] and demo["read_only"]
    assert demo["provider"] == "deepseek", "public release must use configured real provider"
    assert demo["embedding"] == "hash", "hash baseline must be labeled honestly"
    question = demo["suggested_questions"][0]["question"]
    for path in ("api/chat", "api/notebooks", "api/files", "api/evaluate"):
        assert request(base, path, "POST", {})[0] in (403, 405), path
    assert request(base, "api/demo/chat", "POST", {"question": question, "user_id": "private"})[0] == 422
    assert request(base, "api/demo/chat", "POST", {"question": "arbitrary private question"})[0] == 422
    assert request(base, "api/demo/chat", "POST", {"question": question}, {"x-deepseek-api-key": "blocked-test-value"})[0] == 403
    status, unknown = request(base, "api/trace/private-unknown")
    assert status == 200 and unknown == []
    status, result = request(base, "api/demo/chat", "POST", {"question": question})
    assert status == 200, f"curated model request failed with HTTP {status}"
    assert result["provider"] == "deepseek" and result["read_only"] and result["answer"]
    assert result["knowledge_base_ids"] == ["cmrc2018-demo"]
    status, trace = request(base, "api/trace/" + result["trace_id"])
    assert status == 200 and trace, "answer must have an actual trace"
    retrievals = [event for event in trace if event["span"] == "rag" and event["status"] == "ok"]
    assert retrievals, "answer must include successful retrieval"
    assert any(event["meta"].get("hit_count", 0) > 0 and event["meta"].get("knowledge_base_ids") == ["cmrc2018-demo"] for event in retrievals)
    print(json.dumps({"public_smoke": "passed", "provider": result["provider"],
                      "embedding": result["embedding"], "trace_id": result["trace_id"],
                      "spans": len(trace), "cache_hit": result.get("cache_hit", False)}, ensure_ascii=False))


if __name__ == "__main__":
    smoke(sys.argv[1])
