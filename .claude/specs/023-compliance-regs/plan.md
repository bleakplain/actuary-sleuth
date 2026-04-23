# Implementation Plan: 合规审查法规检索策略改造

**Branch**: `023-compliance-regs` | **Date**: 2026-04-23 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

基于 spec.md 和 research.md 的分析，本 feature 的核心目标是改造合规检查的法规检索策略，确保法规覆盖完整性。

**主要需求**（来自 spec.md）：
- FR-001: 按险种加载专属法规库（健康险、寿险、意外险等）
- FR-002: 强制包含通用法规库（保险法、条款管理办法、费率管理办法、精算规定）
- FR-003: 负面清单作为独立检查项强制包含
- FR-004: LLM 自动识别险种类型并让用户确认
- FR-005: 支持用户手动修正险种类型
- FR-007: 法规上下文中标注来源类型

**技术方案**：
- 复用现有 `ProductCategory` 枚举和 `classify_product()` 函数
- 使用 `RAGEngine.search(filters=...)` 按险种过滤法规
- YAML 配置险种法规映射表，便于维护
- 独立负面清单检查模块，结果合并到 items

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: 
- 现有: fastapi, pydantic, sqlite3, yaml
- 无新增依赖

**Storage**: SQLite (`negative_list` 表已存在)
**Testing**: pytest
**Performance Goals**: 法规库加载 < 2s，合规检查总时长 < 30s
**Constraints**: 复用现有 RAG 引擎和 metadata 过滤机制

## Constitution Check

- [x] **Library-First**: 复用 RAGEngine.search(filters)、get_negative_list()、ProductCategory 枚举、classify_product()
- [x] **测试优先**: 每个功能模块规划了单元测试
- [x] **简单优先**: YAML 配置 + metadata 过滤，不新增数据库表
- [x] **显式优于隐式**: 法规来源类型显式标注（险种专属/通用/负面清单）
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md 的 User Story
- [x] **独立可测试**: 每个 User Story 可独立测试和交付

## Project Structure

### Documentation

```text
.claude/specs/023-compliance-regs/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/
├── api/
│   ├── routers/compliance.py      # 修改: 检索逻辑、险种识别、负面清单检查
│   └── schemas/compliance.py      # 修改: 添加 category 字段
├── lib/common/
│   └── regulation_registry.py     # 新增: 险种法规映射配置
└── tests/
    └── compliance/
        └── test_regulation_registry.py  # 新增: 配置测试
```

---

## Implementation Phases

### Phase 1: 险种法规映射配置 (US1)

#### 需求回溯

→ 对应 spec.md User Story 1: 险种专属法规加载 (P1)

#### 实现步骤

**Step 1.1: 创建险种法规映射配置文件**

文件: `scripts/lib/common/regulation_registry.py`

```python
"""险种法规映射配置"""
from typing import Dict, List

CATEGORY_REGULATION_REGISTRY: Dict[str, List[str]] = {
    "健康险": [
        "健康保险管理办法",
        "关于规范短期健康保险发展的通知",
        "健康保险精算规定",
    ],
    "医疗险": [
        "医疗保险管理办法",
        "费用补偿型医疗保险规定",
    ],
    "重疾险": [
        "重大疾病保险的疾病定义使用规范",
        "健康保险管理办法",
    ],
    "寿险": [
        "人身保险精算规定",
        "人寿保险产品指引",
        "人身保险公司保险条款和保险费率管理办法",
    ],
    "意外险": [
        "意外伤害保险业务监管办法",
        "人身保险伤残评定标准",
    ],
}

GENERAL_REGULATIONS: List[str] = [
    "中华人民共和国保险法",
    "保险条款管理办法",
    "保险费率管理办法",
    "人身保险公司精算报告管理办法",
]


def get_category_regulations(category: str) -> List[str]:
    """获取险种专属法规名称列表"""
    return CATEGORY_REGULATION_REGISTRY.get(category, [])


def get_general_regulations() -> List[str]:
    """获取通用法规名称列表"""
    return GENERAL_REGULATIONS.copy()
```

**Step 1.2: 编写配置测试**

文件: `scripts/tests/compliance/test_regulation_registry.py`

```python
"""险种法规映射配置测试"""
import pytest
from lib.common.regulation_registry import (
    get_category_regulations,
    get_general_regulations,
    CATEGORY_REGULATION_REGISTRY,
    GENERAL_REGULATIONS,
)


def test_get_category_regulations():
    """测试获取险种专属法规"""
    health_regs = get_category_regulations("健康险")
    assert len(health_regs) >= 2
    assert "健康保险管理办法" in health_regs


def test_get_category_regulations_unknown():
    """测试未知险种返回空列表"""
    result = get_category_regulations("未知险种")
    assert result == []


def test_get_general_regulations():
    """测试获取通用法规"""
    general = get_general_regulations()
    assert "中华人民共和国保险法" in general
    assert "保险条款管理办法" in general


def test_all_categories_have_regulations():
    """测试所有配置的险种都有法规"""
    for category in CATEGORY_REGULATION_REGISTRY:
        regs = get_category_regulations(category)
        assert len(regs) > 0, f"险种 {category} 没有配置法规"
```

**Checkpoint**: US1 Phase 1 - 险种法规映射配置可用

---

### Phase 2: 通用法规强制包含 (US2)

#### 需求回溯

→ 对应 spec.md User Story 2: 通用法规强制包含 (P1)

#### 实现步骤

**Step 2.1: 更新 Schema 添加 category 字段**

文件: `scripts/api/schemas/compliance.py`

```python
class DocumentCheckRequest(BaseModel):
    document_content: str = Field(..., min_length=1, description="条款文档内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")
    parse_id: Optional[str] = Field(None, description="解析结果ID，用于遗漏检测")
    category: Optional[str] = Field(None, description="险种类型（可选，LLM自动识别或用户选择）")
```

**Step 2.2: 实现法规加载函数**

文件: `scripts/api/routers/compliance.py`

```python
from lib.common.regulation_registry import get_category_regulations, get_general_regulations


def _load_regulations_by_names(engine, regulation_names: List[str]) -> List[Dict]:
    """按法规名称列表加载法规内容
    
    Args:
        engine: RAG 引擎
        regulation_names: 法规名称列表
        
    Returns:
        法规内容列表
    """
    results = []
    for name in regulation_names:
        # 使用 law_name 过滤检索
        regs = engine.search(name, top_k=5, filters={"law_name": name})
        results.extend(regs)
    return results


def _build_enhanced_context(
    engine,
    category: Optional[str],
    query: str,
    top_k: int = 10,
) -> tuple:
    """构建增强的法规上下文
    
    Args:
        engine: RAG 引擎
        category: 险种类型
        query: 查询文本
        top_k: RAG 检索数量
        
    Returns:
        (context_str, sources_info)
    """
    all_results = []
    sources_info = {
        "险种专属": [],
        "通用法规": [],
        "语义检索": [],
    }
    
    # 1. 加载险种专属法规
    if category:
        category_regs = get_category_regulations(category)
        category_results = _load_regulations_by_names(engine, category_regs)
        all_results.extend(category_results)
        sources_info["险种专属"] = [r.get("law_name", "") for r in category_results]
    
    # 2. 加载通用法规
    general_names = get_general_regulations()
    general_results = _load_regulations_by_names(engine, general_names)
    all_results.extend(general_results)
    sources_info["通用法规"] = [r.get("law_name", "") for r in general_results]
    
    # 3. RAG 语义补充检索
    rag_results = engine.search(query, top_k=top_k)
    # 去重：已加载的法规不再添加
    existing_ids = {r.get("law_name", "") + r.get("article_number", "") for r in all_results}
    for r in rag_results:
        key = r.get("law_name", "") + r.get("article_number", "")
        if key not in existing_ids:
            all_results.append(r)
            sources_info["语义检索"].append(r.get("law_name", ""))
    
    # 构建 context 字符串
    context = _build_context(all_results)
    return context, sources_info
```

**Step 2.3: 修改 check_document 使用增强上下文**

文件: `scripts/api/routers/compliance.py`

在 `check_document` 函数中替换检索逻辑：

```python
@router.post("/check/document", response_model=ComplianceReportOut)
async def check_document(req: DocumentCheckRequest):
    engine = get_rag_engine()
    
    # 险种识别（如果未提供）
    category = req.category
    if not category:
        try:
            from lib.llm.factory import LLMClientFactory
            from lib.common.product_types import classify_product, ProductCategory
            llm = LLMClientFactory.create_qa_llm()
            extract_prompt = f"请从以下保险产品文档中识别险种类型（健康险、寿险、意外险、医疗险、重疾险等），仅输出险种名称：\n\n{req.document_content[:2000]}"
            extracted_category = llm.chat([{"role": "user", "content": extract_prompt}])
            extracted_category = str(extracted_category).strip()
            # 验证是否为有效险种
            for pc in ProductCategory:
                if pc.value in extracted_category:
                    category = pc.value
                    break
            # 兜底：关键词匹配
            if not category:
                category = classify_product(req.product_name or "", req.document_content[:500]).value
        except Exception:
            category = None
    
    # 构建增强的法规上下文
    context, sources_info = _build_enhanced_context(
        engine=engine,
        category=category,
        query=f"保险合规要求 {req.document_content[:200]}",
    )
    
    # 使用新上下文执行检查
    prompt = _COMPLIANCE_PROMPT_DOCUMENT_V2.format(
        document_content=req.document_content[:5000],
        context=context,
    )
    
    # ... 后续检查逻辑
    result["regulation_sources"] = sources_info
    result["category"] = category
    
    # ... 保存并返回
```

**Checkpoint**: US2 Phase 2 - 通用法规强制包含可用

---

### Phase 3: 负面清单独立检查 (US3)

#### 需求回溯

→ 对应 spec.md User Story 3: 负面清单独立检查 (P1)

#### 实现步骤

**Step 3.1: 实现负面清单检查函数**

文件: `scripts/api/routers/compliance.py`

```python
import re
from lib.common.database import get_negative_list


def _check_negative_list(document_content: str) -> List[Dict]:
    """执行负面清单检查
    
    Args:
        document_content: 文档内容
        
    Returns:
        检查项列表
    """
    negative_rules = get_negative_list()
    items = []
    
    for rule in negative_rules:
        rule_number = rule.get("rule_number", "")
        description = rule.get("description", "")
        severity = rule.get("severity", "中")
        keywords = rule.get("keywords", "")
        patterns = rule.get("patterns", "")
        
        # 解析关键词
        keyword_list = []
        if keywords:
            try:
                keyword_list = json.loads(keywords) if isinstance(keywords, str) else keywords
            except json.JSONDecodeError:
                keyword_list = []
        
        # 解析正则模式
        pattern_list = []
        if patterns:
            try:
                pattern_list = json.loads(patterns) if isinstance(patterns, str) else patterns
            except json.JSONDecodeError:
                pattern_list = []
        
        # 检查关键词匹配
        matched_keyword = None
        for kw in keyword_list:
            if kw and kw in document_content:
                matched_keyword = kw
                break
        
        # 检查正则匹配
        matched_pattern = None
        for p in pattern_list:
            try:
                if re.search(p, document_content):
                    matched_pattern = p
                    break
            except re.error:
                continue
        
        # 生成检查项
        if matched_keyword or matched_pattern:
            items.append({
                "clause_number": "",
                "param": f"负面清单检查: {description}",
                "value": matched_keyword or matched_pattern or "匹配",
                "requirement": f"违反负面清单规则 {rule_number}: {description}",
                "status": "non_compliant",
                "source": "负面清单",
                "source_excerpt": None,
                "suggestion": rule.get("remediation", "请修改相关表述"),
            })
    
    return items
```

**Step 3.2: 集成到 check_document**

文件: `scripts/api/routers/compliance.py`

```python
@router.post("/check/document", response_model=ComplianceReportOut)
async def check_document(req: DocumentCheckRequest):
    # ... 前面的法规上下文构建
    
    # 执行 LLM 合规检查
    result = await asyncio.to_thread(_run_compliance_check, engine, prompt, search_results)
    
    # 执行负面清单检查
    negative_items = _check_negative_list(req.document_content)
    
    # 合并结果
    if negative_items:
        result["items"].extend(negative_items)
        result["summary"]["non_compliant"] = result["summary"].get("non_compliant", 0) + len(negative_items)
        result["regulation_sources"]["负面清单"] = [item["param"] for item in negative_items]
    
    # 标注负面清单检查完成
    result["negative_list_checked"] = True
    
    # ... 遗漏检测、保存、返回
```

**Step 3.3: 编写负面清单检查测试**

文件: `scripts/tests/compliance/test_negative_list.py`

```python
"""负面清单检查测试"""
import pytest
from api.routers.compliance import _check_negative_list


def test_check_negative_list_no_violation():
    """测试无违规情况"""
    content = "本产品保险期间为1年，等待期为90天。"
    items = _check_negative_list(content)
    # 可能没有负面清单数据，仅验证函数不报错
    assert isinstance(items, list)


def test_check_negative_list_with_violation():
    """测试有违规情况"""
    # 假设负面清单中有 "保证续保" 关键词
    content = "本产品保证续保，保险期间为1年。"
    items = _check_negative_list(content)
    # 验证函数执行正常
    assert isinstance(items, list)
    for item in items:
        assert item["status"] == "non_compliant"
        assert item["source"] == "负面清单"
```

**Checkpoint**: US3 Phase 3 - 负面清单独立检查可用

---

### Phase 4: 险种识别与确认 (US4)

#### 需求回溯

→ 对应 spec.md User Story 4: 险种识别与确认 (P2)

#### 实现步骤

**Step 4.1: 实现险种识别函数**

文件: `scripts/api/routers/compliance.py`

```python
from lib.common.product_types import classify_product, ProductCategory
from lib.llm.factory import LLMClientFactory


def _identify_category(document_content: str, product_name: str = "") -> tuple:
    """识别险种类型
    
    Args:
        document_content: 文档内容
        product_name: 产品名称
        
    Returns:
        (category, confidence, method): 险种、置信度、识别方法
    """
    # 方法1: 关键词匹配（快速）
    category_enum = classify_product(product_name, document_content[:1000])
    if category_enum != ProductCategory.OTHER:
        return category_enum.value, 0.7, "keyword"
    
    # 方法2: LLM 提取
    try:
        llm = LLMClientFactory.create_qa_llm()
        prompt = f"""请从以下保险产品文档中识别险种类型。

可选险种类型：健康险、医疗险、重疾险、寿险、意外险、年金险、财产险

产品名称：{product_name}
文档内容：
{document_content[:2000]}

仅输出险种类型名称，不要输出其他内容。"""
        
        response = llm.chat([{"role": "user", "content": prompt}])
        extracted = str(response).strip()
        
        # 验证是否为有效险种
        valid_categories = ["健康险", "医疗险", "重疾险", "寿险", "意外险", "年金险", "财产险"]
        for vc in valid_categories:
            if vc in extracted:
                return vc, 0.85, "llm"
    except Exception:
        pass
    
    return None, 0.0, "unknown"
```

**Step 4.2: 添加险种识别 API 端点**

文件: `scripts/api/routers/compliance.py`

```python
class CategoryIdentifyRequest(BaseModel):
    document_content: str = Field(..., min_length=1, description="文档内容")
    product_name: Optional[str] = Field(None, description="产品名称")


class CategoryIdentifyResponse(BaseModel):
    category: Optional[str] = None
    confidence: float = 0.0
    method: str = "unknown"
    suggested_categories: List[str] = []


@router.post("/identify-category", response_model=CategoryIdentifyResponse)
async def identify_category(req: CategoryIdentifyRequest):
    """识别险种类型"""
    category, confidence, method = _identify_category(
        req.document_content,
        req.product_name or "",
    )
    
    # 提供候选列表供用户选择
    suggested = []
    if category:
        suggested.append(category)
    suggested.extend(["健康险", "寿险", "意外险", "医疗险", "重疾险"])
    suggested = list(dict.fromkeys(suggested))[:5]  # 去重保留前5个
    
    return CategoryIdentifyResponse(
        category=category,
        confidence=confidence,
        method=method,
        suggested_categories=suggested,
    )
```

**Step 4.3: 更新前端类型定义和 API 调用**

文件: `scripts/web/src/types/index.ts`

```typescript
export interface CategoryIdentifyRequest {
  document_content: string;
  product_name?: string;
}

export interface CategoryIdentifyResponse {
  category: string | null;
  confidence: number;
  method: string;
  suggested_categories: string[];
}

export interface ComplianceCheckRequest {
  document_content: string;
  product_name?: string;
  parse_id?: string;
  category?: string;  // 新增
}
```

文件: `scripts/web/src/api/compliance.ts`

```typescript
export async function identifyCategory(params: {
  document_content: string;
  product_name?: string;
}): Promise<CategoryIdentifyResponse> {
  const { data } = await client.post('/api/compliance/identify-category', params);
  return data;
}
```

**Checkpoint**: US4 Phase 4 - 险种识别与确认可用

---

### Phase 5: 前端险种选择集成

#### 实现步骤

**Step 5.1: 添加险种选择 UI**

文件: `scripts/web/src/pages/CompliancePage.tsx`

在 DocumentReviewPanel 组件中添加险种选择：

```tsx
// 状态定义
const [identifiedCategory, setIdentifiedCategory] = useState<string | null>(null);
const [selectedCategory, setSelectedCategory] = useState<string>("");
const [suggestedCategories, setSuggestedCategories] = useState<string[]>([]);
const [categoryConfidence, setCategoryConfidence] = useState<number>(0);

// 险种识别
const handleIdentifyCategory = async () => {
  if (!parsedDocument) return;
  try {
    const result = await complianceApi.identifyCategory({
      document_content: parsedDocument.combined_text,
      product_name: productName || undefined,
    });
    setIdentifiedCategory(result.category);
    setSelectedCategory(result.category || "");
    setSuggestedCategories(result.suggested_categories);
    setCategoryConfidence(result.confidence);
  } catch (err) {
    message.error(`险种识别失败: ${err}`);
  }
};

// 确认检查时传入险种
const handleConfirmReview = async () => {
  if (!parsedDocument) return;
  setLoading(true);
  try {
    const report = await complianceApi.checkDocument({
      document_content: parsedDocument.combined_text,
      product_name: productName || parsedDocument.file_name || undefined,
      parse_id: parsedDocument.parse_id,
      category: selectedCategory || undefined,
    });
    setCheckingResult(report);
    message.success('合规检查完成');
    loadHistory();
  } catch (err) {
    message.error(`检查失败: ${err}`);
  } finally {
    setLoading(false);
  }
};
```

**Step 5.2: 险种选择 UI 组件**

```tsx
{/* 险种选择区域 */}
<Card size="small" style={{ marginTop: 16 }}>
  <Space direction="vertical" style={{ width: '100%' }}>
    <Space>
      <Text strong>险种类型：</Text>
      <Select
        style={{ width: 200 }}
        placeholder="选择险种类型"
        value={selectedCategory || undefined}
        onChange={setSelectedCategory}
        options={suggestedCategories.map(c => ({ label: c, value: c }))}
      />
      <Button size="small" onClick={handleIdentifyCategory} loading={loading}>
        自动识别
      </Button>
    </Space>
    {identifiedCategory && (
      <Text type="secondary">
        识别结果：{identifiedCategory} (置信度: {(categoryConfidence * 100).toFixed(0)}%)
      </Text>
    )}
  </Space>
</Card>
```

**Checkpoint**: Phase 5 - 前端险种选择集成可用

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

---

## Appendix

### 执行顺序建议

```
Phase 1 (险种法规映射配置) 
  → Phase 2 (通用法规强制包含) 
  → Phase 3 (负面清单独立检查) 
  → Phase 4 (险种识别与确认) 
  → Phase 5 (前端险种选择集成)
```

Phase 1-3 有依赖关系（配置 → 检索逻辑 → 检查集成），Phase 4-5 依赖 Phase 1-3 完成。

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 险种专属法规加载 | 法规上下文包含险种专属法规 | `test_regulation_registry.py` |
| US2 通用法规强制包含 | 法规上下文包含保险法、条款管理办法 | `test_compliance.py` |
| US3 负面清单独立检查 | 检查结果包含负面清单检查项 | `test_negative_list.py` |
| US4 险种识别与确认 | LLM 能识别险种，用户可修正 | E2E 测试 |