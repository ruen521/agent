from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from experiments.reference_methods import run_backtest
from experiments.reference_methods.methods import TimePoint


@dataclass
class _FakeResult:
    rowcount: int = 1


class _FakeSession:
    def execute(self, statement, params=None):
        _ = (statement, params)
        return _FakeResult()


class _FakeDb:
    def __init__(self, database_url=None) -> None:
        self.database_url = database_url

    def ensure_tables(self) -> None:
        return None

    @contextmanager
    def session(self):
        yield _FakeSession()


def test_run_backtest_writes_expected_files(monkeypatch, tmp_path: Path, capsys) -> None:
    base = date(2025, 1, 1)
    series = [TimePoint(period_date=base + timedelta(days=i), value=float(100 + (i % 7))) for i in range(40)]
    grouped = {"ASIN-1": series}

    monkeypatch.setattr(run_backtest, "ExperimentDb", _FakeDb)
    monkeypatch.setattr(run_backtest, "_fetch_series", lambda db, target_metric: grouped)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_backtest.py",
            "--target-metric",
            "units",
            "--matrix",
            "full",
            "--output-dir",
            str(tmp_path),
            "--run-id",
            "ut_run",
        ],
    )

    run_backtest.main()
    summary = json.loads(capsys.readouterr().out)

    run_dir = tmp_path / "run_ut_run"
    assert run_dir.exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "method_metrics.csv").exists()
    assert (run_dir / "asin_method_metrics.csv").exists()
    assert (run_dir / "predictions.csv").exists()
    assert (run_dir / "实验报告.md").exists()

    assert summary["run_id"] == "ut_run"
    assert summary["dataset"]["asin_count"] == 1
    assert any(item["method_code"] == "M01" for item in summary["methods"])
    assert any(item["method_code"] == "M12" for item in summary["methods"])
