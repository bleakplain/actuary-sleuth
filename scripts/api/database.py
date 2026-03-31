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
"""


def init_db():
    """执行建表 DDL。应用启动时调用一次。"""
    with get_connection() as conn:
        conn.executescript(_SCHEMA_SQL)


# ── 对话 (conversations / messages) ──────────────────


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
            "SELECT id, conversation_id, role, content, citations_json, sources_json, timestamp "
            "FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["citations"] = json.loads(d.pop("citations_json"))
            d["sources"] = json.loads(d.pop("sources_json"))
            results.append(d)
        return results


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    citations: Optional[List[Dict]] = None,
    sources: Optional[List[Dict]] = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, citations_json, sources_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(citations or [], ensure_ascii=False),
                json.dumps(sources or [], ensure_ascii=False),
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


# ── 评估数据集 (eval_samples / eval_snapshots) ──────


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
        results = []
        for r in rows:
            d = dict(r)
            d["evidence_docs"] = json.loads(d.pop("evidence_docs_json"))
            d["evidence_keywords"] = json.loads(d.pop("evidence_keywords_json"))
            results.append(d)
        return results


def get_eval_sample(sample_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_samples WHERE id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["evidence_docs"] = json.loads(d.pop("evidence_docs_json"))
        d["evidence_keywords"] = json.loads(d.pop("evidence_keywords_json"))
        return d


def upsert_eval_sample(sample: Dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO eval_samples
                (id, question, ground_truth, evidence_docs_json, evidence_keywords_json,
                 question_type, difficulty, topic, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question = excluded.question,
                ground_truth = excluded.ground_truth,
                evidence_docs_json = excluded.evidence_docs_json,
                evidence_keywords_json = excluded.evidence_keywords_json,
                question_type = excluded.question_type,
                difficulty = excluded.difficulty,
                topic = excluded.topic,
                updated_at = excluded.updated_at
        """, (
            sample["id"], sample["question"], sample.get("ground_truth", ""),
            json.dumps(sample.get("evidence_docs", []), ensure_ascii=False),
            json.dumps(sample.get("evidence_keywords", []), ensure_ascii=False),
            sample.get("question_type", "factual"),
            sample.get("difficulty", "medium"),
            sample.get("topic", ""),
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
    for s in samples:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO eval_samples "
                "(id, question, ground_truth, evidence_docs_json, evidence_keywords_json, "
                "question_type, difficulty, topic, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (
                    s["id"], s["question"], s.get("ground_truth", ""),
                    json.dumps(s.get("evidence_docs", []), ensure_ascii=False),
                    json.dumps(s.get("evidence_keywords", []), ensure_ascii=False),
                    s.get("question_type", "factual"),
                    s.get("difficulty", "medium"),
                    s.get("topic", ""),
                ),
            )
            if cur.rowcount > 0:
                count += 1
    return count


# ── 快照 ─────────────────────────────────────────────


def create_snapshot(name: str, description: str = "") -> str:
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        samples = get_eval_samples()
        samples_json = json.dumps(samples, ensure_ascii=False)
        cnt = len(samples)
        conn.execute(
            "INSERT INTO eval_snapshots (id, name, description, sample_count, samples_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, name, description, cnt, samples_json),
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
            conn.execute(
                "INSERT OR IGNORE INTO eval_samples "
                "(id, question, ground_truth, evidence_docs_json, evidence_keywords_json, "
                "question_type, difficulty, topic, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (
                    s["id"], s["question"], s.get("ground_truth", ""),
                    json.dumps(s.get("evidence_docs", []), ensure_ascii=False),
                    json.dumps(s.get("evidence_keywords", []), ensure_ascii=False),
                    s.get("question_type", "factual"),
                    s.get("difficulty", "medium"),
                    s.get("topic", ""),
                ),
            )
            count += 1
        return count


# ── 评估运行 (eval_runs / eval_sample_results) ──────


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
        if d.get("config_json"):
            d["config"] = json.loads(d.pop("config_json"))
        if d.get("report_json"):
            d["report"] = json.loads(d.pop("report_json"))
        return d


def get_eval_runs() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, mode, status, progress, total, started_at, finished_at, config_json "
            "FROM eval_runs ORDER BY started_at DESC"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("config_json"):
                d["config"] = json.loads(d.pop("config_json"))
            results.append(d)
        return results


def get_sample_results(run_id: str) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_sample_results WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["retrieved_docs"] = json.loads(d.pop("retrieved_docs_json"))
            d["retrieval_metrics"] = json.loads(d.pop("retrieval_metrics_json"))
            d["generation_metrics"] = json.loads(d.pop("generation_metrics_json"))
            results.append(d)
        return results


# ── 合规报告 ─────────────────────────────────────────


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
        results = []
        for r in rows:
            d = dict(r)
            d["result"] = json.loads(d.pop("result_json"))
            results.append(d)
        return results


def get_compliance_report(report_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM compliance_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json"))
        return d
