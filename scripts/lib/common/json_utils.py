"""LLM 返回文本中 JSON 提取的共用工具。

LLM 经常会把 JSON 包在 markdown 代码块或附带解释性文本中，
这里统一处理提取逻辑，避免每个调用点各自实现。
"""
from __future__ import annotations

import re
from typing import Optional

__all__ = ["extract_json_array", "extract_json_object"]

_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*\n", re.MULTILINE)


def _strip_markdown_fence(text: str) -> str:
    """去掉 ```json / ``` 代码块围栏，保留内部内容。"""
    text = _MD_FENCE_RE.sub("", text)
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3].rstrip()
    return text


def _extract_between(text: str, open_ch: str, close_ch: str) -> Optional[str]:
    """按括号深度配对，返回首个完整的 open...close 子串。"""
    start = text.find(open_ch)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_array(text: str) -> Optional[str]:
    """从 LLM 返回文本中提取首个 JSON 数组字面量。

    支持 markdown ```json 代码块包裹；返回原始子串（未解析），
    由调用方决定 json.loads 或自定义解析。未找到返回 None。
    """
    if not text:
        return None
    cleaned = _strip_markdown_fence(text)
    return _extract_between(cleaned, "[", "]")


def extract_json_object(text: str) -> Optional[str]:
    """从 LLM 返回文本中提取首个 JSON 对象字面量。

    支持 markdown 代码块包裹；返回原始子串（未解析）。
    未找到返回 None。
    """
    if not text:
        return None
    cleaned = _strip_markdown_fence(text)
    return _extract_between(cleaned, "{", "}")
