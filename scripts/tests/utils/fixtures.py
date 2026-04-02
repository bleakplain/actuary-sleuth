#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试工具函数
"""
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db_path():
    """临时数据库路径"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)


@pytest.fixture
def sample_feishu_url():
    """模拟飞书URL"""
    return "https://test.feishu.cn/docx/test12345678"


@pytest.fixture
def sample_document_content():
    """示例文档内容"""
    return """
# 产品名称

## 投保年龄
0-65周岁

## 保险期间
1年

## 等待期
90天

## 保险责任
意外身故保险金：被保险人因遭受意外伤害，并自意外伤害发生之日起180日内以该次意外伤害为直接原因身故的，保险公司按保险金额给付意外身故保险金，本合同终止。
"""


@pytest.fixture
def sample_clauses():
    """示例条款"""
    return [
        {"number": "第一条", "title": "保险责任", "text": "被保险人因遭受意外伤害，保险公司按保险金额给付保险金。"},
        {"number": "第二条", "title": "责任免除", "text": "因下列情形之一导致被保险人身故的，保险公司不承担保险责任。"},
        {"number": "第三条", "title": "保险期间", "text": "本合同保险期间为1年。"},
    ]


def create_test_clauses(count: int = 10) -> list:
    """创建测试条款"""
    return [
        {"number": f"第{i}条", "title": f"测试条款{i}", "text": f"内容{i}" * 50}
        for i in range(1, count + 1)
    ]


def create_test_product():
    """创建测试产品"""
    from lib.common.models import Product, ProductCategory
    return Product(
        name="测试产品",
        company="测试公司",
        category=ProductCategory.HEALTH,
        period="1年",
        waiting_period=90,
        age_min=0,
        age_max=65
    )
