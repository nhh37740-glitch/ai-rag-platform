from __future__ import annotations

import re
import json
import os
import threading
import time
from urllib.request import Request, urlopen
from copy import deepcopy
from typing import Callable

from agent_runtime import AgentRuntime, RETRIEVAL_TOOL_NAMES
from core_specifications import (
    ChatMessage,
    DataServicePort,
    LLMProviderPort,
    ModelConfiguration,
    RagServicePort,
    RequestContext,
    ToolCall,
    ToolDef,
    TraceStorePort,
)
from llm_gateway import DeepSeekProvider, MockProvider
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry

__version__ = "0.5.0"


def resolve_model_config(ctx: RequestContext, environment: dict[str, str], public: bool = False) -> ModelConfiguration:
    """Resolve deployment settings and enforce the OpenRouter free-only policy."""
    env = environment
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
        return ModelConfiguration(selected, key, "https://openrouter.ai/api/v1", model)
    if selected not in {"mock", "deepseek"}:
        raise ValueError("LLM_PROVIDER 必须为 mock、deepseek 或 openrouter")
    key = env.get("DEEPSEEK_API_KEY", "").strip() if selected == "deepseek" else ""
    if selected == "deepseek" and not key:
        raise ValueError("DeepSeek 缺少服务端凭据")
    return ModelConfiguration(selected, key, env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
               env.get("DEEPSEEK_MODEL", "deepseek-chat"))


def make_provider(
    api_key: str = "",
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    scenario: str = "qa",
) -> LLMProviderPort:
    """Choose the existing gateway implementation without retaining credentials here."""
    if api_key:
        return DeepSeekProvider(api_key=api_key, base_url=base_url, model=model)
    return MockProvider(scenario=scenario)


class AgentService:
    """Own Agent runtimes while consuming other domains through shared ports."""

    def __init__(
        self,
        data: DataServicePort,
        rag: RagServicePort,
        tracing: TraceStorePort | None = None,
        skill_dir: str = "",
        provider: LLMProviderPort | None = None,
        max_tool_rounds: int = 10,
        environment: dict[str, str] | None = None,
    ) -> None:
        if max_tool_rounds < 10:
            raise ValueError("max_tool_rounds 不能小于 10")
        self._closed = False
        self._lock = threading.RLock()
        self._data = data
        self._environment = dict(os.environ if environment is None else environment)
        self._catalog_cache: dict[str, tuple[float, list[dict]]] = {}
        self._tracing = tracing if tracing is not None else rag
        self._max_tool_rounds = max_tool_rounds
        self._provider = provider if provider is not None else make_provider()
        self._rag = rag
        self._tools = ToolRegistry()
        self._skills = SkillRegistry()
        if skill_dir:
            self._skills.load_dir(skill_dir)
        assembly_context = RequestContext("agent-initialize", "agent-initialize")
        definitions = rag.tool_definitions(assembly_context)
        if {definition.name for definition in definitions} != RETRIEVAL_TOOL_NAMES:
            raise ValueError("RAG must expose exactly the five reserved knowledge tools")
        for definition in definitions:
            self._tools.register(
                deepcopy(definition), self._rag_handler(definition.name), context_aware=True
            )
        data.initialize(assembly_context)
        self._memory = data.memory_store(assembly_context)
        self._runtime = self._make_runtime(self._provider)
        self._load_saved_settings(assembly_context)

    def _make_runtime(self, provider):
        runtime = AgentRuntime(provider, self._memory, self._tools, self._skills, self._tracing, self._max_tool_rounds)
        old = getattr(self, "_runtime", None)
        if old is not None:
            runtime._histories = old._histories
            runtime._history_lock = old._history_lock
        return runtime

    def _catalog(self, env, provider_id):
        if provider_id == "mock":
            return [{"id": "mock", "name": "Mock（离线）"}]
        if provider_id == "deepseek":
            if not env.get("DEEPSEEK_API_KEY", "").strip():
                raise ValueError("DeepSeek 未配置服务器凭据")
            choices = env.get("DEEPSEEK_MODELS", env.get("DEEPSEEK_MODEL", "deepseek-chat"))
            return [{"id": x, "name": x} for x in dict.fromkeys(v.strip() for v in choices.split(",") if v.strip())]
        if provider_id != "openrouter":
            raise ValueError("未知 Provider")
        key = env.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ValueError("OpenRouter 未配置服务器凭据")
        raw = env.get("OPENROUTER_MODELS", "").strip()
        if raw:
            try:
                items = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("OPENROUTER_MODELS 必须是 JSON 数组") from exc
        else:
            cached = self._catalog_cache.get(provider_id)
            if cached and cached[0] > time.monotonic():
                return deepcopy(cached[1])
            req = Request("https://openrouter.ai/api/v1/models", headers={"Authorization": "Bearer " + key})
            try:
                with urlopen(req, timeout=8) as response:
                    items = json.loads(response.read().decode("utf-8")).get("data", [])
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("暂时无法读取 OpenRouter 当前模型目录") from exc
        if not isinstance(items, list):
            raise ValueError("OpenRouter 模型目录格式无效")
        result = [{"id": "openrouter/free", "name": "OpenRouter Free（自动选择免费模型）"}]
        seen = {"openrouter/free"}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            mid, price = item["id"], item.get("pricing", {})
            zero = isinstance(price, dict) and str(price.get("prompt")) in {"0", "0.0", "0.000000"} and str(price.get("completion")) in {"0", "0.0", "0.000000"}
            if (mid.endswith(":free") or zero) and mid not in seen:
                seen.add(mid)
                result.append({"id": mid, "name": item.get("name") or mid})
        if not raw:
            self._catalog_cache[provider_id] = (time.monotonic() + 15, deepcopy(result))
        return result

    def _build_provider(self, provider_id, model_id, validate_catalog=True):
        env = self._environment
        if validate_catalog and model_id not in {item["id"] for item in self._catalog(env, provider_id)}:
            raise ValueError("该模型不在 Provider 当前可选目录中")
        if provider_id == "mock":
            return make_provider(model=model_id)
        if provider_id == "deepseek":
            return make_provider(env["DEEPSEEK_API_KEY"].strip(), env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"), model_id)
        if provider_id == "openrouter":
            return make_provider(env["OPENROUTER_API_KEY"].strip(), "https://openrouter.ai/api/v1", model_id)
        raise ValueError("未知 Provider")

    def _load_saved_settings(self, ctx):
        saved = self._data.get_agent_data(ctx, "model_settings", "active")
        if saved:
            try:
                value = json.loads(saved["content"])
                provider = self._build_provider(value["provider_id"], value["model_id"], validate_catalog=False)
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("保存的模型设置格式无效") from exc
            self._provider = provider
            self._runtime = self._make_runtime(provider)

    def list_model_providers(self, ctx: RequestContext, environment: dict[str, str]) -> list[dict]:
        self._ensure_open()
        return [{"id":"mock","name":"Mock（离线）","configured":True},
                {"id":"deepseek","name":"DeepSeek","configured":bool(environment.get("DEEPSEEK_API_KEY","").strip())},
                {"id":"openrouter","name":"OpenRouter（仅免费模型）","configured":bool(environment.get("OPENROUTER_API_KEY","").strip())}]

    def list_models(self, ctx: RequestContext, provider_id: str, environment: dict[str, str]) -> list[dict]:
        self._ensure_open()
        return self._catalog(environment, provider_id)

    def get_model_settings(self, ctx: RequestContext) -> dict:
        self._ensure_open()
        saved = self._data.get_agent_data(ctx, "model_settings", "active")
        if saved:
            value = json.loads(saved["content"])
            provider_id, model_id = value["provider_id"], value["model_id"]
        else:
            config = resolve_model_config(ctx, self._environment)
            provider_id, model_id = config.provider, config.model
        keyname = {"deepseek":"DEEPSEEK_API_KEY","openrouter":"OPENROUTER_API_KEY"}.get(provider_id)
        return {"provider_id":provider_id,"model_id":model_id,
                "server_key_configured":provider_id=="mock" or bool(keyname and self._environment.get(keyname,"").strip()),
                "free_models_only":provider_id=="openrouter"}

    def update_model_settings(self, ctx: RequestContext, provider_id: str, model_id: str) -> dict:
        self._ensure_open()
        if not isinstance(provider_id,str) or not isinstance(model_id,str):
            raise TypeError("provider_id 和 model_id 必须为字符串")
        new_provider = self._build_provider(provider_id, model_id)
        with self._lock:
            self._ensure_open()
            encoded = json.dumps({"provider_id":provider_id,"model_id":model_id},ensure_ascii=False,sort_keys=True)
            self._data.set_agent_data(ctx,"model_settings","active",encoded)
            self._provider = new_provider
            self._runtime = self._make_runtime(new_provider)
        return self.get_model_settings(ctx)

    @property
    def provider(self) -> LLMProviderPort:
        return self._provider

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("AgentService is closed")

    def _rag_handler(self, name: str) -> Callable:
        def execute(*, ctx: RequestContext, runtime_context: dict | None, **arguments) -> str:
            # ToolRegistry injects ctx and runtime_context after reading model args.
            # Scope comes exclusively from this run, never from model arguments.
            selected_scope = list((runtime_context or {}).get("knowledge_base_ids") or [])
            arguments.pop("knowledge_base_ids", None)
            arguments.pop("ctx", None)
            arguments.pop("runtime_context", None)
            return self._rag.execute_tool(ctx, ToolCall("", name, arguments), selected_scope)

        return execute

    async def run(
        self,
        ctx: RequestContext,
        user_input: str,
        knowledge_base_ids: list[str] | None = None,
        allow_write_tools: bool = True,
        model_id: str | None = None,
        expected_provider_id: str | None = None,
    ) -> str:
        with self._lock:
            self._ensure_open()
            runtime = self._runtime
            if model_id is None:
                if expected_provider_id is not None:
                    raise ValueError("expected_provider_id requires model_id")
            else:
                if not isinstance(model_id, str) or not model_id.strip():
                    raise ValueError("model_id must be a non-empty string")
                settings = self.get_model_settings(ctx)
                provider_id = settings["provider_id"]
                if expected_provider_id is not None and expected_provider_id != provider_id:
                    raise ValueError("当前 Provider 已切换，请重新选择模型")
                runtime = self._make_runtime(self._build_provider(provider_id, model_id))
        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        if not user_input.strip():
            raise ValueError("user_input must not be empty")
        return await runtime.run(ctx, user_input, knowledge_base_ids, allow_write_tools)

    def register_tool(
        self,
        ctx: RequestContext,
        definition: ToolDef,
        handler: Callable,
        context_aware: bool = False,
    ) -> None:
        self._ensure_open()
        if definition.name in RETRIEVAL_TOOL_NAMES:
            raise ValueError("Reserved RAG tools cannot be replaced")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._tools.register(deepcopy(definition), handler, context_aware=context_aware)

    def tool_definitions(self, ctx: RequestContext) -> list[ToolDef]:
        self._ensure_open()
        return deepcopy(self._tools.list(ctx))

    def history(self, ctx: RequestContext) -> list[ChatMessage]:
        self._ensure_open()
        return self._runtime.history(ctx)

    async def aclose(self, ctx: RequestContext) -> None:
        if self._closed:
            return
        self._closed = True
        # Runtimes and registries own only in-memory state. Drop those references;
        # data, rag, tracing and the provider belong to the injecting application.
        self._runtime = None
        self._tools = None
        self._skills = None
        self._rag = None


__all__ = ["resolve_model_config", "AgentService", "make_provider"]
