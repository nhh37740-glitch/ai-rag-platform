from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from request_provider import RequestScopedProvider  # noqa: E402


class FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    async def generate(self, ctx, messages, tools=None):
        await asyncio.sleep(0)
        return self.name, []

    async def stream(self, ctx, messages, tools=None):
        yield self.name


class RequestScopedProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_override_is_isolated_across_concurrent_requests_and_restored(self) -> None:
        scoped = RequestScopedProvider(FakeProvider("server-default"), "https://example.invalid", "model")
        with patch("request_provider.make_provider", side_effect=lambda key, base, model: FakeProvider(key)):
            async def run_with_key(key: str):
                with scoped.use_key(key):
                    await asyncio.sleep(0)
                    return await scoped.generate(None, [])

            first, second = await asyncio.gather(run_with_key("first"), run_with_key("second"))
            self.assertEqual(first[0], "first")
            self.assertEqual(second[0], "second")
            self.assertEqual((await scoped.generate(None, []))[0], "server-default")

    async def test_exception_restores_default(self) -> None:
        scoped = RequestScopedProvider(FakeProvider("server-default"), "https://example.invalid", "model")
        with patch("request_provider.make_provider", return_value=FakeProvider("browser")):
            with self.assertRaisesRegex(ValueError, "failure"):
                with scoped.use_key("placeholder"):
                    raise ValueError("failure")
        self.assertEqual((await scoped.generate(None, []))[0], "server-default")
