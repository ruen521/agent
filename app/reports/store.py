from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.reports.schemas import ExportJobRecord

_LOCK = Lock()
_BASE_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"
_FILES_DIR = _BASE_DIR / "files"
_JOBS_PATH = _BASE_DIR / "jobs.json"


def files_dir() -> Path:
    _FILES_DIR.mkdir(parents=True, exist_ok=True)
    return _FILES_DIR


def jobs_path() -> Path:
    _JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _JOBS_PATH


def _load_raw_jobs() -> dict[str, dict[str, Any]]:
    path = jobs_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _save_raw_jobs(payload: dict[str, dict[str, Any]]) -> None:
    jobs_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def upsert_job(job: ExportJobRecord) -> None:
    with _LOCK:
        payload = _load_raw_jobs()
        payload[job.job_id] = job.model_dump(mode="json")
        _save_raw_jobs(payload)


def get_job(job_id: str) -> ExportJobRecord | None:
    with _LOCK:
        payload = _load_raw_jobs()
        item = payload.get(job_id)
        if not isinstance(item, dict):
            return None
        try:
            return ExportJobRecord.model_validate(item)
        except Exception:
            return None


def update_job(job_id: str, **updates: Any) -> ExportJobRecord | None:
    with _LOCK:
        payload = _load_raw_jobs()
        item = payload.get(job_id)
        if not isinstance(item, dict):
            return None
        merged = dict(item)
        merged.update(updates)
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            record = ExportJobRecord.model_validate(merged)
        except Exception:
            return None
        payload[job_id] = record.model_dump(mode="json")
        _save_raw_jobs(payload)
        return record


def list_jobs() -> list[ExportJobRecord]:
    with _LOCK:
        payload = _load_raw_jobs()
    jobs: list[ExportJobRecord] = []
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        try:
            jobs.append(ExportJobRecord.model_validate(item))
        except Exception:
            continue
    return jobs


def remove_jobs(job_ids: list[str]) -> None:
    if not job_ids:
        return
    with _LOCK:
        payload = _load_raw_jobs()
        for job_id in job_ids:
            payload.pop(job_id, None)
        _save_raw_jobs(payload)

