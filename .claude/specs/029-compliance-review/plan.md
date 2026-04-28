# Implementation Plan: 合规审核模块系统化 Review

**Branch**: `029-compliance-review` | **Date**: 2026-04-28 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

基于 spec.md 的 6 个 User Story 和深度代码分析，发现 **当前实现与设计意图存在严重偏差**：`build_enhanced_context` 已正确实现全量法规检索（通过 `search_by_metadata`），但路由层对文档和法规做了不必要的截断，导致检查不完整。

**核心修复**：
1. **移除不必要的截断** — 128k 模型完全能承载完整文档 + 全量法规
2. **负面清单批量检查** — 从 N 次 LLM 调用改为 1 次
3. **数据正确性问题** — 枚举值对齐、降级语义、双定义标注

## Technical Context

**Language/Version**: Python 3.x
**Primary Dependencies**: fastapi, pydantic, pytest (现有，无新增)
**LLM Context Window**: 128k tokens (≈186,000 中文字符)
**Testing**: pytest + unittest.mock
**Constraints**: 向后兼容 API 请求/响应格式；不改 doc_parser/rag_engine 内部实现

## Token 预算分析

```
LLM 上下文窗口: 128,000 tokens
输出预留: 4,000 tokens
可用于输入: 124,000 tokens ≈ 186,000 中文字符

完整合规检查场景:
├── 文档内容: 30,000 字符 ≈ 20,000 tokens
├── 全量法规:
│   ├── 保险法 180 条款 ≈ 36,000 字符
│   ├── 健康保险管理办法 50 条款 ≈ 10,000 字符
│   └── 其他法规 ≈ 20,000 字符
│   └── 小计: ~66,000 字符 ≈ 44,000 tokens
├── 负面清单 30 条规则 ≈ 6,000 字符 ≈ 4,000 tokens
├── 提示词模板: 500 字符 ≈ 333 tokens
└── 总计: 68,333 tokens (54% 利用率)

结论: 128k 模型完全够用，不需要截断！
```

## Constitution Check

- [x] Library-First: 复用现有 `regulation_registry`、`product_types.classify_product`、`rag_engine.get_engine`、`llm.get_qa_llm`
- [x] 测试优先: Phase 2 优先补齐测试，Phase 1 修改同步更新测试
- [x] 简单优先: 移除截断（最简单）；枚举值直接改为简称；降级用 Tuple 返回
- [x] 显式优于隐式: `check_negative_list` 返回 `(items, checked)` 显式传递降级状态
- [x] 可追溯性: 每个 Phase 回溯到 spec.md User Story
- [x] 独立可测试: 每个 User Story 有独立验收场景

## Project Structure

### Documentation

```text
.claude/specs/029-compliance-review/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code (修改范围)

```text
scripts/
├── lib/common/
│   ├── product_types.py        # Phase 1: 枚举值改为简称
│   └── models.py               # Phase 1: 添加注释标注
├── lib/compliance/
│   └── checker.py              # Phase 1: check_negative_list 返回 Tuple + 批量检查
├── api/
│   └── routers/compliance.py   # Phase 1: 移除截断 + 适配新签名
└── tests/compliance/
    ├── test_clause_level.py    # Phase 2: 重写
    ├── test_negative_list.py   # Phase 1: 更新适配新签名
    └── test_checker.py         # Phase 2: 新增
```

---

## Implementation Phases

### Phase 1: 数据正确性修复 (P0)

→ 回溯 spec.md: US1 (合规检查主链路质量保障)、US2 (法规检索策略有效性)、US4 (险种识别准确性)

---

#### Step 1.1: 移除文档和法规的不必要截断

- **文件**: `scripts/api/routers/compliance.py:42-44`
- **问题**: 
  - 当前代码截断文档到 3,000 字符、法规到 8,000 字符
  - `build_enhanced_context` 已正确返回全量法规（通过 `search_by_metadata`），但被路由层截断
  - 这与 `search_by_metadata` 的设计意图相悖：该函数就是为全量检索设计的
- **Token 验证**: 完整文档(30k) + 全量法规(66k) = 96k 字符 ≈ 64k tokens，在 128k 范围内
- **变更**:

```python
# 当前
prompt = COMPLIANCE_PROMPT_DOCUMENT.format(
    document_content=req.document_content[:3000],  # ❌ 不必要的截断
    context=context[:8000],                         # ❌ 不必要的截断
)

# 修改后
prompt = COMPLIANCE_PROMPT_DOCUMENT.format(
    document_content=req.document_content,  # ✅ 完整文档
    context=context,                         # ✅ 全量法规
)
```

- **超大文档保护**: 仅在文档超过 150,000 字符时按条款边界截断

```python
MAX_DOCUMENT_CHARS = 150_000  # 约 100k tokens

def _prepare_document_content(content: str) -> str:
    """准备文档内容，超大文档按条款边界截断"""
    if len(content) <= MAX_DOCUMENT_CHARS:
        return content
    # 按条款边界截断
    truncated = content[:MAX_DOCUMENT_CHARS]
    last_clause = truncated.rfind("\n【条款")
    if last_clause > 0:
        return truncated[:last_clause]
    return truncated
```

---

#### Step 1.2: 负面清单批量检查（替代逐条调用）

- **文件**: `scripts/lib/compliance/checker.py:49-156`
- **问题**:
  - 当前每条规则一次 LLM 调用（N 次调用）
  - 每次调用文档截断到 2,000 字符
  - 规则内容截断到 500 字符
- **变更**: 重写 `check_negative_list` 和 `_check_violation`

```python
def check_negative_list(document_content: str) -> Tuple[List[Dict], bool]:
    """执行负面清单检查（批量，一次 LLM 调用）

    Returns:
        (items, checked): 违规项列表 + 是否实际执行了检查
    """
    negative_docs = _load_negative_list()
    if not negative_docs:
        logger.warning("知识库中未找到负面清单文档")
        return [], False

    # 构建包含所有规则的 prompt
    rules_text = "\n".join([
        f"{i+1}. 【{doc.get('law_name', '')}】{doc.get('article_number', '')}: {doc.get('content', '')}"
        for i, doc in enumerate(negative_docs)
        if doc.get("content") and doc.get("article_number")
    ])

    if not rules_text:
        return [], True

    prompt = f"""你是一位保险法规合规专家。请判断以下保险产品文档是否违反负面清单规定。

## 负面清单规定（共 {len(negative_docs)} 条）
{rules_text}

## 待审文档内容
{document_content}

## 输出要求
请以 JSON 格式输出所有违规项：
[
  {{"rule_id": 1, "is_violation": true, "reason": "<违规原因>", "source_excerpt": "<文档中违规原文>", "suggestion": "<修改建议>"}},
  {{"rule_id": 2, "is_violation": false}},
  ...
]

注意：
1. 仅输出 is_violation 为 true 的项（或省略 false 项）
2. rule_id 对应上面规则的编号
3. 仅输出 JSON，不要附加其他文字
"""

    try:
        llm = get_qa_llm()
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response).strip()

        # 解析 JSON
        items = _parse_violation_response(answer, negative_docs)
        return items, True
    except Exception as e:
        logger.error(f"Negative list check failed: {e}")
        return [], False


def _parse_violation_response(answer: str, negative_docs: List[Dict]) -> List[Dict]:
    """解析 LLM 返回的违规项列表"""
    try:
        # 移除 code fence
        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0]
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0]

        json_start = answer.find("[")
        json_end = answer.rfind("]") + 1
        if json_start < 0 or json_end <= json_start:
            return []

        violations = json.loads(answer[json_start:json_end])
        items = []
        for v in violations:
            if not v.get("is_violation", False):
                continue
            rule_id = v.get("rule_id", 0) - 1
            if 0 <= rule_id < len(negative_docs):
                doc = negative_docs[rule_id]
                items.append({
                    "clause_number": "",
                    "param": f"负面清单检查: {doc.get('law_name', '')} {doc.get('article_number', '')}",
                    "value": v.get("source_excerpt", "")[:100],
                    "requirement": f"违反负面清单 {doc.get('law_name', '')} {doc.get('article_number', '')}: {doc.get('content', '')[:200]}",
                    "status": "non_compliant",
                    "source": "负面清单",
                    "source_excerpt": doc.get("content", "")[:300],
                    "suggestion": v.get("suggestion", "请修改相关表述"),
                })
        return items
    except Exception as e:
        logger.warning(f"Failed to parse violation response: {e}")
        return []
```

- **同步更新**: 删除原有的 `_check_violation` 函数（已不需要）

---

#### Step 1.3: 对齐 `product_types.py` 枚举值为简称

- **文件**: `scripts/lib/common/product_types.py:12-23`
- **问题**: `ProductCategory.value` 返回全称（"人寿保险"），与 `VALID_CATEGORIES`（"寿险"）不匹配
- **变更**:

```python
# 当前
class ProductCategory(Enum):
    LIFE = "人寿保险"
    HEALTH = "健康保险"
    ACCIDENT = "意外保险"
    ANNUITY = "年金保险"
    MOTOR = "机动车保险"
    PROPERTY = "财产保险"
    PENSION = "养老保险"
    EDUCATION = "教育保险"
    TRAVEL = "旅游保险"
    OTHER = "其他"

# 修改后
class ProductCategory(Enum):
    LIFE = "寿险"
    HEALTH = "健康险"
    ACCIDENT = "意外险"
    ANNUITY = "年金险"
    MOTOR = "财产险"
    PROPERTY = "财产险"
    PENSION = "年金险"
    EDUCATION = "年金险"
    TRAVEL = "意外险"
    OTHER = "其他"
```

---

#### Step 1.4: 更新路由层消费 `check_negative_list` 新签名

- **文件**: `scripts/api/routers/compliance.py:53-65`
- **变更**:

```python
# 当前
negative_items = check_negative_list(req.document_content)
# ...
result["negative_list_checked"] = True

# 修改后
negative_items, negative_list_checked = check_negative_list(req.document_content)
# ...
result["negative_list_checked"] = negative_list_checked
```

---

#### Step 1.5: 更新 `test_negative_list.py` 适配新签名

- **文件**: `scripts/tests/compliance/test_negative_list.py`
- **变更**: 适配 `(items, checked)` 返回值，删除逐条检查相关测试

```python
def test_check_negative_list_no_engine():
    with patch('lib.compliance.checker.get_engine', return_value=None):
        items, checked = check_negative_list("测试内容")
        assert items == []
        assert checked is False

def test_check_negative_list_batch_violation():
    """测试批量检查发现违规"""
    mock_docs = [
        {"law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
        {"law_name": "负面清单", "article_number": "第二条", "content": "禁止夸大收益"},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '[{"rule_id": 1, "is_violation": true, "reason": "文档中出现保证续保", "source_excerpt": "本产品保证续保", "suggestion": "删除该表述"}]'

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
            items, checked = check_negative_list("本产品保证续保，保险期间1年")
            assert checked is True
            assert len(items) == 1
            assert items[0]["status"] == "non_compliant"
```

---

#### Step 1.6: 标注 `models.py` 中 `ProductCategory` 与 `product_types.py` 的关系

- **文件**: `scripts/lib/common/models.py:76`
- **变更**: 添加注释

```python
class ProductCategory(str, Enum):
    """产品类别（audit/product 模块使用，英文值用于数据库存储）

    注意: compliance 模块使用 product_types.ProductCategory（中文简称值），
    两者枚举名相同但用途不同，勿混淆。
    """
```

---

### Phase 2: 测试覆盖补齐 (P1)

→ 回溯 spec.md: US6 (测试覆盖和可靠性)

---

#### Step 2.1: 重写 `test_clause_level.py`

- **文件**: `scripts/tests/compliance/test_clause_level.py`
- **问题**: 引用已删除的 `_detect_missing_clauses` 和 `_run_compliance_check`
- **变更**: 删除旧测试，改为测试 `run_compliance_check` JSON 解析

```python
"""合规检查 JSON 解析测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.compliance.checker import run_compliance_check


def test_run_compliance_check_normal_json():
    """测试正常 JSON 解析"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"summary": {"compliant": 2, "non_compliant": 1, "attention": 0}, "items": []}'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 2


def test_run_compliance_check_with_thinking_tag():
    """测试 thinking tag 剥离"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '<tool_call>分析...厄 {"summary": {"compliant": 1, "non_compliant": 0, "attention": 0}, "items": []}'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 1


def test_run_compliance_check_with_code_fence():
    """测试 markdown code fence 剥离"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '```json\n{"summary": {"compliant": 1, "non_compliant": 0, "attention": 0}, "items": []}\n```'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 1


def test_run_compliance_check_truncated_json():
    """测试截断 JSON 修复"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"summary": {"compliant": 1}, "items": [{"param": "test"'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert "summary" in result


def test_run_compliance_check_no_json():
    """测试非 JSON 响应"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '这是一个保险条款文档，符合法规。'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert "summary" in result


def test_run_compliance_check_llm_error():
    """测试 LLM 调用失败"""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("LLM unavailable")
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert "error" in result
```

---

#### Step 2.2: 新增 `test_checker.py`

- **文件**: `scripts/tests/compliance/test_checker.py` (新建)
- **覆盖**: `identify_category`、`build_enhanced_context`

```python
"""合规检查核心逻辑测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.compliance.checker import identify_category, build_enhanced_context


class TestIdentifyCategory:
    def test_keyword_match_health(self):
        """关键词匹配: 健康险"""
        category, confidence, method = identify_category("", "健康保险产品")
        assert category == "健康险"
        assert confidence == 0.7
        assert method == "keyword"

    def test_keyword_match_life(self):
        """关键词匹配: 寿险"""
        category, confidence, method = identify_category("", "终身寿险")
        assert category == "寿险"
        assert confidence == 0.7
        assert method == "keyword"

    def test_llm_fallback(self):
        """LLM fallback 识别"""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "医疗险"
        with patch('lib.compliance.checker.classify_product') as mock_classify:
            from lib.common.product_types import ProductCategory
            mock_classify.return_value = ProductCategory.OTHER
            with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
                category, confidence, method = identify_category("某产品", "模糊描述")
                assert category == "医疗险"
                assert confidence == 0.85
                assert method == "llm"

    def test_both_fail(self):
        """双阶段都失败"""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("fail")
        with patch('lib.compliance.checker.classify_product') as mock_classify:
            from lib.common.product_types import ProductCategory
            mock_classify.return_value = ProductCategory.OTHER
            with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
                category, confidence, method = identify_category("某产品", "模糊描述")
                assert category is None
                assert confidence == 0.0
                assert method == "unknown"


class TestBuildEnhancedContext:
    def test_engine_not_initialized(self):
        """RAG 引擎未初始化"""
        with patch('lib.compliance.checker.get_engine', return_value=None):
            context, sources = build_enhanced_context("健康险")
            assert context == ""
            assert sources == {"险种专属": [], "通用法规": []}

    def test_category_none(self):
        """category 为 None 时只加载通用法规"""
        mock_engine = MagicMock()
        mock_engine.search_by_metadata.return_value = [{"law_name": "保险法", "article_number": "第一条", "content": "测试", "doc_number": "", "issuing_authority": "", "effective_date": ""}]
        with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
            context, sources = build_enhanced_context(None)
            assert "通用法规" in sources

    def test_full_regulations_loaded(self):
        """验证全量法规加载"""
        mock_engine = MagicMock()
        # 模拟 search_by_metadata 返回完整条款列表
        mock_engine.search_by_metadata.return_value = [
            {"law_name": "健康保险管理办法", "article_number": f"第{i}条", "content": f"内容{i}", "doc_number": "", "issuing_authority": "", "effective_date": ""}
            for i in range(1, 51)  # 50 条款
        ]
        with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
            context, sources = build_enhanced_context("健康险")
            # 验证 context 包含所有条款
            assert "第1条" in context
            assert "第50条" in context
```

---

### Phase 3: 代码质量改进 (P2)

→ 回溯 spec.md: US3 (负面清单检查可靠性)

---

#### Step 3.1: `identify_category` 返回 NamedTuple

- **文件**: `scripts/lib/compliance/checker.py:158`
- **变更**:

```python
from typing import NamedTuple, Optional

class CategoryResult(NamedTuple):
    category: Optional[str]
    confidence: float
    method: str

def identify_category(document_content: str, product_name: str = "") -> CategoryResult:
    category_enum = classify_product(product_name, document_content[:1000])
    if category_enum != ProductCategory.OTHER:
        return CategoryResult(category_enum.value, 0.7, "keyword")
    # ... LLM 逻辑 ...
    return CategoryResult(None, 0.0, "unknown")
```

- **消费方**: NamedTuple 与 tuple 兼容，无需修改

---

#### Step 3.2: 简化 JSON fallback 层级 5

- **文件**: `scripts/lib/compliance/checker.py:297-305`
- **变更**: 移除 regex 提取，改为返回空结果 + error 标记

```python
# 修改后
logger.warning(f"JSON repair failed, returning empty result")
parsed = {
    "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
    "items": [],
    "error": "json_parse_failed",
    "raw_answer": answer[:1000],
}
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | — | — |

---

## Appendix

### 执行顺序建议

```
Phase 1 (Step 1.1→1.2→1.3→1.4→1.5→1.6)  — 核心修复，必须按顺序
    ↓
Phase 2 (Step 2.1, 2.2 可并行)             — 测试补齐
    ↓
Phase 3 (Step 3.1, 3.2 可并行)             — 代码质量改进
```

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 主链路质量 | RAG 未初始化不抛 AttributeError；negative_list_checked 反映真实状态 | `test_check_negative_list_no_engine` |
| US2 法规检索有效性 | 完整文档 + 全量法规被检查；无不必要的截断 | `test_full_regulations_loaded` |
| US3 负面清单可靠性 | 批量检查（1 次 LLM）；checked 标记正确 | `test_check_negative_list_batch_*` |
| US4 险种识别准确性 | 关键词匹配返回简称 | `test_keyword_match_*` |
| US5 API 契约一致性 | Schema 与 TS 类型字段对应 | 人工验证 |
| US6 测试覆盖 | pytest 全部通过 | `test_checker.py`, `test_clause_level.py` |

### 关键变更摘要

| 变更 | 当前 | 修改后 | 影响 |
|------|------|--------|------|
| 文档内容 | `[:3000]` 截断 | 完整文档 | 检查覆盖全部条款 |
| 法规上下文 | `[:8000]` 截断 | 全量法规 | 法规覆盖率 8.9% → 100% |
| 负面清单检查 | N 次 LLM 调用 | 1 次批量调用 | 成本降低 N 倍，覆盖完整 |
| `check_negative_list` 返回 | `List[Dict]` | `Tuple[List, bool]` | 可区分"无违规"和"未检查" |
| `ProductCategory.value` | 全称 | 简称 | 险种专属法规检索正常工作 |
