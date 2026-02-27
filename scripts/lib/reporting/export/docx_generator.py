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
from lib.logger import get_logger
from .constants import DocxConstants
from .result import GenerationResult
from .validation import validate_evaluation_context, validate_title


logger = get_logger('docx_generator')


class _DocxGenerator:
    """
    Docx文档生成器（内部实现）

    负责将EvaluationContext转换为Word文档
    """

    # docx skill路径（用于验证）
    DOCX_SKILL_PATH = "/root/.agents/skills/docx"

    # 默认超时时间（秒）
    DEFAULT_EXECUTION_TIMEOUT = 30
    DEFAULT_VALIDATION_TIMEOUT = 30

    def __init__(
        self,
        output_dir: Optional[str] = None,
        validate: bool = False,
        execution_timeout: Optional[int] = None,
        validation_timeout: Optional[int] = None
    ):
        """
        初始化Word文档生成器

        Args:
            output_dir: 输出目录，默认为系统临时目录
            validate: 是否验证生成的文档（使用docx skill）
            execution_timeout: Node.js执行超时时间（秒），默认30秒
            validation_timeout: 验证超时时间（秒），默认30秒
        """
        self._output_dir = output_dir or tempfile.gettempdir()
        self._validate = validate
        self._docx_skill_path = Path(self.DOCX_SKILL_PATH)
        self._execution_timeout = execution_timeout or self.DEFAULT_EXECUTION_TIMEOUT
        self._validation_timeout = validation_timeout or self.DEFAULT_VALIDATION_TIMEOUT

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
            # 输入验证
            validate_evaluation_context(context)

            logger.info(f"开始生成文档", product=context.product.name)

            # 1. 生成默认标题
            if title is None:
                timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                product_name = context.product.name or "未命名产品"
                title = f"{product_name}_审核报告_{timestamp}"

            # 标题验证
            title = validate_title(title)

            # 2. 生成docx-js代码
            logger.debug("生成 docx-js 代码")
            js_code = self._generate_docx_js_code(context, title)

            # 3. 写入临时JavaScript文件
            js_file = self._write_temp_js(js_code, title)

            # 4. 执行生成docx文件
            logger.debug("执行 Node.js 生成文档")
            docx_file = self._execute_docx_generation(js_file, title)

            # 5. 可选：验证文档
            validation_result = None
            if self._validate:
                logger.debug("验证文档")
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
            logger.error(f"文档生成失败: {str(e)}", exc_info=True)
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
        # 使用常量
        C = DocxConstants

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

        # 预先提取常量值，避免f-string嵌套
        font = C.Style.DEFAULT_FONT
        font_size_normal = C.Units.FONT_SIZE_NORMAL
        font_size_h1 = C.Units.FONT_SIZE_HEADING1
        font_size_h2 = C.Units.FONT_SIZE_HEADING2
        font_size_small = C.Units.FONT_SIZE_SMALL
        color_gray = C.Style.COLOR_GRAY
        spacing_h1_before = C.Spacing.SPACING_BEFORE_HEADING1
        spacing_h1_after = C.Spacing.SPACING_AFTER_HEADING1
        spacing_h2_before = C.Spacing.SPACING_BEFORE_HEADING2
        spacing_h2_after = C.Spacing.SPACING_AFTER_HEADING2
        page_width = C.Page.US_LETTER_WIDTH
        page_height = C.Page.US_LETTER_HEIGHT
        margin = C.Page.DEFAULT_MARGIN

        parts = [
            '''const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        WidthType, AlignmentType, HeadingLevel, BorderStyle } = require('docx');
const fs = require('fs');

async function createAuditReport() {
    const doc = new Document({
        styles: {
            default: {
                document: {
                    run: { font: "''' + font + '''", size: ''' + str(font_size_normal) + ''' }
                }
            },
            paragraphStyles: [
                {
                    id: "Heading1",
                    name: "Heading 1",
                    basedOn: "Normal",
                    next: "Normal",
                    quickFormat: true,
                    run: { size: ''' + str(font_size_h1) + ''', bold: true, font: "''' + font + '''" },
                    paragraph: { spacing: { before: ''' + str(spacing_h1_before) + ''', after: ''' + str(spacing_h1_after) + ''' }, outlineLevel: 0 }
                },
                {
                    id: "Heading2",
                    name: "Heading 2",
                    basedOn: "Normal",
                    next: "Normal",
                    quickFormat: true,
                    run: { size: ''' + str(font_size_h2) + ''', bold: true, font: "''' + font + '''" },
                    paragraph: { spacing: { before: ''' + str(spacing_h2_before) + ''', after: ''' + str(spacing_h2_after) + ''' }, outlineLevel: 1 }
                }
            ]
        },
        sections: [{
            properties: {
                page: {
                    size: {
                        width: ''' + str(page_width) + ''',
                        height: ''' + str(page_height) + '''
                    },
                    margin: { top: ''' + str(margin) + ''', right: ''' + str(margin) + ''', bottom: ''' + str(margin) + ''', left: ''' + str(margin) + ''' }
                }
            },
            children: [
                new Paragraph({
                    text: "''' + escaped_title + '''",
                    heading: HeadingLevel.HEADING_1,
                    alignment: AlignmentType.CENTER,
                }),
'''
        ]

        # 添加产品基本信息
        parts.append(self._generate_product_info_section(product_info))

        # 添加审核结论章节
        parts.append(self._generate_conclusion_section(score, grade, summary, violations, pricing_analysis))

        # 添加问题详情章节
        if violations:
            parts.append(self._generate_details_section(violations, summary, pricing_analysis))

        # 添加修改建议章节
        if violations:
            parts.append(self._generate_suggestions_section(violations))

        # 添加页脚
        parts.extend([
            '''                new Paragraph({
                    text: "",
                }),
                new Paragraph({
                    children: [
                        new TextRun({
                            text: "报告生成时间: ''' + timestamp + '''",
                            size: ''' + str(font_size_small) + ''',
                            color: "''' + color_gray + '''"
                        })
                    ],
                    alignment: AlignmentType.RIGHT,
                }),
            ]
        }]
    });

    const buffer = await Packer.toBuffer(doc);
    const outputPath = "''' + output_path.replace('\\', '\\\\') + '''";
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

    def _generate_heading_paragraph(self, text: str, level: int = 2) -> str:
        """生成标准化的标题段落"""
        escaped_text = self._escape_js(text)
        return f'''                new Paragraph({{
                    text: "{escaped_text}",
                    heading: HeadingLevel.HEADING_{level},
                }}),'''

    def _generate_text_paragraph(self, text: str) -> str:
        """生成标准化的文本段落"""
        escaped_text = self._escape_js(text)
        return f'''                new Paragraph({{
                    text: "{escaped_text}",
                }}),'''

    def _generate_bold_text_paragraph(self, text: str, size: int = 28) -> str:
        """生成带粗体文本的段落"""
        escaped_text = self._escape_js(text)
        return f'''                new Paragraph({{
                    children: [new TextRun({{ text: "{escaped_text}", bold: true, size: {size} }})]
                }}),'''

    def _generate_field_paragraph(self, label: str, value: str) -> str:
        """生成字段段落（标签+值）"""
        escaped_label = self._escape_js(label)
        escaped_value = self._escape_js(value)
        return f'''                new Paragraph({{
                    children: [
                        new TextRun({{ text: "{escaped_label}: ", bold: true }}),
                        new TextRun({{ text: "{escaped_value}" }})
                    ]
                }}),'''

    def _generate_product_info_section(self, product: '_InsuranceProduct') -> str:
        """生成产品信息部分"""
        sections = []
        sections.append(self._generate_heading_paragraph("产品信息", 2))

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

    def _generate_conclusion_section(
        self,
        score: int,
        grade: str,
        summary: Dict[str, Any],
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any]
    ) -> str:
        """生成审核结论章节"""
        sections = []
        sections.append(self._generate_heading_paragraph("一、审核结论", 2))

        # 生成审核意见
        opinion, explanation = self._generate_conclusion_text(score, summary, violations)

        sections.append(self._generate_field_paragraph("审核意见", opinion))
        sections.append(self._generate_field_paragraph("说明", explanation))
        sections.append(self._generate_text_paragraph(""))

        # 关键数据表格（表1-1）
        sections.append(self._generate_bold_text_paragraph("表1-1：关键指标汇总表", 26))
        sections.append(self._generate_text_paragraph(""))

        high_count = summary.get('high', 0)
        medium_count = summary.get('medium', 0)
        low_count = summary.get('low', 0)
        total = len(violations)

        # 计算定价问题数
        pricing_issue_count = 0
        if pricing_analysis:
            for key, value in pricing_analysis.items():
                if isinstance(value, dict) and not value.get('reasonable', True):
                    pricing_issue_count += 1

        score_desc = self._get_score_description(score)
        violation_detail = f"严重{high_count}项，中等{medium_count}项，轻微{low_count}项"

        rows = [
            ["序号", "指标项", "结果", "说明"],
            ["1", "综合评分", f"{score}分", score_desc],
            ["2", "合规评级", grade, "基于违规数量和严重程度评定"],
            ["3", "违规总数", f"{total}项", violation_detail],
            ["4", "定价评估", "合理" if pricing_issue_count == 0 else "需关注", f"{pricing_issue_count}项定价参数需关注"]
        ]
        sections.append(self._generate_data_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_details_section(
        self,
        violations: List[Dict[str, Any]],
        summary: Dict[str, Any],
        pricing_analysis: Dict[str, Any]
    ) -> str:
        """生成问题详情章节"""
        sections = []
        sections.append(self._generate_text_paragraph(""))
        sections.append(self._generate_heading_paragraph("二、问题详情及依据", 2))

        # 审核依据
        sections.append(self._generate_bold_text_paragraph("审核依据", 26))
        regulations = self._generate_regulation_basis(violations)
        for i, reg in enumerate(regulations, 1):
            sections.append(self._generate_text_paragraph(f"{i}. {reg}"))
        sections.append(self._generate_text_paragraph(""))

        # 违规统计表（表2-1）
        sections.append(self._generate_bold_text_paragraph("表2-1：违规级别统计表", 26))
        sections.append(self._generate_text_paragraph(""))

        high_count = summary.get('high', 0)
        medium_count = summary.get('medium', 0)
        low_count = summary.get('low', 0)
        total = len(violations)

        if total > 0:
            high_percent = f"{high_count/total*100:.1f}%"
            medium_percent = f"{medium_count/total*100:.1f}%"
            low_percent = f"{low_count/total*100:.1f}%"
        else:
            high_percent = "0%"
            medium_percent = "0%"
            low_percent = "0%"

        rows = [
            ["序号", "违规级别", "数量", "占比"],
            ["1", "严重", f"{high_count}项", high_percent],
            ["2", "中等", f"{medium_count}项", medium_percent],
            ["3", "轻微", f"{low_count}项", low_percent],
            ["合计", "总计", f"{total}项", "100%"]
        ]
        sections.append(self._generate_data_table(rows))

        # 严重违规明细表（表2-2）
        high_violations = [v for v in violations if v.get('severity') == 'high']
        if high_violations:
            sections.append(self._generate_text_paragraph(""))
            sections.append(self._generate_bold_text_paragraph("表2-2：严重违规明细表", 26))
            sections.append(self._generate_text_paragraph(""))

            rows = [["序号", "条款内容", "问题说明", "法规依据"]]
            for i, v in enumerate(high_violations[:20], 1):
                clause_ref = v.get('clause_reference', '')
                clause_text = v.get('clause_text', '')[:80]
                description = v.get('description', '未知')
                category = v.get('category', '')
                regulation = self._get_regulation_basis(category)

                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}：{clause_text}"
                else:
                    full_clause = clause_text

                rows.append([str(i), full_clause + "...", description, regulation])

            sections.append(self._generate_data_table(rows))

        # 中等违规明细表（表2-3）
        medium_violations = [v for v in violations if v.get('severity') == 'medium']
        if medium_violations:
            sections.append(self._generate_text_paragraph(""))
            sections.append(self._generate_bold_text_paragraph("表2-3：中等违规明细表", 26))
            sections.append(self._generate_text_paragraph(""))

            rows = [["序号", "条款内容", "问题说明", "法规依据"]]
            for i, v in enumerate(medium_violations[:10], 1):
                clause_ref = v.get('clause_reference', '')
                clause_text = v.get('clause_text', '')[:80]
                description = v.get('description', '未知')
                category = v.get('category', '')
                regulation = self._get_regulation_basis(category)

                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}：{clause_text}"
                else:
                    full_clause = clause_text

                rows.append([str(i), full_clause + "...", description, regulation])

            sections.append(self._generate_data_table(rows))

        # 定价问题汇总表（表2-4）
        pricing_issues = []
        if pricing_analysis:
            for category in ['interest', 'expense']:
                value = pricing_analysis.get(category)
                if isinstance(value, dict) and not value.get('reasonable', True):
                    note = value.get('note', '不符合监管要求')
                    pricing_issues.append(('预定利率' if category == 'interest' else '费用率', note))

        if pricing_issues:
            sections.append(self._generate_text_paragraph(""))
            sections.append(self._generate_bold_text_paragraph("表2-4：定价问题汇总表", 26))
            sections.append(self._generate_text_paragraph(""))

            rows = [["序号", "问题类型", "问题描述"]]
            for i, (issue_type, issue_desc) in enumerate(pricing_issues, 1):
                rows.append([str(i), issue_type, issue_desc])

            sections.append(self._generate_data_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_suggestions_section(self, violations: List[Dict[str, Any]]) -> str:
        """生成修改建议章节"""
        sections = []
        sections.append(self._generate_text_paragraph(""))
        sections.append(self._generate_heading_paragraph("三、修改建议", 2))

        # 按严重程度分组
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']

        # P0级整改事项表（表3-1）
        if high_violations:
            sections.append(self._generate_bold_text_paragraph("表3-1：P0级整改事项表（必须立即整改）", 26))
            sections.append(self._generate_text_paragraph(""))

            rows = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(high_violations[:10], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                rows.append([str(i), clause_text + "...", remediation])

            sections.append(self._generate_data_table(rows))

        # P1级整改事项表（表3-2）
        if medium_violations:
            sections.append(self._generate_text_paragraph(""))
            sections.append(self._generate_bold_text_paragraph("表3-2：P1级整改事项表（建议尽快整改）", 26))
            sections.append(self._generate_text_paragraph(""))

            rows = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(medium_violations[:5], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                rows.append([str(i), clause_text + "...", remediation])

            sections.append(self._generate_data_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_simple_table(self, rows: List[List[str]]) -> str:
        """生成简单2列表格（用于产品信息等）"""
        if not rows:
            return ''

        # 使用常量
        C = DocxConstants

        # 2列表格，列宽比例 1:2
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

    def _generate_data_table(self, rows: List[List[str]]) -> str:
        """生成数据表格（多列，用于报告核心表格）"""
        if not rows:
            return ''

        # 使用常量
        C = DocxConstants

        # 根据列数计算列宽
        num_cols = len(rows[0])
        content_width = C.Table.DEFAULT_CONTENT_WIDTH

        # 计算各列宽度（根据列数分配）
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
                # 第一行是表头，使用粗体
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

    def _generate_conclusion_text(
        self,
        score: int,
        summary: Dict[str, Any],
        violations: List[Dict[str, Any]]
    ) -> tuple:
        """生成审核结论文本"""
        high_count = summary.get('high', 0)
        medium_count = summary.get('medium', 0)
        total = len(violations)

        if high_count > 0:
            opinion = "不推荐上会"
            explanation = f"产品存在{high_count}项严重违规，触及监管红线，需完成整改后重新审核"
        elif score >= 90:
            opinion = "推荐通过"
            explanation = "产品符合所有监管要求，未发现违规问题"
        elif score >= 75:
            opinion = "条件推荐"
            explanation = f"产品整体符合要求，存在{medium_count}项中等问题，建议完成修改后提交审核"
        elif score >= 60:
            opinion = "需补充材料"
            explanation = f"产品存在{total}项问题，建议补充说明材料后复审"
        else:
            opinion = "不予推荐"
            explanation = "产品合规性不足，不建议提交审核"

        return opinion, explanation

    def _get_score_description(self, score: int) -> str:
        """获取评分描述"""
        if score >= 90:
            return "产品优秀，建议快速通过"
        elif score >= 80:
            return "产品良好，可正常上会"
        elif score >= 70:
            return "产品合格，建议完成修改后上会"
        elif score >= 60:
            return "产品基本合格，需补充说明材料"
        else:
            return "产品不合格，不建议提交审核"

    def _generate_regulation_basis(self, violations: List[Dict[str, Any]]) -> List[str]:
        """动态生成审核依据"""
        basis = ["《中华人民共和国保险法》"]
        basis.append("《人身保险公司保险条款和保险费率管理办法》")
        return basis

    def _get_regulation_basis(self, category: str) -> str:
        """根据违规类别返回法规依据"""
        regulation_map = {
            '产品条款表述': '《保险法》第十七条',
            '产品责任设计': '《条款费率管理办法》第六条',
            '产品费率厘定及精算假设': '《条款费率管理办法》第三十六条',
            '产品报送管理': '《条款费率管理办法》第十二条',
            '产品形态设计': '《健康保险管理办法》第十六条',
            '销售管理': '《保险销售行为监管办法》第十三条',
            '理赔管理': '《保险法》第二十二条',
            '客户服务': '《保险公司服务管理办法》第八条'
        }
        return regulation_map.get(category, '《保险法》及相关监管规定')

    def _get_specific_remediation(self, violation: Dict[str, Any]) -> str:
        """生成具体的修改建议"""
        default_remediation = violation.get('remediation', '')
        description = violation.get('description', '')

        # 如果默认建议模糊，则基于违规描述生成具体建议
        vague_phrases = ['请根据具体情况', '确保符合', '无', '', '按照《保险法》规定', '建议']
        if any(phrase in default_remediation for phrase in vague_phrases):
            if '等待期' in description:
                if '过长' in description or '超过' in description:
                    return '将等待期调整为90天以内'
                elif '症状' in description or '体征' in description:
                    return '删除将等待期内症状或体征作为免责依据的表述'
                elif '突出' in description:
                    return '在条款中以加粗或红色字体突出说明等待期'
                else:
                    return '合理设置等待期长度，确保符合监管规定'
            elif '免责条款' in description or '责任免除' in description:
                if '不集中' in description:
                    return '将免责条款集中在合同显著位置'
                elif '不清晰' in description or '表述不清' in description:
                    return '使用清晰明确的语言表述免责情形'
                elif '加粗' in description or '标红' in description or '突出' in description:
                    return '使用加粗或红色字体突出显示免责条款'
                elif '免除' in description and '不合理' in description:
                    return '删除不合理的免责条款，确保不违反保险法规定'
                else:
                    return '完善免责条款的表述和展示方式'
            elif '保证收益' in description or '演示收益' in description:
                return '删除保证收益相关表述，改为演示收益或说明利益不确定'
            elif '费率' in description:
                if '倒算' in description:
                    return '停止使用倒算方式确定费率，采用精算方法'
                elif '偏离实际' in description:
                    return '根据实际费用水平重新核算附加费用率'
                elif '不真实' in description or '不合理' in description:
                    return '重新进行费率厘定，确保符合审慎原则'
                else:
                    return '规范费率厘定方法，确保符合监管要求'
            elif '现金价值' in description:
                if '超过' in description or '异化' in description:
                    return '调整现金价值计算方法，确保不超过已交保费'
                else:
                    return '规范现金价值计算，确保符合监管规定'
            elif '基因' in description:
                return '删除根据基因检测结果调节费率的约定'
            elif '犹豫期' in description:
                if '过短' in description or '不足' in description:
                    return '将犹豫期调整为15天以上'
                else:
                    return '规范犹豫期的起算和时长'
            elif '利率' in description or '预定利率' in description:
                if '超过' in description or '超标' in description:
                    return '将预定利率调整为监管上限以内'
                else:
                    return '确保预定利率符合监管规定'
            elif '条款文字' in description or '冗长' in description or '不易懂' in description:
                return '简化条款表述，使用通俗易懂的语言'
            else:
                return '请根据违规描述进行相应调整，确保符合监管要求'

        return default_remediation

    def _write_temp_js(self, js_code: str, title: str) -> str:
        """写入临时JavaScript文件，失败时自动清理"""
        js_file = os.path.join(self._output_dir, f"{title}.js")
        logger.debug(f"写入临时JavaScript文件: {js_file}")
        try:
            with open(js_file, 'w', encoding='utf-8') as f:
                f.write(js_code)
            return js_file
        except Exception:
            # 清理可能创建的不完整文件
            if os.path.exists(js_file):
                os.remove(js_file)
            raise

    def _execute_docx_generation(self, js_file: str, title: str) -> str:
        """执行Node.js生成docx文件"""
        docx_file = os.path.join(self._output_dir, f"{title}.docx")

        try:
            # 设置环境变量，使用全局node_modules
            env = os.environ.copy()
            env['NODE_PATH'] = '/usr/lib/node_modules'

            logger.debug(f"执行 Node.js 生成文档: {js_file}")
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=self._execution_timeout,
                check=True,
                env=env
            )

            logger.debug(f"Node.js 输出: {result.stdout.strip()}")

            # 检查文件是否生成
            if not os.path.exists(docx_file):
                raise ExportException(f"文档生成失败，文件不存在: {docx_file}")

            return docx_file

        except subprocess.CalledProcessError as e:
            raise ExportException(f"Node.js执行失败: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise ExportException(f"文档生成超时（超过{self._execution_timeout}秒）")
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
                timeout=self._validation_timeout,
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
            logger.error(f"文档验证失败: {str(e)}", exc_info=True)
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
