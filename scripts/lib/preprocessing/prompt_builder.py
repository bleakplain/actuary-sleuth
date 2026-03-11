#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt 构建器

组件化的 Prompt 构建，支持动态生成针对不同产品类型的 Prompt。
"""
import json
import logging
from typing import Dict, List


logger = logging.getLogger(__name__)


class PromptBuilder:
    """Prompt 构建器 - 组件化设计"""

    # 组件库
    COMPONENTS = {
        # 基础组件
        'role_base': """你是保险产品文档解析专家。

**任务**: 从保险产品文档中提取结构化信息。
""",

        'role_specialized': """你是{product_type}产品提取专家。

**提取重点**: {extraction_focus}
""",

        # 字段说明组件
        'field_product_info': """
**产品基本信息**:
- product_name: 产品名称
- insurance_company: 保险公司
- product_type: 产品类型
- insurance_period: 保险期间（如：20年、至70岁、终身）
- payment_method: 缴费方式（如：年交、月交、趸交）
- payment_period: 缴费期间
- waiting_period: 等待期天数
- cooling_period: 犹豫期天数
- age_min: 最低投保年龄
- age_max: 最高投保年龄
""",

        'field_diseases': """
**病种信息**:
- covered_diseases: 保障的疾病列表
  - disease_name: 疾病名称
  - disease_grade: 疾病分级（轻症/中症/重症）
  - payout_ratio: 赔付比例（如：0.5 表示 50%，1.0 表示 100%）
  - waiting_period: 该疾病的等待期天数
""",

        'field_coverage': """
**保障范围**:
- coverage: 保障范围
  - inpatient: 住院保障说明
  - outpatient: 门诊保障说明
  - emergency: 急诊保障说明
  - exclusions: 免责内容
""",

        'field_deductible': """
**免赔额**:
- deductible: 免赔额
  - general: 一般免赔额
  - by_hospital_grade: 按医院等级的免赔额
""",

        'field_payout_ratio': """
**赔付比例**:
- payout_ratio: 赔付比例
  - by_hospital_grade: 按医院等级的赔付比例
  - by_expense_type: 按费用类型的赔付比例
""",

        'field_limits': """
**限额**:
- limits: 限额
  - annual_limit: 年度总限额
  - per_claim_limit: 单次限额
  - inpatient_limit: 住院限额
  - outpatient_limit: 门诊限额
""",

        'field_account': """
**账户管理**:
- account_management: 账户管理信息
  - initial_premium: 初始保费
  - minimum_premium: 最低保费
  - add_premium_rules: 追加保费规则
  - partial_withdrawal_rules: 部分领取规则
  - withdrawal_fee: 手续费说明
""",

        'field_settlement_rate': """
**结算利率**:
- settlement_rate: 结算利率
  - guaranteed_rate: 保证利率
  - current_rate: 当前利率
  - historical_rates: 历史利率
""",

        'field_death_benefit': """
**身故保险金**:
- death_benefit: 身故保险金
  - option_a: 选项A（保额固定）
  - option_b: 选项B（保额递增或账户价值）
  - adjustment_rules: 保额调整规则
""",

        # 输出格式组件
        'output_structure': """
**输出要求**:
1. 必须且只能返回 JSON 格式
2. 不要包含任何解释、分析或说明文字
3. 不要使用 markdown 代码块
4. 直接返回 JSON

**输出格式**:
```json
{output_schema}
```
""",

        # 混合产品说明
        'hybrid_notice': """
**注意**: 这是一个组合产品，请分别提取不同产品类型的信息。例如，如果同时包含重疾险和医疗险，请在结果中明确区分。
""",
    }

    def build(self,
              product_type: str,
              required_fields: List[str],
              extraction_focus: List[str],
              output_schema: Dict,
              is_hybrid: bool = False) -> str:
        """
        构建 Prompt

        Args:
            product_type: 产品类型代码
            required_fields: 需要提取的字段
            extraction_focus: 提取重点
            output_schema: 输出 Schema
            is_hybrid: 是否为混合产品

        Returns:
            构建好的 Prompt
        """
        # 1. 角色定义
        if extraction_focus:
            prompt = self.COMPONENTS['role_specialized'].format(
                product_type=self._get_type_name(product_type),
                extraction_focus='、'.join(extraction_focus)
            )
        else:
            prompt = self.COMPONENTS['role_base']

        # 2. 添加字段说明
        field_components = self._get_field_components(required_fields)
        for component in field_components:
            if component in self.COMPONENTS:
                prompt += self.COMPONENTS[component]

        # 3. 混合产品特殊说明
        if is_hybrid:
            prompt += "\n"
            prompt += self.COMPONENTS['hybrid_notice']

        # 4. 输出格式
        prompt += "\n"
        prompt += self.COMPONENTS['output_structure'].format(
            output_schema=json.dumps(output_schema, ensure_ascii=False, indent=2)
        )

        return prompt

    def _get_type_name(self, code: str) -> str:
        """获取产品类型中文名"""
        type_names = {
            'critical_illness': '重大疾病险',
            'medical_insurance': '医疗保险',
            'universal_life': '万能险',
            'term_life': '定期寿险',
            'whole_life': '终身寿险',
            'annuity': '年金保险',
            'accident_insurance': '意外伤害保险',
            'life_insurance': '人身保险',
        }
        return type_names.get(code, '保险')

    def _get_field_components(self, fields: List[str]) -> List[str]:
        """获取字段对应的组件"""
        component_map = {
            'product_name': ['field_product_info'],
            'insurance_company': ['field_product_info'],
            'product_type': ['field_product_info'],
            'insurance_period': ['field_product_info'],
            'payment_method': ['field_product_info'],
            'waiting_period': ['field_product_info'],
            'covered_diseases': ['field_diseases'],
            'coverage': ['field_coverage'],
            'deductible': ['field_deductible'],
            'payout_ratio': ['field_payout_ratio'],
            'limits': ['field_limits'],
            'account_management': ['field_account'],
            'settlement_rate': ['field_settlement_rate'],
            'death_benefit': ['field_death_benefit'],
        }

        components = set()
        for field in fields:
            if field in component_map:
                components.update(component_map[field])

        # 如果有产品相关字段，始终添加产品信息组件
        if any(f in ['product_name', 'insurance_company'] for f in fields):
            components.add('field_product_info')

        return list(components)
