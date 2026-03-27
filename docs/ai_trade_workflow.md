# AI Trade Workflow

## Overview

This repository now includes a practical after-close workflow for China A-share trading:

1. Auto-select candidates after market close
2. Run AI analysis on shortlisted names
3. Convert AI output into structured signals
4. Apply A-share risk rules
5. Generate a next-day trade plan
6. Run paper-trading validation
7. Review the result and execute manually in a broker app

This is intentionally designed for:

- China A-shares
- No broker API
- Paper-trading first
- Manual real-account execution

It is not designed for:

- Fully automated live trading
- Intraday high-frequency execution
- Broker account synchronization

## Main Components

### 1. TradeforAgents-minimal

Primary responsibilities:

- Single-stock AI analysis
- Watchlist batch analysis
- Share-page generation
- Web UI

Core files:

- `scripts/minimal_deepseek_report.py`
- `scripts/minimal_web_app.py`

### 2. Embedded `ai_trade_system`

Primary responsibilities:

- Signal ingestion
- Risk checks
- Paper-trading simulation
- Daily plan generation
- Review report generation
- Auto-selection pipeline

Core modules:

- `ai_trade_system/engine/bridge_service.py`
- `ai_trade_system/engine/risk_engine.py`
- `ai_trade_system/engine/mock_broker.py`
- `ai_trade_system/engine/plan_center.py`
- `ai_trade_system/engine/review_service.py`
- `ai_trade_system/engine/universe_service.py`
- `ai_trade_system/scripts/run_auto_pipeline.py`

## Default User Flow

### Recommended path

Open the Web UI and follow this order:

1. Fill in `API Key`
2. Run `自动选股与生成计划`
3. Check `自动选股摘要`
4. Check `候选卡片`
5. Check `交易计划`
6. Open share pages for names you want to review in detail
7. Manually place orders in your broker app if the plan contains executable trades

### What to focus on

If you are using the system daily, the most important outputs are:

- `自动选股一句话总结`
- `数据源状态`
- `今日可执行清单`
- `今日结论`

If the plan says `今日无可执行交易`, the correct action is usually to do nothing and wait for the next cycle.

## Auto-Selection Logic

The auto-selection pipeline uses:

### Base market filtering

- Eastmoney public market data as the main quote source
- Daily bars for trend and liquidity screening
- Fallback to local snapshots if live data is unavailable

### Enhancement dimensions

- Fund flow
- Announcements
- Financial reports
- Industry context

Enhancement failures do not stop the workflow. The UI will show a compact data-source status instead of failing the full run.

## Risk and Execution Model

### Signal states shown in the UI

- `可执行`
- `观察`
- `仅持仓者处理`
- `风控拦截`

### A-share rules already modeled

- 100-share board lot handling
- T+1 sell restriction
- Position-cap checks
- Stop-loss risk cap
- Reject sell signals when no sellable position exists

### Paper trading behavior

- Uses next-bar style validation logic
- Maintains local cash, positions, and equity
- Produces review reports without touching any real account

## Important Paths

TradeforAgents output:

- `results/<symbol>/<date>/`

Share pages:

- `results/<symbol>/<date>/share/`

Paper-trading database:

- `ai_trade_system/data/db.sqlite3`

Auto-selection reports:

- `ai_trade_system/reports/auto_candidates_YYYY-MM-DD.md`

Daily plans:

- `ai_trade_system/reports/daily_plan_YYYY-MM-DD.md`

Review reports:

- `ai_trade_system/reports/paper_review.md`

## CLI Shortcuts

Initialize the paper account:

```bash
python3 -m ai_trade_system.scripts.bootstrap_db --cash 100000
```

Generate a daily plan:

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

Run the full after-close workflow:

```bash
python3 -m ai_trade_system.scripts.run_auto_pipeline --mode quick --execute-sim
```

Generate a review report:

```bash
python3 -m ai_trade_system.scripts.run_review
```

## Operational Notes

- `quick` is the default recommended mode
- `deep` is useful when the shortlist is small and you are okay with waiting longer
- The system is designed to be resilient to partial failures
- One failed stock in a batch no longer invalidates the whole pipeline if other names succeeded
