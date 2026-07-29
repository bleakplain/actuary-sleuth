"""知识库目录的稳定身份计算。

目录身份必须同时覆盖物理 chunk ID、正文、来源定位和业务元数据。这里集中
实现规范化，避免构建端和审核端各自计算出不同的指纹。
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

_INTEGER_METADATA_KEYS = {
    "chunk_id",
    "chunk_index",
    "level",
    "next_chunk_id",
    "parent_chunk_id",
    "prev_chunk_id",
}


def sha256_file(path: Path) -> str:
    """流式计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    value = candidate.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _value(candidate: Mapping[str, Any], key: str, default: Any = "") -> Any:
    value = candidate.get(key)
    if value not in (None, ""):
        return value
    return _metadata(candidate).get(key, default)


def _canonical_metadata_value(key: str, value: Any) -> Any:
    """消除 Arrow/Pandas 对 nullable 数字造成的序列化漂移。"""
    if isinstance(value, float) and math.isnan(value):
        return None
    if key in _INTEGER_METADATA_KEYS and isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): _canonical_metadata_value(
                str(child_key),
                child_value,
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _canonical_metadata_value(key, child_value)
            for child_value in value
        ]
    return value


def stable_catalog_sha256(
    catalog: Iterable[Mapping[str, Any]],
) -> str:
    """冻结全局 chunk 身份、正文、定位和全部业务元数据。"""
    rows = []
    for candidate in catalog:
        metadata = {
            str(key): _canonical_metadata_value(str(key), value)
            for key, value in _metadata(candidate).items()
            if not str(key).startswith("_")
        }
        rows.append({
            "id": str(candidate.get("id", "")),
            "content": str(_value(candidate, "content", "")),
            "location": {
                key: _value(candidate, key, "")
                for key in (
                    "source_file",
                    "law_name",
                    "article_number",
                    "section_path",
                    "hierarchy_path",
                    "chunk_index",
                    "chunk_id",
                )
            },
            "metadata": metadata,
        })
    canonical = json.dumps(
        sorted(rows, key=lambda row: str(row["id"])),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stable_node_content_sha256(
    nodes: Iterable[Mapping[str, Any]],
) -> str:
    """冻结节点 ID 与正文，用于验证不同索引承载的是同一批 chunk。"""
    rows = [
        {
            "id": str(candidate.get("id", "")),
            "content": str(_value(candidate, "content", "")),
        }
        for candidate in nodes
    ]
    canonical = json.dumps(
        sorted(
            rows,
            key=lambda row: (str(row["id"]), str(row["content"])),
        ),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
