from __future__ import annotations

from .mini_chart import render_panel_shell


def render_kline_panel() -> str:
    return render_panel_shell("K 线图", "klinePanel", "最近 N 日价格区间、收盘线和动作标记。")
