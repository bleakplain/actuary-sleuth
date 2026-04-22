"""记忆模块配置。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryConfig:
    ttl_days: int = 30
    inactive_threshold_days: int = 60
    memory_context_max_chars: int = 2000
    memory_search_limit: int = 3
    dedup_similarity_threshold: float = 0.9
    profile_confidence_threshold: float = 0.6
    retrieve_interval_seconds: int = 60