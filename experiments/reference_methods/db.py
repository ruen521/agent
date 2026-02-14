from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import settings


class ExperimentDb:
    def __init__(self, database_url: str | None = None) -> None:
        db_url = database_url or settings.database_url
        if not db_url:
            raise RuntimeError("DATABASE_URL/MYSQL_URL is required")
        self.engine: Engine = create_engine(db_url, pool_pre_ping=True)
        self._session_factory = sessionmaker(bind=self.engine, autoflush=False)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ensure_tables(self) -> None:
        ddl_statements = [
            """
            CREATE TABLE IF NOT EXISTS experiment_sales_daily (
                as_of_date DATE NOT NULL,
                asin VARCHAR(64) NOT NULL,
                units DOUBLE NOT NULL,
                orders_count DOUBLE NOT NULL,
                amount DOUBLE NOT NULL,
                source_file VARCHAR(255) NOT NULL,
                imported_at DATETIME NOT NULL,
                PRIMARY KEY (as_of_date, asin),
                INDEX idx_experiment_sales_daily_asin (asin)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS experiment_inventory_snapshot_asin (
                snapshot_date DATE NOT NULL,
                asin VARCHAR(64) NOT NULL,
                total_stock DOUBLE NOT NULL,
                sellable_stock DOUBLE NOT NULL,
                inbound_stock DOUBLE NOT NULL,
                avg_unit_cost DOUBLE NOT NULL,
                total_inventory_cost DOUBLE NOT NULL,
                total_goods_value DOUBLE NOT NULL,
                category VARCHAR(255) NOT NULL,
                product_name VARCHAR(255) NOT NULL,
                store_count INT NOT NULL,
                warehouse_count INT NOT NULL,
                raw_row_count INT NOT NULL,
                source_file VARCHAR(255) NOT NULL,
                imported_at DATETIME NOT NULL,
                PRIMARY KEY (snapshot_date, asin),
                INDEX idx_experiment_inventory_snapshot_asin_asin (asin)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS experiment_forecast_runs (
                run_id VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL,
                target_metric VARCHAR(32) NOT NULL,
                granularity VARCHAR(16) NOT NULL,
                pbf INT NOT NULL,
                methods_json JSON NOT NULL,
                dataset_window_start DATE NOT NULL,
                dataset_window_end DATE NOT NULL,
                notes TEXT NULL,
                PRIMARY KEY (run_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS experiment_forecast_predictions (
                id BIGINT NOT NULL AUTO_INCREMENT,
                run_id VARCHAR(64) NOT NULL,
                method_code VARCHAR(32) NOT NULL,
                asin VARCHAR(64) NOT NULL,
                period_date DATE NOT NULL,
                granularity VARCHAR(16) NOT NULL,
                y_true DOUBLE NULL,
                y_pred DOUBLE NULL,
                status VARCHAR(32) NOT NULL,
                status_reason VARCHAR(255) NOT NULL,
                PRIMARY KEY (id),
                INDEX idx_experiment_predictions_run_method_asin (run_id, method_code, asin),
                INDEX idx_experiment_predictions_run (run_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS experiment_forecast_metrics (
                id BIGINT NOT NULL AUTO_INCREMENT,
                run_id VARCHAR(64) NOT NULL,
                method_code VARCHAR(32) NOT NULL,
                scope VARCHAR(32) NOT NULL,
                sample_count INT NOT NULL,
                mad DOUBLE NULL,
                poa DOUBLE NULL,
                mae DOUBLE NULL,
                wape DOUBLE NULL,
                bias DOUBLE NULL,
                runnable_asin_count INT NOT NULL,
                not_applicable_asin_count INT NOT NULL,
                coverage_rate DOUBLE NULL,
                PRIMARY KEY (id),
                INDEX idx_experiment_metrics_run_method (run_id, method_code),
                INDEX idx_experiment_metrics_run (run_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ]
        with self.engine.begin() as conn:
            for ddl in ddl_statements:
                conn.execute(text(ddl))


def upsert_rows(session: Session, table: str, rows: list[dict[str, Any]], key_fields: list[str]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    insert_cols = list(rows[0].keys())
    update_cols = [col for col in insert_cols if col not in key_fields]
    placeholders = ", ".join(f":{col}" for col in insert_cols)
    insert_columns = ", ".join(insert_cols)
    update_clause = ", ".join(f"{col}=VALUES({col})" for col in update_cols)
    stmt = text(
        f"INSERT INTO {table} ({insert_columns}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    inserted = 0
    updated = 0
    for row in rows:
        result = session.execute(stmt, row)
        affected = int(result.rowcount or 0)
        if affected == 1:
            inserted += 1
        elif affected >= 2:
            updated += 1
    return inserted, updated
