import hashlib
import os
import base64


def hash_password(password: str) -> tuple[str, str]:
    """Return (salt_b64, hash_b64) for a password."""
    salt = os.urandom(32)
    h = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        iterations=600_000,
    )
    return base64.b64encode(salt).decode(), base64.b64encode(h).decode()


def verify_password(password: str, salt_b64: str, hash_b64: str) -> bool:
    """Check if password matches the stored salt+hash."""
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(hash_b64)
    actual = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        iterations=600_000,
    )
    return actual == expected
