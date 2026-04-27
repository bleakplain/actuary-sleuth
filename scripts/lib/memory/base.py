"""记忆后端抽象基类 + Mem0 实现。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryBase(ABC):

    @abstractmethod
    def search(self, query: str, user_id: str, limit: int = 3) -> List[Dict]:
        ...

    @abstractmethod
    def add(
        self,
        messages: List[Dict],
        user_id: str,
        metadata: Optional[Dict] = None,
        run_id: Optional[str] = None,
    ) -> List[str]:
        ...

    @abstractmethod
    def delete(self, memory_id: str) -> None:
        ...

    @abstractmethod
    def get_all(self, user_id: str) -> List[Dict]:
        ...


class Mem0Memory(MemoryBase):
    """基于 Mem0 的记忆后端实现。"""

    def __init__(self, memory: Any):
        self._memory = memory

    @classmethod
    def create(cls) -> Optional[Mem0Memory]:
        try:
            for pkg in ("mem0", "lancedb"):
                __import__(pkg)

            from mem0 import Memory

            from lib.config import get_qa_llm_config, get_embed_llm_config, get_memory_dir
            from lib.memory.prompts import AUDIT_FACT_EXTRACTION_PROMPT

            qa_cfg = get_qa_llm_config()
            embed_cfg = get_embed_llm_config()
            memory_dir = Path(get_memory_dir())
            memory_dir.mkdir(parents=True, exist_ok=True)
            lancedb_path = str(memory_dir / "lancedb")
            qdrant_path = str(memory_dir / "qdrant")

            llm_provider = qa_cfg.provider
            if llm_provider == "ollama":
                llm_config = {
                    "provider": "ollama",
                    "config": {
                        "model": qa_cfg.model,
                        "ollama_base_url": qa_cfg.base_url,
                        "temperature": qa_cfg.temperature,
                    }
                }
            elif llm_provider == "zhipu":
                llm_config = {
                    "provider": "openai",
                    "config": {
                        "model": qa_cfg.model,
                        "api_key": qa_cfg.api_key,
                        "openai_base_url": qa_cfg.base_url,
                        "temperature": qa_cfg.temperature,
                    }
                }
            else:
                raise ValueError(f"不支持的 LLM provider: {llm_provider}")

            config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {"path": qdrant_path, "collection_name": "mem0_memories"}
                },
                "llm": llm_config,
                "embedder": {
                    "provider": "ollama",
                    "config": {"model": embed_cfg.model, "ollama_base_url": embed_cfg.base_url}
                },
                "history_db_path": str(memory_dir / "history.db"),
                "custom_fact_extraction_prompt": AUDIT_FACT_EXTRACTION_PROMPT,
                "version": "v1.1",
            }
            memory = Memory.from_config(config)

            from lib.memory.vector_store import LanceDBMemoryStore
            memory.vector_store = LanceDBMemoryStore(lancedb_path, "memories", vector_size=1024)

            logger.info("Mem0 初始化成功")
            return cls(memory)
        except Exception as e:
            logger.warning(f"Mem0 初始化失败，运行无记忆模式: {e}")
            return None

    def search(self, query: str, user_id: str, limit: int = 3) -> List[Dict]:
        result = self._memory.search(query, limit=limit, filters={"user_id": user_id})
        return result.get("results", [])

    def add(
        self,
        messages: List[Dict],
        user_id: str,
        metadata: Optional[Dict] = None,
        run_id: Optional[str] = None,
    ) -> List[str]:
        result = self._memory.add(messages, user_id=user_id, metadata=metadata or {}, run_id=run_id)
        items = result.get("results", [])
        return [item["id"] for item in items if "id" in item] if isinstance(items, list) else []

    def delete(self, memory_id: str) -> None:
        self._memory.delete(memory_id)

    def get_all(self, user_id: str) -> List[Dict]:
        result = self._memory.get_all(filters={"user_id": user_id})
        return result.get("results", [])
