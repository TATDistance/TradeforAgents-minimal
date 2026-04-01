from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _is_transient_market_data_error(message: str | None) -> bool:
    text = str(message or "").lower()
    if not text:
        return False
    markers = [
        "push2.eastmoney.com",
        "nameResolutionError".lower(),
        "failed to resolve",
        "temporarily failed in name resolution",
        "httpsconnectionpool",
        "max retries exceeded",
        "connection aborted",
        "read timed out",
    ]
    return any(marker in text for marker in markers)


def build_system_status(
    *,
    engine_running: bool,
    last_updated_at: str | None,
    last_error: str | None,
    last_error_ts: str | None = None,
    refresh_interval_seconds: int = 10,
) -> Dict[str, object]:
    updated_dt = _parse_ts(last_updated_at)
    error_dt = _parse_ts(last_error_ts)
    now = datetime.now()
    stale_seconds = max(30, int(refresh_interval_seconds) * 3)
    state = "stopped"
    label = "未运行"
    if engine_running:
        stale = not updated_dt or (now - updated_dt).total_seconds() > stale_seconds
        error_newer = bool(error_dt and (not updated_dt or error_dt >= updated_dt))
        transient_data_error = error_newer and _is_transient_market_data_error(last_error)
        if stale or (error_newer and not transient_data_error):
            state = "error"
            label = "运行异常"
        else:
            state = "running"
            label = "运行中"
    return {
        "state": state,
        "label": label,
        "last_updated_at": last_updated_at,
        "last_error": last_error,
        "last_error_ts": last_error_ts,
    }


def build_ai_strategy_status(
    actions: Iterable[Dict[str, object]],
    ai_decisions: Iterable[Dict[str, object]],
    manager_decision: Dict[str, object] | None,
    ai_runtime: Dict[str, str] | None = None,
) -> Dict[str, str]:
    rows = list(actions)
    risk_mode = str((manager_decision or {}).get("risk_mode") or "")
    if not risk_mode:
        decision_modes = {str(item.get("risk_mode") or "") for item in ai_decisions}
        risk_mode = next((mode for mode in decision_modes if mode), "NORMAL")
    buy_count = sum(1 for row in rows if str(row.get("display_action")) == "BUY")
    sell_like = sum(1 for row in rows if str(row.get("display_action")) in {"SELL", "REDUCE"})
    avoid_count = sum(1 for row in rows if str(row.get("display_action")) == "AVOID")
    if risk_mode == "RISK_OFF":
        strategy_style = "风险关闭"
        position_strategy = "暂停新开仓"
    elif risk_mode == "DEFENSIVE":
        strategy_style = "防守"
        position_strategy = "优先控制回撤"
    elif buy_count > sell_like and buy_count > 0:
        strategy_style = "进攻"
        position_strategy = "逐步加仓"
    elif sell_like > 0:
        strategy_style = "收缩"
        position_strategy = "优先处理持仓"
    elif avoid_count > 0:
        strategy_style = "谨慎"
        position_strategy = "等待更强信号"
    else:
        strategy_style = "平衡"
        position_strategy = "维持观察"
    result = {
        "risk_mode": risk_mode,
        "strategy_style": strategy_style,
        "position_strategy": position_strategy,
    }
    if ai_runtime:
        result.update(
            {
                "ai_status": str(ai_runtime.get("ai_status") or ""),
                "ai_source": str(ai_runtime.get("ai_source") or ""),
            }
        )
    return result


def build_home_summary(
    *,
    system_status: Dict[str, object],
    phase: Dict[str, object],
    actions: List[Dict[str, object]],
    strategy_status: Dict[str, str],
) -> str:
    state = str(system_status.get("state") or "stopped")
    phase_label = str(phase.get("phase_label") or phase.get("phase") or "")
    if state == "stopped":
        return "系统未运行，当前展示最近一次 AI 决策快照。"
    if state == "error":
        return "系统运行异常，请优先查看调试面板确认最近错误。"
    executable = [row for row in actions if bool(row.get("executable_now"))]
    blocked = [row for row in actions if bool(row.get("blocked"))]
    if executable:
        top = executable[0]
        return "今日建议：{0}，优先关注 {1} {2}。".format(
            strategy_status.get("position_strategy") or "按计划执行",
            top.get("symbol"),
            top.get("name") or "",
        ).strip()
    if blocked:
        return "当前处于 {0}，系统已有动作意图，但暂不允许真实成交。".format(phase_label or "受限阶段")
    if str(phase.get("phase")) == "POST_CLOSE":
        return "今日建议：收盘后以复盘和次日准备动作为主。"
    return "今日建议：当前无高优先级可执行动作，继续观察市场。"


def build_no_buy_reasons(
    *,
    system_status: Dict[str, object],
    phase: Dict[str, object],
    execution: Dict[str, object],
    actions: List[Dict[str, object]],
    strategy_status: Dict[str, str],
) -> List[str]:
    reasons: List[str] = []
    if str(system_status.get("state") or "") == "stopped":
        reasons.append("实时引擎当前未运行，首页只展示最近一次决策快照。")
        return reasons
    if str(system_status.get("state") or "") == "error":
        reasons.append("实时引擎当前处于异常状态，新的买入动作会优先被抑制。")

    if not bool(phase.get("is_trading_day")):
        reasons.append("今天不是 A 股交易日，系统不会生成新的可成交买入单。")
    if not bool(execution.get("can_open_position")):
        reasons.append("当前阶段不允许新开仓，所以即使有观察信号也不会直接买入。")

    blocked_buys = [
        row for row in actions
        if str(row.get("display_action") or "") == "BUY" and bool(row.get("blocked"))
    ]
    if blocked_buys:
        top = blocked_buys[0]
        reasons.append(
            "已有买入意图，但被执行权限或风控拦截：{0} {1}".format(
                top.get("symbol") or "",
                top.get("reason") or "当前条件不足以执行",
            ).strip()
        )

    position_actions = [
        row for row in actions
        if str(row.get("display_action") or "") in {"SELL", "REDUCE"}
    ]
    if position_actions:
        reasons.append("本轮更偏向持仓管理，系统优先考虑减仓、卖出或继续观察。")

    risk_mode = str(strategy_status.get("risk_mode") or "")
    if risk_mode in {"DEFENSIVE", "RISK_OFF"}:
        reasons.append("当前风险模式偏防守，新开仓信号会被显著收缩。")

    if not reasons:
        reasons.append("当前没有达到买入阈值的高优先级信号，系统选择继续观察。")
    return reasons[:4]
