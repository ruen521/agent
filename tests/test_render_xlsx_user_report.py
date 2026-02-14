from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

from app.reports.render_xlsx import render_scope_xlsx


class _FakeWorksheet:
    def write(self, *_args, **_kwargs) -> None:
        return None

    def set_column(self, *_args, **_kwargs) -> None:
        return None


class _FakeWorkbook:
    latest: "_FakeWorkbook | None" = None

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.sheet_names: list[str] = []
        _FakeWorkbook.latest = self

    def add_worksheet(self, name: str) -> _FakeWorksheet:
        self.sheet_names.append(name)
        return _FakeWorksheet()

    def add_format(self, *_args, **_kwargs):
        return {}

    def close(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"fake-xlsx")


def test_analysis_xlsx_contains_team_v1_full_detail_sheets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "xlsxwriter", SimpleNamespace(Workbook=_FakeWorkbook))

    output_path = tmp_path / "analysis.xlsx"
    context = {
        "generated_at": "2026-02-11T00:00:00+00:00",
        "audience": "external",
        "analysis": {
            "agent_id": "inventory_copilot",
            "question": "今天巡检情况如何",
            "answer": "已完成巡检并给出建议。",
            "external_report": {
                "report_title": "运营编排建议-2026.2.11",
                "agent_label": "库存助手",
                "summary_cards": [{"label": "风险项", "value": "3", "note": "需本周处理"}],
                "action_plan": [
                    {
                        "priority": "高",
                        "action": "优先补货 APP-001",
                        "owner": "采购",
                        "due": "24小时内",
                        "expected": "降低缺货风险",
                    }
                ],
                "detail_sections": [
                    {"title": "成员执行总览", "columns": ["成员", "状态"], "rows": [["异常侦测", "成功"]]},
                    {"title": "成员原始结论", "columns": ["成员", "原始输出"], "rows": [["缺货哨兵", "已识别风险"]]},
                    {"title": "成员工具输出总表", "columns": ["成员", "字段", "内容"], "rows": [["补货规划", "vendor_groups", "..."]]},
                    {"title": "RAG证据库", "columns": ["证据ID", "成员"], "rows": [["ev-1", "异常侦测"]]},
                    {"title": "RAG检索轨迹", "columns": ["成员", "检索问题"], "rows": [["清仓教练", "检索滞销证据"]]},
                    {"title": "异常明细", "columns": ["SKU", "异常类型"], "rows": [["APP-001", "价格偏离"]]},
                    {"title": "缺货明细", "columns": ["SKU", "风险等级"], "rows": [["APP-002", "高"]]},
                    {"title": "补货明细", "columns": ["SKU", "建议数量"], "rows": [["APP-002", "120"]]},
                    {"title": "清仓明细", "columns": ["SKU", "建议折扣"], "rows": [["APP-090", "50%"]]},
                ],
            },
        },
    }

    render_scope_xlsx(scope="analysis", context=context, output_path=output_path)
    names = _FakeWorkbook.latest.sheet_names if _FakeWorkbook.latest else []

    assert "报告概览" in names
    assert "摘要卡片" in names
    assert "行动计划" in names
    assert "成员执行总览" in names
    assert "成员原始结论" in names
    assert "成员工具输出总表" in names
    assert "RAG证据库" in names
    assert "RAG检索轨迹" in names
    assert "异常明细" in names
    assert "缺货明细" in names
    assert "补货明细" in names
    assert "清仓明细" in names
