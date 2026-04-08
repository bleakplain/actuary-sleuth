"""记忆服务 — 后端抽象 + 降级 + 活跃度管理 + 用户画像。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from lib.common.database import get_connection
from lib.llm.factory import LLMClientFactory
from lib.memory.base import MemoryBase, Mem0Memory
from lib.memory.config import MemoryConfig
from lib.memory.prompts import PROFILE_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class MemoryService:
    """记忆服务层 — 面向抽象能力（记忆），不绑定具体实现。"""

    def __init__(self, backend: Optional[MemoryBase] = None):
        self._backend = backend
        self._available = backend is not None
        self._config = MemoryConfig() if self._available else None

    @classmethod
    def create(cls) -> "MemoryService":
        """创建记忆服务，后端初始化失败时降级为无记忆模式。"""
        backend = Mem0Memory.create()
        return cls(backend)

    @property
    def available(self) -> bool:
        return self._available

    def search(self, query: str, user_id: str, limit: int = 3) -> List[Dict]:
        """检索与查询相关的用户记忆。"""
        if not self._available:
            return []
        try:
            memories = self._backend.search(query, user_id, limit)
            self._update_access_stats([m["id"] for m in memories if "id" in m])
            return memories
        except Exception:
            logger.debug("记忆检索失败", exc_info=True)
            return []

    def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
        """写入记忆。"""
        if not self._available:
            return []
        try:
            session_id = (metadata or {}).get("session_id")
            ids = self._backend.add(messages, user_id, metadata=metadata or {}, run_id=session_id)
            for mid in ids:
                self._insert_metadata(mid, user_id, metadata)
            return ids
        except Exception:
            logger.debug("记忆写入失败", exc_info=True)
            return []

    def delete(self, memory_id: str) -> bool:
        """删除记忆。"""
        if not self._available:
            return False
        try:
            self._backend.delete(memory_id)
            self._soft_delete_metadata(memory_id)
            return True
        except Exception:
            return False

    def get_all(self, user_id: str) -> List[Dict]:
        """获取用户全部记忆。"""
        if not self._available:
            return []
        try:
            return self._backend.get_all(user_id)
        except Exception:
            return []

    def cleanup_expired(self) -> int:
        """清理过期记忆 + 活跃度衰减清理。"""
        if not self._available or not self._config:
            return 0
        cfg = self._config
        cleaned = 0

        try:
            with self._get_conn() as conn:
                now = datetime.now().isoformat()
                expired = conn.execute(
                    "SELECT mem0_id FROM memory_metadata "
                    "WHERE expires_at IS NOT NULL AND expires_at < ? AND is_deleted = 0",
                    (now,),
                ).fetchall()
                cleaned += self._purge_memories(expired)

                threshold = (datetime.now() - timedelta(days=cfg.inactive_threshold_days)).isoformat()
                inactive = conn.execute(
                    "SELECT mem0_id FROM memory_metadata "
                    "WHERE last_accessed_at < ? AND access_count = 0 AND is_deleted = 0",
                    (threshold,),
                ).fetchall()
                cleaned += self._purge_memories(inactive)

        except Exception:
            logger.debug("记忆清理失败", exc_info=True)

        return cleaned

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户画像。"""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT focus_areas, preference_tags, audit_stats, summary FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "user_id": user_id,
                    "focus_areas": json.loads(row[0]),
                    "preference_tags": json.loads(row[1]),
                    "audit_stats": json.loads(row[2]),
                    "summary": row[3],
                }
        except Exception:
            return None

    def update_profile(self, question: str, answer: str, user_id: str) -> None:
        """增量更新用户画像。"""
        try:
            extracted = self._extract_profile_tags(question, answer)
            new_areas = extracted.get("focus_areas", [])
            new_tags = extracted.get("preference_tags", [])

            with self._get_conn() as conn:
                existing = conn.execute(
                    "SELECT focus_areas, preference_tags, audit_stats FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()

                if existing:
                    focus_areas = json.loads(existing[0])
                    preference_tags = json.loads(existing[1])
                    audit_stats = json.loads(existing[2])
                else:
                    focus_areas, preference_tags, audit_stats = [], [], {}

                focus_areas = list(set(focus_areas) | set(new_areas))
                preference_tags = list(set(preference_tags) | set(new_tags))
                audit_stats["total_audits"] = audit_stats.get("total_audits", 0) + 1

                conn.execute(
                    "INSERT INTO user_profiles (user_id, focus_areas, preference_tags, audit_stats, updated_at) "
                    "VALUES (?, ?, ?, ?, datetime('now')) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "focus_areas = excluded.focus_areas, "
                    "preference_tags = excluded.preference_tags, "
                    "audit_stats = excluded.audit_stats, "
                    "updated_at = excluded.updated_at",
                    (user_id, json.dumps(focus_areas), json.dumps(preference_tags), json.dumps(audit_stats)),
                )
        except Exception:
            logger.debug("用户画像更新失败", exc_info=True)

    def _extract_profile_tags(self, question: str, answer: str) -> Dict:
        """用 LLM 从对话中提取关注领域和偏好标签。"""
        try:
            llm = LLMClientFactory.create_qa_llm()
            prompt = f"{PROFILE_EXTRACTION_PROMPT}\n\nInput:\n用户: {question}\n助手: {answer}\nOutput: "
            result = llm.generate(prompt)
            text = str(result).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except Exception:
            logger.debug("画像标签提取失败", exc_info=True)
            return {"focus_areas": [], "preference_tags": []}

    def _purge_memories(self, rows) -> int:
        count = 0
        for (mem_id,) in rows:
            try:
                self._backend.delete(mem_id)
                self._soft_delete_metadata(mem_id)
                count += 1
            except Exception:
                pass
        return count

    def _get_conn(self):
        return get_connection()

    def _update_access_stats(self, memory_ids: List[str]) -> None:
        if not memory_ids:
            return
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE memory_metadata SET last_accessed_at = datetime('now'), "
                    "access_count = access_count + 1 WHERE mem0_id IN ({})".format(
                        ",".join("?" for _ in memory_ids)
                    ),
                    memory_ids,
                )
        except Exception:
            pass

    def _insert_metadata(self, mem0_id: str, user_id: str, metadata: Optional[Dict]) -> None:
        if not self._config:
            return
        category = (metadata or {}).get("category", "fact")

        cfg = self._config
        ttl_map = {
            "fact": cfg.ttl_fact,
            "preference": cfg.ttl_preference,
            "audit_conclusion": cfg.ttl_audit_conclusion,
        }
        ttl_days = ttl_map.get(category, cfg.ttl_fact)
        expires_at = None
        if ttl_days > 0:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()

        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO memory_metadata (mem0_id, user_id, session_id, category, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (mem0_id, user_id, (metadata or {}).get("session_id"), category, expires_at),
                )
        except Exception:
            pass

    def _soft_delete_metadata(self, mem0_id: str) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE memory_metadata SET is_deleted = 1 WHERE mem0_id = ?", (mem0_id,)
                )
        except Exception:
            pass
