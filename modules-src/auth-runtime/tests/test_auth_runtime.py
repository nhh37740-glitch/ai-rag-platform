import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

import auth_runtime
from auth_runtime import AuthService
from core_specifications import AuthPrincipal, AuthServicePort, RequestContext


TOKEN = "test-only-proxy-token-private-sentinel-123456789"
OWNER = "private-owner-sentinel"
PERMISSIONS = ("read", "query", "create_notebook", "import_document", "write")


class TestAuthService(unittest.TestCase):
    def setUp(self):
        self.ctx = RequestContext("trace", "request", "visitor", "session")
        self.auth = AuthService(TOKEN, OWNER)

    def admin(self, service=None):
        return (service or self.auth).authenticate_proxy(self.ctx, TOKEN, OWNER, "admin")

    def test_A01_guest_read_query_allowed_writes_denied(self):
        for service in (AuthService(), self.auth):
            principal = service.guest(self.ctx)
            self.assertEqual((principal.user_id, principal.role, principal.proof), ("visitor", "guest", ""))
            for permission in ("read", "query"):
                self.assertIsNone(service.authorize(self.ctx, principal, permission))
            for permission in PERMISSIONS[2:]:
                with self.assertRaises(PermissionError):
                    service.authorize(self.ctx, principal, permission)
            anonymous = service.guest(RequestContext("t", "r"))
            self.assertEqual(anonymous.user_id, "guest")
            with self.assertRaises(FrozenInstanceError):
                principal.role = "admin"

    def test_A02_authenticated_owner_can_use_all_permissions(self):
        principal = self.admin()
        self.assertEqual((principal.user_id, principal.role), (OWNER, "admin"))
        self.assertTrue(principal.proof)
        self.assertNotEqual(principal.proof, TOKEN)
        for permission in PERMISSIONS:
            self.assertIsNone(self.auth.authorize(self.ctx, principal, permission))
        self.assertIsInstance(self.auth, AuthServicePort)

    def test_A02_wrong_token_owner_or_role_denied(self):
        cases = [
            ("incorrect-token-sentinel", OWNER, "admin"), (TOKEN, "different-owner", "admin"),
            (TOKEN, OWNER, "guest"), (TOKEN, OWNER, "Admin"), (TOKEN, OWNER, "admin "),
            (None, OWNER, "admin"), (TOKEN, None, "admin"), (TOKEN, OWNER, None),
            (TOKEN.encode(), OWNER, "admin"), ("\ud800", OWNER, "admin"),
        ]
        for token, owner, role in cases:
            with self.subTest(token_type=type(token).__name__, owner_type=type(owner).__name__, role=role):
                with self.assertRaises(PermissionError):
                    self.auth.authenticate_proxy(self.ctx, token, owner, role)
        with self.assertRaises(PermissionError):
            AuthService().authenticate_proxy(self.ctx, "", "", "admin")

    def test_A02_proxy_token_uses_constant_time_comparison_even_wrong_identity(self):
        original = auth_runtime.hmac.compare_digest
        with patch.object(auth_runtime.hmac, "compare_digest", wraps=original) as compare:
            with self.assertRaises(PermissionError):
                self.auth.authenticate_proxy(self.ctx, TOKEN, "wrong-owner", "guest")
            compare.assert_called_once_with(TOKEN.encode("utf-8"), TOKEN.encode("utf-8"))

    def test_A03_forged_and_cross_instance_principals_denied_for_every_permission(self):
        principal = self.admin()
        other = AuthService(TOKEN, OWNER)
        for permission in PERMISSIONS:
            with self.assertRaises(PermissionError):
                other.authorize(self.ctx, principal, permission)
        forged = [
            AuthPrincipal(OWNER, "admin"), AuthPrincipal(OWNER, "admin", TOKEN),
            AuthPrincipal(OWNER, "admin", "forged-proof"), replace(principal, user_id="other-owner"),
            replace(principal, role="guest"), replace(principal, proof=principal.proof[:-1]),
            replace(principal, proof="\ud800"), AuthPrincipal("", "guest"),
            AuthPrincipal(" guest ", "guest"), AuthPrincipal("visitor", "owner"),
            {"user_id": OWNER, "role": "admin", "proof": principal.proof}, None,
        ]
        for value in forged:
            for permission in PERMISSIONS:
                with self.assertRaises(PermissionError):
                    self.auth.authorize(self.ctx, value, permission)
            with self.assertRaises(PermissionError):
                self.auth.allowed_notebooks(self.ctx, value, ["cmrc2018-demo"], ["cmrc2018-demo"])

    def test_A04_guest_public_intersection_admin_all_order_and_deduplication(self):
        available = ["private", "public-b", "public-a", "public-b", "知识库_1"]
        published = ["public-a", "public-b", "not-available", "public-a"]
        guest = self.auth.guest(self.ctx)
        self.assertEqual(self.auth.allowed_notebooks(self.ctx, guest, available, published), ["public-b", "public-a"])
        selected = self.auth.allowed_notebooks(self.ctx, self.admin(), available, published)
        self.assertEqual(selected, ["private", "public-b", "public-a", "知识库_1"])
        selected.append("changed")
        self.assertNotIn("changed", available)
        self.assertEqual(self.auth.allowed_notebooks(self.ctx, guest, available, []), [])
        self.assertEqual(self.auth.allowed_notebooks(self.ctx, self.admin(), [], published), [])

    def test_A04_invalid_ids_and_unknown_permissions_rejected(self):
        guest = self.auth.guest(self.ctx)
        invalid_ids = ["", " ", "../private", "private/source", "private\\source", ".", "..",
                       "a\x00b", "a\nb", " hidden", "trailing ", "a b", "private%2Fsource", True, None]
        for notebook_id in invalid_ids:
            for available, published in (([notebook_id], []), ([], [notebook_id])):
                with self.assertRaises(ValueError):
                    self.auth.allowed_notebooks(self.ctx, guest, available, published)
                with self.assertRaises(ValueError):
                    self.auth.allowed_notebooks(self.ctx, self.admin(), available, published)
        for invalid_list in (None, "public", ("public",), {"public"}):
            with self.assertRaises(ValueError):
                self.auth.allowed_notebooks(self.ctx, guest, invalid_list, [])
        for permission in ("delete", "", "READ", True, None, ["read"]):
            with self.assertRaises(ValueError):
                self.auth.authorize(self.ctx, guest, permission)

    def test_A05_repr_and_exceptions_do_not_contain_server_secrets(self):
        admin = self.admin()
        forbidden = (TOKEN, OWNER, admin.proof)
        for value in forbidden:
            self.assertNotIn(value, repr(self.auth))
        self.assertNotIn(TOKEN, repr(admin))
        self.assertNotIn(admin.proof, repr(admin))
        for action in (
            lambda: self.auth.authenticate_proxy(self.ctx, TOKEN, "bad-owner", "admin"),
            lambda: self.auth.authorize(self.ctx, AuthPrincipal(OWNER, "admin", TOKEN), "write"),
            lambda: AuthService(TOKEN, OWNER + " "),
        ):
            try:
                action()
            except (PermissionError, ValueError) as error:
                for value in forbidden:
                    self.assertNotIn(value, str(error))
                    self.assertNotIn(value, repr(error))
            else:
                self.fail("Expected authentication failure")

    def test_configuration_validates_pair_byte_length_and_owner(self):
        for token, owner in (("", OWNER), (TOKEN, ""), ("x" * 31, OWNER),
                             (TOKEN, " owner"), (TOKEN, "owner "), (TOKEN, "o\nn"),
                             (TOKEN, "\ud800"), ("\ud800", OWNER), (" " * 40, OWNER),
                             (None, OWNER), (TOKEN, None)):
            with self.assertRaises(ValueError):
                AuthService(token, owner)
        exact = AuthService("x" * 32, OWNER)
        self.assertEqual(exact.authenticate_proxy(self.ctx, "x" * 32, OWNER, "admin").role, "admin")
        multibyte = "密" * 11
        service = AuthService(multibyte, "管理员")
        principal = service.authenticate_proxy(self.ctx, multibyte, "管理员", "admin")
        self.assertIsNone(service.authorize(self.ctx, principal, "write"))


if __name__ == "__main__":
    unittest.main()
