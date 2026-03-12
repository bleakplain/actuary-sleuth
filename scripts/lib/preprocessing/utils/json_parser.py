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


def parse_llm_json_response(response: str, strict: bool = False, default: Dict = None) -> Dict[str, Any]:
    """
    Parse JSON from LLM response with multiple fallback strategies.

    Handles:
    1. JSON in markdown code blocks (```json ... ```)
    2. Bare JSON objects
    3. JSON embedded in other text

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
        return default if not strict else ValueError("Empty response")

    # Strategy 1: Try extracting JSON from markdown code blocks
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse JSON from code block: {e}")
            if strict:
                raise ValueError(f"Invalid JSON in code block: {e}")

    # Strategy 2: Try stripped response as bare JSON
    cleaned = response.strip()
    if cleaned.startswith('{') and cleaned.endswith('}'):
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse bare JSON: {e}")
            if strict:
                raise ValueError(f"Invalid bare JSON: {e}")

    # Strategy 3: Try extracting JSON object from within text
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(cleaned[first_brace:last_brace + 1])
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse embedded JSON: {e}")

    # All strategies failed
    if strict:
        raise ValueError(f"Could not extract JSON from response: {response[:200]}")

    logger.warning(f"Could not extract JSON from response, returning default: {response[:200]}")
    return default
