#!/usr/bin/env python3
"""Regression evidence for model-provider error handling.

Part 1 runs deterministic fake HTTP responses through the real provider and
records the stable error code. Part 2 performs a controlled real OpenRouter
check only when ``OPENROUTER_API_KEY`` is present; it records the HTTP result
and never prints or writes the key.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

import httpx

from core_specifications import ChatMessage, ModelRequestError, RequestContext
from llm_gateway import DeepSeekProvider

SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._-]+)", re.IGNORECASE)


def _sanitize(text: str) -> str:
    return SECRET_RE.sub("<redacted>", text)[:300]


def _code_for_status(status: int) -> str:
    if status in (401, 403):
        return "model_auth_failed"
    if status == 402:
        return "model_quota_exhausted"
    if status == 404:
        return "model_not_found"
    if status in (400, 422):
        return "model_request_rejected"
    if status == 429:
        return "model_rate_limited"
    return "model_unavailable"


async def _simulated() -> list[dict]:
    cases = [
        (401, "invalid key"),
        (402, "insufficient credits"),
        (404, "model not found"),
        (400, "tools unsupported"),
        (429, "rate limited"),
        (503, "provider down"),
    ]
    rows = []
    for status, body in cases:
        def handler(request, status=status, body=body):
            return httpx.Response(status, json={"error": {"message": body}})
        provider = DeepSeekProvider("test-secret-must-not-leak", transport=httpx.MockTransport(handler))
        started = time.perf_counter()
        try:
            await provider.generate(RequestContext("error-check", "request"), [ChatMessage("user", "q")])
            row = {"status": status, "code": "none", "message": ""}
        except ModelRequestError as exc:
            row = {"status": status, "code": exc.code, "message": _sanitize(str(exc))}
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        rows.append(row)

    def timeout_handler(request):
        raise httpx.ReadTimeout("private detail", request=request)
    provider = DeepSeekProvider("test-secret-must-not-leak", transport=httpx.MockTransport(timeout_handler))
    started = time.perf_counter()
    try:
        await provider.generate(RequestContext("error-check", "request"), [ChatMessage("user", "q")])
        timeout_row = {"status": "timeout", "code": "none", "message": ""}
    except ModelRequestError as exc:
        timeout_row = {"status": "timeout", "code": exc.code, "message": _sanitize(str(exc))}
    timeout_row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    rows.append(timeout_row)
    return rows


def _real_openrouter() -> Dict[str, Any]:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {"status": "skipped", "reason": "OPENROUTER_API_KEY not set"}
    started = time.perf_counter()
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": "Bearer " + key, "User-Agent": "ai-rag-error-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {
                "status": "ok",
                "http_status": response.status,
                "key_label": body.get("data", {}).get("label", ""),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
    except urllib.error.HTTPError as exc:
        detail = _sanitize(exc.read().decode("utf-8", errors="replace"))
        return {
            "status": "error",
            "http_status": exc.code,
            "code": _code_for_status(exc.code),
            "detail": detail,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    except Exception as exc:  # noqa: BLE001 - network failures are evidence too
        return {
            "status": "error",
            "code": "model_connection_failed",
            "detail": type(exc).__name__,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="experiments/results/llm-error-regression.json")
    args = parser.parse_args()
    result = {
        "simulated": asyncio.run(_simulated()),
        "real_openrouter": _real_openrouter(),
        "note": "simulated 使用假 HTTP 响应验证错误码；real_openrouter 是真实请求，只记录脱敏结果。",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "real_status": result["real_openrouter"].get("status")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
