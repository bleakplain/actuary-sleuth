#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一错误处理模块（增强版）

提供装饰器和上下文管理器用于统一处理异常，区分用户错误和系统错误
"""
import functools
import logging
import os
import traceback
from typing import Callable, TypeVar, Optional, Dict, Any, overload

from lib.common.exceptions import (
    ActuarySleuthException,
    AuditStepException,
    ValidationException,
    ProcessingException,
    DocumentFetchError
)


logger = logging.getLogger(__name__)

T = TypeVar('T')


class ErrorCode:
    """错误码定义"""
    INVALID_URL = ("E4001", "无效的 URL 格式")
    DOCUMENT_NOT_FOUND = ("E4002", "文档不存在或无法访问")
    INVALID_FILE_FORMAT = ("E4003", "不支持的文件格式")
    INTERNAL_ERROR = ("E5001", "系统内部错误，请稍后重试")
    SERVICE_UNAVAILABLE = ("E5002", "服务暂时不可用")
    DATABASE_ERROR = ("E5003", "数据存储错误")


USER_ERROR_CLASSES = (
    ValueError,
    KeyError,
    DocumentFetchError,
    ValidationException,
    ProcessingException
)


def is_user_error(exception: Exception) -> bool:
    """判断是否为用户错误"""
    return isinstance(exception, USER_ERROR_CLASSES)


def create_error_response(
    exception: Exception,
    include_details: bool = False
) -> Dict[str, Any]:
    """
    创建错误响应

    Args:
        exception: 异常对象
        include_details: 是否包含详细信息（仅用于调试）

    Returns:
        dict: 错误响应
    """
    if is_user_error(exception):
        error_code = getattr(exception, 'error_code', "E4000")
        error_message = str(exception)

        return {
            "success": False,
            "error_code": error_code,
            "error_message": error_message,
            "error_type": "user_error"
        }
    else:
        logger.exception(f"系统错误: {type(exception).__name__}: {exception}")

        debug_mode = os.getenv('DEBUG', '').lower() == 'true'

        if not debug_mode:
            return {
                "success": False,
                "error_code": ErrorCode.INTERNAL_ERROR[0],
                "error_message": ErrorCode.INTERNAL_ERROR[1],
                "error_type": "system_error"
            }
        else:
            return {
                "success": False,
                "error_code": ErrorCode.INTERNAL_ERROR[0],
                "error_message": str(exception),
                "error_type": type(exception).__name__,
                "traceback": traceback.format_exc()
            }


def handle_audit_errors(step: str = "", reraise: bool = True):
    """
    审核流程错误处理装饰器

    Args:
        step: 步骤名称
        reraise: 是否重新抛出异常

    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
            try:
                return func(*args, **kwargs)
            except (ActuarySleuthException, ValidationException):
                raise
            except ValueError as e:
                logger.error(f"{step or func.__name__} - 参数验证失败: {e}")
                if reraise:
                    raise ValidationException(
                        message=f"参数验证失败: {e}",
                        details={'function': func.__name__, 'step': step}
                    )
                return None
            except KeyError as e:
                logger.error(f"{step or func.__name__} - 缺少必需字段: {e}")
                if reraise:
                    raise ValidationException(
                        message=f"缺少必需字段: {e}",
                        details={'function': func.__name__, 'step': step}
                    )
                return None
            except (ConnectionError, TimeoutError) as e:
                logger.error(f"{step or func.__name__} - 网络错误: {e}")
                if reraise:
                    raise AuditStepException(
                        message=f"网络连接失败: {e}",
                        step=step or func.__name__
                    )
                return None
            except Exception as e:
                logger.exception(f"{step or func.__name__} - 未预期的错误")
                if reraise:
                    raise AuditStepException(
                        message=f"处理失败: {e}",
                        step=step or func.__name__,
                        details={'error_type': type(e).__name__}
                    )
                return None
        return wrapper
    return decorator


@overload
def handle_llm_errors(func: Callable[..., T]) -> Callable[..., Optional[T]]: ...

@overload
def handle_llm_errors(func: None = None) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]: ...

def handle_llm_errors(func: Optional[Callable[..., T]] = None):
    """
    LLM 调用错误处理装饰器

    Args:
        func: 要包装的函数（可选，如果为None则返回装饰器）

    Returns:
        装饰器或包装后的函数
    """
    def decorator(f: Callable[..., T]) -> Callable[..., Optional[T]]:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
            try:
                return f(*args, **kwargs)
            except (ActuarySleuthException, ValidationException):
                raise
            except ConnectionError as e:
                logger.error(f"LLM 服务连接失败: {e}")
                raise AuditStepException(
                    message="LLM 服务连接失败",
                    step="llm_call",
                    details={'original_error': str(e)}
                )
            except TimeoutError as e:
                logger.error(f"LLM 服务超时: {e}")
                raise AuditStepException(
                    message="LLM 服务响应超时",
                    step="llm_call",
                    details={'original_error': str(e)}
                )
            except Exception as e:
                logger.exception(f"LLM 调用失败")
                raise AuditStepException(
                    message=f"LLM 调用失败: {e}",
                    step="llm_call",
                    details={'error_type': type(e).__name__}
                )
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


@overload
def handle_database_errors(func: Callable[..., T]) -> Callable[..., T]: ...

@overload
def handle_database_errors(func: None = None) -> Callable[[Callable[..., T]], Callable[..., T]]: ...

def handle_database_errors(func: Optional[Callable[..., T]] = None):
    """
    数据库操作错误处理装饰器

    Args:
        func: 要包装的函数（可选，如果为None则返回装饰器）

    Returns:
        装饰器或包装后的函数
    """
    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return f(*args, **kwargs)
            except (ActuarySleuthException, ValidationException):
                raise
            except Exception as e:
                logger.exception(f"数据库操作失败")
                from lib.common.exceptions import DatabaseException
                raise DatabaseException(
                    message=f"数据库操作失败: {e}",
                    operation=f.__name__
                )
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def safe_execute(
    func: Callable[[], T],
    default_value: T,
    error_message: str = ""
) -> T:
    """
    安全执行函数，捕获所有异常

    Args:
        func: 要执行的函数
        default_value: 发生异常时返回的默认值
        error_message: 错误消息

    Returns:
        函数执行结果或默认值
    """
    try:
        return func()
    except Exception as e:
        if error_message:
            logger.error(f"{error_message}: {e}")
        return default_value
