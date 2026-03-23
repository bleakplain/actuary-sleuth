#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx JS模板生成器

负责生成docx-js JavaScript代码模板
"""
import os
from datetime import datetime
from typing import Dict, List, Any

from lib.common.logger import get_logger
from .constants import DocxConstants

logger = get_logger('docx_templates')


class _DocxTemplateGenerator:
    """Docx JS模板生成器"""

    def __init__(self, output_dir: str):
        self._output_dir = output_dir
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

    def generate_docx_js_code(
        self,
        context: 'EvaluationContext',
        title: str
    ) -> str:
        product_info = context.product
        violations = context.violations
        pricing_analysis = context.pricing_analysis
        score = context.score
        grade = context.grade or "未评级"
        summary = context.summary or {}

        overall_assessment = context.overall_assessment
        assessment_reason = context.assessment_reason

        escaped_title = self._escape_js(title)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        output_path = f"{self._output_dir}/{title}.docx"

        C = self.C
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

        from .docx_sections import DocxSectionGenerator
        section_gen = DocxSectionGenerator()

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

        parts.append(section_gen.generate_product_section(product_info))
        parts.append(self._generate_conclusion_section(score, grade, summary, violations, pricing_analysis, overall_assessment, assessment_reason))

        if violations:
            parts.append(self._generate_details_section(violations, summary, pricing_analysis))

        if violations:
            parts.append(self._generate_suggestions_section(violations))

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

    def _generate_conclusion_section(
        self,
        score: int,
        grade: str,
        summary: Dict[str, Any],
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any],
        overall_assessment: str = "不通过",
        assessment_reason: str = ""
    ) -> str:
        from .docx_sections import DocxSectionGenerator
        section_gen = DocxSectionGenerator()

        sections = []
        sections.append(section_gen.generate_heading_paragraph("一、审核结论", 2))

        opinion = overall_assessment
        explanation = assessment_reason or self._generate_conclusion_text(score, summary, violations)[1]

        sections.append(section_gen.generate_field_paragraph("审核意见", opinion))
        sections.append(section_gen.generate_field_paragraph("说明", explanation))
        sections.append(section_gen.generate_text_paragraph(""))

        sections.append(section_gen.generate_bold_text_paragraph("表1-1：关键指标汇总表", 26))
        sections.append(section_gen.generate_text_paragraph(""))

        high_count = summary.get('high', 0)
        medium_count = summary.get('medium', 0)
        low_count = summary.get('low', 0)
        total = len(violations)

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
        sections.append(section_gen.generate_data_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_details_section(
        self,
        violations: List[Dict[str, Any]],
        summary: Dict[str, Any],
        pricing_analysis: Dict[str, Any]
    ) -> str:
        from .docx_sections import DocxSectionGenerator
        section_gen = DocxSectionGenerator()

        sections = []
        sections.append(section_gen.generate_text_paragraph(""))
        sections.append(section_gen.generate_heading_paragraph("二、问题详情及依据", 2))

        sections.append(section_gen.generate_bold_text_paragraph("审核依据", 26))
        regulations = self._generate_regulation_basis(violations)
        for i, reg in enumerate(regulations, 1):
            sections.append(section_gen.generate_text_paragraph(f"{i}. {reg}"))
        sections.append(section_gen.generate_text_paragraph(""))

        sections.append(section_gen.generate_bold_text_paragraph("表2-1：违规级别统计表", 26))
        sections.append(section_gen.generate_text_paragraph(""))

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
        sections.append(section_gen.generate_data_table(rows))

        high_violations = [v for v in violations if v.get('severity') == 'high']
        if high_violations:
            sections.append(section_gen.generate_text_paragraph(""))
            sections.append(section_gen.generate_bold_text_paragraph("表2-2：严重违规明细表", 26))
            sections.append(section_gen.generate_text_paragraph(""))

            rows = [["序号", "条款内容", "问题说明", "法规依据"]]
            for i, v in enumerate(high_violations[:20], 1):
                clause_ref = v.get('clause_reference', '')
                clause_text = v.get('clause_text_preview', v.get('clause_text', '')[:80])
                description = v.get('description', '未知')
                category = v.get('category', '')
                regulation = self._get_regulation_basis(category)

                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}：{clause_text}"
                else:
                    full_clause = clause_text

                rows.append([str(i), full_clause + "...", description, regulation])

            sections.append(section_gen.generate_data_table(rows))

        medium_violations = [v for v in violations if v.get('severity') == 'medium']
        if medium_violations:
            sections.append(section_gen.generate_text_paragraph(""))
            sections.append(section_gen.generate_bold_text_paragraph("表2-3：中等违规明细表", 26))
            sections.append(section_gen.generate_text_paragraph(""))

            rows = [["序号", "条款内容", "问题说明", "法规依据"]]
            for i, v in enumerate(medium_violations[:10], 1):
                clause_ref = v.get('clause_reference', '')
                clause_text = v.get('clause_text_preview', v.get('clause_text', '')[:80])
                description = v.get('description', '未知')
                category = v.get('category', '')
                regulation = self._get_regulation_basis(category)

                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}：{clause_text}"
                else:
                    full_clause = clause_text

                rows.append([str(i), full_clause + "...", description, regulation])

            sections.append(section_gen.generate_data_table(rows))

        pricing_issues = []
        if pricing_analysis:
            for category in ['mortality', 'interest', 'expense']:
                value = pricing_analysis.get(category)
                if isinstance(value, dict) and not value.get('reasonable', True):
                    note = value.get('note', '不符合监管要求')
                    category_name = {
                        'mortality': '死亡率/发生率',
                        'interest': '预定利率',
                        'expense': '费用率'
                    }.get(category, category)
                    pricing_issues.append((category_name, note))

        if pricing_issues:
            sections.append(section_gen.generate_text_paragraph(""))
            sections.append(section_gen.generate_bold_text_paragraph("表2-4：定价问题汇总表", 26))
            sections.append(section_gen.generate_text_paragraph(""))

            rows = [["序号", "问题类型", "问题描述"]]
            for i, (issue_type, issue_desc) in enumerate(pricing_issues, 1):
                rows.append([str(i), issue_type, issue_desc])

            sections.append(section_gen.generate_data_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_suggestions_section(self, violations: List[Dict[str, Any]]) -> str:
        from .docx_sections import DocxSectionGenerator
        section_gen = DocxSectionGenerator()

        sections = []
        sections.append(section_gen.generate_text_paragraph(""))
        sections.append(section_gen.generate_heading_paragraph("三、修改建议", 2))

        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']

        if high_violations:
            sections.append(section_gen.generate_bold_text_paragraph("表3-1：P0级整改事项表（必须立即整改）", 26))
            sections.append(section_gen.generate_text_paragraph(""))

            rows = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(high_violations[:10], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                rows.append([str(i), clause_text + "...", remediation])

            sections.append(section_gen.generate_data_table(rows))

        if medium_violations:
            sections.append(section_gen.generate_text_paragraph(""))
            sections.append(section_gen.generate_bold_text_paragraph("表3-2：P1级整改事项表（建议尽快整改）", 26))
            sections.append(section_gen.generate_text_paragraph(""))

            rows = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(medium_violations[:5], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                rows.append([str(i), clause_text + "...", remediation])

            sections.append(section_gen.generate_data_table(rows))

        return '\n'.join(sections) + '\n'

    def _generate_conclusion_text(
        self,
        score: int,
        summary: Dict[str, Any],
        violations: List[Dict[str, Any]]
    ) -> tuple:
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
        basis = ["《中华人民共和国保险法》"]
        basis.append("《人身保险公司保险条款和保险费率管理办法》")

        cited_regs = set()
        for v in violations:
            if v.get('regulation_citation'):
                cited_regs.add(v['regulation_citation'])

        if cited_regs:
            basis.extend(sorted(cited_regs))

        return basis

    def _get_regulation_basis(self, category: str) -> str:
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
        default_remediation = violation.get('remediation', '')
        description = violation.get('description', '')

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
