from __future__ import annotations

from .mini_chart import render_panel_shell


def render_equity_curve_panel() -> str:
    return render_panel_shell("账户收益曲线", "equityCurvePanel", "展示总资产、持仓市值与回撤变化。")
