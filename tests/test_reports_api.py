from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reports import service as report_service
from app.reports import store as report_store
from app.reports.schemas import ExportJobRecord


@pytest.fixture
def isolated_export_store(monkeypatch, tmp_path):
    base = tmp_path / "exports"
    files = base / "files"
    jobs = base / "jobs.json"
    monkeypatch.setattr(report_store, "_BASE_DIR", base)
    monkeypatch.setattr(report_store, "_FILES_DIR", files)
    monkeypatch.setattr(report_store, "_JOBS_PATH", jobs)
    return {"base": base, "files": files, "jobs": jobs}


def _wait_terminal(client: TestClient, job_id: str, timeout_s: float = 2.0) -> dict:
    deadline = time.time() + timeout_s
    payload = {}
    while time.time() < deadline:
        res = client.get(f"/reports/exports/{job_id}")
        assert res.status_code == 200
        payload = res.json()
        if payload["status"] in {"DONE", "FAILED", "EXPIRED"}:
            return payload
        time.sleep(0.05)
    return payload


def test_create_global_pdf_export_and_download(monkeypatch, isolated_export_store) -> None:
    monkeypatch.setattr(
        report_service,
        "_build_global_context",
        lambda req: {
            "title": "全局运营报告",
            "generated_at": "2026-02-09T00:00:00+00:00",
            "audience": req.audience,
            "stats": {"total_skus": 3},
            "risks": [{"SKU": "A", "days_until_stockout": 2, "urgency_level": "CRITICAL", "shortage_amount": 5, "revenue_at_risk": 10}],
            "inventory": [{"SKU": "A", "Name": "A", "Category": "C", "CurrentStock": 10, "ReorderPoint": 20, "DailySalesVelocity": 2, "VendorID": "V1"}],
            "latest_agent_summaries": [],
        },
    )

    def fake_pdf(scope, context, output_path):
        output_path.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "global",
            "audience": "external",
            "payload": {},
        },
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    status_payload = _wait_terminal(client, job_id)
    assert status_payload["status"] == "DONE"
    assert "download_url" in status_payload

    download = client.get(f"/reports/exports/{job_id}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")


def test_session_excel_internal_keeps_reasoning(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_xlsx(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"fake-xlsx")

    monkeypatch.setattr(report_service, "render_scope_xlsx", fake_xlsx)

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "xlsx",
            "scope": "session",
            "audience": "internal",
            "session_id": "s-1",
            "agent_id": "inventory_copilot",
            "payload": {
                "messages": [
                    {
                        "role": "assistant",
                        "content": "ok",
                        "meta": {"reasoning": "inner-thought"},
                    }
                ]
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"
    assert captured["context"]["messages"][0]["meta"]["reasoning"] == "inner-thought"


def test_session_excel_external_hides_reasoning(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_xlsx(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"fake-xlsx")

    monkeypatch.setattr(report_service, "render_scope_xlsx", fake_xlsx)

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "xlsx",
            "scope": "session",
            "audience": "external",
            "payload": {
                "messages": [
                    {
                        "role": "assistant",
                        "content": "ok",
                        "meta": {"reasoning": "inner-thought", "request_id": "req-1"},
                    }
                ]
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"
    assert "reasoning" not in captured["context"]["messages"][0]["meta"]


def test_download_when_not_ready_returns_409(isolated_export_store) -> None:
    now = datetime.now(timezone.utc)
    job = ExportJobRecord(
        job_id="job-running",
        status="RUNNING",
        progress=40,
        format="pdf",
        scope="table",
        audience="external",
        title="running",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=1),
        output_path=str((isolated_export_store["files"] / "running.pdf").resolve()),
        error_message=None,
    )
    report_store.upsert_job(job)

    client = TestClient(app)
    res = client.get("/reports/exports/job-running/download")
    assert res.status_code == 409


def test_stalled_running_job_turns_failed_on_status(isolated_export_store) -> None:
    now = datetime.now(timezone.utc)
    job = ExportJobRecord(
        job_id="job-stalled",
        status="RUNNING",
        progress=60,
        format="pdf",
        scope="analysis",
        audience="external",
        title="stalled",
        created_at=now - timedelta(minutes=10),
        updated_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(days=1),
        output_path=str((isolated_export_store["files"] / "stalled.pdf").resolve()),
        error_message=None,
    )
    report_store.upsert_job(job)

    client = TestClient(app)
    res = client.get("/reports/exports/job-stalled")
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "FAILED"
    assert payload["progress"] == 100
    assert "超时" in (payload.get("error_message") or "")


def test_download_expired_returns_404(isolated_export_store) -> None:
    now = datetime.now(timezone.utc)
    path = isolated_export_store["files"] / "expired.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"expired")
    job = ExportJobRecord(
        job_id="job-expired",
        status="DONE",
        progress=100,
        format="pdf",
        scope="table",
        audience="external",
        title="expired",
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=1),
        output_path=str(path.resolve()),
        error_message=None,
    )
    report_store.upsert_job(job)

    client = TestClient(app)
    res = client.get("/reports/exports/job-expired/download")
    assert res.status_code == 404


def test_invalid_format_or_scope_returns_400(isolated_export_store) -> None:
    client = TestClient(app)
    bad_format = client.post(
        "/reports/exports",
        json={"format": "doc", "scope": "global", "audience": "external", "payload": {}},
    )
    assert bad_format.status_code == 400

    bad_scope = client.post(
        "/reports/exports",
        json={"format": "pdf", "scope": "overview", "audience": "external", "payload": {}},
    )
    assert bad_scope.status_code == 400


def test_analysis_scope_external_hides_reasoning(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["scope"] = scope
        captured["context"] = context
        output_path.write_bytes(b"%PDF-analysis")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "stockout_sentinel",
                    "question": "test",
                    "answer": "ok",
                    "reasoning": "should-hide",
                    "structured_output": {"summary": "x"},
                    "tool_trace": [{"tool": "inventory_query"}],
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"
    assert captured["scope"] == "analysis"
    assert captured["context"]["analysis"]["reasoning"] == ""


def test_analysis_pdf_context_keeps_full_payload(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["scope"] = scope
        captured["context"] = context
        output_path.write_bytes(b"%PDF-full")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    huge_text = "x" * 12000
    huge_trace = [
        {
            "tool": "inventory_query",
            "apiPath": "/data/inventory",
            "httpStatusCode": 200,
            "args": {"note": f"payload-{idx}-" + ("a" * 600)},
        }
        for idx in range(260)
    ]

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "inventory_copilot",
                    "question": "q",
                    "answer": "a",
                    "structured_output": {
                        "plan": [{"task": f"step-{idx}"} for idx in range(280)],
                        "blob": huge_text,
                    },
                    "tool_trace": huge_trace,
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"

    analysis = captured["context"]["analysis"]
    assert captured["scope"] == "analysis"
    assert len(analysis["tool_trace"]) == len(huge_trace)
    assert len(analysis["tool_trace_rows"]) == len(huge_trace)
    assert len(analysis["plan_steps"]) == 280
    assert analysis["structured_output"]["blob"] == huge_text
    assert analysis["structured_output_text"].count("x") >= 12000


def test_external_report_uses_agent_specific_template(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"%PDF-external-specific")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "stockout_sentinel",
                    "question": "缺货风险有哪些",
                    "answer": "已生成缺货风险评估。",
                    "structured_output": {
                        "risks": [
                            {"sku": "APP-001", "days": 2.1, "urgency": "CRITICAL", "revenue_at_risk": 120.5, "actions": ["联系供应商"]}
                        ]
                    },
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"

    external = captured["context"]["analysis"]["external_report"]
    assert external["report_title"] == captured["context"]["title"]
    assert external["agent_label"] == "缺货哨兵"
    assert external["action_plan"] == []
    assert external["detail_sections"] == []
    assert external["model_markdown_blocks"]


def test_external_report_replenishment_preserves_model_text_without_notice_fallback(
    monkeypatch, isolated_export_store
) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"%PDF-replenishment-notice")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "replenishment_planner",
                    "question": "补货计划",
                    "answer": "补货接口暂时无法连接，请稍后重试。",
                    "structured_output": {"plan": {}},
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"

    external = captured["context"]["analysis"]["external_report"]
    assert external["report_title"] == captured["context"]["title"]
    assert external["data_notice"] == "PDF 仅展示模型输出内容；业务数据请导出 Excel。"
    assert external["executive_summary"] == "补货接口暂时无法连接，请稍后重试。"
    assert external["model_markdown_blocks"]


def test_analysis_export_title_uses_agent_prefix_with_date(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"%PDF-title")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "agent_id": "replenishment_planner",
            "payload": {
                "analysis": {
                    "agent_id": "replenishment_planner",
                    "answer": "已完成补货建议。",
                    "structured_output": {"plan": {}},
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"

    title = captured["context"]["title"]
    assert re.match(r"^补货建议-\d{4}\.\d{1,2}\.\d{1,2}$", title)
    assert captured["context"]["analysis"]["external_report"]["report_title"] == title


def test_external_summary_uses_model_text_when_answer_is_noisy(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"%PDF-summary")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    noisy_answer = (
        "以下是补货计划，按供应商分组：### 供应商A\n"
        "- SKU: APP-0001, 数量: 120\n"
        "- SKU: APP-0002, 数量: 90\n"
        "- SKU: APP-0003, 数量: 40\n"
    )

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "agent_id": "replenishment_planner",
            "payload": {
                "analysis": {
                    "agent_id": "replenishment_planner",
                    "answer": noisy_answer,
                    "structured_output": {"plan": {"vendor_groups": []}},
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"

    external = captured["context"]["analysis"]["external_report"]
    assert external["executive_summary"] == "以下是补货计划，按供应商分组：供应商A"
    assert external["executive_highlights"]


def test_copilot_external_report_includes_workflow_step_details(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"%PDF-copilot-workflow")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    workflow_results = [
        {
            "label": "异常检测",
            "agent_id": "exception_investigator",
            "status": "DONE",
            "summary": "识别异常并给出修复建议",
            "started_at": "2026-02-09T10:00:00+00:00",
            "finished_at": "2026-02-09T10:01:00+00:00",
            "structured_output": {
                "anomalies": [
                    {"sku": "APP-001", "type": "price_outlier", "note": "价格偏离", "recommendation": "复核目录价"}
                ]
            },
        },
        {
            "label": "缺货风险",
            "agent_id": "stockout_sentinel",
            "status": "DONE",
            "summary": "识别高风险缺货SKU",
            "started_at": "2026-02-09T10:01:00+00:00",
            "finished_at": "2026-02-09T10:02:00+00:00",
            "structured_output": {
                "risks": [
                    {
                        "sku": "APP-002",
                        "urgency": "HIGH",
                        "days": 3.2,
                        "revenue_at_risk": 200,
                        "vendor_name": "Evergreen",
                        "actions": ["加急下单"],
                    }
                ]
            },
        },
    ]

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "inventory_copilot",
                    "answer": "已完成智能检测。",
                    "structured_output": {"objective": "库存智能检测闭环", "past_steps": [], "remaining_plan": []},
                    "tool_output": {"workflow_results": workflow_results},
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"

    external = captured["context"]["analysis"]["external_report"]
    assert external.get("model_markdown_blocks")
    assert external.get("summary_cards") == []
    assert external.get("action_plan") == []
    assert external.get("detail_sections") == []


def test_copilot_external_report_uses_team_execution_when_workflow_missing(monkeypatch, isolated_export_store) -> None:
    captured = {}

    def fake_pdf(scope, context, output_path):
        captured["context"] = context
        output_path.write_bytes(b"%PDF-copilot-team-execution")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)

    team_execution = [
        {
            "member_id": "exception_investigator",
            "result_status": "success",
            "started_at": "2026-02-09T10:00:00+00:00",
            "ended_at": "2026-02-09T10:01:00+00:00",
            "summary": "识别异常并给出修复建议",
            "structured_output": {
                "anomalies": [
                    {"sku": "APP-001", "type": "price_outlier", "note": "价格偏离", "recommendation": "复核目录价"}
                ]
            },
        },
        {
            "member_id": "stockout_sentinel",
            "result_status": "timeout",
            "started_at": "2026-02-09T10:01:00+00:00",
            "ended_at": "2026-02-09T10:02:00+00:00",
            "error_code": "TEAM_V1_TIMEOUT",
            "structured_output": {},
        },
    ]

    client = TestClient(app)
    res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "inventory_copilot",
                    "answer": "已完成智能检测。",
                    "structured_output": {
                        "objective": "固定巡检",
                        "status": "team_v1_partial",
                        "team_execution": team_execution,
                    },
                    "tool_output": {},
                }
            },
        },
    )
    assert res.status_code == 200
    status_payload = _wait_terminal(client, res.json()["job_id"])
    assert status_payload["status"] == "DONE"

    external = captured["context"]["analysis"]["external_report"]
    assert external["summary_cards"] == []
    assert any("已完成智能检测" in line for line in external["key_findings"])
    assert external["action_plan"] == []
    assert external["model_markdown_blocks"]
    assert external["detail_sections"] == []
    block_text = " ".join(
        str(block.get("text") or "")
        for block in external["model_markdown_blocks"]
        if isinstance(block, dict)
    )
    assert "最终结论" in block_text
    assert "成员完整结论" in block_text
    assert "异常侦测" in block_text
    assert "缺货哨兵" in block_text


def test_analysis_pdf_model_only_but_excel_full_details(monkeypatch, isolated_export_store) -> None:
    captured_pdf = {}
    captured_xlsx = {}

    def fake_pdf(scope, context, output_path):
        captured_pdf["context"] = context
        output_path.write_bytes(b"%PDF-topn")

    def fake_xlsx(scope, context, output_path):
        captured_xlsx["context"] = context
        output_path.write_bytes(b"excel-full")

    monkeypatch.setattr(report_service, "render_scope_pdf", fake_pdf)
    monkeypatch.setattr(report_service, "render_scope_xlsx", fake_xlsx)

    anomalies = [
        {
            "sku": f"APP-{index:06d}",
            "type": "price_outlier",
            "note": "价格偏离",
            "recommendation": "复核价格口径",
        }
        for index in range(25)
    ]
    workflow_results = [
        {
            "agent_id": "exception_investigator",
            "label": "异常检测",
            "status": "DONE",
            "summary": "已完成",
            "started_at": "2026-02-09T10:00:00+00:00",
            "finished_at": "2026-02-09T10:01:00+00:00",
            "structured_output": {"anomalies": anomalies},
        }
    ]
    team_execution = [
        {
            "member_id": "exception_investigator",
            "result_status": "success",
            "started_at": "2026-02-09T10:00:00+00:00",
            "ended_at": "2026-02-09T10:01:00+00:00",
            "summary": "已完成",
            "structured_output": {"anomalies": anomalies},
        }
    ]

    client = TestClient(app)

    pdf_res = client.post(
        "/reports/exports",
        json={
            "format": "pdf",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "inventory_copilot",
                    "answer": "已完成智能检测。",
                    "structured_output": {"objective": "库存智能检测闭环", "team_execution": team_execution},
                    "tool_output": {"workflow_results": workflow_results},
                }
            },
        },
    )
    assert pdf_res.status_code == 200
    pdf_status = _wait_terminal(client, pdf_res.json()["job_id"])
    assert pdf_status["status"] == "DONE"

    external_pdf = captured_pdf["context"]["analysis"]["external_report"]
    assert external_pdf.get("model_markdown_blocks")
    assert external_pdf.get("summary_cards") == []
    assert external_pdf.get("action_plan") == []
    assert external_pdf.get("detail_sections") == []

    xlsx_res = client.post(
        "/reports/exports",
        json={
            "format": "xlsx",
            "scope": "analysis",
            "audience": "external",
            "payload": {
                "analysis": {
                    "agent_id": "inventory_copilot",
                    "answer": "已完成智能检测。",
                    "structured_output": {"objective": "库存智能检测闭环", "team_execution": team_execution},
                    "tool_output": {"workflow_results": workflow_results},
                }
            },
        },
    )
    assert xlsx_res.status_code == 200
    xlsx_status = _wait_terminal(client, xlsx_res.json()["job_id"])
    assert xlsx_status["status"] == "DONE"

    external_xlsx = captured_xlsx["context"]["analysis"]["external_report"]
    detail_xlsx = [
        section
        for section in external_xlsx.get("detail_sections", [])
        if isinstance(section, dict) and section.get("title") == "异常明细"
    ][0]
    assert len(detail_xlsx.get("rows", [])) == 25
