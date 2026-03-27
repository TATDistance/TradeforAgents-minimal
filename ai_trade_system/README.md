# AI Trade System MVP

This workspace adds a practical bridge between:

- `tools/TradeforAgents-minimal`
- `tools/vnpy-4.3.0/vnpy-4.3.0`

The MVP follows a safer China A-share workflow:

1. AI analysis
2. Structured signal conversion
3. Risk checks
4. Paper trading
5. Manual real-account execution

## Layout

```text
ai_trade_system/
├── README.md
├── __init__.py
├── engine/
│   ├── __init__.py
│   ├── bridge_service.py
│   ├── config.py
│   ├── db.py
│   ├── market_data.py
│   ├── mock_broker.py
│   ├── plan_center.py
│   ├── pre_filter_engine.py
│   ├── ranking_engine.py
│   ├── review_service.py
│   ├── risk_engine.py
│   ├── scheduler.py
│   └── universe_service.py
├── scripts/
│   ├── __init__.py
│   ├── bootstrap_db.py
│   ├── run_daily_plan.py
│   ├── run_auto_pipeline.py
│   ├── run_watchlist.py
│   └── run_review.py
└── strategies/
    ├── __init__.py
    └── ai_signal_strategy.py
```

## Default integration paths

- TradeforAgents results:
  `tools/TradeforAgents-minimal/results`
- Project home:
  `tools/ai_trade_system`
- SQLite database:
  `tools/ai_trade_system/data/db.sqlite3`
- Daily plans:
  `tools/ai_trade_system/reports/daily_plan_YYYY-MM-DD.md`

You can override them with:

```bash
export AI_TRADE_SYSTEM_HOME=/home/alientek/workspace/tools/ai_trade_system
export TRADEFORAGENTS_RESULTS_DIR=/home/alientek/workspace/tools/TradeforAgents-minimal/results
export AI_TRADE_DB_PATH=/home/alientek/workspace/tools/ai_trade_system/data/db.sqlite3
export VN_PY_HOME=/home/alientek/workspace/tools/vnpy-4.3.0/vnpy-4.3.0
```

Compatibility note:

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

There is also a compatibility symlink at `~/workspace/ai_trade_system`, so your old command style still works from the workspace root.

## Quick start

Initialize the database and a paper account:

```bash
python3 -m ai_trade_system.scripts.bootstrap_db --cash 100000
```

Ingest latest AI reports, run risk checks, and generate a plan:

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

Batch analyze a watchlist before generating the plan:

```bash
python3 -m ai_trade_system.scripts.run_watchlist --symbols-file /home/alientek/workspace/tools/ai_trade_system/config/watchlist.example.txt --mode quick
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

Run the automatic stock-selection pipeline:

```bash
bash /home/alientek/workspace/tools/ai_trade_system/scripts/run_auto_pipeline.sh --skip-ai
```

Run the full after-close pipeline:

```bash
bash /home/alientek/workspace/tools/ai_trade_system/scripts/run_auto_pipeline.sh --mode quick --execute-sim
```

Generate a performance review:

```bash
python3 -m ai_trade_system.scripts.run_review
```

Run paper execution for approved signals:

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --execute-sim
```

## What the MVP already does

- Reads `decision.json` and `analysis_metadata.json`
- Converts AI output into structured `buy/sell/hold` signals
- Applies A-share lot sizing and T+1 aware checks
- Maintains a local paper account in SQLite
- Creates a daily manual execution plan
- Produces a compact review report from simulated trades
- Supports batch watchlist analysis through the TradeforAgents CLI
- Scans a broader A-share universe, filters weak/illiquid names, and ranks top candidates before sending them to AI
- Uses a dedicated Python 3.10 environment with AKShare for A-share universe and daily-bar acquisition when available

## What remains external

- Real broker execution
- Real-time market data feed
- Native vn.py gateway integration

## Notes

- This MVP stays compatible with Python 3.8 style syntax for Ubuntu 20.04.
- The current `TradeforAgents-minimal` `decision.json` does not include entry, stop, or take-profit fields, so the bridge layer derives them with deterministic rules.
- Upstream vn.py 4.3.0 recommends newer Python and Ubuntu versions, so this workspace keeps vn.py usage optional and focused on strategy research scaffolding.
- Automatic universe scan prefers AKShare in `tools/ai_trade_system/.venv310`, then falls back to Eastmoney public quote endpoints, and finally to local `TradeforAgents` snapshots if live data is unavailable.
