#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖版本检查工具"""
import logging
from typing import Optional, Tuple


logger = logging.getLogger(__name__)

# 依赖版本要求
DEPENDENCY_REQUIREMENTS = {
    'bs4': (4, 12, 0),
    'beautifulsoup4': (4, 12, 0),
}


def check_version(module_name: str, min_version: Tuple[int, int, int]) -> Tuple[bool, str]:
    """检查模块版本是否满足要求

    Args:
        module_name: 模块名称
        min_version: 最低版本 (major, minor, patch)

    Returns:
        (是否满足, 版本字符串或错误信息)
    """
    try:
        if module_name == 'bs4':
            import bs4
            version_str = bs4.__version__
        elif module_name == 'beautifulsoup4':
            import bs4
            version_str = bs4.__version__
        else:
            return False, f"未知模块: {module_name}"

        # 解析版本字符串
        version_parts = version_str.split('.')[:3]
        version_tuple = tuple(int(p) for p in version_parts)

        if version_tuple >= min_version:
            return True, version_str
        else:
            return False, f"版本过低: {version_str} < {'.'.join(map(str, min_version))}"

    except ImportError:
        return False, "未安装"
    except (ValueError, AttributeError) as e:
        return False, f"版本解析失败: {e}"


def check_bs4() -> Optional[str]:
    """检查 BeautifulSoup4 版本

    Returns:
        版本字符串，如果不满足要求则返回 None
    """
    is_valid, info = check_version('bs4', DEPENDENCY_REQUIREMENTS['bs4'])

    if is_valid:
        logger.info(f"BeautifulSoup4 版本检查通过: {info}")
        return info
    else:
        logger.warning(f"BeautifulSoup4 版本检查失败: {info}")
        return None
