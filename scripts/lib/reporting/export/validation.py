#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输入验证工具

提供参数验证功能
"""
from typing import Any, Optional
from lib.exceptions import InvalidParameterException, ValidationException


def validate_evaluation_context(context: Any) -> None:
    """
    验证 EvaluationContext 对象

    Args:
        context: 待验证的对象

    Raises:
        ValidationException: 如果验证失败
    """
    from lib.reporting.model import EvaluationContext

    if not isinstance(context, EvaluationContext):
        raise InvalidParameterException(
            'context',
            'EvaluationContext',
            type(context).__name__
        )

    # 验证必填字段
    if not context.product:
        raise ValidationException("EvaluationContext.product 不能为空")

    if not context.product.name:
        raise ValidationException("产品名称不能为空")


def validate_title(title: Optional[str]) -> str:
    """
    验证并规范化文档标题

    Args:
        title: 待验证的标题

    Returns:
        str: 规范化后的标题

    Raises:
        ValidationException: 如果标题无效
    """
    if not title:
        raise ValidationException("文档标题不能为空")

    # 去除首尾空格
    title = title.strip()

    if len(title) > 200:
        raise ValidationException(f"文档标题过长（最多200字符）：{len(title)}")

    # 检查非法字符
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in invalid_chars:
        if char in title:
            raise ValidationException(f"文档标题包含非法字符：{char}")

    return title


def validate_file_path(file_path: str) -> None:
    """
    验证文件路径

    Args:
        file_path: 待验证的文件路径

    Raises:
        ValidationException: 如果路径无效
    """
    import os

    if not file_path:
        raise ValidationException("文件路径不能为空")

    if not os.path.exists(file_path):
        raise ValidationException(f"文件不存在：{file_path}")

    if not file_path.endswith('.docx'):
        raise ValidationException(f"文件格式错误，期望 .docx 文件：{file_path}")
