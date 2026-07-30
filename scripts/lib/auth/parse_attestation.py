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

_V1_DOMAIN = b"actuary-sleuth/parse-attestation/v1"
_V2_DOMAIN = b"actuary-sleuth/parse-attestation/v2"
_DEFAULT_TTL_SECONDS = 30 * 60


class ParseAttestationError(ValueError):
    """解析凭证缺失、损坏、过期或与请求身份不一致。"""


@dataclass(frozen=True)
class IssuedParseAttestation:
    token: str
    expires_at: str


@dataclass(frozen=True)
class VerifiedParseAttestation:
    version: int
    coverage_attested: bool


def _signing_key(domain: bytes = _V2_DOMAIN) -> bytes:
    return hmac.new(
        get_jwt_signing_secret(),
        domain,
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
    coverage_attested: bool = False,
    now: Optional[int] = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> IssuedParseAttestation:
    """签发绑定解析身份、原文覆盖证明和用户主体的短时凭证。"""
    issued_at = int(time.time()) if now is None else int(now)
    expires_epoch = issued_at + max(int(ttl_seconds), 1)
    payload = {
        "v": 2,
        "iat": issued_at,
        "exp": expires_epoch,
        "parse_id": parse_id,
        "document_fingerprint": document_fingerprint,
        "audit_input_fingerprint": audit_input_fingerprint,
        "product_name_source": product_name_source,
        "coverage_attested": coverage_attested,
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
    coverage_attested: bool = False,
    now: Optional[int] = None,
) -> VerifiedParseAttestation:
    """验证解析凭证，并把旧版凭证降级为不具备全文覆盖证明。

    v1 兼容只覆盖其原始最长 30 分钟有效期。它没有绑定
    ``coverage_attested``，因此即使请求声称完整覆盖，也只能返回 False，
    禁止下游据此做“全文未出现某词”的负向推断。
    """
    if not token:
        raise ParseAttestationError("缺少解析凭证")
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
    except ValueError as exc:
        raise ParseAttestationError("解析凭证格式无效") from exc
    try:
        payload: Any = json.loads(_decode(encoded_payload))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ParseAttestationError("解析凭证载荷无效") from exc
    if not isinstance(payload, Mapping) or payload.get("v") not in (1, 2):
        raise ParseAttestationError("解析凭证版本无效")
    version = int(payload["v"])
    domain = _V2_DOMAIN if version == 2 else _V1_DOMAIN
    expected_signature = hmac.new(
        _signing_key(domain),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_decode(encoded_signature), expected_signature):
        raise ParseAttestationError("解析凭证签名无效")
    current_time = int(time.time()) if now is None else int(now)
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or current_time >= expires_at:
        raise ParseAttestationError("解析凭证已过期，请重新解析")
    if (
        version == 1
        and (
            not isinstance(issued_at, int)
            or expires_at - issued_at > _DEFAULT_TTL_SECONDS
        )
    ):
        raise ParseAttestationError("旧版解析凭证兼容窗口无效，请重新解析")
    expected: dict[str, object] = {
        "parse_id": parse_id,
        "document_fingerprint": document_fingerprint,
        "audit_input_fingerprint": audit_input_fingerprint,
        "product_name_source": product_name_source,
        "parse_warnings_sha256": _warnings_digest(parse_warnings),
        "sub": user_subject,
    }
    if version == 2:
        expected["coverage_attested"] = coverage_attested
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ParseAttestationError("解析凭证与审核输入身份不一致，请重新解析")
    return VerifiedParseAttestation(
        version=version,
        coverage_attested=(
            bool(payload.get("coverage_attested")) if version == 2 else False
        ),
    )
