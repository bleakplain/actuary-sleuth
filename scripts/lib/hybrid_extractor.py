#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合提取器 - 规则+LLM混合架构
实现保险产品文档的智能预处理
"""
import re
import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import Counter

from lib.config import get_config
from lib.llm_client import LLMClientFactory, BaseLLMClient


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    """提取结果"""
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    provenance: Dict[str, str] = field(default_factory=dict)

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


class RuleExtractor:
    """规则提取器 - 使用39个预定义模式"""

    PATTERNS = {
        # 产品信息 (8个模式)
        'product_name': [
            r'^#\s*(.+?)(?:\s|条款|保险|产品|\n)',
            r'产品名称[：:]\s*([^\n]+)',
            r'保险产品名称[：:]\s*([^\n]+)',
            r'^(.+?)保险条款'
        ],
        'product_type': [
            r'产品类型[：:]\s*([^\n]+)',
            r'###\s*##\s*(.+?)险',
            r'险种[：:]\s*([^\n]+)'
        ],
        'insurance_company': [
            r'(.+?)人寿保险股份有限公司',
            r'(.+?)保险有限公司',
            r'保险公司[：:]\s*([^\n]+)',
            r'承保公司[：:]\s*([^\n]+)'
        ],

        # 投保信息 (5个模式)
        'age_min': [
            r'(\d+)周?岁',
            r'出生满\s*(\d+)\s*日',
            r'投保年龄.*?(\d+)\s*周?岁'
        ],
        'age_max': [
            r'至\s*(\d+)\s*周岁',
            r'(\d+)周岁以下'
        ],
        'occupation': [
            r'职业类别[：:]\s*([^\n]+)',
            r'职业等级[：:]\s*([^\n]+)'
        ],

        # 保险期间 (4个模式)
        'insurance_period': [
            r'保险期间[：:]\s*([^\n]+)',
            r'保障期限[：:]\s*([^\n]+)',
            r'保险期限[：:]\s*([^\n]+)'
        ],

        # 缴费方式 (6个模式)
        'payment_method': [
            r'缴费方式[：:]\s*([^\n]+)',
            r'交费方式[：:]\s*([^\n]+)'
        ],
        'payment_period': [
            r'缴费期间[：:]\s*([^\n]+)',
            r'交费期间[：:]\s*([^\n]+)'
        ],

        # 等待期 (3个模式)
        'waiting_period': [
            r'等待期[：:]\s*(\d+)[日天年]',
            r'观察期[：:]\s*(\d+)[日天年]',
            r'等待期.*?(\d+)[日天]'
        ],

        # 费率信息 (7个模式)
        'premium_rate': [
            r'年交\s*([0-9.]+)\s*元',
            r'保费[：:]\s*([0-9.]+)'
        ],
        'expense_rate': [
            r'费用率[：:]\s*([0-9.]+)%',
            r'附加费用率[：:]\s*([0-9.]+)%'
        ],
        'interest_rate': [
            r'预定利率[：:]\s*([0-9.]+)%',
            r'定价利率[：:]\s*([0-9.]+)%',
            r'年利率[：:]\s*([0-9.]+)%'
        ],

        # 犹豫期 (3个模式)
        'cooling_period': [
            r'犹豫期[：:]\s*(\d+)[日天]'
        ],

        # 现金价值 (3个模式)
        'cash_value': [
            r'现金价值[：:]\s*([^\n]+)',
            r'退保金[：:]\s*([^\n]+)'
        ]
    }

    def extract(self, document: str) -> ExtractResult:
        """执行规则提取"""
        result = {}
        confidence = {}

        for field, patterns in self.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, document, re.MULTILINE | re.IGNORECASE)
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
            except (ValueError, TypeError):
                score -= 0.2

        # 费用率合理性
        if 'expense_rate' in data:
            try:
                rate_str = str(data['expense_rate']).replace('%', '').replace('，', '.')
                rate = float(rate_str)
                if not (0 <= rate <= 50):
                    score -= 0.2
            except (ValueError, TypeError):
                score -= 0.1

        # 等待期合理性
        if 'waiting_period' in data:
            try:
                period = int(data['waiting_period'])
                if not (0 <= period <= 365):
                    score -= 0.2
            except (ValueError, TypeError):
                score -= 0.1

        return max(score, 0.0)


class LLMEnhancer:
    """LLM增强器 - 使用智谱GLM补充和验证规则提取结果"""

    def __init__(self, client: BaseLLMClient, max_tokens: int = 8192):
        """
        初始化LLM增强器

        Args:
            client: LLM客户端实例
            max_tokens: 最大生成token数
        """
        self.client = client
        self.max_tokens = max_tokens

    def enhance(self, document: str, rule_result: ExtractResult) -> ExtractResult:
        """增强规则提取结果"""

        # 1. 识别缺失字段
        missing_fields = self._identify_missing(rule_result)

        if not missing_fields:
            logger.info("所有必需字段都已提取，无需LLM增强")
            return rule_result

        # 2. 构建增强提示
        prompt = self._build_enhance_prompt(document, rule_result, missing_fields)

        # 3. 调用LLM
        llm_response = self._call_llm(prompt)

        # 4. 解析结果
        llm_data = self._parse_llm_response(llm_response)

        # 5. 合并结果
        return self._merge_results(rule_result, llm_data)

    def extract_full(self, document: str) -> ExtractResult:
        """完整LLM提取"""
        prompt = self._build_full_extract_prompt(document)

        logger.info(f"Calling LLM with prompt length: {len(prompt)}")
        llm_response = self._call_llm(prompt)
        logger.info(f"LLM response length: {len(llm_response)}, preview: {llm_response[:200]}")

        llm_data = self._parse_llm_response(llm_response)
        logger.info(f"Parsed LLM data keys: {list(llm_data.keys())}")

        return ExtractResult(
            data=llm_data,
            confidence={k: 0.75 for k in llm_data},
            provenance={k: 'llm' for k in llm_data}
        )

    def _identify_missing(self, rule_result: ExtractResult) -> set:
        """识别缺失或低置信度字段"""
        missing = set()

        for field in QualityAssessor.REQUIRED_FIELDS:
            if field not in rule_result.data:
                missing.add(field)
            elif rule_result.confidence.get(field, 1.0) < 0.7:
                missing.add(field)

        return missing

    def _build_enhance_prompt(self, document: str, rule_result: ExtractResult, missing: set) -> str:
        """构建增强提示"""
        return f"""你是保险产品信息提取专家。给定保险文档和已有的规则提取结果，请补充以下缺失字段：

缺失字段: {', '.join(missing)}

已有规则提取结果:
```json
{json.dumps(rule_result.data, ensure_ascii=False, indent=2)}
```

请从以下文档中提取缺失字段:
```
{document[:6000]}
```

返回格式:
```json
{{
    "field_name": "提取的值",
    "field_name2": "提取的值2"
}}
```

只返回JSON，不要其他内容。"""

    def _build_full_extract_prompt(self, document: str) -> str:
        """构建完整提取提示"""
        return f"""你是保险产品文档解析专家。请分析以下保险产品文档，提取结构化信息。

**重要要求**:
1. 识别并忽略"阅读指引"、"投保须知"、"产品说明"等非条款内容
2. 只提取"条款正文"中的真正条款
3. 过滤HTML标签、格式化字符
4. 提取产品基本信息和所有条款内容

文档内容:
```
{document[:8000]}
```

请返回JSON格式:
```json
{{
    "product_info": {{
        "product_name": "产品名称",
        "insurance_company": "保险公司",
        "product_type": "产品类型",
        "insurance_period": "保险期间",
        "payment_method": "缴费方式",
        "age_min": "最低投保年龄",
        "age_max": "最高投保年龄",
        "waiting_period": "等待期天数"
    }},
    "clauses": [
        {{"text": "第一条的完整条款内容", "reference": "第一条"}},
        {{"text": "第二条的完整条款内容", "reference": "第二条"}},
        {{"text": "第三条的完整条款内容", "reference": "第三条"}}
    ],
    "pricing_params": {{
        "interest_rate": "预定利率",
        "expense_rate": "费用率",
        "premium_rate": "保费"
    }}
}}
```

只返回JSON，不要其他内容。"""

    def _call_llm(self, prompt: str) -> str:
        """调用LLM"""
        try:
            # 使用配置的max_tokens，确保LLM有足够空间返回完整JSON响应
            # 结构化数据通常需要更多tokens来包含完整的条款内容
            response = self.client.generate(prompt, max_tokens=self.max_tokens)
            logger.info(f"LLM调用完成，max_tokens={self.max_tokens}, 响应长度={len(response)}")
            return response
        except Exception as e:
            import traceback
            logger.warning(f"LLM调用失败: {e}")
            logger.warning(f"异常详情: {traceback.format_exc()}")
            return "{}"

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析LLM响应"""
        try:
            # 尝试多种方式提取JSON

            # 方法1: 提取markdown代码块中的JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))

            # 方法2: 查找JSON对象模式
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass

            # 方法3: 尝试直接解析整个响应
            cleaned = response.strip()
            if cleaned.startswith('{') and cleaned.endswith('}'):
                return json.loads(cleaned)

            logger.warning(f"LLM响应JSON解析失败: {response[:200]}")
            return {}

        except json.JSONDecodeError as e:
            logger.warning(f"LLM响应JSON解析失败: {e}, 响应: {response[:200]}")
            return {}

    def _merge_results(self, rule_result: ExtractResult, llm_data: Dict) -> ExtractResult:
        """合并规则和LLM结果"""
        merged_data = {**rule_result.data}
        merged_confidence = {**rule_result.confidence}
        merged_provenance = {**rule_result.provenance}

        # 展开llm_data（可能包含嵌套结构）
        flat_llm_data = self._flatten_dict(llm_data)

        for field, value in flat_llm_data.items():
            if value and str(value).strip():  # 只添加非空值
                merged_data[field] = value
                merged_confidence[field] = 0.75  # LLM增强置信度
                merged_provenance[field] = 'llm_enhanced'

        return ExtractResult(
            data=merged_data,
            confidence=merged_confidence,
            provenance=merged_provenance
        )

    def _flatten_dict(self, d: Dict, parent_key: str = '', sep: str = '_') -> Dict:
        """展平嵌套字典"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                # 处理clauses列表
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        items.extend(self._flatten_dict(item, f"{new_key}_{i}", sep=sep).items())
                    else:
                        items.append((f"{new_key}_{i}", item))
            else:
                items.append((new_key, v))
        return dict(items)


class ResultFusion:
    """结果融合器 - LLM为主，规则验证"""

    def fuse(self, llm_result: ExtractResult, rule_result: ExtractResult) -> ExtractResult:
        """
        融合提取结果（LLM优先，规则验证）

        Args:
            llm_result: LLM提取结果（主要来源）
            rule_result: 规则提取结果（验证和补充）
        """
        if not llm_result or not llm_result.data:
            return rule_result

        fused_data = {}
        fused_confidence = {}
        fused_provenance = {}

        # 所有字段：优先LLM，规则补充缺失
        all_fields = set(llm_result.data) | set(rule_result.data)

        for field in all_fields:
            llm_value = llm_result.data.get(field)
            rule_value = rule_result.data.get(field)
            llm_conf = llm_result.confidence.get(field, 0.75)
            rule_conf = rule_result.confidence.get(field, 0.85)

            # 决策逻辑：LLM优先
            if llm_value:
                # LLM有结果，优先使用
                if rule_value and self._values_match(llm_value, rule_value):
                    # 规则验证通过，提升置信度
                    fused_data[field] = llm_value
                    fused_confidence[field] = max(llm_conf, rule_conf)
                    fused_provenance[field] = 'llm_validated'
                else:
                    # 使用LLM结果
                    fused_data[field] = llm_value
                    fused_confidence[field] = llm_conf
                    if rule_value:
                        fused_provenance[field] = 'llm_primary'
                    else:
                        fused_provenance[field] = 'llm'

            elif rule_value:
                # LLM没有，规则补充
                fused_data[field] = rule_value
                fused_confidence[field] = rule_conf * 0.9  # 规则补充略降权
                fused_provenance[field] = 'rule_fallback'

        return ExtractResult(
            data=fused_data,
            confidence=fused_confidence,
            provenance=fused_provenance
        )

    def _values_match(self, v1: str, v2: str) -> bool:
        """检查值是否匹配"""
        if not v1 or not v2:
            return False

        v1_str = str(v1).strip()
        v2_str = str(v2).strip()

        if v1_str == v2_str:
            return True

        # 标准化后比较
        v1_clean = re.sub(r'[^\d.]', '', v1_str)
        v2_clean = re.sub(r'[^\d.]', '', v2_str)

        if v1_clean and v2_clean:
            try:
                return float(v1_clean) == float(v2_clean)
            except ValueError:
                pass

        return False


class HybridExtractor:
    """混合提取器 - LLM完整提取 + 规则快速验证"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化混合提取器

        Args:
            config: 配置字典，如果为None则使用默认配置
        """
        if config is None:
            app_config = get_config()
            config = app_config.llm.to_client_config()

        self.config = config
        self.rule_extractor = RuleExtractor()
        self.quality_assessor = QualityAssessor()
        self.llm_client = LLMClientFactory.create_client(config)

        # 从配置中获取max_tokens，如果没有则使用默认值8192
        # GLM-4.7-Flash支持最高128k输出，设置较大值确保完整提取
        self.max_tokens = config.get('max_tokens', 8192)

        self.llm_enhancer = LLMEnhancer(self.llm_client, max_tokens=self.max_tokens)
        self.fusion = ResultFusion()

    def extract(self, document: str) -> ExtractResult:
        """执行混合提取（LLM完整提取 + 规则验证）"""

        logger.info("执行LLM完整提取...")

        # 步骤1: LLM完整提取（产品信息 + 条款内容）
        llm_result = self.llm_enhancer.extract_full(document)
        logger.info(f"LLM提取完成: {len(llm_result.data)}个字段")

        # 步骤2: 规则快速验证和补充
        rule_result = self.rule_extractor.extract(document)
        logger.info(f"规则验证完成: {len(rule_result.data)}个字段")

        # 步骤3: 结果融合（LLM为主，规则为辅）
        final_result = self.fusion.fuse(llm_result, rule_result)
        logger.info(f"最终结果: {len(final_result.data)}个字段")
        logger.info(f"最终来源: {final_result.get_source_summary()}")

        # 步骤4: 质量评估
        quality = self.quality_assessor.assess(final_result)
        score = quality.overall_score()

        logger.info(f"提取质量评分: {score}/100")
        logger.info(f"  - 完整性: {quality.completeness:.2f}")
        logger.info(f"  - 准确性: {quality.accuracy:.2f}")
        logger.info(f"  - 一致性: {quality.consistency:.2f}")
        logger.info(f"  - 合理性: {quality.reasonableness:.2f}")

        return final_result

    def extract_with_debug(self, document: str) -> Dict[str, Any]:
        """带调试信息的提取"""
        rule_result = self.rule_extractor.extract(document)
        quality = self.quality_assessor.assess(rule_result)
        score = quality.overall_score()

        llm_result = None
        if score < self.thresholds['excellent']:
            llm_result = self.llm_enhancer.extract_full(document)

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


# 便捷函数
def extract_document(document: str, config: Optional[Dict[str, Any]] = None) -> ExtractResult:
    """
    提取保险产品文档信息

    Args:
        document: 文档内容
        config: LLM配置（可选）

    Returns:
        ExtractResult: 提取结果
    """
    extractor = HybridExtractor(config)
    return extractor.extract(document)


if __name__ == '__main__':
    # 测试代码
    print("Testing Hybrid Extractor...")

    test_document = """
    # XX人寿保险产品

    第一条：保险责任
    本产品承担身故保险金责任，身故保险金为基本保额。

    第二条：责任免除
    发生以下情况保险公司不承担任何责任：
    1. 投保人故意造成被保险人死亡
    2. 被保险人酒后驾驶

    第三条：保险费
    本产品预定利率为3.5%，费用率为15%。
    """

    try:
        result = extract_document(test_document)
        print(f"提取结果: {result.data}")
        print(f"来源统计: {result.get_source_summary()}")
        print("Hybrid Extractor test completed!")
    except Exception as e:
        print(f"Test failed: {e}")
