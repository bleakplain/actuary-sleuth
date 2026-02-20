#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整改策略接口

定义违规整改策略的抽象接口，所有具体策略必须实现此接口
"""
from abc import ABC, abstractmethod
from typing import Dict, Any


class RemediationStrategy(ABC):
    """
    整改策略接口 (Strategy Interface)

    定义所有整改策略必须实现的接口
    """

    @abstractmethod
    def can_handle(self, violation: Dict[str, Any]) -> bool:
        """
        判断是否可以处理该类型的违规

        Args:
            violation: 违规记录字典

        Returns:
            bool: 如果该策略可以处理此违规返回 True
        """
        pass

    @abstractmethod
    def get_remediation(self, violation: Dict[str, Any]) -> str:
        """
        获取具体的整改建议

        Args:
            violation: 违规记录字典

        Returns:
            str: 整改建议文本
        """
        pass
