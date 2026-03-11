#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理常量配置
"""

# 分块配置
DEFAULT_CHUNK_SIZE = 6000
DEFAULT_OVERLAP = 1500
DEFAULT_CHUNK_THRESHOLD = 10000
DEFAULT_MAX_CONCURRENT = 1  # 默认串行

# 模型并发数推荐
MODEL_CONCURRENT_MAP = {
    'glm-4-flash': 5,
    'glm-4-air': 3,
    'glm-4-plus': 2,
}

# LLM 调用限流配置
LLM_TARGET_QPS = 1.0  # 目标每秒请求数（用于计算请求间延迟）
LLM_MAX_RETRIES = 2  # 最大重试次数
LLM_RETRY_BASE_DELAY = 2.0  # 基础重试延迟（秒）
LLM_RETRY_MAX_DELAY = 60.0  # 最大重试延迟（秒）

# 文档长度限制
MAX_DOCUMENT_LENGTH = 12000
MIN_DOCUMENT_LENGTH = 100

# LLM 配置
LLM_MAX_TOKENS = 16384
LLM_DEFAULT_CONFIDENCE = 0.75

# 分块策略配置
TABLE_DENSITY_THRESHOLD = 0.5  # 表格密度阈值
DENSITY_CALCULATION_MULTIPLIER = 1000  # 密度计算乘数（每1000字符）

# 质量评估权重
QUALITY_WEIGHTS = {
    'completeness': 0.40,
    'accuracy': 0.35,
    'consistency': 0.15,
    'reasonableness': 0.10,
}

# 去重参数
DEDUP_PREFIX_LENGTH = 200
DEDUP_SUFFIX_LENGTH = 100

# 分块策略阈值
SECTION_MIN_COUNT = 5  # 最少章节数才使用章节分块
