from __future__ import annotations

from .mini_chart import render_panel_shell


def render_intraday_panel() -> str:
    return render_panel_shell("分时图", "intradayPanel", "优先展示当前最重要标的的盘中变化，并标注最近动作。")
