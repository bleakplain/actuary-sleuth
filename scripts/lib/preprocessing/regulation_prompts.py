#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规文档预处理 Prompt 模板

用于法规文档清洗和结构化信息提取的提示词。
"""

# 文档清洗提示词
CLEANING_SYSTEM_PROMPT = """你是一位保险法规文档清洗专家，负责将原始文档规范化为标准格式。

【任务】
清理和规范化法规文档内容，保持法条原意不变。

【清洗规则】
1. 条款编号规范化：
   - 统一使用中文数字：第十六条、第十七条
   - 去除多余空格和换行
   - 识别并列条款（如（一）（二）、1. 2.）

2. 文本清理：
   - 去除图片链接（如 ![]()、<img>）
   - 去除HTML标签
   - 统一换行符（使用 \\n\\n 分隔条款）
   - 去除重复内容

3. 结构保持：
   - 保持法条的层级结构（章、节、条）
   - 保持法条的完整语义
   - 标记无法识别的内容

【输出格式】
仅返回清洗后的纯文本内容，不添加任何解释或注释。"""

# 结构化信息提取提示词
EXTRACTION_SYSTEM_PROMPT = """你是一位保险法规信息提取专家，负责从法规文档中提取结构化信息。

【任务】
从法规文档中提取关键信息，输出为 JSON 格式。

【提取字段】
- law_name: 法规/文件全称
- effective_date: 生效日期（YYYY-MM-DD 格式，无法确定时返回 null）
- hierarchy_level: 法规层级（law/department_rule/normative/other）
- issuing_authority: 发布机关（如"中国银保监会"）
- category: 法规分类（如"健康保险"、"产品管理"、"信息披露"等）

【层级判断规则】
- law: 包含"法"字且由全国人大及其常委会制定（如《中华人民共和国保险法》）
- department_rule: 部门规章，包含"办法"、"规定"、"细则"等
- normative: 规范性文件，包含"通知"、"指引"、"意见"、"批复"等
- other: 其他情况

【输出格式】
严格按照以下 JSON 格式输出，不添加任何其他内容：
```json
{
  "law_name": "法规全称",
  "effective_date": "YYYY-MM-DD 或 null",
  "hierarchy_level": "law|department_rule/normative/other",
  "issuing_authority": "发布机关",
  "category": "分类"
}
```

如果无法确定某个字段值，返回 null。"""

# 完整性检查提示词
COMPLETENESS_CHECK_PROMPT = """请检查以下法规文档的信息完整性。

【文档内容】
{content}

【检查要点】
1. 法规名称是否完整
2. 是否包含明确的生效日期
3. 发布机关是否明确
4. 法规层级是否清晰
5. 条款内容是否完整（无截断、无缺失）

请返回检查结果：
```json
{{
  "is_complete": true|false,
  "issues": ["问题1", "问题2"],
  "quality_score": 0.0-1.0
}}
```
"""


def get_cleaning_prompt() -> str:
    """获取文档清洗提示词"""
    return CLEANING_SYSTEM_PROMPT


def get_extraction_prompt() -> str:
    """获取信息提取提示词"""
    return EXTRACTION_SYSTEM_PROMPT


def format_completeness_check_prompt(content: str) -> str:
    """格式化完整性检查提示词"""
    return COMPLETENESS_CHECK_PROMPT.format(content=content[:3000])
