from __future__ import annotations

from app.core.settings import settings
from app.data.repository import load_data
from app.tools.router import invoke_tool_via_router, route_tool_call


def setup_module() -> None:
    settings.database_url = ""
    settings.db_strict = False
    load_data()


def test_router_event_contract_for_query_tool() -> None:
    event = {
        "actionGroup": "inventory-tools",
        "apiPath": "/query-inventory",
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": "query_type", "value": "stockout_risk"},
                        {"name": "limit", "value": "3"},
                    ]
                }
            }
        },
    }
    output = invoke_tool_via_router(event)
    assert output["tool"] == "inventory_query"
    assert output["args"]["query_type"] == "stockout_risk"
    assert output["bedrock_router_response"]["response"]["apiPath"] == "/query-inventory"
    assert output["bedrock_router_response"]["response"]["httpStatusCode"] == 200


def test_route_tool_call_uses_contract() -> None:
    output = route_tool_call("inventory_vendor_info", {})
    assert output["tool"] == "inventory_vendor_info"
    assert "bedrock_router_response" in output
    assert output["bedrock_router_response"]["response"]["apiPath"] == "/get-vendor-info"
