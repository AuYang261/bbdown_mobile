import sys
import os
import time
import tempfile
sys.path.insert(0, '.')
from auth import hash_password, verify_password, RateLimiter
from users import UserStore


def test_hash_password_returns_salt_and_hash():
    salt, h = hash_password("mypassword")
    assert isinstance(salt, str)
    assert isinstance(h, str)
    assert salt != ""
    assert h != ""
    assert salt != h


def test_verify_password_correct():
    salt, h = hash_password("mypassword")
    assert verify_password("mypassword", salt, h) is True


def test_verify_password_wrong():
    salt, h = hash_password("mypassword")
    assert verify_password("wrongpass", salt, h) is False


def test_hash_password_produces_different_salts():
    salt1, h1 = hash_password("samepass")
    salt2, h2 = hash_password("samepass")
    assert salt1 != salt2
    assert h1 != h2


def test_user_store_add_and_verify():
    store = UserStore(filepath="/tmp/test_users_nonexist.json")
    store.add_user("alice", "pass1")
    assert store.verify("alice", "pass1") is True
    assert store.verify("alice", "wrong") is False
    assert store.verify("bob", "pass1") is False


def test_user_store_remove():
    store = UserStore(filepath="/tmp/test_users_remove.json")
    store.add_user("alice", "pass1")
    store.add_user("bob", "pass2")
    store.remove_user("alice")
    assert store.verify("alice", "pass1") is False
    assert store.verify("bob", "pass2") is True


def test_user_store_list():
    store = UserStore(filepath="/tmp/test_users_list.json")
    store.add_user("alice", "pass1")
    store.add_user("bob", "pass2")
    usernames = store.list_users()
    assert "alice" in usernames
    assert "bob" in usernames


def test_user_store_change_password():
    store = UserStore(filepath="/tmp/test_users_chpwd.json")
    store.add_user("alice", "oldpass")
    assert store.change_password("alice", "oldpass", "newpass") is True
    assert store.verify("alice", "oldpass") is False
    assert store.verify("alice", "newpass") is True
    assert store.change_password("alice", "wrong", "x") is False


def test_user_store_persists_to_disk():
    path = "/tmp/test_users_persist.json"
    if os.path.exists(path):
        os.remove(path)
    store1 = UserStore(filepath=path)
    store1.add_user("alice", "pass1")
    store2 = UserStore(filepath=path)
    assert store2.verify("alice", "pass1") is True


def test_rate_limiter_allows_first_five():
    rl = RateLimiter(max_failures=5, window_sec=300, lockout_sec=900)
    for _ in range(5):
        assert rl.is_blocked("1.2.3.4") is False
        rl.record_failure("1.2.3.4")


def test_rate_limiter_blocks_sixth():
    rl = RateLimiter(max_failures=5, window_sec=300, lockout_sec=900)
    for _ in range(5):
        rl.record_failure("1.2.3.4")
    assert rl.is_blocked("1.2.3.4") is True


def test_rate_limiter_different_ips_independent():
    rl = RateLimiter(max_failures=5, window_sec=300, lockout_sec=900)
    for _ in range(5):
        rl.record_failure("1.2.3.4")
    assert rl.is_blocked("1.2.3.4") is True
    assert rl.is_blocked("5.6.7.8") is False


def test_rate_limiter_reset_on_success():
    rl = RateLimiter(max_failures=5, window_sec=300, lockout_sec=900)
    for _ in range(3):
        rl.record_failure("1.2.3.4")
    rl.reset("1.2.3.4")
    for _ in range(5):
        assert rl.is_blocked("1.2.3.4") is False
        rl.record_failure("1.2.3.4")


if __name__ == "__main__":
    tests = [
        test_hash_password_returns_salt_and_hash,
        test_verify_password_correct,
        test_verify_password_wrong,
        test_hash_password_produces_different_salts,
        test_user_store_add_and_verify,
        test_user_store_remove,
        test_user_store_list,
        test_user_store_change_password,
        test_user_store_persists_to_disk,
        test_rate_limiter_allows_first_five,
        test_rate_limiter_blocks_sixth,
        test_rate_limiter_different_ips_independent,
        test_rate_limiter_reset_on_success,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
