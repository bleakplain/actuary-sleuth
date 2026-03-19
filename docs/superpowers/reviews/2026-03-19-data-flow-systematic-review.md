# Preprocessing → Audit → Reporting 数据流系统性Review

**Date:** 2026-03-19
**Scope:** 完整数据流分析 (预处理 → 审核 → 报告)
**Method:** 系统性代码审查 + 数据流追踪

## 数据流架构概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         完整数据流                                     │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Raw Document   │───>│  Preprocessing  │───>│     Audit       │───>│    Reporting    │
│  (PDF/Text)     │    │  Module         │    │  Module         │    │  Module         │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
                              │                       │                       │
                              ▼                       ▼                       ▼
                        ExtractResult          AuditRequest            EvaluationContext
                              │                       │                       │
                              │                       ▼                       ▼
                              │                   AuditResult              Word/Push
                              │                       │                   Document
                              │                       ▼
                              │                   AuditOutcome
                              │                   List[AuditOutcome]
                              │
                              └───────────────────────> Quality Gate
                                                     (validation_score >= 60)
```

## 发现的问题

### P0 - 严重问题

#### 1. 数据模型定义分散在多个文件
**问题:** 同名类 `AuditResult` 存在于两个不同位置

**位置:**
- `lib/audit/auditor.py:62` - dataclass `AuditResult` (审核模块使用)
- `audit.py:91` - TypedDict `AuditResult` (顶层API使用)

**风险:**
```python
# 审核模块返回
from lib.audit import AuditResult  # dataclass with 6 fields

# 顶层API返回
audit_result: AuditResult  # TypedDict with 12+ fields
```

**影响:** 类型混淆、IDE自动补全错误、潜在的运行时错误

**建议:** 统一为单一数据模型定义，使用继承或别名

---

#### 2. 预处理质量门控可能丢失重要数据
**问题:** `AuditRequest.from_extract_result()` 在 `validation_score < 60` 时抛出异常

**位置:** `lib/common/models.py:106-108`

```python
validation_score = extract_result.metadata.get('validation_score', 0)
if validation_score > 0 and validation_score < 60:
    raise ValueError(f"提取质量过低 (score: {validation_score})，不满足审核要求")
```

**风险:**
- 当 `validation_score == 0` (未设置) 时，门控被绕过
- 低质量文档可能进入审核流程
- 没有降级处理机制

**建议:**
```python
# 改进方案
if validation_score == 0:
    # 未验证，记录警告
    logger.warning("未设置validation_score，建议先验证提取质量")
elif validation_score < 60:
    # 低质量，但提供降级选项
    if allow_low_quality:
        logger.warning(f"提取质量较低 (score: {validation_score})，继续审核")
    else:
        raise ValueError(...)
```

---

#### 3. 条款规范化可能丢失数据
**问题:** `_normalize_clauses()` 只保留 `text` 和 `number` 字段

**位置:** `lib/common/models.py:196-228`

```python
normalized_clause = {
    'text': text,
    'number': clause.get('number', ''),
}
```

**丢失的字段:**
- `title` - 条款标题
- `content` - 详细内容
- `reference` - 引用编号

**风险:** 原始文档中的丰富信息在审核时不可用

**建议:**
```python
normalized_clause = {
    'text': text,
    'number': clause.get('number', ''),
    'title': clause.get('title', ''),  # 保留标题
    'original': clause,  # 保留原始数据
}
```

---

### P1 - 高优先级问题

#### 4. AuditRequest 的 Product 类型不一致
**问题:** `Product.category` 是 `ProductCategory` enum，但创建时可能传入字符串

**位置:** `lib/common/models.py:123-124`

```python
product_type = extract_result.metadata.get('product_type', 'other')
category = category_map.get(product_type, ProductCategory.OTHER)
```

**风险:** 如果 `product_type` 不在 `category_map` 中，默认为 `OTHER`，可能掩盖分类错误

**建议:** 添加日志记录未匹配的产品类型

---

#### 5. EvaluationContext 的 violations 属性是派生属性
**问题:** `violations` 是 `@property`，每次访问都重新计算

**位置:** `lib/reporting/model.py:96-116`

```python
@property
def violations(self) -> List[Dict[str, Any]]:
    if not self.audit_result:
        return []
    return [{...} for issue in self.audit_result.issues]  # 每次都重新构建
```

**性能影响:** 在报告生成过程中多次访问 `violations` 会重复创建对象

**建议:** 缓存转换结果或使用 `__post_init__` 预计算

---

#### 6. 产品信息在两个模块中重复定义
**问题:** 产品信息模型分散在两处

**位置:**
- `lib/common/models.py:46-55` - `Product` (审核使用)
- `lib/reporting/model.py:19-30` - `_InsuranceProduct` (报告使用)

**字段对比:**
```python
# lib/common.models.Product
name, company, category(ProductCategory), period, waiting_period, age_min, age_max

# lib.reporting.model._InsuranceProduct
name, type(str), company, document_url, version
```

**不一致点:**
- `category` vs `type` - 类型不同
- `period` vs `version` - 字段不同
- 产品特定字段 (waiting_period, age_min, age_max) 在报告模型中缺失

**建议:** 统一产品信息模型，报告使用审核的 `Product` 或创建适配器

---

#### 7. 整数解析可能丢失信息
**问题:** `_parse_int()` 只提取第一个数字

**位置:** `lib/common/models.py:170-180`

```python
def _parse_int(value: Any) -> Optional[int]:
    if isinstance(value, str):
        import re
        match = re.search(r'\d+', value)  # 只匹配第一个数字
        return int(match.group()) if match else None
```

**问题场景:**
- `"180天"` → 180 ✓
- `"90-180天"` → 90 (应该是范围)
- `"等待期180天" "30天"` → 都只提取第一个数字

**建议:**
```python
# 改进方案
def _parse_int_or_range(value: Any) -> Union[int, Tuple[int, int], None]:
    # 尝试解析范围 "90-180"
    range_match = re.search(r'(\d+)\s*[-~到]\s*(\d+)', str(value))
    if range_match:
        return (int(range_match.group(1)), int(range_match.group(2)))
    # 单个值
    int_match = re.search(r'\d+', str(value))
    return int(int_match.group()) if int_match else None
```

---

### P2 - 中等优先级问题

#### 8. Extra 字段被隔离在 AuditRequest 中
**问题:** `AuditRequest.extra` 包含未使用字段，但未被审核流程使用

**位置:** `lib/common/models.py:165`

```python
extra={k: v for k, v in data.items() if k not in _used_fields()}
```

**风险:** 有价值的数据（如特殊条款、附加信息）在审核时不可用

**建议:** 明确哪些字段应该传递给审核，而不是全部隔离

---

#### 9. Quality Score 来源不明确
**问题:** `validation_score` 的计算逻辑在 `ResultValidator` 中，但没有明确的调用路径

**位置:** `lib/preprocessing/validator.py:173`

```python
score -= error_count * self.ERROR_PENALTY
score -= warning_count * self.WARNING_PENALTY
```

**问题:**
- 没有看到 `validator.validate()` 的结果被设置到 `extract_result.metadata['validation_score']`
- 在 `DocumentExtractor.extract()` 中调用了验证，但分数可能没有正确传播

**需要验证:** 确认 `validation_score` 是否正确写入 `metadata`

---

#### 10. 法规引用在两个地方生成
**问题:** `regulation_basis` 在报告模块有两处生成逻辑

**位置:**
- `lib/reporting/template/report_template.py:179-194` - `_generate_default_regulation_basis()`
- `lib/reporting/export/docx_generator.py:721-725` - `_generate_regulation_basis()`

**重复代码:** 两者都返回硬编码的法规列表

**建议:** 统一到 `AuditResult.regulations_used`

---

### P3 - 低优先级问题

#### 11. 缺少数据流验证
**问题:** 没有端到端的数据完整性检查

**建议:** 添加集成测试验证完整数据流

---

#### 12. 错误处理不统一
**问题:** 各模块使用不同的异常类型

**位置:**
- `lib/common/models.py:108` - `ValueError`
- `lib/audit/auditor.py:224` - `Exception` (捕获后记录日志)

**建议:** 统一异常层次结构

---

#### 13. 日志级别使用不一致
**问题:** 有些地方用 `logger.error`，有些用 `logger.info`

**建议:** 建立日志级别规范

---

## 数据流完整性检查

### 关键转换点

| 转换点 | 输入 | 输出 | 状态 |
|--------|------|------|------|
| Raw → Normalized | Raw Document | NormalizedDocument | ✅ 正常 |
| Normalized → Extract | NormalizedDocument | ExtractResult | ✅ 正常 |
| Extract → Validate | ExtractResult | ValidationResult | ⚠️ 需验证score传播 |
| Extract → AuditRequest | ExtractResult | AuditRequest | ⚠️ 字段丢失 |
| AuditRequest → Audit | AuditRequest | AuditResult | ✅ 正常 |
| AuditResult → ReportContext | AuditResult | EvaluationContext | ✅ 正常 |
| ReportContext → Report | EvaluationContext | Word/Push | ✅ 正常 |

### 字段传播追踪

| 字段 | Preprocessing | Audit | Reporting | 状态 |
|------|---------------|-------|-----------|------|
| `product.name` | ✅ | ✅ | ✅ | ✅ 完整传播 |
| `product.category` | ✅ (string) | ✅ (enum) | ❌ | ⚠️ 类型转换 |
| `product.waiting_period` | ✅ | ✅ | ❌ | ⚠️ 报告中缺失 |
| `clauses.text` | ✅ | ✅ | ✅ | ✅ 完整传播 |
| `clauses.title` | ✅ | ❌ | ❌ | ❌ 丢失 |
| `validation_score` | ✅ | ⚠️ (仅门控) | ❌ | ⚠️ 未传播 |
| `issues.dimension` | - | ✅ | ✅ (as category) | ✅ 字段映射 |
| `issues.suggestion` | - | ✅ | ✅ (as remediation) | ✅ 字段映射 |
| `regulations_used` | - | ✅ | ✅ | ✅ 完整传播 |

---

## 建议的修复优先级

### 立即修复 (P0)
1. **统一 AuditResult 定义** - 合并 `lib/audit/auditor.py` 和 `audit.py` 中的定义
2. **改进质量门控** - 处理 `validation_score == 0` 的情况
3. **保留条款原始数据** - 修改 `_normalize_clauses()` 保留更多字段

### 短期修复 (P1)
4. **统一产品信息模型** - 报告使用审核的 Product 模型
5. **缓存 violations 属性** - 避免重复计算
6. **改进整数解析** - 支持范围解析

### 中期修复 (P2)
7. **验证 validation_score 传播** - 确认分数正确写入 metadata
8. **统一法规引用** - 只使用 `AuditResult.regulations_used`
9. **改进 extra 字段处理** - 明确传递策略

### 长期改进 (P3)
10. **添加端到端测试** - 完整数据流验证
11. **统一异常处理** - 建立异常层次结构
12. **规范日志级别** - 建立日志规范

---

## 测试覆盖建议

### 端到端测试场景
```python
def test_full_data_flow():
    """测试完整数据流"""
    # 1. 预处理
    extract_result = extractor.extract(document)

    # 2. 验证质量分数传播
    assert 'validation_score' in extract_result.metadata
    assert extract_result.metadata['validation_score'] >= 0

    # 3. 转换为审核请求
    request = AuditRequest.from_extract_result(extract_result)

    # 4. 验证关键字段传播
    assert request.product.name == extract_result.data['product_name']
    assert len(request.clauses) > 0

    # 5. 执行审核
    outcomes = auditor.audit(request)

    # 6. 生成报告
    audit_result = outcomes[0].result
    report = template.generate(audit_result, {...})

    # 7. 验证数据完整性
    assert audit_result.score == report['score']
    assert audit_result.overall_assessment in report['content']
```

---

## 总结

### 关键发现
1. **数据模型分散** - 同名类定义在不同位置
2. **字段丢失** - 条款原始数据在转换中丢失
3. **类型不一致** - 产品信息在两处定义不一致
4. **质量门控薄弱** - 未验证时绕过门控

### 整体评估
- **数据流完整性:** 75% - 大部分数据正确传播，但有字段丢失
- **类型安全性:** 70% - 存在类型不一致和重复定义
- **错误处理:** 65% - 缺乏统一的异常处理策略

### 下一步行动
1. 创建统一的数据模型定义
2. 改进质量门控逻辑
3. 添加端到端集成测试
4. 建立数据流监控机制
