import hashlib
import os
import base64
import time as _time


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


class RateLimiter:
    def __init__(self, max_failures: int = 5, window_sec: int = 300, lockout_sec: int = 900):
        self._max_failures = max_failures
        self._window_sec = window_sec
        self._lockout_sec = lockout_sec
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def is_blocked(self, ip: str) -> bool:
        now = _time.time()
        lock = self._locked_until.get(ip)
        if lock and now < lock:
            return True
        if lock and now >= lock:
            del self._locked_until[ip]
            self._failures.pop(ip, None)
        return False

    def record_failure(self, ip: str):
        now = _time.time()
        self._failures.setdefault(ip, []).append(now)
        cutoff = now - self._window_sec
        self._failures[ip] = [t for t in self._failures[ip] if t > cutoff]
        if len(self._failures[ip]) >= self._max_failures:
            self._locked_until[ip] = now + self._lockout_sec

    def reset(self, ip: str):
        self._failures.pop(ip, None)
        self._locked_until.pop(ip, None)
