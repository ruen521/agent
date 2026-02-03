from __future__ import annotations

from app.spapi.client import SpApiClient


def test_spapi_health_mock() -> None:
    client = SpApiClient()
    result = client.health_check()
    assert result["status"] in {"mock", "ok", "error"}


def test_spapi_mock_inventory() -> None:
    client = SpApiClient()
    data = client.get_inventory_summaries()
    assert isinstance(data, dict)
    assert "payload" in data
