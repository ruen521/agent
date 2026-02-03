from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.settings import settings
from app.spapi.constants import MARKETPLACE_IDS, REGION_AWS, REGION_ENDPOINTS
from app.spapi.rate_limit import TokenBucket
from app.spapi.signing import sign_request

logger = logging.getLogger("app.spapi")


class SpApiClient:
    def __init__(self) -> None:
        self.refresh_token = settings.spapi_refresh_token
        self.client_id = settings.lwa_client_id
        self.client_secret = settings.lwa_client_secret
        self.aws_access_key = settings.spapi_access_key
        self.aws_secret_key = settings.spapi_secret_key
        self.role_arn = settings.aws_role_arn
        self.region = settings.spapi_region
        self.use_sandbox = settings.spapi_use_sandbox
        self.marketplace_id = settings.spapi_marketplace_id

        self._token_cache: dict[str, Any] = {}
        self._bucket = TokenBucket(capacity=10, refill_rate_per_sec=1.0)

    @property
    def endpoint(self) -> str:
        key = f"{self.region}_sandbox" if self.use_sandbox else self.region
        return REGION_ENDPOINTS.get(key, REGION_ENDPOINTS["na"])

    def _marketplace(self) -> str:
        if not self.marketplace_id:
            return MARKETPLACE_IDS.get("us", "ATVPDKIKX0DER")
        return MARKETPLACE_IDS.get(self.marketplace_id, self.marketplace_id)

    def _can_call_spapi(self) -> bool:
        return all(
            [
                self.refresh_token,
                self.client_id,
                self.client_secret,
                self.aws_access_key,
                self.aws_secret_key,
            ]
        )

    def _lwa_token(self) -> str:
        cached = self._token_cache.get("access_token")
        expiry = self._token_cache.get("expires_at")
        if cached and expiry and expiry > datetime.now(timezone.utc):
            return cached

        if not all([self.refresh_token, self.client_id, self.client_secret]):
            raise RuntimeError("Missing LWA credentials")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        response = httpx.post(
            "https://api.amazon.com/auth/o2/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_cache["access_token"] = access_token
        self._token_cache["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        return access_token

    def _signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._bucket.consume():
            time.sleep(0.25)

        if not all([self.aws_access_key, self.aws_secret_key]):
            raise RuntimeError("Missing AWS signing keys")

        url = f"{self.endpoint}{path}"
        body = json.dumps(payload) if payload else ""
        headers = {
            "content-type": "application/json",
            "x-amz-access-token": self._lwa_token(),
        }

        region = REGION_AWS.get(self.region, "us-east-1")
        signed_headers = sign_request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            body=body,
            region=region,
            access_key=self.aws_access_key,
            secret_key=self.aws_secret_key,
        )
        headers.update(signed_headers)

        backoff = 0.5
        last_exc: Exception | None = None
        with httpx.Client(timeout=20) as client:
            for _ in range(3):
                try:
                    response = client.request(
                        method, url, params=params, headers=headers, content=body
                    )
                    if response.status_code in {429, 503}:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    response.raise_for_status()
                    return response.json()
                except Exception as exc:  # pragma: no cover - network dependent
                    last_exc = exc
                    time.sleep(backoff)
                    backoff *= 2
        raise RuntimeError("SP-API request failed") from last_exc

    def get_inventory_summaries(self) -> dict[str, Any]:
        if not self._can_call_spapi():
            return self._mock_inventory()
        params = {
            "granularityType": "Marketplace",
            "granularityId": self._marketplace(),
            "marketplaceIds": self._marketplace(),
            "details": "true",
        }
        return self._signed_request("GET", "/fba/inventory/v1/summaries", params=params)

    def get_orders(self) -> dict[str, Any]:
        if not self._can_call_spapi():
            return {"orders": []}
        params = {
            "MarketplaceIds": self._marketplace(),
        }
        return self._signed_request("GET", "/orders/v0/orders", params=params)

    def get_catalog_items(self, asin: str) -> dict[str, Any]:
        if not self._can_call_spapi():
            return {"asin": asin, "attributes": {"title": "Mock Catalog Item"}}
        params = {"marketplaceIds": self._marketplace()}
        return self._signed_request("GET", f"/catalog/2022-04-01/items/{asin}", params=params)

    def health_check(self) -> dict[str, Any]:
        if not self._can_call_spapi():
            return {"status": "mock", "message": "SP-API credentials missing"}
        try:
            _ = self._lwa_token()
            return {"status": "ok"}
        except Exception as exc:
            logger.error("spapi_health_failed", extra={"error_code": type(exc).__name__})
            return {"status": "error", "message": str(exc)}

    def _mock_inventory(self) -> dict[str, Any]:
        try:
            from pathlib import Path

            path = Path(__file__).resolve().parents[2] / "data" / "mock_inventory.json"
            if path.exists():
                items = json.loads(path.read_text(encoding="utf-8"))
                summaries = [
                    {
                        "sellerSku": item["SKU"],
                        "productName": item["Name"],
                        "totalQuantity": item["CurrentStock"],
                        "asin": item.get("ASIN", ""),
                        "condition": "New",
                        "inventoryDetails": {
                            "fulfillableQuantity": item["CurrentStock"],
                            "reservedQuantity": 0,
                            "unfulfillableQuantity": 0,
                            "inboundQuantity": 0,
                        },
                    }
                    for item in items
                ]
                return {"payload": {"inventory_summaries": summaries}}
        except Exception:
            return {"payload": {"inventory_summaries": []}}
        return {"payload": {"inventory_summaries": []}}
