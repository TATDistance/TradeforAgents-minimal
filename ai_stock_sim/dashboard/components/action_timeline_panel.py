from __future__ import annotations

from .mini_chart import render_panel_shell


def render_action_timeline_panel() -> str:
    return render_panel_shell("动作时间线", "actionTimelinePanel", "按时间倒序展示意图、成交和被拦截动作。")
