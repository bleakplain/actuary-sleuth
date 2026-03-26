#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON parsing utilities for LLM responses
"""
import json
import logging
import re
from typing import Dict, Any, Optional


logger = logging.getLogger(__name__)


def parse_llm_json_response(response: str, strict: bool = False, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Parse JSON from LLM response with multiple fallback strategies.

    Handles:
    1. JSON in markdown code blocks (```json ... ```)
    2. Bare JSON objects
    3. JSON embedded in other text
    4. Incomplete JSON (trailing commas, missing quotes)
    5. Multiple JSON objects (returns first)

    Args:
        response: Raw LLM response string
        strict: If True, raise exception on parse failure; if False, return default
        default: Default value to return if parsing fails (default: {})

    Returns:
        Parsed JSON as dict, or default if parsing fails and strict=False

    Raises:
        ValueError: If strict=True and parsing fails
    """
    if default is None:
        default = {}

    if not response:
        logger.warning("Empty response received")
        if strict:
            raise ValueError("Empty response")
        return default

    # 清理响应
    cleaned = response.strip()

    # Strategy 1: Markdown code blocks
    for pattern in [r'```json\s*(.*?)\s*```', r'```\s*(.*?)\s*```']:
        json_match = re.search(pattern, cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse JSON from code block: {e}")

    # Strategy 2: Bare JSON
    if cleaned.startswith('{') and cleaned.endswith('}'):
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 尝试修复常见问题
            fixed = _fix_common_json_issues(cleaned)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse fixed JSON: {e}")

    # Strategy 3: 提取嵌套 JSON
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(cleaned[first_brace:last_brace + 1])
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse embedded JSON: {e}")

    # 所有策略失败
    if strict:
        raise ValueError(f"Could not extract JSON from response: {response[:200]}")

    logger.warning(f"Could not extract JSON from response, returning default")
    return default


def _fix_common_json_issues(json_str: str) -> str:
    """修复常见的 JSON 格式问题"""
    # 移除尾随逗号
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    # 修复未引用的键名
    json_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)', r'\1"\2"\3', json_str)
    return json_str
