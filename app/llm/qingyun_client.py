from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.settings import settings
from app.core.metrics import metrics

logger = logging.getLogger("app.llm")


class QingyunChatClient:
    def __init__(self) -> None:
        self.api_url = settings.qingyun_api_url.rstrip("/")
        self.api_key = settings.qingyun_api_key
        self.model = settings.qingyun_model

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        if not self.api_key:
            metrics.observe_llm(success=False)
            raise RuntimeError("Qingyun API key missing")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.api_url}/v1/chat/completions"

        try:
            with httpx.Client(timeout=60) as client:  # 增加到 60 秒
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.TimeoutException as exc:
            logger.error("qingyun_timeout", extra={"timeout": 60})
            metrics.observe_llm(success=False)
            raise RuntimeError(f"Qingyun request timeout after 60s") from exc
        except httpx.HTTPStatusError as exc:
            logger.error("qingyun_http_error", extra={"status": exc.response.status_code})
            metrics.observe_llm(success=False)
            raise RuntimeError(f"Qingyun HTTP error: {exc.response.status_code}") from exc
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("qingyun_request_failed", extra={"error_code": type(exc).__name__})
            metrics.observe_llm(success=False)
            raise RuntimeError(f"Qingyun request failed: {exc}") from exc

        try:
            metrics.observe_llm(success=True)
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            metrics.observe_llm(success=False)
            raise RuntimeError("Qingyun response parsing failed") from exc
