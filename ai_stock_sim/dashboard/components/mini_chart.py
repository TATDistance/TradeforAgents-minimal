from __future__ import annotations


def render_panel_shell(title: str, body_id: str, subtext: str = "") -> str:
    note = f'<div class="subvalue" style="margin-bottom:10px">{subtext}</div>' if subtext else ""
    return (
        '<div class="card span-12">'
        f"<h3>{title}</h3>"
        f"{note}"
        f'<div id="{body_id}" class="empty">正在加载图表数据…</div>'
        "</div>"
    )
