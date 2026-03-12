# 文档预处理模块系统架构 Review

> 日期: 2025-03-11
> 版本: v3.0 (最新重构)
> 总代码量: ~1590 行 (12 个文件)

---

## 一、系统概述

### 1.1 设计目标

统一保险产品文档的预处理框架，根据文档特征自动选择最优提取策略，平衡成本与质量。

### 1.2 核心特性

- **双车道架构**: Fast 车道 (80% 文档) + Dynamic 车道 (20% 复杂文档)
- **智能路由**: 基于文档画像自动选择提取器
- **产品类型识别**: 7 种产品类型 + 混合产品支持
- **组件化 Prompt**: 11 个可复用组件，按产品类型动态组合

---

## 二、系统流程

### 2.1 完整数据流

```
原始文档 (str)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  DocumentExtractor.extract()                             │
│  主入口：编排整个提取流程                                  │
└────────────┬─────────────────────────────────────────────┘
             │
    ┌────────▼─────────┐
    │  1. Normalizer  │
    │  文档规范化       │
    └────────┬─────────┘
             │
             ▼ NormalizedDocument
    ┌──────────────────────────────────────────────────────┐
    │ content: str                                          │
    │ profile: DocumentProfile                             │
    │   - is_structured: bool                              │
    │   - has_clause_numbers: bool                         │
    │   - has_premium_table: bool                          │
    │ structure_markers: StructureMarkers                 │
    │ metadata: Dict                                       │
    └──────────────────────────────────────────────────────┘
             │
    ┌────────▼─────────────────┐
    │  2. ExtractorSelector    │
    │  提取器选择               │
    └────────┬─────────────────┘
             │
             ▼ extractor: FastExtractor | DynamicExtractor
    ┌──────────────────────────────────────────────────────┐
    │  3a. FastExtractor          │  3b. DynamicExtractor    │
    │  - Few-shot Prompt          │  - 产品类型专用 Prompt    │
    │  - 1500 字符输入            │  - 15000 字符输入        │
    │  - 1500 tokens 输出         │  - 6000 tokens 输出       │
    │  - Regex 补充提取           │  - 专用提取器            │
    │  - 成本 ~0.003 元/次        │  - 成本 ~0.05 元/次      │
    └───────────┬──────────────────┴──────────────────────────┘
                │
                ▼ ExtractResult
    ┌──────────────────────────────────────────────────────┐
    │ data: Dict[str, Any]                                 │
    │ confidence: Dict[str, float]                         │
    │ provenance: Dict[str, str]                           │
    │ metadata: Dict[str, Any]                             │
    └──────────────────────────────────────────────────────┘
                │
    ┌───────────▼─────────────────┐
    │  4. ResultValidator         │
    │  结果验证                   │
    └───────────┬─────────────────┘
                │
                ▼ ValidationResult
    ┌──────────────────────────────────────────────────────┐
    │ is_valid: bool                                       │
    │ errors: List[str]                                    │
    │ warnings: List[str]                                  │
    │ score: int (0-100)                                   │
    └──────────────────────────────────────────────────────┘
                │
                ▼
        添加元数据 → 返回结果
```

---

## 三、提取器选择机制

### 3.1 ExtractorSelector 职责

`ExtractorSelector` 是系统的"大脑"，负责根据文档特征选择合适的提取器。

### 3.2 决策输入

| 输入源 | 数据 | 用途 |
|--------|------|------|
| `document.profile` | 文档画像 | 判断文档复杂度 |
| `document.content` | 文档内容 | 产品分类、位置检查 |
| `ProductTypeClassifier` | 分类器 | 获取产品类型和置信度 |

### 3.3 决策规则 (三重判断)

```python
def _use_dynamic(profile, confidence, document) -> bool:
    # 条件1: 格式复杂
    is_complex = not profile.is_structured or not profile.has_clause_numbers

    # 条件2: 低置信度
    is_low_confidence = confidence < 0.7

    # 条件3: 关键信息靠后
    has_key_info_back = not self._check_key_info_position(document)

    return is_complex or is_low_confidence or has_key_info_back
```

**满足任一条件 → 走 Dynamic 车道**

### 3.4 决策输出

```python
def select(document: NormalizedDocument) -> Union[FastExtractor, DynamicExtractor]:
    """
    Returns:
        提取器实例
    """
```

**设计亮点**:
- 接口极简：只返回提取器实例
- 职责内聚：提取器自己通过 `classifier` 获取产品类型信息
- 无冗余返回值：不再返回 `product_type`, `confidence`, `is_hybrid`

---

## 四、代码结构

### 4.1 文件组织

```
lib/preprocessing/
├── __init__.py              # 模块入口，导出公共 API
├── models.py                # 数据模型 (120 行)
├── document_extractor.py    # 主入口，流程编排 (108 行)
├── normalizer.py            # 文档规范化 (149 行)
├── extractor_selector.py    # 提取器选择器 (125 行)
├── classifier.py            # 产品类型分类器 (72 行)
├── fast_extractor.py        # 快速提取器 (160 行)
├── dynamic_extractor.py     # 动态提取器 (227 行)
├── prompt_builder.py        # Prompt 构建器 (224 行)
├── product_types.py         # 产品类型定义 (198 行)
└── validator.py             # 结果验证器 (134 行)
```

### 4.2 模块依赖关系

```
                    ┌──────────────────┐
                    │ DocumentExtractor│
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌──────────────────┐  ┌──────────────┐
│   Normalizer  │  │ ExtractorSelector│  │   Validator  │
└───────────────┘  └────────┬─────────┘  └──────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
        ┌───────▼────────┐      ┌────────▼────────┐
        │  ProductType   │      │ ExtractorPool   │
        │  Classifier    │      │  (Fast+Dynamic) │
        └────────────────┘      └─────────────────┘
                │                         │
                ▼                         ▼
        ┌───────────────┐      ┌──────────────────┐
        │ product_types │      │ prompt_builder   │
        └───────────────┘      └──────────────────┘
```

### 4.3 耦合度分析

| 组件 | 依赖 | 被依赖 | 耦合度 |
|------|------|--------|--------|
| `models.py` | 无 | 所有模块 | ✅ 无 |
| `normalizer.py` | `models` | `DocumentExtractor` | ✅ 低 |
| `classifier.py` | `models`, `product_types` | `ExtractorSelector`, `DynamicExtractor` | ✅ 低 |
| `extractor_selector.py` | `models`, `classifier`, 提取器 | `DocumentExtractor` | ⚠️ 中 (持有提取器) |
| `fast_extractor.py` | `models` | `ExtractorSelector` | ✅ 低 |
| `dynamic_extractor.py` | `models`, `classifier`, `prompt_builder`, `product_types` | `ExtractorSelector` | ✅ 低 |
| `validator.py` | `models`, `extractor_selector` | `DocumentExtractor` | ⚠️ 中 (依赖 ExtractorSelector 常量) |
| `document_extractor.py` | 所有模块 | 外部调用 | ✅ 低 (编排层) |

**唯一的中度耦合**:
- `ExtractorSelector` 需要持有提取器实例
- `validator` 依赖 `ExtractorSelector.REQUIRED_FIELDS`（可优化）

---

## 五、数据模型

### 5.1 核心数据类

```python
# 文档画像：提取器选择用
@dataclass
class DocumentProfile:
    is_structured: bool       # 有章节结构
    has_clause_numbers: bool  # 有条款编号
    has_premium_table: bool   # 有费率表

# 规范化文档
@dataclass
class NormalizedDocument:
    content: str
    profile: DocumentProfile
    structure_markers: StructureMarkers
    metadata: Dict[str, Any]

# 提取结果
@dataclass
class ExtractResult:
    data: Dict[str, Any]
    confidence: Dict[str, float]
    provenance: Dict[str, str]
    metadata: Dict[str, Any]
```

### 5.2 数据流转换

```
str (原始文档)
    → NormalizedDocument (规范化)
    → Extractor (选择决策)
    → ExtractResult (提取结果)
    → ValidationResult (验证结果)
```

---

## 六、双车道设计

### 6.1 Fast 车道

| 特性 | 值 |
|------|-----|
| Prompt | 固定 Few-shot |
| 输入长度 | 1500 字符 |
| 输出长度 | 1500 tokens |
| 成本 | ~0.003 元/次 |
| 适用场景 | 结构化、短文档、高置信度 |
| Fallback | Regex 补充提取 |

### 6.2 Dynamic 车道

| 特性 | 值 |
|------|-----|
| Prompt | 按产品类型动态生成 |
| 输入长度 | 15000 字符 |
| 输出长度 | 6000 tokens |
| 成本 | ~0.05 元/次 |
| 适用场景 | 复杂、长文档、低置信度 |
| 专用提取器 | `PremiumTableExtractor`, `ClauseExtractor` |
| 依赖注入 | 接收 `ProductTypeClassifier` |

### 6.3 成本对比

```
Fast:  ~0.003 元/次  ×  80%  = 0.0024 元/文档
Dynamic: ~0.05 元/次  ×  20%  = 0.01 元/文档
────────────────────────────────────
平均成本: ~0.0124 元/文档

如果全部走 Dynamic: 0.05 元/文档
节省: ~75%
```

---

## 七、产品类型分类

### 7.1 支持的产品类型

| 代码 | 名称 | 关键特征 |
|------|------|----------|
| `critical_illness` | 重大疾病险 | 病种清单、分级 |
| `medical_insurance` | 医疗保险 | 免赔额、赔付比例 |
| `universal_life` | 万能险 | 保单账户、结算利率 |
| `term_life` | 定期寿险 | 保险期间、身故保险金 |
| `whole_life` | 终身寿险 | 现金价值 |
| `annuity` | 年金保险 | 年金领取方式 |
| `accident_insurance` | 意外伤害保险 | 意险范围 |
| `life_insurance` | 人身保险 (默认) | 基础信息 |

### 7.2 分类机制

```python
# 多标签分类 + 主导类型选择
def classify(document) -> List[Tuple[code, score]]:
    scores = [(code, match_score(document)) for code in types]
    return filter(scores >= threshold)

def get_primary_type(document) -> Tuple[code, confidence]:
    return classify(document)[0]  # 取最高分
```

### 7.3 混合产品识别

```python
def is_hybrid_product(document) -> bool:
    classifications = classify(document)
    # 第二高分 > 0.5 认为是混合产品
    return len(classifications) > 1 and classifications[1][1] > 0.5
```

---

## 八、Prompt 工程组件化

### 8.1 组件库设计

```python
COMPONENTS = {
    # 角色定义
    'role_base': "...",
    'role_specialized': "...",  # 包含 {product_type}, {extraction_focus}

    # 字段说明 (按产品类型)
    'field_product_info': "...",
    'field_diseases': "...",        # 重疾险专用
    'field_coverage': "...",        # 医疗险专用
    'field_account': "...",         # 万能险专用
    # ... 共 11 个组件

    # 输出格式
    'output_structure': "...",

    # 特殊说明
    'hybrid_notice': "...",
}
```

### 8.2 动态组装逻辑

```python
def build(product_type, required_fields, extraction_focus, output_schema, is_hybrid):
    # 1. 角色定义
    prompt = COMPONENTS['role_specialized'] if extraction_focus else role_base

    # 2. 字段说明 (按需添加)
    for component in _get_field_components(required_fields):
        prompt += COMPONENTS[component]

    # 3. 混合产品特殊说明
    if is_hybrid:
        prompt += COMPONENTS['hybrid_notice']

    # 4. 输出格式
    prompt += COMPONENTS['output_structure']

    return prompt
```

---

## 九、接口设计对比

### 9.1 ExtractorSelector 演进

| 版本 | 方法签名 | 返回值 | 评价 |
|------|----------|--------|------|
| v1.0 | `select_route(doc) → ExtractionRoute` | 包含 mode, product_type, confidence, reason | 抽象，暴露内部实现 |
| v2.0 | `select_extractor(doc) → Tuple[Extractor, str, float, bool]` | 4 个值的元组 | 直接但冗余 |
| v3.0 | `select(doc) → Extractor` | 单一提取器实例 | ✅ 简洁、职责内聚 |

### 9.2 DynamicExtractor 演进

| 版本 | 方法签名 | 数据来源 |
|------|----------|----------|
| v2.0 | `extract(doc, product_type, is_hybrid, fields)` | 调用方传入 |
| v3.0 | `extract(doc, fields)` | 内部通过 `classifier` 获取 |

---

## 十、潜在问题与改进建议

### 10.1 发现的问题

| 问题 | 严重性 | 说明 |
|------|--------|------|
| `validator` 依赖 `ExtractorSelector` | P3 | 循环依赖风险，`REQUIRED_FIELDS` 应该独立配置 |
| `ExtractorSelector` 持有提取器实例 | P3 | 增加耦合，但换取了接口简洁度 |
| 魔法数字散落各处 | P2 | 0.7 置信度、2000 字符、75% 覆盖率等应集中配置 |
| `_check_key_info_position` 重复扫描 | P2 | 已在前 2000 字符扫描，但 `field_indicators` 可能遗漏模式 |

### 10.2 改进建议

**1. 抽取配置类**

```python
@dataclass
class ExtractionConfig:
    # 路由阈值
    DYNAMIC_CONFIDENCE_THRESHOLD = 0.7
    KEY_INFO_POSITION_LIMIT = 2000
    KEY_INFO_COVERAGE_RATIO = 0.75

    # Fast 车道
    FAST_INPUT_LIMIT = 1500
    FAST_OUTPUT_LIMIT = 1500

    # Dynamic 车道
    DYNAMIC_INPUT_LIMIT = 15000
    DYNAMIC_OUTPUT_LIMIT = 6000
```

**2. 解耦 `validator`**

```python
# 将 REQUIRED_FIELDS 移到 config 或独立模块
class RequiredFields:
    CORE_FIELDS = {
        'product_name',
        'insurance_company',
        'insurance_period',
        'waiting_period'
    }
```

**3. 统一响应解析**

```python
class ResponseParser:
    """统一的 LLM 响应解析器"""

    @staticmethod
    def parse_json(response: str) -> Dict:
        # 合并 FastExtractor、DynamicExtractor、PremiumTableExtractor
        # 中的重复解析逻辑
```

---

## 十一、架构亮点

### 11.1 设计模式应用

| 模式 | 应用位置 | 效果 |
|------|----------|------|
| **策略模式** | Fast/Dynamic 提取器 | 可替换的提取策略 |
| **建造者模式** | `PromptBuilder` | 灵活组装 Prompt |
| **门面模式** | `DocumentExtractor` | 简化外部调用 |
| **依赖注入** | `DynamicExtractor(classifier)` | 解耦产品类型获取 |

### 11.2 代码质量

| 指标 | 评价 |
|------|------|
| **可读性** | ⭐⭐⭐⭐⭐ 命名清晰，职责单一 |
| **可维护性** | ⭐⭐⭐⭐ 组件化设计，易于扩展 |
| **可测试性** | ⭐⭐⭐⭐⭐ 依赖注入，易于 mock |
| **性能** | ⭐⭐⭐⭐ 成本优化设计，75% 节省 |

### 11.3 最佳实践

1. **单一职责**: 每个类职责明确
2. **依赖注入**: 提取器通过构造函数注入依赖
3. **接口极简**: `ExtractorSelector.select()` 只返回提取器实例
4. **职责内聚**: 提取器自己获取需要的产品类型信息
5. **防御性编程**: Fast 提取失败有回退机制
6. **日志完备**: 关键决策点有日志记录

---

## 十二、总结

### 12.1 当前架构状态

经过最新重构后的预处理模块具有以下特点：

1. **接口极简**: `ExtractorSelector.select()` 只返回提取器实例
2. **职责内聚**: 提取器自己通过 `classifier` 获取产品类型信息
3. **命名准确**: `ExtractorSelector` 比 `RouteSelector` 更准确描述职责
4. **无冗余**: 删除了 `ExtractionStrategy`、`DecisionDiagnostics`、`StructureInfo` 等中间类
5. **数据流清晰**: 每个阶段的输入输出都有明确的类型定义

### 12.2 适用场景

- ✅ 保险产品文档结构化提取
- ✅ 多源文档统一处理（PDF/HTML/Text）
- ✅ 成本敏感的大规模提取任务
- ✅ 需要产品类型分类的场景

### 12.3 扩展方向

1. **新增产品类型**: 在 `product_types.py` 中添加定义
2. **新增专用提取器**: 参考 `PremiumTableExtractor` 实现
3. **调整路由规则**: 修改 `ExtractorSelector._use_dynamic()`
4. **优化 Prompt 组件**: 在 `PromptBuilder.COMPONENTS` 中添加

---

**Review 结论**: 当前架构设计合理，代码质量高，无重大技术债务，可投入生产使用。
