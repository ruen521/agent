from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.reports import store
from app.reports.schemas import ExportRequest
from app.reports.service import execute_export_job


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report export worker")
    parser.add_argument("--job-id", required=True, help="Export job id")
    parser.add_argument("--request-file", required=True, help="Path to serialized ExportRequest JSON")
    return parser.parse_args()


def _load_request(path: Path) -> ExportRequest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExportRequest.model_validate(payload)


def main() -> None:
    args = _parse_args()
    request_path = Path(args.request_file)
    try:
        req = _load_request(request_path)
    except Exception as exc:
        store.update_job(
            args.job_id,
            status="FAILED",
            progress=100,
            error_message=f"导出任务参数异常：{str(exc)[:200]}",
        )
        return
    finally:
        try:
            request_path.unlink(missing_ok=True)
        except Exception:
            pass

    execute_export_job(args.job_id, req)
    record = store.get_job(args.job_id)
    if (
        record
        and record.status == "FAILED"
        and record.error_message
        and "依赖缺失" in record.error_message
    ):
        store.update_job(
            args.job_id,
            error_message=f"{record.error_message}（worker={sys.executable}）",
        )


if __name__ == "__main__":
    main()
