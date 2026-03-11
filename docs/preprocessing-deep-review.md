# 文档预处理模块 - 系统架构与代码实现深度Review

## 一、模块总览

### 1.1 目录结构

```
lib/preprocessing/
├── __init__.py                 # 模块入口，导出所有公共API
├── models.py                  # 核心数据模型定义 (150行)
├── product_types.py            # 产品类型配置 (198行)
├── document_normalizer.py     # 文档规范化处理 (155行)
├── classifier.py               # 产品类型分类器 (72行)
├── path_selector.py           # 路由选择器 (120行)
├── prompt_builder.py          # 动态Prompt构建器 (224行)
├── fast_extractor.py          # 快速通道提取器 (160行)
├── structured_extractor.py    # 结构化通道提取器 (271行)
├── validator.py                # 结果验证器 (134行)
└── extractor.py               # 主入口提取器 (107行)

总计: ~1800行代码，11个文件
```

### 1.2 设计理念

| 原则 | 实现方式 |
|------|---------|
| **单一职责** | 每个类专注单一功能，可独立测试和替换 |
| **开闭原则** | 通过配置（product_types.py）扩展新产品类型，无需修改核心代码 |
| **依赖注入** | LLM客户端通过构造函数注入，便于测试和替换 |
| **数据驱动** | 产品类型、提取重点、Schema模板全部配置化 |
| **容错降级** | 快速通道失败自动回退到结构化通道 |

---

## 二、数据流分析

### 2.1 完整数据流图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        原始文档输入                                  │
│                   document: str, source_type: str                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  第1步: 文档规范化 (DocumentNormalizer.normalize)                   │
├─────────────────────────────────────────────────────────────────────┤
│  输入: document: str, source_type: str                              │
│  输出: NormalizedDocument {                                         │
│           content: str,                    # 规范化后内容             │
│           format_info: FormatInfo,         # 格式检测信息           │
│           structure_markers: StructureMarkers, # 结构位置标记         │
│           metadata: Dict                   # 原始长度/来源类型等      │
│       }                                                               │
│                                                                     │
│  内部流程:                                                            │
│  1. _normalize_encoding()    → 统一编码、换行符、移除控制字符      │
│  2. _remove_noise()         → 按source_type去除特定噪声            │
│  3. _detect_format()        → 检测表格密度/章节结构/条款/费率表   │
│  4. _mark_structure()       → 标记条款/表格/章节的字符位置       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  第2步: 路由选择 (RouteSelector.select_route)                         │
├─────────────────────────────────────────────────────────────────────┤
│  输入: NormalizedDocument                                            │
│  输出: ExtractionRoute {                                              │
│           mode: 'fast' | 'structured',      # 提取通道               │
│           product_type: str,                # 产品类型代码           │
│           confidence: float,                # 分类置信度 (0-1)       │
│           is_hybrid: bool,                  # 是否混合产品           │
│           reason: str                       # 决策原因说明           │
│       }                                                               │
│                                                                     │
│  内部流程:                                                            │
│  1. ProductTypeClassifier.get_primary_type() → 获取主导产品类型     │
│     ├─ classify() → 遍历PRODUCT_TYPES计算匹配分数                   │
│     └─ 返回 (type_code, confidence) 或默认 ("life_insurance", 0.0)  │
│                                                                     │
│  2. _can_use_fast_route() → 判断是否可使用快速通道                │
│     ├─ is_standard: format_info.is_structured && has_clause_numbers │
│     ├─ is_confident: confidence >= 0.7                               │
│     └─ has_key_info_front: 前2000字符包含75%+必需字段指示词      │
│                                                                     │
│  3. is_hybrid_product() → 判断是否混合产品                         │
│     └─ 至少2个类型且次优置信度 > 0.5                                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│     快速通道 (FastLane)        │   │   结构化通道 (StructuredLane)   │
│        目标: 80% 文档          │   │       目标: 20% 文档           │
├───────────────────────────────┤   ├───────────────────────────────┤
│ FastExtractor.extract()       │   │ StructuredExtractor.extract()  │
│                               │   │                               │
│ • Few-shot Prompt (2示例)     │   │ 1. PromptBuilder.build()      │
│ • 文档截取: 1500字符          │   │    - 角色: 产品类型专家        │
│ • max_tokens: 1500            │   │    - 字段: 按需组装组件        │
│ • 正则补充提取缺失字段         │   │    - Schema: 动态生成          │
│ • 失败抛出FastExtractionFailed│   │ 2. LLM主提取 (15000字符)      │
│                               │   │    - max_tokens: 6000         │
│ confidence: 0.85               │   │ 3. 专用提取器 (按需)           │
│ provenance: 'fast_llm'        │   │    - PremiumTableExtractor     │
│                               │   │    - ClauseExtractor           │
└───────────────────────────────┘   │                               │
                                    │ confidence: 0.75               │
                                    │ provenance: 'structured_llm'   │
                                    └───────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  第4步: 结果验证 (ResultValidator.validate)                        │
├─────────────────────────────────────────────────────────────────────┤
│  输入: ExtractResult                                                │
│  输出: ValidationResult {                                            │
│           is_valid: bool,                   # 是否通过验证          │
│           errors: List[str],                # 错误列表              │
│           warnings: List[str],              # 警告列表              │
│           score: int (0-100)                # 验证分数              │
│       }                                                               │
│                                                                     │
│  验证维度:                                                            │
│  1. 必需字段检查 → 对比REQUIRED_FIELDS                              │
│  2. 数据类型检查 → 金额字段转float，年龄字段转int                   │
│  3. 业务规则检查 → 遍历BUSINESS_RULES                               │
│  4. 置信度检查 → 识别低置信度字段(<0.7)                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ExtractResult                                │
│  {                                                                 │
│    data: Dict[str, Any],          # 提取的字段值                   │
│    confidence: Dict[str, float],   # 每个字段的置信度               │
│    provenance: Dict[str, str],     # 每个字段的来源               │
│    metadata: {                                                          │
│      extraction_mode: str,         # 'fast' | 'structured'         │
│      product_type: str,            # 产品类型代码                  │
│      confidence: float,            # 分类置信度                    │
│      is_hybrid: bool,              # 是否混合产品                  │
│      validation_score: int,       # 验证分数 (0-100)             │
│      validation_errors: List,     # 验证错误列表                  │
│      validation_warnings: List    # 验证警告列表                  │
│    }                                                               │
│  }                                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键决策点

#### 决策点1: 快速通道判定

```python
# path_selector.py: _can_use_fast_route()

# 条件1: 格式标准化
is_standard = format_info.is_structured and format_info.has_clause_numbers

# 条件2: 分类置信度高
is_confident = confidence >= 0.7

# 条件3: 关键信息在前
has_key_info_front = required_found >= len(REQUIRED_FIELDS) * 0.75

# 最终决策
return is_standard and is_confident and has_key_info_front
```

**设计意图：**
- 格式标准化 → LLM能更好地理解结构
- 置信度高 → 产品类型判断准确，Prompt更有效
- 关键信息在前 → Few-shot提取能覆盖核心字段

#### 决策点2: 混合产品判定

```python
# classifier.py: is_hybrid_product()

classifications = self.classify(document)  # [(type, score), ...]
return len(classifications) > 1 and classifications[1][1] > 0.5
```

**设计意图：**
- 至少2个产品类型匹配
- 次优类型置信度 > 0.5 → 确保不是误判

---

## 三、代码结构深度分析

### 3.1 模块依赖关系图

```
                    ┌─────────────────┐
                    │   DocumentExtractor
                    │   (主入口)
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│DocumentNormalizer│  │ RouteSelector  │  │ ResultValidator│
└────────────────┘  └────────┬───────┘  └────────────────┘
                            │
                            ▼
                   ┌────────────────┐
                   │ProductClassifier│
                   └────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ FastExtractor  │  │PromptBuilder   │  │StructuredExtractor│
└────────────────┘  └────────────────┘  └────────┬────────┘
                                             │
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                     │StructureAnalyzer│ │PremiumTable  │ │ClauseExtractor│
                     └──────────────┘ └──────────────┘ └──────────────┘

配置层:
┌────────────────┐  ┌────────────────┐
│   models.py    │  │product_types.py│
└────────────────┘  └────────────────┘
```

### 3.2 各文件职责分析

| 文件 | 行数 | 职责 | 依赖 | 被依赖 |
|------|------|------|------|--------|
| `models.py` | 150 | 数据模型定义 | - | 所有文件 |
| `product_types.py` | 198 | 产品类型配置 | models | classifier, prompt_builder, structured_extractor |
| `document_normalizer.py` | 155 | 文档规范化 | models | extractor |
| `classifier.py` | 72 | 产品分类 | models, product_types | path_selector |
| `path_selector.py` | 120 | 路由选择 | models, classifier | extractor, validator |
| `prompt_builder.py` | 224 | Prompt构建 | models, product_types | structured_extractor |
| `fast_extractor.py` | 160 | 快速提取 | models | extractor |
| `structured_extractor.py` | 271 | 结构化提取 | models, prompt_builder, product_types | extractor |
| `validator.py` | 134 | 结果验证 | models | extractor |
| `extractor.py` | 107 | 主入口 | models, document_normalizer, path_selector, fast_extractor, structured_extractor, validator | - |

**依赖特点：**
- 单向依赖，无循环依赖
- `models.py` 是唯一的基础层模块
- `extractor.py` 是唯一的聚合层模块
- 配置与逻辑分离 (`product_types.py` 独立)

---

## 四、核心算法分析

### 4.1 产品类型匹配算法

```python
# models.py: ProductType.match_score()

def match_score(self, document: str) -> float:
    score = 0.0

    # 1. 关键词匹配 (每个模式 1/n 分)
    for pattern in self.patterns:
        if re.search(pattern, document):
            score += 1.0 / len(self.patterns)

    # 2. 特征匹配 (按权重加分)
    for feature, weight in self.features.items():
        if self._has_feature(document, feature):
            score += weight

    return min(score, 1.0)  # 限制在 [0, 1]
```

**算法特点：**
- **关键词模式匹配**: 使用正则表达式匹配产品名称模式
- **特征权重加分**: 独特特征(如病种清单、账户、结算利率)加分
- **分数归一化**: 确保结果在 [0, 1] 区间
- **时间复杂度**: O(n*m), n=文档长度, m=模式数量

### 4.2 路由选择算法

```python
# path_selector.py: RouteSelector.select_route()

def select_route(self, document: NormalizedDocument) -> ExtractionRoute:
    # 1. 获取主导产品类型
    type_code, confidence = self.type_classifier.get_primary_type(document.content)

    # 2. 判断快速通道条件
    is_standard = format_info.is_structured and format_info.has_clause_numbers
    is_confident = confidence >= 0.7
    has_key_info_front = self._check_key_info_position(document)

    # 3. 选择路由
    mode = 'fast' if all([is_standard, is_confident, has_key_info_front]) else 'structured'

    return ExtractionRoute(
        mode=mode,
        product_type=type_code,
        confidence=confidence,
        is_hybrid=self.type_classifier.is_hybrid_product(document.content),
        reason=self._explain_decision(...)
    )
```

**决策表：**

| 格式标准化 | 置信度≥0.7 | 关键信息在前 | 路由 |
|-----------|-----------|-----------|------|
| ✓ | ✓ | ✓ | **快速通道** |
| ✗ | ✓ | ✓ | 结构化 |
| ✓ | ✗ | ✓ | 结构化 |
| ✓ | ✓ | ✗ | 结构化 |
| ✗ | ✗ | ✗ | 结构化 |

### 4.3 JSON解析算法

```python
# fast_extractor.py & structured_extractor.py: _parse_response()

def _parse_response(self, response: str) -> Dict[str, Any]:
    # 策略1: 提取markdown代码块中的JSON
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # 策略2: 直接解析首尾大括号内容
    cleaned = response.strip()
    if cleaned.startswith('{') and cleaned.endswith('}'):
        return json.loads(cleaned)

    # 策略3: 查找完整JSON对象 (处理嵌套)
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace != -1:
        return json.loads(cleaned[first_brace:last_brace + 1])

    raise ValueError("无法解析响应")
```

**容错策略：**
- 优先提取 markdown 代码块（LLM常用格式）
- 其次直接解析完整 JSON 对象
- 最后查找嵌套 JSON（处理多余文本）
- 全部失败则抛出异常，触发降级

---

## 五、设计模式应用

### 5.1 策略模式 (Strategy Pattern)

```python
# extractor.py: DocumentExtractor.extract()

if route.mode == 'fast':
    result = self.fast_extractor.extract(normalized, required_fields)
else:
    result = self.structured_extractor.extract(normalized, route, required_fields)
```

**应用场景：** 根据路由决策选择不同的提取策略

### 5.2 模板方法模式 (Template Method Pattern)

```python
# structured_extractor.py: StructuredExtractor.extract()

def extract(self, document, route, required_fields):
    # 1. 构建 Prompt (钩子方法)
    prompt = self.prompt_builder.build(...)

    # 2. LLM 主提取
    result = self._parse_response(self.llm_client.generate(...))

    # 3. 专用提取器 (按需)
    if 'premium_table' in required_fields:
        result['premium_table'] = self.specialized_extractors['premium_table'].extract(...)

    return ExtractResult(...)
```

**应用场景：** 定义提取流程骨架，子步骤可定制

### 5.3 建造者模式 (Builder Pattern)

```python
# prompt_builder.py: PromptBuilder.build()

def build(self, product_type, required_fields, extraction_focus, output_schema, is_hybrid):
    # 1. 角色定义
    prompt = self.COMPONENTS['role_specialized'].format(...)

    # 2. 添加字段说明
    for component in self._get_field_components(required_fields):
        prompt += self.COMPONENTS[component]

    # 3. 混合产品说明
    if is_hybrid:
        prompt += self.COMPONENTS['hybrid_notice']

    # 4. 输出格式
    prompt += self.COMPONENTS['output_structure'].format(...)

    return prompt
```

**应用场景：** 复杂Prompt的分步组装

### 5.4 责任链模式 (Chain of Responsibility)

```python
# validator.py: ResultValidator.validate()

def validate(self, result):
    errors = []

    # 1. 必需字段检查
    errors.extend(self._check_required_fields(result))

    # 2. 数据类型检查
    errors.extend(self._validate_data_types(result.data))

    # 3. 业务规则检查
    errors.extend(self._validate_business_rules(result.data))

    # 4. 置信度检查
    warnings.extend(self._check_confidence(result.confidence))

    return ValidationResult(is_valid=len(errors)==0, ...)
```

**应用场景：** 多维度验证的责任传递

---

## 六、代码质量分析

### 6.1 代码行数分布

| 文件 | 行数 | 类数 | 函数数 | 平均函数行数 |
|------|------|------|--------|-------------|
| models.py | 150 | 8 | 5 | 12 |
| product_types.py | 198 | 0 | 3 | 8 |
| document_normalizer.py | 155 | 1 | 5 | 18 |
| classifier.py | 72 | 1 | 5 | 8 |
| path_selector.py | 120 | 1 | 6 | 13 |
| prompt_builder.py | 224 | 1 | 4 | 35 |
| fast_extractor.py | 160 | 2 | 5 | 22 |
| structured_extractor.py | 271 | 4 | 5 | 30 |
| validator.py | 134 | 2 | 5 | 16 |
| extractor.py | 107 | 1 | 2 | 35 |

**指标分析：**
- 函数平均长度 < 35行，符合"短函数"原则
- 单个文件类数 ≤ 4，职责单一
- 最大类 (StructuredExtractor) 271行，包含3个子类

### 6.2 圈复杂度分析

| 函数 | 圈复杂度 | 说明 |
|------|---------|------|
| `DocumentExtractor.extract()` | 5 | if-try-except 结构 |
| `RouteSelector.select_route()` | 3 | 简单决策树 |
| `PromptBuilder.build()` | 4 | 条件组装 |
| `ResultValidator.validate()` | 3 | 顺序检查 |
| `_parse_response()` | 4 | 多策略解析 |

**整体评估：** 圈复杂度均 < 10，易于理解和测试

### 6.3 耦合度分析

| 耦合类型 | 评分 | 说明 |
|---------|------|------|
| 模块间耦合 | **低** | 通过接口(models)交互，无直接依赖 |
| 数据耦合 | **低** | 使用dataclass传递数据，结构清晰 |
| 控制耦合 | **低** | 通过返回值控制流程，无共享状态 |
| 逻辑耦合 | **低** | 每个模块独立配置，可独立修改 |

---

## 七、潜在问题与改进建议

### 7.1 发现的问题

#### 问题1: ProductType.match_score() 魔法数字

```python
# models.py: ProductType.match_score()

score += 1.0 / len(self.patterns)  # 每个模式权重不直观
```

**改进建议：**
```python
# 明确配置权重
class ProductType:
    pattern_weight: float = 0.3  # 关键词匹配权重
    feature_weight_scale: float = 1.0  # 特征权重缩放
```

#### 问题2: 快速通道阈值硬编码

```python
# path_selector.py

is_confident = confidence >= 0.7  # 硬编码
required_found >= len(self.REQUIRED_FIELDS) * 0.75  # 硬编码
```

**改进建议：**
```python
class RouteSelector:
    FAST_ROUTE_CONFIDENCE_THRESHOLD = 0.7
    FAST_ROUTE_KEY_INFO_RATIO = 0.75
```

#### 问题3: JSON解析重复代码

`_parse_response()` 在3个类中重复实现

**改进建议：**
```python
# utils.py
def parse_json_response(response: str) -> Dict[str, Any]:
    """通用JSON解析器"""
    ...

# 各提取器直接调用
from .utils import parse_json_response
```

#### 问题4: 业务规则lambda表达式可读性差

```python
# validator.py

BusinessRule(
    name="age_range",
    check=lambda data: int(data.get('age_min', 0)) < int(data.get('age_max', 999)),
    ...
)
```

**改进建议：**
```python
def _check_age_range(data: Dict) -> bool:
    """检查年龄范围"""
    try:
        return int(data.get('age_min', 0)) < int(data.get('age_max', 999))
    except (ValueError, TypeError):
        return False

BusinessRule(
    name="age_range",
    check=_check_age_range,
    ...
)
```

### 7.2 性能优化建议

#### 优化点1: 产品类型匹配预编译正则

```python
class ProductType:
    def __post_init__(self):
        self._compiled_patterns = [re.compile(p) for p in self.patterns]

    def match_score(self, document: str) -> float:
        for pattern in self._compiled_patterns:  # 使用预编译
            if pattern.search(document):
                score += 1.0 / len(self.patterns)
```

#### 优化点2: 结构标记可缓存

```python
class DocumentNormalizer:
    @lru_cache(maxsize=128)
    def _mark_structure(self, document: str) -> StructureMarkers:
        # 对相同文档内容复用结果
        ...
```

#### 优化点3: 路由选择可添加缓存

```python
class RouteSelector:
    @lru_cache(maxsize=512)
    def select_route(self, document_hash: int) -> ExtractionRoute:
        # 使用文档哈希作为缓存键
        ...
```

---

## 八、测试覆盖分析

### 8.1 测试文件统计

| 测试文件 | 测试数 | 覆盖组件 |
|---------|--------|---------|
| test_classifier.py | 3 | ProductTypeClassifier |
| test_normalizer.py | 3 | DocumentNormalizer |
| test_route_selector.py | 2 | RouteSelector |
| test_fast_extractor.py | 2 | FastExtractor |
| test_structured_extractor.py | 1 | StructuredExtractor |
| test_result_validator.py | 2 | ResultValidator |
| test_extractor.py | 2 | DocumentExtractor (端到端) |
| test_prompt_builder.py | 2 | PromptBuilder |
| test_performance_comparison.py | 1 | 性能对比 |
| integration_test.py | 1 | 真实LLM集成 |

**总计：19个测试，覆盖10个组件**

### 8.2 测试覆盖缺口

| 未测试组件 | 原因 | 建议 |
|----------|------|------|
| StructureAnalyzer | 集成在StructuredExtractor中 | 单独测试 |
| PremiumTableExtractor | 集成在StructuredExtractor中 | 单独测试 |
| ClauseExtractor | 集成在StructuredExtractor中 | 单独测试 |
| BusinessRule | 通过ResultValidator间接测试 | 单独测试 |

---

## 九、扩展性分析

### 9.1 新增产品类型步骤

**Step 1:** 在 `product_types.py` 添加定义
```python
ProductType(
    code="new_product",
    name="新产品名称",
    patterns=[r'关键词1', r'关键词2'],
    features={'feature1': 0.3, 'feature2': 0.2},
    required_fields=['field1', 'field2']
)
```

**Step 2:** 更新映射表
```python
EXTRACTION_FOCUS_MAP['new_product'] = ['重点1', '重点2']
OUTPUT_SCHEMA_TEMPLATES['new_product'] = {...}
```

**Step 3:** 如需新字段，更新 `prompt_builder.py`
```python
COMPONENTS['field_new'] = """**新字段**:\n..."""
component_map['field1'] = ['field_new']
```

### 9.2 新增验证规则步骤

```python
# validator.py

BUSINESS_RULES.append(
    BusinessRule(
        name="new_rule",
        check=lambda data: ...,
        error_message="规则说明"
    )
)
```

---

## 十、总结与评分

### 10.1 架构设计评分

| 维度 | 评分 (1-5) | 说明 |
|------|-----------|------|
| 模块化 | 5 | 职责清晰，11个文件各司其职 |
| 可扩展性 | 5 | 配置驱动，新增产品类型无需修改代码 |
| 可测试性 | 4 | 依赖注入友好，测试覆盖良好 |
| 容错性 | 5 | 多层降级，异常处理完善 |
| 性能 | 4 | 双通道优化，有缓存空间 |
| 可读性 | 5 | 命名清晰，注释完整 |
| **综合评分** | **4.7** | **优秀** |

### 10.2 代码质量评分

| 指标 | 评分 | 说明 |
|------|------|------|
| 圈复杂度 | 5 | 均 < 10 |
| 代码重复度 | 4 | JSON解析有重复，可提取 |
| 命名规范 | 5 | 清晰直观 |
| 注释文档 | 5 | 完整的docstring |
| 类型注解 | 4 | 核心函数有类型注解 |
| **综合评分** | **4.5** | **优秀** |

### 10.3 核心优势

1. **双通道设计**: 80%快速通道大幅降低成本
2. **配置驱动**: 产品类型、提取重点、Schema全部配置化
3. **动态Prompt**: 根据产品类型自动生成针对性Prompt
4. **容错降级**: 快速失败自动回退结构化
5. **完整验证**: 多维度验证保证数据质量
6. **来源追溯**: 每个字段记录置信度和来源

### 10.4 改进空间

1. **提取公共工具**: JSON解析等通用函数
2. **配置外部化**: 阈值等参数可配置
3. **性能优化**: 预编译正则、添加缓存
4. **测试补充**: 专用提取器的单元测试
5. **日志增强**: 添加更详细的调试日志

---

## 附录：完整类图

```
┌─────────────────────────────────────────────────────────────────────┐
│                              DocumentExtractor                         │
│  - normalizer: DocumentNormalizer                                   │
│  - route_selector: RouteSelector                                     │
│  - fast_extractor: FastExtractor                                   │
│  - structured_extractor: StructuredExtractor                         │
│  - validator: ResultValidator                                       │
│  + extract(document, source_type, required_fields) -> ExtractResult │
└─────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│ DocumentNormalizer│          │ RouteSelector │          │ ResultValidator│
└───────────────┘          └───────┬───────┘          └───────────────┘
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
        ┌───────────────┐              ┌───────────────┐
        │ProductClassifier│              │  ExtractionRoute│
        └───────────────┘              └───────────────┘
                │                               │
        ┌───────┴───────┐                       │
        ▼               ▼                       ▼
┌───────────────┐ ┌───────────────┐        ┌───────────────┐
│ ProductType    │ │ FormatInfo    │        │ StructureMarkers│
│  - code        │ │  - is_structured│        │  - positions  │
│  - name        │ │  - has_clause  │        └───────────────┘
│  - patterns    │ │  - section_count│
│  - features    │ │  - table_density│
└───────────────┘ └───────────────┘
```
