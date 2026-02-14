from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date

from experiments.reference_methods import import_real_to_mysql
from experiments.reference_methods.xlsx_parsers import InventorySnapshotAsinRow, SalesDailyRow


class _FakeDb:
    def __init__(self, database_url=None) -> None:
        self.database_url = database_url

    def ensure_tables(self) -> None:
        return None

    @contextmanager
    def session(self):
        yield object()


def test_import_real_to_mysql_outputs_insert_and_update(monkeypatch, capsys) -> None:
    sales = [
        SalesDailyRow(as_of_date=date(2026, 2, 4), asin="A1", units=10.0, orders_count=9.0, amount=100.0),
        SalesDailyRow(as_of_date=date(2026, 2, 5), asin="A1", units=8.0, orders_count=7.0, amount=80.0),
    ]
    fba = [
        InventorySnapshotAsinRow(
            snapshot_date=date(2026, 2, 5),
            asin="A1",
            total_stock=30.0,
            sellable_stock=20.0,
            inbound_stock=5.0,
            avg_unit_cost=2.0,
            total_inventory_cost=60.0,
            total_goods_value=120.0,
            category="Cat",
            product_name="Prod",
            store_count=1,
            warehouse_count=1,
            raw_row_count=1,
        )
    ]

    monkeypatch.setattr(import_real_to_mysql, "parse_sales_workbook", lambda path: sales)
    monkeypatch.setattr(import_real_to_mysql, "parse_fba_inventory_workbook", lambda path: fba)
    monkeypatch.setattr(import_real_to_mysql, "ExperimentDb", _FakeDb)

    call_count = {"experiment_sales_daily": 0, "experiment_inventory_snapshot_asin": 0}

    def fake_upsert(session, table, rows, key_fields):
        _ = (session, rows, key_fields)
        index = call_count[table]
        call_count[table] += 1
        if index == 0:
            return len(rows), 0
        return 0, len(rows)

    monkeypatch.setattr(import_real_to_mysql, "upsert_rows", fake_upsert)

    monkeypatch.setattr(
        "sys.argv",
        [
            "import_real_to_mysql.py",
            "--sales-xlsx",
            "data/real/销量统计.xlsx",
            "--inventory-xlsx",
            "data/real/FBA库存.xlsx",
        ],
    )
    import_real_to_mysql.main()
    first = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(
        "sys.argv",
        [
            "import_real_to_mysql.py",
            "--sales-xlsx",
            "data/real/销量统计.xlsx",
            "--inventory-xlsx",
            "data/real/FBA库存.xlsx",
        ],
    )
    import_real_to_mysql.main()
    second = json.loads(capsys.readouterr().out)

    assert first["sales"]["rows_inserted"] == 2
    assert first["inventory"]["rows_inserted"] == 1
    assert second["sales"]["rows_updated"] == 2
    assert second["inventory"]["rows_updated"] == 1
    assert first["intersection"]["sales_inventory_asin_overlap"] == 1
