from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.settings import settings
from app.core.alerts import alerts
from app.core.metrics import metrics
from app.core.progress import progress_broker

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

        progress_broker.publish(
            {
                "phase": "llm",
                "text": f"正在调用 LLM（{self.model}）",
                "tool": "llm",
                "member_status": "running",
            }
        )

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.api_url}/chat/completions"

        try:
            with httpx.Client(timeout=60) as client:  # 增加到 60 秒
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.TimeoutException as exc:
            logger.error("qingyun_timeout", extra={"timeout": 60})
            metrics.observe_llm(success=False)
            _maybe_alert_llm_failure()
            progress_broker.publish(
                {
                    "phase": "llm",
                    "text": "LLM 请求超时",
                    "tool": "llm",
                    "member_status": "failed",
                }
            )
            raise RuntimeError(f"Qingyun request timeout after 60s") from exc
        except httpx.HTTPStatusError as exc:
            logger.error("qingyun_http_error", extra={"status": exc.response.status_code})
            metrics.observe_llm(success=False)
            _maybe_alert_llm_failure()
            progress_broker.publish(
                {
                    "phase": "llm",
                    "text": f"LLM HTTP 错误：{exc.response.status_code}",
                    "tool": "llm",
                    "member_status": "failed",
                }
            )
            raise RuntimeError(f"Qingyun HTTP error: {exc.response.status_code}") from exc
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("qingyun_request_failed", extra={"error_code": type(exc).__name__})
            metrics.observe_llm(success=False)
            _maybe_alert_llm_failure()
            progress_broker.publish(
                {
                    "phase": "llm",
                    "text": f"LLM 调用失败：{type(exc).__name__}",
                    "tool": "llm",
                    "member_status": "failed",
                }
            )
            raise RuntimeError(f"Qingyun request failed: {exc}") from exc

        try:
            choices = data.get("choices") or []
            if not isinstance(choices, list) or not choices:
                raise RuntimeError("Qingyun response missing choices")
            choice0 = choices[0] if isinstance(choices[0], dict) else {}
            message = choice0.get("message") if isinstance(choice0, dict) else {}
            if not isinstance(message, dict):
                message = {}

            finish_reason = str(choice0.get("finish_reason") or "").strip()
            response_id = str(data.get("id") or "").strip()
            refusal = str(message.get("refusal") or "").strip()
            content = _extract_message_content(message)
            raw_content = message.get("content")

            logger.info(
                "qingyun_response_meta",
                extra={
                    "finish_reason": finish_reason,
                    "content_len": len(content),
                    "has_refusal": bool(refusal),
                    "response_id": response_id,
                    "message_keys": list(message.keys()),
                    "content_type": type(raw_content).__name__,
                    "status": 200,
                },
            )

            if content:
                metrics.observe_llm(success=True)
                progress_broker.publish(
                    {
                        "phase": "llm",
                        "text": "LLM 已返回结果",
                        "tool": "llm",
                        "member_status": "success",
                    }
                )
                return content

            metrics.observe_llm(success=False)
            _maybe_alert_llm_failure()
            if refusal:
                raise RuntimeError(
                    f"Qingyun refusal: {refusal}; finish_reason={finish_reason or '-'}; response_id={response_id or '-'}"
                )
            logger.error(
                "qingyun_empty_content",
                extra={
                    "finish_reason": finish_reason,
                    "response_id": response_id,
                    "message_keys": list(message.keys()),
                    "content_type": type(raw_content).__name__,
                    "content_preview": str(raw_content)[:300],
                    "status": 200,
                },
            )
            raise RuntimeError(
                f"Qingyun returned empty content; finish_reason={finish_reason or '-'}; response_id={response_id or '-'}"
            )
        except RuntimeError:
            raise
        except Exception as exc:
            metrics.observe_llm(success=False)
            _maybe_alert_llm_failure()
            raise RuntimeError(f"Qingyun response parsing failed: {type(exc).__name__}: {str(exc)}") from exc


def _extract_message_content(message: dict[str, Any]) -> str:
    return _extract_text_value(message.get("content"))


def _extract_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_extract_text_value(item) for item in value]
        text = "\n".join(part for part in parts if part)
        return text.strip()
    if isinstance(value, dict):
        # Common provider payloads: text/value/output_text/content/parts
        for key in ("text", "value", "output_text"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        for key in ("content", "parts"):
            nested = _extract_text_value(value.get(key))
            if nested:
                return nested
    return ""


def _maybe_alert_llm_failure() -> None:
    if metrics.llm_error_rate_exceeded(
        threshold=settings.alert_llm_error_rate,
        min_requests=settings.alert_llm_min_requests,
    ):
        error_rate, sample_size = metrics.current_llm_error_rate()
        alerts.send_llm_error_rate_alert(
            llm_error_rate=error_rate,
            threshold=settings.alert_llm_error_rate,
            sample_size=sample_size,
        )
