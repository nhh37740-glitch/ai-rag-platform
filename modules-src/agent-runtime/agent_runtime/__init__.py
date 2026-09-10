from __future__ import annotations

from typing import Optional, Union

from core_contracts import ChatMessage, RequestContext
from llm_gateway import LLMProvider
from memory import MemoryStore
from observability import ASpan, TraceStore
from rag_core import InMemoryVectorStore, build_context, retrieve
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry

__version__ = "0.1.0"


class AgentRuntime:
    """最薄的 Agent 编排循环：理解→记忆→Skill→RAG/Tool→LLM→执行→再LLM→写记忆。"""

    def __init__(
        self,
        provider: LLMProvider,
        vector_store: InMemoryVectorStore,
        memory: MemoryStore,
        tools: ToolRegistry,
        skills: SkillRegistry,
        tracing: TraceStore,
        kb_scope: str = "kb",
    ) -> None:
        self.provider = provider
        self.vector_store = vector_store
        self.memory = memory
        self.tools = tools
        self.skills = skills
        self.tracing = tracing
        self.kb_scope = kb_scope

    async def run(self, ctx: RequestContext, user_input: str) -> str:
        async with ASpan(ctx, "agent", self.tracing):
            # 1) 记忆
            user_notes = self.memory.search(ctx, "user", user_input, 3)
            sess_notes = self.memory.search(ctx, "session", user_input, 3)
            mem_text = "\n".join("- " + n.content for n in user_notes + sess_notes) or "(无)"

            # 2) Skill
            skill_text = "; ".join(s.description for s in self.skills.list(ctx)) or "(无)"

            # 3) RAG
            result = retrieve(ctx, user_input, self.vector_store, self.kb_scope)
            kb_text = build_context(result)

            system = (
                "你是企业研发助手。可用技能: " + skill_text + "。\n"
                "相关记忆:\n" + mem_text + "\n"
                "知识库资料:\n" + kb_text + "\n"
                "请基于以上内容作答，尽量引用来源；能调用工具就调用工具。"
            )
            messages: list[ChatMessage] = [ChatMessage("system", system), ChatMessage("user", user_input)]
            tools = self.tools.list(ctx)

            for _ in range(5):
                async with ASpan(ctx, "llm", self.tracing):
                    content, calls = await self.provider.generate(ctx, messages, tools)
                if not calls:
                    self.memory.write(ctx, "session", "current_task", user_input, 0.3)
                    self.memory.write(ctx, "user", "last_task", user_input + " -> " + content[:160], 0.6)
                    return content
                messages.append(ChatMessage("assistant", content, tool_calls=calls))
                async with ASpan(ctx, "tool", self.tracing):
                    for call in calls:
                        outcome = self.tools.execute(ctx, call)
                        messages.append(ChatMessage("tool", outcome, tool_call_id=call.id, name=call.name))
            return "(经过多次工具调用仍未得到结论)"


def make_runtime(**kwargs) -> AgentRuntime:
    return AgentRuntime(**kwargs)


__all__ = ["AgentRuntime", "make_runtime"]
