from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from threading import Lock
from typing import Deque

from app.core.settings import settings

_MAX_MESSAGES = max(1, settings.session_max_messages)
_sessions: dict[str, Deque[dict[str, str]]] = {}
_loaded = False
_lock = Lock()


def _store_path() -> Path:
    return Path(__file__).resolve().parents[2] / settings.session_store_path


def _load_if_needed() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        path = _store_path()
        if not path.exists():
            _loaded = True
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for sid, messages in raw.items():
                    if isinstance(sid, str) and isinstance(messages, list):
                        _sessions[sid] = deque(messages[-_MAX_MESSAGES:], maxlen=_MAX_MESSAGES)
        except Exception:
            _sessions.clear()
        _loaded = True


def _flush() -> None:
    with _lock:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {sid: list(messages) for sid, messages in _sessions.items()}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_session_messages(session_id: str) -> list[dict[str, str]]:
    _load_if_needed()
    return list(_sessions.get(session_id, deque()))


def append_session_messages(session_id: str, new_messages: list[dict[str, str]]) -> None:
    _load_if_needed()
    history = _sessions.setdefault(session_id, deque(maxlen=_MAX_MESSAGES))
    for message in new_messages:
        history.append(message)
    _flush()
