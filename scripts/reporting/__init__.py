#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模块

提供面向对象的报告生成功能，包括：
- ReportGenerator: 审核报告生成器类，支持生成包含违规记录、定价分析、评分和评级的完整报告
"""
from .generator import ReportGenerator

__all__ = ['ReportGenerator']
