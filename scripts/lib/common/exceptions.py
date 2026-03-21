#!/usr/bin/env python3
"""
公共异常模块

提供统一的异常访问点。
"""

# 基础异常
class ActuarySleuthException(Exception):
    pass


class DatabaseError(ActuarySleuthException):
    pass


class RecordNotFoundError(ActuarySleuthException):
    pass


class AuditStepException(ActuarySleuthException):
    pass


# 从主异常模块重新导出
from lib.exceptions import (
    ValidationException,
    MissingParameterException,
    InvalidParameterException,
    ProcessingException,
    DocumentPreprocessException,
    NegativeListCheckException,
    PricingAnalysisException,
    ReportGenerationException,
    DatabaseException,
    DataNotFoundException,
    ExternalServiceException,
    FeishuAPIException,
    OllamaException,
    ConfigurationException,
    ExportException,
)


__all__ = [
    'ActuarySleuthException',
    'DatabaseError',
    'RecordNotFoundError',
    'AuditStepException',
    'ValidationException',
    'MissingParameterException',
    'InvalidParameterException',
    'ProcessingException',
    'DocumentPreprocessException',
    'NegativeListCheckException',
    'PricingAnalysisException',
    'ReportGenerationException',
    'DatabaseException',
    'DataNotFoundException',
    'ExternalServiceException',
    'FeishuAPIException',
    'OllamaException',
    'ConfigurationException',
    'ExportException',
]
