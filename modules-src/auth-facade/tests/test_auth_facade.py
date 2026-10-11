import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from auth_facade import AuthService
from core_specifications import RequestContext

CTX=RequestContext("trace","request","test")
class FakeData:
    def __init__(self):
        self.users={}; self.names={}; self.notebooks={}; self.members={}; self.quotas={}; self.lock=threading.RLock()
    def initialize(self,ctx): pass
    def list_users(self,ctx,active_only=True):
        with self.lock: return [dict(v) for v in self.users.values() if not active_only or v.get("is_active") is True]
    def create_user(self,ctx,user):
        with self.lock:
            if user["id"] in self.users or user["username"].lower() in self.names: raise ValueError("duplicate")
            row=dict(user); self.users[row["id"]]=row; self.names[row["username"].lower()]=row["id"]; return dict(row)
    def get_user(self,ctx,user_id):
        with self.lock:
            row=self.users.get(user_id); return dict(row) if row else None
    def get_user_by_username(self,ctx,username):
        with self.lock:
            user_id=self.names.get(username.lower()) if isinstance(username,str) else None
            return self.get_user(ctx,user_id) if user_id else None
    def set_user_active(self,ctx,user_id,active):
        with self.lock: self.users[user_id]["is_active"]=active
    def create_notebook(self,notebook_id,owner):
        self.notebooks[notebook_id]={"id":notebook_id,"owner_user_id":owner,"name":notebook_id,"created_at":"2026-10-11"}
        self.members[notebook_id]={}
    def get_notebook(self,ctx,notebook_id):
        row=self.notebooks.get(notebook_id); return dict(row) if row else None
    def membership_snapshot(self,ctx,notebook_id):
        return {"members":[{"user_id":u,"role":r} for u,r in self.members.get(notebook_id,{}).items()]}
    def put_member(self,ctx,notebook_id,user_id,role):
        self.members[notebook_id][user_id]=role
    def delete_member(self,ctx,notebook_id,user_id):
        self.members.get(notebook_id,{}).pop(user_id,None)
    def reserve_site_quota(self,ctx,local_date,limit):
        with self.lock:
            used=self.quotas.get(local_date,0)
            if used>=limit:return None
            self.quotas[local_date]=used+1
            return used+1
    def site_quota_used(self,ctx,local_date):
        with self.lock:return self.quotas.get(local_date,0)

class AuthFacadeTests(unittest.TestCase):
    def setUp(self):
        self.data=FakeData(); self.auth=AuthService(self.data,daily_limit=100)
        self.auth.initialize(CTX,"rootadmin","bootstrap-password")
        self.admin,self.admin_token=self.auth.login(CTX,"rootadmin","bootstrap-password")
        self.guest=self.auth.guest(CTX)
        self.alice_record=self.auth.register(CTX,"alice","alice-password")
        self.alice,self.alice_token=self.auth.login(CTX,"alice","alice-password")
        self.bob_record=self.auth.register(CTX,"bob","bob-password")
        self.bob,self.bob_token=self.auth.login(CTX,"bob","bob-password")
    def test_bootstrap_is_one_time_and_guest_cannot_register_or_login(self):
        self.auth.initialize(CTX,"changedadmin","other-password")
        self.assertIsNone(self.data.get_user_by_username(CTX,"changedadmin"))
        self.assertEqual(self.auth.guest(CTX).role,"guest")
        with self.assertRaises(ValueError): self.auth.register(CTX,"guest","guest-password")
        with self.assertRaises(PermissionError): self.auth.login(CTX,"guest","guest-password")
        with self.assertRaises(ValueError): AuthService(FakeData()).initialize(CTX,"admin","short")
    def test_registration_password_hash_and_session_lifecycle(self):
        row=self.data.get_user(CTX,self.alice.user_id)
        self.assertTrue(row["password_hash"].startswith("scrypt$"))
        self.assertNotIn("password_hash",self.alice_record)
        self.assertEqual(self.auth.authenticate_session(CTX,self.alice_token).user_id,self.alice.user_id)
        with self.assertRaises(PermissionError): self.auth.login(CTX,"alice","wrong-password")
        self.auth.logout(CTX,self.alice_token)
        with self.assertRaises(PermissionError): self.auth.authenticate_session(CTX,self.alice_token)
        with self.assertRaises(PermissionError): self.auth.authenticate_session(CTX,"forged")
    def test_active_state_is_reloaded_for_principal_and_session(self):
        self.auth.set_user_active(CTX,self.admin,self.alice.user_id,False)
        for action in (lambda:self.auth.authorize(CTX,self.alice,"read"),
                       lambda:self.auth.authenticate_session(CTX,self.alice_token)):
            with self.assertRaises(PermissionError): action()
        self.assertNotIn("password_hash",repr(self.auth))
        with self.assertRaises(PermissionError): self.auth.set_user_active(CTX,self.alice,self.bob.user_id,False)
    def test_notebook_owner_editor_viewer_guest_and_admin_scope(self):
        self.data.create_notebook("admin-book",self.admin.user_id)
        self.data.create_notebook("bob-book",self.bob.user_id)
        self.auth.set_member(CTX,self.admin,"admin-book",self.alice.user_id,"editor")
        self.auth.set_member(CTX,self.admin,"admin-book","guest","viewer")
        self.auth.set_member(CTX,self.bob,"bob-book",self.alice.user_id,"viewer")
        self.assertEqual(self.auth.notebook_permissions(CTX,self.admin,"admin-book"),
                         ["read","query","import_document","write","manage_members","manage_notebook"])
        self.assertEqual(self.auth.notebook_permissions(CTX,self.alice,"admin-book"),
                         ["read","query","import_document","write"])
        self.assertEqual(self.auth.notebook_permissions(CTX,self.guest,"admin-book"),["read","query"])
        self.assertEqual(self.auth.notebook_permissions(CTX,self.admin,"bob-book"),[])
        self.assertEqual(self.auth.allowed_notebooks(CTX,self.admin,["admin-book","bob-book"],["bob-book"]),["admin-book"])
        self.assertEqual(self.auth.allowed_notebooks(CTX,self.alice,["admin-book","bob-book"]),["admin-book","bob-book"])
        with self.assertRaises(PermissionError): self.auth.authorize_notebook(CTX,self.alice,"admin-book","manage_members")
        with self.assertRaises(ValueError): self.auth.set_member(CTX,self.admin,"admin-book","guest","editor")
        with self.assertRaises(ValueError): self.auth.set_member(CTX,self.admin,"admin-book",self.bob.user_id,"manager")
    def test_share_targets_include_guest_and_membership_is_owner_only(self):
        self.data.create_notebook("admin-book",self.admin.user_id)
        targets=self.auth.list_share_targets(CTX,self.admin,"admin-book")
        self.assertIn("guest",{item["id"] for item in targets})
        self.assertNotIn("password_hash",str(targets))
        with self.assertRaises(PermissionError): self.auth.list_members(CTX,self.alice,"admin-book")
        self.auth.set_member(CTX,self.admin,"admin-book",self.alice.user_id,"viewer")
        self.assertEqual(self.auth.list_members(CTX,self.admin,"admin-book"),[{"user_id":self.alice.user_id,"role":"viewer"}])
        self.auth.remove_member(CTX,self.admin,"admin-book",self.alice.user_id)
        self.assertEqual(self.auth.notebook_permissions(CTX,self.alice,"admin-book"),[])
    def test_admin_user_controls_and_last_admin_protection(self):
        with self.assertRaises(PermissionError): self.auth.set_user_active(CTX,self.admin,self.admin.user_id,False)
        self.assertEqual({u["username"] for u in self.auth.list_admin_users(CTX,self.admin)},{"rootadmin","alice","bob"})
        self.auth.set_user_active(CTX,self.admin,self.bob.user_id,False)
        with self.assertRaises(PermissionError): self.auth.authorize(CTX,self.bob,"query")
        listed={u["id"]:u for u in self.auth.list_admin_users(CTX,self.admin)}
        self.assertFalse(listed[self.bob.user_id]["is_active"])
        self.auth.set_user_active(CTX,self.admin,self.bob.user_id,True)
        self.assertTrue({u["id"]:u for u in self.auth.list_admin_users(CTX,self.admin)}[self.bob.user_id]["is_active"])
        with self.assertRaises(ValueError): self.auth.set_user_active(CTX,self.admin,"guest",False)
    def test_site_quota_is_shared_and_atomic_under_concurrency(self):
        def reserve(_):
            try:self.auth.reserve_query(CTX); return True
            except PermissionError:return False
        with ThreadPoolExecutor(max_workers=32) as pool:
            results=list(pool.map(reserve,range(140)))
        self.assertEqual(sum(results),100)
        self.assertEqual(self.auth.quota_status(CTX)["used"],100)
        with self.assertRaises(PermissionError):self.auth.reserve_query(CTX)
    def test_unknown_permission_and_forged_principal_rejected(self):
        from core_specifications import AuthPrincipal
        with self.assertRaises(PermissionError): self.auth.authorize(CTX,AuthPrincipal(self.admin.user_id,"admin"),"manage_models")
        with self.assertRaises(ValueError): self.auth.authorize(CTX,self.admin,"unknown")
        self.auth.authorize(CTX,self.admin,"manage_models")

if __name__=="__main__": unittest.main()
