import sys
sys.path.insert(0, '.')
from auth import hash_password, verify_password


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


if __name__ == "__main__":
    tests = [
        test_hash_password_returns_salt_and_hash,
        test_verify_password_correct,
        test_verify_password_wrong,
        test_hash_password_produces_different_salts,
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
