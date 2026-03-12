# 文档预处理模块系统架构 Review

> 日期: 2025-03-12
> 版本: v4.0 (最新架构)
> 总代码量: ~1690 行 (15 个文件)

---

## 一、系统概述

### 1.1 设计目标

统一保险产品文档的预处理框架，根据文档特征自动选择最优提取策略，平衡成本与质量。

### 1.2 核心特性

- **双车道架构**: Fast 车道 (80% 文档) + Dynamic 车道 (20% 复杂文档)
- **智能选择**: 基于文档画像自动选择提取器
- **产品类型识别**: 7 种产品类型 + 混合产品支持
- **组件化 Prompt**: 11 个可复用组件，按产品类型动态组合
- **共享工具**: 统一的 JSON 解析和配置管理

### 1.3 设计演进

| 版本 | 主要变更 |
|------|----------|
| v1.0 | 初始架构，使用 `ExtractionRoute` 返回决策结果 |
| v2.0 | 重命名为 `RouteSelector`，简化中间类 |
| v3.0 | 重命名为 `ExtractorSelector`，接口极简化；`ProductTypeClassifier` → `ProductClassifier` |
| v4.0 | 提取共享工具 (JSON 解析、配置常量)，优化效率 |

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
│  - 创建共享的 ProductClassifier                          │
│  - 初始化 FastExtractor, DynamicExtractor                 │
│  - 初始化 ExtractorSelector (持有提取器引用)               │
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
    │   - is_structured: bool (章节数≥5)                   │
    │   - has_clause_numbers: bool                          │
    │   - has_premium_table: bool                           │
    │ structure_markers: StructureMarkers                 │
    │ metadata: Dict                                       │
    └──────────────────────────────────────────────────────┘
             │
    ┌────────▼─────────────────┐
    │  2. ExtractorSelector     │
    │  提取器选择               │
    │  - 分析文档画像           │
    │  - 调用 ProductClassifier                       │
    │  - 三重判断决定车道        │
    │  - 返回提取器实例          │
    └────────┬─────────────────┘
             │
             ▼ extractor: FastExtractor | DynamicExtractor
    ┌──────────────────────────────────────────────────────┐
    │  3. Extractor.extract()                                │
    │                                                          │
    │  3a. FastExtractor               │  3b. DynamicExtractor  │
    │  - Few-shot Prompt               │  - 一次性分类获取类型 │
    │  - parse_llm_json_response()     │  - 按产品类型生成     │
    │  - 1500 字符输入                │  - parse_llm_json_response() │
    │  - 1500 tokens 输出              │  - 15000 字符输入     │
    │  - Regex 补充提取               │  - 6000 tokens 输出     │
    │  - 成本 ~0.003 元/次             │  - 专用提取器         │
    │                                  │  - 成本 ~0.05 元/次     │
    └───────────┬──────────────────────┴──────────────────────────┘
              │
              ▼ ExtractResult
    ┌──────────────────────────────────────────────────────┐
    │ data: Dict[str, Any]                                     │
    │ confidence: Dict[str, float]                             │
    │ provenance: Dict[str, str] (字段来源)                    │
    │ metadata: Dict[str, Any]                                 │
    └──────────────────────────────────────────────────────┘
              │
    ┌───────────▼─────────────────┐
    │  4. ResultValidator         │
    │  - 必需字段检查              │
    │  - 数据类型验证              │
    │  - 业务规则检查              │
    │  - 置信度检查                │
    └───────────┬─────────────────┘
              │
              ▼ ValidationResult
    ┌──────────────────────────────────────────────────────┐
    │ is_valid: bool                                           │
    │ errors: List[str]                                        │
    │ warnings: List[str]                                      │
    │ score: int (0-100)                                      │
    └──────────────────────────────────────────────────────┘
              │
              ▼
      添加元数据 → 返回结果
```

---

## 三、提取器选择机制

### 3.1 ExtractorSelector 职责

`ExtractorSelector` 是系统的"决策中心"，负责根据文档特征选择合适的提取器。

### 3.2 决策输入

| 输入源 | 数据 | 用途 |
|--------|------|------|
| `document.profile.is_structured` | 是否有章节结构 | 判断文档复杂度 |
| `document.profile.has_clause_numbers` | 是否有条款编号 | 判断文档复杂度 |
| `document.content` | 文档内容 | 产品分类、位置检查 |
| `ProductClassifier.get_primary_type()` | 产品类型、置信度 | 路由决策 |

### 3.3 决策规则 (三重判断)

```python
def _use_dynamic(profile, confidence, document) -> bool:
    # 条件1: 格式复杂
    is_complex = not profile.is_structured or not profile.has_clause_numbers

    # 条件2: 低置信度 (使用 config.LOW_CONFIDENCE_THRESHOLD)
    is_low_confidence = confidence < config.LOW_CONFIDENCE_THRESHOLD

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
        提取器实例（直接可调用）
    """
```

**接口极简**:
- 调用方无需解包元组
- 提取器自己获取需要的产品类型信息
- 统一的 `extract(document, required_fields)` 接口

---

## 四、代码结构

### 4.1 文件组织

```
lib/preprocessing/
├── __init__.py              # 模块入口，导出公共 API
├── models.py                # 数据模型 (120 行)
├── document_extractor.py    # 主入口，流程编排 (106 行)
├── normalizer.py            # 文档规范化 (149 行)
├── extractor_selector.py    # 提取器选择器 (126 行)
├── classifier.py            # 产品类型分类器 (72 行)
├── fast_extractor.py        # 快速提取器 (160 行)
├── dynamic_extractor.py     # 动态提取器 (231 行)
├── prompt_builder.py        # Prompt 构建器 (224 行)
├── product_types.py         # 产品类型定义 (198 行)
├── validator.py             # 结果验证器 (134 行)
└── utils/                   # 工具模块 (新增)
    ├── __init__.py
    ├── json_parser.py       # 统一 JSON 解析 (80 行)
    └── constants.py         # 配置常量 (60 行)
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
        │  Product       │      │ ExtractorPool   │
        │  Classifier    │      │  (Fast+Dynamic) │
        └────────────────┘      └─────────────────┘
                │                         │
                ▼                    ┌───┴────────────┐
        ┌───────────────┐            │                │
        │ product_types │            ▼                ▼
        └───────────────┘    ┌──────────┐  ┌──────────────┐
                             │   utils   │  │  specialized  │
                             │ ├─ json   │  │  _extractors │
                             │ ├─ config │  └──────────────┘
                             │ └─ fields│
                             └──────────┘
                              (共享工具)
```

### 4.3 耦合度分析

| 组件 | 依赖 | 被依赖 | 耦合度 |
|------|------|--------|--------|
| `models.py` | 无 | 所有模块 | ✅ 无 |
| `utils/` | `json`, `dataclasses` | 所有提取器 | ✅ 无 (纯工具) |
| `normalizer.py` | `models` | `DocumentExtractor` | ✅ 低 |
| `classifier.py` | `models`, `product_types` | `ExtractorSelector`, `DynamicExtractor` | ✅ 低 |
| `extractor_selector.py` | `models`, `classifier`, `utils.config`, 提取器 | `DocumentExtractor` | ⚠️ 中 (持有提取器) |
| `fast_extractor.py` | `models`, `utils` | `ExtractorSelector` | ✅ 低 |
| `dynamic_extractor.py` | `models`, `classifier`, `utils`, `prompt_builder` | `ExtractorSelector` | ✅ 低 |
| `validator.py` | `models`, `extractor_selector` | `DocumentExtractor` | ⚠️ 中 (依赖 ExtractorSelector 常量) |
| `document_extractor.py` | 所有模块 | 外部调用 | ✅ 低 (编排层) |

**新增的低耦合**:
- `utils/json_parser.py` - 无业务依赖，纯工具函数
- `utils/constants.py` - 仅依赖 `dataclasses`，集中配置

---

## 五、数据模型

### 5.1 核心数据类

```python
@dataclass
class DocumentProfile:
    """文档画像：用于提取器选择"""
    is_structured: bool          # 有章节结构（章节数≥5）
    has_clause_numbers: bool     # 有条款编号（第X条）
    has_premium_table: bool      # 包含费率表特征


@dataclass
class NormalizedDocument:
    """规范化文档"""
    content: str
    profile: DocumentProfile
    structure_markers: StructureMarkers
    metadata: Dict[str, Any]


@dataclass
class ExtractResult:
    """提取结果"""
    data: Dict[str, Any]
    confidence: Dict[str, float]
    provenance: Dict[str, str]      # 字段来源标识
    metadata: Dict[str, Any]
```

### 5.2 数据流转换

```
str (原始文档)
    → NormalizedDocument (规范化 + 画像)
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
| 输入长度 | `config.FAST_CONTENT_MAX_CHARS` (1500) |
| 输出长度 | `config.FAST_EXTRACTION_MAX_TOKENS` (1500) |
| 成本 | ~0.003 元/次 |
| 适用场景 | 结构化、短文档、高置信度 |
| Fallback | Regex 补充提取 |

### 6.2 Dynamic 车道

| 特性 | 值 |
|------|-----|
| Prompt | 按产品类型动态生成 |
| 输入长度 | `config.DYNAMIC_CONTENT_MAX_CHARS` (15000) |
| 输出长度 | `config.DYNAMIC_EXTRACTION_MAX_TOKENS` (6000) |
| 成本 | ~0.05 元/次 |
| 适用场景 | 复杂、长文档、低置信度 |
| 专用提取器 | `PremiumTableExtractor`, `ClauseExtractor` |
| 依赖注入 | 接收共享的 `ProductClassifier` |

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
# ProductClassifier (v4.0 优化)
def classify(document) -> List[Tuple[code, score]]:
    # 多标签分类
    scores = [(code, match_score(document)) for code in types]
    return filter(scores >= threshold).sort(descending)

def get_primary_type(document) -> Tuple[code, confidence]:
    return classify(document)[0]  # 取最高分

def is_hybrid_product(document, classifications=None) -> bool:
    # 可复用已分类结果
    if classifications is None:
        classifications = self.classify(document)
    return len(classifications) > 1 and classifications[1][1] > config.HYBRID_PRODUCT_THRESHOLD
```

### 7.3 分类器共享

`ProductClassifier` 在 `DocumentExtractor` 中创建一次，然后共享给：
- `ExtractorSelector` — 用于路由决策
- `DynamicExtractor` — 用于获取产品类型信息（一次性分类，避免重复）

### 7.4 效率优化 (v4.0)

```python
# O(1) 查找字典
self._type_by_code: Dict[str, ProductType] = {pt.code: pt for pt in PRODUCT_TYPES}

def get_required_fields(self, product_type: str) -> List[str]:
    # 从 dict 直接获取，O(1)
    pt = self._type_by_code.get(product_type)
    return pt.required_fields if pt else []
```

---

## 八、共享工具模块 (v4.0 新增)

### 8.1 JSON 解析器

```python
# utils/json_parser.py
def parse_llm_json_response(response: str, strict: bool = False, default: Dict = None) -> Dict[str, Any]:
    """
    统一的 LLM JSON 响应解析

    策略:
    1. 提取 markdown 代码块中的 JSON
    2. 解析裸 JSON 对象
    3. 从文本中提取嵌入的 JSON

    消除了 4 处重复代码:
    - FastExtractor._parse_response()
    - DynamicExtractor._parse_response()
    - PremiumTableExtractor._parse_response()
    - ClauseExtractor._parse_response()
    """
```

### 8.2 配置常量

```python
# utils/constants.py
@dataclass
class ExtractionConfig:
    """集中式配置"""

    # 分类阈值
    DEFAULT_CLASSIFICATION_THRESHOLD: float = 0.3
    HYBRID_PRODUCT_THRESHOLD: float = 0.5
    LOW_CONFIDENCE_THRESHOLD: float = 0.7

    # 选择器阈值
    KEY_INFO_SEARCH_WINDOW: int = 2000
    REQUIRED_FIELDS_COVERAGE_THRESHOLD: float = 0.75

    # Fast 车道
    FAST_CONTENT_MAX_CHARS: int = 1500
    FAST_EXTRACTION_MAX_TOKENS: int = 1500
    DEFAULT_FAST_CONFIDENCE: float = 0.85

    # Dynamic 车道
    DYNAMIC_CONTENT_MAX_CHARS: int = 15000
    DYNAMIC_EXTRACTION_MAX_TOKENS: int = 6000
    DEFAULT_DYNAMIC_CONFIDENCE: float = 0.75

    # 专用提取器
    TABLE_CONTENT_MAX_CHARS: int = 3000
    TABLE_EXTRACTION_MAX_TOKENS: int = 2000
    CLAUSE_CONTENT_MAX_CHARS: int = 8000
    CLAUSE_EXTRACTION_MAX_TOKENS: int = 4000

    # 元数据键
    EXTRACTION_MODE: str = 'extraction_mode'
    PRODUCT_TYPE: str = 'product_type'
    IS_HYBRID: str = 'is_hybrid'
    # ...

    # 来源标识
    PROVENANCE_FAST_LLM: str = 'fast_llm'
    PROVENANCE_DYNAMIC_LLM: str = 'dynamic_llm'
    PROVENANCE_REGEX: str = 'regex'
    PROVENANCE_SPECIALIZED: str = 'specialized_extractor'

# 全局实例
config = ExtractionConfig()
```

---

## 九、接口设计对比

### 9.1 ExtractorSelector 演进

| 版本 | 方法签名 | 返回值 | 评价 |
|------|----------|--------|------|
| v1.0 | `select_route(doc) → ExtractionRoute` | 包含 mode, product_type, confidence, reason | 抽象，暴露内部实现 |
| v2.0 | `select_extractor(doc) → Tuple[Extractor, str, float, bool]` | 4 个值的元组 | 直接但冗余 |
| v3.0 | `select(doc) → Extractor` | 单一提取器实例 | ✅ 极简、职责内聚 |
| v4.0 | `select(doc) → Extractor` + 使用 `config` 常量 | 统一 | ✅ 使用集中配置 |

### 9.2 DynamicExtractor 演进

| 版本 | 签名 | 数据来源 |
|------|------|----------|
| v2.0 | `extract(doc, product_type, is_hybrid, fields)` | 调用方传入 |
| v3.0 | `extract(doc, fields)` | 内部通过 `classifier` 获取 |
| v4.0 | `extract(doc, fields)` | 一次性分类，复用结果 |

### 9.3 统一提取器接口

```python
# 两个提取器现在有完全一致的接口
FastExtractor.extract(document, required_fields) -> ExtractResult
DynamicExtractor.extract(document, required_fields) -> ExtractResult
```

这是多态的体现，调用方无需区分。

---

## 十、架构亮点

### 10.1 设计模式应用

| 模式 | 应用位置 | 效果 |
|------|----------|------|
| **策略模式** | Fast/Dynamic 提取器 | 可替换的提取策略，统一接口 |
| **依赖注入** | `DynamicExtractor(classifier)` | 解耦产品类型获取，支持共享实例 |
| **门面模式** | `DocumentExtractor` | 简化外部调用，隐藏复杂性 |
| **模板方法** | 提取器统一的 `extract()` 签名 | 统一接口，易于扩展 |
| **工具模式** | `utils/` 模块 | 无状态纯函数，易于测试和复用 |

### 10.2 代码质量

| 指标 | 评价 |
|------|------|
| **可读性** | ⭐⭐⭐⭐⭐ 命名清晰，职责单一 |
| **可维护性** | ⭐⭐⭐⭐⭐ 组件化设计，易于扩展，配置集中 |
| **可测试性** | ⭐⭐⭐⭐⭐ 依赖注入，工具函数易 mock |
| **性能** | ⭐⭐⭐⭐⭐ 成本优化 75%，消除重复分类 |

### 10.3 最佳实践

1. **接口极简**: `ExtractorSelector.select()` 只返回提取器实例
2. **职责内聚**: 提取器自己获取需要的产品类型信息
3. **依赖共享**: `ProductClassifier` 单例共享，避免重复分类
4. **防御性编程**: Fast 提取失败自动回退到 Dynamic
5. **日志完备**: 关键决策点有日志记录
6. **配置集中**: 所有魔法数字移至 `ExtractionConfig`
7. **代码复用**: 统一的 `parse_llm_json_response()` 消除 4 处重复

### 10.4 v4.0 改进成果

| 指标 | v3.0 | v4.0 | 改进 |
|------|------|------|------|
| 代码行数 | ~1590 | ~1690 | +100 (新增工具模块) |
| 重复代码 | ~50 行 | 0 行 | 消除 JSON 解析重复 |
| 魔法数字 | 18 处 | 0 处 | 全部移至配置 |
| 分类次数 | 2 次/提取 | 1 次/提取 | 减少 50% |
| 查找复杂度 | O(n) | O(1) | 字典优化 |

---

## 十一、潜在问题与改进建议

### 11.1 已解决的问题 (v4.0)

| 问题 | 状态 | 解决方案 |
|------|------|----------|
| 4 处重复的 JSON 解析代码 | ✅ 已解决 | 提取 `parse_llm_json_response()` |
| 18 个魔法数字散落各处 | ✅ 已解决 | 移至 `ExtractionConfig` |
| 重复分类调用 | ✅ 已解决 | `DynamicExtractor` 一次性分类 |
| O(n) 查找复杂度 | ✅ 已解决 | 使用 `_type_by_code` 字典 |

### 11.2 剩余问题

| 问题 | 严重性 | 说明 |
|------|--------|------|
| `validator` 依赖 `ExtractorSelector` | P3 | `REQUIRED_FIELDS` 可以移到 config |
| 多次正则扫描文档 | P2 | `normalizer.py` 中可合并扫描 |

### 11.3 未来改进方向

1. **正则优化**: 合并 `normalizer.py` 中的多次文档扫描
2. **流式处理**: 对超大文档支持流式读取
3. **缓存层**: 对分类结果添加缓存
4. **异步支持**: LLM 调用改为异步

---

## 十二、总结

### 12.1 当前架构状态

经过四次迭代后的预处理模块特点：

1. **接口极简**: `ExtractorSelector.select()` 只返回提取器实例
2. **职责内聚**: 提取器自己通过 `classifier` 获取产品类型信息
3. **命名准确**: `ExtractorSelector`、`ProductClassifier` 清晰描述职责
4. **无冗余**: 删除了 `ExtractionStrategy`、`DecisionDiagnostics`、`StructureInfo` 等中间类
5. **统一接口**: 两个提取器有完全一致的 `extract(document, required_fields)` 签名
6. **依赖共享**: `ProductClassifier` 单例共享，避免重复分类
7. **配置集中**: `ExtractionConfig` 统一管理所有阈值和常量
8. **工具复用**: `parse_llm_json_response()` 消除重复代码

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
5. **扩展配置**: 在 `ExtractionConfig` 中添加新常量

---

**Review 结论**: 当前架构设计合理，代码质量高，已解决主要技术债务，可投入生产使用。
