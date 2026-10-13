import unittest
from auth_facade import AuthService
import importlib.util; from pathlib import Path; _spec=importlib.util.spec_from_file_location('auth_facade_test_support',Path(__file__).with_name('test_auth_facade.py')); _support=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_support); FakeData,CTX=_support.FakeData,_support.CTX
class NotebookPermissionBoundaryTests(unittest.TestCase):
    def test_admin_create_user_create_and_public_list_cannot_bypass_membership(self):
        data=FakeData(); auth=AuthService(data); auth.initialize(CTX,"admin","bootstrap-password")
        admin,_=auth.login(CTX,"admin","bootstrap-password")
        user_record=auth.register(CTX,"member","member-password")
        member,_=auth.login(CTX,"member","member-password")
        guest=auth.guest(CTX)
        auth.authorize(CTX,admin,"create_notebook")
        auth.authorize(CTX,member,"create_notebook")
        with self.assertRaises(PermissionError):auth.authorize(CTX,guest,"create_notebook")
        data.create_notebook("private",user_record["id"])
        self.assertEqual(auth.allowed_notebooks(CTX,admin,["private"],["private"]),[])
        self.assertEqual(auth.allowed_notebooks(CTX,guest,["private"],["private"]),[])
        self.assertEqual(auth.allowed_notebooks(CTX,member,["private"],["private"]),["private"])
if __name__=="__main__":unittest.main()
