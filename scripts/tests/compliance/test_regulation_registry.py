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


def test_subcategories_inherit_parent_regulation_category():
    assert ComplianceConstants.CATEGORY_PARENT_MAPPING["医疗险"] == "健康险"
    assert ComplianceConstants.CATEGORY_PARENT_MAPPING["重疾险"] == "健康险"
    assert ComplianceConstants.CATEGORY_PARENT_MAPPING["年金险"] == "寿险"
    assert ComplianceConstants.CATEGORY_PARENT_MAPPING["分红险"] == "寿险"


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


def test_registry_does_not_reference_intentionally_removed_v5_regulations():
    removed = {
        "中国银保监会《关于规范保险公司健康管理服务的通知》（银保监办发〔2020〕83号）",
        "关于短期健康保险产品有关风险的提示（电子报备系统通知公告2023-11-06）",
        "最高人民法院《关于适用〈中华人民共和国保险法〉若干问题的解释（二）》",
        "中国银保监会办公厅关于强化人身保险精算监管有关事项的通知（银保监办发〔2020〕6号）",
        "国家金融监督管理总局关于健全人身保险产品定价机制的通知（金发[2024]18号）",
        "国家金融监督管理总局人身险司关于建立预定利率与市场利率挂钩及动态调整机制有关事项的通知（金寿险函[2025]10号）",
        "中国保监会《关于父母为其未成年子女投保以死亡为给付保险金条件人身保险有关问题的通知》（保监发〔2015〕90号）",
    }
    registered = set(ComplianceConstants.GENERAL_REGULATIONS)
    for names in ComplianceConstants.CATEGORY_REGULATION_REGISTRY.values():
        registered.update(names)

    assert removed.isdisjoint(registered)
