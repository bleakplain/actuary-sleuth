#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档解析共享工具"""
from __future__ import annotations

from typing import Tuple, Dict, List, Any

from ..models import SectionType, DocumentSection, Clause


def separate_title_and_text(content: str) -> Tuple[str, str]:
    """分离条款标题和正文。

    优先按换行符分离，否则按中文句号边界分离。
    """
    if not content:
        return '', ''

    content = content.strip()

    if '\n' in content:
        lines = content.split('\n', 1)
        return lines[0].strip(), lines[1].strip() if len(lines) > 1 else ''

    sentences = []
    current = ''
    for char in content:
        current += char
        if char in '。！？':
            sentences.append(current.strip())
            current = ''

    if current:
        sentences.append(current.strip())

    if len(sentences) >= 2 and len(sentences[0]) <= 30:
        return sentences[0], ''.join(sentences[1:])

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
