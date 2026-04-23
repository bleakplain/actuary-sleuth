"""Mem0 VectorStoreBase 的 LanceDB 实现。

将 user_id / agent_id / run_id 作为顶级列存储，
解决 LangChain LanceDB adapter 把 metadata 嵌套为 struct 导致过滤失败的问题。
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

import lancedb
import numpy as np
import pyarrow as pa
from pydantic import BaseModel

from mem0.vector_stores.base import VectorStoreBase


class OutputData(BaseModel):
    id: Optional[str] = None
    score: Optional[float] = None
    payload: Optional[Dict[str, Any]] = None


logger = logging.getLogger(__name__)

_FILTER_COLUMNS = ("user_id", "agent_id", "run_id")
_DEFAULT_VECTOR_SIZE = 1024

_init_lock = threading.Lock()


def _escape_value(value: str) -> str:
    """SQL 字符串转义：单引号转义为两个单引号（ANSI SQL 标准）。"""
    if not isinstance(value, str):
        raise TypeError(f"过滤值必须是字符串，得到: {type(value).__name__}")
    return value.replace("'", "''")


class LanceDBMemoryStore(VectorStoreBase):

    def __init__(self, uri: str, table_name: str = "memories", vector_size: int = _DEFAULT_VECTOR_SIZE):
        self._db = lancedb.connect(uri)
        self._table_name = table_name
        self._vector_size = vector_size
        self._tbl: Optional[lancedb.table.LanceTable] = None

    def _schema(self) -> pa.Schema:
        fields = [
            pa.field("vector", pa.list_(pa.float32(), self._vector_size)),
            pa.field("id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("metadata", pa.string()),
        ]
        for col in _FILTER_COLUMNS:
            fields.append(pa.field(col, pa.string()))
        return pa.schema(fields)

    def _get_table(self) -> lancedb.table.LanceTable:
        if self._tbl is None:
            with _init_lock:
                if self._tbl is None:
                    if self._table_name in self._db.table_names():
                        self._tbl = self._db.open_table(self._table_name)
                    else:
                        self._tbl = self._db.create_table(self._table_name, schema=self._schema())
        return self._tbl

    @staticmethod
    def _to_row(vector: List[float], doc_id: str, payload: Dict) -> Dict[str, Any]:
        filter_vals = {k: payload.get(k, "") for k in _FILTER_COLUMNS}
        return {
            "vector": np.array(vector, dtype=np.float32),
            "id": doc_id,
            "text": payload.get("data", ""),
            "metadata": json.dumps(payload, ensure_ascii=False, default=str),
            **filter_vals,
        }

    @staticmethod
    def _build_where(filters: Optional[Dict]) -> Optional[str]:
        if not filters:
            return None
        parts = []
        for k, v in filters.items():
            if k in _FILTER_COLUMNS and v:
                parts.append(f"{k} = '{_escape_value(str(v))}'")
        return " AND ".join(parts) if parts else None

    def create_col(self, name: str, vector_size: Optional[int] = None) -> None:
        pass

    def insert(self, vectors: List[List[float]], payloads: Optional[List[Dict]] = None, ids: Optional[List[str]] = None):
        tbl = self._get_table()
        rows = []
        for i, vec in enumerate(vectors):
            pid = ids[i] if ids else str(i)
            payload = (payloads[i] if payloads else {}).copy()
            rows.append(self._to_row(vec, pid, payload))
        tbl.add(rows)

    def search(self, query: str, vectors: List[List[float]], limit: int = 5, filters: Optional[Dict] = None, **kwargs):
        tbl = self._get_table()
        where = self._build_where(filters)
        vec = vectors[0] if isinstance(vectors[0], list) else vectors
        q = tbl.search(np.array(vec, dtype=np.float32)).limit(kwargs.get("top_k", limit))
        if where:
            q = q.where(where)
        results = q.to_arrow()
        out = []
        for i in range(len(results)):
            mid = results["id"][i].as_py()
            meta_raw = results["metadata"][i].as_py()
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
            score = results["_distance"][i].as_py() if "_distance" in results.column_names else None
            out.append(OutputData(id=mid, score=score, payload=meta))
        return out

    def delete(self, vector_id: str):
        tbl = self._get_table()
        tbl.delete(f"id = '{_escape_value(vector_id)}'")

    def update(self, vector_id: str, vector: Optional[List[float]] = None, payload: Optional[Dict] = None):
        tbl = self._get_table()
        values: Dict[str, Any] = {}
        if vector:
            values["vector"] = np.array(vector, dtype=np.float32)
        if payload:
            filter_vals = {k: payload.get(k, "") for k in _FILTER_COLUMNS}
            values["metadata"] = json.dumps(payload, ensure_ascii=False, default=str)
            values["text"] = payload.get("data", "")
            values.update(filter_vals)
        if values:
            tbl.update(where=f"id = '{_escape_value(vector_id)}'", values=values)

    def get(self, vector_id: str) -> Optional[OutputData]:
        tbl = self._get_table()
        results = tbl.search().where(f"id = '{_escape_value(vector_id)}'").limit(1).to_arrow()
        if len(results) == 0:
            return None
        meta_raw = results["metadata"][0].as_py()
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        return OutputData(id=results["id"][0].as_py(), score=None, payload=meta)

    def list_cols(self) -> List[str]:
        return [self._table_name]

    def delete_col(self):
        self._db.drop_table(self._table_name)
        self._tbl = None

    def col_info(self) -> Dict[str, Any]:
        tbl = self._get_table()
        return {"name": self._table_name, "count": tbl.count_rows()}

    def list(self, filters: Optional[Dict] = None, limit: Optional[int] = None, **kwargs):
        tbl = self._get_table()
        where = self._build_where(filters)
        q = tbl.search().limit(kwargs.get("top_k", limit or 100))
        if where:
            q = q.where(where)
        results = q.to_arrow()
        out = []
        for i in range(len(results)):
            meta_raw = results["metadata"][i].as_py()
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
            out.append(OutputData(id=results["id"][i].as_py(), score=None, payload=meta))
        return out

    def reset(self):
        self._db.drop_table(self._table_name)
        self._tbl = self._db.create_table(self._table_name, schema=self._schema())
