"""每次构建用真实 DeepSeek 验证固定 CMRC 问题；普通源码测试不发请求。"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from httpx import ConnectError, ConnectTimeout

from core_specifications import RequestContext
from agent_facade import AgentService, make_provider
from data_facade import DataService
from rag_facade import RagService
from observability import make_trace_store

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("RUN_LIVE_MODEL") == "1", "真实模型只由独立必跑构建步骤启用")
class LiveCmrcTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_questions_have_actual_cmrc_evidence(self):
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        self.assertTrue(key, "每次构建的真实模型验收缺少 DEEPSEEK_API_KEY")
        kb = ROOT / "data/kb/cmrc2018-demo"
        manifest = json.loads((kb / "knowledge-base-manifest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            ctx = RequestContext("live-import", "live-import")
            data = DataService(temporary)
            tracing = make_trace_store()
            rag = RagService(data.vector_store(ctx), tracing)
            provider = make_provider(key, os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                                     os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))
            self.assertEqual(type(provider).__name__, "DeepSeekProvider")
            try:
                for doc in manifest["documents"]:
                    rag.ingest(ctx, str(kb / "knowledge-documents" / doc["file"]), manifest["id"])
                # Two different document subjects bound cost while exercising real tool calling.
                for i, item in enumerate(manifest["featured_questions"][:2]):
                    with self.subTest(question_id=f"featured-{i}"):
                        ctx = RequestContext(f"live-{i}", f"live-{i}", f"user-{i}", f"session-{i}")
                        agent = AgentService(data, rag, tracing, str(ROOT / "skills"), provider)
                        try:
                            for attempt in range(2):
                                try:
                                    answer = await asyncio.wait_for(agent.run(ctx, "请查阅知识库资料，回答：" + item["question"], [manifest["id"]]), 120)
                                    break
                                except (ConnectError, ConnectTimeout) as exc:
                                    if attempt == 0:
                                        await asyncio.sleep(1)
                                        continue
                                    self.fail(f"真实模型连接失败（已重试一次）: {type(exc).__name__}")
                                except Exception as exc:
                                    # Never put server response bodies or credentials in JUnit.
                                    self.fail(f"真实模型调用失败: {type(exc).__name__}")
                            self.assertTrue(answer.strip())
                            self.assertRegex(answer, r"\[\d+\]", "回答缺少引用标记")
                            # The first two fixed source documents define these concepts.
                            concepts = ("电荷", "分布") if i == 0 else ("简单",)
                            for concept in concepts:
                                self.assertIn(concept, answer, "回答遗漏实例文档中的核心内容")
                            if i == 1:
                                self.assertTrue(any(word in answer for word in ("一致", "符合", "解释")),
                                                "奥卡姆剃刀回答遗漏一致性条件")
                            evidence = [s for s in tracing.get(ctx.trace_id) if s.span == "rag" and s.status == "ok" and s.meta.get("hits")]
                            self.assertTrue(evidence, "真实模型未执行成功检索")
                            sources = {hit["source_id"] for s in evidence for hit in s.meta["hits"]}
                            self.assertTrue(all(source.startswith(manifest["id"] + "/") for source in sources))
                            self.assertIn(manifest["id"] + "/" + Path(item["document"]).stem, sources)
                        finally:
                            await agent.aclose(ctx)
            finally:
                data.close(ctx)
