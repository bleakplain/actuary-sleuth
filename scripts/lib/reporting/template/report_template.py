#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模板

ReportGenerationTemplate类：使用模板方法模式生成审核报告

模板方法定义报告生成的固定流程：
1. 计算评分 (_calculate_score)
2. 确定评级 (_calculate_grade)
3. 生成摘要 (_generate_summary)
4. 生成内容 (_generate_content)
5. 生成块 (_generate_blocks)
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from lib.config import get_config
from lib.id_generator import IDGenerator
from lib.reporting.strategies import RemediationStrategies
from lib.reporting.model import EvaluationContext, InsuranceProduct


class ReportGenerationTemplate:
    """
    报告生成模板

    使用模板方法模式,定义报告生成的固定流程:

    Template Method: generate()
        ├─ step 1: _calculate_score()      # 计算评分
        ├─ step 2: _calculate_grade()      # 确定评级
        ├─ step 3: _generate_summary()     # 生成摘要
        ├─ step 4: _generate_content()     # 生成内容 (核心步骤)
        └─ step 5: _generate_blocks()      # 生成块 (核心步骤)

    子类可以重写各步骤方法来定制报告生成行为。
    """

    # ========== 常量定义 ==========

    # 违规严重程度扣分值
    SEVERITY_PENALTY = {
        'high': 20,
        'medium': 10,
        'low': 5
    }

    # 评级阈值
    GRADE_THRESHOLDS = [
        (90, '优秀'),
        (75, '良好'),
        (60, '合格')
    ]
    GRADE_DEFAULT = '不合格'

    # 分数范围
    SCORE_MIN = 0
    SCORE_MAX = 100
    SCORE_BASE = 100

    # 定价问题扣分值
    PRICING_ISSUE_PENALTY = 10

    # 严重违规数量限制
    HIGH_VIOLATIONS_LIMIT = 20
    MEDIUM_VIOLATIONS_LIMIT = 10
    P1_REMEDIATION_MEDIUM_LIMIT = 5  # P1级整改事项表中的中危违规数量限制

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化报告生成模板

        Args:
            config: 配置字典(可选)
        """
        self.config = config or get_config()
        self.report_id = None
        self.remediation_strategies = RemediationStrategies()

    def generate(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any],
        product_info: Dict[str, Any],
        score: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        模板方法：按固定流程生成报告

        Steps:
            1. 构建评估上下文
            2. 计算综合评分
            3. 确定合规评级
            4. 统计违规摘要（含分组）
            5. 生成报告内容
            6. 转换为块格式

        Args:
            violations: 违规记录列表
            pricing_analysis: 定价分析结果
            product_info: 产品信息
            score: 自定义分数(可选)

        Returns:
            dict: 包含 report_id, score, grade, summary, content, blocks
        """
        # 步骤1: 构建评估上下文
        product = InsuranceProduct(
            name=product_info.get('product_name', '未知产品'),
            type=product_info.get('product_type', ''),
            company=product_info.get('insurance_company', ''),
            document_url=product_info.get('document_url', ''),
            version=product_info.get('version', '')
        )

        context = EvaluationContext(
            violations=violations,
            pricing_analysis=pricing_analysis,
            product=product
        )

        # 生成报告ID
        self.report_id = IDGenerator.generate_report()

        # 步骤2-4: 计算分数、评级、统计摘要（含分组）
        if score is not None:
            # 使用自定义分数
            context.score = max(self.SCORE_MIN, min(self.SCORE_MAX, score))
        else:
            # 计算分数
            self._calculate_score(context)

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

    def _calculate_score(self, context: EvaluationContext) -> None:
        """
        计算综合评分

        Args:
            context: 评估上下文，结果存储到 context.score
        """
        # 基础分
        score = self.SCORE_BASE

        # 根据违规严重程度扣分
        for violation in context.violations:
            severity = violation.get('severity', 'low')
            score -= self.SEVERITY_PENALTY.get(severity, 0)

        # 根据定价分析扣分
        pricing_issues = self._count_pricing_issues(context.pricing_analysis)
        score -= pricing_issues * self.PRICING_ISSUE_PENALTY

        # 确保分数在范围内
        context.score = max(self.SCORE_MIN, min(self.SCORE_MAX, score))

    def _calculate_grade(self, context: EvaluationContext) -> None:
        """
        计算评级

        Args:
            context: 评估上下文，结果存储到 context.grade
        """
        for threshold, grade in self.GRADE_THRESHOLDS:
            if context.score >= threshold:
                context.grade = grade
                return
        context.grade = self.GRADE_DEFAULT

    def _summarize_violations(self, context: EvaluationContext) -> None:
        """
        统计违规摘要并分组

        Args:
            context: 评估上下文，结果存储到 context.summary 和 context.context.high_violations 等
        """
        # 统计违规数量
        violation_summary = {
            'high': 0,
            'medium': 0,
            'low': 0
        }

        for violation in context.violations:
            severity = violation.get('severity', 'low')
            if severity in violation_summary:
                violation_summary[severity] += 1

        # 统计定价问题
        pricing_issues = self._count_pricing_issues(context.pricing_analysis)

        # 分组违规项（只做一次，提高性能）
        context.high_violations = [v for v in context.violations if v.get('severity') == 'high']
        context.medium_violations = [v for v in context.violations if v.get('severity') == 'medium']
        context.low_violations = [v for v in context.violations if v.get('severity') == 'low']

        # 生成审核依据
        context.regulation_basis = self._generate_regulation_basis(context)

        # 存储摘要
        context.summary = {
            'total_violations': len(context.violations),
            'violation_severity': violation_summary,
            'pricing_issues': pricing_issues,
            'has_critical_issues': violation_summary['high'] > 0 or pricing_issues > 1,
            'has_issues': len(context.violations) > 0 or pricing_issues > 0
        }

    def _count_pricing_issues(self, pricing_analysis: Dict[str, Any]) -> int:
        """
        统计定价问题数量

        Args:
            pricing_analysis: 定价分析结果

        Returns:
            int: 定价问题数量
        """
        pricing_issues = 0
        pricing = pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            for category in ['mortality', 'interest', 'expense']:
                analysis = pricing.get(category, {})
                if isinstance(analysis, dict) and analysis.get('reasonable') is False:
                    pricing_issues += 1
        return pricing_issues

    def _generate_content(self, context: EvaluationContext) -> str:
        """
        生成精算审核报告

        动态生成,基于实际审核情况:
        - 有问题才显示问题章节
        - 审核依据根据产品类型动态生成
        - 表格只在有数据时显示

        结构:
        1. 审核结论(始终显示)
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
        - 审核依据根据产品类型动态生成
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
        return {
            'product_name': context.product.name,
            'insurance_company': context.product.company,
            'product_type': context.product.type,
            'timestamp': datetime.now().isoformat()
        }

    # ========== 文本内容生成辅助方法 ==========

    def _generate_conclusion_section(self, context: EvaluationContext) -> List[str]:
        """生成审核结论章节"""
        lines = []

        lines.append("一、审核结论")

        # 生成审核意见
        opinion, explanation = self._generate_conclusion_text(context.score, context.summary)

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

    def _generate_details_section(self, context: EvaluationContext) -> List[str]:
        """生成问题详情章节"""
        lines = []

        lines.append("二、问题详情及依据")

        # 生成审核依据(动态)
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
                clause_text = v.get('clause_text', '')[:80]
                description = v.get('description', '未知')
                category = v.get('category', '')
                # 根据类别生成法规依据
                regulation = self._get_regulation_basis(category)
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
                clause_text = v.get('clause_text', '')[:80]
                description = v.get('description', '未知')
                category = v.get('category', '')
                regulation = self._get_regulation_basis(category)
                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}:{clause_text}"
                else:
                    full_clause = clause_text
                lines.append(f"| {i} | {full_clause}... | {description} | {regulation} |")

        # 定价问题
        pricing = context.pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            pricing_issues = []
            for category in ['interest', 'expense']:
                analysis = pricing.get(category)
                if analysis and not analysis.get('reasonable', True):
                    pricing_issues.append(f"{'预定利率' if category == 'interest' else '费用率'}:{analysis.get('note', '不符合监管要求')}")

            if pricing_issues:
                lines.append("")
                lines.append("**表2-4:定价问题汇总表**")
                lines.append("| 序号 | 问题类型 | 问题描述 |")
                lines.append("|:----:|:---------|:---------|")
                for i, issue in enumerate(pricing_issues, 1):
                    lines.append(f"| {i} | {'预定利率' if '预定利率' in issue else '费用率'} | {issue.split(':')[1] if ':' in issue else issue} |")

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

        # 生成审核意见
        opinion, explanation = self._generate_conclusion_text(context.score, context.summary)

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

        # 生成审核依据(动态)
        if context.regulation_basis:  # 只在有依据时显示
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
                category = v.get('category', '')
                regulation = self._get_regulation_basis(category)
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
                clause_text = v.get('clause_text', '')[:80]
                description = v.get('description', '未知')
                category = v.get('category', '')
                regulation = self._get_regulation_basis(category)
                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}:{clause_text}"
                else:
                    full_clause = clause_text
                medium_violation_data.append([str(i), f"{full_clause}...", description, regulation])

            blocks.extend(self._create_table_blocks(medium_violation_data))

        # 定价问题
        pricing = context.pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            pricing_issues = []
            for category in ['interest', 'expense']:
                analysis = pricing.get(category)
                if analysis and not analysis.get('reasonable', True):
                    pricing_issues.append(f"{'预定利率' if category == 'interest' else '费用率'}:{analysis.get('note', '不符合监管要求')}")

            if pricing_issues:
                blocks.append(self._create_text(""))
                blocks.append(self._create_text("表2-4:定价问题汇总表"))

                pricing_data = [["序号", "问题类型", "问题描述"]]
                for i, issue in enumerate(pricing_issues, 1):
                    pricing_data.append([str(i), '预定利率' if '预定利率' in issue else '费用率', issue.split(':')[1] if ':' in issue else issue])

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

    def _generate_conclusion_text(self, score: int, summary: Dict[str, Any]) -> tuple:
        """
        生成审核结论文本

        Args:
            score: 综合评分
            summary: 报告摘要

        Returns:
            tuple: (opinion, explanation)
        """
        high_count = summary['violation_severity']['high']
        medium_count = summary['violation_severity']['medium']
        total = summary['total_violations']

        # 审核意见决策
        if high_count > 0:
            opinion = "不推荐上会"
            explanation = f"产品存在{high_count}项严重违规,触及监管红线,需完成整改后重新审核"
        elif score >= 90:
            opinion = "推荐通过"
            explanation = "产品符合所有监管要求,未发现违规问题"
        elif score >= 75:
            opinion = "条件推荐"
            explanation = f"产品整体符合要求,存在{medium_count}项中等问题,建议完成修改后提交审核"
        elif score >= 60:
            opinion = "需补充材料"
            explanation = f"产品存在{total}项问题,建议补充说明材料后复审"
        else:
            opinion = "不予推荐"
            explanation = "产品合规性不足,不建议提交审核"

        return opinion, explanation

    def _generate_regulation_basis(self, context: EvaluationContext) -> List[str]:
        """
        动态生成审核依据

        基于产品类型和违规情况,动态生成适用的法规依据列表

        Args:
            context: 评估上下文

        Returns:
            list: 法规依据列表
        """
        basis = []

        # 基础法规(始终适用)
        basis.append("《中华人民共和国保险法》")

        # 根据产品类型添加专项法规
        product_type = context.product.type.lower()
        type_regulations = {
            '寿险': '《人身保险公司保险条款和保险费率管理办法》',
            '健康险': '《健康保险管理办法》',
            '意外险': '《意外伤害保险管理办法》',
            '万能险': '《万能型人身保险管理办法》',
            '分红险': '《分红型人身保险管理办法》',
        }

        for key, regulation in type_regulations.items():
            if key in product_type:
                basis.append(regulation)
                break

        # 如果没有匹配到专项法规,添加通用规定
        if len(basis) == 1:
            basis.append('《保险公司管理规定》')

        # 提取违规记录中引用的法规(如果有)
        if context.violations:
            cited_regs = set()
            for v in context.violations:
                if v.get('regulation_citation'):
                    cited_regs.add(v['regulation_citation'])

            if cited_regs:
                basis.extend(sorted(cited_regs))

        return basis

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

    def _get_regulation_basis(self, category: str) -> str:
        """根据违规类别返回法规依据(包含具体条款内容)

        Args:
            category: 违规类别

        Returns:
            str: 法规依据(法规名称+条款+内容)
        """
        regulation_map = {
            '产品条款表述': '《保险法》第十七条:订立保险合同,采用保险人提供的格式条款的,保险人向投保人提供的投保单应当附格式条款,保险人应当向投保人说明合同的内容。',
            '产品责任设计': '《人身保险公司保险条款和保险费率管理办法》第六条:保险条款应当符合下列要求:(一)结构清晰、文字准确、表述严谨、通俗易懂；(二)要素完整、内容完备',
            '产品费率厘定及精算假设': '《人身保险公司保险条款和保险费率管理办法》第三十六条:保险公司应当按照审慎原则拟定保险费率,不得因费率厘定不真实、不合理而损害投保人、被保险人和受益人的合法权益。',
            '产品报送管理': '《人身保险公司保险条款和保险费率管理办法》第十二条:保险公司报送审批或者备案的保险条款和保险费率,应当符合下列条件:(一)结构清晰、文字准确、表述严谨、通俗易懂',
            '产品形态设计': '《健康保险管理办法》第十六条:健康保险产品应当根据被保险人的年龄、性别、健康状况等因素,合理确定保险费率和保险金额。',
            '销售管理': '《保险销售行为监管办法》第十三条:保险销售人员应当向投保人说明保险合同的内容,特别是对投保人、被保险人、受益人的权利和义务、免除保险人责任的条款以及其他重要条款。',
            '理赔管理': '《保险法》第二十二条:保险事故发生后,按照保险合同请求保险人赔偿或者给付保险金时,投保人、被保险人或者受益人应当向保险人提供其所能提供的与确认保险事故的性质、原因、损失程度等有关的证明和资料。',
            '客户服务': '《保险公司服务管理办法》第八条:保险公司应当建立客户服务制度,明确服务标准和服务流程。'
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
