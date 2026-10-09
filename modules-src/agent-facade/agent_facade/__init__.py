from __future__ import annotations

from copy import deepcopy
from typing import Callable

from agent_runtime import AgentRuntime, RETRIEVAL_TOOL_NAMES
from core_specifications import (
    ChatMessage,
    DataServicePort,
    LLMProviderPort,
    RagServicePort,
    RequestContext,
    ToolCall,
    ToolDef,
    TraceStorePort,
)
from llm_gateway import DeepSeekProvider, MockProvider
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry

__version__ = "0.1.0"


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
        tracing: TraceStorePort,
        skill_dir: str = "",
        provider: LLMProviderPort | None = None,
        max_tool_rounds: int = 10,
    ) -> None:
        if max_tool_rounds < 10:
            raise ValueError("max_tool_rounds 不能小于 10")
        self._closed = False
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
        self._runtime = AgentRuntime(
            provider=self._provider,
            memory=data.memory_store(assembly_context),
            tools=self._tools,
            skills=self._skills,
            tracing=tracing,
            max_tool_rounds=max_tool_rounds,
        )

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
    ) -> str:
        self._ensure_open()
        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        if not user_input.strip():
            raise ValueError("user_input must not be empty")
        return await self._runtime.run(ctx, user_input, knowledge_base_ids)

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


__all__ = ["AgentService", "make_provider"]
