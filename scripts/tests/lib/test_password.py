"""argon2 密码哈希/验证测试。"""

from lib.auth.password import hash_password, verify_password


def test_hash_and_verify_success():
    hashed = hash_password("SecureP@ss1")
    assert verify_password("SecureP@ss1", hashed)


def test_verify_wrong_password():
    hashed = hash_password("SecureP@ss1")
    assert not verify_password("wrong", hashed)


def test_different_hashes_for_same_password():
    h1 = hash_password("SecureP@ss1")
    h2 = hash_password("SecureP@ss1")
    assert h1 != h2  # argon2 使用随机 salt
    assert verify_password("SecureP@ss1", h1)
    assert verify_password("SecureP@ss1", h2)
