from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.settings import settings

_lock = Lock()


def _path() -> Path:
    return Path(__file__).resolve().parents[2] / settings.agent_lifecycle_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default() -> dict[str, Any]:
    return {
        "version": 1,
        "agents": {},
    }


def _read() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return _default()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("agents"), dict):
            return payload
    except Exception:
        pass
    return _default()


def _write(payload: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_agent(agent_id: str) -> dict[str, Any]:
    with _lock:
        payload = _read()
        agents = payload["agents"]
        entry = agents.get(agent_id)
        if not isinstance(entry, dict):
            entry = {
                "prepared": False,
                "current_version": 0,
                "versions": [],
                "aliases": {},
                "updated": _now_iso(),
            }
            agents[agent_id] = entry
            _write(payload)
        return entry


def prepare_agent(agent_id: str, alias: str | None = None) -> dict[str, Any]:
    with _lock:
        payload = _read()
        agents = payload["agents"]
        entry = agents.get(agent_id)
        if not isinstance(entry, dict):
            entry = {
                "prepared": False,
                "current_version": 0,
                "versions": [],
                "aliases": {},
            }

        current_version = int(entry.get("current_version", 0)) + 1
        version_tag = f"v{current_version}"
        versions = entry.get("versions") or []
        versions.append({"version": version_tag, "prepared_at": _now_iso()})
        aliases = entry.get("aliases") or {}
        alias_name = alias or settings.agent_default_alias
        aliases[alias_name] = version_tag

        entry.update(
            {
                "prepared": True,
                "current_version": current_version,
                "versions": versions,
                "aliases": aliases,
                "updated": _now_iso(),
            }
        )
        agents[agent_id] = entry
        _write(payload)
        return entry


def get_agent_lifecycle(agent_id: str) -> dict[str, Any]:
    with _lock:
        payload = _read()
        agents = payload.get("agents", {})
        entry = agents.get(agent_id)
        if not isinstance(entry, dict):
            entry = {
                "prepared": False,
                "current_version": 0,
                "versions": [],
                "aliases": {},
                "updated": _now_iso(),
            }
            agents[agent_id] = entry
            payload["agents"] = agents
            _write(payload)
        return entry
