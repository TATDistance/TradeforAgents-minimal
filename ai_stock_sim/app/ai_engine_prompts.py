from __future__ import annotations

import json
from typing import Mapping


SYSTEM_PROMPT = """你是中国 A 股实时模拟系统里的组合级 AI 决策器。

你的职责：
1. 基于结构化上下文，对单个标的给出 BUY / SELL / REDUCE / HOLD / AVOID_NEW_BUY 建议。
2. 你不是最终执行者，不能绕过风控。
3. 必须遵守 A 股约束：100 股整数倍、T+1、涨跌停与流动性限制。
4. 不要输出长篇报告，不要输出 Markdown，只输出结构化 JSON。
5. 仓位建议必须保守，优先考虑账户回撤、现金比例和当前风险模式。
"""


OUTPUT_PROTOCOL = {
    "symbol": "000630",
    "action": "BUY",
    "position_pct": 0.12,
    "reduce_pct": None,
    "confidence": 0.78,
    "risk_mode": "NORMAL",
    "holding_bias": "SHORT_TERM",
    "reason": "多因子共振，趋势与账户风险匹配",
    "warnings": ["成交额下降", "不宜追高"],
}


def build_user_prompt(context: Mapping[str, object]) -> str:
    return (
        "请根据以下 A 股实时上下文生成结构化决策，不要省略字段。\n"
        "上下文如下：\n"
        f"{json.dumps(dict(context), ensure_ascii=False, indent=2)}\n\n"
        "输出协议如下：\n"
        f"{json.dumps(OUTPUT_PROTOCOL, ensure_ascii=False, indent=2)}"
    )
