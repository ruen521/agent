from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.core.context import request_id_ctx


class ProgressBroker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._events: dict[str, deque[dict[str, Any]]] = {}
        self._max_events = 500

    def open(self, request_id: str) -> None:
        rid = str(request_id or "").strip()
        if not rid:
            return
        with self._lock:
            self._events.setdefault(rid, deque(maxlen=self._max_events))

    def publish(self, payload: dict[str, Any], *, request_id: str | None = None) -> None:
        rid = str(request_id or request_id_ctx.get() or "").strip()
        if not rid:
            return
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(payload if isinstance(payload, dict) else {}),
        }
        with self._lock:
            bucket = self._events.setdefault(rid, deque(maxlen=self._max_events))
            bucket.append(event)

    def drain(self, request_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        rid = str(request_id or "").strip()
        if not rid:
            return []
        out: list[dict[str, Any]] = []
        with self._lock:
            bucket = self._events.get(rid)
            if not bucket:
                return []
            for _ in range(max(1, int(limit))):
                if not bucket:
                    break
                out.append(bucket.popleft())
        return out

    def close(self, request_id: str) -> None:
        rid = str(request_id or "").strip()
        if not rid:
            return
        with self._lock:
            self._events.pop(rid, None)


progress_broker = ProgressBroker()
