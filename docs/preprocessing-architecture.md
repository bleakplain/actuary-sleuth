# 文档预处理模块系统架构综述

## 一、整体架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                      DocumentExtractor                            │
│                          (主入口)                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        处理流程                                     │
├─────────────────────────────────────────────────────────────────┤
│  1. DocumentNormalizer   →  文档规范化                             │
│  2. RouteSelector         → 路由选择                               │
│  3. Extractor (Fast/Structured) → 执行提取                        │
│  4. ResultValidator       → 结果验证                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、系统流程与数据流

### 2.1 完整数据流图

```
原始文档 (str)
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  1. DocumentNormalizer.normalize()                           │
│     输入: document (str), source_type (str)                   │
│     输出: NormalizedDocument                                  │
│                                                              │
│     处理步骤:                                                 │
│     • _normalize_encoding()    → 编码统一                    │
│     • _remove_noise()         → 去除噪声                    │
│     • _detect_format()        → 格式检测                    │
│     • _mark_structure()       → 结构标记                    │
└──────────────────────────────────────────────────────────────┘
    │
    │ NormalizedDocument {
    │   content: str,
    │   format_info: FormatInfo,
    │   structure_markers: StructureMarkers,
    │   metadata: Dict
    │ }
    ▼
┌──────────────────────────────────────────────────────────────┐
│  2. RouteSelector.select_route()                              │
│     输入: NormalizedDocument                                  │
│     输出: ExtractionRoute                                      │
│                                                              │
│     决策逻辑:                                                 │
│     • ProductTypeClassifier.classify() → 产品类型            │
│     • _can_use_fast_route()          → 路由判断               │
│       - is_standard: 格式标准化                                │
│       - is_confident: 置信度 ≥ 0.7                             │
│       - has_key_info_front: 关键信息在前2000字符              │
└──────────────────────────────────────────────────────────────┘
    │
    │ ExtractionRoute {
    │   mode: 'fast' | 'structured',
    │   product_type: str,
    │   confidence: float,
    │   is_hybrid: bool,
    │   reason: str
    │ }
    ▼
    ┌─────────────────┬─────────────────┐
    │                 │                 │
    ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  │
│ Fast Lane    │  │Structured    │  │
│ (80%)        │  │Lane (20%)    │  │
└──────────────┘  └──────────────┘  │
    │                 │             │
    │                 ▼             │
    │    ┌─────────────────────────┐│
    │    │ PromptBuilder.build()   ││
    │    │ 动态生成 Prompt          ││
    │    └─────────────────────────┘│
    │                 │             │
    │    ┌─────────────────────────┐│
    │    │ StructuredExtractor     ││
    │    │ • StructureAnalyzer     ││
    │    │ • PremiumTableExtractor ││
    │    │ • ClauseExtractor       ││
    │    └─────────────────────────┘│
    │                                │
    ▼                                ▼
┌──────────────────────────────────────────────────────────────┐
│  4. ResultValidator.validate()                               │
│     输入: ExtractResult                                       │
│     输出: ValidationResult                                    │
│                                                              │
│     验证维度:                                                 │
│     • 必需字段检查                                            │
│     • 数据类型检查                                            │
│     • 业务规则检查                                            │
│     • 置信度检查                                              │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
ExtractResult {
    data: Dict[str, Any],
    confidence: Dict[str, float],
    provenance: Dict[str, str],
    metadata: Dict {
        extraction_mode,
        product_type,
        confidence,
        validation_score,
        ...
    }
}
```

---

## 三、核心组件详解

### 3.1 文档规范化器 (DocumentNormalizer)

| 组件 | 功能 |
|------|------|
| `_normalize_encoding()` | 统一换行符、移除BOM、清理控制字符 |
| `_remove_noise()` | PDF页眉页脚、HTML标签残留、全角空格、零宽字符 |
| `_detect_format()` | 检测表格密度、章节结构、条款编号、费率表特征 |
| `_mark_structure()` | 标记条款/表格/章节位置 |

### 3.2 路由选择器 (RouteSelector)

**快速通道判定条件（必须全部满足）：**

1. **格式标准化**: `is_structured && has_clause_numbers`
2. **分类置信度高**: `confidence >= 0.7`
3. **关键信息在前**: 前2000字符包含75%以上必需字段指示词

**必需字段指示词映射：**
```python
{
    'product_name': ['产品名称', '保险产品', '保险计划'],
    'insurance_company': ['保险公司', '承保机构', '公司名称'],
    'insurance_period': ['保险期间', '保障期限', '保险期限'],
    'waiting_period': ['等待期', '观察期']
}
```

### 3.3 产品类型分类器 (ProductTypeClassifier)

**支持7种产品类型 + 1种默认类型：**

| 代码 | 名称 | 匹配模式 | 特征权重 |
|------|------|----------|----------|
| `critical_illness` | 重大疾病险 | `重大疾病.*?保险`, `重疾险` | 病种清单0.3, 分级0.2, 等待期0.1 |
| `medical_insurance` | 医疗保险 | `医疗.*?保险`, `费用.*?报销` | 免赔额0.3, 赔付比例0.3 |
| `universal_life` | 万能险 | `万能.*?保险` | 账户0.4, 结算利率0.3 |
| `term_life` | 定期寿险 | `定期.*?寿险` | 保险期间0.3, 身故保险金0.3 |
| `whole_life` | 终身寿险 | `终身.*?寿险` | 现金价值0.3, 保险期间0.3 |
| `annuity` | 年金保险 | `年金.*?保险`, `养老金` | 年金期间0.3, 年金金额0.3 |
| `accident_insurance` | 意外伤害保险 | `意外.*?保险`, `意外险` | 意险范围0.3, 赔付比例0.3 |
| `life_insurance` | 人身保险（默认） | `保险`, `条款` | 保险期间0.2, 等待期0.2 |

---

## 四、动态 Prompt 维护机制

### 4.1 Prompt 构建器架构

```
PromptBuilder
    │
    ├── COMPONENTS (组件库)
    │   ├── 角色组件
    │   │   ├── role_base (通用角色)
    │   │   └── role_specialized (专家角色 - 支持产品类型注入)
    │   │
    │   ├── 字段说明组件 (12种)
    │   │   ├── field_product_info
    │   │   ├── field_diseases
    │   │   ├── field_coverage
    │   │   ├── field_deductible
    │   │   ├── field_payout_ratio
    │   │   ├── field_limits
    │   │   ├── field_account
    │   │   ├── field_settlement_rate
    │   │   └── field_death_benefit
    │   │
    │   ├── 输出格式组件
    │   │   └── output_structure
    │   │
    │   └── 特殊场景组件
    │       └── hybrid_notice (混合产品说明)
    │
    └── build() 方法
        ├── 1. 角色定义 (基于产品类型)
        ├── 2. 字段说明 (按需组装)
        ├── 3. 混合产品特殊说明 (条件)
        └── 4. 输出格式 (注入 Schema)
```

### 4.2 动态 Prompt 生成流程

```python
# 1. 产品类型 → 角色定义
product_type = 'critical_illness'
→ "你是重大疾病险产品提取专家"
→ "提取重点: 病种清单、等待期、赔付分级、赔付比例"

# 2. required_fields → 字段组件
required_fields = ['product_name', 'covered_diseases', 'waiting_period']
→ 组件: ['field_product_info', 'field_diseases']

# 3. 产品类型 → 输出 Schema
output_schema = OUTPUT_SCHEMA_TEMPLATES['critical_illness']
→ {
    "product_info": {...},
    "covered_diseases": [...]
  }

# 4. 组装最终 Prompt
prompt = role + field_components + hybrid_notice + output_structure
```

### 4.3 Prompt 维护点

**1. 产品类型定义**
```python
# 位置: product_types.py
PRODUCT_TYPES = [...]  # 新增产品类型
```

**2. 提取重点映射**
```python
# 位置: product_types.py
EXTRACTION_FOCUS_MAP = {
    'new_product_type': ['重点1', '重点2', ...],
}
```

**3. 输出 Schema 模板**
```python
# 位置: product_types.py
OUTPUT_SCHEMA_TEMPLATES = {
    'new_product_type': {
        "field_name": "字段说明",
        ...
    },
}
```

**4. 字段说明组件**
```python
# 位置: prompt_builder.py
COMPONENTS = {
    'field_new_field': """
    **新字段说明**:
    - field_name: 描述
    ...
    """,
}
```

**5. 字段-组件映射**
```python
# 位置: prompt_builder.py → _get_field_components()
component_map = {
    'new_field': ['field_new_field'],
}
```

---

## 五、双通道提取策略

### 5.1 快速通道

**特点：**
- 目标覆盖：80% 的文档
- 成本优化：单次 LLM 调用
- Prompt 类型：Few-shot Prompt（2-3个示例）
- Token 预算：**1500 tokens** (输出)
- 文档截取：**1500 字符** (输入)
- 温度设置：0.1（低随机性）

**提取策略：**
```python
# Few-shot 示例模板
示例1 → 输入: "..." → 输出: {...}
示例2 → 输入: "..." → 输出: {...}
输入: {document[:1500]}  # 1500字符支持中文
输出: ?
```

**补充提取：**
- 如果 LLM 输出缺失必需字段
- 使用正则表达式回退提取
- 支持字段：product_name, insurance_company, insurance_period, waiting_period, payment_method

### 5.2 结构化通道

**特点：**
- 目标覆盖：20% 的复杂文档
- 动态 Prompt：基于产品类型定制
- 专用提取器：费率表、条款
- Token 预算：**6000 tokens** (输出)
- 文档截取：**15000 字符** (输入)
- 温度设置：0.1

**提取策略：**
```
1. PromptBuilder.build() → 生成定制 Prompt
2. LLM 提取 → 主要信息
3. StructureAnalyzer.analyze() → 检测结构
4. PremiumTableExtractor.extract() → 费率表专用
5. ClauseExtractor.extract() → 条款专用
```

---

## 六、数据模型体系

### 6.1 核心数据流

```
原始文档
    ↓
NormalizedDocument {
    content: str                    → 规范化内容
    format_info: FormatInfo         → 格式信息
    structure_markers: StructureMarkers → 结构标记
    metadata: Dict                  → 元数据
}
    ↓
ExtractionRoute {
    mode: str                       → 'fast' | 'structured'
    product_type: str               → 产品类型
    confidence: float               → 置信度
    is_hybrid: bool                 → 是否混合
    reason: str                     → 决策原因
}
    ↓
ExtractResult {
    data: Dict[str, Any]            → 提取数据
    confidence: Dict[str, float]    → 字段置信度
    provenance: Dict[str, str]      → 字段来源
    metadata: Dict {
        extraction_mode: str,        → 'fast' | 'structured'
        product_type: str,
        confidence: float,
        validation_score: int,
        ...
    }
}
    ↓
ValidationResult {
    is_valid: bool                  → 是否有效
    errors: List[str]               → 错误列表
    warnings: List[str]             → 警告列表
    score: int                      → 验证分数 (0-100)
}
```

---

## 七、扩展与维护指南

### 7.1 新增产品类型

**步骤：**

1. 在 `product_types.py` 添加 `ProductType` 定义
2. 更新 `EXTRACTION_FOCUS_MAP`
3. 更新 `OUTPUT_SCHEMA_TEMPLATES`
4. 如需新字段，在 `prompt_builder.py` 添加字段组件
5. 更新 `_get_field_components()` 映射

### 7.2 调整快速通道阈值

**位置：** `path_selector.py`

```python
# 置信度阈值
is_confident = confidence >= 0.7  # 可调整

# 关键信息位置阈值
return required_found >= len(self.REQUIRED_FIELDS) * 0.75  # 可调整
```

### 7.3 添加业务规则

**位置：** `validator.py`

```python
BUSINESS_RULES = [
    BusinessRule(
        name="rule_name",
        check=lambda data: ...,
        error_message="错误描述"
    ),
]
```

---

## 八、系统优势

1. **成本优化**: 80% 文档走快速通道，单次 LLM 调用
2. **准确率高**: 动态 Prompt 针对产品类型优化
3. **可扩展性强**: 组件化 Prompt 构建，易于新增产品类型
4. **容错性好**: 快速通道失败自动回退结构化通道
5. **质量可控**: 多层验证（必需字段、数据类型、业务规则）
6. **来源可追溯**: 每个字段记录置信度和来源
7. **中文友好**: Token 预算针对中文优化（1500/6000 tokens）

---

## 九、类名映射表

| 新名称 | 旧名称 | 说明 |
|--------|--------|------|
| `DocumentExtractor` | `UnifiedDocumentExtractor` | 移除冗余的"Unified"前缀 |
| `RouteSelector` | `ExtractionPathSelector` | 简化名称，路径→路由 |
| `FastExtractor` | `LightweightExtractor` | 更直观的命名 |
| `ResultValidator` | `ExtractResultValidator` | 简化名称 |
| `ExtractionRoute` | `ExtractionPath` | 路径→路由 |
| `FastExtractionFailed` | `FastPathExtractionFailed` | 保持一致性 |
| `mode` | `path_type` | 更简洁的属性名 |
| `extraction_mode` | `extraction_path` | 元数据中使用完整名称 |

---

## 十、术语对照表

| 新术语 | 旧术语 | 说明 |
|--------|--------|------|
| 路由/通道 | 路径 | 更直观的提取方式描述 |
| 快速通道 | 快速路径 | 80%文档的提取方式 |
| 结构化通道 | 结构化路径 | 20%文档的提取方式 |
| 路由选择 | 路径选择 | RouteSelector 的功能描述 |
