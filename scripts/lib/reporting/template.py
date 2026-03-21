#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模板

ReportGenerationTemplate类：使用模板方法模式生成审核报告

统一数据模型：接受 AuditResult 作为输入，消除数据转换

模板方法定义报告生成的固定流程：
1. 从 AuditResult 提取数据
2. 确定评级（基于 audit 的 overall_assessment）
3. 生成摘要 (_summarize_violations)
4. 生成内容 (_generate_content)
5. 生成块 (_generate_blocks)
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from lib.config import get_config, Config
from lib.common.id_generator import IDGenerator
from lib.reporting.strategies import RemediationStrategies
from lib.reporting.model import EvaluationContext
from lib.common.models import Product


class ReportGenerationTemplate:
    """
    报告生成模板

    使用模板方法模式,定义报告生成的固定流程:

    Template Method: generate()
        ├─ step 1: 构建评估上下文
        ├─ step 2: 使用 audit 的 overall_assessment
        ├─ step 3: 确定评级 (_calculate_grade)
        ├─ step 4: 统计违规摘要（含分组）
        ├─ step 5: 生成内容 (核心步骤)
        └─ step 6: 生成块 (核心步骤)

    统一数据模型：
    - 接受 AuditResult 作为输入（来自 audit 模块）
    - 使用 audit 的 overall_assessment，不再重复计算结论
    - 使用 audit 的 regulations_used，不再使用硬编码
    """

    ASSESSMENT_TO_GRADE = {
        '通过': '优秀',
        '有条件通过': '良好',
        '不通过': '不合格',
    }

    def __init__(self, config: Optional[Config] = None):
        """
        初始化报告生成模板

        Args:
            config: 配置对象(可选)
        """
        self.config = config or get_config()
        self.report_id = None
        self.remediation_strategies = RemediationStrategies()
        self._load_thresholds()

    def _load_thresholds(self):
        """从配置加载阈值"""
        self.GRADE_THRESHOLDS = self.config.report.grade_thresholds
        self.GRADE_DEFAULT = self.config.report.default_grade
        self.HIGH_VIOLATIONS_LIMIT = self.config.report.high_violations_limit
        self.MEDIUM_VIOLATIONS_LIMIT = self.config.report.medium_violations_limit
        self.P1_REMEDIATION_MEDIUM_LIMIT = self.config.report.p1_remediation_limit

    def _apply_product_config(self, context: EvaluationContext):
        """应用产品特定配置"""
        product_category = getattr(context.product, 'category', None)
        if product_category:
            product_thresholds = self.config.report.get_product_thresholds(
                product_category.value if hasattr(product_category, 'value') else product_category
            )
            if product_thresholds:
                self.GRADE_THRESHOLDS = product_thresholds

            product_limits = self.config.report.get_product_violation_limits(
                product_category.value if hasattr(product_category, 'value') else product_category
            )
            if product_limits:
                self.HIGH_VIOLATIONS_LIMIT = product_limits.get('high_limit', self.HIGH_VIOLATIONS_LIMIT)
                self.MEDIUM_VIOLATIONS_LIMIT = product_limits.get('medium_limit', self.MEDIUM_VIOLATIONS_LIMIT)

    def generate(
        self,
        context: EvaluationContext,
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        模板方法：按固定流程生成报告

        Args:
            context: 评估上下文对象
            title: 报告标题（可选）

        Returns:
            dict: 包含 report_id, score, grade, summary, content, blocks
        """
        # 验证输入
        if not isinstance(context, EvaluationContext):
            raise TypeError(f"context must be EvaluationContext, got {type(context)}")

        # 应用产品特定配置
        self._apply_product_config(context)

        # 生成报告ID
        self.report_id = IDGenerator.generate_report()

        # 步骤2-4: 使用 audit 的 overall_assessment，确定评级，统计摘要
        self._calculate_grade(context)
        self._summarize_violations(context)

        # 步骤5-6: 生成内容
        content = self._generate_content(context)
        blocks = self._generate_blocks(context)

        return {
            'success': True,
            'report_id': self.report_id,
            'score': context.score,
            'grade': context.grade,
            'summary': context.summary,
            'content': content,
            'blocks': blocks,
            'metadata': self._generate_metadata(context)
        }

    def _calculate_grade(self, context: EvaluationContext) -> None:
        """
        确定评级（根据 score 计算）

        Args:
            context: 评估上下文，结果存储到 context.grade
        """
        if context.score is not None:
            # 根据 score 计算评级
            for threshold, grade in self.GRADE_THRESHOLDS:
                if context.score >= threshold:
                    context.grade = grade
                    break
            else:
                context.grade = self.GRADE_DEFAULT
        else:
            context.grade = self.GRADE_DEFAULT

    def _summarize_violations(self, context: EvaluationContext) -> None:
        """
        统计违规摘要并分组

        Args:
            context: 评估上下文，结果存储到 context.summary 和分组违规项
        """
        # 如果已经分组（from_evaluation_result 已处理），直接使用
        # 否则进行分组
        if not context.high_violations:
            context.high_violations = [v for v in context.violations if v.get('severity') == 'high']
            context.medium_violations = [v for v in context.violations if v.get('severity') == 'medium']
            context.low_violations = [v for v in context.violations if v.get('severity') == 'low']

        # 统计违规数量（使用分组后的结果，提高性能）
        violation_summary = {
            'high': len(context.high_violations),
            'medium': len(context.medium_violations),
            'low': len(context.low_violations)
        }

        # 统计定价问题
        pricing_issues = self._count_pricing_issues(context.pricing_analysis)

        # 使用默认审核依据
        if not context.regulation_basis:
            context.regulation_basis = self._generate_default_regulation_basis()

        # 存储摘要
        context.summary = {
            'total_violations': len(context.violations),
            'violation_severity': violation_summary,
            'pricing_issues': pricing_issues,
            'has_critical_issues': violation_summary['high'] > 0 or pricing_issues > 1,
            'has_issues': len(context.violations) > 0 or pricing_issues > 0,
        }

    def _count_pricing_issues(self, pricing_analysis: Dict[str, Any]) -> int:
        """
        统计定价问题数量

        Args:
            pricing_analysis: 定价分析结果（已包含 {mortality, interest, expense} 键）

        Returns:
            int: 定价问题数量
        """
        pricing_issues = 0
        if isinstance(pricing_analysis, dict):
            for category in ['mortality', 'interest', 'expense']:
                analysis = pricing_analysis.get(category, {})
                if isinstance(analysis, dict) and analysis.get('reasonable') is False:
                    pricing_issues += 1
        return pricing_issues

    def _generate_default_regulation_basis(self) -> List[str]:
        """生成默认审核依据（当 audit_result 为空时）"""
        return [
            "《中华人民共和国保险法》",
            "《人身保险公司保险条款和保险费率管理办法》"
        ]

    def _generate_content(self, context: EvaluationContext) -> str:
        """
        生成精算审核报告

        动态生成,基于实际审核情况:
        - 有问题才显示问题章节
        - 审核依据从 audit 获取
        - 表格只在有数据时显示

        结构:
        1. 审核结论(始终显示) - 使用 audit 的 overall_assessment
        2. 问题详情及依据(有问题时显示)
        3. 修改建议(有问题时显示)
        """
        lines = []

        # ========== 审核结论(始终显示) ==========
        lines.extend(self._generate_conclusion_section(context))

        # ========== 问题详情(有问题时显示) ==========
        if context.summary.get('has_issues', False):
            lines.append("")
            lines.extend(self._generate_details_section(context))

        # ========== 修改建议(有问题时显示) ==========
        if context.summary.get('has_issues', False):
            lines.append("")
            lines.extend(self._generate_suggestions_section(context))

        return '\n'.join(lines)

    def _generate_blocks(self, context: EvaluationContext) -> List[Dict[str, Any]]:
        """
        生成报告块(飞书格式)

        动态生成,基于实际审核情况:
        - 有问题才显示问题章节
        - 审核依据从 audit 获取
        - 表格只在有数据时显示
        """
        blocks = []

        # ========== 审核结论(始终显示) ==========
        blocks.extend(self._create_conclusion_blocks(context))

        # ========== 问题详情(有问题时显示) ==========
        if context.summary.get('has_issues', False):
            blocks.append(self._create_text(""))
            blocks.extend(self._create_details_blocks(context))

        # ========== 修改建议(有问题时显示) ==========
        if context.summary.get('has_issues', False):
            blocks.append(self._create_text(""))
            blocks.extend(self._create_suggestions_blocks(context))

        return blocks

    def _generate_metadata(self, context: EvaluationContext) -> Dict[str, Any]:
        """生成元数据"""
        # 获取 overall_assessment（从 audit_result 或计算）
        audit_result = getattr(context, 'audit_result', None)
        if audit_result and hasattr(audit_result, 'overall_assessment'):
            overall_assessment = audit_result.overall_assessment
        else:
            # 根据 grade 推断 overall_assessment
            grade_to_assessment = {
                '优秀': 'pass',
                '良好': 'pass',
                '合格': 'pass',
                '不合格': 'fail'
            }
            overall_assessment = grade_to_assessment.get(context.grade or 'unknown', 'unknown')

        return {
            'product_name': context.product.name,
            'insurance_company': context.product.company,
            'product_type': context.product.type,
            'timestamp': datetime.now().isoformat(),
            'overall_assessment': overall_assessment,
        }

    # ========== 文本内容生成辅助方法 ==========

    def _generate_conclusion_section(self, context: EvaluationContext) -> List[str]:
        """生成审核结论章节"""
        lines = []

        lines.append("一、审核结论")

        # 获取 overall_assessment（从 audit_result 或计算）
        audit_result = getattr(context, 'audit_result', None)
        if audit_result and hasattr(audit_result, 'overall_assessment'):
            opinion = audit_result.overall_assessment
            explanation = getattr(audit_result, 'assessment_reason', None) or self._get_default_explanation(context)
        else:
            # 根据 grade 生成审核意见
            grade_to_opinion = {
                '优秀': '通过',
                '良好': '通过',
                '合格': '通过',
                '不合格': '不通过'
            }
            opinion = grade_to_opinion.get(context.grade or 'unknown', '待定')
            explanation = self._get_default_explanation(context)

        lines.append(f"**审核意见**:{opinion}")
        lines.append(f"**说明**:{explanation}")
        lines.append("")

        # 关键数据表格
        high_count = context.summary['violation_severity']['high']
        medium_count = context.summary['violation_severity']['medium']
        low_count = context.summary['violation_severity']['low']
        total = context.summary['total_violations']
        pricing_issue_count = context.summary.get('pricing_issues', 0)

        lines.append("**表1-1:关键指标汇总表**")
        lines.append("| 序号 | 指标项 | 结果 | 说明 |")
        lines.append("|:----:|:------|:-----|:-----|")
        lines.append(f"| 1 | 综合评分 | {context.score}分 | {self._get_score_description(context.score)} |")
        lines.append(f"| 2 | 合规评级 | {context.grade} | 基于违规数量和严重程度评定 |")
        lines.append(f"| 3 | 违规总数 | {total}项 | 严重{high_count}项,中等{medium_count}项,轻微{low_count}项 |")
        lines.append(f"| 4 | 定价评估 | {'合理' if pricing_issue_count == 0 else '需关注'} | {pricing_issue_count}项定价参数需关注 |")

        return lines

    def _get_default_explanation(self, context: EvaluationContext) -> str:
        """获取默认说明（当 audit_result.assessment_reason 为空时）"""
        high_count = context.summary['violation_severity']['high']
        medium_count = context.summary['violation_severity']['medium']
        total = context.summary['total_violations']

        if high_count > 0:
            return f"产品存在{high_count}项严重违规,触及监管红线,需完成整改后重新审核"
        elif context.score >= 90:
            return "产品符合所有监管要求,未发现违规问题"
        elif context.score >= 75:
            return f"产品整体符合要求,存在{medium_count}项中等问题,建议完成修改后提交审核"
        elif context.score >= 60:
            return f"产品存在{total}项问题,建议补充说明材料后复审"
        else:
            return "产品合规性不足,不建议提交审核"

    def _generate_details_section(self, context: EvaluationContext) -> List[str]:
        """生成问题详情章节"""
        lines = []

        lines.append("二、问题详情及依据")

        # 生成审核依据(从 audit 获取)
        lines.append("**审核依据**")
        for i, reg in enumerate(context.regulation_basis, 1):
            lines.append(f"{i}. {reg}")
        lines.append("")

        # 违规统计表
        lines.append("**表2-1:违规级别统计表**")
        lines.append("")
        lines.append("| 序号 | 违规级别 | 数量 | 占比 |")
        lines.append("|:----:|:--------|:----:|:----:|")

        high_count = context.summary['violation_severity']['high']
        medium_count = context.summary['violation_severity']['medium']
        low_count = context.summary['violation_severity']['low']
        total = context.summary['total_violations']

        if total > 0:
            high_percent = f"{high_count/total*100:.1f}%"
            medium_percent = f"{medium_count/total*100:.1f}%"
            low_percent = f"{low_count/total*100:.1f}%"
        else:
            high_percent = "0%"
            medium_percent = "0%"
            low_percent = "0%"

        lines.append(f"| 1 | 严重 | {high_count}项 | {high_percent} |")
        lines.append(f"| 2 | 中等 | {medium_count}项 | {medium_percent} |")
        lines.append(f"| 3 | 轻微 | {low_count}项 | {low_percent} |")
        lines.append(f"| **合计** | **总计** | **{total}项** | **100%** |")

        # 严重违规明细表
        if context.high_violations:
            lines.append("")
            lines.append("**表2-2:严重违规明细表**")
            lines.append("| 序号 | 条款内容 | 问题说明 | 法规依据 |")
            lines.append("|:----:|:---------|:---------|:---------|")
            for i, v in enumerate(context.high_violations[:self.HIGH_VIOLATIONS_LIMIT], 1):
                clause_ref = v.get('clause_reference', '')
                # 优先使用预览字段，如果没有则回退到完整文本并截断
                clause_text = v.get('clause_text_preview', v.get('clause_text', '')[:80])
                description = v.get('description', '未知')
                # 使用 audit 的 regulation_citation
                regulation = v.get('regulation_citation', self._get_regulation_basis(v))
                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}:{clause_text}"
                else:
                    full_clause = clause_text
                lines.append(f"| {i} | {full_clause}... | {description} | {regulation} |")

        # 中等违规明细表
        if context.medium_violations:
            lines.append("")
            lines.append("**表2-3:中等违规明细表**")
            lines.append("| 序号 | 条款内容 | 问题说明 | 法规依据 |")
            lines.append("|:----:|:---------|:---------|:---------|")
            for i, v in enumerate(context.medium_violations[:self.MEDIUM_VIOLATIONS_LIMIT], 1):
                clause_ref = v.get('clause_reference', '')
                # 优先使用预览字段，如果没有则回退到完整文本并截断
                clause_text = v.get('clause_text_preview', v.get('clause_text', '')[:80])
                description = v.get('description', '未知')
                regulation = v.get('regulation_citation', self._get_regulation_basis(v))
                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}:{clause_text}"
                else:
                    full_clause = clause_text
                lines.append(f"| {i} | {full_clause}... | {description} | {regulation} |")

        # 定价问题
        pricing = context.pricing_analysis  # 已经是 {mortality, interest, expense} 格式
        if isinstance(pricing, dict):
            pricing_issues = []
            for category in ['mortality', 'interest', 'expense']:
                analysis = pricing.get(category)
                if analysis and not analysis.get('reasonable', True):
                    category_name = {
                        'mortality': '死亡率/发生率',
                        'interest': '预定利率',
                        'expense': '费用率'
                    }.get(category, category)
                    pricing_issues.append(f"{category_name}:{analysis.get('note', '不符合监管要求')}")

            if pricing_issues:
                lines.append("")
                lines.append("**表2-4:定价问题汇总表**")
                lines.append("| 序号 | 问题类型 | 问题描述 |")
                lines.append("|:----:|:---------|:---------|")
                for i, issue in enumerate(pricing_issues, 1):
                    parts = issue.split(':', 1)
                    issue_type = parts[0] if parts else '未知'
                    issue_desc = parts[1] if len(parts) > 1 else issue
                    lines.append(f"| {i} | {issue_type} | {issue_desc} |")

        return lines

    def _generate_suggestions_section(self, context: EvaluationContext) -> List[str]:
        """生成修改建议章节"""
        lines = []

        lines.append("三、修改建议")

        if context.high_violations:
            lines.append("**表3-1:P0级整改事项表(必须立即整改)**")
            lines.append("| 序号 | 条款原文 | 修改建议 |")
            lines.append("|:----:|:---------|:---------|")
            for i, v in enumerate(context.high_violations[:self.MEDIUM_VIOLATIONS_LIMIT], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                lines.append(f"| {i} | {clause_text}... | {remediation} |")

        if context.medium_violations:
            lines.append("")
            lines.append("**表3-2:P1级整改事项表(建议尽快整改)**")
            lines.append("| 序号 | 条款原文 | 修改建议 |")
            lines.append("|:----:|:---------|:---------|")
            for i, v in enumerate(context.medium_violations[:self.P1_REMEDIATION_MEDIUM_LIMIT], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                lines.append(f"| {i} | {clause_text}... | {remediation} |")

        return lines

    # ========== 飞书块生成辅助方法 ==========

    def _create_conclusion_blocks(self, context: EvaluationContext) -> List[Dict[str, Any]]:
        """创建审核结论章节块"""
        blocks = []

        blocks.append(self._create_heading_2("一、审核结论"))

        # 获取 overall_assessment（从 audit_result 或计算）
        audit_result = getattr(context, 'audit_result', None)
        if audit_result and hasattr(audit_result, 'overall_assessment'):
            opinion = audit_result.overall_assessment
            explanation = getattr(audit_result, 'assessment_reason', None) or self._get_default_explanation(context)
        else:
            # 根据 grade 生成审核意见
            grade_to_opinion = {
                '优秀': '通过',
                '良好': '通过',
                '合格': '通过',
                '不合格': '不通过'
            }
            opinion = grade_to_opinion.get(context.grade or 'unknown', '待定')
            explanation = self._get_default_explanation(context)

        blocks.append(self._create_bold_text(f"审核意见:{opinion}"))
        blocks.append(self._create_text(f"说明:{explanation}"))
        blocks.append(self._create_text(""))

        # 关键指标表格
        blocks.append(self._create_text("表1-1:关键指标汇总表"))

        high_count = context.summary['violation_severity']['high']
        medium_count = context.summary['violation_severity']['medium']
        low_count = context.summary['violation_severity']['low']
        total = context.summary['total_violations']
        pricing_issue_count = context.summary.get('pricing_issues', 0)

        key_metrics_data = [
            ["序号", "指标项", "结果", "说明"],
            ["1", "综合评分", f"{context.score}分", self._get_score_description(context.score)],
            ["2", "合规评级", context.grade, "基于违规数量和严重程度评定"],
            ["3", "违规总数", f"{total}项", f"严重{high_count}项,中等{medium_count}项,轻微{low_count}项"],
            ["4", "定价评估", "合理" if pricing_issue_count == 0 else "需关注", f"{pricing_issue_count}项定价参数需关注"]
        ]
        blocks.extend(self._create_table_blocks(key_metrics_data))

        return blocks

    def _create_details_blocks(self, context: EvaluationContext) -> List[Dict[str, Any]]:
        """创建问题详情章节块"""
        blocks = []

        blocks.append(self._create_heading_2("二、问题详情及依据"))

        # 生成审核依据(从 audit 获取)
        if context.regulation_basis:
            blocks.append(self._create_text("审核依据"))
            for reg in context.regulation_basis:
                blocks.append(self._create_text(reg))
            blocks.append(self._create_text(""))

        # 违规统计表
        blocks.append(self._create_text("表2-1:违规级别统计表"))

        high_count = context.summary['violation_severity']['high']
        medium_count = context.summary['violation_severity']['medium']
        low_count = context.summary['violation_severity']['low']
        total = context.summary['total_violations']

        if total > 0:
            high_percent = f"{high_count/total*100:.1f}%"
            medium_percent = f"{medium_count/total*100:.1f}%"
            low_percent = f"{low_count/total*100:.1f}%"
        else:
            high_percent = "0%"
            medium_percent = "0%"
            low_percent = "0%"

        violation_stats_data = [
            ["序号", "违规级别", "数量", "占比"],
            ["1", "严重", f"{high_count}项", high_percent],
            ["2", "中等", f"{medium_count}项", medium_percent],
            ["3", "轻微", f"{low_count}项", low_percent],
            ["合计", "总计", f"{total}项", "100%"]
        ]
        blocks.extend(self._create_table_blocks(violation_stats_data))

        # 严重违规明细表
        if context.high_violations:
            blocks.append(self._create_text(""))
            blocks.append(self._create_text("表2-2:严重违规明细表"))

            high_violation_data = [["序号", "条款内容", "问题说明", "法规依据"]]
            for i, v in enumerate(context.high_violations[:self.HIGH_VIOLATIONS_LIMIT], 1):
                clause_ref = v.get('clause_reference', '')
                clause_text = v.get('clause_text', '')[:80]
                description = v.get('description', '未知')
                regulation = v.get('regulation_citation', self._get_regulation_basis(v))
                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}:{clause_text}"
                else:
                    full_clause = clause_text
                high_violation_data.append([str(i), f"{full_clause}...", description, regulation])

            blocks.extend(self._create_table_blocks(high_violation_data))

        # 中等违规明细表
        if context.medium_violations:
            blocks.append(self._create_text(""))
            blocks.append(self._create_text("表2-3:中等违规明细表"))

            medium_violation_data = [["序号", "条款内容", "问题说明", "法规依据"]]
            for i, v in enumerate(context.medium_violations[:self.MEDIUM_VIOLATIONS_LIMIT], 1):
                clause_ref = v.get('clause_reference', '')
                # 优先使用预览字段，如果没有则回退到完整文本并截断
                clause_text = v.get('clause_text_preview', v.get('clause_text', '')[:80])
                description = v.get('description', '未知')
                regulation = v.get('regulation_citation', self._get_regulation_basis(v))
                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}:{clause_text}"
                else:
                    full_clause = clause_text
                medium_violation_data.append([str(i), f"{full_clause}...", description, regulation])

            blocks.extend(self._create_table_blocks(medium_violation_data))

        # 定价问题
        pricing = context.pricing_analysis  # 已经是 {mortality, interest, expense} 格式
        if isinstance(pricing, dict):
            pricing_issues = []
            for category in ['mortality', 'interest', 'expense']:
                analysis = pricing.get(category)
                if analysis and not analysis.get('reasonable', True):
                    category_name = {
                        'mortality': '死亡率/发生率',
                        'interest': '预定利率',
                        'expense': '费用率'
                    }.get(category, category)
                    pricing_issues.append(f"{category_name}:{analysis.get('note', '不符合监管要求')}")

            if pricing_issues:
                blocks.append(self._create_text(""))
                blocks.append(self._create_text("表2-4:定价问题汇总表"))

                pricing_data = [["序号", "问题类型", "问题描述"]]
                for i, issue in enumerate(pricing_issues, 1):
                    parts = issue.split(':', 1)
                    issue_type = parts[0] if parts else '未知'
                    issue_desc = parts[1] if len(parts) > 1 else issue
                    pricing_data.append([str(i), issue_type, issue_desc])

                blocks.extend(self._create_table_blocks(pricing_data))

        return blocks

    def _create_suggestions_blocks(self, context: EvaluationContext) -> List[Dict[str, Any]]:
        """创建修改建议章节块"""
        blocks = []

        blocks.append(self._create_heading_2("三、修改建议"))

        if context.high_violations:
            blocks.append(self._create_text("表3-1:P0级整改事项表(必须立即整改)"))

            p0_data = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(context.high_violations[:self.MEDIUM_VIOLATIONS_LIMIT], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                p0_data.append([str(i), f"{clause_text}...", remediation])

            blocks.extend(self._create_table_blocks(p0_data))

        if context.medium_violations:
            blocks.append(self._create_text(""))
            blocks.append(self._create_text("表3-2:P1级整改事项表(建议尽快整改)"))

            p1_data = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(context.medium_violations[:self.P1_REMEDIATION_MEDIUM_LIMIT], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                p1_data.append([str(i), f"{clause_text}...", remediation])

            blocks.extend(self._create_table_blocks(p1_data))

        return blocks

    # ========== 工具方法 ==========

    def _get_score_description(self, score: int) -> str:
        """
        获取评分描述

        Args:
            score: 分数

        Returns:
            str: 评分描述
        """
        if score >= 90:
            return "产品优秀,建议快速通过"
        elif score >= 80:
            return "产品良好,可正常上会"
        elif score >= 70:
            return "产品合格,建议完成修改后上会"
        elif score >= 60:
            return "产品基本合格,需补充说明材料"
        else:
            return "产品不合格,不建议提交审核"

    def _get_regulation_basis(self, violation: Dict[str, Any], category: str = "") -> str:
        """获取违规的法规依据

        Args:
            violation: 违规记录
            category: 违规类别（向后兼容）

        Returns:
            str: 法规依据
        """
        if 'regulation_citation' in violation and violation['regulation_citation']:
            return violation['regulation_citation']

        if 'regulation' in violation and violation['regulation']:
            return violation['regulation']

        if not category:
            category = violation.get('category', '')

        regulation_map = {
            '合规性': '《保险法》第十七条:订立保险合同,采用保险人提供的格式条款的,保险人向投保人提供的投保单应当附格式条款,保险人应当向投保人说明合同的内容。',
            '信息披露': '《人身保险公司保险条款和保险费率管理办法》第六条:保险条款应当符合下列要求:(一)结构清晰、文字准确、表述严谨、通俗易懂;(二)要素完整、内容完备',
            '条款清晰度': '《人身保险公司保险条款和保险费率管理办法》第三十六条:保险公司应当按照审慎原则拟定保险费率,不得因费率厘定不真实、不合理而损害投保人、被保险人和受益人的合法权益。',
            '费率合理性': '《健康保险管理办法》第十六条:健康保险产品应当根据被保险人的年龄、性别、健康状况等因素,合理确定保险费率和保险金额。',
        }
        return regulation_map.get(category, '《保险法》及相关监管规定')

    def _get_specific_remediation(self, violation: Dict[str, Any]) -> str:
        """获取具体整改建议（使用策略模式）

        优先使用违规记录中的整改建议，如果不存在或为空，则使用策略模式生成。

        Args:
            violation: 违规记录

        Returns:
            str: 具体的修改建议
        """
        # 优先使用违规记录中已有的整改建议
        if violation.get('remediation'):
            return violation['remediation']

        # 使用策略模式生成整改建议
        return self.remediation_strategies.get_remediation(violation)

    # ========== 飞书块创建方法 ==========

    def _create_heading_2(self, text: str) -> Dict[str, Any]:
        """创建二级标题块"""
        return {
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": text,
                        "style": {
                            "bold": True,
                            "text_size": "large"
                        }
                    }
                }]
            }
        }

    def _create_text(self, text: str) -> Dict[str, Any]:
        """创建文本块"""
        return {
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": text,
                        "style": {}
                    }
                }]
            }
        }

    def _create_bold_text(self, text: str) -> Dict[str, Any]:
        """创建粗体文本块"""
        return {
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": text,
                        "style": {
                            "bold": True
                        }
                    }
                }]
            }
        }

    def _create_table_blocks(self, table_data: List[List[str]]) -> List[Dict[str, Any]]:
        """创建表格块(使用文本块模拟)"""
        blocks = []

        for row_idx, row in enumerate(table_data):
            is_header = (row_idx == 0)

            # 对齐列(使用固定宽度)
            col_widths = [8, 20, 15, 15, 20]
            row_parts = []
            for col_idx, cell in enumerate(row):
                if col_idx < len(col_widths):
                    width = col_widths[col_idx]
                    # 左对齐或右对齐
                    if is_header or col_idx in [0]:
                        cell_text = f"{cell:<{width}}"
                    else:
                        cell_text = f"{cell:>{width}}"
                    row_parts.append(cell_text)

            row_text = " | ".join(row_parts)

            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [{
                        "text_run": {
                            "content": row_text,
                            "style": {
                                "bold": is_header,
                                "font_family": "Courier New"
                            }
                        }
                    }]
                }
            })

        return blocks
