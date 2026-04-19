"""记忆后端抽象基类 + Mem0 实现。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _precheck() -> None:
    for pkg in ("mem0", "lancedb"):
        try:
            __import__(pkg)
        except ImportError:
            raise ImportError(f"缺少依赖包: {pkg}")


class MemoryBase(ABC):

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
        """创建 Mem0 后端，预检失败返回 None（降级模式）。"""
        try:
            _precheck()

            from mem0 import Memory
            from pathlib import Path

            from lib.config import get_qa_llm_config, get_embed_llm_config
            from lib.memory.prompts import AUDIT_FACT_EXTRACTION_PROMPT

            qa_cfg = get_qa_llm_config()
            embed_cfg = get_embed_llm_config()
            lancedb_path = str(Path("./data/lancedb").resolve())

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
                raise ValueError(f"不支持的记忆LLM provider: {llm_provider}")

            config = {
                "llm": llm_config,
                "embedder": {
                    "provider": "ollama",
                    "config": {
                        "model": embed_cfg.model,
                        "ollama_base_url": embed_cfg.base_url,
                    }
                },
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
        items = result.get("results", [])
        if isinstance(items, list):
            return [item["id"] for item in items if "id" in item]
        return []

    def delete(self, memory_id: str) -> None:
        self._memory.delete(memory_id)

    def get_all(self, user_id: str) -> List[Dict]:
        result = self._memory.get_all(user_id=user_id)
        return result.get("results", [])
