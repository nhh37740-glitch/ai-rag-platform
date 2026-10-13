"""Single-app account and model administration regression tests."""
import asyncio
import json
import os
from unittest.mock import patch

import httpx
import server as s

BASE_URL = "http://testserver"
ORIGIN = BASE_URL


def _credentials():
    return os.environ["RAG_BOOTSTRAP_ADMIN_USERNAME"], os.environ["RAG_BOOTSTRAP_ADMIN_PASSWORD"]


def test_disabled_account_session_is_rejected_immediately():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as admin, \
                   httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as user:
            username = "disable-" + os.urandom(5).hex()
            password = "test-password-123"
            registered = await user.post("/api/auth/register", headers={"origin": ORIGIN}, json={"username": username, "password": password})
            assert registered.status_code == 201, registered.text
            user_id = registered.json()["user"]["id"]
            login = await user.post("/api/auth/login", headers={"origin": ORIGIN}, json={"username": username, "password": password})
            assert login.status_code == 200 and user.cookies.get(s.SESSION_COOKIE)
            admin_username, admin_password = _credentials()
            admin_login = await admin.post("/api/auth/login", headers={"origin": ORIGIN}, json={"username": admin_username, "password": admin_password})
            assert admin_login.status_code == 200
            result = await admin.patch(f"/api/admin/users/{user_id}", headers={"origin": ORIGIN}, json={"active": False})
            assert result.status_code == 200, result.text
            denied = await user.get("/api/conversations")
            assert denied.status_code == 401, denied.text
            downgraded = await user.get("/api/auth/session")
            assert downgraded.status_code == 200 and downgraded.json()["role"] == "guest"
    asyncio.run(scenario())


def test_model_admin_is_global_admin_only_and_never_returns_server_keys():
    async def scenario():
        secret = "server-only-openrouter-secret-for-test"
        admin_username, admin_password = _credentials()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as admin, \
                   httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as user:
            registered = await user.post("/api/auth/register", headers={"origin": ORIGIN}, json={"username": "model-user-" + os.urandom(4).hex(), "password": "test-password-123"})
            assert registered.status_code == 201
            await user.post("/api/auth/login", headers={"origin": ORIGIN}, json={"username": registered.json()["user"]["username"], "password": "test-password-123"})
            assert (await user.get("/api/models/providers")).status_code == 403
            await admin.post("/api/auth/login", headers={"origin": ORIGIN}, json={"username": admin_username, "password": admin_password})
            catalog = json.dumps([{"id": "vendor/free-model:free", "name": "Free Model", "pricing": {"prompt": "0", "completion": "0"}}])
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": secret, "OPENROUTER_MODELS": catalog}), \
                 patch.dict(s.runtime._environment, {"OPENROUTER_API_KEY": secret, "OPENROUTER_MODELS": catalog}):
                providers = await admin.get("/api/models/providers")
                assert providers.status_code == 200, providers.text
                openrouter = next(item for item in providers.json()["providers"] if item["id"] == "openrouter")
                assert openrouter["configured"] is True
                models = await admin.get("/api/models/openrouter")
                assert models.status_code == 200 and "vendor/free-model:free" in {item["id"] for item in models.json()["models"]}
                changed = await admin.put("/api/models/settings", headers={"origin": ORIGIN}, json={"provider_id": "openrouter", "model_id": "openrouter/free"})
                assert changed.status_code == 200, changed.text
                settings = await admin.get("/api/models/settings")
                config = await admin.get("/api/llm/config")
                assert settings.json() == {"provider_id": "openrouter", "model_id": "openrouter/free", "server_key_configured": True, "free_models_only": True}
                assert config.json()["server_key_configured"] is True
                assert secret not in providers.text + models.text + changed.text + settings.text + config.text
                restored = await admin.put("/api/models/settings", headers={"origin": ORIGIN}, json={"provider_id": "mock", "model_id": "mock"})
                assert restored.status_code == 200, restored.text
    asyncio.run(scenario())
