#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并发提取使用示例

演示如何启用和使用并发LLM调用
"""
import os
from lib.extraction import DocumentExtractor

# 示例1: 通过配置文件启用
def example_with_config():
    """通过配置字典启用并发"""
    config = {
        'concurrent': {
            'enable': True,
            'max_concurrent': 5  # glm-4-flash 推荐
        },
        'llm_config': {
            'provider': 'zhipu',
            'model': 'glm-4-flash',
            'api_key': os.getenv('ZHIPU_API_KEY')
        }
    }

    extractor = DocumentExtractor(config=config)

    # 处理文档
    with open('document.txt', 'r') as f:
        document = f.read()

    result = extractor.extract(document)
    print(f"提取完成，质量评分: {result.data}")


# 示例2: 通过环境变量启用
def example_with_env():
    """通过环境变量启用并发"""
    # 设置环境变量
    os.environ['ACTUARY_CONCURRENT_ENABLED'] = 'true'
    os.environ['ACTUARY_MAX_CONCURRENT'] = '3'

    extractor = DocumentExtractor()

    # 使用相同的接口
    result = extractor.extract(document)


# 示例3: 代码直接设置
def example_direct_set():
    """直接设置并发属性"""
    extractor = DocumentExtractor()
    extractor.enable_concurrent = True
    extractor.max_concurrent = 5


# 示例4: 不同模型的推荐配置
def model_configs():
    """不同模型的推荐配置"""
    configs = {
        'glm-4-flash': {
            'concurrent': {'enable': True, 'max_concurrent': 5}
        },
        'glm-4-air': {
            'concurrent': {'enable': True, 'max_concurrent': 3}
        },
        'glm-4-plus': {
            'concurrent': {'enable': True, 'max_concurrent': 2}
        }
    }

    model = 'glm-4-flash'
    extractor = DocumentExtractor(config=configs[model])
