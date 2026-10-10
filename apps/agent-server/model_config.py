"""Read server LLM settings; no browser or log may receive credentials."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    api_key: str = field(repr=False)
    base_url: str
    model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str], public: bool = False):
        selected = env.get("LLM_PROVIDER", "").strip().lower()
        if not selected:
            selected = "openrouter" if env.get("OPENROUTER_API_KEY", "").strip() else (
                env.get("DEMO_PROVIDER", "mock").strip().lower() if public else
                "deepseek" if env.get("DEEPSEEK_API_KEY", "").strip() else "mock"
            )
        if selected == "openrouter":
            key = env.get("OPENROUTER_API_KEY", "").strip()
            model = env.get("OPENROUTER_MODEL", "openrouter/free").strip()
            if not key:
                raise ValueError("OpenRouter 缺少服务端凭据")
            if model != "openrouter/free" and re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:free", model) is None:
                raise ValueError("OpenRouter 仅允许免费模型")
            return cls(selected, key, "https://openrouter.ai/api/v1", model)
        if selected not in {"mock", "deepseek"}:
            raise ValueError("LLM_PROVIDER 必须为 mock、deepseek 或 openrouter")
        key = env.get("DEEPSEEK_API_KEY", "").strip() if selected == "deepseek" else ""
        if selected == "deepseek" and not key:
            raise ValueError("DeepSeek 缺少服务端凭据")
        return cls(selected, key, env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                   env.get("DEEPSEEK_MODEL", "deepseek-chat"))
