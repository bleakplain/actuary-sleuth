"""规则引擎测试"""
import pytest
from lib.compliance.rule_engine import check_rules, _extract_numeric_value, RULES, ProductMetadata


class TestExtractNumericValue:
    def test_days_extraction(self):
        assert _extract_numeric_value("犹豫期为15天", "犹豫期") == 15

    def test_context_window(self):
        assert _extract_numeric_value("条款内容...\n犹豫期 30 日\n后续内容", "犹豫期") == 30

    def test_no_match(self):
        assert _extract_numeric_value("无相关数值", "犹豫期") is None

    def test_synonym_observation_period(self):
        assert _extract_numeric_value("观察期为90天", "等待期") == 90

    def test_synonym_cooling_off(self):
        assert _extract_numeric_value("冷静期10天", "犹豫期") == 10

    def test_percentage_extraction(self):
        assert _extract_numeric_value("轻症给付比例为35%", "轻症") == 35

    def test_wan_extraction(self):
        assert _extract_numeric_value("身故保险金30万", "身故保险金") == 30

    def test_decimal_percentage(self):
        assert _extract_numeric_value("给付比例为2.5%", "比例") == 2.5


class TestCheckRules:
    def test_wait_period_violation(self):
        doc = "【条款 3.1】等待期\n本产品等待期为270天"
        violations = check_rules(doc, "健康险")
        wait_v = [v for v in violations if v.rule_id == "health_wait_period_max_180"]
        assert len(wait_v) == 1
        assert wait_v[0].confidence == "high"
        assert wait_v[0].check_type == "rule_engine"

    def test_wait_period_compliant(self):
        doc = "【条款 3.1】等待期\n本产品等待期为90天"
        violations = check_rules(doc, "健康险")
        wait_v = [v for v in violations if v.rule_id == "health_wait_period_max_180"]
        assert len(wait_v) == 0

    def test_wait_period_no_value(self):
        doc = "【条款 3.1】等待期\n等待期以条款约定为准"
        violations = check_rules(doc, "健康险")
        wait_v = [v for v in violations if v.rule_id == "health_wait_period_max_180"]
        assert len(wait_v) == 0

    def test_category_filter(self):
        doc = "【条款 3.1】等待期\n等待期为270天"
        violations = check_rules(doc, "意外险")
        wait_v = [v for v in violations if v.rule_id == "health_wait_period_max_180"]
        assert len(wait_v) == 0

    def test_guarantee_renew_violation(self):
        doc = "【条款 2.1】续保\n本产品保证续保"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        renew_v = [v for v in violations if v.rule_id == "short_health_no_guarantee_renew"]
        assert len(renew_v) == 1
        assert "禁止表述" in renew_v[0].conclusion

    def test_guarantee_renew_compliant(self):
        doc = "【条款 2.1】续保\n本产品不保证续保"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        renew_v = [v for v in violations if v.rule_id == "short_health_no_guarantee_renew"]
        assert len(renew_v) == 0

    def test_guarantee_renew_wrong_category(self):
        doc = "【条款 2.1】续保\n本产品保证续保"
        violations = check_rules(doc, "寿险")
        renew_v = [v for v in violations if v.rule_id == "short_health_no_guarantee_renew"]
        assert len(renew_v) == 0

    def test_hesitation_period_violation(self):
        doc = "【条款 4.1】犹豫期\n犹豫期为7天"
        meta = ProductMetadata(category="健康险", insurance_term="长期")
        violations = check_rules(doc, "健康险", meta)
        hes_v = [v for v in violations if v.rule_id in ("hesitation_period_min_15", "health_hesitation_min_15", "life_hesitation_min_15")]
        assert len(hes_v) >= 1

    def test_hesitation_period_compliant(self):
        doc = "【条款 4.1】犹豫期\n犹豫期为15天"
        meta = ProductMetadata(category="健康险", insurance_term="长期")
        violations = check_rules(doc, "健康险", meta)
        hes_v = [v for v in violations if v.rule_id in ("hesitation_period_min_15", "health_hesitation_min_15", "life_hesitation_min_15")]
        assert len(hes_v) == 0

    def test_hesitation_period_short_health_not_applied(self):
        # 短期健康险不应触发长期健康险的犹豫期规则
        doc = "【条款 4.1】犹豫期\n犹豫期为7天"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        hes_v = [v for v in violations if v.rule_id == "health_hesitation_min_15"]
        assert len(hes_v) == 0

    def test_hesitation_period_applies_all_categories(self):
        doc = "【条款 4.1】犹豫期\n犹豫期为7天"
        violations = check_rules(doc, "意外险")
        hes_v = [v for v in violations if v.rule_id == "life_hesitation_min_15"]
        assert len(hes_v) == 1

    def test_no_category(self):
        doc = "【条款 3.1】等待期\n等待期为270天"
        violations = check_rules(doc, None)
        assert len(violations) == 0

    def test_multiple_violations(self):
        doc = "【条款 3.1】等待期\n等待期为270天\n\n【条款 4.1】犹豫期\n犹豫期为7天"
        meta = ProductMetadata(category="健康险", insurance_term="长期")
        violations = check_rules(doc, "健康险", meta)
        rules = {v.rule_id for v in violations}
        assert "health_wait_period_max_180" in rules
        assert "health_hesitation_min_15" in rules
        assert len(violations) >= 2


class TestRequiredText:
    def test_short_health_must_state_1year_violation(self):
        doc = "【条款 2.1】保险期间\n本产品保险期间为长期"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        v = [v for v in violations if v.rule_id == "short_health_must_state_1year"]
        assert len(v) == 1
        assert "缺少必要内容" in v[0].conclusion

    def test_short_health_must_state_1year_compliant(self):
        doc = "【条款 2.1】保险期间\n本产品保险期间为1年"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        v = [v for v in violations if v.rule_id == "short_health_must_state_1year"]
        assert len(v) == 0

    def test_short_health_must_state_1year_wrong_category(self):
        doc = "【条款 2.1】保险期间\n本产品保险期间为长期"
        meta = ProductMetadata(category="寿险", insurance_term="短期")
        violations = check_rules(doc, "寿险", meta)
        v = [v for v in violations if v.rule_id == "short_health_must_state_1year"]
        assert len(v) == 0

    def test_short_health_rules_not_triggered_for_long_term(self):
        """长期健康险不应触发短期健康险规则。"""
        doc = "【条款 2.1】保险期间\n本产品保险期间为长期"
        meta = ProductMetadata(category="健康险", insurance_term="长期")
        violations = check_rules(doc, "健康险", meta)
        v = [v for v in violations if v.rule_id in ("short_health_no_guarantee_renew", "short_health_must_state_1year", "short_health_must_nonrenew_disclosure")]
        assert len(v) == 0

    def test_must_nonrenew_disclosure_violation(self):
        doc = "【条款 2.2】续保\n本产品可续保"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        v = [v for v in violations if v.rule_id == "short_health_must_nonrenew_disclosure"]
        assert len(v) == 1

    def test_must_nonrenew_disclosure_compliant(self):
        doc = "【条款 2.2】续保\n本产品不保证续保"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        v = [v for v in violations if v.rule_id == "short_health_must_nonrenew_disclosure"]
        assert len(v) == 0

    def test_dividend_must_state_undetermined_violation(self):
        doc = "【条款 5.1】红利\n本公司每年分配红利"
        violations = check_rules(doc, "分红险")
        v = [v for v in violations if v.rule_id == "dividend_must_state_undetermined"]
        assert len(v) == 1

    def test_dividend_must_state_undetermined_compliant(self):
        doc = "【条款 5.1】红利\n红利是不确定的"
        violations = check_rules(doc, "分红险")
        v = [v for v in violations if v.rule_id == "dividend_must_state_undetermined"]
        assert len(v) == 0

    def test_required_text_in_any_clause(self):
        doc = "【条款 1.1】投保须知\n重要提示\n\n【条款 2.1】续保\n本产品不保证续保，保险期间为1年"
        meta = ProductMetadata(category="健康险", insurance_term="短期")
        violations = check_rules(doc, "健康险", meta)
        v1 = [v for v in violations if v.rule_id == "short_health_must_state_1year"]
        assert len(v1) == 0
        v2 = [v for v in violations if v.rule_id == "short_health_must_nonrenew_disclosure"]
        assert len(v2) == 0


class TestProhibitedClause:
    def test_dividend_no_guarantee_rate_violation(self):
        doc = "【条款 5.1】红利\n本公司保证红利不低于3%"
        violations = check_rules(doc, "分红险")
        v = [v for v in violations if v.rule_id == "dividend_no_guarantee_rate"]
        assert len(v) == 1
        assert "禁止内容" in v[0].conclusion

    def test_dividend_no_guarantee_rate_compliant(self):
        doc = "【条款 5.1】红利\n红利分配根据公司经营状况确定"
        violations = check_rules(doc, "分红险")
        v = [v for v in violations if v.rule_id == "dividend_no_guarantee_rate"]
        assert len(v) == 0

    def test_internet_annuity_no_guarantee_rate_removed(self):
        # 该规则已删除（项目内法规无此要求）
        doc = "【条款 3.1】保险费\n本产品保证利率为2.5%"
        violations = check_rules(doc, "年金险")
        v = [v for v in violations if v.rule_id == "internet_annuity_no_guarantee_rate"]
        assert len(v) == 0

    def test_design_no_death_main_health_violation(self):
        doc = "【条款 1.1】保险责任\n本健康险以死亡为给付保险金条件"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "design_no_death_main_health"]
        assert len(v) == 1

    def test_design_no_death_main_health_compliant(self):
        doc = "【条款 1.1】保险责任\n本产品承担疾病给付责任"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "design_no_death_main_health"]
        assert len(v) == 0


class TestFieldPresence:
    def test_health_must_have_preexisting_violation(self):
        doc = "【条款 1.1】保险责任\n本产品承担疾病给付责任\n\n【条款 2.1】等待期\n等待期为90天"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "health_must_have_preexisting"]
        assert len(v) == 1
        assert v[0].clause_number == "全文档"
        assert "既往症" in v[0].conclusion

    def test_health_must_have_preexisting_compliant(self):
        doc = "【条款 1.1】保险责任\n本产品承担疾病给付责任\n\n【条款 1.2】定义\n既往症指投保前已患的疾病"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "health_must_have_preexisting"]
        assert len(v) == 0

    def test_health_must_have_preexisting_synonym(self):
        doc = "【条款 1.1】定义\n既往疾病指投保前已患的疾病"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "health_must_have_preexisting"]
        assert len(v) == 0

    def test_life_must_have_cash_value_violation(self):
        doc = "【条款 1.1】保险责任\n身故给付基本保额\n\n【条款 2.1】保费\n年交保费1000元"
        violations = check_rules(doc, "寿险")
        v = [v for v in violations if v.rule_id == "life_must_have_cash_value"]
        assert len(v) == 1

    def test_life_must_have_cash_value_compliant(self):
        doc = "【条款 1.1】保险责任\n身故给付\n\n【条款 5.1】现金价值\n现金价值表如下"
        violations = check_rules(doc, "寿险")
        v = [v for v in violations if v.rule_id == "life_must_have_cash_value"]
        assert len(v) == 0

    def test_life_must_have_cash_value_wrong_category(self):
        doc = "【条款 1.1】保险责任\n身故给付"
        violations = check_rules(doc, "意外险")
        v = [v for v in violations if v.rule_id == "life_must_have_cash_value"]
        assert len(v) == 0

    def test_health_must_have_waiting_period_disclosure_removed(self):
        # 该规则已删除（法规仅规定上限，未强制必须设置）
        doc = "【条款 1.1】保险责任\n本产品承担疾病给付责任"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "health_must_have_waiting_period_disclosure"]
        assert len(v) == 0

    def test_health_long_term_renewal_clause_violation(self):
        doc = "【条款 1.1】保险责任\n本产品承担疾病给付责任"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "health_long_term_renewal_clause"]
        assert len(v) == 1

    def test_health_long_term_renewal_clause_compliant(self):
        doc = "【条款 1.1】保险责任\n本产品承担疾病给付责任\n\n【条款 3.1】续保\n保证续保期间为20年"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "health_long_term_renewal_clause"]
        assert len(v) == 0


class TestNumericSpecificRules:
    def test_deleted_non_clause_regulation_has_no_deterministic_rule(self):
        deleted_rule_ids = {"minor_death_benefit_under10", "minor_death_benefit_10to17"}

        assert deleted_rule_ids.isdisjoint(rule.rule_id for rule in RULES)

    def test_ci_mild_pay_ratio_max_30_violation(self):
        doc = "【条款 2.1】轻症\n轻度疾病给付比例为基本保险金额的40%"
        violations = check_rules(doc, "重疾险")
        v = [v for v in violations if v.rule_id == "ci_mild_pay_ratio_max_30"]
        assert len(v) == 1

    def test_ci_mild_pay_ratio_max_30_compliant(self):
        doc = "【条款 2.1】轻症\n轻度疾病给付比例为基本保险金额的30%"
        violations = check_rules(doc, "重疾险")
        v = [v for v in violations if v.rule_id == "ci_mild_pay_ratio_max_30"]
        assert len(v) == 0

    def test_ci_moderate_pay_ratio_max_60_removed(self):
        # 该规则已删除（2020版规范无中症60%的强制条款）
        doc = "【条款 2.2】中症\n中度疾病给付比例为基本保险金额的70%"
        violations = check_rules(doc, "重疾险")
        v = [v for v in violations if v.rule_id == "ci_moderate_pay_ratio_max_60"]
        assert len(v) == 0

    def test_grace_period_min_60_violation(self):
        doc = "【条款 5.1】宽限期\n宽限期为30天"
        violations = check_rules(doc, "寿险")
        v = [v for v in violations if v.rule_id == "grace_period_min_60"]
        assert len(v) == 1

    def test_grace_period_min_60_compliant(self):
        doc = "【条款 5.1】宽限期\n宽限期为60天"
        violations = check_rules(doc, "寿险")
        v = [v for v in violations if v.rule_id == "grace_period_min_60"]
        assert len(v) == 0

    def test_long_medical_rate_adjust_first_interval_3y_violation(self):
        doc = "【条款 3.1】首次费率调整\n首次费率调整时间为上市后2年"
        meta = ProductMetadata(category="医疗险", insurance_term="长期")
        violations = check_rules(doc, "医疗险", meta)
        v = [v for v in violations if v.rule_id == "long_medical_rate_adjust_first_interval_3y"]
        assert len(v) == 1

    def test_long_medical_rate_adjust_first_interval_3y_compliant(self):
        doc = "【条款 3.1】首次费率调整\n首次费率调整时间为上市后3年"
        meta = ProductMetadata(category="医疗险", insurance_term="长期")
        violations = check_rules(doc, "医疗险", meta)
        v = [v for v in violations if v.rule_id == "long_medical_rate_adjust_first_interval_3y"]
        assert len(v) == 0

    def test_long_medical_rate_adjust_subsequent_interval_1y_violation(self):
        # 法规要求 ≥1年，"间隔为0年"（即随时调整）触发违规
        # 注：数值提取按单位独立比较，不跨单位换算
        doc = "【条款 3.1】费率调整间隔\n费率调整间隔为0年"
        meta = ProductMetadata(category="医疗险", insurance_term="长期")
        violations = check_rules(doc, "医疗险", meta)
        v = [v for v in violations if v.rule_id == "long_medical_rate_adjust_subsequent_interval_1y"]
        assert len(v) == 1

    def test_long_medical_rate_adjust_not_long_term(self):
        doc = "【条款 3.1】费率调整间隔\n费率调整间隔为2年"
        # 短期医疗险不应触发长期费率调整规则
        meta = ProductMetadata(category="医疗险", insurance_term="短期")
        violations = check_rules(doc, "医疗险", meta)
        v1 = [v for v in violations if v.rule_id == "long_medical_rate_adjust_first_interval_3y"]
        v2 = [v for v in violations if v.rule_id == "long_medical_rate_adjust_subsequent_interval_1y"]
        assert len(v1) == 0
        assert len(v2) == 0

    def test_insurance_law_limitation_life_violation(self):
        # 人寿保险诉讼时效不得少于5年（保险法第二十六条）
        doc = "【条款 6.1】诉讼时效\n诉讼时效为3年"
        violations = check_rules(doc, "寿险")
        v = [v for v in violations if v.rule_id == "insurance_law_limitation_5y_life"]
        assert len(v) == 1

    def test_insurance_law_limitation_life_compliant(self):
        doc = "【条款 6.1】诉讼时效\n诉讼时效为5年"
        violations = check_rules(doc, "寿险")
        v = [v for v in violations if v.rule_id == "insurance_law_limitation_5y_life"]
        assert len(v) == 0

    def test_insurance_law_limitation_nonlife_violation(self):
        # 非人寿保险诉讼时效不得少于2年
        doc = "【条款 6.1】诉讼时效\n诉讼时效为1年"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "insurance_law_limitation_2y_nonlife"]
        assert len(v) == 1

    def test_tax_health_deductible_limit_removed(self):
        # 该规则已删除（法规无"免赔额≤2万"要求，方向相反）
        doc = "【条款 3.1】免赔额\n免赔额为3万"
        violations = check_rules(doc, "健康险")
        v = [v for v in violations if v.rule_id == "tax_health_deductible_limit"]
        assert len(v) == 0

    def test_design_first_survival_payment_after_5y_violation(self):
        doc = "【条款 2.1】首次生存保险金给付\n首次生存保险金给付为保单生效后3年"
        meta = ProductMetadata(category="寿险", insurance_term="长期")
        violations = check_rules(doc, "寿险", meta)
        v = [v for v in violations if v.rule_id == "design_first_survival_payment_after_5y"]
        assert len(v) == 1

    def test_design_first_survival_payment_after_5y_compliant(self):
        doc = "【条款 2.1】首次生存保险金给付\n首次生存保险金给付为保单生效后5年"
        meta = ProductMetadata(category="寿险", insurance_term="长期")
        violations = check_rules(doc, "寿险", meta)
        v = [v for v in violations if v.rule_id == "design_first_survival_payment_after_5y"]
        assert len(v) == 0


class TestRuleUniqueness:
    def test_all_rule_ids_unique(self):
        ids = [r.rule_id for r in RULES]
        assert len(ids) == len(set(ids)), f"重复的 rule_id: {[rid for rid in ids if ids.count(rid) > 1]}"

    def test_no_empty_applicable_categories_when_needed(self):
        for rule in RULES:
            if rule.check_type in ("numeric_comparison", "numeric_range"):
                if rule.rule_id not in ("life_hesitation_min_15",):
                    assert rule.applicable_categories or rule.applicable_categories == [], \
                        f"规则 {rule.rule_id} 应设置 applicable_categories"


class TestIntegration:
    def test_multi_type_violations(self):
        doc = (
            "【条款 1.1】保险责任\n本健康险以死亡为给付保险金条件\n\n"
            "【条款 2.1】等待期\n等待期为270天\n\n"
            "【条款 3.1】犹豫期\n犹豫期为7天"
        )
        violations = check_rules(doc, "健康险")
        rules = {v.rule_id for v in violations}
        assert "health_wait_period_max_180" in rules
        assert "design_no_death_main_health" in rules

    def test_fully_compliant_doc(self):
        doc = (
            "【条款 1.1】定义\n既往症指投保前已患的疾病\n\n"
            "【条款 2.1】等待期\n等待期为90天\n\n"
            "【条款 2.2】续保\n本产品不保证续保，保险期间为1年\n\n"
            "【条款 3.1】犹豫期\n犹豫期为15天\n\n"
            "【条款 4.1】诉讼时效\n诉讼时效为5年"
        )
        violations = check_rules(doc, "健康险")
        assert len(violations) == 0
