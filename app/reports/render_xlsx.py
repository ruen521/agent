from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _write_kv_sheet(workbook: Any, name: str, data: dict[str, Any]) -> None:
    ws = workbook.add_worksheet(name[:31])
    header_fmt = workbook.add_format({"bold": True, "bg_color": "#E9EFF7"})
    ws.write(0, 0, "字段", header_fmt)
    ws.write(0, 1, "值", header_fmt)
    row = 1
    for key, value in data.items():
        ws.write(row, 0, key)
        if isinstance(value, (dict, list)):
            ws.write(row, 1, json.dumps(value, ensure_ascii=False))
        else:
            ws.write(row, 1, str(value))
        row += 1
    ws.set_column(0, 0, 24)
    ws.set_column(1, 1, 80)


def _write_table_sheet(
    workbook: Any,
    name: str,
    rows: list[dict[str, Any]],
) -> None:
    ws = workbook.add_worksheet(name[:31])
    header_fmt = workbook.add_format({"bold": True, "bg_color": "#E9EFF7"})
    if not rows:
        ws.write(0, 0, "无数据")
        return

    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key in seen:
                continue
            seen.add(key)
            columns.append(key)

    for index, column in enumerate(columns):
        ws.write(0, index, column, header_fmt)
        ws.set_column(index, index, 18)

    for r, row in enumerate(rows, start=1):
        for c, column in enumerate(columns):
            value = row.get(column, "")
            if isinstance(value, (dict, list)):
                ws.write(r, c, json.dumps(value, ensure_ascii=False))
            else:
                ws.write(r, c, value)


def _write_list_sheet(workbook: Any, name: str, header: str, values: list[str]) -> None:
    ws = workbook.add_worksheet(name[:31])
    header_fmt = workbook.add_format({"bold": True, "bg_color": "#E9EFF7"})
    ws.write(0, 0, header, header_fmt)
    ws.set_column(0, 0, 110)
    if not values:
        ws.write(1, 0, "无数据")
        return
    for index, value in enumerate(values, start=1):
        ws.write(index, 0, str(value))


def _clean_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[:\\/?*\[\]]", "_", str(name))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "业务明细"


def _unique_sheet_name(base_name: str, used_names: set[str]) -> str:
    base = _clean_sheet_name(base_name)[:31]
    if base not in used_names:
        used_names.add(base)
        return base

    serial = 2
    while True:
        suffix = f"_{serial}"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        serial += 1


def _write_external_detail_sections(workbook: Any, sections: list[dict[str, Any]]) -> None:
    used_sheet_names: set[str] = set()
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title", "")).strip()
        columns = section.get("columns", [])
        rows = section.get("rows", [])
        if not isinstance(columns, list) or not isinstance(rows, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list):
                continue
            normalized_row: dict[str, Any] = {}
            for col_idx, col_name in enumerate(columns):
                key = str(col_name or f"col_{col_idx + 1}")
                normalized_row[key] = row[col_idx] if col_idx < len(row) else ""
            normalized_rows.append(normalized_row)
        default_title = f"业务明细_{index}"
        sheet_name = _unique_sheet_name(title or default_title, used_sheet_names)
        _write_table_sheet(workbook, sheet_name, normalized_rows)


def _write_analysis_user_report(workbook: Any, analysis: dict[str, Any], generated_at: str, audience: str) -> None:
    external = analysis.get("external_report", {})
    if not isinstance(external, dict):
        external = {}

    report_title = str(external.get("report_title") or "分析报告")
    agent_label = str(external.get("agent_label") or analysis.get("agent_id") or "智能体")
    question = str(analysis.get("question", ""))
    _write_kv_sheet(
        workbook,
        "报告概览",
        {
            "报告标题": report_title,
            "智能体": agent_label,
            "问题": question,
            "导出时间": generated_at,
            "导出对象": audience,
            "说明": "本文件展示本轮 Team V1 全量结构化数据与RAG证据。",
        },
    )

    summary_cards = external.get("summary_cards", [])
    if isinstance(summary_cards, list):
        normalized_cards = [item for item in summary_cards if isinstance(item, dict)]
        if normalized_cards:
            _write_table_sheet(workbook, "摘要卡片", normalized_cards)

    action_plan = external.get("action_plan", [])
    if isinstance(action_plan, list):
        normalized_actions = [item for item in action_plan if isinstance(item, dict)]
        if normalized_actions:
            _write_table_sheet(workbook, "行动计划", normalized_actions)

    detail_sections = external.get("detail_sections", [])
    if isinstance(detail_sections, list):
        _write_external_detail_sections(workbook, detail_sections)


def render_scope_xlsx(
    *,
    scope: str,
    context: dict[str, Any],
    output_path: Path,
) -> None:
    try:
        import xlsxwriter
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        raise RuntimeError("Excel 导出不可用：XlsxWriter 依赖缺失。") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(output_path))
    try:
        if scope != "analysis":
            _write_kv_sheet(
                workbook,
                "Summary",
                {
                    "标题": context.get("title", ""),
                    "范围": scope,
                    "导出类型": context.get("audience", "external"),
                    "导出时间": context.get("generated_at", ""),
                },
            )

        if scope == "global":
            _write_kv_sheet(workbook, "Overview", context.get("stats", {}))
            _write_table_sheet(workbook, "StockoutRisks", context.get("risks", []))
            _write_table_sheet(workbook, "Inventory", context.get("inventory", []))
            _write_table_sheet(
                workbook,
                "AgentSummaries",
                context.get("latest_agent_summaries", []),
            )
        elif scope == "analysis":
            analysis = context.get("analysis", {})
            if not isinstance(analysis, dict):
                analysis = {}
            _write_analysis_user_report(
                workbook,
                analysis,
                str(context.get("generated_at", "")),
                str(context.get("audience", "")),
            )
        elif scope == "session":
            _write_kv_sheet(
                workbook,
                "SessionMeta",
                {
                    "session_id": context.get("session_id", ""),
                    "agent_id": context.get("agent_id", ""),
                    "message_count": len(context.get("messages", [])),
                },
            )
            _write_table_sheet(workbook, "SessionMessages", context.get("messages", []))
        else:
            _write_kv_sheet(workbook, "TableMeta", context.get("filters", {}))
            _write_table_sheet(workbook, "TableRows", context.get("rows", []))
    finally:
        workbook.close()
