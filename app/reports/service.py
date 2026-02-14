from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import html
import json
import re
import subprocess
import sys
import threading
from pathlib import Path
import os
import uuid
from typing import Any

from fastapi import HTTPException

from app.reports.render_pdf import render_scope_pdf
from app.reports.render_xlsx import render_scope_xlsx
from app.reports.schemas import ExportJobRecord, ExportRequest
from app.reports import store
from app.core.settings import settings
from app.tools.inventory_tools import inventory_query_tool
from app.tools.stats import stats_calculator

_SESSION_MAX_MESSAGES = 200
_TABLE_MAX_ROWS = 10_000
_REPORT_TTL_DAYS = 7
_STALLED_RUNNING_SECONDS = 180
_REPORT_DEFAULT_OWNER = "运营负责人"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_AGENT_LABELS = {
    "stockout_sentinel": "缺货哨兵",
    "replenishment_planner": "补货规划",
    "exception_investigator": "异常侦测",
    "markdown_clearance_coach": "清仓教练",
    "inventory_copilot": "库存助手",
}

_ANOMALY_LABELS = {
    "velocity_reorder_mismatch": "销量与补货点不匹配",
    "price_outlier": "价格偏离同类区间",
    "price_zscore_outlier": "价格波动异常",
    "velocity_zscore_outlier": "销量波动异常",
    "negative_margin": "毛利异常",
    "zero_stock_positive_velocity": "库存与销量数据冲突",
    "stale_inventory": "滞销库存积压",
}

_COPILOT_STATUS_LABELS = {
    "completed": "已完成",
    "max_steps_reached": "达到执行步数上限",
    "team_v1_completed": "协同完成",
    "team_v1_partial": "部分完成",
    "team_v1_failed": "执行失败",
}

_SCOPE_TITLE_PREFIX = {
    "global": "运营总览",
    "session": "会话分析",
    "table": "数据明细",
    "analysis": "智能体建议",
}

_ANALYSIS_TITLE_PREFIX = {
    "stockout_sentinel": "缺货建议",
    "replenishment_planner": "补货建议",
    "exception_investigator": "异常修复建议",
    "markdown_clearance_coach": "清仓折扣建议",
    "inventory_copilot": "运营编排建议",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _file_ext(fmt: str) -> str:
    return "pdf" if fmt == "pdf" else "xlsx"


def _title_date_label(moment: datetime) -> str:
    local = moment.astimezone()
    return f"{local.year}.{local.month}.{local.day}"


def _default_title(scope: str, agent_id: str | None = None) -> str:
    if scope == "analysis":
        prefix = _ANALYSIS_TITLE_PREFIX.get(str(agent_id or "").strip(), _SCOPE_TITLE_PREFIX["analysis"])
    else:
        prefix = _SCOPE_TITLE_PREFIX.get(scope, "运营报告")
    return f"{prefix}-{_title_date_label(_now())}"


def _safe_title(scope: str, title: str | None, agent_id: str | None = None) -> str:
    if title:
        return title.strip()[:80] or _default_title(scope, agent_id)
    return _default_title(scope, agent_id)


def _resolve_title_agent_id(req: ExportRequest) -> str | None:
    if req.agent_id:
        return req.agent_id
    if req.scope != "analysis":
        return None
    payload = req.payload if isinstance(req.payload, dict) else {}
    analysis = payload.get("analysis", {})
    if isinstance(analysis, dict):
        raw = str(analysis.get("agent_id") or "").strip()
        return raw or None
    return None


def _build_filename(req: ExportRequest, job_id: str) -> str:
    timestamp = _now().strftime("%Y%m%d_%H%M%S")
    ext = _file_ext(req.format)
    return f"{req.scope}_{req.audience}_{timestamp}_{job_id}.{ext}"


def _request_payload_dir() -> Path:
    path = store.files_dir().parent / "requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _request_payload_path(job_id: str) -> Path:
    return _request_payload_dir() / f"{job_id}.json"


def _new_job_record(req: ExportRequest) -> ExportJobRecord:
    now = _now()
    job_id = uuid.uuid4().hex
    filename = _build_filename(req, job_id)
    output_path = str(store.files_dir() / filename)
    title_agent_id = _resolve_title_agent_id(req)
    return ExportJobRecord(
        job_id=job_id,
        status="PENDING",
        progress=0,
        format=req.format,
        scope=req.scope,
        audience=req.audience,
        title=_safe_title(req.scope, req.title, title_agent_id),
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=_REPORT_TTL_DAYS),
        output_path=output_path,
        error_message=None,
    )


def _cleanup_expired() -> None:
    now = _now()
    expired_ids: list[str] = []
    for job in store.list_jobs():
        if job.expires_at >= now:
            if job.status == "RUNNING" and (now - job.updated_at).total_seconds() > _STALLED_RUNNING_SECONDS:
                store.update_job(
                    job.job_id,
                    status="FAILED",
                    progress=100,
                    error_message="导出任务超时，请重试。",
                )
            continue
        if job.status != "EXPIRED":
            store.update_job(job.job_id, status="EXPIRED", progress=100, error_message="导出任务已过期")
        expired_ids.append(job.job_id)
        try:
            path = Path(job.output_path)
            if path.exists():
                path.unlink()
        except Exception:
            pass
    if expired_ids:
        # Keep metadata for visibility; do not remove records in first version.
        pass


def create_export_job(req: ExportRequest) -> ExportJobRecord:
    _cleanup_expired()
    job = _new_job_record(req)
    store.upsert_job(job)
    return job


def _build_global_context(req: ExportRequest) -> dict[str, Any]:
    stats = stats_calculator()
    risks = inventory_query_tool(query_type="stockout_risk", limit=200).get("items", [])
    inventory = inventory_query_tool(query_type="all", limit=1000).get("items", [])
    payload = req.payload if isinstance(req.payload, dict) else {}
    latest = payload.get("latest_agent_summaries", [])
    if not isinstance(latest, list):
        latest = []
    return {
        "title": _safe_title(req.scope, req.title, req.agent_id),
        "generated_at": _iso_now(),
        "audience": req.audience,
        "stats": stats,
        "risks": risks,
        "inventory": inventory,
        "latest_agent_summaries": latest,
    }


def _sanitize_message_for_audience(message: dict[str, Any], audience: str) -> dict[str, Any]:
    output = dict(message)
    meta = output.get("meta")
    if not isinstance(meta, dict):
        return output
    if audience == "internal":
        return output
    hidden = dict(meta)
    hidden.pop("reasoning", None)
    output["meta"] = hidden
    return output


def _build_session_context(req: ExportRequest) -> dict[str, Any]:
    payload = req.payload if isinstance(req.payload, dict) else {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    messages = messages[:_SESSION_MAX_MESSAGES]
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        normalized.append(_sanitize_message_for_audience(message, req.audience))
    return {
        "title": _safe_title(req.scope, req.title, req.agent_id),
        "generated_at": _iso_now(),
        "audience": req.audience,
        "session_id": req.session_id or "",
        "agent_id": req.agent_id or "",
        "messages": normalized,
    }


def _build_table_context(req: ExportRequest) -> dict[str, Any]:
    payload = req.payload if isinstance(req.payload, dict) else {}
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        rows = []
    rows = rows[:_TABLE_MAX_ROWS]
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized_rows.append(row)

    filters = payload.get("filters", {})
    if not isinstance(filters, dict):
        filters = {}

    return {
        "title": _safe_title(req.scope, req.title, req.agent_id),
        "generated_at": _iso_now(),
        "audience": req.audience,
        "table_name": str(payload.get("table_name") or "table"),
        "filters": filters,
        "rows": normalized_rows,
    }


def _as_json_text(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        text = str(value)
    return text


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_str(value: Any, default: str = "-") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _urgency_rank(urgency: str) -> int:
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    return order.get(str(urgency).upper(), 9)


def _urgency_label(urgency: Any) -> str:
    mapping = {"CRITICAL": "紧急", "HIGH": "高", "MEDIUM": "中", "LOW": "低"}
    return mapping.get(str(urgency).upper(), _to_str(urgency))


def _money(amount: Any) -> str:
    return f"${_safe_float(amount):,.2f}"


def _markdown_inline_to_html(text: str) -> str:
    escaped = html.escape(text)

    def _link_repl(match: re.Match[str]) -> str:
        label = match.group(1)
        url = match.group(2)
        safe_label = html.escape(label)
        safe_url = html.escape(url, quote=True)
        return f'<a href="{safe_url}">{safe_label}</a>'

    rendered = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _link_repl, escaped)
    rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", rendered)
    rendered = re.sub(r"_([^_]+)_", r"<em>\1</em>", rendered)
    return rendered


def _markdown_inline_to_text(text: str) -> str:
    normalized = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", text)
    normalized = re.sub(r"(?<!\w)#{1,6}\s*", "", normalized)
    for token in ("**", "__", "`"):
        normalized = normalized.replace(token, "")
    normalized = re.sub(r"\*([^*]+)\*", r"\1", normalized)
    normalized = re.sub(r"_([^_]+)_", r"\1", normalized)
    return normalized.strip()


def _markdown_table_cells(line: str) -> list[str]:
    value = line.strip().strip("|")
    if not value:
        return []
    return [_markdown_inline_to_html(cell.strip()) for cell in value.split("|")]


def _is_markdown_table_separator(line: str) -> bool:
    value = line.strip()
    if not value:
        return False
    candidate = value.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
    if candidate:
        return False
    return "-" in value


def _markdown_blocks(text: str) -> list[dict[str, Any]]:
    if not text:
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict[str, Any]] = []
    paragraph_lines: list[str] = []
    unordered_items: list[str] = []
    ordered_items: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if not paragraph_lines:
            return
        merged = " ".join(item.strip() for item in paragraph_lines if item.strip())
        if merged:
            blocks.append(
                {
                    "type": "paragraph",
                    "text": _markdown_inline_to_text(merged),
                    "html": _markdown_inline_to_html(merged),
                }
            )
        paragraph_lines = []

    def flush_unordered() -> None:
        nonlocal unordered_items
        if not unordered_items:
            return
        blocks.append(
            {
                "type": "unordered_list",
                "items": [
                    {"text": _markdown_inline_to_text(item), "html": _markdown_inline_to_html(item)}
                    for item in unordered_items
                    if item.strip()
                ],
            }
        )
        unordered_items = []

    def flush_ordered() -> None:
        nonlocal ordered_items
        if not ordered_items:
            return
        blocks.append(
            {
                "type": "ordered_list",
                "items": [
                    {"text": _markdown_inline_to_text(item), "html": _markdown_inline_to_html(item)}
                    for item in ordered_items
                    if item.strip()
                ],
            }
        )
        ordered_items = []

    def flush_code() -> None:
        nonlocal code_lines
        if not code_lines:
            return
        blocks.append({"type": "code_block", "text": "\n".join(code_lines).rstrip("\n")})
        code_lines = []

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            flush_unordered()
            flush_ordered()
            if in_code:
                flush_code()
            in_code = not in_code
            index += 1
            continue

        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            flush_unordered()
            flush_ordered()
            index += 1
            continue

        header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if header_match:
            flush_paragraph()
            flush_unordered()
            flush_ordered()
            level = len(header_match.group(1))
            raw = header_match.group(2).strip()
            blocks.append(
                {
                    "type": "heading",
                    "level": level,
                    "text": _markdown_inline_to_text(raw),
                    "html": _markdown_inline_to_html(raw),
                }
            )
            index += 1
            continue

        if "|" in stripped and index + 1 < len(lines) and _is_markdown_table_separator(lines[index + 1]):
            flush_paragraph()
            flush_unordered()
            flush_ordered()
            header = _markdown_table_cells(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines):
                row_line = lines[index].strip()
                if not row_line or "|" not in row_line:
                    break
                rows.append(_markdown_table_cells(row_line))
                index += 1
            if header:
                blocks.append({"type": "table", "header": header, "rows": rows})
            continue

        unordered_match = re.match(r"^\s*[-*]\s+(.+)$", line)
        if unordered_match:
            flush_paragraph()
            flush_ordered()
            unordered_items.append(unordered_match.group(1).strip())
            index += 1
            continue

        ordered_match = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if ordered_match:
            flush_paragraph()
            flush_unordered()
            ordered_items.append(ordered_match.group(1).strip())
            index += 1
            continue

        paragraph_lines.append(line)
        index += 1

    flush_paragraph()
    flush_unordered()
    flush_ordered()
    if in_code:
        flush_code()
    return blocks


def _clean_summary_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r", "\n")
    compact = " ".join(
        _markdown_inline_to_text(segment.strip())
        for segment in normalized.splitlines()
        if segment.strip() and not segment.strip().startswith("```")
    )
    for marker in ("- ", "* ", "1. ", "2. ", "3. "):
        compact = compact.replace(marker, " ")
    compact = " ".join(compact.split())
    return compact.strip()


def _model_primary_summary(answer: str) -> str:
    blocks = _markdown_blocks(answer)
    for block in blocks:
        if block.get("type") == "paragraph":
            text = _clean_summary_text(_to_str(block.get("text"), ""))
            if text:
                return text
        if block.get("type") == "heading":
            text = _clean_summary_text(_to_str(block.get("text"), ""))
            if text:
                return text
    return _clean_summary_text(answer)


def _model_highlights(answer: str, limit: int = 5) -> list[str]:
    blocks = _markdown_blocks(answer)
    highlights: list[str] = []
    for block in blocks:
        block_type = str(block.get("type", ""))
        if block_type in {"unordered_list", "ordered_list"}:
            items = block.get("items", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = _to_str(item.get("text"), "").strip()
                if not text:
                    continue
                highlights.append(text)
                if len(highlights) >= limit:
                    return highlights
        elif block_type == "paragraph":
            text = _to_str(block.get("text"), "").strip()
            if text:
                highlights.append(text)
                if len(highlights) >= limit:
                    return highlights
    if highlights:
        return highlights
    clean = _clean_summary_text(answer)
    return [clean] if clean else []


def _model_report_content(answer: str) -> dict[str, Any]:
    summary = _model_primary_summary(answer)
    highlights = _model_highlights(answer, limit=8)
    if not summary and highlights:
        summary = highlights[0]
    return {
        "value_statement": summary,
        "executive_summary": summary,
        "executive_highlights": highlights[:5],
        "key_findings": highlights,
        "impact_lines": highlights[:3],
        "model_markdown_blocks": _markdown_blocks(answer),
    }


def _section(title: str, columns: list[str], rows: list[list[str]], empty_text: str) -> dict[str, Any]:
    return {
        "title": title,
        "columns": columns,
        "rows": rows,
        "empty_text": empty_text,
    }


def _build_stockout_external(structured_output: dict[str, Any], answer: str) -> dict[str, Any]:
    model_content = _model_report_content(answer)
    risks = structured_output.get("risks", [])
    if not isinstance(risks, list):
        risks = []
    sorted_risks = sorted(
        [risk for risk in risks if isinstance(risk, dict)],
        key=lambda item: (_urgency_rank(str(item.get("urgency", ""))), _safe_float(item.get("days", 9999))),
    )

    critical_count = sum(1 for risk in sorted_risks if str(risk.get("urgency", "")).upper() == "CRITICAL")
    high_count = sum(1 for risk in sorted_risks if str(risk.get("urgency", "")).upper() == "HIGH")
    total_risk = sum(_safe_float(risk.get("revenue_at_risk", 0)) for risk in sorted_risks)

    action_plan: list[dict[str, str]] = []
    for risk in sorted_risks[:8]:
        urgency = str(risk.get("urgency", "")).upper()
        due = "24小时内" if urgency == "CRITICAL" else ("48小时内" if urgency == "HIGH" else "3个工作日内")
        actions = risk.get("actions", [])
        action_text = " / ".join([_to_str(item) for item in actions]) if isinstance(actions, list) and actions else "联系供应商并预置替代方案"
        action_plan.append(
            {
                "priority": _urgency_label(urgency),
                "action": f"SKU {_to_str(risk.get('sku'))}：{action_text}",
                "owner": "采购与库存运营",
                "due": due,
                "expected": "降低缺货概率并保障销售连续性",
            }
        )

    detail_rows = []
    for risk in sorted_risks:
        actions = risk.get("actions", [])
        action_text = " / ".join([_to_str(item) for item in actions]) if isinstance(actions, list) and actions else "-"
        detail_rows.append(
            [
                _to_str(risk.get("sku")),
                _urgency_label(risk.get("urgency")),
                f"{_to_str(risk.get('days'))} 天",
                _money(risk.get("revenue_at_risk", 0)),
                _to_str(risk.get("vendor_name", "-")),
                action_text,
            ]
        )

    summary_cards = [
        {"label": "风险商品数", "value": str(len(sorted_risks)), "note": "建议每天复核一次"},
        {"label": "紧急风险", "value": str(critical_count), "note": "优先在24小时内处理"},
        {"label": "预计风险金额", "value": _money(total_risk), "note": "按当前销量口径估算"},
    ]

    return {
        "report_title": "缺货风险行动报告",
        "value_statement": model_content["value_statement"],
        "executive_summary": model_content["executive_summary"],
        "executive_highlights": model_content["executive_highlights"],
        "summary_cards": summary_cards,
        "key_findings": model_content["key_findings"],
        "action_plan": action_plan,
        "impact_lines": model_content["impact_lines"],
        "detail_sections": [
            _section(
                "缺货风险明细",
                ["SKU", "风险等级", "预计缺货天数", "风险金额", "供应商", "建议动作"],
                detail_rows,
                "暂无缺货风险商品。",
            )
        ],
        "data_notice": "",
        "model_markdown_blocks": model_content["model_markdown_blocks"],
    }


def _build_exception_external(structured_output: dict[str, Any], answer: str) -> dict[str, Any]:
    model_content = _model_report_content(answer)
    anomalies = structured_output.get("anomalies", [])
    if not isinstance(anomalies, list):
        anomalies = []
    clean_anomalies = [item for item in anomalies if isinstance(item, dict)]

    type_count: dict[str, int] = {}
    for anomaly in clean_anomalies:
        key = str(anomaly.get("type", "unknown"))
        type_count[key] = type_count.get(key, 0) + 1

    ranked_types = sorted(type_count.items(), key=lambda item: item[1], reverse=True)
    action_plan: list[dict[str, str]] = []
    owner_map = {
        "velocity_reorder_mismatch": "库存运营",
        "price_outlier": "定价运营",
        "price_zscore_outlier": "定价运营",
        "velocity_zscore_outlier": "需求分析",
        "negative_margin": "商品运营",
        "zero_stock_positive_velocity": "库存运营",
        "stale_inventory": "商品运营",
    }
    for code, count in ranked_types[:6]:
        action_plan.append(
            {
                "priority": "高" if count >= 5 else "中",
                "action": f"处理「{_ANOMALY_LABELS.get(code, code)}」异常，完成口径修正与规则校验。",
                "owner": owner_map.get(code, _REPORT_DEFAULT_OWNER),
                "due": "2个工作日内",
                "expected": "提高补货与定价决策准确性",
            }
        )

    detail_rows = []
    for anomaly in clean_anomalies:
        detail_rows.append(
            [
                _to_str(anomaly.get("sku")),
                _ANOMALY_LABELS.get(str(anomaly.get("type", "")), _to_str(anomaly.get("type"))),
                _to_str(anomaly.get("note")),
                _to_str(anomaly.get("recommendation")),
            ]
        )

    summary_cards = [
        {"label": "异常总数", "value": str(len(clean_anomalies)), "note": "优先修复高频异常类型"},
        {"label": "异常类型数", "value": str(len(ranked_types)), "note": "反映库存数据稳定性"},
        {"label": "高频异常", "value": _ANOMALY_LABELS.get(ranked_types[0][0], ranked_types[0][0]) if ranked_types else "-", "note": "建议优先治理"},
    ]

    return {
        "report_title": "库存异常修复报告",
        "value_statement": model_content["value_statement"],
        "executive_summary": model_content["executive_summary"],
        "executive_highlights": model_content["executive_highlights"],
        "summary_cards": summary_cards,
        "key_findings": model_content["key_findings"],
        "action_plan": action_plan,
        "impact_lines": model_content["impact_lines"],
        "detail_sections": [
            _section(
                "异常明细与修复建议",
                ["SKU", "异常类型", "异常说明", "修复建议"],
                detail_rows,
                "暂无异常数据。",
            )
        ],
        "data_notice": "",
        "model_markdown_blocks": model_content["model_markdown_blocks"],
    }


def _build_markdown_external(structured_output: dict[str, Any], answer: str) -> dict[str, Any]:
    model_content = _model_report_content(answer)
    markdowns = structured_output.get("markdowns", [])
    if not isinstance(markdowns, list):
        markdowns = []
    clean_markdowns = [item for item in markdowns if isinstance(item, dict)]

    def _bucket_label(discount: float) -> str:
        if discount >= 0.5:
            return "180天以上清理层"
        if discount >= 0.3:
            return "90天清理层"
        if discount >= 0.2:
            return "60天清理层"
        return "45天优化层"

    bucket_count: dict[str, int] = {}
    for row in clean_markdowns:
        bucket = _bucket_label(_safe_float(row.get("recommended_markdown", 0)))
        bucket_count[bucket] = bucket_count.get(bucket, 0) + 1

    action_plan: list[dict[str, str]] = []
    for bucket, count in sorted(bucket_count.items(), key=lambda item: item[1], reverse=True):
        action_plan.append(
            {
                "priority": "高" if "180天" in bucket else "中",
                "action": f"执行「{bucket}」折扣策略，覆盖 {count} 个商品。",
                "owner": "商品与促销运营",
                "due": "本周内",
                "expected": "加快库存周转并提升现金回笼速度",
            }
        )

    detail_rows = []
    for row in clean_markdowns:
        detail_rows.append(
            [
                _to_str(row.get("SKU")),
                f"{round(_safe_float(row.get('recommended_markdown', 0)) * 100)}%",
                _to_str(row.get("days_to_clear")),
                _money(row.get("net_benefit", 0)),
                _to_str(row.get("status", "-")),
            ]
        )

    summary_cards = [
        {"label": "建议清理商品", "value": str(len(clean_markdowns)), "note": "建议按层级分批推进"},
        {"label": "最高折扣层商品", "value": str(bucket_count.get("180天以上清理层", 0)), "note": "优先回笼资金"},
        {"label": "预计净收益合计", "value": _money(sum(_safe_float(row.get("net_benefit", 0)) for row in clean_markdowns)), "note": "按当前折扣口径估算"},
    ]

    return {
        "report_title": "清仓与收益优化报告",
        "value_statement": model_content["value_statement"],
        "executive_summary": model_content["executive_summary"],
        "executive_highlights": model_content["executive_highlights"],
        "summary_cards": summary_cards,
        "key_findings": model_content["key_findings"],
        "action_plan": action_plan,
        "impact_lines": model_content["impact_lines"],
        "detail_sections": [
            _section(
                "清仓策略明细",
                ["SKU", "建议折扣", "预计清理周期(天)", "预估净收益", "状态"],
                detail_rows,
                "暂无清仓建议数据。",
            )
        ],
        "data_notice": "",
        "model_markdown_blocks": model_content["model_markdown_blocks"],
    }


def _build_replenishment_external(structured_output: dict[str, Any], tool_output: dict[str, Any], answer: str) -> dict[str, Any]:
    model_content = _model_report_content(answer)
    plan = structured_output.get("plan")
    if not isinstance(plan, dict):
        plan = {}
    if not plan and isinstance(tool_output, dict):
        plan = tool_output
    vendor_groups = plan.get("vendor_groups", [])
    if not isinstance(vendor_groups, list):
        vendor_groups = []
    groups = [item for item in vendor_groups if isinstance(item, dict)]

    total_cost = _safe_float(plan.get("total_cost", 0))
    unmet_count = sum(1 for item in groups if not bool(item.get("meets_minimum_order", True)))
    action_plan: list[dict[str, str]] = []
    for group in groups[:8]:
        meets = bool(group.get("meets_minimum_order", True))
        action_plan.append(
            {
                "priority": "高" if not meets else "中",
                "action": f"推进供应商 {_to_str(group.get('vendor_name', group.get('vendor_id')))} 的补货分单执行。",
                "owner": "采购运营",
                "due": "1-2个工作日内",
                "expected": "提升库存覆盖并降低缺货风险",
            }
        )

    detail_rows = []
    for group in groups:
        detail_rows.append(
            [
                _to_str(group.get("vendor_name", group.get("vendor_id"))),
                str(len(group.get("items", []))) if isinstance(group.get("items"), list) else "0",
                _money(group.get("total_cost", 0)),
                _money(group.get("minimum_order", 0)),
                f"{_safe_int(group.get('lead_time_days', 0))} 天",
                "满足起订" if bool(group.get("meets_minimum_order", True)) else _to_str(group.get("warning", "需复核")),
            ]
        )

    summary_cards = [
        {"label": "供应商分单数", "value": str(len(groups)), "note": "用于采购执行分派"},
        {"label": "预计采购金额", "value": _money(total_cost), "note": "按当前计划测算"},
        {"label": "待复核分单", "value": str(unmet_count), "note": "涉及起订约束"},
    ]

    return {
        "report_title": "补货执行计划报告",
        "value_statement": model_content["value_statement"],
        "executive_summary": model_content["executive_summary"],
        "executive_highlights": model_content["executive_highlights"],
        "summary_cards": summary_cards,
        "key_findings": model_content["key_findings"],
        "action_plan": action_plan,
        "impact_lines": model_content["impact_lines"],
        "detail_sections": [
            _section(
                "供应商补货分单",
                ["供应商", "SKU数", "计划金额", "起订要求", "交期", "结论"],
                detail_rows,
                "暂无可执行补货分单。",
            )
        ],
        "data_notice": "",
        "model_markdown_blocks": model_content["model_markdown_blocks"],
    }


def _workflow_status_label(value: str) -> str:
    return "已完成" if str(value).upper() == "DONE" else "失败"


def _team_result_status_label(value: str) -> str:
    status = str(value or "").strip().lower()
    if status == "success":
        return "已完成"
    if status == "partial_success":
        return "部分完成"
    if status == "timeout":
        return "超时失败"
    if status == "failed":
        return "失败"
    return "未知"


def _team_execution_to_workflow_results(team_execution: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for item in team_execution:
        if not isinstance(item, dict):
            continue
        member_id = str(item.get("member_id", "")).strip()
        if not member_id:
            continue
        raw_status = str(item.get("result_status", "")).strip().lower()
        status = "DONE" if raw_status == "success" else "FAILED"
        summary = _to_str(item.get("summary") or item.get("response_text") or item.get("error_code"), "无结论")
        member_structured = item.get("structured_output")
        if not isinstance(member_structured, dict):
            member_structured = {}
        mapped.append(
            {
                "label": _AGENT_LABELS.get(member_id, member_id),
                "agent_id": member_id,
                "status": status,
                "summary": summary,
                "response_text": _to_str(item.get("response_text")),
                "started_at": _to_str(item.get("started_at")),
                "finished_at": _to_str(item.get("ended_at")),
                "structured_output": member_structured,
            }
        )
    return mapped


def _safe_time_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def _estimate_metric(agent_id: str, structured_output: dict[str, Any]) -> str:
    if agent_id == "exception_investigator":
        anomalies = structured_output.get("anomalies", [])
        return f"异常条目 {len(anomalies) if isinstance(anomalies, list) else 0}"
    if agent_id == "stockout_sentinel":
        risks = structured_output.get("risks", [])
        return f"风险条目 {len(risks) if isinstance(risks, list) else 0}"
    if agent_id == "replenishment_planner":
        plan = structured_output.get("plan", {})
        groups = plan.get("vendor_groups", []) if isinstance(plan, dict) else []
        return f"供应商分单 {len(groups) if isinstance(groups, list) else 0}"
    if agent_id == "markdown_clearance_coach":
        markdowns = structured_output.get("markdowns", [])
        return f"清仓条目 {len(markdowns) if isinstance(markdowns, list) else 0}"
    return "-"


def _build_workflow_detail_sections(workflow_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    overview_rows: list[list[str]] = []
    for module in workflow_results:
        agent_id = str(module.get("agent_id", ""))
        module_label = _to_str(module.get("label") or _AGENT_LABELS.get(agent_id, "业务模块"))
        module_status = _workflow_status_label(str(module.get("status", "")))
        summary = _to_str(module.get("summary"), "无结论")
        started = _safe_time_text(module.get("started_at"))
        finished = _safe_time_text(module.get("finished_at"))
        module_structured = module.get("structured_output", {})
        if not isinstance(module_structured, dict):
            module_structured = {}
        overview_rows.append(
            [
                module_label,
                module_status,
                started,
                finished,
                summary,
                _estimate_metric(agent_id, module_structured),
            ]
        )

    sections.append(
        _section(
            "业务流程执行总览",
            ["模块", "状态", "开始时间", "结束时间", "结论摘要", "关键指标"],
            overview_rows,
            "暂无流程数据。",
        )
    )

    for module in workflow_results:
        agent_id = str(module.get("agent_id", ""))
        module_label = _to_str(module.get("label") or _AGENT_LABELS.get(agent_id, "业务模块"))
        module_structured = module.get("structured_output", {})
        if not isinstance(module_structured, dict):
            module_structured = {}

        if agent_id == "exception_investigator":
            anomalies = module_structured.get("anomalies", [])
            rows = []
            if isinstance(anomalies, list):
                for anomaly in anomalies:
                    if not isinstance(anomaly, dict):
                        continue
                    rows.append(
                        [
                            _to_str(anomaly.get("sku")),
                            _ANOMALY_LABELS.get(str(anomaly.get("type", "")), _to_str(anomaly.get("type"))),
                            _to_str(anomaly.get("note")),
                            _to_str(anomaly.get("recommendation")),
                        ]
                    )
            sections.append(
                _section(
                    f"{module_label}明细",
                    ["SKU", "异常类型", "异常说明", "修复建议"],
                    rows,
                    "该模块无异常明细。",
                )
            )
        elif agent_id == "stockout_sentinel":
            risks = module_structured.get("risks", [])
            rows = []
            if isinstance(risks, list):
                for risk in risks:
                    if not isinstance(risk, dict):
                        continue
                    actions = risk.get("actions", [])
                    actions_text = " / ".join([_to_str(item) for item in actions]) if isinstance(actions, list) and actions else "-"
                    rows.append(
                        [
                            _to_str(risk.get("sku")),
                            _urgency_label(risk.get("urgency")),
                            f"{_to_str(risk.get('days'))} 天",
                            _money(risk.get("revenue_at_risk", 0)),
                            _to_str(risk.get("vendor_name")),
                            actions_text,
                        ]
                    )
            sections.append(
                _section(
                    f"{module_label}明细",
                    ["SKU", "风险等级", "预计缺货天数", "风险金额", "供应商", "建议动作"],
                    rows,
                    "该模块无风险明细。",
                )
            )
        elif agent_id == "replenishment_planner":
            plan = module_structured.get("plan", {})
            if not isinstance(plan, dict):
                plan = {}
            groups = plan.get("vendor_groups", [])
            group_rows: list[list[str]] = []
            item_rows: list[list[str]] = []
            if isinstance(groups, list):
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    group_rows.append(
                        [
                            _to_str(group.get("vendor_name", group.get("vendor_id"))),
                            str(len(group.get("items", []))) if isinstance(group.get("items"), list) else "0",
                            _money(group.get("total_cost", 0)),
                            _money(group.get("minimum_order", 0)),
                            f"{_safe_int(group.get('lead_time_days', 0))} 天",
                            "满足起订" if bool(group.get("meets_minimum_order", True)) else _to_str(group.get("warning", "需复核")),
                        ]
                    )
                    items = group.get("items", [])
                    if isinstance(items, list):
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            item_rows.append(
                                [
                                    _to_str(item.get("SKU")),
                                    _to_str(group.get("vendor_name", group.get("vendor_id"))),
                                    str(_safe_int(item.get("recommended_qty", 0))),
                                    _money(item.get("unit_cost", 0)),
                                    _money(item.get("line_cost", 0)),
                                    _to_str(item.get("expected_delivery_date")),
                                ]
                            )
            sections.append(
                _section(
                    f"{module_label}-供应商分单",
                    ["供应商", "SKU数", "计划金额", "起订要求", "交期", "结论"],
                    group_rows,
                    "该模块无供应商分单。",
                )
            )
            sections.append(
                _section(
                    f"{module_label}-SKU补货明细",
                    ["SKU", "供应商", "建议数量", "单价", "行成本", "预计到货"],
                    item_rows,
                    "该模块无SKU补货明细。",
                )
            )
        elif agent_id == "markdown_clearance_coach":
            markdowns = module_structured.get("markdowns", [])
            rows = []
            if isinstance(markdowns, list):
                for row in markdowns:
                    if not isinstance(row, dict):
                        continue
                    rows.append(
                        [
                            _to_str(row.get("SKU")),
                            f"{round(_safe_float(row.get('recommended_markdown', 0)) * 100)}%",
                            _to_str(row.get("days_to_clear")),
                            _money(row.get("net_benefit", 0)),
                            _to_str(row.get("status")),
                        ]
                    )
            sections.append(
                _section(
                    f"{module_label}明细",
                    ["SKU", "建议折扣", "预计清理周期(天)", "预估净收益", "状态"],
                    rows,
                    "该模块无清仓明细。",
                )
            )
        else:
            generic_rows = [[_to_str(key), _to_str(value)] for key, value in module_structured.items()]
            sections.append(
                _section(
                    f"{module_label}明细",
                    ["字段", "内容"],
                    generic_rows,
                    "该模块无可展示明细。",
                )
            )

    return sections


def _build_copilot_external(structured_output: dict[str, Any], tool_output: dict[str, Any], answer: str) -> dict[str, Any]:
    model_content = _model_report_content(answer)
    status = _COPILOT_STATUS_LABELS.get(str(structured_output.get("status", "")), "执行中")

    team_execution = structured_output.get("team_execution", [])
    if not isinstance(team_execution, list):
        team_execution = []
    team_execution = [item for item in team_execution if isinstance(item, dict)]

    workflow_results = tool_output.get("workflow_results", []) if isinstance(tool_output, dict) else []
    if not isinstance(workflow_results, list):
        workflow_results = []
    workflow_results = [item for item in workflow_results if isinstance(item, dict)]
    if not workflow_results:
        workflow_results = _team_execution_to_workflow_results(team_execution)

    member_tool_outputs = tool_output.get("member_tool_outputs", {}) if isinstance(tool_output, dict) else {}
    if not isinstance(member_tool_outputs, dict):
        member_tool_outputs = {}
    rag_corpus = tool_output.get("rag_corpus", []) if isinstance(tool_output, dict) else []
    if not isinstance(rag_corpus, list):
        rag_corpus = []
    rag_trace = tool_output.get("rag_retrieval_trace", []) if isinstance(tool_output, dict) else []
    if not isinstance(rag_trace, list):
        rag_trace = []
    rag_summary = structured_output.get("rag_summary", {})
    if not isinstance(rag_summary, dict):
        rag_summary = {}

    action_plan: list[dict[str, str]] = []
    for module in workflow_results:
        module_status = str(module.get("status", "")).upper()
        if module_status == "DONE":
            continue
        module_label = _to_str(module.get("label") or _AGENT_LABELS.get(str(module.get("agent_id", "")), "业务模块"))
        action_plan.append(
            {
                "priority": "高",
                "action": f"{module_label}执行失败，建议人工复核后重跑该模块。",
                "owner": _REPORT_DEFAULT_OWNER,
                "due": "当日内",
                "expected": "恢复智能检测流程完整性",
            }
        )
    if not action_plan:
        action_plan.append(
            {
                "priority": "中",
                "action": "按模块执行既定运营动作并跟踪次日指标变化。",
                "owner": _REPORT_DEFAULT_OWNER,
                "due": "本周内",
                "expected": "形成稳定的库存运营闭环",
            }
        )

    summary_cards = [
        {"label": "执行状态", "value": status, "note": "反映当前任务进度"},
        {"label": "成员执行数", "value": str(len(team_execution)), "note": "本轮协同实际执行成员"},
        {"label": "RAG证据数", "value": str(len(rag_corpus)), "note": "用于结论可追溯"},
        {"label": "RAG检索次数", "value": str(len(rag_trace)), "note": "成员执行前的检索次数"},
    ]

    overview_rows: list[list[str]] = []
    raw_output_rows: list[list[str]] = []
    for item in team_execution:
        member_id = str(item.get("member_id") or "").strip()
        member_label = _AGENT_LABELS.get(member_id, member_id or "成员")
        overview_rows.append(
            [
                member_label,
                _team_result_status_label(_to_str(item.get("result_status"))),
                _safe_time_text(item.get("started_at")),
                _safe_time_text(item.get("ended_at")),
                _to_str(item.get("summary"), "无结论"),
            ]
        )
        raw_output_rows.append(
            [
                member_label,
                _team_result_status_label(_to_str(item.get("result_status"))),
                _to_str(item.get("response_text") or item.get("summary"), "-"),
            ]
        )

    tool_output_rows: list[list[str]] = []
    for member_id, outputs in member_tool_outputs.items():
        member_label = _AGENT_LABELS.get(str(member_id), str(member_id))
        if isinstance(outputs, dict) and outputs:
            for key, value in outputs.items():
                tool_output_rows.append([member_label, _to_str(key), _to_str(value)])
        else:
            tool_output_rows.append([member_label, "-", "无工具输出"])

    rag_corpus_rows: list[list[str]] = []
    for row in rag_corpus:
        if not isinstance(row, dict):
            continue
        rag_corpus_rows.append(
            [
                _to_str(row.get("evidence_id")),
                _AGENT_LABELS.get(_to_str(row.get("member_id"), ""), _to_str(row.get("member_id"), "")),
                _to_str(row.get("tool_name")),
                _to_str(row.get("title_cn")),
                _to_str(row.get("content_text_cn")),
                _safe_time_text(row.get("created_at")),
            ]
        )

    rag_trace_rows: list[list[str]] = []
    for row in rag_trace:
        if not isinstance(row, dict):
            continue
        member_id = _to_str(row.get("member_id"), "")
        hits = row.get("hits", [])
        hit_text = "-"
        if isinstance(hits, list) and hits:
            hit_text = " | ".join(
                [
                    f"{_to_str(hit.get('evidence_id'))}:{_to_str(hit.get('title_cn'))}"
                    for hit in hits
                    if isinstance(hit, dict)
                ]
            )
        rag_trace_rows.append(
            [
                _AGENT_LABELS.get(member_id, member_id),
                _to_str(row.get("query"), "-"),
                str(len(hits) if isinstance(hits, list) else 0),
                hit_text,
            ]
        )

    anomalies_rows: list[list[str]] = []
    stockout_rows: list[list[str]] = []
    replenishment_rows: list[list[str]] = []
    markdown_rows: list[list[str]] = []
    for item in team_execution:
        if not isinstance(item, dict):
            continue
        member_id = str(item.get("member_id") or "").strip()
        member_structured = item.get("structured_output")
        if not isinstance(member_structured, dict):
            member_structured = {}
        if member_id == "exception_investigator":
            anomalies = member_structured.get("anomalies", [])
            if isinstance(anomalies, list):
                for row in anomalies:
                    if not isinstance(row, dict):
                        continue
                    anomalies_rows.append(
                        [
                            _to_str(row.get("sku")),
                            _ANOMALY_LABELS.get(_to_str(row.get("type"), ""), _to_str(row.get("type"))),
                            _to_str(row.get("note")),
                            _to_str(row.get("recommendation")),
                        ]
                    )
        elif member_id == "stockout_sentinel":
            risks = member_structured.get("risks", [])
            if isinstance(risks, list):
                for row in risks:
                    if not isinstance(row, dict):
                        continue
                    stockout_rows.append(
                        [
                            _to_str(row.get("sku")),
                            _urgency_label(row.get("urgency")),
                            _to_str(row.get("days")),
                            _money(row.get("revenue_at_risk", 0)),
                            _to_str(row.get("vendor_name")),
                        ]
                    )
        elif member_id == "replenishment_planner":
            plan = member_structured.get("plan", {})
            if isinstance(plan, dict):
                groups = plan.get("vendor_groups", [])
                if isinstance(groups, list):
                    for group in groups:
                        if not isinstance(group, dict):
                            continue
                        items = group.get("items", [])
                        if isinstance(items, list) and items:
                            for sku_item in items:
                                if not isinstance(sku_item, dict):
                                    continue
                                replenishment_rows.append(
                                    [
                                        _to_str(sku_item.get("SKU")),
                                        _to_str(group.get("vendor_name", group.get("vendor_id"))),
                                        _to_str(sku_item.get("recommended_qty")),
                                        _money(sku_item.get("line_cost", 0)),
                                        _to_str(sku_item.get("expected_delivery_date")),
                                    ]
                                )
                        else:
                            replenishment_rows.append(
                                [
                                    "-",
                                    _to_str(group.get("vendor_name", group.get("vendor_id"))),
                                    "0",
                                    _money(group.get("total_cost", 0)),
                                    "-",
                                ]
                            )
        elif member_id == "markdown_clearance_coach":
            markdowns = member_structured.get("markdowns", [])
            if isinstance(markdowns, list):
                for row in markdowns:
                    if not isinstance(row, dict):
                        continue
                    markdown_rows.append(
                        [
                            _to_str(row.get("SKU")),
                            f"{round(_safe_float(row.get('recommended_markdown', 0)) * 100)}%",
                            _to_str(row.get("days_to_clear")),
                            _money(row.get("net_benefit", 0)),
                            _to_str(row.get("status")),
                        ]
                    )

    detail_sections = [
        _section("成员执行总览", ["成员", "执行状态", "开始时间", "结束时间", "结论摘要"], overview_rows, "暂无成员执行数据。"),
        _section("成员原始结论", ["成员", "执行状态", "原始输出"], raw_output_rows, "暂无成员原始输出。"),
        _section("成员工具输出总表", ["成员", "字段", "内容"], tool_output_rows, "暂无成员工具输出。"),
        _section("RAG证据库", ["证据ID", "成员", "工具", "标题", "内容摘要", "创建时间"], rag_corpus_rows, "暂无RAG证据。"),
        _section("RAG检索轨迹", ["成员", "检索问题", "命中证据数", "命中详情"], rag_trace_rows, "暂无RAG检索轨迹。"),
        _section("异常明细", ["SKU", "异常类型", "异常说明", "修复建议"], anomalies_rows, "暂无异常明细。"),
        _section("缺货明细", ["SKU", "风险等级", "预计缺货天数", "风险金额", "供应商"], stockout_rows, "暂无缺货明细。"),
        _section("补货明细", ["SKU", "供应商", "建议数量", "行成本", "预计到货"], replenishment_rows, "暂无补货明细。"),
        _section("清仓明细", ["SKU", "建议折扣", "预计清理周期(天)", "预估净收益", "状态"], markdown_rows, "暂无清仓明细。"),
    ]

    return {
        "report_title": "综合运营编排报告",
        "value_statement": model_content["value_statement"],
        "executive_summary": model_content["executive_summary"],
        "executive_highlights": model_content["executive_highlights"],
        "summary_cards": summary_cards,
        "key_findings": model_content["key_findings"],
        "action_plan": action_plan,
        "impact_lines": model_content["impact_lines"],
        "detail_sections": detail_sections,
        "data_notice": f"RAG目录：{_to_str(rag_summary.get('run_dir'), '-')}",
        "model_markdown_blocks": model_content["model_markdown_blocks"],
    }


def _build_generic_external(agent_label: str, structured_output: dict[str, Any], answer: str) -> dict[str, Any]:
    model_content = _model_report_content(answer)
    summary_cards = [
        {"label": "结构化字段数", "value": str(len(structured_output)), "note": "用于结果完整性判断"},
        {"label": "报告对象", "value": agent_label, "note": "本次分析智能体"},
        {"label": "执行建议", "value": "已生成", "note": "可进入行动分派"},
    ]
    detail_rows = [[_to_str(key), _to_str(value)] for key, value in structured_output.items()]
    return {
        "report_title": f"{agent_label}运营报告",
        "value_statement": model_content["value_statement"],
        "executive_summary": model_content["executive_summary"],
        "executive_highlights": model_content["executive_highlights"],
        "summary_cards": summary_cards,
        "key_findings": model_content["key_findings"],
        "action_plan": [],
        "impact_lines": model_content["impact_lines"],
        "detail_sections": [
            _section("结果摘要", ["字段", "内容"], detail_rows, "暂无可展示内容。")
        ],
        "data_notice": "",
        "model_markdown_blocks": model_content["model_markdown_blocks"],
    }


def _build_external_report(
    agent_id: str,
    structured_output: dict[str, Any],
    tool_output: dict[str, Any],
    answer: str,
    preferred_title: str,
) -> dict[str, Any]:
    agent_label = _AGENT_LABELS.get(agent_id, "智能体")
    if agent_id == "stockout_sentinel":
        report = _build_stockout_external(structured_output, answer)
    elif agent_id == "exception_investigator":
        report = _build_exception_external(structured_output, answer)
    elif agent_id == "markdown_clearance_coach":
        report = _build_markdown_external(structured_output, answer)
    elif agent_id == "replenishment_planner":
        report = _build_replenishment_external(structured_output, tool_output, answer)
    elif agent_id == "inventory_copilot":
        report = _build_copilot_external(structured_output, tool_output, answer)
    else:
        report = _build_generic_external(agent_label, structured_output, answer)

    report["agent_label"] = agent_label
    report["report_title"] = preferred_title
    return report


def _build_analysis_context(req: ExportRequest) -> dict[str, Any]:
    payload = req.payload if isinstance(req.payload, dict) else {}
    analysis = payload.get("analysis", {})
    if not isinstance(analysis, dict):
        analysis = {}

    structured_output = analysis.get("structured_output", {})
    if not isinstance(structured_output, dict):
        structured_output = {}

    tool_trace = analysis.get("tool_trace", [])
    if not isinstance(tool_trace, list):
        tool_trace = []
    tool_trace_rows: list[dict[str, Any]] = []
    for trace in tool_trace:
        if isinstance(trace, dict):
            tool_trace_rows.append(
                {
                    "tool": str(trace.get("tool", "-")),
                    "apiPath": str(trace.get("apiPath", "-")),
                    "httpStatusCode": str(trace.get("httpStatusCode", "-")),
                    "args_text": _as_json_text(trace.get("args", {})),
                }
            )
        else:
            tool_trace_rows.append(
                {
                    "tool": "-",
                    "apiPath": "-",
                    "httpStatusCode": "-",
                    "args_text": str(trace),
                }
            )

    raw_tool_output = analysis.get("tool_output", {})
    tool_output = raw_tool_output if isinstance(raw_tool_output, dict) else {}

    agent_id = str(analysis.get("agent_id") or req.agent_id or "")
    answer = str(analysis.get("answer") or "")
    effective_title = _safe_title(req.scope, req.title, agent_id)
    external_report = _build_external_report(agent_id, structured_output, tool_output, answer, effective_title)

    reasoning = str(analysis.get("reasoning") or "")
    if req.audience != "internal":
        reasoning = ""

    plan_steps = structured_output.get("plan") if isinstance(structured_output.get("plan"), list) else []
    past_steps = structured_output.get("past_steps") if isinstance(structured_output.get("past_steps"), list) else []
    remaining_steps = (
        structured_output.get("remaining_plan") if isinstance(structured_output.get("remaining_plan"), list) else []
    )
    structured_output_text = _as_json_text(structured_output)

    return {
        "title": effective_title,
        "generated_at": _iso_now(),
        "audience": req.audience,
        "analysis": {
            "agent_id": agent_id,
            "question": str(analysis.get("question") or ""),
            "answer": answer,
            "reasoning": reasoning,
            "structured_output": structured_output,
            "structured_output_text": structured_output_text,
            "plan_steps": plan_steps,
            "past_steps": past_steps,
            "remaining_steps": remaining_steps,
            "tool_trace": tool_trace,
            "tool_trace_rows": tool_trace_rows,
            "tool_output": tool_output,
            "request_id": str(analysis.get("request_id") or ""),
            "model": str(analysis.get("model") or ""),
            "timestamp": str(analysis.get("timestamp") or ""),
            "external_report": external_report,
        },
    }


def _build_context(req: ExportRequest) -> dict[str, Any]:
    if req.scope == "global":
        return _build_global_context(req)
    if req.scope == "session":
        return _build_session_context(req)
    if req.scope == "analysis":
        return _build_analysis_context(req)
    return _build_table_context(req)


def _limit_analysis_context_for_pdf(context: dict[str, Any]) -> dict[str, Any]:
    limited = copy.deepcopy(context)
    if str(limited.get("audience", "")) != "external":
        return limited
    analysis = limited.get("analysis", {})
    if not isinstance(analysis, dict):
        return limited
    external = analysis.get("external_report", {})
    if not isinstance(external, dict):
        return limited
    answer = str(analysis.get("answer") or "")
    structured_output = analysis.get("structured_output")
    if not isinstance(structured_output, dict):
        structured_output = {}
    team_execution = structured_output.get("team_execution", [])
    if not isinstance(team_execution, list):
        team_execution = []

    lines: list[str] = [
        "# 最终结论",
        answer or "（无最终结论）",
    ]
    if team_execution:
        lines.append("")
        lines.append("# 成员完整结论")
        for item in team_execution:
            if not isinstance(item, dict):
                continue
            member_id = str(item.get("member_id") or "").strip()
            member_label = str(item.get("member_label") or "").strip() or _AGENT_LABELS.get(member_id, member_id or "成员")
            member_text = str(item.get("response_text") or "").strip() or str(item.get("summary") or "").strip() or "（无成员结论）"
            lines.append(f"## {member_label}")
            lines.append(member_text)
            lines.append("")
    merged_model_text = "\n".join(lines).strip()
    model_content = _model_report_content(merged_model_text)
    answer_content = _model_report_content(answer)

    # PDF 仅展示模型输出内容（最终结论+成员完整结论），不展示业务数据明细。
    external["value_statement"] = answer_content["value_statement"]
    external["executive_summary"] = answer_content["executive_summary"]
    external["executive_highlights"] = answer_content["executive_highlights"]
    external["key_findings"] = answer_content["key_findings"]
    external["impact_lines"] = answer_content["impact_lines"]
    external["model_markdown_blocks"] = model_content["model_markdown_blocks"]
    external["summary_cards"] = []
    external["action_plan"] = []
    external["detail_sections"] = []
    external["data_notice"] = "PDF 仅展示模型输出内容；业务数据请导出 Excel。"
    analysis["external_report"] = external
    limited["analysis"] = analysis
    return limited


def _run_pdf_render_with_timeout(*, scope: str, context: dict[str, Any], output_path: Path, timeout_seconds: int) -> None:
    timeout = max(5, int(timeout_seconds))
    result: dict[str, Any] = {"error": None}
    done = threading.Event()

    def _worker() -> None:
        try:
            render_scope_pdf(scope=scope, context=context, output_path=output_path)
        except Exception as exc:  # pragma: no cover - runtime dependent
            result["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_worker, name=f"pdf-render-{output_path.stem}", daemon=True)
    worker.start()
    if not done.wait(timeout=timeout):
        raise RuntimeError(f"PDF 导出超时：超过 {timeout} 秒未完成，请改用 Excel 或缩小导出范围。")
    if result["error"] is not None:
        raise RuntimeError(str(result["error"]))


def execute_export_job(job_id: str, req: ExportRequest) -> None:
    running = store.update_job(job_id, status="RUNNING", progress=15, error_message=None)
    if not running:
        return
    output_path = Path(running.output_path)
    try:
        effective_req = req.model_copy(update={"title": running.title})
        context = _build_context(effective_req)
        store.update_job(job_id, progress=60)

        if effective_req.format == "pdf":
            pdf_context = context
            if effective_req.scope == "analysis":
                pdf_context = _limit_analysis_context_for_pdf(context)
            store.update_job(job_id, progress=80)
            _run_pdf_render_with_timeout(
                scope=effective_req.scope,
                context=pdf_context,
                output_path=output_path,
                timeout_seconds=settings.report_pdf_timeout_seconds,
            )
        else:
            store.update_job(job_id, progress=80)
            render_scope_xlsx(scope=effective_req.scope, context=context, output_path=output_path)

        store.update_job(
            job_id,
            status="DONE",
            progress=100,
            error_message=None,
        )
    except Exception as exc:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass
        store.update_job(
            job_id,
            status="FAILED",
            progress=100,
            error_message=str(exc)[:400],
        )


def _dispatch_with_thread(job_id: str, req: ExportRequest) -> None:
    worker = threading.Thread(
        target=execute_export_job,
        args=(job_id, req),
        name=f"export-job-{job_id[:8]}",
        daemon=True,
    )
    worker.start()


def _dispatch_with_subprocess(job_id: str, req: ExportRequest) -> None:
    payload_path = _request_payload_path(job_id)
    payload_path.write_text(
        json.dumps(req.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    configured_python = settings.report_worker_python.strip()
    if configured_python:
        python_bin = configured_python
    else:
        default_worker = _PROJECT_ROOT / "demo" / "bin" / "python"
        python_bin = str(default_worker) if default_worker.exists() else sys.executable
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "").strip()
    project_path = str(_PROJECT_ROOT)
    env["PYTHONPATH"] = (
        f"{project_path}{os.pathsep}{current_pythonpath}" if current_pythonpath else project_path
    )
    command = [
        python_bin,
        "-m",
        "app.reports.worker",
        "--job-id",
        job_id,
        "--request-file",
        str(payload_path),
    ]
    subprocess.Popen(
        command,
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def dispatch_export_job(job_id: str, req: ExportRequest) -> None:
    mode = settings.report_dispatch_mode.strip().lower()
    if mode == "thread" or os.environ.get("PYTEST_CURRENT_TEST"):
        _dispatch_with_thread(job_id, req)
        return
    try:
        _dispatch_with_subprocess(job_id, req)
    except Exception as exc:
        try:
            _request_payload_path(job_id).unlink(missing_ok=True)
        except Exception:
            pass
        store.update_job(
            job_id,
            status="FAILED",
            progress=100,
            error_message=f"导出任务派发失败：{str(exc)[:200]}",
        )


def get_export_job(job_id: str) -> ExportJobRecord:
    _cleanup_expired()
    record = store.get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Export job not found")
    return record


def export_status_payload(job_id: str) -> dict[str, Any]:
    record = get_export_job(job_id)
    payload = {
        "success": True,
        "job_id": record.job_id,
        "status": record.status,
        "progress": record.progress,
        "error_message": record.error_message,
    }
    if record.status == "DONE":
        payload["download_url"] = f"/reports/exports/{record.job_id}/download"
    return payload


def resolve_download(job_id: str) -> tuple[Path, str]:
    record = get_export_job(job_id)
    if record.status == "EXPIRED":
        raise HTTPException(status_code=404, detail="Export job expired")
    if record.status != "DONE":
        raise HTTPException(status_code=409, detail="Export file is not ready")
    path = Path(record.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    filename = os.path.basename(record.output_path)
    return path, filename
