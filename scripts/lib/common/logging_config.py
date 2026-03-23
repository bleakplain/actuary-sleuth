"""日志配置（统一版本）"""

import logging
import sys
from typing import Optional
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    """结构化日志格式器"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        if hasattr(record, 'audit_id'):
            base += f" [audit_id={record.audit_id}]"
        return base


_log_level = logging.INFO
_log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_json_output = False


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[str] = None
) -> None:
    """
    配置应用日志（统一入口）

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: 是否使用JSON格式输出
        log_file: 日志文件路径（可选）
    """
    global _log_level, _log_format, _json_output

    _log_level = getattr(logging, level.upper(), logging.INFO)
    _log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    _json_output = json_output

    root_logger = logging.getLogger()
    root_logger.setLevel(_log_level)

    handlers = []

    stdout_handler = logging.StreamHandler(sys.stdout)
    formatter = StructuredFormatter(_log_format)
    stdout_handler.setFormatter(formatter)
    handlers.append(stdout_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root_logger.handlers = handlers


def get_logger(name: str) -> logging.Logger:
    """
    获取命名日志记录器（统一方式）

    Args:
        name: 日志记录器名称，通常使用 __name__

    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(_log_level)
    return logger


def set_log_level(level: str) -> None:
    """
    动态设置日志级别

    Args:
        level: 日志级别字符串
    """
    global _log_level
    _log_level = getattr(logging, level.upper(), logging.INFO)
    logging.getLogger().setLevel(_log_level)


def enable_debug_logging() -> None:
    """启用调试日志"""
    set_log_level("DEBUG")


def enable_file_logging(log_dir: str) -> None:
    """
    启用文件日志

    Args:
        log_dir: 日志目录路径
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / "actuary_sleuth.log"

    file_handler = logging.FileHandler(str(log_file), encoding='utf-8')
    formatter = StructuredFormatter(_log_format)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

