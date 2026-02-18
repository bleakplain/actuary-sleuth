#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志处理模块

提供统一的日志记录功能，支持不同级别和格式化输出
"""
import sys
import logging
from datetime import datetime
from typing import Optional, Any
from pathlib import Path

from .exceptions import ActuarySleuthError


class AuditLogger:
    """
    审核系统日志记录器

    提供统一的日志接口，支持结构化日志记录
    """

    def __init__(self, name: str, level: int = logging.INFO):
        """
        初始化日志记录器

        Args:
            name: 日志记录器名称
            level: 日志级别
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # 避免重复添加handler
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(level)

            # 格式化器
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(formatter)

            self.logger.addHandler(console_handler)

    def debug(self, message: str, **kwargs):
        """记录调试信息"""
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        """记录一般信息"""
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        """记录警告信息"""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """记录错误信息"""
        if exception:
            kwargs['exception_type'] = type(exception).__name__
            kwargs['exception_message'] = str(exception)

            if isinstance(exception, ActuarySleuthError):
                kwargs.update(exception.details)

        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """记录严重错误"""
        if exception:
            kwargs['exception_type'] = type(exception).__name__
            kwargs['exception_message'] = str(exception)

            if isinstance(exception, ActuarySleuthError):
                kwargs.update(exception.details)

        self._log(logging.CRITICAL, message, **kwargs)

    def _log(self, level: int, message: str, **kwargs):
        """
        内部日志记录方法

        Args:
            level: 日志级别
            message: 日志消息
            **kwargs: 额外的结构化数据
        """
        if kwargs:
            # 将结构化数据附加到消息
            details = " | " + " | ".join(f"{k}={v}" for k, v in kwargs.items())
            message = message + details

        self.logger.log(level, message)


class AuditStepLogger:
    """
    审核步骤日志记录器

    专门用于记录审核流程中的各个步骤
    """

    def __init__(self, audit_id: str, logger: Optional[AuditLogger] = None):
        """
        初始化步骤日志记录器

        Args:
            audit_id: 审核ID
            logger: 日志记录器（可选）
        """
        self.audit_id = audit_id
        self.logger = logger or AuditLogger(f"audit.{audit_id}")
        self.step_number = 0

    def step(self, step_name: str, status: str = "start", **kwargs):
        """
        记录审核步骤

        Args:
            step_name: 步骤名称
            status: 状态 (start/progress/complete/error)
            **kwargs: 额外信息
        """
        self.step_number += 1

        status_symbol = {
            'start': '▶',
            'progress': '⟳',
            'complete': '✅',
            'error': '❌'
        }.get(status, '•')

        message = f"[{self.audit_id}] Step {self.step_number}: {step_name}"
        if status != 'start':
            message = f"{message} ({status})"

        # 输出到 stderr 确保与 JSON 输出分离
        print(f"{status_symbol} {message}", file=sys.stderr, flush=True)

        if kwargs:
            self.logger.info(f"Step {self.step_number}: {step_name}", **kwargs)

    def error(self, step_name: str, error: Exception, **kwargs):
        """
        记录步骤错误

        Args:
            step_name: 步骤名称
            error: 异常对象
            **kwargs: 额外信息
        """
        self.step(step_name, status='error')
        self.logger.error(f"步骤失败: {step_name}", exception=error, **kwargs)


# 便捷函数
def get_logger(name: str) -> AuditLogger:
    """获取日志记录器"""
    return AuditLogger(name)


def get_audit_logger(audit_id: str) -> AuditStepLogger:
    """获取审核步骤日志记录器"""
    return AuditStepLogger(audit_id)