from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.core.settings import settings

logger = logging.getLogger("app.alerts")


class AlertManager:
    def __init__(self) -> None:
        self._last_sent: dict[str, float] = {}

    def _should_send(self, key: str) -> bool:
        now = time.time()
        last = self._last_sent.get(key, 0.0)
        if now - last < max(0, settings.alert_cooldown_seconds):
            return False
        self._last_sent[key] = now
        return True

    def send(self, key: str, payload: dict[str, Any]) -> None:
        if not settings.alert_webhook_url:
            logger.warning("alert_skipped", extra={"error_code": "ALERT_WEBHOOK_MISSING"})
            return
        if not self._should_send(key):
            return

        try:
            with httpx.Client(timeout=5) as client:
                client.post(
                    settings.alert_webhook_url,
                    json={
                        "source": "inventory-system",
                        "alert_key": key,
                        "payload": payload,
                    },
                )
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("alert_send_failed", extra={"error_code": type(exc).__name__})

    def send_error_rate_alert(self, error_rate: float, threshold: float, sample_size: int) -> None:
        self.send(
            "http_error_rate_high",
            {
                "kind": "http_error_rate_high",
                "error_rate": round(error_rate, 4),
                "threshold": threshold,
                "sample_size": sample_size,
            },
        )

    def send_llm_error_rate_alert(self, llm_error_rate: float, threshold: float, sample_size: int) -> None:
        self.send(
            "llm_error_rate_high",
            {
                "kind": "llm_error_rate_high",
                "llm_error_rate": round(llm_error_rate, 4),
                "threshold": threshold,
                "sample_size": sample_size,
            },
        )


alerts = AlertManager()

