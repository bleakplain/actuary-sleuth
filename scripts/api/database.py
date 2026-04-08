"""API 数据库层 — 建表 DDL 和数据访问函数。

复用 lib.common.database.get_connection() 连接池，
不创建独立连接。
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, List, Dict

from lib.common.database import get_connection


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL DEFAULT '',
    citations_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

CREATE TABLE IF NOT EXISTS eval_samples (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    ground_truth TEXT NOT NULL DEFAULT '',
    evidence_docs_json TEXT NOT NULL DEFAULT '[]',
    evidence_keywords_json TEXT NOT NULL DEFAULT '[]',
    question_type TEXT NOT NULL DEFAULT 'factual',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    topic TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eval_snapshots (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sample_count INTEGER NOT NULL DEFAULT 0,
    samples_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode IN ('retrieval', 'generation', 'full', 'llm_judge')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    progress INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    report_json TEXT
);

CREATE TABLE IF NOT EXISTS eval_sample_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    sample_id TEXT NOT NULL,
    retrieved_docs_json TEXT NOT NULL DEFAULT '[]',
    generated_answer TEXT NOT NULL DEFAULT '',
    retrieval_metrics_json TEXT NOT NULL DEFAULT '{}',
    generation_metrics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_sample_results(run_id);

CREATE TABLE IF NOT EXISTS eval_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS human_reviews (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    sample_id TEXT NOT NULL,
    reviewer TEXT NOT NULL DEFAULT '',
    faithfulness_score REAL,
    correctness_score REAL,
    relevancy_score REAL,
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_human_reviews_eval ON human_reviews(evaluation_id);

CREATE TABLE IF NOT EXISTS compliance_reports (
    id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL CHECK(mode IN ('product', 'document')),
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    rating TEXT NOT NULL CHECK(rating IN ('up', 'down')),
    reason TEXT NOT NULL DEFAULT '',
    correction TEXT DEFAULT '',
    source_channel TEXT NOT NULL DEFAULT 'user_button',
    auto_quality_score REAL,
    auto_quality_details_json TEXT,
    classified_type TEXT,
    classified_reason TEXT,
    classified_fix_direction TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'classified', 'fixing', 'fixed', 'rejected', 'converted')),
    compliance_risk INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(classified_type);

CREATE TABLE IF NOT EXISTS kb_versions (
    version_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    regulations_dir TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    message_id INTEGER,
    conversation_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_traces_trace_id ON traces(trace_id);

CREATE TABLE IF NOT EXISTS spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    input_json TEXT,
    output_json TEXT,
    metadata_json TEXT DEFAULT '{}',
    start_time REAL NOT NULL,
    end_time REAL,
    duration_ms REAL,
    status TEXT NOT NULL DEFAULT 'ok' CHECK(status IN ('ok', 'error')),
    error TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_spans_trace_span ON spans(trace_id, span_id);
CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_parent ON spans(parent_span_id);
"""


def _deserialize_json_fields(row: dict, mappings: Dict[str, str]) -> dict:
    for python_name, db_column in mappings.items():
        val = row.pop(db_column, None)
        if val is not None:
            row[python_name] = json.loads(val)
    return row


_MSG_JSON_FIELDS = {"citations": "citations_json", "sources": "sources_json", "unverified_claims": "unverified_claims_json"}
_SAMPLE_JSON_FIELDS = {"evidence_docs": "evidence_docs_json", "evidence_keywords": "evidence_keywords_json", "regulation_refs": "regulation_refs_json"}
_RESULT_JSON_FIELDS = {
    "retrieved_docs": "retrieved_docs_json",
    "retrieval_metrics": "retrieval_metrics_json",
    "generation_metrics": "generation_metrics_json",
}


def init_db():
    with get_connection() as conn:
        conn.executescript(_SCHEMA_SQL)
    _migrate_db()


def _migrate_db():
    """增量迁移：添加新列（如已存在则跳过）"""
    with get_connection() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if 'faithfulness_score' not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN faithfulness_score REAL")
        if 'unverified_claims_json' not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN unverified_claims_json TEXT DEFAULT '[]'")

        trace_cols = {row[1] for row in conn.execute("PRAGMA table_info(traces)").fetchall()}
        if 'conversation_id' not in trace_cols:
            conn.execute("ALTER TABLE traces ADD COLUMN conversation_id TEXT")
        if 'name' not in trace_cols:
            conn.execute("ALTER TABLE traces ADD COLUMN name TEXT")
        for col, dtype, default in [
            ('status', 'TEXT NOT NULL DEFAULT', "'ok'"),
            ('total_duration_ms', 'REAL DEFAULT', '0'),
            ('span_count', 'INTEGER DEFAULT', '0'),
            ('llm_call_count', 'INTEGER DEFAULT', '0'),
        ]:
            if col not in trace_cols:
                conn.execute(f"ALTER TABLE traces ADD COLUMN {col} {dtype} {default}")

        # Migrate eval_configs: remove name column, make is_active global
        config_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_configs)").fetchall()}
        if 'name' in config_cols:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS eval_configs_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL DEFAULT 1,
                    description TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                INSERT INTO eval_configs_new (id, version, description, config_json, is_active, created_at)
                SELECT id, version, description, config_json,
                       CASE WHEN rowid = (SELECT rowid FROM eval_configs WHERE is_active = 1 LIMIT 1) THEN 1 ELSE 0 END,
                       created_at
                FROM eval_configs
            """)
            conn.execute("DROP TABLE eval_configs")
            conn.execute("ALTER TABLE eval_configs_new RENAME TO eval_configs")

        sample_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_samples)").fetchall()}
        if 'regulation_refs_json' not in sample_cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN regulation_refs_json TEXT NOT NULL DEFAULT '[]'")
        if 'review_status' not in sample_cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
        if 'reviewer' not in sample_cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN reviewer TEXT NOT NULL DEFAULT ''")
        if 'reviewed_at' not in sample_cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN reviewed_at TEXT NOT NULL DEFAULT ''")
        if 'review_comment' not in sample_cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN review_comment TEXT NOT NULL DEFAULT ''")
        if 'created_by' not in sample_cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN created_by TEXT NOT NULL DEFAULT 'human'")
        if 'kb_version' not in sample_cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN kb_version TEXT NOT NULL DEFAULT ''")


def create_conversation(conversation_id: str, title: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, title) VALUES (?, ?)",
            (conversation_id, title),
        )


def get_conversations() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.created_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_messages(conversation_id: str) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, citations_json, sources_json, faithfulness_score, unverified_claims_json, timestamp "
            "FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [_deserialize_json_fields(dict(r), _MSG_JSON_FIELDS) for r in rows]


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    citations: Optional[List[Dict]] = None,
    sources: Optional[List[Dict]] = None,
    faithfulness_score: Optional[float] = None,
    unverified_claims: Optional[List[str]] = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, citations_json, sources_json, faithfulness_score, unverified_claims_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(citations or [], ensure_ascii=False),
                json.dumps(sources or [], ensure_ascii=False),
                faithfulness_score,
                json.dumps(unverified_claims or [], ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def delete_conversation(conversation_id: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        msg_count = cur.rowcount
        conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        return msg_count


def search_conversations(search: str = "", page: int = 1, size: int = 20) -> tuple:
    """分页搜索对话，按标题 LIKE 匹配。

    Returns:
        (rows, total_count)，rows 中每条记录包含 id, title, created_at, message_count。
    """
    offset = (page - 1) * size
    where_clause = ""
    params: list = []
    if search:
        where_clause = "WHERE c.title LIKE ?"
        params.append(f"%{search}%")

    with get_connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM conversations c {where_clause}", params
        ).fetchone()
        total = count_row["cnt"]

        rows = conn.execute(f"""
            SELECT c.id, c.title, c.created_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            {where_clause}
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [size, offset]).fetchall()
        return [dict(r) for r in rows], total


def batch_delete_conversations(ids: list) -> int:
    """批量删除对话及其关联消息。返回实际删除的对话数。"""
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        conn.execute(
            f"DELETE FROM messages WHERE conversation_id IN ({placeholders})", ids
        )
        cur = conn.execute(
            f"DELETE FROM conversations WHERE id IN ({placeholders})", ids
        )
        return cur.rowcount


def get_eval_samples(
    question_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
    review_status: Optional[str] = None,
) -> List[Dict]:
    clauses: list[str] = []
    params: list = []
    if question_type:
        clauses.append("question_type = ?")
        params.append(question_type)
    if difficulty:
        clauses.append("difficulty = ?")
        params.append(difficulty)
    if topic:
        clauses.append("topic = ?")
        params.append(topic)
    if review_status:
        clauses.append("review_status = ?")
        params.append(review_status)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM eval_samples{where} ORDER BY id", params
        ).fetchall()
        return [_deserialize_json_fields(dict(r), _SAMPLE_JSON_FIELDS) for r in rows]


def get_eval_sample(sample_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_samples WHERE id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            return None
        return _deserialize_json_fields(dict(row), _SAMPLE_JSON_FIELDS)


def _sample_insert_values(s: Dict, use_now: bool = True) -> tuple:
    now = datetime.now(timezone.utc).isoformat()
    return (
        s["id"], s["question"], s.get("ground_truth", ""),
        json.dumps(s.get("evidence_docs", []), ensure_ascii=False),
        json.dumps(s.get("evidence_keywords", []), ensure_ascii=False),
        s.get("question_type", "factual"),
        s.get("difficulty", "medium"),
        s.get("topic", ""),
        now if use_now else s.get("created_at", now),
        now if use_now else s.get("updated_at", now),
        json.dumps(s.get("regulation_refs", []), ensure_ascii=False),
        s.get("review_status", "pending"),
        s.get("reviewer", ""),
        s.get("reviewed_at", ""),
        s.get("review_comment", ""),
        s.get("created_by", "human"),
        s.get("kb_version", ""),
    )


_SAMPLE_INSERT_SQL = (
    "INSERT OR IGNORE INTO eval_samples "
    "(id, question, ground_truth, evidence_docs_json, evidence_keywords_json, "
    "question_type, difficulty, topic, created_at, updated_at, "
    "regulation_refs_json, review_status, reviewer, reviewed_at, review_comment, "
    "created_by, kb_version) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def upsert_eval_sample(sample: Dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO eval_samples
                (id, question, ground_truth, evidence_docs_json, evidence_keywords_json,
                 question_type, difficulty, topic, created_at, updated_at,
                 regulation_refs_json, review_status, reviewer, reviewed_at, review_comment,
                 created_by, kb_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question = excluded.question,
                ground_truth = excluded.ground_truth,
                evidence_docs_json = excluded.evidence_docs_json,
                evidence_keywords_json = excluded.evidence_keywords_json,
                question_type = excluded.question_type,
                difficulty = excluded.difficulty,
                topic = excluded.topic,
                updated_at = excluded.updated_at,
                regulation_refs_json = excluded.regulation_refs_json,
                review_status = excluded.review_status,
                reviewer = excluded.reviewer,
                reviewed_at = excluded.reviewed_at,
                review_comment = excluded.review_comment,
                created_by = excluded.created_by,
                kb_version = excluded.kb_version
        """, (
            sample["id"], sample["question"], sample.get("ground_truth", ""),
            json.dumps(sample.get("evidence_docs", []), ensure_ascii=False),
            json.dumps(sample.get("evidence_keywords", []), ensure_ascii=False),
            sample.get("question_type", "factual"),
            sample.get("difficulty", "medium"),
            sample.get("topic", ""),
            now, now,
            json.dumps(sample.get("regulation_refs", []), ensure_ascii=False),
            sample.get("review_status", "pending"),
            sample.get("reviewer", ""),
            sample.get("reviewed_at", ""),
            sample.get("review_comment", ""),
            sample.get("created_by", "human"),
            sample.get("kb_version", ""),
        ))


def delete_eval_sample(sample_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM eval_samples WHERE id = ?", (sample_id,)
        )
        return cur.rowcount > 0


def eval_sample_count() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM eval_samples").fetchone()
        return row["cnt"]


def get_review_stats() -> Dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN review_status = 'approved' THEN 1 ELSE 0 END) AS approved, "
            "SUM(CASE WHEN review_status != 'approved' THEN 1 ELSE 0 END) AS pending "
            "FROM eval_samples"
        ).fetchone()
        return {"total": row["total"], "pending": row["pending"], "approved": row["approved"]}


def import_eval_samples(samples: List[Dict]) -> int:
    count = 0
    with get_connection() as conn:
        for s in samples:
            cur = conn.execute(_SAMPLE_INSERT_SQL, _sample_insert_values(s))
            if cur.rowcount > 0:
                count += 1
    return count


def create_snapshot(name: str, description: str = "") -> str:
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        samples = get_eval_samples()
        conn.execute(
            "INSERT INTO eval_snapshots (id, name, description, sample_count, samples_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, name, description, len(samples),
             json.dumps(samples, ensure_ascii=False)),
        )
    return snapshot_id


def get_snapshots() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description, sample_count, created_at "
            "FROM eval_snapshots ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def restore_snapshot(snapshot_id: str) -> int:
    with get_connection() as conn:
        conn.execute("DELETE FROM eval_samples")
        snap = conn.execute(
            "SELECT samples_json FROM eval_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if not snap or not snap["samples_json"]:
            return 0
        count = 0
        for s in json.loads(snap["samples_json"]):
            conn.execute(_SAMPLE_INSERT_SQL, _sample_insert_values(s))
            count += 1
        return count


# ── 评测配置版本管理 ──────────────────────────────────


def insert_eval_config(description: str, config: Dict) -> tuple:
    """创建评测配置新版本，自动 version+1。返回 (id, version)。"""
    with get_connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM eval_configs").fetchone()
        next_version = row[0] + 1
        conn.execute(
            "INSERT INTO eval_configs (version, description, config_json) VALUES (?, ?, ?)",
            (next_version, description, json.dumps(config, ensure_ascii=False)),
        )
        config_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return config_id, next_version


def get_eval_configs() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, version, description, is_active, created_at FROM eval_configs "
            "ORDER BY version DESC",
        ).fetchall()
        return [dict(r) for r in rows]


def get_eval_config(config_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, version, description, config_json, is_active, created_at "
            "FROM eval_configs WHERE id = ?",
            (config_id,),
        ).fetchone()
        if row is None:
            return None
        return _deserialize_json_fields(dict(row), {"config_json": "config_json"})


def get_active_config() -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, version, description, config_json, is_active, created_at "
            "FROM eval_configs WHERE is_active = 1",
        ).fetchone()
        if row is None:
            return None
        return _deserialize_json_fields(dict(row), {"config_json": "config_json"})


def remove_eval_config(config_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_active FROM eval_configs WHERE id = ?", (config_id,),
        ).fetchone()
        if row is None:
            return False
        if row["is_active"]:
            return False
        conn.execute("DELETE FROM eval_configs WHERE id = ?", (config_id,))
        return True


def activate_eval_config(config_id: int) -> bool:
    """将指定配置设为激活版本，其他版本自动停用。"""
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM eval_configs WHERE id = ?", (config_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE eval_configs SET is_active = 0 WHERE is_active = 1")
        conn.execute("UPDATE eval_configs SET is_active = 1 WHERE id = ?", (config_id,))
        return True


def _ensure_default_config():
    """启动时检查，如果 eval_configs 为空则插入默认配置。"""
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM eval_configs").fetchone()[0]
        if count > 0:
            return
    from lib.rag_engine.config import RAGConfig
    config_id, _ = insert_eval_config("默认配置", RAGConfig().to_dict())
    with get_connection() as conn:
        conn.execute("UPDATE eval_configs SET is_active = 1 WHERE id = ?", (config_id,))


def insert_evaluation(run_id: str, mode: str, config: Dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO eval_runs (id, mode, status, config_json) VALUES (?, ?, 'pending', ?)",
            (run_id, mode, json.dumps(config, ensure_ascii=False)),
        )


def update_evaluation_status(
    run_id: str, status: str, progress: int = 0, total: int = 0
) -> None:
    with get_connection() as conn:
        sets = ["status = ?"]
        params: list = [status]
        if status == "running":
            sets.append("progress = ?")
            sets.append("total = ?")
            params.extend([progress, total])
        elif status in ("completed", "failed"):
            sets.append("finished_at = datetime('now')")
            sets.append("progress = total")
        params.append(run_id)
        conn.execute(
            f"UPDATE eval_runs SET {', '.join(sets)} WHERE id = ?", params
        )


def save_evaluation_report(run_id: str, report: Dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE eval_runs SET report_json = ? WHERE id = ?",
            (json.dumps(report, ensure_ascii=False), run_id),
        )


def update_evaluation_config(run_id: str, config: Dict, total: int = 0) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE eval_runs SET config_json = ?, total = ? WHERE id = ?",
            (json.dumps(config, ensure_ascii=False), total, run_id),
        )


def save_sample_result(
    run_id: str,
    sample_id: str,
    retrieved_docs: Optional[List] = None,
    generated_answer: str = "",
    retrieval_metrics: Optional[Dict] = None,
    generation_metrics: Optional[Dict] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO eval_sample_results "
            "(run_id, sample_id, retrieved_docs_json, generated_answer, "
            "retrieval_metrics_json, generation_metrics_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id, sample_id,
                json.dumps(retrieved_docs or [], ensure_ascii=False),
                generated_answer,
                json.dumps(retrieval_metrics or {}, ensure_ascii=False),
                json.dumps(generation_metrics or {}, ensure_ascii=False),
            ),
        )


def get_evaluation(run_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        _deserialize_json_fields(d, {"config": "config_json", "report": "report_json"})
        return d


def get_evaluations() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, mode, status, progress, total, started_at, finished_at, config_json "
            "FROM eval_runs ORDER BY started_at DESC"
        ).fetchall()
        return [_deserialize_json_fields(dict(r), {"config": "config_json"}) for r in rows]


def fetch_evaluation_trends(metric: str, limit: int = 20) -> List[Dict]:
    """获取指定指标在历次已完成评测中的值。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, started_at, report_json FROM eval_runs "
            "WHERE status = 'completed' AND report_json IS NOT NULL "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    section, _, key = metric.partition(".")
    points = []
    for row in rows:
        d = _deserialize_json_fields(dict(row), {"report": "report_json"})
        report = d.get("report", {})
        section_data = report.get(section, report if not section else {})
        if not isinstance(section_data, dict):
            continue
        val = section_data.get(key) if section else report.get(metric)
        if val is None or not isinstance(val, (int, float)):
            continue
        points.append({
            "run_id": d["id"],
            "label": d["id"][:12],
            "value": val,
            "timestamp": d.get("started_at", ""),
        })
    return points


def get_sample_results(run_id: str) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_sample_results WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [_deserialize_json_fields(dict(r), _RESULT_JSON_FIELDS) for r in rows]


def batch_delete_evaluations(evaluation_ids: List[str]) -> int:
    """删除评测运行及其关联的样本结果。"""
    if not evaluation_ids:
        return 0
    placeholders = ",".join("?" * len(evaluation_ids))
    with get_connection() as conn:
        conn.execute(f"DELETE FROM eval_sample_results WHERE run_id IN ({placeholders})", evaluation_ids)
        cursor = conn.execute(f"DELETE FROM eval_runs WHERE id IN ({placeholders})", evaluation_ids)
        return cursor.rowcount


def save_compliance_report(
    report_id: str,
    product_name: str,
    category: str,
    mode: str,
    result: Dict,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO compliance_reports (id, product_name, category, mode, result_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (report_id, product_name, category, mode,
             json.dumps(result, ensure_ascii=False)),
        )


def get_compliance_reports() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM compliance_reports ORDER BY created_at DESC"
        ).fetchall()
        return [_deserialize_json_fields(dict(r), {"result": "result_json"}) for r in rows]


def get_compliance_report(report_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM compliance_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return None
        return _deserialize_json_fields(dict(row), {"result": "result_json"})


_FEEDBACK_JSON_FIELDS = {
    "auto_quality_details": "auto_quality_details_json",
}


def create_feedback(
    message_id: int,
    conversation_id: str,
    rating: str,
    reason: str = "",
    correction: str = "",
    source_channel: str = "user_button",
) -> str:
    feedback_id = f"fb_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO feedback (id, message_id, conversation_id, rating, reason, correction, source_channel) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (feedback_id, message_id, conversation_id, rating, reason, correction, source_channel),
        )
    return feedback_id


def _enrich_feedback(row: Dict) -> Dict:
    """为反馈记录补充用户问题和助手回答"""
    row = _deserialize_json_fields(row, _FEEDBACK_JSON_FIELDS)
    mid = row.get("message_id")
    cid = row.get("conversation_id")
    if not mid or not cid:
        return row
    with get_connection() as conn:
        assistant = conn.execute(
            "SELECT content FROM messages WHERE id = ?", (mid,)
        ).fetchone()
        user_msg = conn.execute(
            "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
            (cid, mid),
        ).fetchone()
    row["assistant_answer"] = assistant[0] if assistant else ""
    row["user_question"] = user_msg[0] if user_msg else ""
    return row


def get_feedback(feedback_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        if row is None:
            return None
        return _enrich_feedback(dict(row))


def list_feedbacks(
    status: Optional[str] = None,
    classified_type: Optional[str] = None,
    compliance_risk: Optional[int] = None,
) -> List[Dict]:
    clauses: list[str] = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if classified_type:
        clauses.append("classified_type = ?")
        params.append(classified_type)
    if compliance_risk is not None:
        clauses.append("compliance_risk >= ?")
        params.append(compliance_risk)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM feedback{where} ORDER BY created_at DESC", params
        ).fetchall()
        return [_enrich_feedback(dict(r)) for r in rows]


def update_feedback(feedback_id: str, updates: Dict) -> bool:
    if not updates:
        return False
    sets = []
    params = []
    for key, value in updates.items():
        sets.append(f"{key} = ?")
        params.append(value)
    sets.append("updated_at = datetime('now')")
    params.append(feedback_id)
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE feedback SET {', '.join(sets)} WHERE id = ?", params
        )
        return cur.rowcount > 0


def get_feedback_stats() -> Dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        up_count = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 'up'").fetchone()[0]
        down_count = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 'down'").fetchone()[0]
        by_type = {}
        for row in conn.execute(
            "SELECT classified_type, COUNT(*) as cnt FROM feedback "
            "WHERE classified_type IS NOT NULL GROUP BY classified_type"
        ).fetchall():
            by_type[row[0] or "unclear"] = row[1]
        by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM feedback GROUP BY status"
        ).fetchall():
            by_status[row[0]] = row[1]
        by_risk = {}
        for row in conn.execute(
            "SELECT compliance_risk, COUNT(*) as cnt FROM feedback GROUP BY compliance_risk"
        ).fetchall():
            by_risk[str(row[0])] = row[1]
    return {
        "total": total,
        "up_count": up_count,
        "down_count": down_count,
        "satisfaction_rate": round(up_count / total, 4) if total > 0 else 0.0,
        "by_type": by_type,
        "by_status": by_status,
        "by_risk": by_risk,
    }


def save_trace(
    trace_id: str,
    message_id: int,
    conversation_id: str = "",
    name: str = "",
    status: str = "ok",
    total_duration_ms: float = 0,
    span_count: int = 0,
    llm_call_count: int = 0,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO traces "
            "(trace_id, message_id, conversation_id, name, status, total_duration_ms, span_count, llm_call_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (trace_id, message_id, conversation_id, name, status, total_duration_ms, span_count, llm_call_count),
        )


_SPAN_JSON_FIELDS = {"input": "input_json", "output": "output_json", "metadata": "metadata_json"}


def save_spans(spans_data: List[Dict]) -> None:
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO spans "
            "(trace_id, span_id, parent_span_id, name, category, "
            "input_json, output_json, metadata_json, start_time, end_time, duration_ms, status, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s["trace_id"], s["span_id"], s["parent_span_id"], s["name"], s["category"],
                    json.dumps(s["input"], ensure_ascii=False) if s.get("input") is not None else None,
                    json.dumps(s["output"], ensure_ascii=False) if s.get("output") is not None else None,
                    json.dumps(s.get("metadata") or {}, ensure_ascii=False),
                    s["start_time"], s["end_time"], s["duration_ms"], s["status"], s.get("error"),
                )
                for s in spans_data
            ],
        )


def _build_trace_detail(trace_row) -> Optional[Dict]:
    """从 traces 行构建完整 trace 数据（含 span 树和 summary）。"""
    if trace_row is None:
        return None
    tid = trace_row["trace_id"]

    with get_connection() as conn:
        span_rows = conn.execute(
            "SELECT span_id, parent_span_id, name, category, input_json, output_json, "
            "metadata_json, start_time, end_time, duration_ms, status, error "
            "FROM spans WHERE trace_id = ? ORDER BY start_time",
            (tid,),
        ).fetchall()

        span_dicts = [_deserialize_json_fields(dict(r), _SPAN_JSON_FIELDS) for r in span_rows]

    span_map: Dict[str, Dict] = {s["span_id"]: {**s, "children": []} for s in span_dicts}
    roots: List[Dict] = []
    for s in span_dicts:
        parent_id = s.get("parent_span_id")
        if parent_id and parent_id in span_map:
            span_map[parent_id]["children"].append(span_map[s["span_id"]])
        else:
            roots.append(span_map[s["span_id"]])

    root = roots[0] if roots else None
    if root is None:
        return None

    return {
        "trace_id": tid,
        "root": root,
        "spans": span_dicts,
        "summary": {
            "total_duration_ms": root.get("duration_ms") or 0,
            "span_count": len(span_dicts),
            "llm_call_count": trace_row["llm_call_count"] if trace_row else 0,
            "error_count": sum(1 for s in span_dicts if s["status"] == "error"),
        },
    }


def get_trace_by_message_id(message_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        trace_row = conn.execute(
            "SELECT trace_id, llm_call_count FROM traces WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (message_id,),
        ).fetchone()
    return _build_trace_detail(trace_row)


def get_trace_by_id(trace_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        trace_row = conn.execute(
            "SELECT trace_id, llm_call_count FROM traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    return _build_trace_detail(trace_row)


def search_traces(
    trace_id: str = "",
    conversation_id: str = "",
    message_id: int = 0,
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    page: int = 1,
    size: int = 20,
) -> tuple:
    """分页搜索 trace，支持按 trace_id / conversation_id / message_id / status / 日期范围过滤。

    Returns:
        (rows, total_count)，rows 中每条记录包含 trace_id, message_id,
        conversation_id, created_at, status, total_duration_ms, span_count。
    """
    clauses: list[str] = []
    params: list = []

    if trace_id:
        clauses.append("trace_id = ?")
        params.append(trace_id)
    if conversation_id:
        clauses.append("conversation_id = ?")
        params.append(conversation_id)
    if message_id:
        clauses.append("message_id = ?")
        params.append(message_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if start_date:
        clauses.append("created_at >= ?")
        params.append(start_date)
    if end_date:
        end_val = end_date
        if len(end_date) == 10:
            end_val = f"{end_date} 23:59:59"
        clauses.append("created_at <= ?")
        params.append(end_val)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    offset = (page - 1) * size

    with get_connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM traces {where}",
            params,
        ).fetchone()
        total = count_row["cnt"]

        rows = conn.execute(
            f"SELECT trace_id, message_id, conversation_id, created_at, "
            f"status, total_duration_ms, span_count, llm_call_count, "
            f"name AS trace_name "
            f"FROM traces {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total


def batch_delete_traces(trace_ids: list) -> int:
    """批量删除 trace 及其关联 spans。返回实际删除的 trace 数。"""
    if not trace_ids:
        return 0
    placeholders = ",".join("?" for _ in trace_ids)
    with get_connection() as conn:
        conn.execute(
            f"DELETE FROM spans WHERE trace_id IN ({placeholders})", trace_ids
        )
        cur = conn.execute(
            f"DELETE FROM traces WHERE trace_id IN ({placeholders})", trace_ids
        )
        return cur.rowcount


def _build_cleanup_filter(start_date: str, end_date: str, status: str = "") -> tuple:
    """构建清理/统计查询的 WHERE 子句，使用 traces 表的反规范化 status 列。"""
    clauses: list[str] = []
    params: list = []

    if start_date:
        clauses.append("created_at >= ?")
        params.append(start_date)
    if end_date:
        end_val = end_date
        if len(end_date) == 10:
            end_val = f"{end_date} 23:59:59"
        clauses.append("created_at <= ?")
        params.append(end_val)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def count_traces_for_cleanup(
    start_date: str, end_date: str, status: str = ""
) -> int:
    """统计满足条件的 trace 数量（用于清理预览）。"""
    where, params = _build_cleanup_filter(start_date, end_date, status)
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM traces {where}",
            params,
        ).fetchone()
        return row["cnt"]


def cleanup_traces(
    start_date: str, end_date: str, status: str = ""
) -> int:
    """按条件删除 trace 及其 spans。先查找匹配的 trace_id，再调用 batch_delete_traces。"""
    where, params = _build_cleanup_filter(start_date, end_date, status)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT trace_id FROM traces {where}",
            params,
        ).fetchall()
    trace_ids = [r["trace_id"] for r in rows]
    return batch_delete_traces(trace_ids)


def insert_human_review(
    evaluation_id: str,
    sample_id: str,
    reviewer: str = "",
    faithfulness_score: Optional[float] = None,
    correctness_score: Optional[float] = None,
    relevancy_score: Optional[float] = None,
    comment: str = "",
) -> str:
    review_id = f"hr_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO human_reviews "
            "(id, evaluation_id, sample_id, reviewer, faithfulness_score, "
            "correctness_score, relevancy_score, comment) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (review_id, evaluation_id, sample_id, reviewer,
             faithfulness_score, correctness_score, relevancy_score, comment),
        )
    return review_id


def get_human_reviews(evaluation_id: str) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM human_reviews WHERE evaluation_id = ? ORDER BY created_at DESC",
            (evaluation_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_human_review_stats(evaluation_id: str) -> Dict:
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE evaluation_id = ?",
            (evaluation_id,),
        ).fetchone()[0]
        if total == 0:
            return {'total': 0, 'faithfulness': None, 'correctness': None, 'relevancy': None}
        row = conn.execute(
            "SELECT AVG(faithfulness_score), AVG(correctness_score), AVG(relevancy_score) "
            "FROM human_reviews WHERE evaluation_id = ?",
            (evaluation_id,),
        ).fetchone()
        return {
            'total': total,
            'faithfulness': round(row[0], 4) if row[0] is not None else None,
            'correctness': round(row[1], 4) if row[1] is not None else None,
            'relevancy': round(row[2], 4) if row[2] is not None else None,
        }
