from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, Iterator, List

import pytest

from api.routers import compliance
from api.schemas.compliance import DocumentCheckRequest


def _request() -> DocumentCheckRequest:
    return DocumentCheckRequest(
        document_content="第一条 等待期\n等待期为30日。",
        product_name="测试短期医疗保险",
        category="健康险",
        clause_topics=["coverage.waiting_period"],
    )


def _empty_stream(*args: Any) -> Iterator[Dict[str, Any]]:
    return iter(())


async def _event_payloads(response: Any) -> List[Dict[str, Any]]:
    payloads = []
    body: AsyncIterator[Dict[str, Any]] = response.body_iterator
    async for event in body:
        payloads.append(json.loads(event["data"]))
    return payloads


@pytest.fixture()
def isolated_stream(monkeypatch: pytest.MonkeyPatch) -> List[tuple]:
    saved: List[tuple] = []
    monkeypatch.setattr(
        compliance,
        "retrieve_audit_regulations_with_status",
        lambda *args: SimpleNamespace(regulations=(), warnings=(), degraded=False),
    )
    monkeypatch.setattr(compliance, "streaming_negative_check", _empty_stream)
    monkeypatch.setattr(
        compliance,
        "save_compliance_report",
        lambda *args: saved.append(args),
    )
    return saved


@pytest.mark.asyncio
async def test_producer_exception_persists_incomplete_report_and_emits_only_done(
    monkeypatch: pytest.MonkeyPatch,
    isolated_stream: List[tuple],
) -> None:
    def exploding_stream(*args: Any) -> Iterator[Dict[str, Any]]:
        raise RuntimeError("模型连接中断")
        yield  # pragma: no cover

    monkeypatch.setattr(compliance, "streaming_compliance_check", exploding_stream)

    response = await compliance.check_document_stream(_request(), user={})
    payloads = await _event_payloads(response)

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert [item["type"] for item in terminal] == ["done"]
    done = terminal[0]["data"]
    assert done["audit_status"] == "incomplete"
    assert done["compliance_conclusion"] == "undetermined"
    assert done["failed_count"] == 1
    assert done["failure_reasons"] == ["审核流异常：模型连接中断"]
    assert len(isolated_stream) == 1
    persisted = isolated_stream[0][4]
    assert persisted["audit_status"] == "incomplete"
    assert persisted["compliance_conclusion"] == "undetermined"
    assert persisted["failure_reasons"] == done["failure_reasons"]


@pytest.mark.asyncio
async def test_stream_error_event_is_absorbed_into_single_done_terminal(
    monkeypatch: pytest.MonkeyPatch,
    isolated_stream: List[tuple],
) -> None:
    def failed_stream(*args: Any) -> Iterator[Dict[str, Any]]:
        yield {"type": "error", "data": "法规审核超时"}

    monkeypatch.setattr(compliance, "streaming_compliance_check", failed_stream)

    response = await compliance.check_document_stream(_request(), user={})
    payloads = await _event_payloads(response)

    assert [item["type"] for item in payloads if item["type"] in {"done", "error"}] == [
        "done"
    ]
    done = next(item["data"] for item in payloads if item["type"] == "done")
    assert done["audit_status"] == "incomplete"
    assert done["failure_reasons"] == ["法规审核超时"]
    assert len(isolated_stream) == 1


@pytest.mark.asyncio
async def test_known_stream_failure_progress_marks_report_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    isolated_stream: List[tuple],
) -> None:
    def failed_batch(*args: Any) -> Iterator[Dict[str, Any]]:
        yield {"type": "progress", "data": "⚠ 法规审查批次 1/1 失败"}

    monkeypatch.setattr(compliance, "streaming_compliance_check", failed_batch)

    response = await compliance.check_document_stream(_request(), user={})
    payloads = await _event_payloads(response)

    progress = [item for item in payloads if item["type"] == "progress"]
    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert progress == [{"type": "progress", "data": "⚠ 法规审查批次 1/1 失败"}]
    assert [item["type"] for item in terminal] == ["done"]
    assert terminal[0]["data"]["audit_status"] == "incomplete"
    assert terminal[0]["data"]["failure_reasons"] == [
        "⚠ 法规审查批次 1/1 失败"
    ]
    assert len(isolated_stream) == 1


@pytest.mark.asyncio
async def test_persistence_failure_emits_only_error_and_never_done(
    monkeypatch: pytest.MonkeyPatch,
    isolated_stream: List[tuple],
) -> None:
    monkeypatch.setattr(compliance, "streaming_compliance_check", _empty_stream)

    def fail_save(*args: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(compliance, "save_compliance_report", fail_save)

    response = await compliance.check_document_stream(_request(), user={})
    payloads = await _event_payloads(response)

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert terminal == [
        {
            "type": "error",
            "data": "报告保存失败，审核结果未持久化",
        }
    ]
    assert not any(item["type"] == "done" for item in payloads)
