import base64
import os
import secrets
from hashlib import pbkdf2_hmac


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(key: str, salt: bytes | None = None) -> tuple[str, bytes]:
    salt = salt or os.urandom(16)
    dk = pbkdf2_hmac("sha256", key.encode("utf-8"), salt, 100_000)
    payload = salt + dk
    return base64.b64encode(payload).decode("utf-8"), salt


def verify_api_key(key: str, encoded: str) -> bool:
    try:
        payload = base64.b64decode(encoded.encode("utf-8"))
    except Exception:
        return False
    salt, digest = payload[:16], payload[16:]
    new_digest = pbkdf2_hmac("sha256", key.encode("utf-8"), salt, 100_000)
    return secrets.compare_digest(digest, new_digest)
