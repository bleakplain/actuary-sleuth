#!/usr/bin/env python3
"""
公共异常模块

提供统一的异常访问点，重新导出 lib.exceptions 中的常用异常。
"""

# 从主异常模块重新导出
from lib.exceptions import (
    ActuarySleuthException,
    DatabaseError,
    AuditStepException,
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


# 本模块独有的异常
class RecordNotFoundError(ActuarySleuthException):
    """记录未找到异常"""
    pass


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
