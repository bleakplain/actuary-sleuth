"""记忆服务 — 后端抽象 + 降级 + 活跃度管理 + 用户画像。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol

from lib.common.database import get_connection
from lib.config import get_memory_config
from lib.memory.base import MemoryBase, Mem0Memory
from lib.memory.prompts import PROFILE_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class UserProfileUpdateRequest(Protocol):
    focus_areas: Optional[List[str]]
    preference_tags: Optional[List[str]]
    summary: Optional[str]


class MemoryService:

    def __init__(self, backend: Optional[MemoryBase] = None):
        self._backend = backend
        self._available = backend is not None
        config = get_memory_config()
        self._ttl_days = config.ttl_days
        self._dedup_threshold = config.similarity_threshold
        self._profile_confidence_threshold = config.confidence_threshold

    @classmethod
    def create(cls) -> "MemoryService":
        backend = Mem0Memory.create()
        return cls(backend)

    @property
    def available(self) -> bool:
        return self._available

    def search(self, query: str, user_id: str, limit: Optional[int] = None) -> List[Dict]:
        if not self._available:
            return []
        try:
            memories = self._backend.search(query, user_id, limit or 3)
            self._update_access_stats([m["id"] for m in memories if "id" in m])
            return memories
        except Exception:
            logger.debug("记忆检索失败", exc_info=True)
            return []

    def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
        if not self._available:
            return []
        try:
            query = messages[-1].get("content", "") if messages else ""
            if query:
                similar = self._backend.search(query, user_id, limit=1)
                if similar and similar[0].get("score", 0) > self._dedup_threshold:
                    logger.debug(f"跳过重复记忆: {query[:50]}")
                    return []

            session_id = (metadata or {}).get("session_id")
            ids = self._backend.add(messages, user_id, metadata=metadata or {}, run_id=session_id)
            if not ids:
                return []

            failed_ids = []
            for mid in ids:
                try:
                    self._insert_metadata(mid, user_id, metadata)
                except Exception:
                    logger.warning(f"元数据写入失败: {mid}", exc_info=True)
                    failed_ids.append(mid)

            if failed_ids:
                for mid in failed_ids:
                    try:
                        self._backend.delete(mid)
                    except Exception:
                        logger.warning(f"回滚向量记录失败: {mid}")
                ids = [mid for mid in ids if mid not in failed_ids]

            return ids
        except Exception:
            logger.debug("记忆写入失败", exc_info=True)
            return []

    def delete(self, memory_id: str) -> bool:
        if not self._available:
            return False
        try:
            self._soft_delete_metadata(memory_id)
            try:
                self._backend.delete(memory_id)
            except Exception:
                self._restore_metadata(memory_id)
                raise
            return True
        except Exception:
            logger.debug(f"记忆删除失败: {memory_id}", exc_info=True)
            return False

    def get_all(self, user_id: str) -> List[Dict]:
        if not self._available:
            return []
        try:
            return self._backend.get_all(user_id)
        except Exception:
            logger.debug("获取全部记忆失败", exc_info=True)
            return []

    def cleanup_expired(self) -> int:
        if not self._available:
            return 0
        cleaned = 0

        try:
            with get_connection() as conn:
                now = datetime.now().isoformat()
                expired = conn.execute(
                    "SELECT mem0_id FROM memory_metadata "
                    "WHERE expires_at IS NOT NULL AND expires_at < ? AND is_deleted = 0",
                    (now,),
                ).fetchall()
                cleaned += self._purge_memories(expired)

                threshold = (datetime.now() - timedelta(days=60)).isoformat()
                inactive = conn.execute(
                    "SELECT mem0_id FROM memory_metadata "
                    "WHERE last_accessed_at < ? AND access_count = 0 AND is_deleted = 0",
                    (threshold,),
                ).fetchall()
                cleaned += self._purge_memories(inactive)
        except Exception:
            logger.debug("记忆清理失败", exc_info=True)

        return cleaned

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT focus_areas, preference_tags, summary FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "user_id": user_id,
                    "focus_areas": json.loads(row[0]),
                    "preference_tags": json.loads(row[1]),
                    "summary": row[2],
                }
        except Exception:
            logger.debug(f"获取用户画像失败: {user_id}", exc_info=True)
            return None

    def patch_user_profile(self, req: UserProfileUpdateRequest, user_id: str) -> Dict[str, Any]:
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT focus_areas, preference_tags, summary FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if not existing:
                raise ValueError(f"用户画像不存在: {user_id}")

            focus_areas = json.loads(existing[0]) if req.focus_areas is None else req.focus_areas
            preference_tags = json.loads(existing[1]) if req.preference_tags is None else req.preference_tags
            summary = existing[2] if req.summary is None else req.summary

            conn.execute(
                "UPDATE user_profiles SET focus_areas = ?, preference_tags = ?, summary = ?, updated_at = datetime('now') "
                "WHERE user_id = ?",
                (json.dumps(focus_areas), json.dumps(preference_tags), summary, user_id),
            )

        return {"user_id": user_id, "focus_areas": focus_areas, "preference_tags": preference_tags, "summary": summary}

    def update_user_profile(self, question: str, answer: str, user_id: str) -> None:
        try:
            from lib.llm.factory import LLMClientFactory

            llm = LLMClientFactory.create_qa_llm()
            prompt = PROFILE_EXTRACTION_PROMPT.format(question=question, answer=answer)
            raw = str(llm.chat([{"role": "user", "content": prompt}]))
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0] if "```" in text else text
            extracted = json.loads(text)
        except Exception:
            logger.debug("用户画像提取失败", exc_info=True)
            return

        if extracted.get("confidence", 0.5) < self._profile_confidence_threshold:
            return

        focus_areas = extracted.get("focus_areas", [])
        preference_tags = extracted.get("preference_tags", [])
        summary = extracted.get("summary", "")

        if not focus_areas and not preference_tags and not summary:
            return

        try:
            with get_connection() as conn:
                existing = conn.execute(
                    "SELECT focus_areas, preference_tags FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()

                merged_areas = list({*json.loads(existing[0]), *focus_areas}) if existing else focus_areas
                merged_tags = list({*json.loads(existing[1]), *preference_tags}) if existing else preference_tags

                conn.execute(
                    "INSERT OR REPLACE INTO user_profiles (user_id, focus_areas, preference_tags, summary, updated_at) "
                    "VALUES (?, ?, ?, ?, datetime('now'))",
                    (user_id, json.dumps(merged_areas), json.dumps(merged_tags), summary),
                )
        except Exception:
            logger.debug("用户画像写入失败", exc_info=True)

    def _purge_memories(self, rows: List[tuple]) -> int:
        count = 0
        for (mem_id,) in rows:
            try:
                self._backend.delete(mem_id)
                self._soft_delete_metadata(mem_id)
                count += 1
            except Exception:
                logger.debug(f"清理记忆失败: {mem_id}", exc_info=True)
        return count

    def _update_access_stats(self, memory_ids: List[str]) -> None:
        if not memory_ids:
            return
        try:
            placeholders = ",".join("?" * len(memory_ids))
            sql = f"UPDATE memory_metadata SET last_accessed_at = datetime('now'), access_count = access_count + 1 WHERE mem0_id IN ({placeholders})"
            with get_connection() as conn:
                conn.execute(sql, memory_ids)
        except Exception:
            logger.debug("更新访问统计失败", exc_info=True)

    def _insert_metadata(self, mem0_id: str, user_id: str, metadata: Optional[Dict]) -> None:
        expires_at = (datetime.now() + timedelta(days=self._ttl_days)).isoformat() if self._ttl_days > 0 else None
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memory_metadata (mem0_id, user_id, session_id, category, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (mem0_id, user_id, (metadata or {}).get("session_id"), (metadata or {}).get("category", "fact"), expires_at),
            )

    def _soft_delete_metadata(self, mem0_id: str) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE memory_metadata SET is_deleted = 1 WHERE mem0_id = ?", (mem0_id,))

    def _restore_metadata(self, mem0_id: str) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE memory_metadata SET is_deleted = 0 WHERE mem0_id = ?", (mem0_id,))