"""统一 ID 生成器。

基于 uuid4 生成唯一标识，全局统一调用。
"""
import uuid


class IDGenerator:
    """生成唯一 ID。

    默认 16 字符 hex，足以在分布式环境下保证唯一性。
    """

    def new_id(self, length: int = 16) -> str:
        return uuid.uuid4().hex[:length]


_id_generator = IDGenerator()
