from __future__ import annotations

import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from app.core.settings import settings


def main() -> None:
    if not settings.database_url:
        raise SystemExit("DATABASE_URL/MYSQL_URL not set")
    from app.db.mysql_repository import MysqlRepository

    repo = MysqlRepository(settings.database_url)
    repo.create_tables()
    _migrate_columns(repo)
    print("mysql tables created")


def _migrate_columns(repo: MysqlRepository) -> None:
    from sqlalchemy import inspect, text

    engine = repo.engine
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "inventory_items" not in table_names:
        return
    columns = {col["name"] for col in inspector.get_columns("inventory_items")}
    alters = []
    if "selling_price" not in columns:
        alters.append("ADD COLUMN selling_price DOUBLE NULL")
    if "gross_margin_pct" not in columns:
        alters.append("ADD COLUMN gross_margin_pct DOUBLE NULL")
    if "holding_cost_pct" not in columns:
        alters.append("ADD COLUMN holding_cost_pct DOUBLE NULL")
    if "substitute_skus" not in columns:
        alters.append("ADD COLUMN substitute_skus JSON NULL")

    if alters:
        alter_sql = "ALTER TABLE inventory_items " + ", ".join(alters)
        with engine.begin() as conn:
            conn.execute(text(alter_sql))

    if "vendor_call_logs" in table_names:
        _migrate_vendor_call_logs(inspector, engine)
    if "replenishment_plans" in table_names:
        _migrate_replenishment_plans(inspector, engine)


def _migrate_vendor_call_logs(inspector, engine) -> None:
    from sqlalchemy import text

    columns = {col["name"] for col in inspector.get_columns("vendor_call_logs")}
    alters = []
    if "duration" not in columns:
        alters.append("ADD COLUMN duration INT NULL")
    if "outcome" not in columns:
        alters.append("ADD COLUMN outcome VARCHAR(64) NULL")
    if "recording_url" not in columns:
        alters.append("ADD COLUMN recording_url VARCHAR(1024) NULL")
    if not alters:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE vendor_call_logs " + ", ".join(alters)))


def _migrate_replenishment_plans(inspector, engine) -> None:
    from sqlalchemy import text

    columns = {col["name"] for col in inspector.get_columns("replenishment_plans")}
    alters = []
    if "created_by" not in columns:
        alters.append("ADD COLUMN created_by VARCHAR(128) NULL")
    if "status" not in columns:
        alters.append("ADD COLUMN status VARCHAR(64) NULL")
    if not alters:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE replenishment_plans " + ", ".join(alters)))


if __name__ == "__main__":
    main()
