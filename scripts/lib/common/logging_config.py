"""日志配置"""

import logging
import sys
from typing import Any


class StructuredFormatter(logging.Formatter):
    """结构化日志格式器"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        if hasattr(record, 'audit_id'):
            base += f" [audit_id={record.audit_id}]"
        return base


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """配置应用日志"""
    handler = logging.StreamHandler(sys.stdout)

    if json_output:
        formatter = StructuredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    else:
        formatter = StructuredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.addHandler(handler)
