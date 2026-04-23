# Implementation Plan: 保险产品合规检查

**Branch**: `022-compliance-check` | **Date**: 2026-04-23 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

基于 spec.md 和 research.md 的分析，本 feature 的核心目标是完善合规检查功能的用户体验和测试验证。

**主要需求**（来自 spec.md）：
- FR-001: 分步操作 — **已实现**
- FR-002/FR-002a/FR-002b: 条款级结构化检查结果 + 遗漏检测 — **待开发**
- FR-003: 报告管理 — **暂缓**（先结构化展示审核结果）
- FR-006: 法规无结果处理 — **需增强**
- FR-007: 测试验证流程 — **待开发**

**技术方案**：
- 修改 Prompt 让 LLM 按条款编号输出
- 修改数据结构增加 `clause_number` 字段
- 前端按条款编号树状展示
- 对比文档解析的条款列表 vs 检查结果，检测遗漏项

## Technical Context

**Language/Version**: Python 3.11+, TypeScript 5.x
**Primary Dependencies**:
- 现有: fastapi, python-docx, jinja2, sqlite3, react, antd

**Storage**: SQLite (`compliance_reports` 表)
**Testing**: pytest (后端), vitest (前端单元), playwright (E2E)
**Performance Goals**: 合规检查 < 30s
**Constraints**: 复用现有 RAG 引擎和文档解析模块

## Constitution Check

- [x] **Library-First**: 复用 RAGEngine、parse_product_document、CompliancePage 组件
- [x] **测试优先**: 每个功能模块规划了单元测试和集成测试
- [x] **简单优先**: 先结构化展示，暂不开发导出功能
- [x] **显式优于隐式**: 所有 API 参数和数据结构明确定义
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md 的 User Story
- [x] **独立可测试**: 每个 User Story 可独立测试和交付

## Project Structure

```text
scripts/
├── api/
│   ├── routers/compliance.py      # 修改：Prompt + 数据结构 + 遗漏检测
│   └── schemas/compliance.py      # 修改：添加 clause_number 字段
├── web/src/
│   └── pages/CompliancePage.tsx   # 修改：条款级树状展示
└── tests/
    └── compliance/                # 新增：测试验证流程
        ├── test_compliance.py
        └── fixtures/
```

---

## Implementation Phases

### Phase 1: 条款级检查结果改造 (FR-002a)

#### 需求回溯

→ 对应 spec.md User Story 2: 合规检查报告生成

> 检查结果按条款编号树状组织，每个检查项包含 `clause_number` 字段

#### 实现步骤

**Step 1.1: 修改 Prompt 要求按条款编号输出**

文件: `scripts/api/routers/compliance.py`

```python
_COMPLIANCE_PROMPT_DOCUMENT_V2 = """你是一位保险法规合规专家。请审查以下保险条款文档，检查是否符合相关法规要求。

## 条款文档内容
{document_content}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "clause_number": "<条款编号，如 1.2.3>",
            "param": "<检查项名称，如 '等待期'>",
            "value": "<产品实际值>",
            "requirement": "<法规要求，引用法规原文关键句>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源，格式：[来源X]>",
            "source_excerpt": "<从来源法规中直接摘录的原文片段>",
            "suggestion": "<修改建议，仅不合规时填写>"
        }}
    ],
    "extracted_params": {{
        "<参数名>": "<提取值>"
    }}
}}

注意：
1. **clause_number 必须填写**：从条款文本中识别条款编号（如 "第一条" → "1"，"1.2.3" → "1.2.3"）
2. 检查项按条款组织：同一条款下的多个参数共享相同的 clause_number
3. 先提取条款中的关键参数，再逐项检查合规性
4. source 必须使用 [来源X] 格式引用法规条款
5. source_excerpt 必须是从对应来源中直接摘录的原文
6. 仅输出 JSON，不要附加其他文字
"""
```

**Step 1.2: 更新 Schema 添加 clause_number**

文件: `scripts/api/schemas/compliance.py`

```python
class ComplianceItem(BaseModel):
    clause_number: str = ""  # 条款编号
    param: str
    value: Optional[object] = None
    requirement: str = ""
    status: str = Field(..., pattern="^(compliant|non_compliant|attention)$")
    source: Optional[str] = None
    source_excerpt: Optional[str] = None
    suggestion: Optional[str] = None
```

**Step 1.3: 更新调用处使用新 Prompt**

文件: `scripts/api/routers/compliance.py`

```python
@router.post("/check/document", response_model=ComplianceReportOut)
async def check_document(req: DocumentCheckRequest):
    engine = get_rag_engine()

    # 提取关键参数用于检索
    try:
        from lib.llm.factory import LLMClientFactory
        llm = LLMClientFactory.create_qa_llm()
        extract_prompt = f"请从以下保险条款中提取关键参数（险种类型、等待期、免赔额等），以 JSON 格式输出：\n\n{req.document_content[:3000]}"
        extracted = llm.chat([{"role": "user", "content": extract_prompt}])
    except Exception:
        extracted = ""

    query = f"保险合规要求 {extracted[:200]}"
    search_results = engine.search(query, top_k=10)

    context = _build_context(search_results)

    # 使用新 Prompt
    prompt = _COMPLIANCE_PROMPT_DOCUMENT_V2.format(
        document_content=req.document_content[:5000],
        context=context,
    )

    result = await asyncio.to_thread(_run_compliance_check, engine, prompt, search_results)
    # ... 其余逻辑不变
```

#### 测试

```python
# scripts/tests/compliance/test_clause_level.py
def test_clause_number_in_output():
    """测试检查结果包含条款编号"""
    result = {
        "items": [
            {"clause_number": "1.1", "param": "等待期", "status": "compliant"},
            {"clause_number": "1.2", "param": "免赔额", "status": "compliant"},
            {"clause_number": "2.1", "param": "保险期间", "status": "non_compliant"},
        ]
    }
    # 验证所有 item 都有 clause_number
    for item in result["items"]:
        assert item["clause_number"], f"item {item['param']} missing clause_number"
```

---

### Phase 2: 遗漏检测 (FR-002b)

#### 需求回溯

→ 对应 spec.md User Story 2: 合规检查报告生成

> 检测文档中存在但未被检查覆盖的条款，标注为 attention

#### 实现步骤

**Step 2.1: 实现遗漏检测逻辑**

文件: `scripts/api/routers/compliance.py`

```python
def _detect_missing_clauses(
    parsed_doc: Dict,      # 文档解析结果
    check_result: Dict,    # 检查结果
) -> List[Dict]:
    """检测文档中存在但未被检查覆盖的条款

    Args:
        parsed_doc: 从 parse_file 返回的解析结果，包含 clauses 列表
        check_result: 检查结果，包含 items 列表

    Returns:
        遗漏项列表，每个遗漏项包含 clause_number 和 title
    """
    # 从解析结果提取所有条款编号
    parsed_numbers = set()
    for clause in parsed_doc.get("clauses", []):
        number = clause.get("number", "")
        if number:
            parsed_numbers.add(number)

    # 从检查结果提取已覆盖的条款编号
    checked_numbers = set()
    for item in check_result.get("items", []):
        clause_num = item.get("clause_number", "")
        if clause_num:
            checked_numbers.add(clause_num)

    # 计算遗漏
    missing_numbers = parsed_numbers - checked_numbers

    # 构建遗漏项
    missing_items = []
    for clause in parsed_doc.get("clauses", []):
        if clause.get("number") in missing_numbers:
            missing_items.append({
                "clause_number": clause.get("number", ""),
                "param": f"条款 {clause.get('number', '')} {clause.get('title', '')}",
                "value": "-",
                "requirement": "该条款未被检查覆盖",
                "status": "attention",
                "source": None,
                "source_excerpt": None,
                "suggestion": "请补充检查该条款的合规性",
            })

    return missing_items


@router.post("/check/document", response_model=ComplianceReportOut)
async def check_document(req: DocumentCheckRequest):
    # ... 前面的检查逻辑不变

    # 如果提供了 parse_id，执行遗漏检测
    missing_items = []
    if req.parse_id:
        from api.database import get_parsed_document
        parsed_doc = get_parsed_document(req.parse_id)
        if parsed_doc:
            missing_items = _detect_missing_clauses(parsed_doc, result)

    # 将遗漏项添加到结果中
    if missing_items:
        result["items"].extend(missing_items)
        result["summary"]["attention"] += len(missing_items)
        result["missing_clauses"] = [m["clause_number"] for m in missing_items]

    # ... 保存并返回
```

**Step 2.2: 更新请求 Schema 支持传入 parse_id**

文件: `scripts/api/schemas/compliance.py`

```python
class DocumentCheckRequest(BaseModel):
    document_content: str = Field(..., min_length=1, description="条款文档内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")
    parse_id: Optional[str] = Field(None, description="解析结果ID，用于遗漏检测")
```

**Step 2.3: 前端传入 parse_id**

文件: `scripts/web/src/pages/CompliancePage.tsx`

```typescript
const handleConfirmReview = async () => {
  if (!parsedDocument) return;
  setLoading(true);
  try {
    const report = await complianceApi.checkDocument({
      document_content: parsedDocument.combined_text,
      product_name: productName || parsedDocument.file_name || undefined,
      parse_id: parsedDocument.parse_id,  // 传入解析ID
    });
    setCheckingResult(report);
    // ...
  }
};
```

#### 测试

```python
def test_detect_missing_clauses():
    """测试遗漏检测"""
    parsed_doc = {
        "clauses": [
            {"number": "1", "title": "保险责任"},
            {"number": "2", "title": "责任免除"},
            {"number": "3", "title": "保费"},
        ]
    }
    check_result = {
        "items": [
            {"clause_number": "1", "param": "等待期", "status": "compliant"},
            {"clause_number": "2", "param": "免责条款", "status": "compliant"},
        ]
    }

    missing = _detect_missing_clauses(parsed_doc, check_result)
    assert len(missing) == 1
    assert missing[0]["clause_number"] == "3"
    assert missing[0]["status"] == "attention"
```

---

### Phase 3: 前端条款级树状展示 (FR-002a)

#### 需求回溯

→ 对应 spec.md User Story 2: 合规检查报告生成

> 检查结果按条款编号树状组织展示

#### 实现步骤

**Step 3.1: 按条款编号分组展示**

文件: `scripts/web/src/pages/CompliancePage.tsx`

```typescript
// 按条款编号分组检查结果
const groupedByClause = useMemo(() => {
  if (!result?.items) return {};
  const groups: Record<string, ComplianceItem[]> = {};

  // 先按 clause_number 分组
  for (const item of result.items) {
    const clauseNum = item.clause_number || '其他';
    if (!groups[clauseNum]) groups[clauseNum] = [];
    groups[clauseNum].push(item);
  }

  // 按条款编号排序（1, 1.1, 1.2, 2, 2.1...）
  const sortedKeys = Object.keys(groups).sort((a, b) => {
    const aParts = a.split('.').map(Number);
    const bParts = b.split('.').map(Number);
    for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
      const aVal = aParts[i] || 0;
      const bVal = bParts[i] || 0;
      if (aVal !== bVal) return aVal - bVal;
    }
    return 0;
  });

  const sorted: Record<string, ComplianceItem[]> = {};
  for (const key of sortedKeys) {
    sorted[key] = groups[key];
  }
  return sorted;
}, [result?.items]);

// 计算每个条款的状态汇总
const getClauseSummary = (items: ComplianceItem[]) => {
  const compliant = items.filter(i => i.status === 'compliant').length;
  const nonCompliant = items.filter(i => i.status === 'non_compliant').length;
  const attention = items.filter(i => i.status === 'attention').length;
  return { compliant, nonCompliant, attention };
};
```

**Step 3.2: 使用 Collapse 树状展示**

```tsx
// 检查结果展示区域
<Collapse
  defaultActiveKey={Object.keys(groupedByClause)}
  items={Object.entries(groupedByClause).map(([clauseNum, items]) => {
    const summary = getClauseSummary(items);
    const hasIssue = summary.nonCompliant > 0 || summary.attention > 0;
    return {
      key: clauseNum,
      label: (
        <Space>
          <Text strong>条款 {clauseNum}</Text>
          <Text type="secondary">({items.length} 项)</Text>
          {summary.nonCompliant > 0 && (
            <Tag color="error">{summary.nonCompliant} 不合规</Tag>
          )}
          {summary.attention > 0 && (
            <Tag color="warning">{summary.attention} 需关注</Tag>
          )}
          {summary.nonCompliant === 0 && summary.attention === 0 && (
            <Tag color="success">全部合规</Tag>
          )}
        </Space>
      ),
      children: (
        <Table
          dataSource={items}
          columns={[
            { title: '检查项', dataIndex: 'param', key: 'param', width: 120 },
            { title: '产品值', dataIndex: 'value', key: 'value', width: 120 },
            { title: '法规要求', dataIndex: 'requirement', key: 'requirement', ellipsis: true },
            {
              title: '状态', dataIndex: 'status', key: 'status', width: 100,
              render: (s: string) => {
                const cfg = STATUS_CONFIG[s];
                return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>;
              },
            },
            {
              title: '法规来源', dataIndex: 'source', key: 'source', width: 150,
              render: (text: string, record: ComplianceItem) => (
                text ? (
                  <Tag color="blue" style={{ cursor: 'pointer' }}
                       onClick={() => handleSourceClick(text, record.source_excerpt)}>
                    {text}
                  </Tag>
                ) : '-'
              ),
            },
            { title: '建议', dataIndex: 'suggestion', key: 'suggestion', ellipsis: true },
          ]}
          rowKey={(r) => `${r.clause_number}-${r.param}`}
          size="small"
          pagination={false}
        />
      ),
    };
  })}
/>
```

**Step 3.3: 显示遗漏项警告**

```tsx
{result.missing_clauses && result.missing_clauses.length > 0 && (
  <Alert
    type="warning"
    showIcon
    style={{ marginBottom: 16 }}
    message="遗漏条款提示"
    description={
      <span>
        以下条款未被检查覆盖：
        {result.missing_clauses.map(c => <Tag key={c}>{c}</Tag>)}
      </span>
    }
  />
)}
```

#### 测试

```typescript
describe('ClauseLevelDisplay', () => {
  it('should group items by clause_number', () => {
    const items = [
      { clause_number: '1.1', param: '等待期', status: 'compliant' },
      { clause_number: '1.2', param: '免赔额', status: 'compliant' },
      { clause_number: '2.1', param: '保险期间', status: 'non_compliant' },
    ];
    // 验证分组结果: { '1.1': [...], '1.2': [...], '2.1': [...] }
  });

  it('should sort clauses correctly', () => {
    // 验证排序: 1 < 1.1 < 1.2 < 2 < 2.1
  });

  it('should show missing clauses warning', () => {
    // 验证遗漏项警告显示
  });
});
```

---

### Phase 4: 法规无结果处理 (FR-006)

#### 需求回溯

→ 对应 spec.md User Story 2

> 法规检索无结果时标注检查项为 attention 并提示用户

#### 实现步骤

**Step 4.1: 修改 `_run_compliance_check` 添加无结果处理**

文件: `scripts/api/routers/compliance.py`

```python
def _run_compliance_check(engine, prompt: str, search_results: list) -> Dict:
    """执行合规检查，处理法规无结果情况"""
    if not search_results:
        return {
            "summary": {"compliant": 0, "non_compliant": 0, "attention": 1},
            "items": [{
                "clause_number": "",
                "param": "法规检索",
                "value": "-",
                "requirement": "未找到相关法规",
                "status": "attention",
                "source": None,
                "source_excerpt": None,
                "suggestion": "请检查知识库是否包含相关法规",
            }],
            "sources": [],
            "citations": [],
            "warning": "法规检索无结果，无法进行合规检查",
        }
    # ... 其余逻辑不变
```

---

### Phase 5: 测试验证流程 (FR-007)

#### 需求回溯

→ 对应 spec.md User Story 5: 测试验证流程

#### 实现步骤

**Step 5.1: 创建测试验证脚本**

文件: `scripts/tests/compliance/validate_flow.py`

```python
"""合规检查测试验证流程"""

import json
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

@dataclass
class ValidationSample:
    id: str
    document_path: str
    human_result: Dict[str, Any]

@dataclass
class ClauseMatch:
    clause_number: str
    auto_status: str
    human_status: str
    match: bool

@dataclass
class ValidationResult:
    sample_id: str
    clause_accuracy: float
    status_accuracy: float
    mismatches: List[ClauseMatch]

@dataclass
class ValidationReport:
    total_samples: int
    avg_clause_accuracy: float
    avg_status_accuracy: float
    results: List[ValidationResult]


def compare_clause_level(auto_result: Dict, human_result: Dict) -> ValidationResult:
    """条款级对比：按条款编号整体判定"""
    auto_items = {item["clause_number"]: item for item in auto_result.get("items", [])}
    human_items = {item["clause_number"]: item for item in human_result.get("items", [])}

    all_clauses = set(auto_items.keys()) | set(human_items.keys())
    mismatches = []
    correct = 0

    for clause_num in all_clauses:
        auto_item = auto_items.get(clause_num, {})
        human_item = human_items.get(clause_num, {})

        auto_status = auto_item.get("status", "missing")
        human_status = human_item.get("status", "missing")

        if auto_status == human_status:
            correct += 1
            mismatches.append(ClauseMatch(
                clause_number=clause_num,
                auto_status=auto_status,
                human_status=human_status,
                match=True,
            ))
        else:
            mismatches.append(ClauseMatch(
                clause_number=clause_num,
                auto_status=auto_status,
                human_status=human_status,
                match=False,
            ))

    accuracy = correct / len(all_clauses) if all_clauses else 0.0

    return ValidationResult(
        sample_id="",
        clause_accuracy=accuracy,
        status_accuracy=accuracy,
        mismatches=mismatches,
    )


def main():
    parser = argparse.ArgumentParser(description="合规检查测试验证")
    parser.add_argument("--fixtures", type=str, default="scripts/tests/fixtures/compliance")
    parser.add_argument("--output", type=str, default="validation_report.json")
    args = parser.parse_args()

    # ... 执行验证并输出报告
```

**Step 5.2: 创建测试数据**

文件: `scripts/tests/fixtures/compliance/sample_1.json`

```json
{
  "summary": {"compliant": 2, "non_compliant": 1, "attention": 0},
  "items": [
    {
      "clause_number": "1.1",
      "param": "等待期",
      "value": "90天",
      "status": "compliant",
      "source": "[来源1]"
    },
    {
      "clause_number": "1.2",
      "param": "免赔额",
      "value": "0元",
      "status": "compliant",
      "source": "[来源2]"
    },
    {
      "clause_number": "2.1",
      "param": "保险期间",
      "value": "1年",
      "status": "non_compliant",
      "source": "[来源3]",
      "suggestion": "建议明确产品为短期健康保险"
    }
  ]
}
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

---

## Appendix

### 执行顺序建议

```
Phase 1 (条款级数据结构) → Phase 2 (遗漏检测) → Phase 3 (前端展示) → Phase 4 (无结果处理) → Phase 5 (测试验证)
```

Phase 1-3 有依赖关系，Phase 4 可并行，Phase 5 最后。

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 文档解析确认 | 用户可在解析后确认再检查 | E2E 测试 |
| US2 合规检查报告 | 条款级结构化展示 + 遗漏检测 | `test_clause_level.py` |
| US3 报告管理 | 暂缓 | - |
| US4 产品自查 | 与 US2 一致 | 同 US2 |
| US5 测试验证 | 条款级对比验证流程 | `validate_flow.py` |
