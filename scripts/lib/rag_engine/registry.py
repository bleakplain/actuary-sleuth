"""法规注册表。

按"法规"为单位（而非"条款"）聚合元数据，支持目录/计数/元数据查询。
数据从 LanceDB chunk metadata 现查现聚合，避免单独维护文件。
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegulationEntry:
    """单个法规的聚合信息。"""
    law_name: str
    collection: str
    source_file: str
    article_count: int


class RegulationRegistry:
    """法规注册表，按 law_name 聚合 chunk metadata。"""

    def __init__(self, vector_db_path: str, collection_name: str = "regulations_vectors"):
        self._vector_db_path = vector_db_path
        self._collection_name = collection_name
        self._entries: Optional[List[RegulationEntry]] = None

    def _load(self) -> List[RegulationEntry]:
        """从 LanceDB 聚合所有法规的元数据。"""
        if self._entries is not None:
            return self._entries

        try:
            import lancedb
            db = lancedb.connect(self._vector_db_path)
            table = db.open_table(self._collection_name)
            rows = table.search().limit(10000).to_list()
        except Exception as e:
            logger.warning(f"加载法规注册表失败: {e}")
            self._entries = []
            return self._entries

        agg: Dict[str, Dict] = {}
        for row in rows:
            meta = row.get("metadata", {})
            if isinstance(meta, str):
                import json
                try:
                    meta = json.loads(meta)
                except Exception:
                    continue
            law = (meta.get("law_name") or "").strip()
            if not law:
                continue
            if law not in agg:
                agg[law] = {
                    "law_name": law,
                    "collection": meta.get("category", "") or meta.get("collection", ""),
                    "source_file": meta.get("source_file", ""),
                    "seen_chunk_ids": set(),
                }
            entry = agg[law]
            # 用 chunk_id 去重计数（同一 chunk 不会重复出现）
            chunk_id = meta.get("chunk_id")
            if chunk_id is not None and chunk_id not in entry["seen_chunk_ids"]:
                entry["seen_chunk_ids"].add(chunk_id)

        self._entries = [
            RegulationEntry(
                law_name=e["law_name"],
                collection=e["collection"],
                source_file=e["source_file"],
                article_count=len(e["seen_chunk_ids"]),
            )
            for e in agg.values()
        ]
        self._entries.sort(key=lambda x: (x.collection, x.law_name))
        logger.info(f"法规注册表加载完成: {len(self._entries)} 部法规")
        return self._entries

    def list_all(self) -> List[RegulationEntry]:
        return self._load()

    def count(self) -> int:
        return len(self._load())

    def total_articles(self) -> int:
        return sum(e.article_count for e in self._load())

    def filter_by_keyword(self, keyword: str) -> List[RegulationEntry]:
        """按法规名关键词过滤。"""
        kw = keyword.strip().lower()
        if not kw:
            return self._load()
        return [e for e in self._load() if kw in e.law_name.lower()]

    def find_by_name(self, law_name: str) -> Optional[RegulationEntry]:
        """模糊匹配法规名。"""
        target = law_name.strip()
        if not target:
            return None
        # 精确匹配优先
        for e in self._load():
            if e.law_name == target:
                return e
        # 包含匹配
        candidates = [e for e in self._load() if target in e.law_name or e.law_name in target]
        return candidates[0] if candidates else None

    def group_by_collection(self) -> Dict[str, List[RegulationEntry]]:
        grouped: Dict[str, List[RegulationEntry]] = {}
        for e in self._load():
            grouped.setdefault(e.collection or "其他", []).append(e)
        return grouped


def format_registry_context(
    intent: str,
    registry: RegulationRegistry,
    law_name: Optional[str] = None,
) -> str:
    """根据意图格式化法规清单为 LLM 可读的上下文文本。"""
    if intent == "count":
        total = registry.count()
        articles = registry.total_articles()
        groups = registry.group_by_collection()
        lines = [f"知识库共收录 {total} 部法规，合计 {articles} 个条款单元，按分类分布："]
        for cat, entries in sorted(groups.items()):
            lines.append(f"- {cat or '其他'}：{len(entries)} 部")
        return "\n".join(lines)

    if intent == "metadata":
        if not law_name:
            return "未识别到具体的法规名称。"
        entry = registry.find_by_name(law_name)
        if not entry:
            return f"未找到名称包含「{law_name}」的法规。"
        lines = [
            f"法规名称：{entry.law_name}",
            f"所属分类：{entry.collection or '未分类'}",
            f"源文件：{entry.source_file}",
            f"条款单元数：{entry.article_count}",
        ]
        return "\n".join(lines)

    # catalog（默认）
    groups = registry.group_by_collection()
    lines = [f"当前知识库共收录 {registry.count()} 部法规，按分类列出："]
    for cat, entries in sorted(groups.items()):
        lines.append(f"\n【{cat or '其他'}】({len(entries)} 部)")
        for e in entries:
            lines.append(f"  - {e.law_name}（{e.article_count} 个条款单元）")
    return "\n".join(lines)
