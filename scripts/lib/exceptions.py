#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一异常定义模块

定义 Actuary Sleuth 系统中使用的所有异常类型，
提供清晰的错误分类和处理机制
"""
from typing import Optional, Any


class ActuarySleuthException(Exception):
    """
    Actuary Sleuth 基础异常类

    所有自定义异常的基类，提供统一的错误信息格式
    """

    def __init__(self, message: str, details: Optional[dict] = None):
        """
        初始化异常

        Args:
            message: 错误信息
            details: 错误详细信息（可选）
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} - {self.details}"
        return self.message

    def to_dict(self) -> dict:
        """将异常转换为字典格式"""
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'details': self.details
        }


# ========== 输入验证异常 ==========

class ValidationException(ActuarySleuthException):
    """输入验证失败异常"""
    pass


class MissingParameterException(ValidationException):
    """缺少必需参数异常"""

    def __init__(self, parameter_name: str):
        super().__init__(
            message=f"缺少必需参数: '{parameter_name}'",
            details={'parameter': parameter_name}
        )
        self.parameter_name = parameter_name


class InvalidParameterException(ValidationException):
    """无效参数异常"""

    def __init__(self, parameter_name: str, expected_type: str, actual_value: Any = None):
        details = {
            'parameter': parameter_name,
            'expected_type': expected_type
        }
        if actual_value is not None:
            details['actual_value'] = str(actual_value)[:100]  # 限制长度

        super().__init__(
            message=f"参数 '{parameter_name}' 类型错误，期望: {expected_type}",
            details=details
        )
        self.parameter_name = parameter_name
        self.expected_type = expected_type


# ========== 业务逻辑异常 ==========

class ProcessingException(ActuarySleuthException):
    """处理过程异常基类"""

    def __init__(self, message: str, step: str = "", details: Optional[dict] = None):
        full_details = details or {}
        if step:
            full_details['step'] = step

        super().__init__(message, full_details)
        self.step = step


class DocumentPreprocessException(ProcessingException):
    """文档预处理失败"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, step="preprocessing", details=details)


class NegativeListCheckException(ProcessingException):
    """负面清单检查失败"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, step="negative_list_check", details=details)


class PricingAnalysisException(ProcessingException):
    """定价分析失败"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, step="pricing_analysis", details=details)


class ReportGenerationException(ProcessingException):
    """报告生成失败"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, step="report_generation", details=details)


class AuditStepException(ProcessingException):
    """审核步骤失败"""

    def __init__(self, message: str, step: str = "", details: Optional[dict] = None):
        super().__init__(message, step=step, details=details)


# ========== 数据访问异常 ==========

class DatabaseException(ActuarySleuthException):
    """数据库操作异常"""

    def __init__(self, message: str, operation: str = "", details: Optional[dict] = None):
        full_details = details or {}
        if operation:
            full_details['operation'] = operation

        super().__init__(message, full_details)
        self.operation = operation


class DataNotFoundException(DatabaseException):
    """数据未找到异常"""

    def __init__(self, resource_type: str, resource_id: str = ""):
        message = f"{resource_type} 未找到"
        if resource_id:
            message += f" (ID: {resource_id})"

        super().__init__(
            message=message,
            operation="query",
            details={'resource_type': resource_type, 'resource_id': resource_id}
        )


# ========== 外部服务异常 ==========

class ExternalServiceException(ActuarySleuthException):
    """外部服务调用异常"""

    def __init__(self, service_name: str, message: str, details: Optional[dict] = None):
        full_message = f"{service_name} 调用失败: {message}"
        full_details = details or {}
        full_details['service'] = service_name

        super().__init__(full_message, full_details)
        self.service_name = service_name


class FeishuAPIException(ExternalServiceException):
    """飞书API调用异常"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("飞书", message, details)


class OllamaException(ExternalServiceException):
    """Ollama服务异常"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("Ollama", message, details)


# ========== 配置异常 ==========

class ConfigurationException(ActuarySleuthException):
    """配置错误异常"""

    def __init__(self, config_key: str, message: str = ""):
        if not message:
            message = f"配置错误: {config_key}"

        super().__init__(
            message=message,
            details={'config_key': config_key}
        )
        self.config_key = config_key


class MissingConfigurationException(ConfigurationException):
    """缺少必需配置"""

    def __init__(self, config_key: str):
        super().__init__(
            config_key=config_key,
            message=f"缺少必需配置: {config_key}"
        )


# ========== 导出异常 ==========

class ExportException(ActuarySleuthException):
    """文档导出异常"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, details)