from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

from core_contracts import ChatMessage, RequestContext, SpanEvent
from llm_gateway import LLMProvider
from memory import MemoryStore
from observability import ASpan, TraceStore
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry

__version__ = "0.3.3"

RETRIEVAL_TOOL_NAMES = frozenset(
    {
        "search_knowledge_base",
        "keyword_search_knowledge_base",
        "hybrid_search_knowledge_base",
        "list_knowledge_documents",
        "read_knowledge_document",
    }
)

SKIPPED_RETRIEVAL_MESSAGE = (
    "SKIPPED: 同一轮只执行一次知识库检索；请先阅读已返回的结果，再决定是否需要下一次检索。"
)

MAX_RETRIEVAL_REMINDERS = 2

RETRIEVAL_REQUIRED_MESSAGE = (
    "本轮还没有执行任何知识库检索。当前对话已选择知识库，规则要求每个问题至少检索一次："
    "请先调用 search_knowledge_base，必要时再按回退顺序换用其他检索工具，然后基于返回结果作答。"
    "在完成检索之前，不得断言知识库中有什么或没有什么，不得输出 [n] 引用标注，"
    "也不得复用历史对话里的引用。"
)


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

    def _record_retrieval_reminder(
        self,
        ctx: RequestContext,
        attempt: int,
        knowledge_base_ids: List[str],
    ) -> None:
        """记录一次'未检索就想收尾'的拦截，便于在 trace 里发现这类回答。"""
        now = time.perf_counter_ns()
        self.tracing.record(
            SpanEvent(
                trace_id=ctx.trace_id,
                span="retrieval_guard",
                start_ns=now,
                end_ns=now,
                status="ok",
                error="",
                meta={
                    "attempt": attempt,
                    "knowledge_base_ids": list(knowledge_base_ids),
                },
            )
        )

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
            knowledge_base_state = (
                "已选择: " + ", ".join(selected_knowledge_bases)
                if selected_knowledge_bases
                else "未选择"
            )
            system = (
                "你是企业研发知识与协作智能体。\n"
                "当前知识库状态: " + knowledge_base_state + "。\n"
                "只要当前已选择至少一个知识库，每一个问题都必须至少调用一次 search_knowledge_base：闲聊、翻译、改写、计算、创作、玩笑、商品询价，以及你确信自己知道答案的问题，一律先检索再作答。问题看上去与知识库无关也必须先检索，因为“无关”这个判断本身就要用检索结果来证明。\n"
                "检索工具共五个：search_knowledge_base（向量语义）、hybrid_search_knowledge_base（向量+关键词融合）、keyword_search_knowledge_base（词面精确匹配）、list_knowledge_documents（列出知识库收录的全部文档）、read_knowledge_document（按 source_id 读取整篇原文）。\n"
                "结果不理想时按下面的顺序逐级回退，每换一级先读完上一级的结果：\n"
                "1) 命中无关、过宽或缺少直接证据时，改用 hybrid_search_knowledge_base 重试；已知原文可能出现的专有名词、术语、人名或标题时，改用 keyword_search_knowledge_base 做词面匹配。\n"
                "2) 多轮检索仍无结果时，调用 list_knowledge_documents 确认知识库实际收录了哪些文档，判断哪些标题或主题可能相关。\n"
                "3) 确定可能相关的 source_id 后，调用 read_knowledge_document 读取全文核对上下文，不要只凭片段下结论。\n"
                "每轮只调用一次知识库检索工具：先阅读返回结果，再决定下一轮是否需要换工具或换查询。禁止在同一轮同时发出多个检索调用，也不要重复完全相同的 query。\n"
                "唯一可以不检索的情况是当前没有选择任何知识库；此时知识库工具不可用，直接回答即可。\n"
                "不得把模型常识冒充知识库结论。引用只能来自本轮工具实际返回的 source_id：历史对话里出现过的 [n] 标注一律不得复用，本轮没有检索就不允许出现任何 [n] 标注，也不允许说“根据检索结果”。\n"
                "不得在没有检索的情况下断言知识库中“有”或“没有”某项内容；没查就只能说“需要检索才能确认”。\n"
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

            retrieval_done = False
            reminders = 0
            for _ in range(self.max_tool_rounds):
                async with ASpan(ctx, "llm", self.tracing):
                    content, calls = await self.provider.generate(
                        ctx, messages, tool_definitions
                    )
                if not calls:
                    # 已选择知识库时，每个问题至少检索一次；模型想直接收尾
                    # 就打回去重来，最多提醒 MAX_RETRIEVAL_REMINDERS 次。
                    if (
                        selected_knowledge_bases
                        and not retrieval_done
                        and reminders < MAX_RETRIEVAL_REMINDERS
                    ):
                        reminders += 1
                        if content:
                            messages.append(ChatMessage("assistant", content))
                        messages.append(ChatMessage("system", RETRIEVAL_REQUIRED_MESSAGE))
                        self._record_retrieval_reminder(
                            ctx, reminders, selected_knowledge_bases
                        )
                        continue
                    self._remember_turn(ctx, user_input, content)
                    return content

                messages.append(ChatMessage("assistant", content, tool_calls=calls))
                async with ASpan(ctx, "tool", self.tracing):
                    retrieval_executed = False
                    for call in calls:
                        if call.name in RETRIEVAL_TOOL_NAMES:
                            if retrieval_executed:
                                # 同一条消息里的后续检索调用会被丢弃，让 LLM
                                # 先读第一条结果，再决定下一轮怎么查。
                                outcome = SKIPPED_RETRIEVAL_MESSAGE
                            else:
                                retrieval_executed = True
                                retrieval_done = True
                                outcome = self.tools.execute(ctx, call, runtime_context)
                        else:
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


__all__ = [
    "AgentRuntime",
    "MAX_RETRIEVAL_REMINDERS",
    "RETRIEVAL_REQUIRED_MESSAGE",
    "RETRIEVAL_TOOL_NAMES",
    "SKIPPED_RETRIEVAL_MESSAGE",
    "make_runtime",
]
