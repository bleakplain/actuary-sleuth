#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预处理模块异常层次

定义清晰的异常层次结构，便于错误处理和调试。
"""


class PreprocessingException(Exception):
    """预处理模块基础异常"""
    pass


class DocumentFetchError(PreprocessingException):
    """文档获取失败"""
    pass


class DocumentValidationError(PreprocessingException):
    """文档验证失败"""
    pass


class ExtractionError(PreprocessingException):
    """提取失败基础异常"""
    pass


class FastExtractionFailed(ExtractionError):
    """快速通道提取失败"""

    def __init__(self, message: str, partial_result=None):
        super().__init__(message)
        self.partial_result = partial_result


class DynamicExtractionFailed(ExtractionError):
    """动态通道提取失败"""
    pass


class ChunkExtractionFailed(ExtractionError):
    """分块提取失败"""
    pass


class ParseError(PreprocessingException):
    """解析失败"""
    pass


class JSONParseError(ParseError):
    """JSON 解析失败"""
    pass


class ValidationError(PreprocessingException):
    """验证失败"""
    pass


class BusinessRuleViolation(ValidationError):
    """业务规则违反"""
    pass
