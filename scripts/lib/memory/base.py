"""记忆后端抽象基类 + Mem0 实现。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryBase(ABC):
    """记忆后端抽象接口 — 定义记忆的增删查能力。"""

    @abstractmethod
    def search(self, query: str, user_id: str, limit: int = 3) -> List[Dict]:
        """检索与查询相关的用户记忆。"""
        ...

    @abstractmethod
    def add(
        self,
        messages: List[Dict],
        user_id: str,
        metadata: Optional[Dict] = None,
        run_id: Optional[str] = None,
    ) -> List[str]:
        """写入记忆，返回记忆 ID 列表。"""
        ...

    @abstractmethod
    def delete(self, memory_id: str) -> None:
        """删除单条记忆。"""
        ...

    @abstractmethod
    def get_all(self, user_id: str) -> List[Dict]:
        """获取用户全部记忆。"""
        ...


class Mem0Memory(MemoryBase):
    """基于 Mem0 的记忆后端实现。"""

    def __init__(self, memory: Any):
        self._memory = memory

    @classmethod
    def create(cls) -> Optional[Mem0Memory]:
        """创建 Mem0 后端，初始化失败返回 None。"""
        try:
            from mem0 import Memory
            from langchain_community.vectorstores import LanceDB as LCLanceDB

            from lib.config import get_config
            from lib.memory.embeddings import EmbeddingBridge
            from lib.memory.prompts import AUDIT_FACT_EXTRACTION_PROMPT

            cfg = get_config()
            qa_cfg = cfg.qa

            embedding_lc = EmbeddingBridge()
            lancedb_store = LCLanceDB(
                uri="./data/lancedb",
                table_name="memories",
                embedding=embedding_lc,
            )

            base_url = qa_cfg.get("base_url", "").rstrip("/")
            config = {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": qa_cfg.get("model", "glm-4-flash"),
                        "api_key": qa_cfg.get("api_key"),
                        "openai_base_url": base_url,
                        "temperature": 0.1,
                    }
                },
                "embedder": {
                    "provider": "langchain",
                    "config": {"model": embedding_lc}
                },
                "vector_store": {
                    "provider": "langchain",
                    "config": {"client": lancedb_store}
                },
                "custom_fact_extraction_prompt": AUDIT_FACT_EXTRACTION_PROMPT,
                "version": "v1.1",
            }
            memory = Memory.from_config(config)
            logger.info("Mem0 初始化成功")
            return cls(memory)
        except Exception as e:
            logger.warning(f"Mem0 初始化失败，运行无记忆模式: {e}")
            return None

    def search(self, query: str, user_id: str, limit: int = 3) -> List[Dict]:
        result = self._memory.search(query, user_id=user_id, limit=limit)
        return result.get("results", [])

    def add(
        self,
        messages: List[Dict],
        user_id: str,
        metadata: Optional[Dict] = None,
        run_id: Optional[str] = None,
    ) -> List[str]:
        result = self._memory.add(
            messages, user_id=user_id, metadata=metadata or {}, run_id=run_id,
        )
        return result.get("results", {}).get("ids", [])

    def delete(self, memory_id: str) -> None:
        self._memory.delete(memory_id)

    def get_all(self, user_id: str) -> List[Dict]:
        result = self._memory.get_all(user_id=user_id)
        return result.get("results", [])
