from __future__ import annotations

"""
Optional vn.py strategy skeleton.

This file is intentionally lightweight so the MVP can live on systems where
vn.py and related addons are not fully installed yet.
"""

try:
    from vnpy_ctastrategy import BarData, CtaTemplate
except ImportError:  # pragma: no cover - only used when vn.py addons are absent
    class CtaTemplate(object):  # type: ignore
        parameters = []
        variables = []

        def __init__(self, *args, **kwargs):
            pass

    class BarData(object):  # type: ignore
        close_price = 0.0


class AiSignalStrategy(CtaTemplate):
    author = "Codex"
    fixed_size = 100
    signal_path = "signals.csv"

    parameters = ["fixed_size", "signal_path"]
    variables = []

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super(AiSignalStrategy, self).__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.current_signal = None

    def on_init(self) -> None:
        self.write_log("AiSignalStrategy initialized. Wire your SQLite or CSV signal loader here.")

    def on_start(self) -> None:
        self.write_log("AiSignalStrategy started.")

    def on_stop(self) -> None:
        self.write_log("AiSignalStrategy stopped.")

    def on_bar(self, bar: BarData) -> None:
        """
        Suggested next step:
        1. Load the latest approved signal for this symbol.
        2. Map signal action to buy/sell requests.
        3. Keep actual risk checks outside the vn.py callback where possible.
        """
        _ = bar
