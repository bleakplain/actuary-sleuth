"""保险产品文档合规审核端到端测试

使用流式 SSE 端点验证完整的文档解析 → 流式合规检查 → 结果输出流程。
"""
import json
import os
import pytest
import httpx
from pathlib import Path
from typing import NamedTuple, List, Dict, Any


class TestCase(NamedTuple):
    name: str
    file_path: str
    expected_category: str
    min_items: int
    check_negative_list: bool


TEST_CASES = [
    TestCase("互联网重大疾病保险",
             "《人保健康互联网重大疾病保险（A款）》条款V5 - 无修订.docx",
             "重疾险", 1, True),
    TestCase("互联网团体意外伤害保险",
             "《人保健康互联网团体意外伤害保险（2025版）》条款.pdf",
             "意外险", 1, True),
    TestCase("互联网手术医疗意外保险",
             "《人保健康互联网手术医疗意外保险》保险条款.pdf",
             "医疗险", 1, True),
    TestCase("互联网失能收入损失保险",
             "《人保健康互联网失能收入损失保险（2025版）》条款.docx",
             "寿险", 1, True),
    TestCase("附加互联网恶性肿瘤特定药品费用医疗保险",
             "《人保健康附加互联网恶性肿瘤特定药品费用医疗保险》条款.pdf",
             "医疗险", 1, True),
    TestCase("团体短期重大疾病保险",
             "《人保健康团体短期重大疾病保险（推荐版）》条款.docx",
             "重疾险", 1, True),
    TestCase("附加团体终身重度恶性肿瘤疾病保险",
             "《人保健康附加团体终身重度恶性肿瘤疾病保险》条款.docx",
             "重疾险", 1, True),
    TestCase("企业员工团体终身重大疾病保险",
             "《人保健康企业员工团体终身重大疾病保险（H款）》条款.docx",
             "重疾险", 1, True),
    TestCase("城市定制型团体医疗保险",
             "《人保健康城市定制型团体医疗保险（A款）》产品条款.docx",
             "医疗险", 1, True),
    TestCase("附加出境人员团体意外医疗保险",
             "《人保健康附加出境人员团体意外医疗保险》条款v2-无标记.docx",
             "意外险", 1, True),
]

PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def api_client():
    with httpx.Client(base_url=API_BASE_URL, timeout=600.0) as client:
        yield client


def _consume_stream(client: httpx.Client, payload: Dict) -> Dict[str, Any]:
    """POST to streaming endpoint, parse SSE events, return done data."""
    violations: List[Dict] = []
    done_data: Dict[str, Any] = {}
    with client.stream("POST", "/api/compliance/check/document/stream", json=payload) as resp:
        assert resp.status_code == 200
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                    if data.get("type") == "violation":
                        violations.append(data["data"])
                    elif data.get("type") == "done":
                        done_data = data["data"]
                except json.JSONDecodeError:
                    pass
    done_data["violations"] = violations
    return done_data


@pytest.mark.parametrize("test_case", TEST_CASES, ids=[tc.name for tc in TEST_CASES])
def test_compliance_check_e2e(test_case: TestCase, api_client: httpx.Client):
    file_path = PRODUCTS_DIR / test_case.file_path
    assert file_path.exists(), f"文件不存在: {file_path}"

    with open(file_path, "rb") as f:
        parse_response = api_client.post("/api/compliance/parse-file", files={"file": (file_path.name, f)})

    assert parse_response.status_code == 200
    parse_result = parse_response.json()
    assert "combined_text" in parse_result
    assert len(parse_result["combined_text"]) > 100

    result = _consume_stream(api_client, {
        "document_content": parse_result["combined_text"],
        "product_name": test_case.name,
    })

    assert "summary" in result
    assert result["summary"]["non_compliant"] >= test_case.min_items

    if test_case.check_negative_list:
        assert result.get("negative_list_result") in ("passed", "violated", "skipped")

    assert "regulation_sources" in result
    sources = result["regulation_sources"]
    assert "通用法规" in sources and len(sources["通用法规"]) > 0

    assert result.get("report_id"), "Missing report_id in done event"


def test_category_identification(api_client: httpx.Client):
    test_cases = [
        ("重大疾病保险条款", "重疾险"),
        ("意外伤害保险条款", "意外险"),
        ("住院医疗保险条款", "医疗险"),
    ]
    for content, expected_category in test_cases:
        response = api_client.post(
            "/api/compliance/parse-rich-text",
            json={"html_content": f"<p>{content}</p>"}
        )
        assert response.status_code == 200
        result = response.json()
        if result.get("identified_category") and result.get("category_confidence", 0) > 0.5:
            assert result["identified_category"] == expected_category


def test_report_crud(api_client: httpx.Client):
    result = _consume_stream(api_client, {
        "document_content": "测试保险条款：保险期间为1年，等待期为90天。",
        "product_name": "CRUD测试产品",
    })
    report_id = result["report_id"]

    get_response = api_client.get(f"/api/compliance/reports/{report_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == report_id

    list_response = api_client.get("/api/compliance/reports")
    assert list_response.status_code == 200
    assert any(r["id"] == report_id for r in list_response.json())

    delete_response = api_client.delete(f"/api/compliance/reports/{report_id}")
    assert delete_response.status_code == 200

    assert api_client.get(f"/api/compliance/reports/{report_id}").status_code == 404
