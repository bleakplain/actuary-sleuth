# 文档预处理模块详细数据流

> 版本: v4.0
> 日期: 2025-03-12
> 作者: System Architecture Review

---

## 一、数据流概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              原始文档 (str)                                 │
│                         "保险产品文档内容..."                                │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           阶段 1: 文档规范化                                 │
│                        Normalizer.normalize()                               │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌───────────────┐ ┌─────────────┐ ┌────────────────┐
            │ 1.1 编码统一   │ │ 1.2 去除噪声 │ │ 1.3 格式检测   │
            │ - 移除 BOM     │ │ - PDF/HTML  │ │ - 章节结构     │
            │ - 统一换行符   │ │ - 通用噪声  │ │ - 条款编号     │
            │ - 移除控制字符 │ │             │ │ - 费率表特征   │
            └───────────────┘ └─────────────┘ └────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                     ▼
            ┌───────────────┐                   ┌──────────────┐
            │ 1.4 结构标记   │                   └──────────────┘
            │ - 条款位置     │
            │ - 表格位置     │
            │ - 章节位置     │
            └───────┬───────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          NormalizedDocument                                 │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ content: str                    # 清洗后的文档内容                        ││
│ │ profile: DocumentProfile      # 文档画像（用于路由决策）                ││
│ │   - is_structured: bool        # 是否有章节结构 (≥5个章节)              ││
│ │   - has_clause_numbers: bool   # 是否有条款编号 (第X条)                ││
│ │   - has_premium_table: bool    # 是否包含费率表                         ││
│ │ structure_markers: StructureMarkers                                     ││
│ │   - clause_positions: List[int]  # 条款位置索引列表                    ││
│ │   - table_positions: List[int]   # 表格位置索引列表                    ││
│ │   - section_positions: List[int] # 章节位置索引列表                    ││
│ │ metadata: Dict[str, Any]        # {original_length, normalized_length} ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           阶段 2: 提取器选择                                 │
│                       ExtractorSelector.select()                            │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌───────────────┐ ┌─────────────┐ ┌────────────────┐
            │ 2.1 产品分类   │ │ 2.2 三重判断 │ │ 2.3 提取器选择  │
            │ ProductClass  │ │             │ │                │
            │ - classify()  │ │ - 格式复杂  │ │ - FastExtractor│
            │ - 返回类型+   │ │ - 低置信度  │ │ - Dynamic      │
            │   置信度      │ │ - 关键信息  │ │   Extractor    │
            └───────┬───────┘ └──────┬──────┘ └────────┬───────┘
                    │                  │                  │
                    │                  └──────────────────┤
                    │                                     │
                    ▼                                     ▼
        [(type_code, confidence), ...]           FastExtractor |
        e.g., [('critical_illness', 0.85)]       DynamicExtractor
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          阶段 3: 信息提取                                     │
│                    extractor.extract(document, fields)                       │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
                    ▼                                   ▼
        ┌───────────────────────┐       ┌───────────────────────┐
        │     3a. Fast 车道      │       │     3b. Dynamic 车道   │
        │   FastExtractor       │       │   DynamicExtractor     │
        └───────────────────────┘       └───────────────────────┘
                    │                                   │
        ┌───────────┼───────────┐                   ┌───┴──────────────────────┐
        ▼           ▼           ▼                   ▼                          ▼
  ┌────────┐ ┌────────┐ ┌────────┐         ┌────────────┐      ┌─────────────┐
  │Few-shot│ │ LLM    │ │Regex   │         │产品分类     │      │专用提取器   │
  │Prompt  │ │调用    │ │补充    │         │(一次性)     │      │- 费率表     │
  └────┬───┘ └───┬────┘ └───┬────┘         └──────┬─────┘      │- 条款       │
       │         │          │                     │            └─────────────┘
       │         │          │               ┌──────┴──────┐
       │         │          │               ▼             ▼
       │         │          │         ┌─────────┐  ┌────────────┐
       │         │          │         │Prompt   │  │LLM 调用    │
       │         │          │         │Builder  │  │            │
       │         │          │         └────┬────┘  └──────┬─────┘
       │         │          │              │              │
       │         └──────────┴──────────────┴──────────────┘
       │                  │
       ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            parse_llm_json_response()                         │
│                      统一的 JSON 响应解析 (utils/json_parser.py)             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ 策略 1: 提取 markdown 代码块  ```json ... ```                           ││
│ │ 策略 2: 解析裸 JSON 对象  {...}                                         ││
│ │ 策略 3: 从文本中提取嵌入的 JSON                                          ││
│ │ 策略 4: 失败时返回默认值或抛出异常                                        ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ExtractResult                                  │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ data: Dict[str, Any]              # 提取的字段数据                      ││
│ │   {                                                                    ││
│ │     'product_name': '重大疾病保险',                                     ││
│ │     'insurance_company': 'XX人寿保险股份有限公司',                      ││
│ │     'insurance_period': '终身',                                        ││
│ │     'waiting_period': 90,                                              ││
│ │     'covered_diseases': [...],     # Dynamic 专用                       ││
│ │     'premium_table': {...},        # Dynamic 专用                       ││
│ │     'clauses': [...]               # Dynamic 专用                       ││
│ │   }                                                                    ││
│ │                                                                        ││
│ │ confidence: Dict[str, float]      # 字段置信度                          ││
│ │   {                                                                    ││
│ │     'product_name': 0.85,             # Fast 车道默认 0.85              ││
│ │     'insurance_company': 0.85,                                     ││
│ │     'covered_diseases': 0.75,       # Dynamic 车道默认 0.75            ││
│ │     ...                                                                  ││
│ │   }                                                                    ││
│ │                                                                        ││
│ │ provenance: Dict[str, str]        # 字段来源标识                        ││
│ │   {                                                                    ││
│ │     'product_name': 'fast_llm',     # Fast: 'fast_llm', 'regex'        ││
│ │     'covered_diseases': 'dynamic_llm',  # Dynamic: 'dynamic_llm',      ││
│ │     'premium_table': 'specialized_extractor'                          ││
│ │   }                                                                    ││
│ │                                                                        ││
│ │ metadata: Dict[str, Any]           # 提取元数据                         ││
│ │   {                                                                    ││
│ │     'extraction_mode': 'fast',      # 'fast' 或 'dynamic'              ││
│ │     'product_type': 'critical_illness',  # Dynamic 车道包含            ││
│ │     'is_hybrid': false                                                    ││
│ │   }                                                                    ││
│ │ }                                                                      ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           阶段 4: 结果验证                                   │
│                        ResultValidator.validate()                           │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌───────────────┐ ┌─────────────┐ ┌────────────────┐
            │ 4.1 必需字段   │ │ 4.2 数据类型 │ │ 4.3 业务规则   │
            │   检查        │ │   检查      │ │   检查        │
            │ - product_name│ │ - 金额格式  │ │ - 年龄范围     │
            │ - insurance_  │ │ - 年龄整数  │ │ - 等待期范围   │
            │   company     │ │             │ │                │
            │ - insurance_  │ │             │ │                │
            │   period      │ │             │ │                │
            │ - waiting_    │ │             │ │                │
            │   period      │ │             │ │                │
            └───────┬───────┘ └──────┬──────┘ └────────┬───────┘
                    │                  │                  │
                    └──────────────────┴──────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            ValidationResult                                │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ is_valid: bool                   # 是否通过验证                          ││
│ │ errors: List[str]                # 错误列表（必需字段缺失、格式错误等） ││
│ │ warnings: List[str]              # 警告列表（低置信度字段等）            ││
│ │ score: int                       # 验证分数 (0-100)                     ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           阶段 5: 元数据添加                                 │
│                   result.metadata.update()                                  │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ {                                                                      ││
│ │   'extraction_mode': 'fast',       # 保留原有的提取模式                 ││
│ │   'validation_score': 85,           # 新增：验证分数                   ││
│ │   'validation_errors': [],          # 新增：验证错误                   ││
│ │   'validation_warnings': [...]      # 新增：验证警告                   ││
│ │ }                                                                      ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            最终返回 ExtractResult                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、各阶段详细数据转换

### 2.1 阶段 1: 文档规范化

**输入**: `document: str, source_type: str`

**处理流程**:

```python
# Normalizer.normalize()
normalized = document
    ↓ _normalize_encoding()
    # "保险内容\r\n" → "保险内容\n"
    # "\ufeff开头" → ""
    ↓ _remove_noise(source_type)
    # PDF: 移除 "第 X 页"、孤立项码
    # HTML: 移除 <tag> 残留
    # 通用: 全角空格→空格, 统一引号
    ↓ _detect_format()
    # DocumentProfile {
    #   is_structured: bool (章节≥5)
    #   has_clause_numbers: bool (第X条)
    #   has_premium_table: bool
    # }
    ↓ _mark_structure()
    # StructureMarkers {
    #   clause_positions: [123, 456, ...]
    #   table_positions: [789, ...]
    #   section_positions: [10, 20, ...]
    # }
```

**输出**: `NormalizedDocument`

### 2.2 阶段 2: 提取器选择

**输入**: `NormalizedDocument`

**处理流程**:

```python
# ExtractorSelector.select()
document = NormalizedDocument
    ↓ ProductClassifier.get_primary_type(document.content)
    # ProductClassifier.classify() 内部:
    # for product_type in PRODUCT_TYPES:
    #     score = product_type.match_score(document)
    #     # 关键词匹配 + 特征匹配
    # return sorted(scores, descending)
    # 返回: [('critical_illness', 0.85), ...]
    # get_primary_type() 返回: ('critical_illness', 0.85)
    ↓ _use_dynamic(profile, confidence, document)
    # 条件1: is_complex = not profile.is_structured or not profile.has_clause_numbers
    # 条件2: is_low_confidence = confidence < 0.7
    # 条件3: has_key_info_back = not _check_key_info_position()
    #   检查前 2000 字符是否包含 ≥75% 的字段指示词
    # return any(is_complex, is_low_confidence, has_key_info_back)
    ↓ 三元选择
    # extractor = dynamic_extractor if use_dynamic else fast_extractor
```

**输出**: `FastExtractor | DynamicExtractor` (实例)

### 2.3 阶段 3a: Fast 车道数据流

**输入**: `NormalizedDocument, required_fields: List[str]`

**处理流程**:

```python
# FastExtractor.extract()
document, required_fields
    ↓ 构建 Few-shot Prompt
    # prompt = FEW_SHOT_EXTRACT.format(document[:1500])
    # 包含示例1、示例2、当前文档
    ↓ LLM 调用
    # response = llm_client.generate(prompt, max_tokens=1500, temperature=0.1)
    ↓ parse_llm_json_response(response, strict=True)
    # 策略1: 提取 ```json ... ```
    # 策略2: 解析裸 {...}
    # 策略3: 提取嵌入的 JSON
    # 策略4: 失败抛 ValueError
    ↓ _supplement_extract() (如有缺失字段)
    # for missing_field in required_fields - result.keys():
    #     value = _extract_by_regex(document.content, missing_field)
    #     if value: result[missing_field] = value
    ↓ 构建 ExtractResult
    # data = result
    # confidence = {k: 0.85 for k in result}
    # provenance = {k: 'fast_llm' for k in result}
    # metadata = {'extraction_mode': 'fast'}
```

**输出**: `ExtractResult`

### 2.4 阶段 3b: Dynamic 车道数据流

**输入**: `NormalizedDocument, required_fields: List[str]`

**处理流程**:

```python
# DynamicExtractor.extract()
document, required_fields
    ↓ 一次性产品分类 (避免重复)
    # classifications = self.classifier.classify(document.content)
    # product_type = classifications[0][0]  # e.g., 'critical_illness'
    # is_hybrid = len(classifications) > 1 and classifications[1][1] > 0.5
    ↓ PromptBuilder.build()
    # prompt = builder.build(
    #     product_type=product_type,
    #     required_fields=required_fields,
    #     extraction_focus=get_extraction_focus(product_type),
    #     output_schema=get_output_schema(product_type),
    #     is_hybrid=is_hybrid
    # )
    # 根据产品类型动态组装 Prompt 组件
    ↓ 拼接文档内容
    # full_prompt = f"{prompt}\n\n文档内容:\n{document.content[:15000]}"
    ↓ LLM 调用
    # response = llm_client.generate(full_prompt, max_tokens=6000, temperature=0.1)
    ↓ parse_llm_json_response(response)
    # 统一解析策略
    ↓ 专用提取器 (按需)
    # if 'premium_table' in required_fields and profile.has_premium_table:
    #     result['premium_table'] = PremiumTableExtractor.extract(document.content)
    # if 'clauses' in required_fields:
    #     result['clauses'] = ClauseExtractor.extract(document.content)
    ↓ 构建 ExtractResult
    # data = result
    # confidence = {k: 0.75 for k in result}
    # provenance = {k: 'dynamic_llm' for k in result}
    # metadata = {
    #     'extraction_mode': 'dynamic',
    #     'product_type': product_type,
    #     'is_hybrid': is_hybrid
    # }
```

**输出**: `ExtractResult`

### 2.5 阶段 4: 结果验证

**输入**: `ExtractResult`

**处理流程**:

```python
# ResultValidator.validate(result)
result = ExtractResult
    ↓ 必需字段检查
    # missing = REQUIRED_FIELDS - set(result.data.keys())
    # if missing: errors.append(f"缺失必需字段: {missing}")
    ↓ 数据类型检查
    # for field in ['premium_rate', 'age_min', ...]:
    #     if field in data and not valid_type(data[field]):
    #         errors.append(f"{field} 格式错误")
    ↓ 业务规则检查
    # for rule in BUSINESS_RULES:
    #     if not rule.check(data):
    #         errors.append(rule.error_message)
    ↓ 置信度检查
    # low_confidence = [k for k, v in result.confidence.items() if v < 0.7]
    # if low_confidence: warnings.append(f"低置信度字段: {low_confidence}")
    ↓ 计算分数
    # score = 100 - error_count * 20 - warning_count * 5
```

**输出**: `ValidationResult`

### 2.6 阶段 5: 元数据添加

**输入**: `ExtractResult, ValidationResult, extractor`

**处理流程**:

```python
# DocumentExtractor.extract() 最后步骤
result.metadata.update({
    'extraction_mode': 'fast' if isinstance(extractor, FastExtractor) else 'dynamic',
    'validation_score': validation.score,
    'validation_errors': validation.errors,
    'validation_warnings': validation.warnings
})
```

**输出**: 最终 `ExtractResult` (包含完整元数据)

---

## 三、核心数据结构详解

### 3.1 DocumentProfile (文档画像)

用于路由决策的文档特征，在 `Normalizer._detect_format()` 中生成：

```python
@dataclass
class DocumentProfile:
    is_structured: bool          # 章节数 ≥ 5
    has_clause_numbers: bool     # 存在 "第X条" 模式
    has_premium_table: bool      # 存在 "年龄.*费率" 模式
```

**用途**:
- `is_structured` + `has_clause_numbers` → 判断文档格式复杂度
- `has_premium_table` → 决定是否调用 `PremiumTableExtractor`

### 3.2 StructureMarkers (结构标记)

记录文档中关键结构的位置索引：

```python
@dataclass
class StructureMarkers:
    clause_positions: List[int]    # [123, 456, 789, ...]
    table_positions: List[int]     # [100, 200, ...]
    section_positions: List[int]   # [10, 50, 100, ...]
```

**当前用途**: 主要用于调试和未来扩展

### 3.3 ExtractResult (提取结果)

核心数据结构，包含提取的所有信息：

```python
@dataclass
class ExtractResult:
    data: Dict[str, Any]              # 提取的字段值
    confidence: Dict[str, float]       # 每个字段的置信度
    provenance: Dict[str, str]         # 每个字段的来源标识
    metadata: Dict[str, Any]           # 提取过程元数据
```

**字段来源 (provenance)**:
- `'fast_llm'` - Fast 车道 LLM 提取
- `'regex'` - Fast 车道正则补充
- `'dynamic_llm'` - Dynamic 车道 LLM 提取
- `'specialized_extractor'` - 专用提取器 (费率表/条款)

### 3.4 ValidationResult (验证结果)

```python
@dataclass
class ValidationResult:
    is_valid: bool               # 是否通过验证
    errors: List[str]            # 致命错误列表
    warnings: List[str]          # 警告列表
    score: int                   # 0-100 分数
```

**计分规则**:
- 基础分: 100
- 每个错误: -20
- 每个警告: -5

---

## 四、关键决策点数据流

### 4.1 路由决策 (ExtractorSelector)

```
NormalizedDocument
    │
    ├─→ profile.is_structured ──────┐
    ├─→ profile.has_clause_numbers ─┤
    ├─→ content (前2000字符) ────────┤──→ _use_dynamic() ─→ bool
    │                                │
    └─→ ProductClassifier.classify()─┘
           │
           └─→ (type_code, confidence)
                  │
                  └─→ confidence < 0.7 ──┘
```

**决策结果**:
- `True` → `DynamicExtractor`
- `False` → `FastExtractor`

### 4.2 产品分类决策 (ProductClassifier)

```
document.content
    │
    ├─→ PRODUCT_TYPES 遍历
    │     │
    │     └─→ ProductType.match_score()
    │           │
    │           ├─→ pattern 匹配 (关键词)
    │           └─→ feature 匹配 (特征)
    │                 │
    │                 └─→ score (累加)
    │
    └─→ filter(score >= threshold)
          │
          └─→ sort(descending)
                │
                └─→ [(type_code, score), ...]
```

**输出**: `List[Tuple[str, float]]` 按置信度降序

### 4.3 JSON 解析决策 (parse_llm_json_response)

```
LLM 响应 (str)
    │
    ├─→ 策略1: re.search(r'```json\s*(.*?)\s*```')
    │     └─→ 匹配成功? ─→ 返回解析结果
    │           │
    │           └─→ 失败 ─→
    │                     │
    ├─→ 策略2: response.strip().startswith('{') and endswith('}')
    │     └─→ 匹配成功? ─→ 返回解析结果
    │           │
    │           └─→ 失败 ─→
    │                     │
    ├─→ 策略3: 查找最外层 {...} 对
    │     └─→ 找到? ─→ 返回解析结果
    │           │
    │           └─→ 失败 ─→
    │                     │
    └─→ 策略4: strict=True? ─→ 抛 ValueError
          └─→ strict=False? ─→ 返回 default={}
```

---

## 五、数据流图总结

### 5.1 数据转换链

```
str (原始文档)
  → NormalizedDocument (规范化 + 画像)
    → FastExtractor | DynamicExtractor (选择决策)
      → parse_llm_json_response (LLM 响应解析)
        → ExtractResult (提取结果)
          → ValidationResult (验证结果)
            → ExtractResult (添加元数据)
```

### 5.2 关键数据依赖

| 阶段 | 输入数据 | 依赖的字段 |
|------|----------|------------|
| 规范化 | `str` | 全部原始内容 |
| 选择器 | `NormalizedDocument` | `content`, `profile` |
| Fast 提取 | `NormalizedDocument` | `content[:1500]` |
| Dynamic 提取 | `NormalizedDocument` | `content`, `profile` |
| 验证 | `ExtractResult` | `data`, `confidence` |

### 5.3 数据传递方式

1. **直接传递**: `NormalizedDocument` 在各组件间直接传递
2. **共享实例**: `ProductClassifier` 在 `ExtractorSelector` 和 `DynamicExtractor` 间共享
3. **常量引用**: `config` 常量在所有模块中引用

---

## 六、异常处理数据流

### 6.1 Fast 提取失败回退

```
FastExtractor.extract()
    │
    ├─→ LLM 调用成功 ─→ parse_llm_json_response()
    │                           │
    │                           ├─→ 成功 ─→ 返回 ExtractResult
    │                           └─→ 失败 ─→ 抛 FastExtractionFailed
    │
    └─→ 抛出 FastExtractionFailed
          │
          └─→ DocumentExtractor 捕获
                │
                └─→ 回退到 DynamicExtractor.extract()
```

### 6.2 LLM 调用超时

```
LLM 调用 (timeout=120s)
    │
    ├─→ 正常响应 ─→ 继续处理
    │
    └─→ 超时异常
          │
          ├─→ FastExtractor: 抛 FastExtractionFailed → 回退
          └─→ DynamicExtractor: logger.error() → 返回空 result = {}
```

---

**文档版本**: v4.0
**最后更新**: 2025-03-12
