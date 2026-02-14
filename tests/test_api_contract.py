from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app


def test_invoke_missing_required_fields_returns_400() -> None:
    client = TestClient(app)
    res = client.post("/agents/invoke", json={"agent": "stockout"})
    assert res.status_code == 400
    payload = res.json()
    assert payload["success"] is False
    assert payload["error_code"] == "BAD_REQUEST"


def test_invoke_invalid_payload_returns_400() -> None:
    client = TestClient(app)
    res = client.post("/agents/invoke", json={"agent": 1, "input": {}})
    assert res.status_code == 400
    payload = res.json()
    assert payload["success"] is False
    assert payload["error_code"] == "BAD_REQUEST"


def test_invoke_accepts_short_agent_name(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "run_agent",
        lambda state: {
            **state,
            "response_text": "ok",
            "reasoning": "forced",
            "structured_output": {"tool": "inventory_query", "result": {"count": 1}},
            "tool_output": {"count": 1},
            "tool_trace": [],
        },
    )
    client = TestClient(app)
    res = client.post(
        "/agents/invoke",
        json={
            "agent": "stockout",
            "input": "show stockout risks",
            "parameters": {
                "tool": "inventory_query",
                "args": {"query_type": "stockout_risk", "limit": 5},
            },
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert payload["agent"] == "stockout"
    assert "response_text" in payload
    assert "response" in payload
    assert "tool_trace" in payload["response"]


def test_list_agents_contains_lifecycle_metadata() -> None:
    client = TestClient(app)
    res = client.get("/agents/list")
    assert res.status_code == 200
    agents = res.json()["agents"]
    assert len(agents) == 5
    for agent in agents:
        assert agent["status"] in {"PREPARED", "NOT_PREPARED"}
        assert "lifecycle" in agent
        assert "version" in agent["lifecycle"]


def test_invoke_team_v2_mode_normalized_to_team(monkeypatch) -> None:
    def fake_run_agent(state: dict) -> dict:
        return {
            **state,
            "response_text": "ok",
            "reasoning": "orchestrated",
            "structured_output": {
                "team_version": "v1",
                "status": "team_v1_completed",
                "team_plan": ["stockout_sentinel"],
                "team_execution": [],
                "team_summary": {"success_count": 1, "failure_count": 0, "partial_success_count": 0},
                "rag_summary": {"run_dir": "/tmp/team_v1", "evidence_count": 0, "retrieval_event_count": 0},
            },
            "tool_output": {},
            "tool_trace": [],
        }

    monkeypatch.setattr(routes, "run_agent", fake_run_agent)
    client = TestClient(app)
    res = client.post(
        "/agents/invoke",
        json={
            "agent": "copilot",
            "input": "协同分析",
            "parameters": {"mode": "team_v2"},
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert payload["collab_mode"] == "team"
    assert payload["response"]["structured_output"]["status"] == "team_v1_completed"


def test_invoke_runtime_error_returns_non_200_with_error_code(monkeypatch) -> None:
    monkeypatch.setattr(routes, "run_agent", lambda state: (_ for _ in ()).throw(RuntimeError("TOOL_ROUTER_ERROR: bad tool")))
    client = TestClient(app)
    res = client.post(
        "/agents/invoke",
        json={
            "agent": "copilot",
            "input": "协同分析",
        },
    )
    assert res.status_code == 502
    payload = res.json()
    assert payload["success"] is False
    assert payload["error_code"] == "TOOL_ROUTER_ERROR"
    assert "bad tool" in payload["error_message"]


def test_invoke_stream_emits_done_for_specialist_agents(monkeypatch) -> None:
    def fake_run_agent_updates(state: dict):
        yield {"planner": {"plan": [{"task": "noop"}]}}
        yield {
            "finalize": {
                **state,
                "response_text": "ok",
                "reasoning": "done",
                "structured_output": {"status": "completed"},
                "tool_output": {"count": 1},
                "tool_trace": [],
            }
        }

    monkeypatch.setattr(routes, "run_agent_updates", fake_run_agent_updates)
    client = TestClient(app)

    for agent_alias in ("exceptions", "markdown"):
        with client.stream(
            "POST",
            "/agents/invoke_stream",
            json={"agent": agent_alias, "input": "请执行"},
        ) as res:
            assert res.status_code == 200
            body = "".join(chunk for chunk in res.iter_text())

        assert "event: start" in body
        assert "event: done" in body


def test_invoke_stream_runtime_error_emits_error_without_done(monkeypatch) -> None:
    def fake_run_agent_updates(state: dict):
        yield {"copilot_team_v1_plan": {"team_v1_plan": ["stockout_sentinel"]}}
        raise RuntimeError("TEAM_V1_RUNTIME_ERROR: team failed")

    monkeypatch.setattr(routes, "run_agent_updates", fake_run_agent_updates)
    client = TestClient(app)
    with client.stream(
        "POST",
        "/agents/invoke_stream",
        json={"agent": "copilot", "input": "请执行"},
    ) as res:
        assert res.status_code == 200
        body = "".join(chunk for chunk in res.iter_text())

    assert "event: error" in body
    assert "TEAM_V1_RUNTIME_ERROR" in body
    assert "event: done" not in body
