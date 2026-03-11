#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预处理模块使用示例

演示如何使用新的预处理模块进行文档提取
"""
import os
from lib.llm_client import LLMClientFactory
from lib.preprocessing import DocumentExtractor, create_extractor

# 示例1: 使用便捷函数创建提取器
def example_with_factory():
    """使用便捷函数创建提取器"""
    llm_config = {
        'provider': 'zhipu',
        'model': 'glm-4-flash',
        'api_key': os.getenv('ZHIPU_API_KEY')
    }

    llm_client = LLMClientFactory.create_client(llm_config)
    extractor = create_extractor(llm_client)

    # 处理文档
    with open('document.txt', 'r') as f:
        document = f.read()

    result = extractor.extract(document, source_type='text')
    print(f"提取完成，提取模式: {result.metadata.get('extraction_mode')}")
    print(f"产品类型: {result.metadata.get('product_type')}")
    print(f"验证分数: {result.metadata.get('validation_score')}")


# 示例2: 直接创建提取器
def example_direct():
    """直接创建提取器"""
    llm_config = {
        'provider': 'zhipu',
        'model': 'glm-4-flash',
        'api_key': os.getenv('ZHIPU_API_KEY')
    }

    llm_client = LLMClientFactory.create_client(llm_config)
    extractor = DocumentExtractor(llm_client)

    # 使用相同的接口
    result = extractor.extract(document, source_type='text')
    print(result.data)


# 示例3: 指定提取字段
def example_with_fields():
    """指定需要提取的字段"""
    llm_client = LLMClientFactory.create_client({
        'provider': 'zhipu',
        'model': 'glm-4-flash',
        'api_key': os.getenv('ZHIPU_API_KEY')
    })

    extractor = DocumentExtractor(llm_client)

    # 只提取特定字段
    result = extractor.extract(
        document,
        source_type='text',
        required_fields=['product_name', 'insurance_company', 'waiting_period']
    )
