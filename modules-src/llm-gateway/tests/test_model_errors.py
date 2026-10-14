import asyncio
import json
import httpx
import pytest
from core_specifications import ChatMessage, ModelRequestError, RequestContext
from llm_gateway import DeepSeekProvider


@pytest.mark.parametrize("status,body,code", [
    (429, {"error": "credential-must-not-leak"}, "model_rate_limited"),
    (400, {"error": "tools unsupported"}, "model_unavailable"),
    (503, "provider not available", "model_unavailable"),
    (200, "not JSON", "model_invalid_response"),
    (200, {"choices": []}, "model_invalid_response"),
    (200, {"choices": [{"message": {"content": None}}]}, "model_invalid_response"),
    (200, {"choices": [{"message": {"tool_calls": [{"function": {"name": "search", "arguments": "[]"}}]}}]}, "model_invalid_response"),
])
def test_model_errors_are_stable_and_do_not_expose_upstream_body(status, body, code):
    def handler(request):
        return httpx.Response(status, content=body if isinstance(body, str) else json.dumps(body))
    provider = DeepSeekProvider("credential-must-not-leak", transport=httpx.MockTransport(handler))
    with pytest.raises(ModelRequestError) as error:
        asyncio.run(provider.generate(RequestContext("t", "r"), [ChatMessage("user", "question")]))
    assert error.value.code == code
    assert "credential-must-not-leak" not in str(error.value)


def test_model_timeout_is_distinct_from_invalid_json():
    def handler(request):
        raise httpx.ReadTimeout("private endpoint detail", request=request)
    provider = DeepSeekProvider("unused", transport=httpx.MockTransport(handler))
    with pytest.raises(ModelRequestError) as error:
        asyncio.run(provider.generate(RequestContext("t", "r"), [ChatMessage("user", "question")]))
    assert error.value.code == "model_timeout"
    assert error.value.status_code == 504
