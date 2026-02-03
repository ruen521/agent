from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlparse


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _hash_payload(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_query(params: dict[str, str]) -> str:
    if not params:
        return ""
    return urlencode(sorted(params.items()), quote_via=quote, safe="-_.~")


def _canonical_headers(headers: dict[str, str]) -> tuple[str, str]:
    sorted_items = sorted((k.lower().strip(), " ".join(v.strip().split())) for k, v in headers.items())
    header_lines = [f"{k}:{v}" for k, v in sorted_items]
    signed_headers = ";".join(k for k, _ in sorted_items)
    return "\n".join(header_lines) + "\n", signed_headers


def _canonical_request(
    method: str,
    path: str,
    query: dict[str, str],
    headers: dict[str, str],
    payload_hash: str,
) -> str:
    canonical_headers, signed_headers = _canonical_headers(headers)
    canonical_query = _canonical_query(query)
    return "\n".join(
        [
            method.upper(),
            path or "/",
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )


def _credential_scope(date_stamp: str, region: str, service: str) -> str:
    return f"{date_stamp}/{region}/{service}/aws4_request"


def _string_to_sign(amz_date: str, scope: str, canonical_request: str) -> str:
    hashed = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    return "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashed])


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def sign_request(
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None,
    body: str,
    region: str,
    access_key: str,
    secret_key: str,
    service: str = "execute-api",
) -> dict[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    headers = {**headers, "host": host, "x-amz-date": amz_date}
    payload_hash = _hash_payload(body or "")

    canonical_request = _canonical_request(method, path, params or {}, headers, payload_hash)
    scope = _credential_scope(date_stamp, region, service)
    string_to_sign = _string_to_sign(amz_date, scope, canonical_request)
    signing_key = _signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    canonical_headers, signed_headers = _canonical_headers(headers)
    _ = canonical_headers  # keep for parity

    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    return {"Authorization": authorization, "x-amz-date": amz_date}
