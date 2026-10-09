"""Owner-session adapter tests with an isolated fake Media authentication server."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin_login import COOKIE, PREFIX, LoginConfig, create_app

ORIGIN = "https://portfolio.test:8443"
PROOF = "test-only-internal-admin-proof-1234567890"
OWNER = "7a35bc4b-f998-4fce-9bf6-4c7dfed2c193"
PASSWORD = "test-only-password-never-returned"
CONFIG = LoginConfig(PROOF, OWNER, ORIGIN, "http://host.docker.internal:8088/api/v1/auth")


class AdminLoginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.logged_out = set()
        self.identities = {
            "owner-session": {"userId": OWNER, "username": "owner"},
            "editor-session": {"userId": "different-account", "username": "editor"},
            "forged-owner-session": {"userId": "different-account", "username": "owner"},
            "renamed-session": {"userId": OWNER, "username": "viewer"},
        }

        def media(request):
            self.calls.append(request)
            cookie = request.headers.get("cookie", "").removeprefix("SESSION=")
            if request.url.path.endswith("/csrf"):
                return httpx.Response(200, json={"token": "test-csrf", "headerName": "X-CSRF-TOKEN"}, headers={"Set-Cookie": "SESSION=prelogin-session; Path=/; HttpOnly"})
            if request.url.path.endswith("/me"):
                if cookie not in self.identities or cookie in self.logged_out:
                    return httpx.Response(401, json={"message": "auth required"})
                return httpx.Response(200, json=self.identities[cookie])
            if request.url.path.endswith("/login"):
                body = json.loads(request.content)
                if request.headers.get("x-csrf-token") != "test-csrf" or cookie != "prelogin-session":
                    return httpx.Response(403)
                if body["password"] != PASSWORD:
                    return httpx.Response(401, json={"password": body["password"]})
                name = "owner-session" if body["username"] == "owner" else "editor-session"
                return httpx.Response(200, json=self.identities[name], headers={"Set-Cookie": "SESSION=" + name + "; Path=/; HttpOnly"})
            if request.url.path.endswith("/logout"):
                if request.headers.get("x-csrf-token") != "test-csrf":
                    return httpx.Response(403)
                self.logged_out.add(cookie)
                return httpx.Response(204)
            raise AssertionError("Unexpected Media endpoint " + request.url.path)

        app = create_app(CONFIG, transport=httpx.MockTransport(media))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_owner_login_rotates_cookie_and_exposes_no_credentials(self):
        csrf = await self.client.get("/csrf")
        self.assertEqual(csrf.json(), {"token": "test-csrf", "headerName": "X-CSRF-TOKEN"})
        self.assert_cookie(csrf, "prelogin-session")
        response = await self.client.post("/login", json={"username": "owner", "password": PASSWORD}, headers={"origin": ORIGIN, "X-CSRF-TOKEN": "test-csrf", "Cookie": COOKIE + "=prelogin-session"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"administrator": True, "redirect": PREFIX})
        self.assert_cookie(response, "owner-session")
        for hidden in [PASSWORD, PROOF, "owner-session", OWNER]:
            self.assertNotIn(hidden, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(self.calls[-1].headers["Cookie"], "SESSION=prelogin-session")

    def assert_cookie(self, response, value):
        cookie = response.headers["set-cookie"]
        self.assertIn(COOKIE + "=" + value, cookie)
        for attribute in ["HttpOnly", "Secure", "SameSite=strict", "Path=" + PREFIX]:
            self.assertIn(attribute, cookie)
        self.assertNotIn("SESSION=", cookie)

    async def test_verify_needs_internal_proof_and_exact_live_owner_identity(self):
        self.assertEqual((await self.client.get("/verify", headers={"Cookie": COOKIE + "=owner-session"})).status_code, 403)
        self.assertFalse(self.calls)
        headers = {"X-Rag-Proxy-Token": PROOF}
        self.assertEqual((await self.client.get("/verify", headers=headers)).status_code, 401)
        for name in ["editor-session", "forged-owner-session", "renamed-session", "expired-session"]:
            denied = await self.client.get("/verify", headers={**headers, "Cookie": COOKIE + "=" + name})
            self.assertEqual(denied.status_code, 403)
            self.assertNotIn("x-rag-user-id", denied.headers)
            self.assertNotIn("x-rag-role", denied.headers)
        verified = await self.client.get("/verify", headers={**headers, "Cookie": COOKIE + "=owner-session"})
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.headers["x-rag-user-id"], OWNER)
        self.assertEqual(verified.headers["x-rag-role"], "admin")
        self.assertNotIn(PROOF, verified.text)
        self.assertNotIn("owner-session", verified.text)

    async def test_duplicate_cookies_and_proof_headers_are_rejected(self):
        duplicates = {"X-Rag-Proxy-Token": PROOF, "Cookie": COOKIE + "=owner-session; " + COOKIE + "=editor-session"}
        self.assertEqual((await self.client.get("/verify", headers=duplicates)).status_code, 401)
        duplicates = [("X-Rag-Proxy-Token", PROOF), ("x-rag-proxy-token", PROOF), ("Cookie", COOKIE + "=owner-session")]
        self.assertEqual((await self.client.get("/verify", headers=duplicates)).status_code, 403)
        self.assertFalse(self.calls)

    async def test_other_account_and_cross_site_login_are_denied(self):
        headers = {"origin": ORIGIN, "X-CSRF-TOKEN": "test-csrf", "Cookie": COOKIE + "=prelogin-session"}
        for replacement in [{"origin": "https://attacker.test"}, {"sec-fetch-site": "cross-site"}, {"X-CSRF-TOKEN": ""}]:
            result = await self.client.post("/login", json={"username": "owner", "password": PASSWORD}, headers={**headers, **replacement})
            self.assertEqual(result.status_code, 403)
        self.assertFalse(self.calls)
        denied = await self.client.post("/login", json={"username": "editor", "password": PASSWORD}, headers=headers)
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("editor-session", denied.headers.get("set-cookie", ""))
        invalid = await self.client.post("/login", json={"username": "owner", "password": "private-input-sentinel"}, headers=headers)
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn("private-input-sentinel", invalid.text)

    async def test_logout_revokes_live_session_and_clears_secure_cookie(self):
        headers = {"origin": ORIGIN, "X-CSRF-TOKEN": "test-csrf", "Cookie": COOKIE + "=owner-session"}
        response = await self.client.post("/logout", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        verify = await self.client.get("/verify", headers={"X-Rag-Proxy-Token": PROOF, "Cookie": COOKIE + "=owner-session"})
        self.assertEqual(verify.status_code, 403)

    async def test_login_rate_limit_and_invalid_body_hide_input(self):
        headers = {"origin": ORIGIN, "X-CSRF-TOKEN": "test-csrf", "Cookie": COOKIE + "=prelogin-session"}
        for _ in range(10):
            result = await self.client.post("/login", json={"username": "owner", "password": "private-input-sentinel", "userId": OWNER}, headers=headers)
            self.assertEqual(result.status_code, 422)
            self.assertNotIn("private-input-sentinel", result.text)
        limited = await self.client.post("/login", json={"username": "owner", "password": PASSWORD}, headers=headers)
        self.assertEqual(limited.status_code, 429)
        self.assertFalse(self.calls)

    async def test_upstream_failure_fails_closed_without_identity_headers(self):
        def unavailable(request):
            raise httpx.ConnectError("private-error-sentinel", request=request)
        app = create_app(CONFIG, transport=httpx.MockTransport(unavailable))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            response = await client.get("/verify", headers={"X-Rag-Proxy-Token": PROOF, "Cookie": COOKIE + "=owner-session"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-error-sentinel", response.text)
        self.assertNotIn("x-rag-user-id", response.headers)

    def test_insecure_or_unpinned_configuration_is_rejected(self):
        for settings in [("short", OWNER, ORIGIN, CONFIG.auth_base), (PROOF, "", ORIGIN, CONFIG.auth_base), (PROOF, OWNER, "http://portfolio.test", CONFIG.auth_base), (PROOF, OWNER, ORIGIN, "http://external.example/api/v1/auth")]:
            with self.assertRaises(RuntimeError):
                LoginConfig(*settings)
