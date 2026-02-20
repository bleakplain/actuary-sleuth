#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ID 生成器模块

提供统一的ID生成功能，消除代码重复，确保ID唯一性和一致性
"""
import random
from datetime import datetime
from typing import Optional
from enum import Enum


class IDPrefix(Enum):
    """ID 前缀枚举"""
    AUDIT = "AUD"      # 审核ID
    PREPROCESS = "PRE" # 预处理ID
    REPORT = "RPT"     # 报告ID
    REGULATION = "REG" # 法规ID
    VIOLATION = "VL"   # 违规ID


class IDGenerator:
    """
    统一ID生成器

    使用毫秒时间戳 + 随机数确保并发安全性
    格式: {PREFIX}-{timestamp_ms}-{random}

    示例:
        AUD-1771382404509-3186
        PRE-1771382407877-5547
        RPT-1771382413137-1996
    """

    # 随机数范围
    RANDOM_MIN = 1000
    RANDOM_MAX = 9999

    @classmethod
    def generate(cls, prefix: IDPrefix, random_range: tuple = (RANDOM_MIN, RANDOM_MAX)) -> str:
        """
        生成唯一ID

        Args:
            prefix: ID前缀枚举值
            random_range: 随机数范围 (min, max)

        Returns:
            str: 格式化的唯一ID

        Examples:
            >>> IDGenerator.generate(IDPrefix.AUDIT)
            'AUD-1771382404509-3186'
            >>> IDGenerator.generate(IDPrefix.REPORT)
            'RPT-1771382407877-5547'
        """
        timestamp = int(datetime.now().timestamp() * 1000)
        random_num = random.randint(random_range[0], random_range[1])
        return f"{prefix.value}-{timestamp}-{random_num}"

    @classmethod
    def generate_audit(cls) -> str:
        """生成审核ID"""
        return cls.generate(IDPrefix.AUDIT)

    @classmethod
    def generate_preprocess(cls) -> str:
        """生成预处理ID"""
        return cls.generate(IDPrefix.PREPROCESS)

    @classmethod
    def generate_report(cls) -> str:
        """生成报告ID"""
        return cls.generate(IDPrefix.REPORT)

    @classmethod
    def generate_regulation(cls) -> str:
        """生成法规ID"""
        return cls.generate(IDPrefix.REGULATION)

    @classmethod
    def generate_violation(cls) -> str:
        """生成违规ID"""
        return cls.generate(IDPrefix.VIOLATION)

    @classmethod
    def parse_id(cls, id_str: str) -> Optional[dict]:
        """
        解析ID字符串，提取各组成部分

        Args:
            id_str: ID字符串

        Returns:
            dict: 包含 prefix, timestamp, random_num 的字典，解析失败返回 None

        Examples:
            >>> IDGenerator.parse_id("AUD-1771382404509-3186")
            {'prefix': 'AUD', 'timestamp': 1771382404509, 'random_num': 3186}
        """
        try:
            parts = id_str.split('-')
            if len(parts) != 3:
                return None

            return {
                'prefix': parts[0],
                'timestamp': int(parts[1]),
                'random_num': int(parts[2])
            }
        except (ValueError, AttributeError):
            return None

    @classmethod
    def is_valid_id(cls, id_str: str, expected_prefix: Optional[IDPrefix] = None) -> bool:
        """
        验证ID格式是否有效

        Args:
            id_str: 待验证的ID字符串
            expected_prefix: 期望的前缀，如果为None则不检查前缀

        Returns:
            bool: ID是否有效

        Examples:
            >>> IDGenerator.is_valid_id("AUD-1771382404509-3186", IDPrefix.AUDIT)
            True
            >>> IDGenerator.is_valid_id("INVALID-ID")
            False
        """
        parsed = cls.parse_id(id_str)
        if not parsed:
            return False

        if expected_prefix:
            return parsed['prefix'] == expected_prefix.value

        return True


# 便捷函数，保持向后兼容
def generate_audit_id() -> str:
    """生成审核ID (便捷函数)"""
    return IDGenerator.generate_audit()


def generate_preprocess_id() -> str:
    """生成预处理ID (便捷函数)"""
    return IDGenerator.generate_preprocess()


def generate_report_id() -> str:
    """生成报告ID (便捷函数)"""
    return IDGenerator.generate_report()