import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from core_specifications import AuthPrincipal, RequestContext
from auth_facade import AuthService
from storage import NotebookStore

CTX=RequestContext("trace","request","owner")
TOKEN="test-only-proxy-proof-1234567890123456789"

class NotebookPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"notebooks.sqlite")
        self.store=NotebookStore(self.path); self.addCleanup(self.store.close)
        self.auth=AuthService(TOKEN,"owner",self.store)
        self.admin=self.auth.authenticate_proxy(CTX,TOKEN,"owner","admin")
        self.user=self.auth.authenticate_proxy(CTX,TOKEN,"alice","user")
        for uid in ["bob"]+["user-"+str(i) for i in range(40)]: self.auth.authenticate_proxy(CTX,TOKEN,uid,"user")
        for uid,public in [("a",False),("b",False),("legacy",False),("public",True)]:
            self.store.create_notebook(CTX,{"id":uid,"owner_user_id":"owner","name":uid,"created_at":"2026-10-11","is_public":public})

    def test_role_matrix_scope_and_public_readonly(self):
        for role, expected in [("viewer",["read","query"]),("editor",["read","query","import_document","write"]),("manager",["read","query","import_document","write","manage_members","manage_notebook"])]:
            self.auth.set_member(CTX,self.admin,"a","alice",role)
            self.assertEqual(self.auth.notebook_permissions(CTX,self.user,"a"),expected)
            self.assertEqual(self.auth.notebook_permissions(CTX,self.user,"b"),[])
            for p in ["read","query","import_document","write","manage_members","manage_notebook","archive_notebook"]:
                if p in expected: self.auth.authorize_notebook(CTX,self.user,"a",p)
                else:
                    with self.assertRaises(PermissionError): self.auth.authorize_notebook(CTX,self.user,"a",p)
        self.assertEqual(self.auth.notebook_permissions(CTX,self.admin,"public",True),["read","query"])
        with self.assertRaises(PermissionError): self.auth.set_member(CTX,self.admin,"public","alice","manager")
        self.assertEqual(self.auth.allowed_notebooks(CTX,self.user,["public","a","b"],["public"]),["public","a"])

    def test_forged_proofs_and_unknown_users_denied(self):
        self.auth.set_member(CTX,self.admin,"a","alice","manager")
        self.assertEqual(self.auth.notebook_permissions(CTX,AuthPrincipal("alice","guest"),"a"),[])
        for forged in [AuthPrincipal("alice","user"),replace(self.user,role="admin"),replace(self.user,user_id="bob")]:
            with self.assertRaises(PermissionError): self.auth.notebook_permissions(CTX,forged,"a")
        with self.assertRaises(ValueError): self.auth.set_member(CTX,self.admin,"a","unknown","viewer")
        for role in ["admin","",[],None]:
            with self.assertRaises(ValueError): self.auth.set_member(CTX,self.admin,"a","bob",role)
        with self.assertRaises(ValueError): self.auth.set_member(CTX,self.admin,"a","owner","viewer")

    def test_manager_scope_revocation_and_archive(self):
        self.auth.set_member(CTX,self.admin,"a","alice","manager")
        self.auth.set_member(CTX,self.user,"a","bob","viewer")
        with self.assertRaises(PermissionError): self.auth.set_member(CTX,self.user,"b","bob","manager")
        self.store.set_archived(CTX,"a",True)
        self.assertEqual(self.auth.notebook_permissions(CTX,self.user,"a"),[])
        self.assertEqual(self.auth.notebook_permissions(CTX,self.admin,"a"),[])
        with self.assertRaises(PermissionError): self.auth.set_member(CTX,self.admin,"a","bob","editor")
        self.store.set_archived(CTX,"a",False)
        self.auth.remove_member(CTX,self.admin,"a","alice")
        self.assertEqual(self.auth.notebook_permissions(CTX,self.user,"a"),[])

    def test_reopen_persistence_and_cross_instance_proof_rejection(self):
        self.auth.set_member(CTX,self.admin,"a","alice","editor")
        other=NotebookStore(self.path); self.addCleanup(other.close)
        reopened=AuthService(TOKEN,"owner",other)
        user=reopened.authenticate_proxy(CTX,TOKEN,"alice","user")
        self.assertEqual(reopened.notebook_permissions(CTX,user,"legacy"),[])
        self.assertIn("import_document",reopened.notebook_permissions(CTX,user,"a"))
        with self.assertRaises(PermissionError): reopened.notebook_permissions(CTX,self.user,"a")

    def test_concurrent_distinct_members_across_connections_not_lost(self):
        stores=[NotebookStore(self.path) for _ in range(4)]
        for st in stores: self.addCleanup(st.close)
        auths=[AuthService(TOKEN,"owner",st) for st in stores]
        owners=[a.authenticate_proxy(CTX,TOKEN,"owner","admin") for a in auths]
        def update(i):
            j=i%4; auths[j].set_member(CTX,owners[j],"a","user-"+str(i),"viewer")
        with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(update,range(40)))
        self.assertEqual(len(self.auth.list_members(CTX,self.admin,"a")),40)

    def test_cas_conflict_reauthorizes_revoked_manager_before_retry(self):
        self.auth.set_member(CTX,self.admin,"a","alice","manager")
        store=self.store
        class RevokingPort:
            def __getattr__(self,name): return getattr(store,name)
            def put_member(self,ctx,nb,uid,role,expected_revision):
                store.delete_member(ctx,nb,"alice",expected_revision)
                return store.put_member(ctx,nb,uid,role,expected_revision)
        auth=AuthService(TOKEN,"owner",RevokingPort())
        alice=auth.authenticate_proxy(CTX,TOKEN,"alice","user")
        with self.assertRaises(PermissionError): auth.set_member(CTX,alice,"a","bob","editor")
        self.assertNotIn("bob",[m["user_id"] for m in store.membership_snapshot(CTX,"a")["members"]])
