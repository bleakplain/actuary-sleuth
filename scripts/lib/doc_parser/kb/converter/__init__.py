#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel 检查清单 → Markdown 知识库转换器

将 Excel 格式的产品开发检查清单转换为结构化 Markdown 文件。
每个 sheet 按法规粒度拆分，提取元数据标签，处理内嵌表格图片。
"""
from .excel_to_md import convert_excel_to_markdown

__all__ = ['convert_excel_to_markdown']
