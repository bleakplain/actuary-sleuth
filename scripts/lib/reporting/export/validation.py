#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输入验证工具（增强版）

提供参数验证功能，包括路径遍历防护和消息清理
"""
import os
import re
from pathlib import Path
from typing import Optional
from lib.common.exceptions import InvalidParameterException, ValidationException


MAX_MESSAGE_LENGTH = 500
ALLOWED_PATH_CHARS = re.compile(r'^[a-zA-Z0-9_\-./\s\:]+$')
DANGEROUS_PATH_PATTERNS = [
    r'\.\./',
    r'~/',
    r'/etc/',
    r'/dev/',
]


def validate_file_path(file_path: str, allowed_dir: Optional[str] = None) -> str:
    """
    验证文件路径（增强版，支持路径遍历防护）

    Args:
        file_path: 待验证的文件路径
        allowed_dir: 允许的目录（可选）

    Returns:
        str: 规范化后的绝对路径

    Raises:
        ValidationException: 如果路径无效
    """
    if not file_path:
        raise ValidationException("文件路径不能为空")

    for pattern in DANGEROUS_PATH_PATTERNS:
        if re.search(pattern, file_path):
            raise ValidationException(f"文件路径包含危险模式: {pattern}")

    try:
        abs_path = str(Path(file_path).resolve())
    except (OSError, ValueError) as e:
        raise ValidationException(f"无效的文件路径: {e}")

    if not ALLOWED_PATH_CHARS.match(abs_path):
        raise ValidationException(f"文件路径包含非法字符")

    if not os.path.exists(abs_path):
        raise ValidationException(f"文件不存在: {file_path}")

    if not abs_path.endswith('.docx'):
        raise ValidationException(f"文件格式错误，期望 .docx 文件: {file_path}")

    try:
        file_size = os.path.getsize(abs_path)
        if file_size == 0:
            raise ValidationException("文件为空")
        if file_size > 50 * 1024 * 1024:
            raise ValidationException(f"文件过大: {file_size / 1024 / 1024:.1f}MB")
    except OSError as e:
        raise ValidationException(f"无法访问文件: {e}")

    if allowed_dir:
        allowed_abs = str(Path(allowed_dir).resolve())
        if not abs_path.startswith(allowed_abs):
            raise ValidationException(f"文件路径不在允许目录内: {allowed_dir}")

    return abs_path


def sanitize_message(message: str) -> str:
    """
    清理消息内容，移除危险字符

    Args:
        message: 原始消息

    Returns:
        str: 清理后的消息

    Raises:
        ValidationException: 如果消息无效
    """
    if not message:
        return ""

    message = message.strip()

    cleaned = ''.join(
        char for char in message
        if char == '\n' or char == '\t' or (ord(char) >= 32 and ord(char) != 127)
    )

    if len(cleaned) > MAX_MESSAGE_LENGTH:
        cleaned = cleaned[:MAX_MESSAGE_LENGTH - 3] + "..."

    return cleaned


def validate_group_id(group_id: str) -> str:
    """
    验证飞书群组 ID

    Args:
        group_id: 群组 ID

    Returns:
        str: 验证后的群组 ID

    Raises:
        ValidationException: 如果群组 ID 无效
    """
    if not group_id:
        raise ValidationException("群组 ID 不能为空")

    group_id = group_id.strip()

    if not re.match(r'^oc_[a-zA-Z0-9_-]{10,30}$', group_id):
        raise ValidationException(f"无效的群组 ID 格式: {group_id}。期望格式: oc_xxxxxxxxxxxxx")

    return group_id


def validate_title(title: str) -> str:
    """
    验证报告标题

    Args:
        title: 报告标题

    Returns:
        str: 验证后的标题

    Raises:
        ValidationException: 如果标题无效
    """
    if not title:
        raise ValidationException("标题不能为空")

    title = title.strip()

    if len(title) > 100:
        raise ValidationException(f"标题过长: {len(title)} 字符（最大 100）")

    return title


def validate_evaluation_context(context):
    """
    验证评估上下文

    Args:
        context: 评估上下文对象

    Raises:
        ValidationException: 如果上下文无效
    """
    if context is None:
        raise ValidationException("评估上下文不能为空")

    if not hasattr(context, 'violations'):
        raise ValidationException("评估上下文缺少 violations 属性")

    if not hasattr(context, 'product'):
        raise ValidationException("评估上下文缺少 product 属性")
