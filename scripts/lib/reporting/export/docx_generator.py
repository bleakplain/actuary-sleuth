#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx文档生成器（内部实现）

_DocxGenerator类：负责将EvaluationContext转换为Word文档

职责：
- 将EvaluationContext转换为docx-js JavaScript代码
- 调用Node.js执行生成.docx文件
- 可选：使用docx skill验证生成的文档

注意：此模块为内部实现，不直接对外暴露
"""
import os
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

from lib.exceptions import ExportException


class _DocxGenerator:
    """
    Docx文档生成器（内部实现）

    负责将EvaluationContext转换为Word文档
    """

    # docx skill路径（用于验证）
    DOCX_SKILL_PATH = "/root/.agents/skills/docx"

    def __init__(
        self,
        output_dir: Optional[str] = None,
        validate: bool = False
    ):
        """
        初始化Word文档生成器

        Args:
            output_dir: 输出目录，默认为系统临时目录
            validate: 是否验证生成的文档（使用docx skill）
        """
        self._output_dir = output_dir or tempfile.gettempdir()
        self._validate = validate
        self._docx_skill_path = Path(self.DOCX_SKILL_PATH)

    def generate(
        self,
        context: 'EvaluationContext',
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成Word文档

        Args:
            context: 评估上下文对象
            title: 文档标题（可选）

        Returns:
            dict: 包含生成结果的字典
                - success: 是否成功
                - file_path: 本地文件路径（成功时）
                - file_size: 文件大小（字节）
                - title: 文档标题
                - validation_result: 验证结果（validate=True时）
                - error: 错误信息（失败时）
        """
        try:
            # 1. 生成默认标题
            if title is None:
                timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                product_name = context.product.name or "未命名产品"
                title = f"{product_name}_审核报告_{timestamp}"

            # 2. 生成docx-js代码
            js_code = self._generate_docx_js_code(context, title)

            # 3. 写入临时JavaScript文件
            js_file = self._write_temp_js(js_code, title)

            # 4. 执行生成docx文件
            docx_file = self._execute_docx_generation(js_file, title)

            # 5. 可选：验证文档
            validation_result = None
            if self._validate:
                validation_result = self._validate_docx(docx_file)

            # 6. 返回结果
            file_size = os.path.getsize(docx_file)

            return {
                'success': True,
                'file_path': docx_file,
                'file_size': file_size,
                'title': title,
                'validation_result': validation_result
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _generate_docx_js_code(
        self,
        context: 'EvaluationContext',
        title: str
    ) -> str:
        """
        生成docx-js JavaScript代码

        Args:
            context: 评估上下文对象
            title: 文档标题

        Returns:
            str: JavaScript代码
        """
        # 提取数据
        product_info = context.product
        violations = context.violations
        pricing_analysis = context.pricing_analysis
        score = context.score or 0
        grade = context.grade or "未评级"
        summary = context.summary or {}

        # 生成JavaScript代码
        escaped_title = self._escape_js(title)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        output_path = f"{self._output_dir}/{title}.docx"

        parts = [
            '''const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        WidthType, AlignmentType, HeadingLevel, BorderStyle } = require('docx');
const fs = require('fs');

async function createAuditReport() {
    const doc = new Document({
        styles: {
            default: {
                document: {
                    run: { font: "Arial", size: 24 }
                }
            },
            paragraphStyles: [
                {
                    id: "Heading1",
                    name: "Heading 1",
                    basedOn: "Normal",
                    next: "Normal",
                    quickFormat: true,
                    run: { size: 32, bold: true, font: "Arial" },
                    paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 }
                },
                {
                    id: "Heading2",
                    name: "Heading 2",
                    basedOn: "Normal",
                    next: "Normal",
                    quickFormat: true,
                    run: { size: 28, bold: true, font: "Arial" },
                    paragraph: { spacing: { before: 180, after: 180 }, outlineLevel: 1 }
                }
            ]
        },
        sections: [{
            properties: {
                page: {
                    size: {
                        width: 12240,
                        height: 15840
                    },
                    margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
                }
            },
            children: [
                new Paragraph({
                    text: "''',
            escaped_title,
            '''",
                    heading: HeadingLevel.HEADING_1,
                    alignment: AlignmentType.CENTER,
                }),
'''
        ]

        # 添加产品基本信息
        parts.append(self._generate_product_info_section(product_info))

        # 添加评分概览
        parts.append(self._generate_score_section(score, grade, summary))

        # 添加定价分析
        parts.append(self._generate_pricing_section(pricing_analysis))

        # 添加违规详情
        parts.append(self._generate_violations_section(violations))

        # 添加审核依据
        if context.regulation_basis:
            parts.append(self._generate_regulation_section(context.regulation_basis))

        # 添加页脚
        parts.extend([
            '''                new Paragraph({
                    text: "",
                }),
                new Paragraph({
                    children: [
                        new TextRun({
                            text: "报告生成时间: ''',
            timestamp,
            '''",
                            size: 18,
                            color: "999999"
                        })
                    ],
                    alignment: AlignmentType.RIGHT,
                }),
            ]
        }]
    });

    const buffer = await Packer.toBuffer(doc);
    const outputPath = "''',
            output_path.replace('\\', '\\\\'),
            '''";
    fs.writeFileSync(outputPath, buffer);
    console.log(outputPath);
    return outputPath;
}

createAuditReport()
    .then(path => console.log("文档生成成功: " + path))
    .catch(err => {
        console.error("文档生成失败:", err);
        process.exit(1);
    });
'''
        ])

        return ''.join(parts)
    def _generate_product_info_section(self, product: '_InsuranceProduct') -> str:
        """生成产品信息部分"""
        sections = []
        sections.append('                new Paragraph({')
        sections.append('                    text: "产品信息",')
        sections.append('                    heading: HeadingLevel.HEADING_2,')
        sections.append('                }),')

        # 产品信息表格
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

    def _generate_score_section(
        self,
        score: int,
        grade: str,
        summary: Dict[str, Any]
    ) -> str:
        """生成评分概览部分"""
        sections = []
        sections.append('                new Paragraph({')
        sections.append('                    text: "审核评分",')
        sections.append('                    heading: HeadingLevel.HEADING_2,')
        sections.append('                }),')

        # 评分表格
        rows = [
            ["综合评分", f"{score} 分"],
            ["合规评级", grade],
        ]

        if summary:
            high_count = summary.get('high', 0)
            medium_count = summary.get('medium', 0)
            low_count = summary.get('low', 0)
            rows.extend([
                ["高危违规", str(high_count)],
                ["中危违规", str(medium_count)],
                ["低危违规", str(low_count)],
            ])

        sections.append(self._generate_simple_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_pricing_section(self, pricing: Dict[str, Any]) -> str:
        """生成定价分析部分"""
        if not pricing:
            return ''

        sections = []
        sections.append('                new Paragraph({')
        sections.append('                    text: "定价分析",')
        sections.append('                    heading: HeadingLevel.HEADING_2,')
        sections.append('                }),')

        rows = []
        for key, value in pricing.items():
            if isinstance(value, dict):
                item_value = value.get('value', '')
                item_benchmark = value.get('benchmark', '')
                item_deviation = value.get('deviation', 0)
                item_reasonable = value.get('reasonable', True)

                status = "✓ 合理" if item_reasonable else "✗ 不合理"
                rows.append([
                    self._get_pricing_label(key),
                    f"{item_value} (基准: {item_benchmark}, 偏差: {item_deviation:.1f}%) {status}"
                ])

        if rows:
            sections.append(self._generate_simple_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_violations_section(self, violations: List[Dict[str, Any]]) -> str:
        """生成违规详情部分"""
        if not violations:
            return '                new Paragraph({ text: "未发现违规问题", heading: HeadingLevel.HEADING_2 }),\n'

        sections = []
        sections.append('                new Paragraph({')
        sections.append('                    text: "违规详情",')
        sections.append('                    heading: HeadingLevel.HEADING_2,')
        sections.append('                }),')

        # 按严重程度分组
        high = [v for v in violations if v.get('severity') == 'high']
        medium = [v for v in violations if v.get('severity') == 'medium']
        low = [v for v in violations if v.get('severity') == 'low']

        # 高危违规
        if high:
            sections.append('                new Paragraph({')
            sections.append('                    children: [new TextRun({ text: "高危违规", bold: true, size: 28 })]')
            sections.append('                }),')
            for idx, v in enumerate(high, 1):
                sections.append(self._generate_violation_item(idx, v))

        # 中危违规
        if medium:
            sections.append('                new Paragraph({')
            sections.append('                    children: [new TextRun({ text: "中危违规", bold: true, size: 28 })]')
            sections.append('                }),')
            for idx, v in enumerate(medium, 1):
                sections.append(self._generate_violation_item(idx, v))

        # 低危违规
        if low:
            sections.append('                new Paragraph({')
            sections.append('                    children: [new TextRun({ text: "低危违规", bold: true, size: 28 })]')
            sections.append('                }),')
            for idx, v in enumerate(low, 1):
                sections.append(self._generate_violation_item(idx, v))

        return '\n'.join(sections) + '\n'

    def _generate_violation_item(self, index: int, violation: Dict[str, Any]) -> str:
        """生成单个违规项"""
        rule = violation.get('rule', '')
        description = violation.get('description', '')
        category = violation.get('category', '')
        remediation = violation.get('remediation', '')

        lines = [
            '                new Paragraph({',
            '                    children: [',
        ]

        # 序号和描述
        lines.append(f'                        new TextRun({{ text: "{index}. ", bold: true }}),')
        lines.append(f'                        new TextRun({{ text: "{self._escape_js(description)}" }}),')
        lines.append('                    ],')
        lines.append('                }),')

        # 规则编号
        if rule:
            lines.append('                new Paragraph({')
            lines.append('                    children: [')
            lines.append(f'                        new TextRun({{ text: "规则编号: ", bold: true }}),')
            lines.append(f'                        new TextRun({{ text: "{self._escape_js(rule)}" }}),')
            lines.append('                    ]')
            lines.append('                }),')

        # 类别
        if category:
            lines.append('                new Paragraph({')
            lines.append('                    children: [')
            lines.append(f'                        new TextRun({{ text: "类别: ", bold: true }}),')
            lines.append(f'                        new TextRun({{ text: "{self._escape_js(category)}" }}),')
            lines.append('                    ]')
            lines.append('                }),')

        # 整改建议
        if remediation:
            lines.append('                new Paragraph({')
            lines.append('                    children: [')
            lines.append(f'                        new TextRun({{ text: "整改建议: ", bold: true }}),')
            lines.append(f'                        new TextRun({{ text: "{self._escape_js(remediation)}" }}),')
            lines.append('                    ]')
            lines.append('                }),')

        return '\n'.join(lines)

    def _generate_regulation_section(self, regulations: List[str]) -> str:
        """生成审核依据部分"""
        if not regulations:
            return ''

        sections = []
        sections.append('                new Paragraph({')
        sections.append('                    text: "审核依据",')
        sections.append('                    heading: HeadingLevel.HEADING_2,')
        sections.append('                }),')

        for reg in regulations:
            sections.append('                new Paragraph({')
            sections.append(f'                    text: "{self._escape_js(reg)}",')
            sections.append('                }),')

        return '\n'.join(sections) + '\n'

    def _generate_simple_table(self, rows: List[List[str]]) -> str:
        """生成简单表格代码"""
        if not rows:
            return ''

        # 计算列宽（内容宽度9360 DXA）
        num_cols = len(rows[0])
        col_width = 9360 // num_cols
        col_widths = [col_width] * num_cols

        lines = [
            '                new Table({',
            f'                    width: {{ size: 9360, type: WidthType.DXA }},',
            f'                    columnWidths: {col_widths},',
            '                    rows: [',
        ]

        for row_idx, row in enumerate(rows):
            cells = []
            for cell in row:
                escaped_cell = self._escape_js(cell)
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

    def _write_temp_js(self, js_code: str, title: str) -> str:
        """写入临时JavaScript文件"""
        js_file = os.path.join(self._output_dir, f"{title}.js")
        with open(js_file, 'w', encoding='utf-8') as f:
            f.write(js_code)
        return js_file

    def _execute_docx_generation(self, js_file: str, title: str) -> str:
        """执行Node.js生成docx文件"""
        docx_file = os.path.join(self._output_dir, f"{title}.docx")

        try:
            # 设置环境变量，使用全局node_modules
            env = os.environ.copy()
            env['NODE_PATH'] = '/usr/lib/node_modules'

            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
                env=env
            )

            # 检查文件是否生成
            if not os.path.exists(docx_file):
                raise ExportException(f"文档生成失败，文件不存在: {docx_file}")

            return docx_file

        except subprocess.CalledProcessError as e:
            raise ExportException(f"Node.js执行失败: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise ExportException("文档生成超时")
        except Exception as e:
            raise ExportException(f"文档生成异常: {str(e)}")

    def _validate_docx(self, docx_file: str) -> Dict[str, Any]:
        """验证docx文件（使用docx skill）"""
        try:
            validate_script = self._docx_skill_path / "scripts/office/validate.py"

            result = subprocess.run(
                [
                    'python3',
                    str(validate_script),
                    docx_file,
                    '--auto-repair'
                ],
                capture_output=True,
                text=True,
                timeout=30,
                env={
                    'PYTHONPATH': str(self._docx_skill_path / "scripts/office")
                }
            )

            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _escape_js(self, text: str) -> str:
        """转义JavaScript字符串"""
        if not text:
            return ''
        return (text
                .replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace("'", "\\'")
                .replace('\n', '\\n')
                .replace('\r', '')
                .replace('\t', '\\t'))

    def _get_pricing_label(self, key: str) -> str:
        """获取定价标签"""
        labels = {
            'mortality': '死亡率',
            'interest': '利率',
            'expense': '费用率',
            'premium': '保费',
            'reserves': '准备金'
        }
        return labels.get(key, key)
