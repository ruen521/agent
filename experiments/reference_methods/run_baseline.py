from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text

from experiments.reference_methods.db import ExperimentDb
from experiments.reference_methods.methods import TimePoint, compute_metrics, resample_series


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


def _matrix(plan_mode: str) -> list[tuple[str, int]]:
    if plan_mode == "full":
        return [("day", 3), ("week", 3), ("day", 14)]
    if plan_mode == "main":
        return [("day", 3)]
    if plan_mode == "compare":
        return [("day", 3), ("week", 3)]
    raise ValueError(f"unsupported matrix mode: {plan_mode}")


def _baseline_row(
    *,
    grouped: dict[str, list[TimePoint]],
    granularity: str,
    pbf: int,
    window: int,
) -> dict[str, Any]:
    total_asins = len(grouped)
    runnable_asin = 0
    not_applicable_asin = 0
    errors: list[dict[str, float]] = []

    for _, points in grouped.items():
        rs = resample_series(points, granularity)
        values = [float(p.value) for p in rs]
        if len(values) < window + pbf:
            not_applicable_asin += 1
            continue

        holdout_start = len(values) - pbf
        if holdout_start < window:
            not_applicable_asin += 1
            continue

        runnable_asin += 1
        for idx in range(holdout_start, len(values)):
            history = values[:idx]
            pred = sum(history[-window:]) / float(window)
            errors.append({"actual": float(values[idx]), "forecast": float(pred)})

    metrics = compute_metrics(errors)
    coverage_rate = 0.0 if total_asins == 0 else runnable_asin / float(total_asins)
    return {
        "method_code": "B07",
        "method_name": f"Baseline Last {window} Period Mean",
        "scope": f"{granularity}_pbf_{pbf}",
        "sample_count": int(metrics["sample_count"]),
        "mad": float(metrics["mad"]),
        "poa": float(metrics["poa"]),
        "mae": float(metrics["mae"]),
        "wape": float(metrics["wape"]),
        "bias": float(metrics["bias"]),
        "runnable_asin_count": runnable_asin,
        "not_applicable_asin_count": not_applicable_asin,
        "coverage_rate": round(coverage_rate, 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate 7-period mean baseline on experiment data")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--target-metric", default="units", choices=["units", "orders_count", "amount"])
    parser.add_argument("--matrix", default="full", choices=["full", "main", "compare"])
    parser.add_argument("--window", type=int, default=7)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", default="experiments/reference_methods/output")
    args = parser.parse_args()

    if args.window <= 0:
        raise SystemExit("--window must be > 0")

    db = ExperimentDb(args.database_url or None)
    grouped = _fetch_series(db, args.target_metric)
    if not grouped:
        raise SystemExit("No experiment data found. Run import_real_to_mysql.py first.")

    rows = [
        _baseline_row(grouped=grouped, granularity=granularity, pbf=pbf, window=args.window)
        for granularity, pbf in _matrix(args.matrix)
    ]

    output_root = Path(args.output_dir)
    if args.run_id:
        output_root = output_root / f"run_{args.run_id}"
    output_root.mkdir(parents=True, exist_ok=True)

    csv_path = output_root / "baseline_metrics.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
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
        writer.writerows(rows)

    print(
        json.dumps(
            {
                "target_metric": args.target_metric,
                "matrix": args.matrix,
                "window": args.window,
                "rows": rows,
                "file": str(csv_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
