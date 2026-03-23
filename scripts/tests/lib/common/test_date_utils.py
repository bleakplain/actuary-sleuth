#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试时间工具
"""
import pytest
from datetime import datetime

from lib.common.date_utils import get_current_timestamp


class TestDateUtils:
    """测试时间工具函数"""

    def test_get_current_timestamp(self):
        """测试获取当前时间"""
        result = get_current_timestamp()
        assert isinstance(result, datetime)
        assert result <= datetime.now()

    def test_get_current_timestamp_multiple_calls(self):
        """测试多次调用返回递增时间"""
        result1 = get_current_timestamp()
        result2 = get_current_timestamp()
        assert result2 >= result1
