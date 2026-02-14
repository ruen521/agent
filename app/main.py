from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.logging import configure_logging
from app.core.middleware import (
    ApiKeyMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
)
from app.core.settings import settings

configure_logging()
app = FastAPI(title="Multi-Agent AI Inventory Management System", version="0.1.0")
app.logger = logging.getLogger("app")

app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        error_code = str(detail.get("error_code") or detail.get("code") or "HTTP_ERROR")
        error_message = str(detail.get("error_message") or detail.get("message") or "HTTP error")
    else:
        error_code = "HTTP_ERROR"
        error_message = str(detail)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": error_code,
            "error_message": error_message,
            "request_id": getattr(request.state, "request_id", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    app.logger.error(
        "unhandled_exception",
        extra={"status": 500, "error_code": type(exc).__name__},
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "error_message": f"{type(exc).__name__}: {str(exc)}",
            "request_id": getattr(request.state, "request_id", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    missing_agent = False
    missing_input = False
    for err in exc.errors():
        loc = err.get("loc", [])
        if "agent" in loc:
            missing_agent = True
        if "input" in loc:
            missing_input = True
    message = "Invalid request payload"
    if missing_agent or missing_input:
        message = "Missing required fields (agent, input)"

    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error_code": "BAD_REQUEST",
            "error_message": message,
            "request_id": getattr(request.state, "request_id", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
