from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from api.routers.compliance import parse_file, parse_rich_text
from api.schemas.compliance import RichTextParseRequest
from lib.common.constants import ComplianceConstants


@pytest.mark.asyncio
async def test_parse_file_rejects_payload_over_controlled_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ComplianceConstants, "MAX_PRODUCT_DOCUMENT_BYTES", 4)
    upload = UploadFile(filename="test.pdf", file=BytesIO(b"12345"))

    with pytest.raises(HTTPException) as exc_info:
        await parse_file(upload, user={"user_id": "test"})

    assert exc_info.value.status_code == 413
    await upload.close()


@pytest.mark.asyncio
async def test_parse_rich_text_rejects_payload_over_controlled_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ComplianceConstants, "MAX_RICH_TEXT_CHARACTERS", 4)

    with pytest.raises(HTTPException) as exc_info:
        await parse_rich_text(
            RichTextParseRequest(html_content="12345"),
            user={"user_id": "test"},
        )

    assert exc_info.value.status_code == 413
