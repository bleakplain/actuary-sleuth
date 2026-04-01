# Feedback Mechanism P0+P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the RAG badcase feedback mechanism from rule-based classification to LLM-driven structured classification, upgrade quality detection to LLM-based evaluation, add manual regression testing, and implement fix action tracking.

**Architecture:** Four independent modules, each modifying existing files. All LLM calls go through `rag_engine.llm_provider()`. No new external dependencies. Database migrations are additive (ALTER TABLE ADD COLUMN, CREATE TABLE IF NOT EXISTS).

**Tech Stack:** Python/FastAPI, React/TypeScript/Ant Design, SQLite, existing LLM provider (zhipu/ollama)

---

## Task 1: LLM Badcase Classifier

**Files:**
- Modify: `scripts/lib/rag_engine/badcase_classifier.py`
- Modify: `scripts/tests/lib/rag_engine/test_badcase_classifier.py`

- [ ] **Step 1: Write the failing test**

The new classifier requires an LLM provider, so we test with a mock. Replace the entire test file:

```python
# scripts/tests/lib/rag_engine/test_badcase_classifier.py
import json
import pytest
from unittest.mock import MagicMock, patch

from lib.rag_engine.badcase_classifier import classify_badcase, assess_compliance_risk


def _mock_llm_return(cls_type: str, reason: str, fix_dir: str) -> str:
    return json.dumps({"type": cls_type, "reason": reason, "fix_direction": fix_dir}, ensure_ascii=False)


class TestClassifyBadcase:
    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_retrieval_failure(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_return(
            "retrieval_failure",
            "相关文档未被检索到",
            "优化检索策略",
        )
        mock_get_llm.return_value = mock_llm

        result = classify_badcase(
            query="意外险的免赔额是多少",
            retrieved_docs=[{"content": "健康保险的免赔规定"}],
            answer="未找到相关信息",
            unverified_claims=[],
        )
        assert result["type"] == "retrieval_failure"
        assert "fix_direction" in result

    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_hallucination(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_return(
            "hallucination",
            "回答包含来源不支持的内容",
            "加强 Prompt 忠实度约束",
        )
        mock_get_llm.return_value = mock_llm

        result = classify_badcase(
            query="健康保险等待期最长多少天",
            retrieved_docs=[{"content": "健康保险等待期不得超过90天"}],
            answer="等待期最长为30天",
            unverified_claims=["等待期最长为30天"],
        )
        assert result["type"] == "hallucination"

    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_knowledge_gap(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_return(
            "knowledge_gap",
            "知识库中不存在相关信息",
            "补充相关法规文档",
        )
        mock_get_llm.return_value = mock_llm

        result = classify_badcase(
            query="线上理赔怎么操作",
            retrieved_docs=[],
            answer="未找到相关信息",
            unverified_claims=[],
        )
        assert result["type"] == "knowledge_gap"

    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_llm_failure_raises(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        mock_get_llm.return_value = mock_llm

        with pytest.raises(RuntimeError):
            classify_badcase(
                query="test",
                retrieved_docs=[],
                answer="test",
                unverified_claims=[],
            )

    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_llm_returns_invalid_json(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "not json at all"
        mock_get_llm.return_value = mock_llm

        with pytest.raises(ValueError):
            classify_badcase(
                query="test",
                retrieved_docs=[{"content": "test"}],
                answer="test",
                unverified_claims=[],
            )


class TestAssessComplianceRisk:
    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_high_risk(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"risk_level": 2, "reason": "包含错误金额信息"}'
        mock_get_llm.return_value = mock_llm

        risk = assess_compliance_risk("答案错误", "身故保险金为基本保额的150%")
        assert risk == 2

    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_low_risk(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"risk_level": 0, "reason": "一般性回答问题"}'
        mock_get_llm.return_value = mock_llm

        risk = assess_compliance_risk("回答不完整", "相关规定请查阅条款")
        assert risk == 0

    @patch("lib.rag_engine.badcase_classifier._get_llm")
    def test_llm_failure_returns_zero(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        mock_get_llm.return_value = mock_llm

        risk = assess_compliance_risk("test", "test")
        assert risk == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism && python -m pytest scripts/tests/lib/rag_engine/test_badcase_classifier.py -v`
Expected: FAIL — `_get_llm` does not exist, `classify_badcase` still uses rules

- [ ] **Step 3: Write the LLM classifier implementation**

Replace the entire `scripts/lib/rag_engine/badcase_classifier.py`:

```python
"""Badcase 三分类 LLM 结构化分类 + 合规风险评估。

分类类型（适配本系统无路由错误的场景）：
- retrieval_failure: 检索失败 — 知识库有答案但没检索到
- hallucination: 幻觉生成 — 检索正确但 LLM 答案错误
- knowledge_gap: 知识缺失 — 知识库里确实没有
"""
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """你是一个 RAG 系统的质量分析专家。请分析以下 badcase 并分类。

用户问题：{query}

检索到的来源：
{sources}

助手回答：
{answer}

未验证声明：{unverified_claims}

用户反馈原因：{reason}

请将此 badcase 分类为以下类别之一：
- retrieval_failure: 检索失败 — 知识库中有相关信息但未被检索到
- hallucination: 幻觉生成 — 检索到了相关文档但回答包含来源不支持的内容
- knowledge_gap: 知识缺失 — 知识库中确实不存在相关信息

返回 JSON（不要包含其他内容）：
{{"type": "<分类类型>", "reason": "<分类理由>", "fix_direction": "<修复建议方向>"}}"""

_COMPLIANCE_PROMPT = """评估以下 badcase 的合规风险等级。

用户反馈原因：{reason}
助手回答：{answer}

风险等级定义：
- 0（低）：一般性回答问题，不涉及合规敏感内容
- 1（中）：涉及保险条款解读，但无明显错误
- 2（高）：包含错误的金额、比例、法律条款引用，可能误导用户

返回 JSON（不要包含其他内容）：
{{"risk_level": 0, "reason": "<评估理由>"}}"""


def _get_llm():
    """获取 LLM 客户端，延迟导入避免循环依赖。"""
    from api.app import rag_engine
    if rag_engine is None:
        raise RuntimeError("RAG 引擎未就绪")
    return rag_engine.llm_provider()


def _parse_json_response(text: str) -> Dict:
    """从 LLM 响应中提取 JSON，处理 markdown 代码块包裹。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove ```json or ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def classify_badcase(
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    answer: str,
    unverified_claims: List[str],
) -> Dict[str, str]:
    """LLM 驱动的三分类自动分类。"""
    llm = _get_llm()

    sources_text = "\n".join(
        f"- [{d.get('source_file', '未知')}] {d.get('content', '')[:200]}"
        for d in retrieved_docs
    ) if retrieved_docs else "（无检索结果）"

    claims_text = "；".join(unverified_claims[:5]) if unverified_claims else "（无）"

    prompt = _CLASSIFY_PROMPT.format(
        query=query,
        sources=sources_text,
        answer=answer[:500],
        unverified_claims=claims_text,
        reason="",
    )

    response = llm.generate(prompt)
    result = _parse_json_response(response)

    valid_types = {"retrieval_failure", "hallucination", "knowledge_gap"}
    if result.get("type") not in valid_types:
        raise ValueError(f"Invalid classification type: {result.get('type')}")

    return {
        "type": result["type"],
        "reason": result.get("reason", ""),
        "fix_direction": result.get("fix_direction", ""),
    }


def assess_compliance_risk(reason: str, answer: str) -> int:
    """LLM 驱动的合规风险评估。失败时返回 0（安全默认值）。"""
    if not answer and not reason:
        return 0

    try:
        llm = _get_llm()
        prompt = _COMPLIANCE_PROMPT.format(reason=reason, answer=answer[:500])
        response = llm.generate(prompt)
        result = _parse_json_response(response)
        risk = int(result.get("risk_level", 0))
        return max(0, min(2, risk))
    except Exception as e:
        logger.warning(f"Compliance risk assessment failed, defaulting to 0: {e}")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism && python -m pytest scripts/tests/lib/rag_engine/test_badcase_classifier.py -v`
Expected: PASS — all 8 tests pass

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/rag_engine/badcase_classifier.py scripts/tests/lib/rag_engine/test_badcase_classifier.py
git commit -m "refactor: replace rule-based badcase classifier with LLM structured classification"
```

---

## Task 2: LLM Quality Detection

**Files:**
- Modify: `scripts/lib/rag_engine/quality_detector.py`
- Modify: `scripts/tests/lib/rag_engine/test_quality_detector.py`

- [ ] **Step 1: Write the failing test**

Replace the entire test file:

```python
# scripts/tests/lib/rag_engine/test_quality_detector.py
import json
import pytest
from unittest.mock import MagicMock, patch

from lib.rag_engine.quality_detector import detect_quality


def _mock_quality_response(faithfulness: float, relevance: float, completeness: float) -> str:
    return json.dumps({
        "faithfulness": {"score": faithfulness, "issues": ""},
        "relevance": {"score": relevance, "issues": ""},
        "completeness": {"score": completeness, "issues": ""},
    }, ensure_ascii=False)


class TestDetectQuality:
    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_high_quality(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_quality_response(0.9, 0.85, 0.9)
        mock_get_llm.return_value = mock_llm

        scores = detect_quality(
            query="健康保险等待期规定",
            answer="健康保险等待期不得超过90天。",
            sources=[{"content": "健康保险等待期不得超过90天"}],
        )
        assert scores["faithfulness"] == 0.9
        assert scores["relevance"] == 0.85
        assert scores["completeness"] == 0.9
        assert scores["overall"] > 0.85

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_low_quality(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_quality_response(0.2, 0.3, 0.1)
        mock_get_llm.return_value = mock_llm

        scores = detect_quality(
            query="健康保险等待期规定",
            answer="等待期最长为30天",
            sources=[{"content": "财产保险的理赔流程"}],
        )
        assert scores["overall"] < 0.3

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_llm_failure_raises(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        mock_get_llm.return_value = mock_llm

        with pytest.raises(RuntimeError):
            detect_quality(
                query="test",
                answer="test",
                sources=[],
            )

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_empty_inputs(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_quality_response(0.0, 0.0, 0.0)
        mock_get_llm.return_value = mock_llm

        scores = detect_quality(query="", answer="", sources=[])
        assert scores["overall"] == 0.0

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_llm_returns_invalid_json(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "not json"
        mock_get_llm.return_value = mock_llm

        with pytest.raises(ValueError):
            detect_quality(
                query="test",
                answer="test",
                sources=[{"content": "test"}],
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism && python -m pytest scripts/tests/lib/rag_engine/test_quality_detector.py -v`
Expected: FAIL — `_get_llm` does not exist, old bigram functions no longer imported

- [ ] **Step 3: Write the LLM quality detector implementation**

Replace the entire `scripts/lib/rag_engine/quality_detector.py`:

```python
"""自动质量检测 — LLM 驱动的三维度评分（忠实度 + 相关性 + 完整性）。"""
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

_QUALITY_PROMPT = """评估以下回答的质量，从三个维度打分。

用户问题：{query}

来源内容：
{sources}

回答内容：
{answer}

维度定义：
1. faithfulness（忠实度）: 回答是否严格基于来源内容，无无依据内容
   - 1.0: 完全基于来源
   - 0.7: 基本基于来源，有少量合理推断
   - 0.4: 部分基于来源，存在一些无依据内容
   - 0.0: 主要基于来源之外的信息

2. relevance（相关性）: 回答是否切题回答了用户问题
   - 1.0: 完全切题
   - 0.7: 基本切题但有偏差
   - 0.4: 部分相关
   - 0.0: 完全不相关

3. completeness（完整性）: 回答是否充分覆盖了问题涉及的方面
   - 1.0: 充分覆盖
   - 0.7: 基本覆盖，有少量遗漏
   - 0.4: 部分覆盖
   - 0.0: 未覆盖问题核心

每个维度 0.0-1.0 评分。如果有问题请填写 issues 字段。

返回 JSON（不要包含其他内容）：
{{"faithfulness": {{"score": 0.0, "issues": ""}}, "relevance": {{"score": 0.0, "issues": ""}}, "completeness": {{"score": 0.0, "issues": ""}}}}"""


def _get_llm():
    """获取 LLM 客户端，延迟导入避免循环依赖。"""
    from api.app import rag_engine
    if rag_engine is None:
        raise RuntimeError("RAG 引擎未就绪")
    return rag_engine.llm_provider()


def _parse_json_response(text: str) -> Dict:
    """从 LLM 响应中提取 JSON，处理 markdown 代码块包裹。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def detect_quality(
    query: str,
    answer: str,
    sources: List[Dict[str, Any]],
    faithfulness_score: float = None,
) -> Dict[str, float]:
    """LLM 驱动的三维度质量评分。

    Args:
        query: 用户问题
        answer: 助手回答
        sources: 检索到的来源列表
        faithfulness_score: 已弃用，保留参数兼容性但不再使用

    Returns:
        包含 faithfulness, relevance, completeness, overall 四个 0-1 分数的字典
    """
    if not query or not answer:
        return {"faithfulness": 0.0, "relevance": 0.0, "completeness": 0.0, "overall": 0.0}

    llm = _get_llm()

    sources_text = "\n".join(
        f"- {s.get('content', '')[:300]}"
        for s in sources
    ) if sources else "（无来源）"

    prompt = _QUALITY_PROMPT.format(
        query=query,
        sources=sources_text,
        answer=answer[:500],
    )

    response = llm.generate(prompt)
    result = _parse_json_response(response)

    faithfulness = float(result.get("faithfulness", {}).get("score", 0.0))
    relevance = float(result.get("relevance", {}).get("score", 0.0))
    completeness = float(result.get("completeness", {}).get("score", 0.0))

    # Clamp to [0, 1]
    faithfulness = max(0.0, min(1.0, faithfulness))
    relevance = max(0.0, min(1.0, relevance))
    completeness = max(0.0, min(1.0, completeness))

    overall = 0.4 * faithfulness + 0.3 * relevance + 0.3 * completeness

    return {
        "faithfulness": round(faithfulness, 4),
        "relevance": round(relevance, 4),
        "completeness": round(completeness, 4),
        "overall": round(overall, 4),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism && python -m pytest scripts/tests/lib/rag_engine/test_quality_detector.py -v`
Expected: PASS — all 5 tests pass

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/rag_engine/quality_detector.py scripts/tests/lib/rag_engine/test_quality_detector.py
git commit -m "refactor: replace bigram quality detection with LLM-based three-dimension evaluation"
```

---

## Task 3: Database Schema for Regression Testing + Fix Action Tracking

**Files:**
- Modify: `scripts/api/database.py`

- [ ] **Step 1: Add database migration and new functions**

In `scripts/api/database.py`, make these changes:

1. In `_SCHEMA_SQL`, add the `feedback_action_log` table DDL after the feedback table:

```python
CREATE TABLE IF NOT EXISTS feedback_action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id TEXT NOT NULL REFERENCES feedback(id),
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_action_log_feedback ON feedback_action_log(feedback_id);
```

2. In `_migrate_db()`, add migrations for:
   - `eval_samples.is_regression` column
   - `feedback.fix_action` column
   - `feedback.resolved_at` column
   - `eval_runs.mode` CHECK constraint update (SQLite doesn't support ALTER CONSTRAINT, so we recreate the table if needed)

Add this code at the end of `_migrate_db()`:

```python
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
```

3. Add new functions after `get_feedback_stats()`:

```python
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
```

4. Update `upsert_eval_sample()` to handle `is_regression` field. Add to the INSERT and ON CONFLICT sections:

In the VALUES clause, add `is_regression` parameter:
- After `topic` in the INSERT column list, add `is_regression`
- After `s.get("topic", "")` in the VALUES, add `1 if s.get("is_regression") else 0`
- In ON CONFLICT DO UPDATE SET, add `is_regression = excluded.is_regression`

The full updated `upsert_eval_sample`:

```python
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
```

5. Update `update_feedback()` to auto-log status changes. Replace the existing function:

```python
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
            # Log status change
            if "status" in updates:
                log_feedback_action(feedback_id, "status_change", f"状态变更为: {updates['status']}")
            if updates.get("fix_action"):
                log_feedback_action(feedback_id, "fix_applied", updates["fix_action"])
        return cur.rowcount > 0
```

- [ ] **Step 2: Run existing tests to verify no breakage**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism && python -m pytest scripts/tests/ -v --timeout=30 -x -q 2>&1 | tail -20`
Expected: All existing tests still pass

- [ ] **Step 3: Commit**

```bash
git add scripts/api/database.py
git commit -m "feat: add regression sample flag, fix action tracking, and action log table"
```

---

## Task 4: API Schemas + Endpoints for Fix Tracking and Regression

**Files:**
- Modify: `scripts/api/schemas/feedback.py`
- Modify: `scripts/api/routers/feedback.py`
- Modify: `scripts/api/routers/eval.py`
- Modify: `scripts/api/schemas/eval.py`

- [ ] **Step 1: Update feedback schemas**

In `scripts/api/schemas/feedback.py`:

1. Add `FeedbackActionLog` model:

```python
class FeedbackActionLog(BaseModel):
    id: int
    feedback_id: str
    action: str
    detail: str
    created_at: str
```

2. Add `fix_action` to `FeedbackUpdate`:

```python
class FeedbackUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(pending|classified|fixing|fixed|rejected|converted)$")
    classified_type: Optional[str] = None
    classified_reason: Optional[str] = None
    classified_fix_direction: Optional[str] = None
    compliance_risk: Optional[int] = Field(None, ge=0, le=2)
    fix_action: Optional[str] = None
```

3. Add `fix_action` and `resolved_at` to `FeedbackOut`:

```python
class FeedbackOut(BaseModel):
    id: str
    message_id: int
    conversation_id: str
    rating: str
    reason: str
    correction: str
    source_channel: str
    auto_quality_score: Optional[float] = None
    auto_quality_details: Optional[Dict] = None
    classified_type: Optional[str] = None
    classified_reason: Optional[str] = None
    classified_fix_direction: Optional[str] = None
    status: str
    compliance_risk: int
    fix_action: str = ""
    resolved_at: Optional[str] = None
    created_at: str
    updated_at: str
    user_question: str = ""
    assistant_answer: str = ""
```

- [ ] **Step 2: Add history endpoint to feedback router**

In `scripts/api/routers/feedback.py`, add a new endpoint after the `get_stats` endpoint:

```python
@router.get("/badcases/{feedback_id}/history", response_model=list[FeedbackActionLog])
async def get_badcase_history(feedback_id: str):
    """查看反馈的状态变更历史"""
    from api.schemas.feedback import FeedbackActionLog
    from api.database import get_feedback, get_feedback_history
    fb = get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return get_feedback_history(feedback_id)
```

Also add `FeedbackActionLog` to the imports at the top of the file:
```python
from api.schemas.feedback import (
    FeedbackCreate, FeedbackOut, FeedbackUpdate, FeedbackStats, FeedbackActionLog,
)
```

- [ ] **Step 3: Update convert endpoint to set is_regression**

In `scripts/api/routers/feedback.py`, in the `convert_to_eval_sample` function, update the `upsert_eval_sample` call to include `is_regression: True`:

```python
    sample_id = f"bc_{feedback_id}"
    upsert_eval_sample({
        "id": sample_id,
        "question": user_msg[0],
        "ground_truth": ground_truth or fb.get("correction", ""),
        "evidence_docs": evidence_docs,
        "evidence_keywords": [],
        "question_type": fb.get("classified_type", "factual") or "factual",
        "difficulty": "medium",
        "topic": "",
        "is_regression": True,
    })
```

- [ ] **Step 4: Add regression trigger endpoint to eval router**

In `scripts/api/schemas/eval.py`, update `EvalRunRequest.mode` pattern to include `regression`:

```python
class EvalRunRequest(BaseModel):
    mode: str = Field("full", pattern="^(retrieval|generation|full|regression)$")
```

In `scripts/api/routers/eval.py`, add a new endpoint after `create_eval_run`:

```python
@router.post("/runs/regression")
async def create_regression_run():
    """手动触发回归测试 — 仅运行标记为回归测试的样本"""
    from api.database import get_regression_samples, create_eval_run, eval_sample_count

    regression_samples = get_regression_samples()
    if not regression_samples:
        raise HTTPException(status_code=400, detail="没有回归测试样本，请先将 badcase 转化为评估样本")

    run_id = f"reg_{uuid.uuid4().hex[:8]}"
    create_eval_run(run_id, "regression", {"regression": True})
    _eval_tasks[run_id] = {"status": "pending"}

    async def _run_regression():
        try:
            _eval_tasks[run_id]["status"] = "running"
            from api.app import rag_engine
            if rag_engine is None:
                raise RuntimeError("RAG 引擎未就绪")

            from api.database import update_eval_run_status, save_eval_report, save_sample_result
            from lib.rag_engine.eval_dataset import EvalSample, QuestionType

            samples = [
                EvalSample(
                    id=s["id"],
                    question=s["question"],
                    ground_truth=s["ground_truth"],
                    evidence_docs=s["evidence_docs"],
                    evidence_keywords=s["evidence_keywords"],
                    question_type=QuestionType(s["question_type"]),
                    difficulty=s["difficulty"],
                    topic=s["topic"],
                )
                for s in regression_samples
            ]

            total = len(samples)
            update_eval_run_status(run_id, "running", progress=0, total=total)

            ret_metrics = {"precision_at_k": 0.0, "recall_at_k": 0.0, "mrr": 0.0, "ndcg": 0.0}
            gen_metrics = {"faithfulness": 0.0, "answer_relevancy": 0.0, "answer_correctness": 0.0}

            for i, sample in enumerate(samples):
                result = rag_engine.ask(sample.question, include_sources=True)
                save_sample_result(
                    run_id, sample.id,
                    retrieved_docs=result.get("sources", []),
                    generated_answer=result.get("answer", ""),
                )
                current = i + 1
                _eval_tasks[run_id]["progress"] = current
                update_eval_run_status(run_id, "running", progress=current, total=total)

            report = {
                "retrieval": ret_metrics,
                "generation": gen_metrics,
                "total_samples": total,
                "failed_samples": [],
            }
            save_eval_report(run_id, report)
            update_eval_run_status(run_id, "completed")
            _eval_tasks[run_id]["status"] = "completed"

        except Exception as e:
            logger.error(f"Regression run {run_id} failed: {e}")
            from api.database import update_eval_run_status
            update_eval_run_status(run_id, "failed")
            _eval_tasks[run_id]["status"] = "failed"
            _eval_tasks[run_id]["error"] = str(e)

    asyncio.create_task(_run_regression())
    return {"run_id": run_id, "status": "pending", "total_samples": len(regression_samples)}
```

Note: The `mode` column CHECK constraint in the DDL only allows `retrieval|generation|full`. SQLite doesn't support ALTER CONSTRAINT. Since `create_eval_run` uses a plain INSERT and the CHECK is only enforced at write time, we need to update the schema. The simplest approach: in `_migrate_db()`, add logic to recreate the `eval_runs` table without the restrictive CHECK. Add this to `_migrate_db()`:

```python
        # eval_runs: widen mode CHECK to include 'regression'
        cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_runs)").fetchall()}
        mode_check = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='eval_runs'"
        ).fetchone()
        if mode_check and "'retrieval', 'generation', 'full'" in (mode_check[0] or ""):
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS eval_runs_new (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL DEFAULT (datetime('now')),
                    finished_at TEXT,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    report_json TEXT
                );
                INSERT INTO eval_runs_new SELECT * FROM eval_runs;
                DROP TABLE eval_runs;
                ALTER TABLE eval_runs_new RENAME TO eval_runs;
            """)
```

Also update the `_SCHEMA_SQL` DDL for `eval_runs` to remove the restrictive CHECK:

```sql
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    report_json TEXT
);
```

- [ ] **Step 5: Run existing tests**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism && python -m pytest scripts/tests/ -v --timeout=30 -x -q 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add scripts/api/schemas/feedback.py scripts/api/schemas/eval.py scripts/api/routers/feedback.py scripts/api/routers/eval.py scripts/api/database.py
git commit -m "feat: add fix action tracking API, regression test trigger endpoint"
```

---

## Task 5: Frontend — Fix Action Tracking UI

**Files:**
- Modify: `scripts/web/src/types/index.ts`
- Modify: `scripts/web/src/api/feedback.ts`
- Modify: `scripts/web/src/stores/feedbackStore.ts`
- Modify: `scripts/web/src/pages/FeedbackPage.tsx`

- [ ] **Step 1: Update TypeScript types**

In `scripts/web/src/types/index.ts`, add the `FeedbackActionLog` interface after `FeedbackStats`:

```typescript
export interface FeedbackActionLog {
  id: number;
  feedback_id: string;
  action: string;
  detail: string;
  created_at: string;
}
```

Also add `fix_action` and `resolved_at` to the `Feedback` interface, after `assistant_answer`:

```typescript
export interface Feedback {
  // ... existing fields ...
  user_question: string;
  assistant_answer: string;
  fix_action: string;
  resolved_at: string | null;
}
```

- [ ] **Step 2: Add API functions**

In `scripts/web/src/api/feedback.ts`, add:

1. Update `updateBadcase` to accept `fix_action`:

```typescript
export async function updateBadcase(
  id: string,
  updates: {
    status?: string;
    classified_type?: string;
    classified_reason?: string;
    classified_fix_direction?: string;
    compliance_risk?: number;
    fix_action?: string;
  },
): Promise<Feedback> {
  const { data } = await client.put(`/api/feedback/badcases/${id}`, updates);
  return data;
}
```

2. Add `fetchBadcaseHistory`:

```typescript
export async function fetchBadcaseHistory(id: string): Promise<FeedbackActionLog[]> {
  const { data } = await client.get(`/api/feedback/badcases/${id}/history`);
  return data;
}
```

3. Add the import for `FeedbackActionLog`:

```typescript
import type { Feedback, FeedbackStats, FeedbackActionLog, Source, Citation } from '../types';
```

- [ ] **Step 3: Add history loading to store**

In `scripts/web/src/stores/feedbackStore.ts`, add:

1. Import `FeedbackActionLog`:

```typescript
import type { Feedback, FeedbackStats, FeedbackActionLog } from '../types';
```

2. Add `history` state and `loadHistory` action:

```typescript
interface FeedbackState {
  badcases: Feedback[];
  stats: FeedbackStats | null;
  loading: boolean;
  history: Record<string, FeedbackActionLog[]>;

  loadBadcases: (params?: { status?: string; classified_type?: string }) => Promise<void>;
  loadStats: () => Promise<void>;
  loadHistory: (feedbackId: string) => Promise<void>;
  updateBadcase: (id: string, updates: Record<string, unknown>) => Promise<void>;
  classifyAll: () => Promise<void>;
}
```

3. In the store implementation, add `history: {}` to initial state and add `loadHistory`:

```typescript
  history: {},

  loadHistory: async (feedbackId) => {
    const logs = await feedbackApi.fetchBadcaseHistory(feedbackId);
    set((state) => ({ history: { ...state.history, [feedbackId]: logs } }));
  },
```

- [ ] **Step 4: Update FeedbackPage with fix action UI**

In `scripts/web/src/pages/FeedbackPage.tsx`:

1. Add imports:

```typescript
import React, { useEffect, useState } from 'react';
import { Table, Tag, Select, Button, Space, message, Popconfirm, Modal, Descriptions, Card, Statistic, Row, Col, Tooltip, Input, Timeline } from 'antd';
import { ReloadOutlined, ThunderboltOutlined, DislikeOutlined, LikeOutlined, WarningOutlined, CheckCircleOutlined } from '@ant-design/icons';
```

2. Add action label mapping (after `RISK_LABELS`):

```typescript
const ACTION_LABELS: Record<string, string> = {
  status_change: '状态变更',
  fix_applied: '修复动作',
  classified: '自动分类',
  verified: '验证',
};
```

3. Extract `ExpandedRow` as a proper React component (needed because it uses `useEffect` and `useState`). Place it before `FeedbackPage`:

```typescript
const ExpandedRow: React.FC<{ record: Feedback }> = ({ record }) => {
  const { loadHistory, history, loadBadcases, loadStats, updateBadcase } = useFeedbackStore();
  const [fixAction, setFixAction] = useState('');

  useEffect(() => { loadHistory(record.id); }, [record.id, loadHistory]);

  const actionLogs = history[record.id] || [];

  return (
    <div style={{ padding: '8px 16px' }}>
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="用户问题">
          <span style={{ fontWeight: 500 }}>{record.user_question || '（无法获取）'}</span>
        </Descriptions.Item>
        <Descriptions.Item label="助手回答">
          <div style={{ maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
            {record.assistant_answer || '（无法获取）'}
          </div>
        </Descriptions.Item>
        <Descriptions.Item label="用户反馈">
          <Space>
            {record.rating === 'up'
              ? <Tag icon={<LikeOutlined />} color="green">满意</Tag>
              : <Tag icon={<DislikeOutlined />} color="red">不满意</Tag>}
            {record.reason && <span>原因：{record.reason}</span>}
            {record.correction && (
              <span>修正建议：<span style={{ color: '#1890ff' }}>{record.correction}</span></span>
            )}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="来源渠道">
          {record.source_channel === 'user_button' ? '用户按钮' : record.source_channel === 'auto_detect' ? '自动检测' : record.source_channel}
        </Descriptions.Item>
        {record.classified_type && (
          <Descriptions.Item label="分类详情">
            <Space direction="vertical">
              <span>类型：<Tag color={TYPE_COLORS[record.classified_type]}>{TYPE_LABELS[record.classified_type] || record.classified_type}</Tag></span>
              <span>原因：{record.classified_reason}</span>
              <span>修复方向：{record.classified_fix_direction}</span>
            </Space>
          </Descriptions.Item>
        )}
        {record.auto_quality_details && (
          <Descriptions.Item label="质量评估">
            <Space>
              <Tag>忠实度: {(record.auto_quality_details as any).faithfulness?.toFixed(2) ?? '-'}</Tag>
              <Tag>相关性: {(record.auto_quality_details as any).relevance?.toFixed(2) ?? '-'}</Tag>
              <Tag>完整性: {(record.auto_quality_details as any).completeness?.toFixed(2) ?? '-'}</Tag>
              <Tag color="blue">综合: {record.auto_quality_score?.toFixed(2) ?? '-'}</Tag>
            </Space>
          </Descriptions.Item>
        )}
      </Descriptions>

      {(record.status === 'classified' || record.status === 'fixing' || record.status === 'fixed') && (
        <div style={{ marginTop: 12 }}>
          <h4 style={{ marginBottom: 8 }}>修复记录</h4>
          {record.status !== 'fixed' && (
            <Space style={{ marginBottom: 8 }}>
              <Input.TextArea
                rows={2}
                placeholder="描述修复动作（如：补充了《健康保险管理办法》第三章）"
                value={fixAction}
                onChange={(e) => setFixAction(e.target.value)}
                style={{ width: 400 }}
              />
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={async () => {
                  try {
                    await updateBadcase(record.id, { status: 'fixed', fix_action: fixAction || record.fix_action || '' });
                    message.success('已标记为已修复');
                    setFixAction('');
                    loadBadcases();
                    loadStats();
                  } catch { message.error('操作失败'); }
                }}
              >
                标记已解决
              </Button>
            </Space>
          )}
          {record.fix_action && (
            <div style={{ marginBottom: 8, color: '#52c41a' }}>
              修复动作：{record.fix_action}
              {record.resolved_at && <span style={{ color: '#999', marginLeft: 8 }}>（{record.resolved_at}）</span>}
            </div>
          )}
          {actionLogs.length > 0 && (
            <Timeline
              items={actionLogs.map(log => ({
                children: (
                  <span>
                    <Tag>{ACTION_LABELS[log.action] || log.action}</Tag>
                    {log.detail}
                    <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>{log.created_at}</span>
                  </span>
                ),
              }))}
            />
          )}
        </div>
      )}
    </div>
  );
};
```

4. Remove the old `expandedRowRender` function from `FeedbackPage`. Update the Table to use the new component:

```typescript
expandable={{ expandedRowRender: (record) => <ExpandedRow record={record} /> }}
```

- [ ] **Step 5: Build frontend to check for type errors**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism/scripts/web && npx tsc --noEmit 2>&1 | head -30`
Expected: No type errors

- [ ] **Step 6: Commit**

```bash
git add scripts/web/src/types/index.ts scripts/web/src/api/feedback.ts scripts/web/src/stores/feedbackStore.ts scripts/web/src/pages/FeedbackPage.tsx
git commit -m "feat: add fix action tracking UI with history timeline in feedback page"
```

---

## Task 6: Frontend — Regression Test Trigger

**Files:**
- Modify: `scripts/web/src/api/eval.ts`
- Modify: `scripts/web/src/pages/FeedbackPage.tsx`
- Modify: `scripts/web/src/types/index.ts`

- [ ] **Step 1: Add regression API function**

In `scripts/web/src/api/eval.ts`, add:

```typescript
export async function createRegressionRun(): Promise<{
  run_id: string;
  status: string;
  total_samples: number;
}> {
  const { data } = await client.post('/api/eval/runs/regression');
  return data;
}
```

- [ ] **Step 2: Add regression trigger button to FeedbackPage**

In `scripts/web/src/pages/FeedbackPage.tsx`, add a "运行回归测试" button in the toolbar area (next to "批量分类" button):

1. Add import:

```typescript
import { createRegressionRun } from '../api/eval';
import { useNavigate } from 'react-router-dom';
```

2. Add navigate hook:

```typescript
const navigate = useNavigate();
```

3. Add handler function (after `handleClassify`):

```typescript
const handleRegression = async () => {
  try {
    const result = await createRegressionRun();
    message.success(`回归测试已启动，共 ${result.total_samples} 个样本`);
    navigate('/eval/runs');
  } catch (err: any) {
    const detail = err?.response?.data?.detail || '启动失败';
    message.error(detail);
  }
};
```

4. Add button in the toolbar:

```typescript
<Button icon={<ThunderboltOutlined />} onClick={handleRegression} loading={loading} danger>
  回归测试
</Button>
```

- [ ] **Step 3: Build frontend to check for type errors**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/feedback-mechanism/scripts/web && npx tsc --noEmit 2>&1 | head -30`
Expected: No type errors

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/api/eval.ts scripts/web/src/pages/FeedbackPage.tsx
git commit -m "feat: add regression test trigger button in feedback page"
```

