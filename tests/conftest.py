#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pytest 配置文件
"""
import sys
from pathlib import Path

# 添加 scripts 目录到 Python 路径
scripts_dir = Path(__file__).parent.parent / 'scripts'
sys.path.insert(0, str(scripts_dir))
sys.path.insert(0, str(scripts_dir / 'infrastructure'))

import pytest


def pytest_configure(config):
    """pytest 配置"""
    config.addinivalue_line(
        "markers",
        "unit: 单元测试"
    )
    config.addinivalue_line(
        "markers",
        "integration: 集成测试"
    )
    config.addinivalue_line(
        "markers",
        "slow: 慢速测试"
    )


@pytest.fixture
def sample_document_content():
    """示例文档内容"""
    return """# XX人寿保险产品

第一条：保险责任
本产品承担身故保险金责任，身故保险金为基本保额。

第二条：责任免除
发生以下情况保险公司不承担任何责任：
1. 投保人故意造成被保险人死亡
2. 被保险人酒后驾驶

第三条：保险费
本产品预定利率为3.5%，费用率为15%。
"""


@pytest.fixture
def sample_audit_params():
    """示例审核参数"""
    return {
        "documentContent": "# 测试保险产品\n\n简单测试内容。",
        "documentUrl": "https://test.example.com/policy",
        "auditType": "negative-only"
    }


@pytest.fixture
def sample_violations():
    """示例违规记录"""
    return [
        {
            "clause_text": "等待期为180天",
            "description": "等待期过长",
            "severity": "high",
            "category": "产品条款表述"
        },
        {
            "clause_text": "预定利率为3.5%",
            "description": "预定利率超过监管上限",
            "severity": "medium",
            "category": "产品费率厘定及精算假设"
        }
    ]


@pytest.fixture
def sample_product_info():
    """示例产品信息"""
    return {
        "product_name": "XX人寿保险",
        "insurance_company": "XX人寿保险股份有限公司",
        "product_type": "寿险",
        "insurance_period": "终身",
        "payment_method": "年交",
        "age_range": "0-65周岁",
        "occupation_class": "1-6类"
    }