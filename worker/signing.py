"""Request signing shared by the worker and (re-implemented in TypeScript) by the store API.

Header:  X-Render-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>." + raw body)>
The server rejects timestamps more than 5 minutes off and compares in constant time."""
import hashlib
import hmac
import time


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"
