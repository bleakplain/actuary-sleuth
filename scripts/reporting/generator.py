#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成器模块

提供面向对象的报告生成接口
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

# 兼容相对导入和绝对导入
try:
    from ..infrastructure.config import get_config
    from ..infrastructure.id_generator import IDGenerator
except ImportError:
    # 当作为脚本运行或直接导入时使用绝对导入
    import sys
    from pathlib import Path
    scripts_dir = Path(__file__).parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from infrastructure.config import get_config
    from infrastructure.id_generator import IDGenerator


# ========== 整改建议模式映射 ==========

# 违规关键词到具体整改建议的映射
REMEDIATION_PATTERNS = {
    '等待期': {
        '过长': '将等待期调整为90天以内',
        '超过': '将等待期调整为90天以内',
        '症状': '删除将等待期内症状或体征作为免责依据的表述',
        '体征': '删除将等待期内症状或体征作为免责依据的表述',
        '突出': '在条款中以加粗或红色字体突出说明等待期',
        '_default': '合理设置等待期长度，确保符合监管规定'
    },
    '免责条款': {
        '不集中': '将免责条款集中在合同显著位置',
        '不清晰': '使用清晰明确的语言表述免责情形',
        '表述不清': '使用清晰明确的语言表述免责情形',
        '加粗': '使用加粗或红色字体突出显示免责条款',
        '标红': '使用加粗或红色字体突出显示免责条款',
        '突出': '使用加粗或红色字体突出显示免责条款',
        '免除': '删除不合理的免责条款，确保不违反保险法规定',
        '_default': '完善免责条款的表述和展示方式'
    },
    '责任免除': {
        '_default': '完善免责条款的表述和展示方式'
    },
    '保险金额': {
        '不规范': '使用规范的保险金额表述，确保与保险法一致',
        '不一致': '使用规范的保险金额表述，确保与保险法一致',
        '_default': '明确保险金额的确定方式和计算标准'
    },
    '保证收益': {
        '_default': '删除保证收益相关表述，改为演示收益或说明利益不确定'
    },
    '演示收益': {
        '_default': '删除保证收益相关表述，改为演示收益或说明利益不确定'
    },
    '费率': {
        '倒算': '停止使用倒算方式确定费率，采用精算方法',
        '偏离实际': '根据实际费用水平重新核算附加费用率',
        '不真实': '重新进行费率厘定，确保符合审慎原则',
        '不合理': '重新进行费率厘定，确保符合审慎原则',
        '_default': '规范费率厘定方法，确保符合监管要求'
    },
    '现金价值': {
        '超过': '调整现金价值计算方法，确保不超过已交保费',
        '异化': '调整现金价值计算方法，确保不超过已交保费',
        '_default': '规范现金价值计算，确保符合监管规定'
    },
    '基因': {
        '_default': '删除根据基因检测结果调节费率的约定'
    },
    '犹豫期': {
        '过短': '将犹豫期调整为15天以上',
        '不足': '将犹豫期调整为15天以上',
        '_default': '规范犹豫期的起算和时长'
    },
    '利率': {
        '超过': '将预定利率调整为监管上限以内',
        '超标': '将预定利率调整为监管上限以内',
        '_default': '确保预定利率符合监管规定'
    },
    '预定利率': {
        '超过': '将预定利率调整为监管上限以内',
        '超标': '将预定利率调整为监管上限以内',
        '_default': '确保预定利率符合监管规定'
    },
    '备案': {
        '不达标': '停止销售不达标产品，按规定报送停止使用报告',
        '未报送': '停止销售不达标产品，按规定报送停止使用报告',
        '_default': '完善产品备案管理，确保符合监管要求'
    },
    '产品设计异化': {
        '万能型': '调整产品形态设计，避免异化为万能型产品',
        '偏离': '强化风险保障功能，确保符合保险本质',
        '_default': '优化产品设计，确保符合保险保障属性'
    },
    '异化': {
        '万能型': '调整产品形态设计，避免异化为万能型产品',
        '偏离': '强化风险保障功能，确保符合保险本质',
        '_default': '优化产品设计，确保符合保险保障属性'
    },
    '条款文字': {
        '_default': '简化条款表述，使用通俗易懂的语言'
    },
    '冗长': {
        '_default': '简化条款表述，使用通俗易懂的语言'
    },
    '不易懂': {
        '_default': '简化条款表述，使用通俗易懂的语言'
    },
    '职业': {
        '_default': '明确职业类别要求和限制'
    },
    '类别': {
        '_default': '明确职业类别要求和限制'
    },
    '年龄': {
        '_default': '明确投保年龄范围和要求'
    },
    '保险期间': {
        '_default': '明确保险期间和保障期限'
    },
    '保险期限': {
        '_default': '明确保险期间和保障期限'
    },
}

# 模糊建议列表
VAGUE_REMEDIATION_PHRASES = ['请根据具体情况', '确保符合', '无', '', '按照《保险法》规定', '建议']


class ReportGenerator:
    """审核报告生成器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化报告生成器

        Args:
            config: 配置字典（可选）
        """
        self.config = config or get_config()
        self.report_id = None

    def generate(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any],
        product_info: Dict[str, Any],
        score: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        生成完整的审核报告

        Args:
            violations: 违规记录列表
            pricing_analysis: 定价分析结果
            product_info: 产品信息
            score: 自定义分数（可选）

        Returns:
            包含报告内容的字典
        """
        # 生成报告ID
        self.report_id = IDGenerator.generate_report()

        # 计算分数和评级
        if score is None:
            score = self._calculate_score(violations, pricing_analysis)

        grade = self._calculate_grade(score)
        summary = self._generate_summary(violations, pricing_analysis)

        # 生成报告内容
        content = self._generate_content(
            violations, pricing_analysis, product_info,
            score, grade, summary
        )

        # 生成报告块
        blocks = self._generate_blocks(
            violations, pricing_analysis, product_info,
            score, grade, summary
        )

        return {
            'success': True,
            'report_id': self.report_id,
            'score': score,
            'grade': grade,
            'summary': summary,
            'content': content,
            'blocks': blocks,
            'metadata': self._generate_metadata(product_info)
        }

    def _calculate_score(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any]
    ) -> int:
        """
        计算综合评分

        Args:
            violations: 违规记录列表
            pricing_analysis: 定价分析结果

        Returns:
            int: 评分（0-100）
        """
        # 基础分
        score = 100

        # 根据违规严重程度扣分
        for violation in violations:
            severity = violation.get('severity', 'low')
            if severity == 'high':
                score -= 20
            elif severity == 'medium':
                score -= 10
            elif severity == 'low':
                score -= 5

        # 根据定价分析扣分
        pricing = pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            for category in ['mortality', 'interest', 'expense']:
                analysis = pricing.get(category, {})
                if isinstance(analysis, dict) and analysis.get('reasonable') is False:
                    score -= 10

        # 确保分数在 0-100 范围内
        return max(0, min(100, score))

    def _calculate_grade(self, score: int) -> str:
        """
        计算评级

        Args:
            score: 分数

        Returns:
            str: 评级
        """
        if score >= 90:
            return '优秀'
        elif score >= 75:
            return '良好'
        elif score >= 60:
            return '合格'
        else:
            return '不合格'

    def _generate_summary(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成报告摘要

        Args:
            violations: 违规记录列表
            pricing_analysis: 定价分析结果

        Returns:
            dict: 关键信息
        """
        # 统计违规数量
        violation_summary = {
            'high': 0,
            'medium': 0,
            'low': 0
        }

        for violation in violations:
            severity = violation.get('severity', 'low')
            if severity in violation_summary:
                violation_summary[severity] += 1

        # 统计定价问题
        pricing_issues = 0
        pricing = pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            for category in ['mortality', 'interest', 'expense']:
                analysis = pricing.get(category, {})
                if isinstance(analysis, dict) and analysis.get('reasonable') is False:
                    pricing_issues += 1

        return {
            'total_violations': len(violations),
            'violation_severity': violation_summary,
            'pricing_issues': pricing_issues,
            'has_critical_issues': violation_summary['high'] > 0 or pricing_issues > 1,
            'has_issues': len(violations) > 0 or pricing_issues > 0
        }

    def _generate_content(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any],
        product_info: Dict[str, Any],
        score: int,
        grade: str,
        summary: Dict[str, Any]
    ) -> str:
        """
        生成精算审核报告

        动态生成，基于实际审核情况：
        - 有问题才显示问题章节
        - 审核依据根据产品类型动态生成
        - 表格只在有数据时显示

        结构：
        1. 审核结论（始终显示）
        2. 问题详情及依据（有问题时显示）
        3. 修改建议（有问题时显示）
        """
        lines = []

        # ========== 审核结论（始终显示） ==========
        lines.extend(self._generate_conclusion_section(score, grade, summary))

        # ========== 问题详情（有问题时显示） ==========
        if summary.get('has_issues', False):
            lines.append("")
            lines.extend(self._generate_details_section(violations, pricing_analysis, product_info, summary))

        # ========== 修改建议（有问题时显示） ==========
        if summary.get('has_issues', False):
            lines.append("")
            lines.extend(self._generate_suggestions_section(violations, summary))

        return '\n'.join(lines)

    def _generate_blocks(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any],
        product_info: Dict[str, Any],
        score: int,
        grade: str,
        summary: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        生成报告块（飞书格式）

        动态生成，基于实际审核情况：
        - 有问题才显示问题章节
        - 审核依据根据产品类型动态生成
        - 表格只在有数据时显示
        """
        blocks = []

        # ========== 审核结论（始终显示） ==========
        blocks.extend(self._create_conclusion_blocks(score, grade, summary))

        # ========== 问题详情（有问题时显示） ==========
        if summary.get('has_issues', False):
            blocks.append(self._create_text(""))
            blocks.extend(self._create_details_blocks(violations, pricing_analysis, product_info, summary))

        # ========== 修改建议（有问题时显示） ==========
        if summary.get('has_issues', False):
            blocks.append(self._create_text(""))
            blocks.extend(self._create_suggestions_blocks(violations, summary))

        return blocks

    def _generate_metadata(self, product_info: Dict[str, Any]) -> Dict[str, Any]:
        """生成元数据"""
        return {
            'product_name': product_info.get('product_name', '未知产品'),
            'insurance_company': product_info.get('insurance_company', '未知'),
            'product_type': product_info.get('product_type', '未知'),
            'timestamp': datetime.now().isoformat()
        }

    # ========== 文本内容生成辅助方法 ==========

    def _generate_conclusion_section(self, score: int, grade: str, summary: Dict[str, Any]) -> List[str]:
        """生成审核结论章节"""
        lines = []

        lines.append("一、审核结论")

        # 生成审核意见
        opinion, explanation = self._generate_conclusion_text(score, summary)

        lines.append(f"**审核意见**：{opinion}")
        lines.append(f"**说明**：{explanation}")
        lines.append("")

        # 关键数据表格
        high_count = summary['violation_severity']['high']
        medium_count = summary['violation_severity']['medium']
        low_count = summary['violation_severity']['low']
        total = summary['total_violations']
        pricing_issue_count = summary.get('pricing_issues', 0)

        lines.append("**表1-1：关键指标汇总表**")
        lines.append("| 序号 | 指标项 | 结果 | 说明 |")
        lines.append("|:----:|:------|:-----|:-----|")
        lines.append(f"| 1 | 综合评分 | {score}分 | {self._get_score_description(score)} |")
        lines.append(f"| 2 | 合规评级 | {grade} | 基于违规数量和严重程度评定 |")
        lines.append(f"| 3 | 违规总数 | {total}项 | 严重{high_count}项，中等{medium_count}项，轻微{low_count}项 |")
        lines.append(f"| 4 | 定价评估 | {'合理' if pricing_issue_count == 0 else '需关注'} | {pricing_issue_count}项定价参数需关注 |")

        return lines

    def _generate_details_section(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any],
        product_info: Dict[str, Any],
        summary: Dict[str, Any]
    ) -> List[str]:
        """生成问题详情章节"""
        lines = []

        lines.append("二、问题详情及依据")

        # 生成审核依据（动态）
        regulation_basis = self._generate_regulation_basis(violations, product_info)
        lines.append("**审核依据**")
        for i, reg in enumerate(regulation_basis, 1):
            lines.append(f"{i}. {reg}")
        lines.append("")

        # 按严重程度分组
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']

        # 违规统计表
        lines.append("**表2-1：违规级别统计表**")
        lines.append("")
        lines.append("| 序号 | 违规级别 | 数量 | 占比 |")
        lines.append("|:----:|:--------|:----:|:----:|")

        high_count = summary['violation_severity']['high']
        medium_count = summary['violation_severity']['medium']
        low_count = summary['violation_severity']['low']
        total = summary['total_violations']

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
        if high_violations:
            lines.append("")
            lines.append("**表2-2：严重违规明细表**")
            lines.append("| 序号 | 条款内容 | 问题说明 | 法规依据 |")
            lines.append("|:----:|:---------|:---------|:---------|")
            for i, v in enumerate(high_violations[:20], 1):
                clause_ref = v.get('clause_reference', '')
                clause_text = v.get('clause_text', '')[:80]
                description = v.get('description', '未知')
                category = v.get('category', '')
                # 根据类别生成法规依据
                regulation = self._get_regulation_basis(category)
                # 合并条款引用和原文
                if clause_ref and not clause_ref.startswith('段落'):
                    full_clause = f"{clause_ref}：{clause_text}"
                else:
                    full_clause = clause_text
                lines.append(f"| {i} | {full_clause}... | {description} | {regulation} |")

        # 中等违规明细表
        if medium_violations:
            lines.append("")
            lines.append("**表2-3：中等违规明细表**")
            lines.append("| 序号 | 条款内容 | 问题说明 | 法规依据 |")
            lines.append("|:----:|:---------|:---------|:---------|")
            for i, v in enumerate(medium_violations[:10], 1):
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
                lines.append(f"| {i} | {full_clause}... | {description} | {regulation} |")

        # 定价问题
        pricing = pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            pricing_issues = []
            for category in ['interest', 'expense']:
                analysis = pricing.get(category)
                if analysis and not analysis.get('reasonable', True):
                    pricing_issues.append(f"{'预定利率' if category == 'interest' else '费用率'}：{analysis.get('note', '不符合监管要求')}")

            if pricing_issues:
                lines.append("")
                lines.append("**表2-4：定价问题汇总表**")
                lines.append("| 序号 | 问题类型 | 问题描述 |")
                lines.append("|:----:|:---------|:---------|")
                for i, issue in enumerate(pricing_issues, 1):
                    lines.append(f"| {i} | {'预定利率' if '预定利率' in issue else '费用率'} | {issue.split('：')[1] if '：' in issue else issue} |")

        return lines

    def _generate_suggestions_section(self, violations: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[str]:
        """生成修改建议章节"""
        lines = []

        lines.append("三、修改建议")

        # 按严重程度分组
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']

        if high_violations:
            lines.append("**表3-1：P0级整改事项表（必须立即整改）**")
            lines.append("| 序号 | 条款原文 | 修改建议 |")
            lines.append("|:----:|:---------|:---------|")
            for i, v in enumerate(high_violations[:10], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                lines.append(f"| {i} | {clause_text}... | {remediation} |")

        if medium_violations:
            lines.append("")
            lines.append("**表3-2：P1级整改事项表（建议尽快整改）**")
            lines.append("| 序号 | 条款原文 | 修改建议 |")
            lines.append("|:----:|:---------|:---------|")
            for i, v in enumerate(medium_violations[:5], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                lines.append(f"| {i} | {clause_text}... | {remediation} |")

        return lines

    # ========== 飞书块生成辅助方法 ==========

    def _create_conclusion_blocks(self, score: int, grade: str, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        """创建审核结论章节块"""
        blocks = []

        blocks.append(self._create_heading_2("一、审核结论"))

        # 生成审核意见
        opinion, explanation = self._generate_conclusion_text(score, summary)

        blocks.append(self._create_bold_text(f"审核意见：{opinion}"))
        blocks.append(self._create_text(f"说明：{explanation}"))
        blocks.append(self._create_text(""))

        # 关键指标表格
        blocks.append(self._create_text("表1-1：关键指标汇总表"))

        high_count = summary['violation_severity']['high']
        medium_count = summary['violation_severity']['medium']
        low_count = summary['violation_severity']['low']
        total = summary['total_violations']
        pricing_issue_count = summary.get('pricing_issues', 0)

        key_metrics_data = [
            ["序号", "指标项", "结果", "说明"],
            ["1", "综合评分", f"{score}分", self._get_score_description(score)],
            ["2", "合规评级", grade, "基于违规数量和严重程度评定"],
            ["3", "违规总数", f"{total}项", f"严重{high_count}项，中等{medium_count}项，轻微{low_count}项"],
            ["4", "定价评估", "合理" if pricing_issue_count == 0 else "需关注", f"{pricing_issue_count}项定价参数需关注"]
        ]
        blocks.extend(self._create_table_blocks(key_metrics_data))

        return blocks

    def _create_details_blocks(
        self,
        violations: List[Dict[str, Any]],
        pricing_analysis: Dict[str, Any],
        product_info: Dict[str, Any],
        summary: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """创建问题详情章节块"""
        blocks = []

        blocks.append(self._create_heading_2("二、问题详情及依据"))

        # 生成审核依据（动态）
        regulation_basis = self._generate_regulation_basis(violations, product_info)
        if regulation_basis:  # 只在有依据时显示
            blocks.append(self._create_text("审核依据"))
            for reg in regulation_basis:
                blocks.append(self._create_text(reg))
            blocks.append(self._create_text(""))

        # 违规统计表
        blocks.append(self._create_text("表2-1：违规级别统计表"))

        high_count = summary['violation_severity']['high']
        medium_count = summary['violation_severity']['medium']
        low_count = summary['violation_severity']['low']
        total = summary['total_violations']

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

        # 按严重程度分组
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']

        # 严重违规明细表
        if high_violations:
            blocks.append(self._create_text(""))
            blocks.append(self._create_text("表2-2：严重违规明细表"))

            high_violation_data = [["序号", "条款内容", "问题说明", "法规依据"]]
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
                high_violation_data.append([str(i), f"{full_clause}...", description, regulation])

            blocks.extend(self._create_table_blocks(high_violation_data))

        # 中等违规明细表
        if medium_violations:
            blocks.append(self._create_text(""))
            blocks.append(self._create_text("表2-3：中等违规明细表"))

            medium_violation_data = [["序号", "条款内容", "问题说明", "法规依据"]]
            for i, v in enumerate(medium_violations[:10], 1):
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
                medium_violation_data.append([str(i), f"{full_clause}...", description, regulation])

            blocks.extend(self._create_table_blocks(medium_violation_data))

        # 定价问题
        pricing = pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            pricing_issues = []
            for category in ['interest', 'expense']:
                analysis = pricing.get(category)
                if analysis and not analysis.get('reasonable', True):
                    pricing_issues.append(f"{'预定利率' if category == 'interest' else '费用率'}：{analysis.get('note', '不符合监管要求')}")

            if pricing_issues:
                blocks.append(self._create_text(""))
                blocks.append(self._create_text("表2-4：定价问题汇总表"))

                pricing_data = [["序号", "问题类型", "问题描述"]]
                for i, issue in enumerate(pricing_issues, 1):
                    pricing_data.append([str(i), '预定利率' if '预定利率' in issue else '费用率', issue.split('：')[1] if '：' in issue else issue])

                blocks.extend(self._create_table_blocks(pricing_data))

        return blocks

    def _create_suggestions_blocks(self, violations: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        """创建修改建议章节块"""
        blocks = []

        blocks.append(self._create_heading_2("三、修改建议"))

        # 按严重程度分组
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']

        if high_violations:
            blocks.append(self._create_text("表3-1：P0级整改事项表（必须立即整改）"))

            p0_data = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(high_violations[:10], 1):
                clause_text = v.get('clause_text', '')[:40]
                remediation = self._get_specific_remediation(v)
                p0_data.append([str(i), f"{clause_text}...", remediation])

            blocks.extend(self._create_table_blocks(p0_data))

        if medium_violations:
            blocks.append(self._create_text(""))
            blocks.append(self._create_text("表3-2：P1级整改事项表（建议尽快整改）"))

            p1_data = [["序号", "条款原文", "修改建议"]]
            for i, v in enumerate(medium_violations[:5], 1):
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

    def _generate_regulation_basis(self, violations: List[Dict[str, Any]], product_info: Dict[str, Any]) -> List[str]:
        """
        动态生成审核依据

        基于产品类型和违规情况，动态生成适用的法规依据列表

        Args:
            violations: 违规记录列表
            product_info: 产品信息

        Returns:
            list: 法规依据列表
        """
        basis = []

        # 基础法规（始终适用）
        basis.append("《中华人民共和国保险法》")

        # 根据产品类型添加专项法规
        product_type = product_info.get('product_type', '').lower()
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

        # 如果没有匹配到专项法规，添加通用规定
        if len(basis) == 1:
            basis.append('《保险公司管理规定》')

        # 提取违规记录中引用的法规（如果有）
        if violations:
            cited_regs = set()
            for v in violations:
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
            return "产品优秀，建议快速通过"
        elif score >= 80:
            return "产品良好，可正常上会"
        elif score >= 70:
            return "产品合格，建议完成修改后上会"
        elif score >= 60:
            return "产品基本合格，需补充说明材料"
        else:
            return "产品不合格，不建议提交审核"

    def _get_regulation_basis(self, category: str) -> str:
        """根据违规类别返回法规依据（包含具体条款内容）

        Args:
            category: 违规类别

        Returns:
            str: 法规依据（法规名称+条款+内容）
        """
        regulation_map = {
            '产品条款表述': '《保险法》第十七条：订立保险合同，采用保险人提供的格式条款的，保险人向投保人提供的投保单应当附格式条款，保险人应当向投保人说明合同的内容。',
            '产品责任设计': '《人身保险公司保险条款和保险费率管理办法》第六条：保险条款应当符合下列要求：（一）结构清晰、文字准确、表述严谨、通俗易懂；（二）要素完整、内容完备',
            '产品费率厘定及精算假设': '《人身保险公司保险条款和保险费率管理办法》第三十六条：保险公司应当按照审慎原则拟定保险费率，不得因费率厘定不真实、不合理而损害投保人、被保险人和受益人的合法权益。',
            '产品报送管理': '《人身保险公司保险条款和保险费率管理办法》第十二条：保险公司报送审批或者备案的保险条款和保险费率，应当符合下列条件：（一）结构清晰、文字准确、表述严谨、通俗易懂',
            '产品形态设计': '《健康保险管理办法》第十六条：健康保险产品应当根据被保险人的年龄、性别、健康状况等因素，合理确定保险费率和保险金额。',
            '销售管理': '《保险销售行为监管办法》第十三条：保险销售人员应当向投保人说明保险合同的内容，特别是对投保人、被保险人、受益人的权利和义务、免除保险人责任的条款以及其他重要条款。',
            '理赔管理': '《保险法》第二十二条：保险事故发生后，按照保险合同请求保险人赔偿或者给付保险金时，投保人、被保险人或者受益人应当向保险人提供其所能提供的与确认保险事故的性质、原因、损失程度等有关的证明和资料。',
            '客户服务': '《保险公司服务管理办法》第八条：保险公司应当建立客户服务制度，明确服务标准和服务流程。'
        }
        return regulation_map.get(category, '《保险法》及相关监管规定')

    def _find_remediation_by_pattern(self, description: str, category: str) -> Optional[str]:
        """根据违规描述关键词查找具体整改建议

        Args:
            description: 违规描述
            category: 违规类别

        Returns:
            具体整改建议，如果未找到返回 None
        """
        # 先尝试类别匹配
        for category_key, pattern_dict in REMEDIATION_PATTERNS.items():
            if category_key in description or category_key in category:
                # 尝试关键词匹配
                for keyword, remediation in pattern_dict.items():
                    if keyword == '_default':
                        continue
                    if keyword in description:
                        return remediation
                # 使用默认建议
                return pattern_dict.get('_default', '')

        return None

    def _get_fallback_remediation(self, description: str) -> str:
        """当没有匹配的模式时，生成后备建议

        Args:
            description: 违规描述

        Returns:
            后备建议
        """
        if '规定' in description or '违反' in description:
            # 找出违反的是什么规定
            words = description.split('，')
            if len(words) > 1:
                issue_part = words[0][:30]
                return f"针对{issue_part}问题进行调整"
            else:
                return '请根据违规描述进行相应调整，确保符合监管要求'
        else:
            # 如果无法识别具体问题，返回基于类别的一般建议
            return '请根据问题描述进行相应调整，确保符合监管要求'

    def _get_specific_remediation(self, violation: Dict[str, Any]) -> str:
        """生成具体的修改建议（基于实际违规描述动态生成）

        Args:
            violation: 违规记录

        Returns:
            str: 具体的修改建议
        """
        # 获取数据库中的默认建议
        default_remediation = violation.get('remediation', '')
        description = violation.get('description', '')
        category = violation.get('category', '')

        # 如果默认建议是空或太模糊，则基于违规描述生成具体建议
        if any(phrase in default_remediation for phrase in VAGUE_REMEDIATION_PHRASES):
            # 尝试使用模式匹配
            specific_remediation = self._find_remediation_by_pattern(description, category)
            if specific_remediation:
                return specific_remediation

            # 如果模式匹配失败，使用后备建议
            return self._get_fallback_remediation(description)

        return default_remediation

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
        """创建表格块（使用文本块模拟）"""
        blocks = []

        for row_idx, row in enumerate(table_data):
            is_header = (row_idx == 0)

            # 对齐列（使用固定宽度）
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
