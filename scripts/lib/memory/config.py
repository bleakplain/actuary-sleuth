"""记忆模块配置。"""
from dataclasses import dataclass
from enum import Enum


class MemoryCategory(str, Enum):
    """记忆分层类型。"""
    SESSION = "session"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    FACT = "fact"
    PREFERENCE = "preference"
    AUDIT_CONCLUSION = "audit_conclusion"


@dataclass(frozen=True)
class MemoryConfig:
    ttl_fact: int = 30
    ttl_preference: int = 90
    ttl_audit_conclusion: int = -1

    ttl_session: int = -1
    ttl_short_term: int = 7
    ttl_long_term: int = -1

    inactive_threshold_days: int = 60
    memory_context_max_chars: int = 2000
    memory_search_limit: int = 3
    dedup_similarity_threshold: float = 0.9

    def get_ttl(self, category: str) -> int:
        """获取指定分类的 TTL。"""
        ttl_map = {
            MemoryCategory.SESSION.value: self.ttl_session,
            MemoryCategory.SHORT_TERM.value: self.ttl_short_term,
            MemoryCategory.LONG_TERM.value: self.ttl_long_term,
            MemoryCategory.FACT.value: self.ttl_fact,
            MemoryCategory.PREFERENCE.value: self.ttl_preference,
            MemoryCategory.AUDIT_CONCLUSION.value: self.ttl_audit_conclusion,
        }
        return ttl_map.get(category, self.ttl_fact)
