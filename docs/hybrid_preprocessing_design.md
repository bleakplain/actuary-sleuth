# 规则提取 + LLM 提取混合方案设计

## 1. 方案概述

### 1.1 核心理念
```
快速路径(规则) + 增强路径(LLM) = 高效且准确的混合提取
```

### 1.2 设计原则
- **规则优先**: 简单明确的字段用规则提取，快速可靠
- **LLM 增强**: 复杂语义和规则缺失的字段用 LLM 补充
- **质量驱动**: 根据质量评分智能决策提取策略
- **可追溯性**: 记录每个字段的来源和置信度

## 2. 架构设计

### 2.1 整体流程

```
原始文档
    |
    v
[规则提取] (并行)
    |    fast_path
    |--------> RuleExtractor (39个正则模式)
    |         |
    |         v
    |    rule_result (快速结果)
    |
    v
[质量评估]
    |
    v
QualityAssessor (多维度评分)
    |
    v
quality_score (0-100)
    |
    +-- >=70: 规则路径 ✓ (足够好)
    |         |
    |         v
    |    ResultFusion (合并)
    |
    +-- 50-69: LLM增强 → LLMEnhancer (补充验证)
    |         |
    |         v
    |    ResultFusion (智能合并)
    |
    +-- <50: LLM主导 → LLMExtractor (完整提取)
    |         |
    |         v
    |    ResultFusion (智能合并)
    |
    v
[结果融合]
    |
    v
final_result (带来源标记)
```

### 2.2 双路径架构

```
┌─────────────────────────────────────────────────────────┐
│                    混合提取引擎                           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────────┐              ┌──────────────────┐   │
│  │  规则提取路径    │              │   LLM增强路径     │   │
│  │  (RuleExtractor)│              │  (LLMEnhancer)   │   │
│  └────────────────┘              └──────────────────┘   │
│         │                                 │              │
│         │ 39 patterns                    │ GPT-4/Qwen   │
│         │ regex matching                 │ semantic     │
│         │                                 │ understanding│
│         v                                 v              │
│  ┌────────────────┐              ┌──────────────────┐   │
│  │  rule_result   │              │  llm_result      │   │
│  │  - structured  │              │  - structured    │   │
│  │  - confidence  │              │  - confidence    │   │
│  │  - provenance  │              │  - provenance    │   │
│  └────────────────┘              └──────────────────┘   │
│         │                                 │              │
│         └─────────────┬───────────────────┘              │
│                       │                                  │
│                       v                                  │
│              ┌──────────────────┐                       │
│              │  ResultFusion    │                       │
│              │  - 合并结果       │                       │
│              │  - 冲突解决       │                       │
│              │  - 来源标记       │                       │
│              └──────────────────┘                       │
│                       │                                  │
│                       v                                  │
│              ┌──────────────────┐                       │
│              │  final_result    │                       │
│              └──────────────────┘                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## 3. 核心组件

### 3.1 RuleExtractor (规则提取器)

**职责**: 使用预定义的正则模式快速提取结构化信息

```python
class RuleExtractor:
    """规则提取器 - 使用39个预定义模式"""

    PATTERNS = {
        # 产品信息 (8个模式)
        'product_name': [r'产品名称[：:]\s*([^\n]+)'],
        'product_type': [r'产品类型[：:]\s*([^\n]+)'],
        'insurance_company': [r'保险公司[：:]\s*([^\n]+)', r'承保机构[：:]\s*([^\n]+)'],

        # 投保信息 (5个模式)
        'age_min': [r'(\d+)周?岁', r'出生满\s*(\d+)\s*日'],
        'age_max': [r'至\s*(\d+)\s*周岁'],
        'occupation': [r'职业类别[：:]\s*([^\n]+)'],

        # 保险期间 (4个模式)
        'insurance_period': [r'保险期间[：:]\s*([^\n]+)', r'保障期限[：:]\s*([^\n]+)'],

        # 缴费方式 (6个模式)
        'payment_method': [r'缴费方式[：:]\s*([^\n]+)', r'交费方式[：:]\s*([^\n]+)'],
        'payment_period': [r'缴费期间[：:]\s*([^\n]+)', r'交费期间[：:]\s*([^\n]+)'],

        # 等待期 (3个模式)
        'waiting_period': [r'等待期[：:]\s*(\d+)[日天年]', r'观察期[：:]\s*(\d+)[日天年]'],

        # 费率信息 (7个模式)
        'premium_rate': [r'年交\s*([0-9.]+)\s*元'],
        'expense_rate': [r'费用率[：:]\s*([0-9.]+)%'],
        'interest_rate': [r'预定利率[：:]\s*([0-9.]+)%', r'定价利率[：:]\s*([0-9.]+)%'],

        # 犹豫期 (3个模式)
        'cooling_period': [r'犹豫期[：:]\s*(\d+)[日天]'],

        # 现金价值 (3个模式)
        'cash_value': [r'现金价值[：:]\s*([^\n]+)']
    }

    def extract(self, document: str) -> ExtractResult:
        """执行规则提取"""
        result = {}
        confidence = {}

        for field, patterns in self.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, document)
                if match:
                    result[field] = match.group(1).strip()
                    confidence[field] = self._calculate_confidence(pattern, match)
                    break

        return ExtractResult(
            data=result,
            confidence=confidence,
            provenance={k: 'rule' for k in result}
        )

    def _calculate_confidence(self, pattern: str, match: re.Match) -> float:
        """计算置信度"""
        base = 0.85  # 规则提取基础置信度

        # 根据匹配质量调整
        if match.group(1).strip():
            base += 0.10

        # 根据模式特异性调整
        if '产品名称' in pattern or '保险公司' in pattern:
            base += 0.05

        return min(base, 1.0)
```

### 3.2 QualityAssessor (质量评估器)

**职责**: 多维度评估规则提取结果的质量

```python
@dataclass
class QualityMetrics:
    """质量指标"""
    completeness: float  # 完整性 0-1
    accuracy: float      # 准确性 0-1
    consistency: float   # 一致性 0-1
    reasonableness: float # 合理性 0-1

    def overall_score(self) -> int:
        """总体质量评分 (0-100)"""
        weights = {
            'completeness': 0.40,
            'accuracy': 0.35,
            'consistency': 0.15,
            'reasonableness': 0.10
        }
        score = sum(
            getattr(self, k) * weights[k]
            for k in weights
        )
        return int(score * 100)


class QualityAssessor:
    """质量评估器"""

    REQUIRED_FIELDS = {
        'product_name', 'insurance_company',
        'waiting_period', 'premium_rate'
    }

    def assess(self, result: ExtractResult) -> QualityMetrics:
        """评估提取结果质量"""

        # 1. 完整性评估 (40%)
        completeness = self._assess_completeness(result)

        # 2. 准确性评估 (35%)
        accuracy = self._assess_accuracy(result)

        # 3. 一致性评估 (15%)
        consistency = self._assess_consistency(result)

        # 4. 合理性评估 (10%)
        reasonableness = self._assess_reasonableness(result)

        return QualityMetrics(
            completeness=completeness,
            accuracy=accuracy,
            consistency=consistency,
            reasonableness=reasonableness
        )

    def _assess_completeness(self, result: ExtractResult) -> float:
        """评估完整性"""
        if not result.data:
            return 0.0

        present = len(result.data)
        required = len(self.REQUIRED_FIELDS)
        return min(present / required, 1.0)

    def _assess_accuracy(self, result: ExtractResult) -> float:
        """评估准确性 - 基于置信度"""
        if not result.confidence:
            return 0.0

        avg_confidence = sum(result.confidence.values()) / len(result.confidence)
        return avg_confidence

    def _assess_consistency(self, result: ExtractResult) -> float:
        """评估一致性 - 检查格式统一性"""
        data = result.data

        # 检查金额格式一致性
        amounts = []
        for k, v in data.items():
            if 'rate' in k or 'premium' in k:
                amounts.append(str(v))

        if not amounts:
            return 1.0

        # 检查格式是否一致
        formats = set()
        for amount in amounts:
            if '%' in amount:
                formats.add('percent')
            elif '元' in amount:
                formats.add('currency')

        return 1.0 if len(formats) <= 1 else 0.7

    def _assess_reasonableness(self, result: ExtractResult) -> float:
        """评估合理性 - 业务逻辑验证"""
        data = result.data
        score = 1.0

        # 年龄范围合理性
        if 'age_min' in data and 'age_max' in data:
            try:
                min_age = int(data['age_min'])
                max_age = int(data['age_max'])
                if min_age >= max_age:
                    score -= 0.3
                if max_age > 100 or min_age < 0:
                    score -= 0.2
            except ValueError:
                score -= 0.2

        # 费用率合理性
        if 'expense_rate' in data:
            try:
                rate = float(data['expense_rate'].replace('%', ''))
                if not (0 <= rate <= 50):
                    score -= 0.2
            except ValueError:
                score -= 0.1

        # 等待期合理性
        if 'waiting_period' in data:
            try:
                period = int(data['waiting_period'])
                if not (0 <= period <= 365):
                    score -= 0.2
            except ValueError:
                score -= 0.1

        return max(score, 0.0)
```

### 3.3 LLMEnhancer (LLM增强器)

**职责**: 使用LLM补充规则提取的缺失字段，验证现有结果

```python
class LLMEnhancer:
    """LLM增强器 - 补充和验证规则提取结果"""

    def __init__(self, model: str = "qwen2:7b"):
        self.model = model
        self.client = OllamaClient(host="http://localhost:11434")

    def enhance(self, document: str, rule_result: ExtractResult) -> ExtractResult:
        """增强规则提取结果"""

        # 1. 识别缺失字段
        missing_fields = self._identify_missing(rule_result)

        # 2. 构建增强提示
        prompt = self._build_enhance_prompt(document, rule_result, missing_fields)

        # 3. 调用LLM
        llm_response = self._call_llm(prompt)

        # 4. 解析结果
        llm_data = self._parse_llm_response(llm_response)

        # 5. 合并结果
        return self._merge_results(rule_result, llm_data)

    def _identify_missing(self, rule_result: ExtractResult) -> Set[str]:
        """识别缺失或低置信度字段"""
        missing = set()

        for field in QualityAssessor.REQUIRED_FIELDS:
            if field not in rule_result.data:
                missing.add(field)
            elif rule_result.confidence.get(field, 1.0) < 0.7:
                missing.add(field)

        return missing

    def _build_enhance_prompt(self, document: str, rule_result: ExtractResult, missing: Set[str]) -> str:
        """构建增强提示"""
        return f"""你是保险产品信息提取专家。给定保险文档和已有的规则提取结果，请补充以下缺失字段：

缺失字段: {', '.join(missing)}

已有规则提取结果:
```json
{json.dumps(rule_result.data, ensure_ascii=False, indent=2)}
```

请从以下文档中提取缺失字段:
```
{document[:4000]}
```

返回格式:
```json
{{
    "field_name": "提取的值",
    "field_name2": "提取的值2"
}}
```

只返回JSON，不要其他内容。"""

    def _call_llm(self, prompt: str) -> str:
        """调用LLM"""
        try:
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                timeout=30
            )
            return response['response']
        except Exception as e:
            logger.warning(f"LLM调用失败: {e}")
            return "{}"

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析LLM响应"""
        try:
            # 提取JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                response = json_match.group(1)
            else:
                response = response.strip()

            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning(f"LLM响应JSON解析失败: {response[:200]}")
            return {}

    def _merge_results(self, rule_result: ExtractResult, llm_data: Dict) -> ExtractResult:
        """合并规则和LLM结果"""
        merged_data = {**rule_result.data}
        merged_confidence = {**rule_result.confidence}
        merged_provenance = {**rule_result.provenance}

        for field, value in llm_data.items():
            if value:  # 只添加非空值
                merged_data[field] = value
                merged_confidence[field] = 0.75  # LLM增强置信度
                merged_provenance[field] = 'llm_enhanced'

        return ExtractResult(
            data=merged_data,
            confidence=merged_confidence,
            provenance=merged_provenance
        )
```

### 3.4 ResultFusion (结果融合器)

**职责**: 智能合并规则和LLM结果，处理冲突

```python
class ResultFusion:
    """结果融合器 - 智能合并多路径结果"""

    def fuse(self, rule_result: ExtractResult, llm_result: Optional[ExtractResult]) -> ExtractResult:
        """融合多个提取结果"""
        if not llm_result:
            return rule_result

        fused_data = {}
        fused_confidence = {}
        fused_provenance = {}

        all_fields = set(rule_result.data) | set(llm_result.data)

        for field in all_fields:
            rule_value = rule_result.data.get(field)
            llm_value = llm_result.data.get(field)
            rule_conf = rule_result.confidence.get(field, 0)
            llm_conf = llm_result.confidence.get(field, 0)

            # 决策逻辑
            if rule_value and llm_value:
                # 冲突解决
                if self._values_match(rule_value, llm_value):
                    # 值一致，使用高置信度来源
                    if rule_conf >= llm_conf:
                        fused_data[field] = rule_value
                        fused_confidence[field] = max(rule_conf, llm_conf)
                        fused_provenance[field] = 'rule_validated'
                    else:
                        fused_data[field] = llm_value
                        fused_confidence[field] = max(rule_conf, llm_conf)
                        fused_provenance[field] = 'llm_validated'
                else:
                    # 值冲突，使用高置信度来源
                    if rule_conf > llm_conf + 0.2:  # 规则明显更可信
                        fused_data[field] = rule_value
                        fused_confidence[field] = rule_conf * 0.9  # 降权
                        fused_provenance[field] = 'rule_conflict'
                    elif llm_conf > rule_conf + 0.2:  # LLM明显更可信
                        fused_data[field] = llm_value
                        fused_confidence[field] = llm_conf * 0.9  # 降权
                        fused_provenance[field] = 'llm_override'
                    else:
                        # 置信度接近，标记冲突
                        fused_data[field] = rule_value  # 默认规则
                        fused_confidence[field] = rule_conf * 0.7
                        fused_provenance[field] = 'conflict'

            elif rule_value:
                fused_data[field] = rule_value
                fused_confidence[field] = rule_conf
                fused_provenance[field] = 'rule'

            elif llm_value:
                fused_data[field] = llm_value
                fused_confidence[field] = llm_conf
                fused_provenance[field] = 'llm'

        return ExtractResult(
            data=fused_data,
            confidence=fused_confidence,
            provenance=fused_provenance
        )

    def _values_match(self, v1: str, v2: str) -> bool:
        """检查值是否匹配"""
        if v1 == v2:
            return True

        # 标准化后比较
        v1_clean = re.sub(r'[^\d.]', '', v1)
        v2_clean = re.sub(r'[^\d.]', '', v2)

        if v1_clean and v2_clean:
            try:
                return float(v1_clean) == float(v2_clean)
            except ValueError:
                pass

        return False
```

### 3.5 HybridExtractor (混合提取器 - 主入口)

**职责**: 协调所有组件，实现智能混合提取

```python
class HybridExtractor:
    """混合提取器 - 主入口"""

    def __init__(self, config: Dict[str, Any]):
        self.rule_extractor = RuleExtractor()
        self.quality_assessor = QualityAssessor()
        self.llm_enhancer = LLMEnhancer(
            model=config.get('llm_model', 'qwen2:7b')
        )
        self.fusion = ResultFusion()

        # 阈值配置
        self.thresholds = {
            'excellent': config.get('threshold_excellent', 70),
            'fair': config.get('threshold_fair', 50)
        }

    def extract(self, document: str) -> ExtractResult:
        """执行混合提取"""

        # 步骤1: 规则提取 (始终执行)
        rule_result = self.rule_extractor.extract(document)

        # 步骤2: 质量评估
        quality = self.quality_assessor.assess(rule_result)
        score = quality.overall_score()

        logger.info(f"规则提取质量评分: {score}/100")
        logger.info(f"  - 完整性: {quality.completeness:.2f}")
        logger.info(f"  - 准确性: {quality.accuracy:.2f}")
        logger.info(f"  - 一致性: {quality.consistency:.2f}")
        logger.info(f"  - 合理性: {quality.reasonableness:.2f}")

        # 步骤3: 决策逻辑
        if score >= self.thresholds['excellent']:
            # 质量足够好，直接使用规则结果
            logger.info("质量优秀，使用规则提取结果")
            return rule_result

        elif score >= self.thresholds['fair']:
            # 质量一般，LLM增强
            logger.info("质量一般，执行LLM增强")
            llm_result = self.llm_enhancer.enhance(document, rule_result)
            return self.fusion.fuse(rule_result, llm_result)

        else:
            # 质量差，LLM主导提取
            logger.info("质量不足，执行完整LLM提取")
            llm_result = self.llm_enhancer.extract_full(document)
            return self.fusion.fuse(rule_result, llm_result)

    def extract_with_debug(self, document: str) -> Dict[str, Any]:
        """带调试信息的提取"""
        rule_result = self.rule_extractor.extract(document)
        quality = self.quality_assessor.assess(rule_result)
        score = quality.overall_score()

        llm_result = None
        if score < self.thresholds['excellent']:
            llm_result = self.llm_enhancer.enhance(document, rule_result)

        final_result = self.fusion.fuse(rule_result, llm_result)

        return {
            'final': final_result,
            'debug': {
                'rule_result': rule_result,
                'llm_result': llm_result,
                'quality_score': score,
                'quality_metrics': quality,
                'decision': self._get_decision_label(score)
            }
        }

    def _get_decision_label(self, score: int) -> str:
        """获取决策标签"""
        if score >= self.thresholds['excellent']:
            return 'rule_only'
        elif score >= self.thresholds['fair']:
            return 'llm_enhanced'
        else:
            return 'llm_dominant'
```

## 4. 数据结构

```python
@dataclass
class ExtractResult:
    """提取结果"""
    data: Dict[str, Any]           # 提取的字段数据
    confidence: Dict[str, float]   # 每个字段的置信度 (0-1)
    provenance: Dict[str, str]     # 每个字段的来源 (rule/llm/hybrid)

    def get_source_summary(self) -> Dict[str, int]:
        """获取来源统计"""
        sources = Counter(self.provenance.values())
        return dict(sources)

    def get_low_confidence_fields(self, threshold: float = 0.7) -> List[str]:
        """获取低置信度字段"""
        return [
            k for k, v in self.confidence.items()
            if v < threshold
        ]

    def get_conflicts(self) -> List[str]:
        """获取冲突字段"""
        return [
            k for k, v in self.provenance.items()
            if 'conflict' in v
        ]
```

## 5. 配置管理

```json
{
  "preprocess": {
    "mode": "hybrid",
    "llm": {
      "enabled": true,
      "model": "qwen2:7b",
      "timeout": 30,
      "temperature": 0.1,
      "max_tokens": 2000
    },
    "threshold": {
      "excellent": 70,
      "good": 60,
      "fair": 50
    },
    "rules": {
      "enabled": true,
      "patterns_file": "patterns.json"
    }
  }
}
```

## 6. 错误处理

### 6.1 错误场景与处理策略

| 错误场景 | 处理策略 | 回退方案 |
|---------|---------|---------|
| LLM不可用 | 记录警告，使用规则提取 | 返回规则结果 |
| LLM超时 | 缩短上下文重试1次 | 使用规则结果 |
| JSON解析失败 | 清理响应后重试 | 忽略LLM结果 |
| 显然错误 | 规则交叉验证 | 修正或标记 |

### 6.2 错误处理实现

```python
class HybridExtractor:
    def extract(self, document: str) -> ExtractResult:
        """带错误处理的混合提取"""
        try:
            rule_result = self.rule_extractor.extract(document)
        except Exception as e:
            logger.error(f"规则提取失败: {e}")
            return ExtractResult({}, {}, {})

        quality = self.quality_assessor.assess(rule_result)
        score = quality.overall_score()

        if score >= self.thresholds['excellent']:
            return rule_result

        try:
            llm_result = self.llm_enhancer.enhance(document, rule_result)
        except LLMUnavailableError:
            logger.warning("LLM不可用，使用规则结果")
            return rule_result
        except LLMTimeoutError:
            logger.warning("LLM超时，使用规则结果")
            return rule_result
        except JSONDecodeError:
            logger.warning("LLM响应解析失败，使用规则结果")
            return rule_result
        except Exception as e:
            logger.error(f"LLM增强失败: {e}")
            return rule_result

        return self.fusion.fuse(rule_result, llm_result)
```

## 7. 监控指标

```python
@dataclass
class ExtractionMetrics:
    """提取指标"""
    total_extractions: int = 0
    rule_only_count: int = 0
    llm_enhanced_count: int = 0
    llm_dominant_count: int = 0
    avg_quality_score: float = 0.0
    avg_extraction_time: float = 0.0
    llm_failure_count: int = 0

    def log_summary(self):
        """记录摘要"""
        logger.info(f"""
提取指标摘要:
- 总提取次数: {self.total_extractions}
- 规则路径: {self.rule_only_count} ({self.rule_only_count/self.total_extractions*100:.1f}%)
- LLM增强: {self.llm_enhanced_count} ({self.llm_enhanced_count/self.total_extractions*100:.1f}%)
- LLM主导: {self.llm_dominant_count} ({self.llm_dominant_count/self.total_extractions*100:.1f}%)
- 平均质量: {self.avg_quality_score:.1f}/100
- 平均耗时: {self.avg_extraction_time:.2f}s
- LLM失败: {self.llm_failure_count}
        """)
```

## 8. 使用示例

```python
# 初始化
config = {
    'llm_model': 'qwen2:7b',
    'threshold_excellent': 70,
    'threshold_fair': 50
}
extractor = HybridExtractor(config)

# 标准提取
result = extractor.extract(document)

# 带调试信息提取
debug_result = extractor.extract_with_debug(document)
print(f"最终结果: {debug_result['final'].data}")
print(f"决策: {debug_result['debug']['decision']}")
print(f"质量评分: {debug_result['debug']['quality_score']}")

# 检查结果
print(f"字段来源: {result.get_source_summary()}")
print(f"低置信度字段: {result.get_low_confidence_fields()}")
print(f"冲突字段: {result.get_conflicts()}")
```

## 9. 优势总结

| 维度 | 纯规则 | 纯LLM | 混合方案 |
|-----|-------|-------|---------|
| 速度 | 快 (~0.1s) | 慢 (~5s) | 快速+按需加速 |
| 准确性 | 中等 | 高 | 高 |
| 成本 | 低 | 高 | 低 |
| 可解释性 | 高 | 低 | 高 |
| 可维护性 | 中等 | 低 | 中等 |
| 鲁棒性 | 低 | 中等 | 高 |

**混合方案核心优势**:
1. **性能优化**: 70%+ 文档走快速路径，LLM仅用于增强
2. **质量保证**: 多维度质量评估确保结果可靠性
3. **成本可控**: 按需使用LLM，降低API调用成本
4. **可追溯性**: 明确记录每个字段的来源和置信度
5. **容错能力**: LLM失败时优雅降级到规则提取
6. **持续改进**: 可通过调整阈值优化性能/质量平衡
