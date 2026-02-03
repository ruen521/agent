from __future__ import annotations

from collections import deque
from typing import Deque

_MAX_MESSAGES = 20
_sessions: dict[str, Deque[dict[str, str]]] = {}


def get_session_messages(session_id: str) -> list[dict[str, str]]:
    return list(_sessions.get(session_id, deque()))


def append_session_messages(session_id: str, new_messages: list[dict[str, str]]) -> None:
    history = _sessions.setdefault(session_id, deque(maxlen=_MAX_MESSAGES))
    for message in new_messages:
        history.append(message)
