#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档解析共享工具"""
from __future__ import annotations

from typing import Tuple, Dict, List, Any

from ..models import SectionType, DocumentSection, Clause


def split_title_and_content(content: str) -> Tuple[str, str]:
    """分离条款标题和正文。

    保险产品条款格式：标题 正文内容
    如：被保险人范围 凡出生满28天至70周岁7.1，在本公司认可的医院...

    标题通常是 4-15 字的名词短语，以"范围"、"期间"、"责任"等双字词结尾。
    """
    if not content:
        return '', ''

    content = content.strip()

    # 先处理换行符
    if '\n' in content:
        lines = content.split('\n')
        first_line = lines[0].strip()
        if len(first_line) <= 15 and first_line:
            remaining = '\n'.join(lines[1:]).strip()
            return first_line, remaining

    # 条款标题常见结尾双字词
    title_enders = [
        '范围', '期间', '责任', '金额', '事项', '条款', '条件',
        '原则', '规定', '程序', '流程', '标准', '要求', '义务',
        '权利', '效力', '限额', '比例', '费用', '保费', '年龄',
        '构成', '生效', '终止', '解除', '变更', '转让', '计划',
    ]

    # 查找标题边界：检查双字结尾词
    for i in range(3, min(len(content) - 1, 20)):
        two_chars = content[i:i+2]
        if two_chars in title_enders:
            # 结尾词后是空格或换行
            if i + 2 < len(content):
                next_char = content[i + 2]
                if next_char in ' \n\t':
                    return content[:i + 2].strip(), content[i + 2:].strip()
                # 结尾词后是"投保人"、"凡"、"本"等正文开头词
                next_two = content[i+2:i+4] if i+4 <= len(content) else ''
                if next_two in ['投保人', '凡出生', '凡投保', '本合同', '被保险', '由投保']:
                    return content[:i + 2].strip(), content[i + 2:].strip()

    if len(content) <= 15:
        return content, ''

    return content[:15].strip(), content[15:].strip()



_SECTION_KEY_MAP = {
    SectionType.NOTICE: 'notices',
    SectionType.HEALTH_DISCLOSURE: 'health_disclosures',
    SectionType.EXCLUSION: 'exclusions',
    SectionType.RIDER: 'rider_clauses',
}


def add_section(
    result: Dict[str, List[Any]],
    section_type: SectionType,
    title: str,
    content: str,
) -> None:
    """添加文档章节到结果字典。

    对于 rider_clauses，创建 Clause 对象（包含 number 属性）。
    对于其他类型，创建 DocumentSection 对象。
    """
    key = _SECTION_KEY_MAP.get(section_type)
    if not key:
        return

    if section_type == SectionType.RIDER:
        # rider_clauses 是 List[Clause] 类型，需要有 number 属性
        # 从 title 中提取编号（如 "1.2 附加险条款" -> number="1.2", title="附加险条款"）
        import re
        match = re.match(r'^(\d+(?:\.\d+)*)\s+(.+)$', title.strip())
        if match:
            number = match.group(1)
            clause_title = match.group(2).strip()
        else:
            number = ''
            clause_title = title
        result[key].append(Clause(number=number, title=clause_title, text=content))
    else:
        section = DocumentSection(title=title, content=content, section_type=section_type.value)
        result[key].append(section)
