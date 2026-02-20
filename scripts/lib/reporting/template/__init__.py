#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模板模块

使用模板方法模式生成审核报告：

- report_template.py: ReportGenerationTemplate类，定义报告生成的固定流程
  1. 计算评分 (_calculate_score)
  2. 确定评级 (_calculate_grade)
  3. 生成摘要 (_generate_summary)
  4. 生成内容 (_generate_content)
  5. 生成块 (_generate_blocks)
"""
from .report_template import ReportGenerationTemplate

__all__ = ['ReportGenerationTemplate']
