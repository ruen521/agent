from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


def render_scope_pdf(
    *,
    scope: str,
    context: dict[str, Any],
    output_path: Path,
) -> None:
    try:
        from weasyprint import CSS, HTML
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        raise RuntimeError(
            "PDF 导出不可用：WeasyPrint 运行依赖缺失，请先安装系统库。"
        ) from exc

    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template_name = {
        "global": "report_global.html",
        "session": "report_session.html",
        "table": "report_table.html",
        "analysis": "report_analysis.html",
    }.get(scope, "report_table.html")
    template = env.get_template(template_name)
    html_content = template.render(**context)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    css_path = template_dir / "report.css"
    HTML(string=html_content).write_pdf(
        str(output_path),
        stylesheets=[CSS(filename=str(css_path))],
    )
