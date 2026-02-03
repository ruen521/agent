from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.context import agent_ctx, request_id_ctx, trace_id_ctx
from app.core.metrics import metrics
from app.core.settings import settings


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        trace_header = request.headers.get("x-trace-id") or request.headers.get("traceparent")
        trace_token = trace_id_ctx.set(trace_header or request_id)
        response: Response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-trace-id"] = trace_id_ctx.get() or request_id
        request_id_ctx.reset(token)
        trace_id_ctx.reset(trace_token)
        return response


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if settings.api_key:
            header_key = request.headers.get("x-api-key")
            auth_header = request.headers.get("authorization") or ""
            bearer = auth_header.replace("Bearer", "").strip() if auth_header else ""
            if header_key != settings.api_key and bearer != settings.api_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Invalid API key",
                            "request_id": getattr(request.state, "request_id", ""),
                        },
                    },
                )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, Deque[float]] = {}

    async def dispatch(self, request: Request, call_next):
        limit = settings.rate_limit_per_minute
        if limit > 0:
            key = request.client.host if request.client else "global"
            now = time.time()
            window_start = now - 60
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] < window_start:
                bucket.popleft()
            if len(bucket) >= limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many requests",
                            "request_id": getattr(request.state, "request_id", ""),
                        },
                    },
                )
            bucket.append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception as exc:  # pragma: no cover - handled by exception handlers
            duration = (time.perf_counter() - start) * 1000
            request.app.logger.error(
                "request_failed",
                extra={
                    "latency_ms": round(duration, 2),
                    "status": 500,
                    "error_code": type(exc).__name__,
                },
            )
            raise
        finally:
            agent_ctx.set(None)

        duration = (time.perf_counter() - start) * 1000
        metrics.observe_request(response.status_code, round(duration, 2))
        if metrics.error_rate_exceeded(
            threshold=settings.alert_error_rate, min_requests=settings.alert_min_requests
        ):
            request.app.logger.error(
                "alert_error_rate_high",
                extra={
                    "status": response.status_code,
                    "error_code": "ERROR_RATE_HIGH",
                    "latency_ms": round(duration, 2),
                },
            )
        request.app.logger.info(
            "request_complete",
            extra={
                "latency_ms": round(duration, 2),
                "status": response.status_code,
            },
        )
        return response
