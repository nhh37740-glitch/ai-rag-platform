"""Select an LLM provider for one chat request without changing shared runtime state."""

from contextlib import contextmanager
from contextvars import ContextVar

from llm_gateway import DeepSeekProvider


class RequestScopedProvider:
    def __init__(self, default_provider, base_url: str, model: str) -> None:
        self._default = default_provider
        self._base_url = base_url
        self._model = model
        self._current = ContextVar("request_llm_provider", default=None)

    @contextmanager
    def use_key(self, api_key: str | None):
        provider = DeepSeekProvider(api_key, self._base_url, self._model) if api_key else None
        token = self._current.set(provider)
        try:
            yield
        finally:
            self._current.reset(token)

    def _provider(self):
        return self._current.get() or self._default

    async def generate(self, ctx, messages, tools=None):
        return await self._provider().generate(ctx, messages, tools)

    async def stream(self, ctx, messages, tools=None):
        async for chunk in self._provider().stream(ctx, messages, tools):
            yield chunk
