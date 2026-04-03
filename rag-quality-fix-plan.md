# Actuary Sleuth RAG 系统 — 质量保障体系改进方案

生成时间: 2026-04-03
源文档: worktree-rag-quality-fix-research.md

本方案基于 research.md 的 18 个问题条目生成，按优先级分阶段实施。

---

## 一、问题修复方案 ✅

### 🔴 P1 问题 — 必须修复

---

#### 问题 1.1: [P1] 忠实度评分默认禁用，自动检测形同虚设 ✅

- **文件**: `scripts/lib/rag_engine/quality_detector.py:56-78`
- **严重程度**: P1
- **影响范围**: 自动质量检测渠道完全失效

**当前代码**:

```python
# quality_detector.py:56-78
def detect_quality(
    query: str,
    answer: str,
    sources: List[Dict[str, Any]],
    faithfulness_score: Optional[float] = None,
) -> Dict[str, float]:
    """三维度自动质量评分"""
    faithfulness = faithfulness_score if faithfulness_score is not None else 0.0
    retrieval_relevance = compute_retrieval_relevance(query, sources)
    completeness = compute_info_completeness(query, answer)

    overall = (
        0.4 * faithfulness +
        0.3 * retrieval_relevance +
        0.3 * completeness
    )
    ...
```

**问题分析**: `enable_faithfulness` 默认 `False`（`config.py:54`），导致 `faithfulness_score` 为 `None` → 替换为 `0.0`。忠实度占 40% 权重，此维度恒为 0 时，总分上限为 `0.6`，且高质量回答的总分也仅 `0.48`，距阈值 `0.4` 过近。

**修复方案**: 当 faithful 不可用时，动态调整权重，将 40% 忠实度权重按比例分配给其他两个维度（各变为 50%）。

**代码变更**:

```python
# quality_detector.py:56-78 — 替换 detect_quality 函数
def detect_quality(
    query: str,
    answer: str,
    sources: List[Dict[str, Any]],
    faithfulness_score: Optional[float] = None,
) -> Dict[str, float]:
    """三维度自动质量评分

    当 faithfulness_score 不可用时，自动将权重重新分配给
    retrieval_relevance 和 completeness（各 50%）。
    """
    faithfulness = faithfulness_score if faithfulness_score is not None else 0.0
    retrieval_relevance = compute_retrieval_relevance(query, sources)
    completeness = compute_info_completeness(query, answer)

    if faithfulness_score is not None:
        overall = (
            0.4 * faithfulness +
            0.3 * retrieval_relevance +
            0.3 * completeness
        )
    else:
        overall = (
            0.5 * retrieval_relevance +
            0.5 * completeness
        )

    return {
        "faithfulness": round(faithfulness, 4),
        "retrieval_relevance": round(retrieval_relevance, 4),
        "completeness": round(completeness, 4),
        "overall": round(overall, 4),
    }
```

**涉及文件**:

| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/quality_detector.py` |
| 修改 | `scripts/tests/lib/rag_engine/test_badcase_classifier.py` (新增测试) |

**权衡考虑**:

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 动态权重分配 | 无需改配置，自动适配 | 三维度评分变成两维度，丢失信息 | ✅ |
| B: 默认启用 faithfulness | 完整三维评分 | 增加 LLM 调用开销，影响响应延迟 | ❌ |
| C: 去掉 faithful 维度 | 简化逻辑 | 丢失重要质量信号 | ❌ |

**测试建议**:

```python
# 新增到 test_badcase_classifier.py 或新建 test_quality_detector.py
class TestDetectQualityDynamicWeights:
    def test_without_faithfulness_uses_50_50_weights(self):
        """faithful 不可用时，权重重新分配为 50/50"""
        from lib.rag_engine.quality_detector import detect_quality
        result = detect_quality(
            query="健康保险等待期有什么规定",
            answer="健康保险等待期不得超过90天",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=None,
        )
        # 两个维度各 0.5 权重，relevance 和 completeness 都高时 overall 应 > 0.4
        assert result["faithfulness"] == 0.0
        assert result["overall"] > 0.4

    def test_with_faithfulness_uses_40_30_30_weights(self):
        """faithful 可用时，权重为 40/30/30"""
        from lib.rag_engine.quality_detector import detect_quality
        result = detect_quality(
            query="健康保险等待期有什么规定",
            answer="健康保险等待期不得超过90天",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=0.9,
        )
        expected = 0.4 * 0.9 + 0.3 * result["retrieval_relevance"] + 0.3 * result["completeness"]
        assert abs(result["overall"] - round(expected, 4)) < 0.0001
```

**验收标准**:
- [ ] `faithfulness_score=None` 时 overall 权重正确分配（50/50）
- [ ] `faithfulness_score=0.9` 时 overall 权重正确分配（40/30/30）
- [ ] 高质量回答（relevance>0.8, completeness>0.8）在 faithful 不可用时 overall > 0.4
- [ ] 低质量回答在 faithful 不可用时 overall < 0.4

---

#### 问题 1.2: [P1] 幻觉检测依赖启发式规则，非 LLM 判断 ✅

- **文件**: `scripts/lib/rag_engine/badcase_classifier.py:22-89`
- **严重程度**: P1
- **影响范围**: badcase 分类准确率低

**当前代码**:

```python
# badcase_classifier.py:22-89
def classify_badcase(query, retrieved_docs, answer, unverified_claims):
    # 1. 空 docs → knowledge_gap
    # 2. unverified_claims → hallucination
    # 3. answer 含"未找到" → 按字符重叠判断
    # 4. bigram 重叠 < 0.2 → hallucination
    # 5. 否则 → retrieval_failure
```

**问题分析**:
1. `unverified_claims` 基于正则检测，LLM 引用了但内容有误（如"150% [来源1]"）不会触发
2. bigram 重叠 < 0.2 阈值过低，简洁正确回答会被误判为幻觉
3. 无法区分"检索到了但答案错了"和"检索结果不相关"

**修复方案**: 引入 LLM 辅助分类作为增强模式，保留启发式作为快速预筛。当 `llm_client` 可用时使用 LLM 分类，否则回退到启发式。

**代码变更**:

```python
# badcase_classifier.py — 完整替换

"""Badcase 三分类自动分类 + 合规风险评估。

分类类型（适配本系统无路由错误的场景）：
- retrieval_failure: 检索失败 — 知识库有答案但没检索到
- hallucination: 幻觉生成 — 检索正确但 LLM 答案错误
- knowledge_gap: 知识缺失 — 知识库里确实没有
"""
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """分析以下 RAG 系统的失败案例，判断失败原因类型。

## 用户问题
{query}

## 检索到的文档（Top3）
{docs}

## 系统回答
{answer}

## 未验证声明
{unverified}

请判断失败类型（只能选一个）：
A. retrieval_failure — 检索失败：文档里有答案但没检索到
B. hallucination — 幻觉生成：检索结果正确但 LLM 生成了错误答案
C. knowledge_gap — 知识缺失：知识库里确实没有这个信息

输出 JSON（不要输出其他内容）：{{"type": "A/B/C", "reason": "具体原因"}}"""

_HEURISTIC_GAP_PHRASES = [
    "未找到", "未涉及", "没有找到", "无法确定",
    "未提供", "未包含", "条款中未找到",
]

_COMPLIANCE_AMOUNT_PATTERN = re.compile(
    r'\d+[%元万元]|身故保险金|赔付|赔偿|保额|保费|等待期|免赔'
)
_COMPLIANCE_KEYWORD_PATTERN = re.compile(
    r'(不得|必须|禁止|严禁|不得以|免除|承担|退还|返还)'
)


def classify_badcase(
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    answer: str,
    unverified_claims: List[str],
    llm_client=None,
) -> Dict[str, str]:
    """三分类自动分类

    Args:
        query: 用户问题
        retrieved_docs: 检索到的文档列表
        answer: 系统回答
        unverified_claims: 未验证声明列表
        llm_client: 可选 LLM 客户端，提供时使用 LLM 分类

    Returns:
        包含 type, reason, fix_direction 的字典
    """
    combined_content = " ".join(d.get("content", "") for d in retrieved_docs)
    if not combined_content.strip():
        return {
            "type": "knowledge_gap",
            "reason": "检索结果为空",
            "fix_direction": "补充相关法规文档到知识库",
        }

    # 启发式快速预筛：明确的知识缺失
    if any(phrase in answer for phrase in _HEURISTIC_GAP_PHRASES):
        query_chars = set(query)
        content_chars = set(combined_content)
        if len(query_chars & content_chars) <= 2:
            return {
                "type": "knowledge_gap",
                "reason": f"系统回答表示未找到相关信息: {answer[:100]}",
                "fix_direction": "补充相关法规文档到知识库",
            }

    # LLM 辅助分类
    if llm_client is not None:
        result = _classify_with_llm(
            query, retrieved_docs, answer, unverified_claims, llm_client
        )
        if result is not None:
            return result

    # 回退：启发式分类
    return _classify_heuristic(query, combined_content, answer, unverified_claims)


def _classify_with_llm(
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    answer: str,
    unverified_claims: List[str],
    llm_client,
) -> Optional[Dict[str, str]]:
    """使用 LLM 进行分类，失败时返回 None"""
    docs_text = "\n".join(
        f"[{i}] {d.get('content', '')[:300]}"
        for i, d in enumerate(retrieved_docs[:3], 1)
    )
    unverified_text = "；".join(unverified_claims[:5]) if unverified_claims else "无"

    prompt = _CLASSIFY_PROMPT.format(
        query=query,
        docs=docs_text,
        answer=answer[:500],
        unverified=unverified_text,
    )

    try:
        response = llm_client.generate(prompt)
        return _parse_llm_classification(str(response).strip())
    except Exception as e:
        logger.warning(f"LLM 分类失败，回退到启发式: {e}")
        return None


def _parse_llm_classification(response: str) -> Optional[Dict[str, str]]:
    """解析 LLM 分类结果"""
    import json

    # 提取 JSON 部分
    json_match = re.search(r'\{[^}]+\}', response)
    if not json_match:
        return None

    try:
        data = json.loads(json_match.group())
        type_map = {
            "A": "retrieval_failure",
            "B": "hallucination",
            "C": "knowledge_gap",
            "retrieval_failure": "retrieval_failure",
            "hallucination": "hallucination",
            "knowledge_gap": "knowledge_gap",
        }
        mapped_type = type_map.get(data.get("type", ""))
        if not mapped_type:
            return None

        fix_map = {
            "retrieval_failure": "优化 Chunk 策略、混合检索权重或 RRF 参数",
            "hallucination": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
            "knowledge_gap": "补充相关法规文档到知识库",
        }

        return {
            "type": mapped_type,
            "reason": data.get("reason", ""),
            "fix_direction": fix_map[mapped_type],
        }
    except (json.JSONDecodeError, KeyError):
        return None


def _classify_heuristic(
    query: str,
    combined_content: str,
    answer: str,
    unverified_claims: List[str],
) -> Dict[str, str]:
    """启发式分类（LLM 不可用时的回退）"""
    if unverified_claims:
        claims_preview = "；".join(unverified_claims[:3])
        return {
            "type": "hallucination",
            "reason": f"回答包含 {len(unverified_claims)} 条未引用的事实性陈述: {claims_preview}",
            "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
        }

    if any(phrase in answer for phrase in _HEURISTIC_GAP_PHRASES):
        return {
            "type": "retrieval_failure",
            "reason": "检索到的文档与查询相关但答案表示未找到",
            "fix_direction": "优化 Chunk 策略、混合检索权重或 RRF 参数",
        }

    return {
        "type": "retrieval_failure",
        "reason": "检索结果可能不相关或排序不佳",
        "fix_direction": "优化 Chunk 策略、混合检索权重或 RRF 参数",
    }


def assess_compliance_risk(badcase_type: str, reason: str, answer: str) -> int:
    """评估合规风险等级

    Args:
        badcase_type: 分类类型 (retrieval_failure / hallucination / knowledge_gap)
        reason: 分类原因
        answer: 系统回答

    Returns:
        风险等级: 0=低, 1=中, 2=高
    """
    if not answer:
        return 0

    # 幻觉 + 涉及金额 → 高风险
    if badcase_type == "hallucination" and _COMPLIANCE_AMOUNT_PATTERN.search(answer):
        return 2

    # 任何类型 + 合规关键词 → 中风险
    if _COMPLIANCE_KEYWORD_PATTERN.search(answer):
        return 1

    return 0
```

**涉及文件**:

| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/badcase_classifier.py` |
| 修改 | `scripts/api/routers/feedback.py` (传入 llm_client) |
| 修改 | `scripts/tests/lib/rag_engine/test_badcase_classifier.py` |

**feedback.py 调用侧变更**:

```python
# feedback.py:82-135 — classify_badcases 端点中传入 llm_client
# 在 classify_badcase 调用处添加 llm_client 参数
from lib.rag_engine.badcase_classifier import classify_badcase
from api.dependencies import get_rag_engine

engine = get_rag_engine()
llm_client = engine._llm_client if engine else None

result = classify_badcase(
    query=question,
    retrieved_docs=sources,
    answer=assistant_answer,
    unverified_claims=unverified,
    llm_client=llm_client,
)

# assess_compliance_risk 调用处也更新
risk = assess_compliance_risk(
    badcase_type=result["type"],
    reason=result["reason"],
    answer=assistant_answer,
)
```

**权衡考虑**:

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: LLM 分类 + 启发式回退 | 准确率高（~80%），渐进增强 | 增加 LLM 调用开销（分类场景，可接受） | ✅ |
| B: 纯 LLM 分类 | 最准确 | LLM 不可用时完全失效 | ❌ |
| C: 优化启发式阈值 | 无额外开销 | 准确率提升有限，治标不治本 | ❌ |

**测试建议**:

```python
class TestClassifyBadcaseLLM:
    def test_llm_classify_hallucination_with_wrong_number(self):
        """LLM 应检测出数字错误的幻觉"""
        # 需要 mock LLM client
        pass  # 集成测试

class TestAssessComplianceRiskUpdated:
    def test_hallucination_with_amount_is_high_risk(self):
        """幻觉 + 金额 = 高风险"""
        risk = assess_compliance_risk(
            badcase_type="hallucination",
            reason="数字错误",
            answer="身故保险金为基本保额的150%",
        )
        assert risk == 2

    def test_retrieval_failure_with_amount_is_not_high_risk(self):
        """检索失败 + 金额 ≠ 高风险（答案可能正确）"""
        risk = assess_compliance_risk(
            badcase_type="retrieval_failure",
            reason="检索结果不相关",
            answer="身故保险金为基本保额的200%",
        )
        assert risk < 2
```

**验收标准**:
- [ ] LLM 分类返回有效结果时使用 LLM 分类
- [ ] LLM 分类失败时回退到启发式分类
- [ ] 无 llm_client 时纯启发式分类正常工作
- [ ] 合规风险结合分类类型评估（hallucination + 金额 = 高风险）
- [ ] 现有启发式测试全部通过

---

#### 问题 1.3: [P1] 引用校验仅检查格式，不验证内容 ✅

- **文件**: `scripts/lib/rag_engine/attribution.py:52-84`
- **严重程度**: P1
- **影响范围**: 无法检测数值类幻觉（如"200%"→"150% [来源1]"）

**当前代码**:

```python
# attribution.py:52-84
def parse_citations(answer, sources):
    # 只检查 [来源X] 标注是否存在
    # 不验证引用的具体内容是否与源文档一致
```

**修复方案**: 在 `parse_citations` 返回结果中增加 `content_mismatches` 字段，检测 LLM 回答中引用的数值与源文档中的数值是否一致。

**代码变更**:

```python
# attribution.py — 修改 parse_citations 函数和 AttributionResult

@dataclass(frozen=True)
class AttributionResult:
    """归因分析结果"""
    citations: List[Citation] = field(default_factory=list)
    unverified_claims: List[str] = field(default_factory=list)
    uncited_sources: List[int] = field(default_factory=list)
    content_mismatches: List[Dict[str, Any]] = field(default_factory=list)


# 数值提取模式 — 匹配回答和源文档中的数值
_VALUE_PATTERNS = [
    re.compile(r'(\d+(?:\.\d+)?)\s*[%％]'),           # 百分比
    re.compile(r'(\d+(?:\.\d+)?)\s*(?:倍|元|万元)'),    # 金额/倍数
    re.compile(r'(\d+)\s*(?:天|年|个月|周岁)'),           # 时间
]


def _extract_numeric_values(text: str) -> Dict[str, str]:
    """从文本中提取数值，返回 {归一化数值: 原始匹配文本}"""
    values: Dict[str, str] = {}
    for pattern in _VALUE_PATTERNS:
        for match in pattern.finditer(text):
            values[match.group(1)] = match.group(0)
    return values


def _check_content_mismatches(
    answer: str,
    sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """检测回答中的数值与源文档是否一致

    对比策略：提取回答和各源文档中的数值，检查回答中是否出现了
    源文档中不存在的数值（可能是幻觉）。
    """
    if not answer or not sources:
        return []

    answer_values = _extract_numeric_values(answer)
    if not answer_values:
        return []

    # 收集所有源文档中的数值
    source_values: set = set()
    for source in sources:
        source_values.update(_extract_numeric_values(source.get("content", "")).keys())

    # 找出回答中有但源文档中没有的数值
    mismatches = []
    for value, original_text in answer_values.items():
        if value not in source_values:
            mismatches.append({
                "value": original_text,
                "type": "numeric_mismatch",
            })

    return mismatches


def parse_citations(
    answer: str,
    sources: List[Dict[str, Any]],
) -> AttributionResult:
    """解析 LLM 回答中的引用标注"""
    if not answer or not sources:
        return AttributionResult()

    cited_indices: set[int] = set()
    citations: List[Citation] = []

    for match in _SOURCE_TAG_PATTERN.finditer(answer):
        idx = int(match.group(1)) - 1
        if 0 <= idx < len(sources):
            cited_indices.add(idx)
            source = sources[idx]
            citations.append(Citation(
                source_idx=idx,
                law_name=source.get('law_name', '未知'),
                article_number=source.get('article_number', '未知'),
                content=source.get('content', ''),
            ))

    all_indices = set(range(len(sources)))
    uncited = sorted(all_indices - cited_indices)

    unverified = _detect_unverified_claims(answer, cited_indices)
    mismatches = _check_content_mismatches(answer, sources)

    return AttributionResult(
        citations=citations,
        unverified_claims=unverified,
        uncited_sources=uncited,
        content_mismatches=mismatches,
    )
```

**涉及文件**:

| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/attribution.py` |
| 修改 | `scripts/lib/rag_engine/rag_engine.py:240` (传递 content_mismatches) |
| 修改 | `scripts/api/routers/ask.py:69` (SSE 事件中传递 content_mismatches) |

**rag_engine.py 侧变更**:

```python
# rag_engine.py:242-255 — 在 result dict 中添加 content_mismatches
result: Dict[str, Any] = {
    'answer': answer_str,
    'sources': search_results if include_sources else [],
    'citations': [...],
    'unverified_claims': attribution.unverified_claims,
    'content_mismatches': attribution.content_mismatches,
}
```

**权衡考虑**:

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 数值比对（本方案） | 无 LLM 开销，快速 | 仅检测数值类幻觉，不检测文字类 | ✅ |
| B: LLM 逐句校验 | 最准确 | 大幅增加延迟和成本 | ❌ |
| C: 仅正则增强 | 改动最小 | 准确率提升有限 | ⏳ 备选 |

**测试建议**:

```python
class TestContentMismatchDetection:
    def test_wrong_percentage_detected(self):
        """百分比数值错误应被检测"""
        from lib.rag_engine.attribution import parse_citations
        result = parse_citations(
            answer="身故保险金为基本保额的150%[来源1]",
            sources=[{"content": "身故保险金为基本保额的200%", "law_name": "保险法"}],
        )
        assert len(result.content_mismatches) > 0
        assert result.content_mismatches[0]["value"] == "150%"

    def test_correct_percentage_no_mismatch(self):
        """正确百分比不应产生 mismatch"""
        from lib.rag_engine.attribution import parse_citations
        result = parse_citations(
            answer="身故保险金为基本保额的200%[来源1]",
            sources=[{"content": "身故保险金为基本保额的200%", "law_name": "保险法"}],
        )
        assert len(result.content_mismatches) == 0

    def test_empty_answer_no_mismatch(self):
        from lib.rag_engine.attribution import parse_citations
        result = parse_citations("", [])
        assert result.content_mismatches == []
```

**验收标准**:
- [ ] 回答中出现的百分比/金额/时间数值在源文档中不存在时，产生 mismatch 记录
- [ ] 回答中的数值与源文档一致时，不产生 mismatch
- [ ] `AttributionResult` 新增 `content_mismatches` 字段，默认空列表
- [ ] 现有引用解析测试不受影响

---

#### 问题 1.4: [P1] 无自动化回归测试流程 + 缺少趋势追踪 ✅

- **文件**: `scripts/evaluate_rag.py`, `scripts/api/database.py`
- **严重程度**: P1
- **影响范围**: 修复后无法防止退化

**修复方案**: 在 `evaluate_rag.py` 中添加基线管理和退化检测功能，支持自动保存评估结果到数据库并与上次结果对比。

**代码变更**:

```python
# evaluate_rag.py — 添加基线管理和退化检测

def save_run_to_db(report: Dict, engine_config: Dict) -> int:
    """保存评估运行结果到数据库，返回 run_id"""
    from api.database import get_connection
    import json
    from datetime import datetime

    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO eval_runs (config_json, report_json, created_at)
               VALUES (?, ?, ?)""",
            (json.dumps(engine_config, ensure_ascii=False),
             json.dumps(report, ensure_ascii=False),
             datetime.now().isoformat()),
        )
        return cursor.lastrowid


def detect_regressions(current_report: Dict, baseline_report: Dict) -> Dict:
    """检测指标退化，返回退化详情

    对比当前报告与基线报告，检测是否有指标退化超过容差。

    Args:
        current_report: 当前评估报告
        baseline_report: 基线评估报告

    Returns:
        {
            "passed": bool,
            "degradations": [{"metric": str, "baseline": float, "current": float, "delta": float}],
            "improvements": [{"metric": str, "baseline": float, "current": float, "delta": float}],
        }
    """
    TOLERANCE = 0.02  # 2% 容差

    metrics_to_check = [
        ("recall@5", "retrieval.recall@5"),
        ("faithfulness", "generation.faithfulness"),
        ("answer_correctness", "generation.answer_correctness"),
    ]

    degradations = []
    improvements = []

    for display_name, key_path in metrics_to_check:
        keys = key_path.split(".")
        current_val = current_report
        baseline_val = baseline_report
        try:
            for k in keys:
                current_val = current_val[k]
                baseline_val = baseline_val[k]
        except (KeyError, TypeError):
            continue

        delta = current_val - baseline_val
        if delta < -TOLERANCE:
            degradations.append({
                "metric": display_name,
                "baseline": baseline_val,
                "current": current_val,
                "delta": round(delta, 4),
            })
        elif delta > TOLERANCE:
            improvements.append({
                "metric": display_name,
                "baseline": baseline_val,
                "current": current_val,
                "delta": round(delta, 4),
            })

    return {
        "passed": len(degradations) == 0,
        "degradations": degradations,
        "improvements": improvements,
    }
```

**涉及文件**:

| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/evaluate_rag.py` |
| 修改 | `scripts/api/database.py` (确保 eval_runs 表支持 config_json) |

**权衡考虑**:

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 数据库存储 + 退化检测（本方案） | 持久化，可追溯 | 需要 DB 迁移 | ✅ |
| B: 文件存储 + diff 对比 | 无需改 DB | 不易查询和可视化 | ❌ |
| C: CI/CD 集成 | 自动化程度最高 | 需要额外基础设施 | ⏳ 后续 |

**验收标准**:
- [ ] `save_run_to_db` 能正确保存评估结果到数据库
- [ ] `detect_regressions` 能检测 2% 以上的退化
- [ ] 退化检测覆盖 recall@5、faithfulness、answer_correctness 三个核心指标
- [ ] 无退化时 `passed=True`

---

### ⚠️ P2 问题 — 尽快修复

---

#### 问题 2.1: [P2] 检索相关性仅用 bigram 重叠

- **文件**: `scripts/lib/rag_engine/quality_detector.py:14-33`
- **严重程度**: P2

**修复方案**: 用 embedding cosine similarity 替代 bigram 重叠，复用已有 `JinaEmbeddingAdapter`。

**代码变更**:

```python
# quality_detector.py:14-33 — 替换 compute_retrieval_relevance

def compute_retrieval_relevance(query: str, sources: List[Dict[str, Any]]) -> float:
    """计算 query 与检索结果的语义相关性

    使用 embedding cosine similarity 替代 bigram 重叠。
    不可用时回退到 bigram 方法。
    """
    if not query or not sources:
        return 0.0

    # 尝试 embedding 方法
    embedding_score = _compute_embedding_relevance(query, sources)
    if embedding_score is not None:
        return embedding_score

    # 回退到 bigram 方法
    return _compute_bigram_relevance(query, sources)


def _compute_embedding_relevance(
    query: str, sources: List[Dict[str, Any]]
) -> Optional[float]:
    """使用 embedding 计算 query 与最高分检索文档的语义相似度"""
    try:
        from lib.llm import LLMClientFactory
        from llama_index.core import QueryBundle, Settings

        embed_llm = LLMClientFactory.create_embed_llm()
        embed_model = None
        if hasattr(embed_llm, 'embed_model'):
            embed_model = embed_llm.embed_model
        if embed_model is None:
            return None

        query_embedding = embed_model.get_query_embedding(query)
        if not query_embedding:
            return None

        best_score = 0.0
        for source in sources:
            content = source.get("content", "")
            if not content:
                continue
            doc_embedding = embed_model.get_text_embedding(content)
            if not doc_embedding:
                continue
            score = _cosine_similarity(query_embedding, doc_embedding)
            best_score = max(best_score, score)

        return best_score
    except Exception:
        return None


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度"""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _compute_bigram_relevance(query: str, sources: List[Dict[str, Any]]) -> float:
    """Bigram 重叠（回退方法）"""
    query_bigrams = _token_bigrams(query)
    if not query_bigrams:
        return 0.0

    context_bigrams: set = set()
    for s in sources:
        content = s.get("content", "")
        if content:
            context_bigrams |= _token_bigrams(content)

    if not context_bigrams:
        return 0.0

    matched = query_bigrams & context_bigrams
    return len(matched) / len(query_bigrams)
```

**权衡考虑**:

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: Embedding + bigram 回退 | 语义准确，有兜底 | embed 调用开销 | ✅ |
| B: 纯 embedding | 最准确 | 不可用时完全失效 | ❌ |
| C: 优化 bigram（jieba 分词） | 无额外开销 | 仍无法捕捉语义 | ❌ |

**验收标准**:
- [ ] embedding 可用时使用 cosine similarity
- [ ] embedding 不可用时回退到 bigram
- [ ] 语义相关但字面不同的 query-source 对，relevance > 0.5

---

#### 问题 2.2: [P2] Query LLM 重写使用原始 query 而非归一化结果 ✅ (已在前序合并中修复)

- **文件**: `scripts/lib/rag_engine/query_preprocessor.py:63-68`
- **严重程度**: P2

**修复方案**: 将 `_rewrite_with_llm(query)` 改为 `_rewrite_with_llm(normalized)`。

**代码变更**:

```python
# query_preprocessor.py:63-68 — 修改 preprocess 方法
def preprocess(self, query: str) -> PreprocessedQuery:
    normalized = self._normalize(query)

    # 传入归一化后的 query，避免 LLM 重新引入口语化表达
    rewritten = self._rewrite_with_llm(normalized)
    if rewritten and rewritten != normalized:
        normalized = rewritten

    expanded = self._expand(normalized)
    ...
```

**涉及文件**: `scripts/lib/rag_engine/query_preprocessor.py` (1 行修改)

**验收标准**:
- [ ] `_rewrite_with_llm` 接收归一化后的 query
- [ ] 现有预处理测试不受影响

---

#### 问题 2.3: [P2] 无检索相关性阈值过滤 ✅

- **文件**: `scripts/lib/rag_engine/retrieval.py:108-112`, `scripts/lib/rag_engine/fusion.py:78`
- **严重程度**: P2

**修复方案**: 在 `fusion.py` 的 `reciprocal_rank_fusion` 返回结果后，在 `rag_engine.py` 的 `_hybrid_search` 中添加阈值过滤。

**代码变更**:

```python
# config.py — 在 HybridQueryConfig 中添加阈值配置
@dataclass
class HybridQueryConfig:
    """混合查询配置"""
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 1.0
    enable_rerank: bool = True
    rerank_top_k: int = 5
    reranker_type: str = "llm"
    max_chunks_per_article: int = 3
    min_rrf_score: float = 0.0  # RRF 最低分数阈值，低于此值视为无相关结果
```

```python
# rag_engine.py:344-374 — 在 _hybrid_search 中添加阈值过滤
def _hybrid_search(self, query_text, top_k=None, filters=None):
    ...
    results = hybrid_search(...)

    # 阈值过滤：最高分低于阈值时返回空（视为无相关文档）
    if results and config.min_rrf_score > 0:
        max_score = results[0].get('score', 0) if results else 0
        if max_score < config.min_rrf_score:
            logger.debug(f"最高 RRF 分数 {max_score:.4f} 低于阈值 {config.min_rrf_score}")
            return []

    if self._reranker:
        results = self._reranker.rerank(query_text, results, top_k=top_k)

    return results
```

**权衡考虑**:

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: RRF 分数阈值（本方案） | 简单有效，在融合后过滤 | 阈值需要根据数据调优 | ✅ |
| B: 向量相似度阈值 | 更直观 | 仅考虑一路检索 | ❌ |
| C: 不加阈值 | 零改动 | 对不相关问题强行回答 | ❌ |

**验收标准**:
- [ ] `min_rrf_score=0.0` 时行为与当前一致（不过滤）
- [ ] `min_rrf_score>0` 时，低分结果被过滤
- [ ] 过滤后返回空列表，触发"未找到相关法规条款"fallback

---

#### 问题 2.4: [P2] 合规风险评估过于简单 ✅ (已与问题 1.2 一并修复)

- **文件**: `scripts/lib/rag_engine/badcase_classifier.py:92-103`
- **严重程度**: P2

**修复方案**: 已在问题 1.2 的代码变更中一并修复。`assess_compliance_risk` 现在接收 `badcase_type` 参数，只有 `hallucination + 金额` 才标记为高风险。

**验收标准**:
- [ ] hallucination + 金额 → 风险等级 2
- [ ] retrieval_failure + 金额 → 风险等级 1（非高风险）
- [ ] 任何类型 + 合规关键词 → 风险等级 1
- [ ] 无关键词和金额 → 风险等级 0

---

#### 问题 2.5: [P2] 检索结果截断不尊重语义边界 ✅ (已在前序合并中修复)

- **文件**: `scripts/lib/rag_engine/rag_engine.py:289-294`
- **严重程度**: P2

**修复方案**: 按句子边界（`。`、`\n`）截断，而非纯字符数。

**代码变更**:

```python
# rag_engine.py:276-300 — 替换 _build_qa_prompt 中的截断逻辑
@staticmethod
def _build_qa_prompt(config: 'RAGConfig', question: str, search_results: List[Dict[str, Any]]) -> tuple[str, int]:
    context_parts: List[str] = []
    total_chars = 0
    max_chars = config.max_context_chars

    for i, result in enumerate(search_results, 1):
        law_name = result.get('law_name', '未知法规')
        article = result.get('article_number', '')
        content = result.get('content', '')
        header = f"{i}. 【{law_name}】{article}\n"
        full_part = header + content

        if total_chars + len(full_part) > max_chars:
            remaining = max_chars - total_chars - 50
            if remaining > 100:
                # 按句子边界截断：在 remaining 范围内找最后一个句号/换行
                truncation_point = content[:remaining]
                for sep in ['\n', '。', '；', '，']:
                    last_sep = truncation_point.rfind(sep)
                    if last_sep > remaining // 3:  # 不回退超过 2/3
                        truncation_point = content[:last_sep + len(sep)]
                        break
                truncated_content = truncation_point + '……'
                context_parts.append(header + truncated_content)
            break

        context_parts.append(full_part)
        total_chars += len(full_part)

    context = "\n\n".join(context_parts)
    return _QA_PROMPT_TEMPLATE.format(context=context, question=question), len(context_parts)
```

**验收标准**:
- [ ] 截断优先在 `。` 或 `\n` 处断开
- [ ] 不会回退超过内容 2/3 的长度
- [ ] 现有 prompt 构建测试不受影响

---

#### 问题 2.6: [P2] Reranker 截断 800 字符 ✅

- **文件**: `scripts/lib/rag_engine/llm_reranker.py:82`
- **严重程度**: P2

**修复方案**: 将截断提升到 1500 字符（覆盖大多数条款），并在 `RerankConfig` 中可配置。

**代码变更**:

```python
# llm_reranker.py:31-35 — RerankConfig 添加 max_content_chars
@dataclass(frozen=True)
class RerankConfig:
    enabled: bool = True
    top_k: int = 5
    max_candidates: int = 20
    max_content_chars: int = 1500  # 精排时每条款最大字符数
```

```python
# llm_reranker.py:82 — 使用配置值
truncated = content[:self._config.max_content_chars] if len(content) > self._config.max_content_chars else content
```

**验收标准**:
- [ ] 默认截断 1500 字符（覆盖大多数完整条款）
- [ ] `max_content_chars` 可通过 RerankConfig 配置
- [ ] 现有精排测试不受影响

---

#### 问题 2.7: [P2] 分类需手动触发 ✅

- **文件**: `scripts/api/routers/feedback.py:82-135`
- **严重程度**: P2

**修复方案**: 在 API 启动时注册后台定时任务，自动执行分类。使用 FastAPI 的 `asyncio.create_task`。

**代码变更**:

```python
# app.py — 在 lifespan 中启动自动分类任务
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # 启动
    ...
    # 启动自动分类后台任务
    task = asyncio.create_task(auto_classify_loop())
    yield
    # 关闭
    task.cancel()
    ...

async def auto_classify_loop():
    """每小时自动分类 pending 状态的 badcase"""
    import asyncio
    while True:
        try:
            await asyncio.sleep(3600)  # 每小时执行
            from api.database import get_pending_feedback_count
            count = get_pending_feedback_count()
            if count > 0:
                from api.routers.feedback import classify_pending_badcases
                await classify_pending_badcases()
                logger.info(f"自动分类完成，处理 {count} 条 pending badcase")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"自动分类任务失败: {e}")
```

**权衡考虑**:

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: FastAPI lifespan + asyncio | 无外部依赖，简单 | 进程重启时重置 | ✅ |
| B: 系统 cron + API 调用 | 可靠性高 | 需要外部配置 | ⏳ |
| C: Celery Beat | 分布式，专业 | 引入新依赖 | ❌ |

**验收标准**:
- [ ] 服务启动后自动开始定时分类
- [ ] 无 pending badcase 时跳过执行
- [ ] 分类失败不影响主服务

---

## 二、测试覆盖改进方案

### 当前测试覆盖分析

| 模块 | 已有测试 | 覆盖率估算 | 关键缺口 |
|------|---------|-----------|---------|
| quality_detector.py | ❌ 无 | 0% | detect_quality, compute_retrieval_relevance |
| badcase_classifier.py | ✅ 有 | 60% | LLM 分类路径、合规风险新逻辑 |
| attribution.py | ❌ 无 | 0% | content_mismatches 检测 |
| query_preprocessor.py | ✅ 有 | 70% | LLM 重写传入归一化 query |
| fusion.py | ✅ 有 | 85% | 阈值过滤 |
| retrieval.py | ✅ 有 | 70% | — |
| reranker.py | ❌ 无 | 0% | 截断字符数配置 |
| rag_engine.py | ✅ 有 | 60% | _build_qa_prompt 截断逻辑 |

### 新增测试计划

| 优先级 | 测试文件 | 测试内容 |
|--------|---------|---------|
| P1 | `test_quality_detector.py` (新建) | 动态权重、embedding 回退、bigram 回退 |
| P1 | `test_badcase_classifier.py` (扩展) | LLM 分类路径、合规风险新签名 |
| P1 | `test_attribution.py` (新建) | content_mismatches 检测 |
| P2 | `test_qa_prompt.py` (扩展) | 句子边界截断 |
| P2 | `test_reranker.py` (新建) | max_content_chars 配置 |

---

## 三、技术债务清理方案

### 债务清单

| 优先级 | 债务 | 位置 | 处理方式 |
|--------|------|------|---------|
| P2 | `_detect_unverified_claims` 逻辑复杂且脆弱 | attribution.py:87-128 | 保留但降级为辅助信号 |
| P3 | 评估数据集仅 30 条硬编码 | eval_dataset.py:90-396 | 通过 badcase 转换逐步扩充 |
| P3 | 知识库无老化检测 | version_manager.py | 添加版本年龄检查 |

---

## 四、架构和代码质量改进

### 4.1 反馈闭环自动化路线图

```
当前状态:
  用户反馈 ─→ DB ─→ [手动] 分类 ─→ [手动] 验证 ─→ [手动] 转评估样本

目标状态（分阶段）:
  阶段一 (本次):
    用户反馈 ─→ DB ─→ [自动] 分类(LLM) ─→ DB
    自动质量检测 ─→ DB (修复权重)

  阶段二:
    [定时] 分类 ─→ [自动] 高风险告警 ─→ DB

  阶段三:
    [自动] 验证 ─→ [自动] 回归测试 ─→ 告警
```

### 4.2 数据库 Schema 变更

无需新建表。现有 `feedback` 表已包含所需字段：
- `classified_type` — 存储分类结果
- `auto_quality_score` — 存储质量分数
- `auto_quality_details_json` — 存储详细指标
- `status` — 工作流状态

唯一需要确认的是 `messages` 表是否支持 `content_mismatches_json` 列，可在 `_migrate_db()` 中增量添加。

---

## 附录

### 执行顺序建议

```
1. [P1] 修复 quality_detector.py 动态权重      ← 无依赖，可立即执行
2. [P1] 修复 attribution.py 内容校验           ← 无依赖，可立即执行
3. [P2] 修复 query_preprocessor.py 归一化传递   ← 无依赖，可立即执行
4. [P2] 修复 llm_reranker.py 截断长度           ← 无依赖，可立即执行
5. [P1] 升级 badcase_classifier.py LLM 分类     ← 依赖 1（质量检测修复后分类更准确）
6. [P2] 修复 rag_engine.py 句子边界截断         ← 无依赖
7. [P2] 添加 fusion.py 阈值过滤                 ← 无依赖
8. [P1] 添加 evaluate_rag.py 回归检测           ← 无依赖
9. [P2] 添加自动分类定时任务                     ← 依赖 5
```

步骤 1-4 可并行执行，步骤 5 依赖 1 完成。

### 变更摘要

| 操作 | 文件数 | 风险 |
|------|--------|------|
| 修改 | 10 个文件 | 低 |
| 新建 | 2 个测试文件 | 无 |
| 删除 | 0 | 无 |
| 数据库迁移 | 0（可选 1 列） | 低 |

### 验收标准总结

#### 功能验收标准

- [ ] 自动质量检测在 faithful 不可用时正确计算 overall 分数
- [ ] Badcase 分类支持 LLM 辅助模式，准确率提升
- [ ] 引用校验能检测数值类幻觉（content_mismatches）
- [ ] 回归测试支持基线保存和退化检测
- [ ] 检索相关性检测使用 embedding 语义相似度
- [ ] Query 预处理使用归一化后的 query 进行 LLM 重写
- [ ] Reranker 截断长度可配置且默认 1500 字符
- [ ] 上下文构建按句子边界截断
- [ ] 检索管线支持 RRF 分数阈值过滤
- [ ] 合规风险结合分类类型评估

#### 质量验收标准

- [ ] 所有现有测试通过（`pytest scripts/tests/`）
- [ ] 新增测试覆盖所有修改的模块
- [ ] 类型检查通过（`mypy scripts/lib/rag_engine/`）

#### 部署验收标准

- [ ] 所有修改向后兼容（数据库 schema 无破坏性变更）
- [ ] 新增功能可通过配置关闭（embedding 不可用时回退）
- [ ] LLM 分类失败时优雅降级到启发式
