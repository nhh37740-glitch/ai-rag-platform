#!/usr/bin/env python3
"""Call the running RAG service and print answer, evidence and trace.

Example (server-side, against the private container):

    python scripts/demo_rag_evidence.py --base-url http://127.0.0.1:18080 \
        --question "请查资料，什么是静电感应？"

The script prints retrieval hits separately from the generated answer so a
reader can tell "no evidence found" from "evidence found but answer wrong".
It never reads or prints model credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _request(url: str, *, body: Dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    parsed = urllib.parse.urlsplit(url)
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Origin": f"{parsed.scheme}://{parsed.netloc}",
        },
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_detail = json.loads(detail)
        except ValueError:
            parsed_detail = {}
        return {"_http_error": exc.code, "_detail": parsed_detail, "_raw": detail}


def _rag_hits(trace: List[dict]) -> List[dict]:
    hits: List[dict] = []
    for event in trace:
        if event.get("span") != "rag":
            continue
        meta = event.get("meta") or {}
        for hit in meta.get("hits") or []:
            hits.append(
                {
                    "tool": meta.get("tool", ""),
                    "query": meta.get("query", ""),
                    "source_id": hit.get("source_id", ""),
                    "title": hit.get("title", ""),
                    "score": hit.get("score"),
                    "preview": (hit.get("text_preview") or hit.get("text") or hit.get("preview") or "")[:200],
                }
            )
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--question", default="请查资料，什么是静电感应？")
    parser.add_argument("--kb", default="cmrc2018-demo")
    parser.add_argument("--user-id", default="demo-reader")
    parser.add_argument("--session-id", default="demo-session")
    parser.add_argument("--output", default="", help="optional JSON result path")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    demo = _request(base + "/api/demo")
    print("== 服务 ==")
    print(json.dumps(
        {
            "provider": demo.get("provider"),
            "model": demo.get("model"),
            "embedding": demo.get("embedding"),
            "kb": demo.get("id", args.kb),
        },
        ensure_ascii=False,
        indent=2,
    ))

    reply = _request(
        base + "/api/chat",
        body={
            "user_id": args.user_id,
            "session_id": args.session_id,
            "message": args.question,
            "knowledge_base_ids": [args.kb],
        },
    )
    error = reply.get("_http_error")
    error_detail = reply.get("_detail") or {}
    trace_id = reply.get("trace_id") or error_detail.get("trace_id", "")
    trace = _request(base + "/api/trace/" + trace_id) if trace_id else []
    if isinstance(trace, dict) and trace.get("_http_error"):
        trace = []
    hits = _rag_hits(trace)
    stops = [event for event in trace if event.get("span") == "agent_stop"]
    print("\n== 问题 ==")
    print(args.question)
    print("\n== 检索命中 ==")
    if hits:
        for index, hit in enumerate(hits, start=1):
            print(f"[{index}] {hit['source_id']} score={hit['score']} tool={hit['tool']}")
            print("    " + hit["preview"].replace("\n", " "))
    else:
        print("(没有命中；这是检索失败，不是生成失败)")
    print("\n== 回答 ==")
    if error:
        print(f"生成失败：HTTP {error} {json.dumps(error_detail, ensure_ascii=False)}")
        print("检索命中已经单独列出；请区分“没找到证据”和“找到证据但模型调用失败”。")
    else:
        print(reply.get("answer", ""))
    stop_reasons = [event.get("meta", {}) for event in stops]
    quota = reply.get("quota") or error_detail.get("quota") or {}
    print("\n== 停止原因 ==")
    print(json.dumps(stop_reasons, ensure_ascii=False))
    print("\n== 额度 ==")
    print(json.dumps(quota, ensure_ascii=False))
    if demo.get("provider") == "mock":
        print("\n注意：当前是 Mock 生成，以上只能证明检索链路和引用字段；不能作为自然语言答案质量证据。")
    if args.output:
        result = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "base_url": base,
            "service": {
                "version": demo.get("version"),
                "provider": demo.get("provider"),
                "model": demo.get("model"),
                "embedding": demo.get("embedding"),
                "knowledge_base": demo.get("id", args.kb),
            },
            "question": args.question,
            "retrieval_hits": hits,
            "answer": reply.get("answer", ""),
            "http_error": error,
            "error_detail": error_detail,
            "stop_reasons": stop_reasons,
            "quota": quota,
            "mock": demo.get("provider") == "mock",
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n结果已写入 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
