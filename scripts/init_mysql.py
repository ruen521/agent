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
    if "inventory_items" not in inspector.get_table_names():
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

    if not alters:
        return
    alter_sql = "ALTER TABLE inventory_items " + ", ".join(alters)
    with engine.begin() as conn:
        conn.execute(text(alter_sql))


if __name__ == "__main__":
    main()
