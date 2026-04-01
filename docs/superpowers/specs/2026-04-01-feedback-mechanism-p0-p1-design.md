# Feedback Mechanism P0+P1 Improvement Design

**Goal:** Upgrade the RAG badcase feedback mechanism from MVP to operational-grade by replacing rule-based classification with LLM-driven structured classification, upgrading quality detection to LLM-based evaluation, adding manual regression testing, and implementing fix action tracking.

**Architecture:** Four independent improvement modules, each modifying existing files without introducing new packages. All LLM calls go through the existing `rag_engine.llm_provider`. No new external dependencies.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Ant Design (frontend), SQLite (database), existing LLM provider

---

## Module 1: LLM Structured Badcase Classifier

### Problem
Current `badcase_classifier.py` uses heuristic rules (bigram overlap, keyword matching) to classify badcases into three categories. Classification accuracy is low — most cases fall into the "hallucination" catch-all. This makes it hard for operators to triage and fix issues efficiently.

### Design
Replace rule-based classification with LLM structured output. Delete all heuristic rule code.

**Classification categories (unchanged):**
- `retrieval_failure`: Relevant documents were not retrieved
- `hallucination`: Answer contains content not supported by sources
- `knowledge_gap`: Information does not exist in the knowledge base

**LLM prompt:**
```
Given the following information:
- User question: {query}
- Retrieved sources: {sources}
- Assistant answer: {answer}
- Unverified claims: {unverified_claims}
- User feedback reason: {reason}

Classify this badcase into one of:
- retrieval_failure: relevant documents were not retrieved
- hallucination: answer contains unsupported content
- knowledge_gap: information does not exist in the knowledge base

Return JSON:
{"type": "<category>", "reason": "<why>", "fix_direction": "<what to fix>"}
```

**Interface:**
- `classify_badcase(query, sources, answer, unverified_claims, reason="")` — signature unchanged
- Returns `{"type": str, "reason": str, "fix_direction": str}`
- No fallback to rules — if LLM fails, raise exception (caller in `feedback.py` has try/except, will skip that item)
- No `confidence` field (keep it simple)

**Compliance risk assessment (`assess_compliance_risk`):**
- Also upgrade to LLM-based evaluation
- Prompt asks LLM to assess risk level (0=low, 1=medium, 2=high) based on the badcase content
- Fallback: if LLM fails, return 0 (low risk, safe default)

**Files:**
- Modify: `scripts/lib/rag_engine/badcase_classifier.py` — full rewrite of classification logic
- No schema changes needed (classified_type, classified_reason, classified_fix_direction fields already exist)

---

## Module 2: LLM Quality Detection

### Problem
Current `quality_detector.py` uses bigram overlap for faithfulness/relevance/completeness scoring. This is semantically blind — synonym substitution causes false negatives, long questions inflate relevance scores, and thresholds are arbitrary.

### Design
Replace bigram-based scoring with LLM-based evaluation. Single LLM call evaluates all three dimensions.

**LLM prompt:**
```
Evaluate the quality of the following answer from three dimensions.

User question: {query}
Source content: {sources}
Answer content: {answer}

Dimensions:
1. faithfulness: Is the answer strictly grounded in the sources? No unsupported claims?
2. relevance: Does the answer directly address the user's question?
3. completeness: Does the answer adequately cover all aspects of the question?

Score each dimension 0.0-1.0.

Return JSON:
{
  "faithfulness": {"score": 0.0-1.0, "issues": ""},
  "relevance": {"score": 0.0-1.0, "issues": ""},
  "completeness": {"score": 0.0-1.0, "issues": ""}
}
```

**Interface:**
- `detect_quality(query, answer, sources)` — signature unchanged
- Returns `{"faithfulness": float, "relevance": float, "completeness": float, "overall": float}`
- `overall` = weighted average: faithfulness×0.4 + relevance×0.3 + completeness×0.3
- Delete all bigram/tokenization code
- If LLM fails, raise exception (caller handles gracefully)

**Files:**
- Modify: `scripts/lib/rag_engine/quality_detector.py` — full rewrite

---

## Module 3: Manual Regression Testing

### Problem
Badcases converted to eval samples have no way to be re-run as a regression suite. Operators cannot verify that system changes don't reintroduce previously fixed issues.

### Design
Tag badcase-derived eval samples as regression samples. Add a manual trigger endpoint to run regression tests using the existing eval infrastructure.

**Database changes:**
- `eval_samples` table: add `is_regression` INTEGER DEFAULT 0
- Migration: `ALTER TABLE eval_samples ADD COLUMN is_regression INTEGER DEFAULT 0`
- `convert_to_eval_sample` sets `is_regression = 1`

**API changes:**
- `POST /api/eval/runs/regression` — new endpoint
  - Queries all samples where `is_regression = 1`
  - If no regression samples exist, returns 400
  - Starts a new eval run with `mode = 'regression'`, using only regression samples
  - Reuses existing `start_eval_run` logic
  - Returns the new run's ID and status

**Frontend changes:**
- FeedbackPage: when a badcase is successfully converted, show confirmation "已标记为回归测试样本"
- EvalRunPage: regression runs appear in the run list with mode='regression', can be compared like any other run

**No new UI pages needed** — the existing eval comparison UI handles this.

**Files:**
- Modify: `scripts/api/database.py` — add `is_regression` to sample schema, add regression query
- Modify: `scripts/api/routers/eval.py` — add regression trigger endpoint
- Modify: `scripts/api/routers/feedback.py` — update convert to set `is_regression`
- Modify: `scripts/web/src/pages/FeedbackPage.tsx` — update convert confirmation
- Modify: `scripts/web/src/api/eval.ts` — add regression trigger API call

---

## Module 4: Fix Action Tracking

### Problem
Knowledge gap badcases have no way to record what fix was applied. Operators cannot track the resolution history of individual badcases or measure fix effectiveness.

### Design
Add fix action recording and status change history to the feedback system.

**Database changes:**

1. `feedback` table: add columns
   - `fix_action` TEXT — description of the fix applied (e.g., "补充了《健康保险管理办法》第三章")
   - `resolved_at` TEXT — ISO timestamp when marked as fixed

2. New `feedback_action_log` table:
   ```sql
   CREATE TABLE feedback_action_log (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     feedback_id TEXT NOT NULL REFERENCES feedback(id),
     action TEXT NOT NULL,          -- 'classified', 'status_change', 'fix_applied', 'verified'
     detail TEXT DEFAULT '',
     created_at TEXT NOT NULL DEFAULT (datetime('now'))
   )
   CREATE INDEX idx_action_log_feedback ON feedback_action_log(feedback_id)
   ```

**API changes:**

- `PUT /api/feedback/badcases/{id}` — existing endpoint, expand `FeedbackUpdate` schema:
  - Add optional `fix_action` field

- `GET /api/feedback/badcases/{id}/history` — new endpoint
  - Returns list of action log entries for a feedback item
  - Ordered by `created_at` desc

- When status changes via update, automatically insert an action log entry

**Frontend changes:**

- FeedbackPage expanded row: add "修复记录" section
  - When status is `classified` or `fixing`: show textarea for `fix_action` + "标记已解决" button
  - "标记已解决" sends `PUT` with `status=fixed` and `fix_action`
  - Below the input: show action history timeline (auto-logs status changes)

**Status flow (unchanged):**
`pending → classified → fixing → fixed/rejected/converted`

**Files:**
- Modify: `scripts/api/database.py` — add feedback_action_log table, action logging functions, fix_action/resolved_at fields
- Modify: `scripts/api/schemas/feedback.py` — add fix_action to FeedbackUpdate, add FeedbackActionLog schema
- Modify: `scripts/api/routers/feedback.py` — add history endpoint, auto-log on status change
- Modify: `scripts/web/src/pages/FeedbackPage.tsx` — add fix action UI and history timeline
- Modify: `scripts/web/src/api/feedback.ts` — add history API call
- Modify: `scripts/web/src/types/index.ts` — add FeedbackActionLog type

---

## Non-Goals (deferred to P2/P3)
- Pagination and keyword search for badcase list
- Trend charts and time-series analytics
- Batch operations (classify/verify/convert multiple at once)
- Structured feedback buttons (reason selection UI)
- Auto-triggered regression testing on knowledge base updates
- Gradual/canary release mechanism
- Feedback-driven system improvement automation (auto-suggest knowledge base updates)
