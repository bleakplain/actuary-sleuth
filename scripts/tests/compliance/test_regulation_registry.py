"""险种法规映射配置测试"""
import pytest
from lib.common.constants import ComplianceConstants


def test_get_category_regulations():
    """测试获取险种专属法规"""
    health_regs = ComplianceConstants.CATEGORY_REGULATION_REGISTRY.get("健康险", [])
    assert len(health_regs) >= 2
    assert "《健康保险管理办法》2019年第3号" in health_regs


def test_get_category_regulations_unknown():
    """测试未知险种返回空列表"""
    result = ComplianceConstants.CATEGORY_REGULATION_REGISTRY.get("未知险种", [])
    assert result == []


def test_get_general_regulations():
    """测试获取通用法规"""
    general = ComplianceConstants.GENERAL_REGULATIONS
    assert "中华人民共和国保险法（2015年修订版）" in general
    assert "《人身保险公司保险条款和保险费率管理办法（2015年修订）》（2015年第3号）" in general


def test_all_categories_have_regulations():
    """测试所有配置的险种都有法规"""
    for category in ComplianceConstants.CATEGORY_REGULATION_REGISTRY:
        regs = ComplianceConstants.CATEGORY_REGULATION_REGISTRY[category]
        assert len(regs) > 0, f"险种 {category} 没有配置法规"
