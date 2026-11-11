import unittest
from unittest.mock import patch
from auth_runtime import AuthRuntime
from core_specifications import RequestContext,AuthPrincipal
CTX=RequestContext("t","r","u")
class AuthRuntimeTests(unittest.TestCase):
    def test_scrypt_hash_and_verification(self):
        encoded=AuthRuntime.hash_password("correct-password")
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertTrue(AuthRuntime.verify_password("correct-password",encoded))
        self.assertFalse(AuthRuntime.verify_password("wrong-password",encoded))
        self.assertFalse(AuthRuntime.verify_password("correct-password","bad"))
        with self.assertRaises(ValueError): AuthRuntime.hash_password("short")
    def test_signed_principal_is_instance_bound(self):
        first=AuthRuntime(); second=AuthRuntime()
        principal=first.issue_principal(CTX,"user-1","user")
        self.assertTrue(first.validate_principal(CTX,principal))
        with self.assertRaises(PermissionError): second.validate_principal(CTX,principal)
        with self.assertRaises(PermissionError): first.validate_principal(CTX,AuthPrincipal("user-1","admin"))
    def test_session_expiry_revoke_and_instance_scope(self):
        first=AuthRuntime(); second=AuthRuntime(); token=first.issue_session(CTX,"u",12)
        self.assertEqual(first.resolve_session(CTX,token),"u")
        self.assertIsNone(second.resolve_session(CTX,token))
        first.revoke_session(CTX,token); self.assertIsNone(first.resolve_session(CTX,token))
        token=first.issue_session(CTX,"u",1)
        with patch("auth_runtime.time.monotonic",return_value=10**12): self.assertIsNone(first.resolve_session(CTX,token))
if __name__=="__main__": unittest.main()
