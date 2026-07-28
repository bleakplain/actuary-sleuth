"""为无状态文档解析结果签发短时、不可伪造的审核凭证。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from lib.auth.jwt import get_jwt_signing_secret

_DOMAIN = b"actuary-sleuth/parse-attestation/v1"
_DEFAULT_TTL_SECONDS = 30 * 60


class ParseAttestationError(ValueError):
    """解析凭证缺失、损坏、过期或与请求身份不一致。"""


@dataclass(frozen=True)
class IssuedParseAttestation:
    token: str
    expires_at: str


def _signing_key() -> bytes:
    return hmac.new(
        get_jwt_signing_secret(),
        _DOMAIN,
        hashlib.sha256,
    ).digest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise ParseAttestationError("解析凭证编码无效") from exc


def _warnings_digest(parse_warnings: Sequence[str]) -> str:
    canonical = json.dumps(
        list(parse_warnings),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def issue_parse_attestation(
    parse_id: str,
    document_fingerprint: str,
    audit_input_fingerprint: str,
    product_name_source: str,
    parse_warnings: Sequence[str] = (),
    user_subject: str = "",
    *,
    now: Optional[int] = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> IssuedParseAttestation:
    """签发绑定解析身份、内容身份、名称身份和用户主体的短时凭证。"""
    issued_at = int(time.time()) if now is None else int(now)
    expires_epoch = issued_at + max(int(ttl_seconds), 1)
    payload = {
        "v": 1,
        "iat": issued_at,
        "exp": expires_epoch,
        "parse_id": parse_id,
        "document_fingerprint": document_fingerprint,
        "audit_input_fingerprint": audit_input_fingerprint,
        "product_name_source": product_name_source,
        "parse_warnings_sha256": _warnings_digest(parse_warnings),
        "sub": user_subject,
    }
    encoded_payload = _encode(json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8"))
    signature = hmac.new(
        _signing_key(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    expires_at = datetime.fromtimestamp(
        expires_epoch,
        timezone.utc,
    ).isoformat()
    return IssuedParseAttestation(
        token=f"{encoded_payload}.{_encode(signature)}",
        expires_at=expires_at,
    )


def verify_parse_attestation(
    token: str,
    parse_id: str,
    document_fingerprint: str,
    audit_input_fingerprint: str,
    product_name_source: str,
    parse_warnings: Sequence[str] = (),
    user_subject: str = "",
    *,
    now: Optional[int] = None,
) -> None:
    """验证签名、有效期以及审核请求与原始解析快照的全部绑定字段。"""
    if not token:
        raise ParseAttestationError("缺少解析凭证")
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
    except ValueError as exc:
        raise ParseAttestationError("解析凭证格式无效") from exc
    expected_signature = hmac.new(
        _signing_key(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_decode(encoded_signature), expected_signature):
        raise ParseAttestationError("解析凭证签名无效")
    try:
        payload: Any = json.loads(_decode(encoded_payload))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ParseAttestationError("解析凭证载荷无效") from exc
    if not isinstance(payload, Mapping) or payload.get("v") != 1:
        raise ParseAttestationError("解析凭证版本无效")
    current_time = int(time.time()) if now is None else int(now)
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or current_time >= expires_at:
        raise ParseAttestationError("解析凭证已过期，请重新解析")
    expected = {
        "parse_id": parse_id,
        "document_fingerprint": document_fingerprint,
        "audit_input_fingerprint": audit_input_fingerprint,
        "product_name_source": product_name_source,
        "parse_warnings_sha256": _warnings_digest(parse_warnings),
        "sub": user_subject,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ParseAttestationError("解析凭证与审核输入身份不一致，请重新解析")
