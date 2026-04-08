"""记忆模块配置。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryConfig:
    ttl_fact: int = 30
    ttl_preference: int = 90
    ttl_audit_conclusion: int = -1

    inactive_threshold_days: int = 60
    memory_context_max_chars: int = 2000
