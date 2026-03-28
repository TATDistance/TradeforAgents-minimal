from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Deque, Iterable, List, Mapping, Optional, Sequence

from .db import fetch_rows_by_sql, write_mode_comparison, write_strategy_evaluation
from .metrics_service import (
    calc_expectancy,
    calc_longest_loss_streak,
    calc_longest_win_streak,
    calc_max_drawdown,
    calc_monthly_positive_ratio,
    calc_profit_factor,
    calc_profit_loss_ratio,
    calc_return_drawdown_ratio,
    calc_total_return,
    calc_win_rate,
)
from .models import ModeComparison, StrategyEvaluation
from .scoring_service import ScoringService
from .settings import Settings, load_settings


@dataclass
class ClosedTrade:
    symbol: str
    closed_ts: datetime
    pnl: float
    return_pct: float
    qty: int
    side: str
    strategy_name: str
    exit_strategy_name: str
    mode_name: str


class EvaluationService:
    def __init__(self, settings: Settings | None = None, scoring_service: ScoringService | None = None) -> None:
        self.settings = settings or load_settings()
        self.scoring = scoring_service or ScoringService(self.settings)

    def compute_daily_metrics(
        self,
        conn,
        trade_date: str,
        strategy_name: str = "portfolio_actual",
        attribution: str = "entry",
    ) -> StrategyEvaluation:
        target_date = datetime.fromisoformat(trade_date).date()
        snapshots = self._load_snapshots(conn, start_date=target_date, end_date=target_date)
        closed_trades = self._load_closed_trades(
            conn,
            strategy_name=strategy_name,
            start_date=target_date,
            end_date=target_date,
            attribution=attribution,
        )
        return self._build_evaluation(
            strategy_name=strategy_name,
            period_type="daily",
            period_start=target_date.isoformat(),
            period_end=target_date.isoformat(),
            snapshots=snapshots,
            closed_trades=closed_trades,
        )

    def compute_weekly_metrics(
        self,
        conn,
        week_start: str,
        week_end: str,
        strategy_name: str = "portfolio_actual",
        attribution: str = "entry",
    ) -> StrategyEvaluation:
        start = datetime.fromisoformat(week_start).date()
        end = datetime.fromisoformat(week_end).date()
        snapshots = self._load_snapshots(conn, start_date=start, end_date=end)
        closed_trades = self._load_closed_trades(
            conn,
            strategy_name=strategy_name,
            start_date=start,
            end_date=end,
            attribution=attribution,
        )
        return self._build_evaluation(
            strategy_name=strategy_name,
            period_type="weekly",
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            snapshots=snapshots,
            closed_trades=closed_trades,
        )

    def compute_monthly_metrics(
        self,
        conn,
        month: str,
        strategy_name: str = "portfolio_actual",
        attribution: str = "entry",
    ) -> StrategyEvaluation:
        period_start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        period_end = next_month - timedelta(days=1)
        snapshots = self._load_snapshots(conn, start_date=period_start, end_date=period_end)
        closed_trades = self._load_closed_trades(
            conn,
            strategy_name=strategy_name,
            start_date=period_start,
            end_date=period_end,
            attribution=attribution,
        )
        return self._build_evaluation(
            strategy_name=strategy_name,
            period_type="monthly",
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            snapshots=snapshots,
            closed_trades=closed_trades,
        )

    def compute_rolling_trade_metrics(
        self,
        conn,
        last_n_trades: int = 20,
        strategy_name: str = "portfolio_actual",
        attribution: str = "entry",
    ) -> StrategyEvaluation:
        closed_trades = self._load_closed_trades(conn, strategy_name=strategy_name, attribution=attribution)
        selected = closed_trades[-last_n_trades:] if last_n_trades > 0 else closed_trades
        if selected:
            start = selected[0].closed_ts.date()
            end = selected[-1].closed_ts.date()
            snapshots = self._load_snapshots(conn, start_date=start, end_date=end)
        else:
            snapshots = []
        return self._build_evaluation(
            strategy_name=strategy_name,
            period_type=f"rolling_trade_{last_n_trades}",
            period_start=selected[0].closed_ts.date().isoformat() if selected else None,
            period_end=selected[-1].closed_ts.date().isoformat() if selected else None,
            snapshots=snapshots,
            closed_trades=selected,
        )

    def compute_rolling_day_metrics(
        self,
        conn,
        last_n_days: int = 20,
        strategy_name: str = "portfolio_actual",
        attribution: str = "entry",
    ) -> StrategyEvaluation:
        snapshots = self._load_snapshots(conn)
        daily_snapshots = self._compress_daily_snapshots(snapshots)
        selected_daily = daily_snapshots[-last_n_days:] if last_n_days > 0 else daily_snapshots
        if selected_daily:
            start = datetime.fromisoformat(str(selected_daily[0]["ts"])).date()
            end = datetime.fromisoformat(str(selected_daily[-1]["ts"])).date()
        else:
            start = None
            end = None
        closed_trades = self._load_closed_trades(
            conn,
            strategy_name=strategy_name,
            start_date=start,
            end_date=end,
            attribution=attribution,
        )
        return self._build_evaluation(
            strategy_name=strategy_name,
            period_type=f"rolling_day_{last_n_days}",
            period_start=start.isoformat() if start else None,
            period_end=end.isoformat() if end else None,
            snapshots=selected_daily,
            closed_trades=closed_trades,
        )

    def compute_mode_comparisons(self, conn) -> List[ModeComparison]:
        proxies = self._build_signal_mode_proxies(conn)
        actual_by_mode = self._actual_mode_returns(conn)
        comparisons: List[ModeComparison] = []
        mode_order = [
            "legacy_review_mode",
            "ai_decision_engine_mode",
            "strategy_only",
            "strategy_plus_ai",
            "strategy_plus_risk",
            "strategy_plus_ai_plus_risk",
        ]
        for mode_name in mode_order:
            values = actual_by_mode.get(mode_name) or proxies.get(mode_name) or []
            if not values:
                basis = "actual_closed_trades" if mode_name in actual_by_mode else "signal_forward_return_proxy"
                comparison = ModeComparison(mode_name=mode_name, metadata_json=json.dumps({"basis": basis, "trades": 0}, ensure_ascii=False))
                comparisons.append(comparison)
                continue
            total_return = sum(values)
            win_rate = calc_win_rate(values).value
            profit_factor = calc_profit_factor(values).value
            expectancy = calc_expectancy(values).value
            drawdown = calc_max_drawdown(self._equity_curve_from_returns(values)).value
            score = self.scoring.score_strategy(
                mode_name,
                {
                    "total_return": total_return,
                    "monthly_return": total_return / max(len(values), 1),
                    "expectancy": expectancy,
                    "max_drawdown": drawdown,
                    "current_drawdown": drawdown,
                    "monthly_positive_ratio": 1.0 if total_return > 0 else 0.0,
                    "return_volatility": self._return_volatility(values),
                    "longest_loss_streak": calc_longest_loss_streak(values).value,
                    "pnl_ratio": calc_profit_loss_ratio(values).value,
                    "profit_factor": profit_factor,
                    "signal_hit_rate": win_rate,
                    "risk_events": 0,
                },
            )
            comparisons.append(
                ModeComparison(
                    mode_name=mode_name,
                    total_return=round(total_return, 6),
                    max_drawdown=round(drawdown, 6),
                    win_rate=round(win_rate, 6),
                    profit_factor=round(0.0 if profit_factor == float("inf") else profit_factor, 6),
                    expectancy=round(expectancy, 6),
                    score_total=round(score.score_total, 2),
                    metadata_json=json.dumps(
                        {
                            "basis": "actual_closed_trades" if mode_name in actual_by_mode else "signal_forward_return_proxy",
                            "trades": len(values),
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        return comparisons

    def persist_evaluations(self, conn, reference_date: str | None = None) -> dict[str, object]:
        trade_date = reference_date or datetime.now().date().isoformat()
        target_date = datetime.fromisoformat(trade_date).date()
        week_start = target_date - timedelta(days=target_date.weekday())
        month_label = target_date.strftime("%Y-%m")
        evaluations = [
            self.compute_daily_metrics(conn, trade_date),
            self.compute_weekly_metrics(conn, week_start.isoformat(), trade_date),
            self.compute_monthly_metrics(conn, month_label),
        ]
        for window in self.settings.evaluation.rolling_trade_windows:
            evaluations.append(self.compute_rolling_trade_metrics(conn, last_n_trades=int(window)))
        for window in self.settings.evaluation.rolling_day_windows:
            evaluations.append(self.compute_rolling_day_metrics(conn, last_n_days=int(window)))
        for evaluation in evaluations:
            write_strategy_evaluation(conn, evaluation)

        strategy_names = self._strategy_names()
        for strategy_name in strategy_names:
            write_strategy_evaluation(conn, self.compute_daily_metrics(conn, trade_date, strategy_name=strategy_name, attribution="entry"))
            rolling_trade_window = int(self.settings.evaluation.rolling_trade_windows[0]) if self.settings.evaluation.rolling_trade_windows else 20
            write_strategy_evaluation(
                conn,
                self.compute_rolling_trade_metrics(conn, last_n_trades=rolling_trade_window, strategy_name=strategy_name, attribution="entry"),
            )

            exit_name = f"exit::{strategy_name}"
            write_strategy_evaluation(conn, self.compute_daily_metrics(conn, trade_date, strategy_name=exit_name, attribution="exit"))
            write_strategy_evaluation(
                conn,
                self.compute_rolling_trade_metrics(conn, last_n_trades=rolling_trade_window, strategy_name=exit_name, attribution="exit"),
            )

        comparisons = self.compute_mode_comparisons(conn)
        for comparison in comparisons:
            write_mode_comparison(conn, comparison)

        return {"evaluations": evaluations, "comparisons": comparisons}

    def _build_evaluation(
        self,
        strategy_name: str,
        period_type: str,
        period_start: Optional[str],
        period_end: Optional[str],
        snapshots: Sequence[Mapping[str, object]],
        closed_trades: Sequence[ClosedTrade],
    ) -> StrategyEvaluation:
        trade_pnls = [trade.pnl for trade in closed_trades]
        trade_returns = [trade.return_pct for trade in closed_trades]
        wins = [value for value in trade_pnls if value > 0]
        losses = [abs(value) for value in trade_pnls if value < 0]
        equity_curve = [float(row["equity"]) for row in snapshots] if snapshots else []
        drawdown_result = calc_max_drawdown(equity_curve)
        current_drawdown = float(drawdown_result.details.get("current_drawdown", 0.0) or 0.0)
        if len(equity_curve) >= 2:
            total_return_result = calc_total_return(equity_curve[0], equity_curve[-1])
        else:
            total_return_result = calc_total_return(1.0, 1.0 + sum(trade_returns))
        monthly_returns = self._monthly_returns_from_snapshots(snapshots)
        recent_window = trade_pnls[-20:]
        metrics = {
            "total_return": total_return_result.value,
            "monthly_return": total_return_result.value,
            "max_drawdown": drawdown_result.value,
            "current_drawdown": current_drawdown,
            "win_rate": calc_win_rate(trade_pnls).value,
            "pnl_ratio": self._finite_metric(calc_profit_loss_ratio(trade_pnls).value),
            "profit_factor": self._finite_metric(calc_profit_factor(trade_pnls).value),
            "expectancy": calc_expectancy(trade_pnls).value,
            "return_drawdown_ratio": self._finite_metric(calc_return_drawdown_ratio(total_return_result.value, drawdown_result.value).value),
            "monthly_positive_ratio": calc_monthly_positive_ratio(monthly_returns).value,
            "recent_win_rate": calc_win_rate(recent_window).value,
            "recent_profit_factor": self._finite_metric(calc_profit_factor(recent_window).value),
            "recent_expectancy": calc_expectancy(recent_window).value,
            "longest_win_streak": calc_longest_win_streak(trade_pnls).value,
            "longest_loss_streak": calc_longest_loss_streak(trade_pnls).value,
            "max_single_win": max(trade_pnls, default=0.0),
            "max_single_loss": min(trade_pnls, default=0.0),
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(losses) / len(losses) if losses else 0.0,
            "signal_hit_rate": calc_win_rate(trade_returns).value,
            "risk_events": 0,
            "return_volatility": self._return_volatility(trade_returns),
        }
        score = self.scoring.score_strategy(strategy_name, metrics)
        metadata = {
            "trade_count": len(closed_trades),
            "period_start": period_start,
            "period_end": period_end,
            "longest_win_streak": metrics["longest_win_streak"],
            "longest_loss_streak": metrics["longest_loss_streak"],
            "max_single_win": metrics["max_single_win"],
            "max_single_loss": metrics["max_single_loss"],
            "avg_win": metrics["avg_win"],
            "avg_loss": metrics["avg_loss"],
        }
        return StrategyEvaluation(
            strategy_name=strategy_name,
            period_type=period_type,
            total_return=round(metrics["total_return"], 6),
            max_drawdown=round(metrics["max_drawdown"], 6),
            current_drawdown=round(metrics["current_drawdown"], 6),
            win_rate=round(metrics["win_rate"], 6),
            pnl_ratio=round(metrics["pnl_ratio"], 6),
            profit_factor=round(metrics["profit_factor"], 6),
            expectancy=round(metrics["expectancy"], 6),
            return_drawdown_ratio=round(metrics["return_drawdown_ratio"], 6),
            monthly_positive_ratio=round(metrics["monthly_positive_ratio"], 6),
            recent_win_rate=round(metrics["recent_win_rate"], 6),
            recent_profit_factor=round(metrics["recent_profit_factor"], 6),
            recent_expectancy=round(metrics["recent_expectancy"], 6),
            score_total=score.score_total,
            score_return=score.score_return,
            score_risk=score.score_risk,
            score_stability=score.score_stability,
            score_execution=score.score_execution,
            grade=score.grade,
            status=score.status,
            total_trades=len(closed_trades),
            period_start=period_start,
            period_end=period_end,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )

    def _load_snapshots(self, conn, start_date: date | None = None, end_date: date | None = None) -> List[Mapping[str, object]]:
        sql = "SELECT * FROM account_snapshots"
        conditions: List[str] = []
        params: List[object] = []
        if start_date:
            conditions.append("date(ts) >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date(ts) <= ?")
            params.append(end_date.isoformat())
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY ts ASC, id ASC"
        return [dict(row) for row in fetch_rows_by_sql(conn, sql, params)]

    def _load_closed_trades(
        self,
        conn,
        strategy_name: str = "portfolio_actual",
        start_date: date | None = None,
        end_date: date | None = None,
        attribution: str = "entry",
    ) -> List[ClosedTrade]:
        sql = "SELECT * FROM orders WHERE status IN ('FILLED', 'PARTIAL_FILLED')"
        params: List[object] = []
        if start_date:
            sql += " AND date(ts) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            sql += " AND date(ts) <= ?"
            params.append(end_date.isoformat())
        sql += " ORDER BY ts ASC, id ASC"
        rows = [dict(row) for row in fetch_rows_by_sql(conn, sql, params)]
        inventories: dict[str, Deque[dict[str, float | str]]] = defaultdict(deque)
        closed_trades: List[ClosedTrade] = []
        for row in rows:
            symbol = str(row["symbol"])
            qty = int(row["qty"] or 0)
            if qty <= 0:
                continue
            ts = datetime.fromisoformat(str(row["ts"]))
            side = str(row["side"]).upper()
            price = float(row["price"] or 0.0)
            fee = float(row["fee"] or 0.0)
            tax = float(row["tax"] or 0.0)
            slippage = float(row["slippage"] or 0.0)
            strategy_value = str(row.get("strategy_name") or strategy_name)
            mode_value = str(row.get("mode_name") or "strategy_plus_ai_plus_risk")
            if side == "BUY":
                unit_cost = (price * qty + fee + tax + slippage) / max(qty, 1)
                inventories[symbol].append(
                    {"qty": float(qty), "unit_cost": unit_cost, "strategy_name": strategy_value, "mode_name": mode_value}
                )
                continue
            unit_sell = (price * qty - fee - tax - slippage) / max(qty, 1)
            remaining = qty
            while remaining > 0 and inventories[symbol]:
                lot = inventories[symbol][0]
                lot_qty = int(lot["qty"])
                matched = min(remaining, lot_qty)
                buy_cost = float(lot["unit_cost"]) * matched
                sell_value = unit_sell * matched
                pnl = sell_value - buy_cost
                return_pct = 0.0 if buy_cost <= 0 else pnl / buy_cost
                closed_trades.append(
                    ClosedTrade(
                        symbol=symbol,
                        closed_ts=ts,
                        pnl=pnl,
                        return_pct=return_pct,
                        qty=matched,
                        side=side,
                        strategy_name=str(lot["strategy_name"]),
                        exit_strategy_name=str(strategy_value),
                        mode_name=str(lot["mode_name"]),
                    )
                )
                remaining -= matched
                if matched >= lot_qty:
                    inventories[symbol].popleft()
                else:
                    lot["qty"] = float(lot_qty - matched)
        if strategy_name == "portfolio_actual":
            return closed_trades
        if attribution == "exit":
            exit_key = strategy_name.replace("exit::", "", 1)
            return [trade for trade in closed_trades if trade.exit_strategy_name == exit_key]
        return [trade for trade in closed_trades if trade.strategy_name == strategy_name]

    def _compress_daily_snapshots(self, snapshots: Sequence[Mapping[str, object]]) -> List[Mapping[str, object]]:
        by_day: dict[str, Mapping[str, object]] = {}
        for row in snapshots:
            ts = datetime.fromisoformat(str(row["ts"]))
            by_day[ts.date().isoformat()] = row
        return [by_day[key] for key in sorted(by_day)]

    def _monthly_returns_from_snapshots(self, snapshots: Sequence[Mapping[str, object]]) -> List[float]:
        if not snapshots:
            return []
        by_month: dict[str, List[float]] = defaultdict(list)
        for row in self._compress_daily_snapshots(snapshots):
            ts = datetime.fromisoformat(str(row["ts"]))
            by_month[ts.strftime("%Y-%m")].append(float(row["equity"]))
        returns: List[float] = []
        for values in by_month.values():
            if len(values) >= 2 and values[0] > 0:
                returns.append((values[-1] - values[0]) / values[0])
            elif values:
                returns.append(0.0)
        return returns

    def _build_signal_mode_proxies(self, conn) -> dict[str, List[float]]:
        signal_rows = [dict(row) for row in fetch_rows_by_sql(conn, "SELECT * FROM signals ORDER BY ts ASC, id ASC")]
        ai_rows = [dict(row) for row in fetch_rows_by_sql(conn, "SELECT * FROM ai_decisions ORDER BY ts ASC, id ASC")]
        ai_map = {(str(row["symbol"]), str(row["ts"])[:10]): row for row in ai_rows}
        grouped: dict[tuple[str, str], List[Mapping[str, object]]] = defaultdict(list)
        for row in signal_rows:
            grouped[(str(row["symbol"]), str(row["ts"])[:10])].append(row)

        comparisons: dict[str, List[float]] = {
            "legacy_review_mode": [],
            "ai_decision_engine_mode": [],
            "strategy_only": [],
            "strategy_plus_ai": [],
            "strategy_plus_risk": [],
            "strategy_plus_ai_plus_risk": [],
        }
        for (symbol, signal_date), rows in grouped.items():
            if len(rows) < 2:
                continue
            by_action: dict[str, List[Mapping[str, object]]] = defaultdict(list)
            for row in rows:
                by_action[str(row["action"]).upper()].append(row)
            dominant_action, same_side = max(by_action.items(), key=lambda item: len(item[1]))
            if dominant_action == "HOLD" or len(same_side) < 2:
                continue
            entry_price = sum(float(row["signal_price"]) for row in same_side) / len(same_side)
            position_pct = min(sum(float(row["position_pct"]) for row in same_side) / len(same_side), self.settings.max_single_position_pct)
            proxy_return = self._proxy_forward_return(symbol=symbol, signal_date=signal_date, entry_price=entry_price, action=dominant_action)
            if proxy_return is None:
                continue
            comparisons["strategy_only"].append(proxy_return)
            risk_pass = position_pct <= self.settings.max_single_position_pct and entry_price > 0
            ai_row = ai_map.get((symbol, signal_date))
            ai_pass = bool(ai_row and int(ai_row.get("approved") or 0) == 1 and str(ai_row.get("ai_action") or "").upper() != "HOLD")
            if ai_pass and risk_pass:
                comparisons["legacy_review_mode"].append(proxy_return)
            if ai_pass:
                comparisons["strategy_plus_ai"].append(proxy_return)
            if risk_pass:
                comparisons["strategy_plus_risk"].append(proxy_return)
            if ai_pass and risk_pass:
                comparisons["strategy_plus_ai_plus_risk"].append(proxy_return)
        return comparisons

    def _actual_mode_returns(self, conn) -> dict[str, List[float]]:
        closed_trades = self._load_closed_trades(conn, strategy_name="portfolio_actual")
        grouped: dict[str, List[float]] = defaultdict(list)
        for trade in closed_trades:
            grouped[str(trade.mode_name or "legacy_review_mode")].append(float(trade.return_pct))
        return grouped

    def _proxy_forward_return(self, symbol: str, signal_date: str, entry_price: float, action: str) -> Optional[float]:
        try:
            from .market_data_service import MarketDataService

            history = MarketDataService(self.settings).fetch_history_daily(symbol=symbol, limit=120)
        except Exception:
            return None
        if history.empty or "trade_date" not in history.columns:
            return None
        date_values = [str(value)[:10] for value in history["trade_date"].tolist()]
        if signal_date not in date_values:
            return None
        index = date_values.index(signal_date)
        if index + 5 >= len(history):
            return None
        future_close = float(history.iloc[index + 5]["close"])
        if entry_price <= 0:
            return None
        raw_return = (future_close - entry_price) / entry_price
        return raw_return if action == "BUY" else -raw_return

    @staticmethod
    def _equity_curve_from_returns(returns: Sequence[float]) -> List[float]:
        equity = 1.0
        curve = [equity]
        for item in returns:
            equity *= 1.0 + float(item)
            curve.append(equity)
        return curve

    @staticmethod
    def _finite_metric(value: float) -> float:
        if value == float("inf"):
            return 999.0
        if value == float("-inf"):
            return -999.0
        return float(value)

    @staticmethod
    def _return_volatility(values: Sequence[float]) -> float:
        if len(values) <= 1:
            return 0.0
        avg = sum(values) / len(values)
        variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
        return variance ** 0.5

    @staticmethod
    def _strategy_names() -> List[str]:
        from .strategy_engine import STRATEGY_REGISTRY

        return sorted(STRATEGY_REGISTRY.keys())
