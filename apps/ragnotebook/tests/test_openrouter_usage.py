"""The one app enforces a 100-query site quota for guest and signed-in users."""
import asyncio
from unittest.mock import patch

import httpx
import server as s

BASE_URL = "http://testserver"


def test_site_quota_is_shared_and_stops_at_100():
    async def scenario():
        calls = []
        async def fake_run(ctx, question, notebook_ids, **kwargs):
            calls.append((ctx.user_id, ctx.session_id))
            return "answer"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as guest:
            with patch.object(s.runtime, "run", new=fake_run):
                status = await guest.get("/api/llm/config")
                assert status.status_code == 200
                quota = status.json()["quota"]
                assert quota["scope"] == "site" and quota["limit"] == 100
                for index in range(quota["remaining"]):
                    response = await guest.post("/api/chat", headers={"origin": BASE_URL}, json={"message": f"quota question {index}", "knowledge_base_ids": [s.DEMO_KB_ID]})
                    assert response.status_code == 200, response.text
                    assert response.json()["quota"]["remaining"] == quota["remaining"] - index - 1
                exhausted = await guest.post("/api/chat", headers={"origin": BASE_URL}, json={"message": "over quota", "knowledge_base_ids": [s.DEMO_KB_ID]})
                assert exhausted.status_code == 429
                assert exhausted.json()["detail"]["quota"]["remaining"] == 0
                assert len(calls) == quota["remaining"]
                assert all(user_id == "guest" and not session_id for user_id, session_id in calls)
    asyncio.run(scenario())
