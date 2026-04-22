"""记忆模块配置。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryConfig:
    """记忆配置 - 仅保留业务参数。

    技术实现细节（检索数量、阈值等）直接内联在代码中，
    避免过度配置化。
    """
    ttl_days: int = 30