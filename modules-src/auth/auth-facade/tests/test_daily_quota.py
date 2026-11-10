import unittest
from auth_facade import AuthService
import importlib.util; from pathlib import Path; _spec=importlib.util.spec_from_file_location('auth_facade_test_support',Path(__file__).with_name('test_auth_facade.py')); _support=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_support); FakeData,CTX=_support.FakeData,_support.CTX
class QuotaApiTests(unittest.TestCase):
    def test_configured_default_and_unlimited_validation(self):
        self.assertEqual(AuthService(FakeData())._daily_limit,100)
        for limit in (0,-1,True):
            with self.assertRaises(ValueError): AuthService(FakeData(),daily_limit=limit)
    def test_status_has_site_scope(self):
        data=FakeData(); auth=AuthService(data); auth.initialize(CTX,"admin","bootstrap-password")
        result=auth.quota_status(CTX)
        self.assertEqual(result["scope"],"site")
        self.assertEqual(result["limit"],100)
        self.assertEqual(result["remaining"],100)
if __name__=="__main__": unittest.main()
