"""Select an LLM provider for one chat request without changing shared runtime state."""

from contextlib import contextmanager
from contextvars import ContextVar

from agent_facade import make_provider


class RequestScopedProvider:
    def __init__(self, default_provider, base_url: str, model: str) -> None:
        self._default = default_provider
        self._base_url = base_url
        self._model = model
        self._current = ContextVar("request_llm_provider", default=None)

    @contextmanager
    def use_key(self, api_key: str | None):
        provider = make_provider(api_key, self._base_url, self._model) if api_key else None
        token = self._current.set(provider)
        try:
            yield
        finally:
            self._current.reset(token)

    def _provider(self):
        return self._current.get() or self._default

    def for_request(self, default_provider=None):
        """Bind only this request's override to an ephemeral Agent."""
        return self if self._current.get() is not None or default_provider is self._default or default_provider is None else default_provider

    async def generate(self, ctx, messages, tools=None):
        try:
            return await self._provider().generate(ctx, messages, tools)
        except Exception:
            # Provider/network exceptions can contain request or credential data.
            # Raise only a fixed message before the Agent records an error span.
            if self._current.get() is not None:
                raise RuntimeError("临时模型请求失败") from None
            raise RuntimeError("服务端模型请求失败") from None

    async def stream(self, ctx, messages, tools=None):
        try:
            async for chunk in self._provider().stream(ctx, messages, tools):
                yield chunk
        except Exception:
            if self._current.get() is not None:
                raise RuntimeError("临时模型请求失败") from None
            raise RuntimeError("服务端模型请求失败") from None
