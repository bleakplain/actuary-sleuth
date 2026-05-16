"""密码哈希与验证（argon2id）。"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1)


def hash_password(password: str) -> str:
    """对密码进行 argon2id 哈希。"""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码是否匹配哈希。"""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
