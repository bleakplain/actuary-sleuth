#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx 章节生成器

负责生成文档的各个章节部分
"""
from typing import Dict, List, Any, TYPE_CHECKING

from lib.common.logger import get_logger
from .constants import DocxConstants

if TYPE_CHECKING:
    from lib.common.models import Product

logger = get_logger('docx_sections')


class DocxSectionGenerator:
    """Docx 章节生成器"""

    def __init__(self):
        self.C = DocxConstants

    def _escape_js(self, text: str) -> str:
        if not text:
            return ''
        return (text
                .replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace("'", "\\'")
                .replace('\n', '\\n')
                .replace('\r', '')
                .replace('\t', '\\t'))

    def generate_heading_paragraph(self, text: str, level: int = 2) -> str:
        escaped_text = self._escape_js(text)
        return f'''                new Paragraph({{
                    text: "{escaped_text}",
                    heading: HeadingLevel.HEADING_{level},
                }}),'''

    def generate_text_paragraph(self, text: str) -> str:
        escaped_text = self._escape_js(text)
        return f'''                new Paragraph({{
                    text: "{escaped_text}",
                }}),'''

    def generate_bold_text_paragraph(self, text: str, size: int = 28) -> str:
        escaped_text = self._escape_js(text)
        return f'''                new Paragraph({{
                    children: [new TextRun({{ text: "{escaped_text}", bold: true, size: {size} }})]
                }}),'''

    def generate_field_paragraph(self, label: str, value: str) -> str:
        escaped_label = self._escape_js(label)
        escaped_value = self._escape_js(value)
        return f'''                new Paragraph({{
                    children: [
                        new TextRun({{ text: "{escaped_label}: ", bold: true }}),
                        new TextRun({{ text: "{escaped_value}" }})
                    ]
                }}),'''

    def generate_product_section(self, product: 'Product') -> str:
        sections = []
        sections.append(self.generate_heading_paragraph("产品信息", 2))

        rows = [
            ["产品名称", product.name or "未提供"],
            ["产品类型", product.type or "未提供"],
            ["保险公司", product.company or "未提供"],
            ["版本号", product.version or "未提供"],
        ]

        if product.document_url:
            rows.append(["文档链接", product.document_url])

        sections.append(self._generate_simple_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_simple_table(self, rows: List[List[str]]) -> str:
        if not rows:
            return ''

        C = self.C
        col_widths = [C.Table.DEFAULT_CONTENT_WIDTH // 3, (C.Table.DEFAULT_CONTENT_WIDTH // 3) * 2]
        table_width = C.Table.DEFAULT_CONTENT_WIDTH

        lines = [
            '                new Table({',
            f'                    width: {{ size: {table_width}, type: WidthType.DXA }},',
            f'                    columnWidths: {col_widths},',
            '                    rows: [',
        ]

        for row in rows:
            cells = []
            for idx, cell in enumerate(row):
                escaped_cell = self._escape_js(cell)
                col_width = col_widths[idx]
                cells.append(f'''                            new TableCell({{
                                width: {{ size: {col_width}, type: WidthType.DXA }},
                                children: [new Paragraph({{ text: "{escaped_cell}" }})]
                            }})''')

            lines.append(f'                        new TableRow({{')
            lines.append(f'                            children: [')
            lines.append(',\n'.join(cells))
            lines.append('                            ]')
            lines.append('                        }),')

        lines.extend([
            '                    ]',
            '                }),',
        ])

        return '\n'.join(lines)

    def generate_data_table(self, rows: List[List[str]]) -> str:
        if not rows:
            return ''

        C = self.C
        num_cols = len(rows[0])
        content_width = C.Table.DEFAULT_CONTENT_WIDTH

        if num_cols == 2:
            col_widths = [content_width // 3, (content_width // 3) * 2]
        elif num_cols == 3:
            col_widths = [content_width // 6, content_width // 3, content_width // 2]
        elif num_cols == 4:
            col_widths = [content_width // 8, content_width // 4, content_width // 3, (content_width // 3) - (content_width // 24)]
        else:
            col_width = content_width // num_cols
            col_widths = [col_width] * num_cols

        table_width = content_width

        lines = [
            '                new Table({',
            f'                    width: {{ size: {table_width}, type: WidthType.DXA }},',
            f'                    columnWidths: {col_widths},',
            '                    rows: [',
        ]

        for row_idx, row in enumerate(rows):
            cells = []
            for col_idx, cell in enumerate(row):
                escaped_cell = self._escape_js(cell)
                col_width = col_widths[col_idx]
                is_header = (row_idx == 0)
                if is_header:
                    cells.append(f'''                            new TableCell({{
                                width: {{ size: {col_width}, type: WidthType.DXA }},
                                children: [new Paragraph({{ children: [new TextRun({{ text: "{escaped_cell}", bold: true }})] }})]
                            }})''')
                else:
                    cells.append(f'''                            new TableCell({{
                                width: {{ size: {col_width}, type: WidthType.DXA }},
                                children: [new Paragraph({{ text: "{escaped_cell}" }})]
                            }})''')

            lines.append(f'                        new TableRow({{')
            lines.append(f'                            children: [')
            lines.append(',\n'.join(cells))
            lines.append('                            ]')
            lines.append('                        }),')

        lines.extend([
            '                    ]',
            '                }),',
        ])

        return '\n'.join(lines)
