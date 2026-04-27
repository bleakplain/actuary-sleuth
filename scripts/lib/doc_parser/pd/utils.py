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
    或名词释义格式：术语 定义
    如：周岁 以法定身份证明文件中记载的出生日期为基础计算...
    或复合术语：先天性畸形、变形或染色体异常 指被保险人出生时就具有的...

    分离策略：
    1. 优先按空格分离（标题和正文之间通常有空格）
    2. 按换行符分离（标题单独一行）
    3. 无法分离时返回空正文（后续从下文提取）
    """
    if not content:
        return '', ''

    content = content.strip()

    # 先处理换行符（标题单独一行）
    if '\n' in content:
        lines = content.split('\n')
        first_line = lines[0].strip()
        # 第一行是标题（长度 <= 25 且不含句号）
        if len(first_line) <= 25 and first_line and '。' not in first_line:
            remaining = '\n'.join(lines[1:]).strip()
            return first_line, remaining
        # 第一行过长，可能是标题+正文合并
        content = first_line

    # 按空格分离（标题和正文之间有空格）
    first_space_idx = content.find(' ')
    if first_space_idx > 0:
        potential_title = content[:first_space_idx]
        potential_content = content[first_space_idx + 1:].strip()

        # 标题特征：长度 2-25
        if 2 <= len(potential_title) <= 25:
            # 检查标题不含句号（句号表示正文开始）
            # 注意：顿号、逗号在名词释义标题中是合法的
            if '。' not in potential_title:
                # 检查有正文内容（不为空）
                if potential_content:
                    return potential_title, potential_content

    # 书名号分离（标准/法规名称引用格式）
    # 格式：《标准名称》是由xxx发布...或《标准名称》指xxx
    if content.startswith('《') and '》' in content:
        end_idx = content.find('》') + 1
        remaining = content[end_idx:].strip()
        if remaining:
            return content[:end_idx], remaining

    # 无法分离，视为纯标题（正文从后续行提取）
    return content, ''



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
