"""API 数据库层 — 建表 DDL 和数据访问函数。

复用 lib.common.database.get_connection() 连接池，
不创建独立连接。
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict

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
    mode TEXT NOT NULL CHECK(mode IN ('retrieval', 'generation', 'full')),
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

CREATE TABLE IF NOT EXISTS feedback_action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id TEXT NOT NULL REFERENCES feedback(id),
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_action_log_feedback ON feedback_action_log(feedback_id);
"""


def _deserialize_json_fields(row: dict, mappings: Dict[str, str]) -> dict:
    for python_name, db_column in mappings.items():
        val = row.pop(db_column, None)
        if val is not None:
            row[python_name] = json.loads(val)
    return row


_MSG_JSON_FIELDS = {"citations": "citations_json", "sources": "sources_json", "unverified_claims": "unverified_claims_json"}
_SAMPLE_JSON_FIELDS = {"evidence_docs": "evidence_docs_json", "evidence_keywords": "evidence_keywords_json"}
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

        # eval_samples: add is_regression
        cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_samples)").fetchall()}
        if 'is_regression' not in cols:
            conn.execute("ALTER TABLE eval_samples ADD COLUMN is_regression INTEGER DEFAULT 0")

        # feedback: add fix_action and resolved_at
        cols = {row[1] for row in conn.execute("PRAGMA table_info(feedback)").fetchall()}
        if 'fix_action' not in cols:
            conn.execute("ALTER TABLE feedback ADD COLUMN fix_action TEXT DEFAULT ''")
        if 'resolved_at' not in cols:
            conn.execute("ALTER TABLE feedback ADD COLUMN resolved_at TEXT")

        # feedback_action_log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback_action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT NOT NULL REFERENCES feedback(id),
                action TEXT NOT NULL,
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_action_log_feedback ON feedback_action_log(feedback_id)")


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


def get_eval_samples(
    question_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
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
    ts = "datetime('now')" if use_now else "?"
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
    )


_SAMPLE_INSERT_SQL = (
    "INSERT OR IGNORE INTO eval_samples "
    "(id, question, ground_truth, evidence_docs_json, evidence_keywords_json, "
    "question_type, difficulty, topic, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def upsert_eval_sample(sample: Dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO eval_samples
                (id, question, ground_truth, evidence_docs_json, evidence_keywords_json,
                 question_type, difficulty, topic, is_regression, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question = excluded.question,
                ground_truth = excluded.ground_truth,
                evidence_docs_json = excluded.evidence_docs_json,
                evidence_keywords_json = excluded.evidence_keywords_json,
                question_type = excluded.question_type,
                difficulty = excluded.difficulty,
                topic = excluded.topic,
                is_regression = excluded.is_regression,
                updated_at = excluded.updated_at
        """, (
            sample["id"], sample["question"], sample.get("ground_truth", ""),
            json.dumps(sample.get("evidence_docs", []), ensure_ascii=False),
            json.dumps(sample.get("evidence_keywords", []), ensure_ascii=False),
            sample.get("question_type", "factual"),
            sample.get("difficulty", "medium"),
            sample.get("topic", ""),
            1 if sample.get("is_regression") else 0,
            now, now,
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


def create_eval_run(run_id: str, mode: str, config: Dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO eval_runs (id, mode, status, config_json) VALUES (?, ?, 'pending', ?)",
            (run_id, mode, json.dumps(config, ensure_ascii=False)),
        )


def update_eval_run_status(
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


def save_eval_report(run_id: str, report: Dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE eval_runs SET report_json = ? WHERE id = ?",
            (json.dumps(report, ensure_ascii=False), run_id),
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


def get_eval_run(run_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        _deserialize_json_fields(d, {"config": "config_json", "report": "report_json"})
        return d


def get_eval_runs() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, mode, status, progress, total, started_at, finished_at, config_json "
            "FROM eval_runs ORDER BY started_at DESC"
        ).fetchall()
        return [_deserialize_json_fields(dict(r), {"config": "config_json"}) for r in rows]


def get_sample_results(run_id: str) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_sample_results WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [_deserialize_json_fields(dict(r), _RESULT_JSON_FIELDS) for r in rows]


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

    # Auto-set resolved_at when status changes to 'fixed'
    if updates.get("status") == "fixed":
        sets.append("resolved_at = datetime('now')")

    sets.append("updated_at = datetime('now')")
    params.append(feedback_id)
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE feedback SET {', '.join(sets)} WHERE id = ?", params
        )
        if cur.rowcount > 0:
            if "status" in updates:
                log_feedback_action(feedback_id, "status_change", f"状态变更为: {updates['status']}")
            if updates.get("fix_action"):
                log_feedback_action(feedback_id, "fix_applied", updates["fix_action"])
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


def get_regression_samples() -> List[Dict]:
    """获取所有标记为回归测试的评估样本"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_samples WHERE is_regression = 1 ORDER BY id"
        ).fetchall()
        return [_deserialize_json_fields(dict(r), _SAMPLE_JSON_FIELDS) for r in rows]


def log_feedback_action(feedback_id: str, action: str, detail: str = "") -> None:
    """记录反馈状态变更日志"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO feedback_action_log (feedback_id, action, detail) VALUES (?, ?, ?)",
            (feedback_id, action, detail),
        )


def get_feedback_history(feedback_id: str) -> List[Dict]:
    """获取反馈的状态变更历史"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback_action_log WHERE feedback_id = ? ORDER BY created_at ASC",
            (feedback_id,),
        ).fetchall()
        return [dict(r) for r in rows]
