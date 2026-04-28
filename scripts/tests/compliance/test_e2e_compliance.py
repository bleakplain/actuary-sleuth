"""保险产品文档合规审核端到端测试

使用表驱动测试方法，从真实保险产品文档目录加载文件，
验证完整的文档解析 → 合规检查 → 结果输出流程。
"""
import os
import pytest
import httpx
from pathlib import Path
from typing import NamedTuple


class TestCase(NamedTuple):
    """测试用例定义"""
    name: str           # 用例名称
    file_path: str      # 文件路径
    expected_category: str  # 预期险种类型
    min_items: int      # 预期最小检查项数
    check_negative_list: bool  # 是否检查负面清单


# 测试数据表 - 使用真实保险产品文档
TEST_CASES = [
    TestCase(
        name="互联网重大疾病保险",
        file_path="《人保健康互联网重大疾病保险（A款）》条款V5 - 无修订.docx",
        expected_category="重疾险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="互联网团体意外伤害保险",
        file_path="《人保健康互联网团体意外伤害保险（2025版）》条款.pdf",
        expected_category="意外险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="互联网手术医疗意外保险",
        file_path="《人保健康互联网手术医疗意外保险》保险条款.pdf",
        expected_category="医疗险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="互联网失能收入损失保险",
        file_path="《人保健康互联网失能收入损失保险（2025版）》条款.docx",
        expected_category="寿险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="附加互联网恶性肿瘤特定药品费用医疗保险",
        file_path="《人保健康附加互联网恶性肿瘤特定药品费用医疗保险》条款.pdf",
        expected_category="医疗险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="团体短期重大疾病保险",
        file_path="《人保健康团体短期重大疾病保险（推荐版）》条款.docx",
        expected_category="重疾险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="附加团体终身重度恶性肿瘤疾病保险",
        file_path="《人保健康附加团体终身重度恶性肿瘤疾病保险》条款.docx",
        expected_category="重疾险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="企业员工团体终身重大疾病保险",
        file_path="《人保健康企业员工团体终身重大疾病保险（H款）》条款.docx",
        expected_category="重疾险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="城市定制型团体医疗保险",
        file_path="《人保健康城市定制型团体医疗保险（A款）》产品条款.docx",
        expected_category="医疗险",
        min_items=1,
        check_negative_list=True,
    ),
    TestCase(
        name="附加出境人员团体意外医疗保险",
        file_path="《人保健康附加出境人员团体意外医疗保险》条款v2-无标记.docx",
        expected_category="意外险",
        min_items=1,
        check_negative_list=True,
    ),
]


# 产品文档目录
PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products")

# API 基础 URL
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def api_client():
    """HTTP 客户端 fixture"""
    with httpx.Client(base_url=API_BASE_URL, timeout=120.0) as client:
        yield client


@pytest.mark.parametrize("test_case", TEST_CASES, ids=[tc.name for tc in TEST_CASES])
def test_compliance_check_e2e(test_case: TestCase, api_client: httpx.Client):
    """端到端测试：文档解析 → 合规检查 → 结果验证"""
    file_path = PRODUCTS_DIR / test_case.file_path
    assert file_path.exists(), f"文件不存在: {file_path}"

    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f)}
        parse_response = api_client.post("/api/compliance/parse-file", files=files)

    assert parse_response.status_code == 200, f"解析失败: {parse_response.text}"
    parse_result = parse_response.json()
    assert "combined_text" in parse_result, "解析结果缺少 combined_text"
    assert len(parse_result["combined_text"]) > 100, "解析文本过短"
    assert len(parse_result.get("clauses", [])) > 0 or len(parse_result.get("premium_tables", [])) > 0, \
        "解析结果无条款或费率表"

    check_response = api_client.post(
        "/api/compliance/check/document",
        json={
            "document_content": parse_result["combined_text"],
            "product_name": test_case.name,
        }
    )

    assert check_response.status_code == 200, f"合规检查失败: {check_response.text}"
    check_result = check_response.json()
    assert "result" in check_result, "结果缺少 result 字段"
    result = check_result["result"]

    assert "summary" in result, "结果缺少 summary"
    summary = result["summary"]
    total_items = summary.get("compliant", 0) + summary.get("non_compliant", 0) + summary.get("attention", 0)
    assert total_items >= test_case.min_items, f"检查项数 {total_items} 少于预期 {test_case.min_items}"

    if test_case.check_negative_list:
        assert result.get("negative_list_checked") == True, "未执行负面清单检查"

    assert "regulation_sources" in result, "结果缺少 regulation_sources"
    sources = result["regulation_sources"]
    assert "通用法规" in sources and len(sources["通用法规"]) > 0, "缺少通用法规"
    assert "险种专属" in sources, "缺少险种专属"


def test_category_identification(api_client: httpx.Client):
    """测试险种识别功能"""
    test_cases = [
        ("重大疾病保险条款", "重疾险"),
        ("意外伤害保险条款", "意外险"),
        ("住院医疗保险条款", "医疗险"),
        ("终身寿险条款", "寿险"),
        ("年金保险条款", "年金险"),
    ]

    for content, expected_category in test_cases:
        response = api_client.post(
            "/api/compliance/identify-category",
            json={"document_content": content}
        )
        assert response.status_code == 200
        result = response.json()
        assert "category" in result
        assert "confidence" in result
        assert "suggested_categories" in result
        assert len(result["suggested_categories"]) <= 5


def test_report_crud(api_client: httpx.Client):
    """测试报告 CRUD 操作"""
    response = api_client.post(
        "/api/compliance/check/document",
        json={
            "document_content": "测试保险条款：保险期间为1年，等待期为90天。",
            "product_name": "CRUD测试产品",
        }
    )
    assert response.status_code == 200
    report_id = response.json()["id"]

    get_response = api_client.get(f"/api/compliance/reports/{report_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == report_id

    list_response = api_client.get("/api/compliance/reports")
    assert list_response.status_code == 200
    assert any(r["id"] == report_id for r in list_response.json())

    delete_response = api_client.delete(f"/api/compliance/reports/{report_id}")
    assert delete_response.status_code == 200

    get_deleted = api_client.get(f"/api/compliance/reports/{report_id}")
    assert get_deleted.status_code == 404
