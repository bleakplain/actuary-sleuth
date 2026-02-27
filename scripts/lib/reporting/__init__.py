#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模块

提供面向对象的报告生成功能，按功能模块化组织：

- template/   : ReportGenerationTemplate类，使用模板方法模式生成报告
- export/     : Docx文档导出（生成 + 推送到飞书）
- strategies/ : 策略模式实现，包含整改策略等
"""
# 从子模块导出主要类
from .template import ReportGenerationTemplate
from .export import DocxExporter, export_docx

__all__ = [
    'ReportGenerationTemplate',
    'DocxExporter',
    'export_docx',
]
