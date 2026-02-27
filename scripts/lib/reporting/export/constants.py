#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx 文档常量

定义 docx-js 相关的常量，避免魔法数字散布在代码中
"""
from dataclasses import dataclass


@dataclass
class DocxUnits:
    """
    Docx 单位常量

    DXA (Twentieth of a Point) 是 Word 使用的长度单位
    1 英寸 = 1440 DXA
    1 磅 = 20 DXA
    """
    ONE_INCH_DXA = 1440      # 1 英寸
    ONE_POINT_DXA = 20       # 1 磅

    # 字号（半点单位）
    FONT_SIZE_NORMAL = 24    # 12pt
    FONT_SIZE_HEADING1 = 32  # 16pt
    FONT_SIZE_HEADING2 = 28  # 14pt
    FONT_SIZE_SMALL = 18     # 9pt


@dataclass
class DocxPage:
    """
    Docx 页面常量

    所有尺寸单位为 DXA
    """
    # US Letter 尺寸 (8.5" x 11")
    US_LETTER_WIDTH = 12240   # 8.5 英寸
    US_LETTER_HEIGHT = 15840  # 11 英寸

    # A4 尺寸 (210mm x 297mm，约 8.27" x 11.69")
    A4_WIDTH = 11906
    A4_HEIGHT = 16838

    # 默认边距（1 英寸）
    MARGIN_DEFAULT = 1440
    MARGIN_NARROW = 720       # 0.5 英寸
    MARGIN_WIDE = 2160        # 1.5 英寸

    # 默认使用 US Letter
    DEFAULT_WIDTH = US_LETTER_WIDTH
    DEFAULT_HEIGHT = US_LETTER_HEIGHT
    DEFAULT_MARGIN = MARGIN_DEFAULT


@dataclass
class DocxSpacing:
    """
    Docx 间距常量
    """
    # 段落间距（DXA）
    SPACING_BEFORE_HEADING1 = 240  # 12pt
    SPACING_AFTER_HEADING1 = 240
    SPACING_BEFORE_HEADING2 = 180  # 9pt
    SPACING_AFTER_HEADING2 = 180

    # 表格单元格内边距（DXA）
    CELL_MARGIN_TOP = 80
    CELL_MARGIN_BOTTOM = 80
    CELL_MARGIN_LEFT = 120
    CELL_MARGIN_RIGHT = 120


@dataclass
class DocxTable:
    """
    Docx 表格常量
    """
    # 内容宽度（页宽 - 左右边距）
    CONTENT_WIDTH_US_LETTER = DocxPage.US_LETTER_WIDTH - 2 * DocxPage.MARGIN_DEFAULT  # 9360
    CONTENT_WIDTH_A4 = DocxPage.A4_WIDTH - 2 * DocxPage.MARGIN_DEFAULT  # 8986

    # 默认内容宽度
    DEFAULT_CONTENT_WIDTH = CONTENT_WIDTH_US_LETTER


@dataclass
class DocxStyle:
    """
    Docx 样式常量
    """
    # 字体
    DEFAULT_FONT = "Arial"

    # 颜色
    COLOR_BLACK = "000000"
    COLOR_GRAY = "999999"
    COLOR_BORDER = "CCCCCC"
    COLOR_HEADER_BG = "D5E8F0"

    # 表格边框样式
    BORDER_STYLE = "SINGLE"
    BORDER_SIZE = 1


# 合并所有常量到一个类中方便使用
class DocxConstants:
    """Docx 文档常量集合"""
    Units = DocxUnits
    Page = DocxPage
    Spacing = DocxSpacing
    Table = DocxTable
    Style = DocxStyle

    # 快捷访问
    FONT = DocxStyle.DEFAULT_FONT
    US_LETTER_WIDTH = DocxPage.US_LETTER_WIDTH
    US_LETTER_HEIGHT = DocxPage.US_LETTER_HEIGHT
    ONE_INCH = DocxUnits.ONE_INCH_DXA
    CONTENT_WIDTH = DocxTable.DEFAULT_CONTENT_WIDTH
