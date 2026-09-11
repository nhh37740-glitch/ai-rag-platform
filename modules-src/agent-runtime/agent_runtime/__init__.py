from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from core_contracts import ChatMessage, RequestContext
from llm_gateway import LLMProvider
from memory import MemoryStore
from observability import ASpan, TraceStore
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry

__version__ = "0.3.0"


class AgentRuntime:
    """Agentic tool loop: memory/history -> full skills -> LLM/tools -> memory."""

    def __init__(
        self,
        provider: LLMProvider,
        memory: MemoryStore,
        tools: ToolRegistry,
        skills: SkillRegistry,
        tracing: TraceStore,
        max_tool_rounds: int = 10,
    ) -> None:
        if max_tool_rounds < 10:
            raise ValueError("max_tool_rounds 不能小于 10")
        self.provider = provider
        self.memory = memory
        self.tools = tools
        self.skills = skills
        self.tracing = tracing
        self.max_tool_rounds = max_tool_rounds
        self._histories: Dict[Tuple[str, str], List[ChatMessage]] = {}
        self._history_lock = threading.Lock()

    def _history(self, ctx: RequestContext) -> List[ChatMessage]:
        key = (ctx.user_id, ctx.session_id)
        with self._history_lock:
            return list(self._histories.get(key, []))

    def _remember_turn(self, ctx: RequestContext, user_input: str, answer: str) -> None:
        key = (ctx.user_id, ctx.session_id)
        with self._history_lock:
            history = self._histories.setdefault(key, [])
            history.extend([ChatMessage("user", user_input), ChatMessage("assistant", answer)])
            if len(history) > 40:
                del history[:-40]
        self.memory.write(ctx, "session", "current_task", user_input, 0.3)
        self.memory.write(ctx, "user", "last_task", user_input + " -> " + answer[:160], 0.6)

    async def run(
        self,
        ctx: RequestContext,
        user_input: str,
        knowledge_base_ids: Optional[List[str]] = None,
    ) -> str:
        async with ASpan(ctx, "agent", self.tracing):
            user_notes = self.memory.search(ctx, "user", user_input, 3)
            session_notes = self.memory.search(ctx, "session", user_input, 3)
            memory_text = "\n".join(
                "- " + note.content for note in user_notes + session_notes
            ) or "(无)"

            skill_text = self.skills.render(ctx, user_input) or "(无匹配技能)"
            selected_knowledge_bases = list(dict.fromkeys(knowledge_base_ids or []))
            system = (
                "你是企业研发知识与协作智能体。\n"
                "对普通闲聊或无需外部知识的问题可直接回答。\n"
                "需要知识库事实时，必须调用 search_knowledge_base；结果不理想时先缩短或改写查询后再次调用。\n"
                "不得把模型常识冒充知识库结论；引用必须来自工具返回的 source_id。\n"
                "只能检索当前对话已选中的知识库，范围由系统注入。\n"
                "只有用户明确要求时，才可创建文件或把对话保存为新知识库。\n"
                "相关记忆:\n" + memory_text + "\n"
                "已加载技能:\n" + skill_text
            )
            messages: List[ChatMessage] = [
                ChatMessage("system", system),
                *self._history(ctx),
                ChatMessage("user", user_input),
            ]
            tool_definitions = self.tools.list(ctx)
            runtime_context = {
                "knowledge_base_ids": selected_knowledge_bases,
                "messages": messages,
                "user_input": user_input,
            }

            for _ in range(self.max_tool_rounds):
                async with ASpan(ctx, "llm", self.tracing):
                    content, calls = await self.provider.generate(
                        ctx, messages, tool_definitions
                    )
                if not calls:
                    self._remember_turn(ctx, user_input, content)
                    return content

                messages.append(ChatMessage("assistant", content, tool_calls=calls))
                async with ASpan(ctx, "tool", self.tracing):
                    for call in calls:
                        outcome = self.tools.execute(ctx, call, runtime_context)
                        messages.append(
                            ChatMessage(
                                "tool",
                                outcome,
                                tool_call_id=call.id,
                                name=call.name,
                            )
                        )

            messages.append(
                ChatMessage(
                    "system",
                    "已达到工具调用轮数上限，请根据已有结果直接给出最终回答，不再调用工具。",
                )
            )
            async with ASpan(ctx, "llm", self.tracing):
                content, _ = await self.provider.generate(ctx, messages, [])
            answer = content or "(工具调用达到上限，未生成最终结论)"
            self._remember_turn(ctx, user_input, answer)
            return answer


def make_runtime(**kwargs) -> AgentRuntime:
    return AgentRuntime(**kwargs)


__all__ = ["AgentRuntime", "make_runtime"]
