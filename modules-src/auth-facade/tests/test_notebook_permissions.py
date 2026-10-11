import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from auth_facade import AuthService
from core_specifications import AuthPrincipal, RequestContext

TOKEN = "test-only-notebook-proof-1234567890123456789"
CTX = RequestContext("t", "r", "spoofed")

class Store:
    def __init__(self): self.values = {}
    def get(self, ctx, key): return copy.deepcopy(self.values.get((ctx.user_id, key)))
    def set(self, ctx, key, value): self.values[(ctx.user_id, key)] = copy.deepcopy(value)

class NotebookPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.auth = AuthService(TOKEN, "owner", self.store)
        self.admin = self.auth.authenticate_proxy(CTX, TOKEN, "owner", "admin")
        self.user = self.auth.authenticate_proxy(CTX, TOKEN, "alice", "user")

    def test_roles_are_local_to_notebook_and_public_is_always_readonly(self):
        self.assertEqual(self.auth.allowed_notebooks(CTX, self.user, ["public", "a", "b"], ["public"]), ["public"])
        for role, expected in [("viewer", ["read", "query"]), ("editor", ["read", "query", "import_document", "write"]), ("manager", ["read", "query", "import_document", "write", "manage_members"])]:
            self.auth.set_member(CTX, self.admin, "a", "alice", role)
            self.assertEqual(self.auth.notebook_permissions(CTX, self.user, "a"), expected)
            self.assertEqual(self.auth.notebook_permissions(CTX, self.user, "b"), [])
            for permission in ["read", "query", "import_document", "write", "manage_members"]:
                if permission in expected:
                    self.auth.authorize_notebook(CTX, self.user, "a", permission)
                else:
                    with self.assertRaises(PermissionError): self.auth.authorize_notebook(CTX, self.user, "a", permission)
            self.assertEqual(self.auth.notebook_permissions(CTX, self.admin, "public", True), ["read", "query"])
        self.assertEqual(self.auth.allowed_notebooks(CTX, self.user, ["public", "a", "b"], ["public"]), ["public", "a"])

    def test_forged_guest_same_id_and_modified_signed_user_cannot_gain_access(self):
        self.auth.set_member(CTX, self.admin, "a", "alice", "manager")
        self.assertEqual(self.auth.notebook_permissions(CTX, AuthPrincipal("alice", "guest"), "a"), [])
        for forged in [AuthPrincipal("alice", "user"), replace(self.user, role="admin"), replace(self.user, user_id="bob")]:
            with self.assertRaises(PermissionError): self.auth.notebook_permissions(CTX, forged, "a")
        for token, user_id, role in [("wrong", "alice", "user"), (TOKEN, "alice", "admin"), (TOKEN, "owner", "user")]:
            with self.assertRaises(PermissionError): self.auth.authenticate_proxy(CTX, token, user_id, role)
        with self.assertRaises(PermissionError): self.auth.authorize(CTX, self.auth.guest(CTX), "authenticated")

    def test_manager_can_change_members_only_in_authorized_notebook_and_revocation_is_immediate(self):
        self.auth.set_member(CTX, self.admin, "a", "alice", "manager")
        self.auth.set_member(CTX, self.user, "a", "bob", "viewer")
        with self.assertRaises(PermissionError): self.auth.set_member(CTX, self.user, "b", "bob", "manager")
        for role in ["admin", "", [], None]:
            with self.assertRaises(ValueError): self.auth.set_member(CTX, self.admin, "a", "bob", role)
        for user_id in ["owner", "", " alice ", "a/b", "a\\b", "alice\nadmin"]:
            with self.assertRaises(ValueError): self.auth.set_member(CTX, self.admin, "a", user_id, "viewer")
        self.auth.remove_member(CTX, self.admin, "a", "alice")
        self.assertEqual(self.auth.notebook_permissions(CTX, self.user, "a"), [])
        with self.assertRaises(PermissionError): self.auth.list_members(CTX, self.user, "a")
        self.auth.remove_member(CTX, self.admin, "a", "alice")

    def test_old_notebooks_stay_private_and_reopening_policy_keeps_roles(self):
        self.auth.set_member(CTX, self.admin, "a", "alice", "editor")
        reopened = AuthService(TOKEN, "owner", self.store)
        user = reopened.authenticate_proxy(CTX, TOKEN, "alice", "user")
        self.assertEqual(reopened.notebook_permissions(CTX, user, "legacy"), [])
        self.assertIn("import_document", reopened.notebook_permissions(CTX, user, "a"))
        with self.assertRaises(PermissionError): reopened.notebook_permissions(CTX, self.user, "a")

    def test_corrupt_policy_fails_closed_and_concurrent_members_are_not_lost(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self.auth.set_member(CTX, self.admin, "a", "user-"+str(i), "viewer"), range(40)))
        self.assertEqual(len(self.auth.list_members(CTX, self.admin, "a")), 40)
        self.store.values[("__rag_notebook_acl__", "notebook-members:a")] = {"alice": ["manager"]}
        with self.assertRaises(PermissionError): self.auth.notebook_permissions(CTX, self.user, "a")
