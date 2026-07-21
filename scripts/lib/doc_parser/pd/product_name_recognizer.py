#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保险产品名称识别与命名合规校验。

产品名识别依据：《人身保险公司保险条款和保险费率管理办法》规定的命名结构
"保险公司名称 + 吉庆/说明性文字（≤10字）+ 险种类别 + （设计类型）"。
在正式条款开始之前的封面/目录段落里，产品名通常以"条款"结尾、含"保险"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# 条款起始标记：第一条条款之前的段落是"产品名候选区"
_CLAUSE_START_PATTERNS = [
    re.compile(r'【\s*(?:附加险\s*)?条款\s+\d'),
    re.compile(r'^\s*第[一二三四五]条'),
]

# 产品名识别规则（按优先级降序）
# 1. 书名号包裹且以"条款"结尾：《XXX》...条款 / 《XXX》保险条款
_BRACKET_NAME_PATTERN = re.compile(r'《([^《》]+)》[^《》]*条款')
# 2. 不含书名号但以"条款"结尾且含"保险"/"寿险"/"险种"
_BARE_NAME_PATTERN = re.compile(r'([\u4e00-\u9fa5A-Za-z0-9（）()、]{4,40}(?:保险|寿险|年金险|两全险|健康险|意外险|医疗险|重疾险|护理险|疾病险)[^\n。；;]{0,20}条款)')

# 险种关键字（用于识别失败时的兜底分类提示）
_INSURANCE_KEYWORDS = ["医疗", "疾病", "重疾", "护理", "意外", "寿险", "年金", "两全", "健康"]

# 常见保险公司简称（用于命名合规校验）
_COMPANY_NAMES = [
    "人保健康", "人保", "人保寿险", "平安", "太保", "太平洋", "新华", "泰康",
    "友邦", "中国人寿", "太平", "阳光", "华夏", "百年", "信泰", "工银安盛",
    "建信", "招商仁和", "中意", "中英", "中美联泰", "大都会", "弘康", "国华",
    "恒安标准", "英大泰和", "国寿", "国宝", "京东安联", "水滴", "小雨伞",
]

# 设计类型（出现在产品名末尾括号内）
_DESIGN_TYPES = ["普通型", "分红型", "万能型", "投资连结型", "变额型"]


@dataclass(frozen=True)
class ProductNameRecognition:
    """产品名识别结果"""
    product_name: Optional[str]            # 识别出的产品名（不含书名号）
    is_rider: bool                         # 是否附加险
    group_or_individual: Optional[str] = None  # 团体/个人 标签（团体险命名合规校验也会用到）
    duration_type: Optional[str] = None    # 终身/定期 标签
    design_type: Optional[str] = None      # 设计类型（普通型/分红型/万能型等）
    warnings: List[str] = field(default_factory=list)  # 命名合规警告


def _is_clause_start(text: str) -> bool:
    """判断段落是否是条款起始（即产品名候选区的结束边界）"""
    if not text:
        return False
    return any(p.search(text) for p in _CLAUSE_START_PATTERNS)


def _collect_pre_clause_paragraphs(paragraphs: List[str]) -> List[str]:
    """收集条款起始前的所有段落文本，作为产品名候选区"""
    result: List[str] = []
    for text in paragraphs:
        if _is_clause_start(text):
            break
        if text and text.strip():
            result.append(text.strip())
    return result


def _clean_product_name(raw: str) -> str:
    """去除产品名两端可能残留的修饰符号/空白，保留中英文与括号"""
    name = raw.strip()
    # 去掉末尾可能残留的"条款"以外的修饰（如"（修订版）"等），保留核心结构
    return name


def _try_bracket_match(paragraphs: List[str]) -> Optional[str]:
    """规则 1：从含《》的段落里提取产品名"""
    for text in paragraphs:
        m = _BRACKET_NAME_PATTERN.search(text)
        if m:
            # 取《》内完整内容 + 后续到"条款"的部分
            full_match = m.group(0)
            # 去掉书名号包裹后保留核心
            inner = full_match.removeprefix('《').split('》')[0]
            suffix = full_match.split('》', 1)[1] if '》' in full_match else ''
            return _clean_product_name(f"{inner}{suffix}")
    return None


def _try_bare_match(paragraphs: List[str]) -> Optional[str]:
    """规则 2：不含《》但含"保险"且以"条款"结尾"""
    for text in paragraphs:
        m = _BARE_NAME_PATTERN.search(text)
        if m:
            return _clean_product_name(m.group(1))
    return None


def _try_fallback_match(paragraphs: List[str]) -> Optional[str]:
    """规则 3：兜底——最长的含"保险"的短段落"""
    candidates = [
        t for t in paragraphs
        if '保险' in t and len(t) <= 60
    ]
    if not candidates:
        return None
    return max(candidates, key=len)


def _detect_is_rider(product_name: str) -> bool:
    """判断是否附加险：产品名中"附加"出现在"保险"之前"""
    add_idx = product_name.find('附加')
    ins_idx = product_name.find('保险')
    return add_idx >= 0 and (ins_idx < 0 or add_idx < ins_idx)


def _extract_group_or_individual(product_name: str) -> Optional[str]:
    """提取投保对象标签：团体/个人"""
    has_group = any(kw in product_name for kw in ("团体", "团险"))
    has_individual = '个人' in product_name
    if has_group:
        return '团体'
    if has_individual:
        return '个人'
    return None


def _extract_duration_type(product_name: str) -> Optional[str]:
    """提取保险期限标签：终身/定期"""
    if '终身' in product_name:
        return '终身'
    if '定期' in product_name:
        return '定期'
    return None


# 险种类别后缀（用于从产品名末尾剥离，识别"吉庆文字"部分）
# 顺序重要：长的优先，避免"重大疾病"被"疾病"提前截断
_INSURANCE_CATEGORY_SUFFIXES = [
    "重大疾病", "重疾", "医疗", "疾病", "护理", "失能收入损失",
    "意外伤害", "意外", "终身寿险", "定期寿险", "两全保险",
    "年金保险", "养老保险", "人寿保险", "寿险", "两全", "年金",
    "养老", "健康保险", "健康",
]

# 设计类型 / 修饰词 / 版本号（出现在产品名末尾，需要剥离以定位吉庆文字）
_NAME_SUFFIX_NOISE = [
    "普通型", "分红型", "万能型", "投资连结型", "变额型",
    "互联网", "个人",
]

# 标签维度的修饰词（不是吉庆文字）
# 团体/个人 = 投保对象标签；终身/定期 = 保险期限标签
_GROUP_INDIVIDUAL_KEYWORDS = ["团体", "个人"]
_TERM_DURATION_KEYWORDS = ["终身", "定期"]

# 末尾括号内容（版本号、款型、设计类型）：（2025版）、（A款）、(2.0版)、（分红型） 等
# 需同时匹配设计类型与版本号，避免设计类型被误算入吉庆文字
_TRAILING_PAREN_PATTERN = re.compile(
    r'[（(][^（）()]*(?:[版款]|普通型|分红型|万能型|投资连结型|变额型|个人|团体)[^（）()]*[）)]$'
)


def _extract_felicity_text(product_name: str) -> Optional[str]:
    """从产品名中切出"吉庆/说明性文字"部分。

    法规命名结构：保险公司名称 + 吉庆/说明性文字 + 险种类别 + （设计类型）
    剥离头部公司名、尾部险种类别与噪声后，剩下的中间段即为吉庆文字。
    """
    if not product_name:
        return None
    s = product_name
    # 去掉末尾的"条款"
    if s.endswith('条款'):
        s = s[:-len('条款')]
    # 去掉末尾括号（版本号/款型/设计类型）
    s = _TRAILING_PAREN_PATTERN.sub('', s).strip()
    # 从尾部剥离险种类别（长的优先）；先剥离"保险"再剥离类别后缀
    # 例：XXX医疗保险 → 剥"保险"→ "XXX医疗" → 不再匹配类别 → 需先剥类别
    # 例：XXX终身寿险 → 直接匹配"终身寿险"或"寿险"后缀
    for _ in range(2):
        s_before_strip = s
        for suffix in _INSURANCE_CATEGORY_SUFFIXES + ["保险"]:
            if s.endswith(suffix):
                s = s[:-len(suffix)].strip()
                break
        if s == s_before_strip:
            break
    # 去掉头部保险公司名称（最长匹配优先：先匹配精确公司简称，再兜底"XX保险公司"）
    matched_company = False
    for company in sorted(_COMPANY_NAMES, key=len, reverse=True):
        if s.startswith(company):
            s = s[len(company):]
            matched_company = True
            break
    if not matched_company:
        # 兜底：公司全称（"XX保险股份有限公司"/"XX人寿保险股份有限公司"等）
        m = re.match(r'^[\u4e00-\u9fa5A-Za-z]+(?:保险|人寿保险|养老保险|健康保险|农业保险)[\u4e00-\u9fa5]*?(?:股份有限公司|有限责任公司|保险公司)', s)
        if m:
            s = s[m.end():]
    # 去掉头部的"附加"等修饰
    for prefix in ("附加",):
        if s.startswith(prefix):
            s = s[len(prefix):]
    # 去掉头部和尾部的修饰词（设计类型、互联网、个人）
    s = s.strip()
    for noise in _NAME_SUFFIX_NOISE:
        if s.startswith(noise):
            s = s[len(noise):]
        if s.endswith(noise):
            s = s[:-len(noise)]
    # 剥离标签维度修饰词（团体/个人、终身/定期），这些是结构化标签，不算吉庆文字
    # 头尾各剥一遍，最多重复 3 次以处理多词叠加（如"企业员工团体终身"）
    for _ in range(3):
        s_before = s
        for kw in _GROUP_INDIVIDUAL_KEYWORDS + _TERM_DURATION_KEYWORDS:
            if s.startswith(kw):
                s = s[len(kw):]
            elif s.endswith(kw):
                s = s[:-len(kw)]
            elif kw in s and len(s) > 0:
                # 中间也可能存在（如"企业员工团体终身"中"团体"在中间），整词剔除
                s = s.replace(kw, '', 1)
        s = s.strip()
        if s == s_before:
            break
    s = s.strip()
    return s if s else None


def _check_naming_compliance(
    product_name: str,
    is_rider: bool,
    group_or_individual: Optional[str] = None,
    design_type: Optional[str] = None,
) -> List[str]:
    """根据《人身保险公司保险条款和保险费率管理办法》校验命名结构

    法规要求：保险公司名称 + 吉庆/说明性文字（≤10字）+ 险种类别 + （设计类型）
    附加险必须含"附加"；团体险必须含"团体"。
    """
    warnings: List[str] = []
    if not product_name:
        return warnings

    # 必须包含可识别的保险公司名称
    has_company = any(c in product_name for c in _COMPANY_NAMES)
    if not has_company:
        warnings.append("产品名称未识别到保险公司名称，请确认是否符合命名规范")

    # 必须以"保险条款"或"保险"结尾（覆盖"XXX医疗保险条款"、"XXX保险（A款）条款"等变体）
    name = product_name.rstrip()
    ends_with_insurance = (
        name.endswith('保险条款')
        or name.endswith('保险')
        or '保险' in name  # 含"保险"即可，避免"（A款）条款"这种合法变体被误报
    )
    if not ends_with_insurance:
        warnings.append('产品名称应包含「保险」字样')

    # 附加险校验
    if is_rider and '附加' not in product_name:
        warnings.append('附加险产品名称应当包含「附加」字样')
    if not is_rider and '附加' in product_name:
        warnings.append('主险产品名称不应包含「附加」字样')

    # 团体险校验：基于识别出的投保对象标签
    # 法规要求团体保险必须在名称中标明"团体"字样
    # 注：此处只能正向识别（产品名含"团体"），无法判断应保但未标的违规

    # 是否包含明确险种类别
    has_category = any(kw in product_name for kw in _INSURANCE_KEYWORDS)
    if not has_category:
        warnings.append("产品名称未包含明确险种类别（如医疗、疾病、护理、意外、寿险、年金等）")

    # 吉庆/说明性文字长度 ≤10 字（《人身保险公司保险条款和保险费率管理办法》）
    felicity = _extract_felicity_text(product_name)
    if felicity is not None:
        felicity_len = len(felicity)
        if felicity_len > 10:
            warnings.append(
                f"产品名称中吉庆/说明性文字「{felicity}」共{felicity_len}字，"
                f"超过法规上限10字"
            )

    return warnings


def recognize_product_name(paragraphs: List[str]) -> ProductNameRecognition:
    """从段落列表中识别产品名称并校验命名合规性

    Args:
        paragraphs: 文档段落文本列表（按出现顺序）

    Returns:
        ProductNameRecognition: 包含产品名、是否附加险、命名合规警告
    """
    pre_clauses = _collect_pre_clause_paragraphs(paragraphs)
    if not pre_clauses:
        return ProductNameRecognition(
            product_name=None,
            is_rider=False,
            warnings=["未能在条款开始之前识别到产品名称，请手动填写"],
        )

    # 按优先级尝试三条规则
    product_name = (
        _try_bracket_match(pre_clauses)
        or _try_bare_match(pre_clauses)
        or _try_fallback_match(pre_clauses)
    )

    if not product_name:
        return ProductNameRecognition(
            product_name=None,
            is_rider=False,
            warnings=["未能在条款开始之前识别到产品名称，请手动填写"],
        )

    is_rider = _detect_is_rider(product_name)
    group_or_individual = _extract_group_or_individual(product_name)
    duration_type = _extract_duration_type(product_name)
    design_type = next((d for d in _DESIGN_TYPES if d in product_name), None)
    warnings = _check_naming_compliance(
        product_name, is_rider, group_or_individual, design_type,
    )

    return ProductNameRecognition(
        product_name=product_name,
        is_rider=is_rider,
        group_or_individual=group_or_individual,
        duration_type=duration_type,
        design_type=design_type,
        warnings=warnings,
    )
