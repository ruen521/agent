from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from experiments.reference_methods.db import ExperimentDb
from experiments.reference_methods.method_registry import METHOD_REGISTRY, runnable_methods
from experiments.reference_methods.methods import TimePoint, compute_metrics, resample_series


@dataclass
class MethodMetricRow:
    method_code: str
    method_name: str
    scope: str
    sample_count: int
    mad: float
    poa: float
    mae: float
    wape: float
    bias: float
    runnable_asin_count: int
    not_applicable_asin_count: int
    coverage_rate: float


def _fetch_series(db: ExperimentDb, target_metric: str) -> dict[str, list[TimePoint]]:
    metric_col = {
        "units": "units",
        "orders_count": "orders_count",
        "amount": "amount",
    }.get(target_metric)
    if metric_col is None:
        raise ValueError(f"unsupported target metric: {target_metric}")

    sql = text(
        f"""
        SELECT s.as_of_date AS as_of_date, s.asin AS asin, s.{metric_col} AS metric
        FROM experiment_sales_daily s
        INNER JOIN (
          SELECT DISTINCT asin FROM experiment_inventory_snapshot_asin
        ) i ON i.asin = s.asin
        ORDER BY s.asin ASC, s.as_of_date ASC
        """
    )
    grouped: dict[str, list[TimePoint]] = defaultdict(list)
    with db.session() as session:
        rows = session.execute(sql).mappings().all()
    for row in rows:
        grouped[str(row["asin"])].append(
            TimePoint(period_date=row["as_of_date"], value=float(row["metric"] or 0.0))
        )
    return grouped


def _future_date(last_date: date, granularity: str, step: int) -> date:
    if granularity == "day":
        return last_date + timedelta(days=step)
    if granularity == "week":
        return last_date + timedelta(days=7 * step)
    raise ValueError(f"unsupported granularity: {granularity}")


def _matrix(plan_mode: str) -> list[tuple[str, int]]:
    if plan_mode == "full":
        return [("day", 3), ("week", 3), ("day", 14)]
    if plan_mode == "main":
        return [("day", 3)]
    if plan_mode == "compare":
        return [("day", 3), ("week", 3)]
    raise ValueError(f"unsupported matrix mode: {plan_mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reference method backtest on experiment tables")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--target-metric", default="units", choices=["units", "orders_count", "amount"])
    parser.add_argument("--matrix", default="full", choices=["full", "main", "compare"])
    parser.add_argument("--output-dir", default="experiments/reference_methods/output")
    parser.add_argument("--notes", default="")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()

    db = ExperimentDb(args.database_url or None)
    db.ensure_tables()

    grouped = _fetch_series(db, args.target_metric)
    if not grouped:
        raise SystemExit("No experiment data found. Run import_real_to_mysql.py first.")

    run_id = args.run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    matrix = _matrix(args.matrix)

    all_dates = [point.period_date for series in grouped.values() for point in series]
    dataset_window_start = min(all_dates)
    dataset_window_end = max(all_dates)

    output_root = Path(args.output_dir) / f"run_{run_id}"
    output_root.mkdir(parents=True, exist_ok=True)

    method_metrics_rows: list[MethodMetricRow] = []
    prediction_rows: list[dict[str, Any]] = []
    asin_method_rows: list[dict[str, Any]] = []

    total_asins = len(grouped)

    for granularity, pbf in matrix:
        scope = f"{granularity}_pbf_{pbf}"
        for method_meta in METHOD_REGISTRY:
            code = str(method_meta["method_code"])
            method_name = str(method_meta["method_name"])
            fn = method_meta.get("function")
            default_config = dict(method_meta.get("default_config", {}))

            if not method_meta.get("supported_on_current_dataset") or fn is None:
                method_metrics_rows.append(
                    MethodMetricRow(
                        method_code=code,
                        method_name=method_name,
                        scope=scope,
                        sample_count=0,
                        mad=0.0,
                        poa=0.0,
                        mae=0.0,
                        wape=0.0,
                        bias=0.0,
                        runnable_asin_count=0,
                        not_applicable_asin_count=total_asins,
                        coverage_rate=0.0,
                    )
                )
                for asin, points in grouped.items():
                    if not points:
                        continue
                    prediction_rows.append(
                        {
                            "run_id": run_id,
                            "method_code": code,
                            "asin": asin,
                            "period_date": points[-1].period_date.isoformat(),
                            "granularity": granularity,
                            "y_true": "",
                            "y_pred": "",
                            "status": "not_applicable",
                            "status_reason": str(method_meta.get("unsupported_reason", "")),
                            "scope": scope,
                        }
                    )
                continue

            runnable_asin = 0
            not_applicable_asin = 0
            scope_errors: list[dict[str, float]] = []

            for asin, points in grouped.items():
                rs = resample_series(points, granularity)
                values = [float(p.value) for p in rs]
                result = fn(values, default_config, pbf, granularity)

                status = str(result.get("status", ""))
                reason = str(result.get("status_reason", ""))
                if status != "success":
                    not_applicable_asin += 1
                    period_date = rs[-1].period_date if rs else points[-1].period_date
                    prediction_rows.append(
                        {
                            "run_id": run_id,
                            "method_code": code,
                            "asin": asin,
                            "period_date": period_date.isoformat(),
                            "granularity": granularity,
                            "y_true": "",
                            "y_pred": "",
                            "status": status,
                            "status_reason": reason,
                            "scope": scope,
                        }
                    )
                    asin_method_rows.append(
                        {
                            "scope": scope,
                            "method_code": code,
                            "method_name": method_name,
                            "asin": asin,
                            "status": status,
                            "status_reason": reason,
                            "sample_count": 0,
                            "mad": 0.0,
                            "poa": 0.0,
                            "mae": 0.0,
                            "wape": 0.0,
                            "bias": 0.0,
                        }
                    )
                    continue

                runnable_asin += 1
                holdout = result.get("simulated_holdout", [])
                holdout_start = len(rs) - pbf
                asin_errors: list[dict[str, float]] = []
                for idx, row in enumerate(holdout):
                    period_date = rs[holdout_start + idx].period_date
                    actual = float(row.get("actual", 0.0))
                    forecast = float(row.get("forecast", 0.0))
                    scope_errors.append({"actual": actual, "forecast": forecast})
                    asin_errors.append({"actual": actual, "forecast": forecast})
                    prediction_rows.append(
                        {
                            "run_id": run_id,
                            "method_code": code,
                            "asin": asin,
                            "period_date": period_date.isoformat(),
                            "granularity": granularity,
                            "y_true": round(actual, 6),
                            "y_pred": round(forecast, 6),
                            "status": "success",
                            "status_reason": "",
                            "scope": scope,
                        }
                    )

                asin_metrics = compute_metrics(asin_errors)
                asin_method_rows.append(
                    {
                        "scope": scope,
                        "method_code": code,
                        "method_name": method_name,
                        "asin": asin,
                        "status": "success",
                        "status_reason": "",
                        "sample_count": int(asin_metrics["sample_count"]),
                        "mad": asin_metrics["mad"],
                        "poa": asin_metrics["poa"],
                        "mae": asin_metrics["mae"],
                        "wape": asin_metrics["wape"],
                        "bias": asin_metrics["bias"],
                    }
                )

                future_forecasts = [float(x) for x in result.get("forecasts", [])]
                if rs:
                    last_date = rs[-1].period_date
                    for m, pred in enumerate(future_forecasts, start=1):
                        prediction_rows.append(
                            {
                                "run_id": run_id,
                                "method_code": code,
                                "asin": asin,
                                "period_date": _future_date(last_date, granularity, m).isoformat(),
                                "granularity": granularity,
                                "y_true": "",
                                "y_pred": round(pred, 6),
                                "status": "future_forecast",
                                "status_reason": "",
                                "scope": scope,
                            }
                        )

            metrics = compute_metrics(scope_errors)
            coverage_rate = 0.0 if total_asins == 0 else runnable_asin / float(total_asins)
            method_metrics_rows.append(
                MethodMetricRow(
                    method_code=code,
                    method_name=method_name,
                    scope=scope,
                    sample_count=int(metrics["sample_count"]),
                    mad=float(metrics["mad"]),
                    poa=float(metrics["poa"]),
                    mae=float(metrics["mae"]),
                    wape=float(metrics["wape"]),
                    bias=float(metrics["bias"]),
                    runnable_asin_count=runnable_asin,
                    not_applicable_asin_count=not_applicable_asin,
                    coverage_rate=round(coverage_rate, 6),
                )
            )

    with db.session() as session:
        session.execute(
            text(
                """
                INSERT INTO experiment_forecast_runs (
                  run_id, created_at, target_metric, granularity, pbf,
                  methods_json, dataset_window_start, dataset_window_end, notes
                ) VALUES (
                  :run_id, :created_at, :target_metric, :granularity, :pbf,
                  :methods_json, :dataset_window_start, :dataset_window_end, :notes
                )
                ON DUPLICATE KEY UPDATE
                  created_at=VALUES(created_at),
                  target_metric=VALUES(target_metric),
                  granularity=VALUES(granularity),
                  pbf=VALUES(pbf),
                  methods_json=VALUES(methods_json),
                  dataset_window_start=VALUES(dataset_window_start),
                  dataset_window_end=VALUES(dataset_window_end),
                  notes=VALUES(notes)
                """
            ),
            {
                "run_id": run_id,
                "created_at": created_at,
                "target_metric": args.target_metric,
                "granularity": "matrix",
                "pbf": 0,
                "methods_json": json.dumps([m["method_code"] for m in METHOD_REGISTRY], ensure_ascii=False),
                "dataset_window_start": dataset_window_start,
                "dataset_window_end": dataset_window_end,
                "notes": args.notes,
            },
        )

        # replace existing rows for same run_id
        session.execute(text("DELETE FROM experiment_forecast_predictions WHERE run_id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM experiment_forecast_metrics WHERE run_id = :run_id"), {"run_id": run_id})

        pred_stmt = text(
            """
            INSERT INTO experiment_forecast_predictions (
              run_id, method_code, asin, period_date, granularity,
              y_true, y_pred, status, status_reason
            ) VALUES (
              :run_id, :method_code, :asin, :period_date, :granularity,
              :y_true, :y_pred, :status, :status_reason
            )
            """
        )

        for row in prediction_rows:
            y_true = None if row["y_true"] == "" else float(row["y_true"])
            y_pred = None if row["y_pred"] == "" else float(row["y_pred"])
            session.execute(
                pred_stmt,
                {
                    "run_id": run_id,
                    "method_code": row["method_code"],
                    "asin": row["asin"],
                    "period_date": date.fromisoformat(str(row["period_date"])),
                    "granularity": row["granularity"],
                    "y_true": y_true,
                    "y_pred": y_pred,
                    "status": row["status"],
                    "status_reason": row["status_reason"],
                },
            )

        metric_stmt = text(
            """
            INSERT INTO experiment_forecast_metrics (
              run_id, method_code, scope, sample_count,
              mad, poa, mae, wape, bias,
              runnable_asin_count, not_applicable_asin_count, coverage_rate
            ) VALUES (
              :run_id, :method_code, :scope, :sample_count,
              :mad, :poa, :mae, :wape, :bias,
              :runnable_asin_count, :not_applicable_asin_count, :coverage_rate
            )
            """
        )

        for row in method_metrics_rows:
            session.execute(
                metric_stmt,
                {
                    "run_id": run_id,
                    "method_code": row.method_code,
                    "scope": row.scope,
                    "sample_count": row.sample_count,
                    "mad": row.mad,
                    "poa": row.poa,
                    "mae": row.mae,
                    "wape": row.wape,
                    "bias": row.bias,
                    "runnable_asin_count": row.runnable_asin_count,
                    "not_applicable_asin_count": row.not_applicable_asin_count,
                    "coverage_rate": row.coverage_rate,
                },
            )

    summary = {
        "run_id": run_id,
        "target_metric": args.target_metric,
        "matrix": [{"granularity": g, "pbf": p} for g, p in matrix],
        "dataset": {
            "asin_count": total_asins,
            "window_start": dataset_window_start.isoformat(),
            "window_end": dataset_window_end.isoformat(),
        },
        "methods": [
            {
                "method_code": item["method_code"],
                "method_name": item["method_name"],
                "supported_on_current_dataset": bool(item["supported_on_current_dataset"]),
                "unsupported_reason": item["unsupported_reason"],
            }
            for item in METHOD_REGISTRY
        ],
        "metrics": [asdict(row) for row in method_metrics_rows],
        "files": {
            "summary_json": str((output_root / "summary.json").resolve()),
            "method_metrics_csv": str((output_root / "method_metrics.csv").resolve()),
            "asin_method_metrics_csv": str((output_root / "asin_method_metrics.csv").resolve()),
            "predictions_csv": str((output_root / "predictions.csv").resolve()),
            "report_md": str((output_root / "实验报告.md").resolve()),
        },
    }

    (output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (output_root / "method_metrics.csv").open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "method_code",
                "method_name",
                "scope",
                "sample_count",
                "mad",
                "poa",
                "mae",
                "wape",
                "bias",
                "runnable_asin_count",
                "not_applicable_asin_count",
                "coverage_rate",
            ],
        )
        writer.writeheader()
        for row in method_metrics_rows:
            writer.writerow(asdict(row))

    with (output_root / "asin_method_metrics.csv").open("w", encoding="utf-8", newline="") as fp:
        fieldnames = [
            "scope",
            "method_code",
            "method_name",
            "asin",
            "status",
            "status_reason",
            "sample_count",
            "mad",
            "poa",
            "mae",
            "wape",
            "bias",
        ]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asin_method_rows)

    with (output_root / "predictions.csv").open("w", encoding="utf-8", newline="") as fp:
        fieldnames = [
            "run_id",
            "scope",
            "method_code",
            "asin",
            "period_date",
            "granularity",
            "y_true",
            "y_pred",
            "status",
            "status_reason",
        ]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(prediction_rows)

    report_lines = [
        "# 参考方法回测实验报告（自动生成）",
        "",
        f"- Run ID: {run_id}",
        f"- 目标指标: {args.target_metric}",
        f"- 样本ASIN数: {total_asins}",
        f"- 数据窗口: {dataset_window_start.isoformat()} ~ {dataset_window_end.isoformat()}",
        f"- 矩阵: {', '.join(f'{g}/pbf={p}' for g, p in matrix)}",
        "",
        "## 方法覆盖",
    ]
    for item in METHOD_REGISTRY:
        report_lines.append(
            f"- {item['method_code']} {item['method_name']}: "
            f"supported={item['supported_on_current_dataset']} reason={item['unsupported_reason']}"
        )

    report_lines.append("")
    report_lines.append("## 关键结果（method_metrics.csv）")
    for row in method_metrics_rows:
        report_lines.append(
            f"- {row.scope} | {row.method_code}: MAD={row.mad}, POA={row.poa}, MAE={row.mae}, "
            f"WAPE={row.wape}, Bias={row.bias}, Coverage={row.coverage_rate}"
        )

    (output_root / "实验报告.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
