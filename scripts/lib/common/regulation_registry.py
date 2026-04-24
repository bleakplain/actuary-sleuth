"""险种法规映射配置"""
from typing import Dict, List
from lib.common.constants import ComplianceConstants

VALID_CATEGORIES = ComplianceConstants.VALID_CATEGORIES

CATEGORY_REGULATION_REGISTRY: Dict[str, List[str]] = ComplianceConstants.CATEGORY_REGULATION_REGISTRY

GENERAL_REGULATIONS: List[str] = ComplianceConstants.GENERAL_REGULATIONS


def get_category_regulations(category: str) -> List[str]:
    """获取险种专属法规名称列表"""
    return CATEGORY_REGULATION_REGISTRY.get(category, [])


def get_general_regulations() -> List[str]:
    """获取通用法规名称列表"""
    return GENERAL_REGULATIONS.copy()
