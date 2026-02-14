from __future__ import annotations

import json
from pathlib import Path

from app.agents import memory


def test_session_memory_persists_to_disk(tmp_path: Path) -> None:
    store = tmp_path / "session_memory.json"

    original_store_path = memory._store_path
    original_sessions = dict(memory._sessions)
    original_loaded = memory._loaded
    try:
        memory._sessions.clear()
        memory._loaded = False
        memory._store_path = lambda: store

        memory.append_session_messages("s-1", [{"role": "user", "content": "hello"}])
        assert store.exists()

        raw = json.loads(store.read_text(encoding="utf-8"))
        assert "s-1" in raw
        assert raw["s-1"][0]["content"] == "hello"

        memory._sessions.clear()
        memory._loaded = False
        messages = memory.get_session_messages("s-1")
        assert len(messages) == 1
        assert messages[0]["content"] == "hello"
    finally:
        memory._store_path = original_store_path
        memory._sessions.clear()
        for key, value in original_sessions.items():
            memory._sessions[key] = value
        memory._loaded = original_loaded

