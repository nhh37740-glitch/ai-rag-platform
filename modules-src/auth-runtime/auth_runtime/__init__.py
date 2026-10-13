# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations
import base64,hashlib,hmac,secrets,time
from core_specifications import AuthPrincipal,RequestContext
__version__="0.5.0"
_N=1<<14
_R=8
_P=1
_KEY=64
def _password_bytes(password):
    if not isinstance(password,str): raise ValueError("Invalid password")
    try: raw=password.encode("utf-8")
    except UnicodeEncodeError: raise ValueError("Invalid password") from None
    if not 8<=len(raw)<=1024: raise ValueError("Invalid password")
    return raw
class AuthRuntime:
    """Password hashing and process-local credentials."""
    def __init__(self): self._key=secrets.token_bytes(32); self._sessions={}
    def __repr__(self): return "AuthRuntime(process_local=True)"
    @staticmethod
    def hash_password(password):
        salt=secrets.token_bytes(16); digest=hashlib.scrypt(_password_bytes(password),salt=salt,n=_N,r=_R,p=_P,dklen=_KEY)
        return "scrypt$"+base64.urlsafe_b64encode(salt).decode()+"$"+base64.urlsafe_b64encode(digest).decode()
    @staticmethod
    def verify_password(password,encoded):
        try:
            raw=_password_bytes(password); alg,salt_text,digest_text=encoded.split("$")
            salt=base64.urlsafe_b64decode(salt_text.encode("ascii")); expected=base64.urlsafe_b64decode(digest_text.encode("ascii"))
            if alg!="scrypt" or len(salt)!=16 or len(expected)!=_KEY: return False
            actual=hashlib.scrypt(raw,salt=salt,n=_N,r=_R,p=_P,dklen=_KEY)
            return hmac.compare_digest(actual,expected)
        except (ValueError,TypeError,AttributeError,UnicodeEncodeError): return False
    def issue_principal(self,ctx,user_id,role):
        if not isinstance(user_id,str) or not user_id or not isinstance(role,str) or role not in {"admin","user","guest"}: raise ValueError("Invalid identity")
        proof=hmac.new(self._key,b"principal\\0"+role.encode()+b"\\0"+user_id.encode(),hashlib.sha256).hexdigest()
        return AuthPrincipal(user_id=user_id,role=role,proof=proof)
    def validate_principal(self,ctx,principal):
        if type(principal) is not AuthPrincipal or not isinstance(principal.role,str) or principal.role not in {"admin","user","guest"}: raise PermissionError("Authentication denied")
        try:
            expected=hmac.new(self._key,b"principal\\0"+principal.role.encode()+b"\\0"+principal.user_id.encode(),hashlib.sha256).hexdigest()
            valid=hmac.compare_digest(expected,principal.proof)
        except (AttributeError,TypeError,UnicodeEncodeError): valid=False
        if not valid: raise PermissionError("Authentication denied")
        return True
    def issue_session(self,ctx,user_id,ttl_seconds):
        if not isinstance(user_id,str) or not user_id or type(ttl_seconds) is not int or not 1<=ttl_seconds<=43200: raise ValueError("Invalid session")
        nonce=secrets.token_urlsafe(32); sig=hmac.new(self._key,b"session\\0"+user_id.encode()+b"\\0"+nonce.encode(),hashlib.sha256).hexdigest()
        token=nonce+"."+sig; self._sessions[hashlib.sha256(token.encode("ascii")).hexdigest()]=(user_id,time.monotonic()+ttl_seconds)
        return token
    def resolve_session(self,ctx,token):
        if not isinstance(token,str) or len(token)>512: return None
        try:
            nonce,sig=token.split(".",1); key=hashlib.sha256(token.encode("ascii")).hexdigest(); row=self._sessions.get(key)
            if row is None: return None
            user_id,expires=row; expected=hmac.new(self._key,b"session\\0"+user_id.encode()+b"\\0"+nonce.encode(),hashlib.sha256).hexdigest()
            if time.monotonic()>=expires or not hmac.compare_digest(expected,sig): self._sessions.pop(key,None); return None
            return user_id
        except (ValueError,UnicodeEncodeError): return None
    def revoke_session(self,ctx,token):
        if isinstance(token,str):
            try: key=hashlib.sha256(token.encode("ascii")).hexdigest()
            except UnicodeEncodeError: return
            self._sessions.pop(key,None)
__all__=["AuthRuntime"]
