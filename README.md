# TradeforAgents-minimal

TradeforAgents-minimal is now a practical after-close AI trading workspace for China A-shares.

It combines:

- AI stock analysis
- Share-page generation
- Auto-selection after market close
- Structured signal conversion
- A-share risk checks
- Paper-trading validation
- Next-day trade planning

The target workflow is:

`收盘后选股 -> AI 分析 -> 交易计划 -> 模拟盘验证 -> 人工实盘执行`

## What This Project Is Good For

- China A-share swing / after-close workflow
- Personal use without broker API
- AI-assisted stock review
- Paper-trading first validation
- Manual execution through a broker app

## What It Does Not Try To Do

- Fully automated live trading
- Broker account synchronization
- Intraday high-frequency execution
- Institutional-grade market data infrastructure

## Main Features

### 1. Web UI on port `8600`

The homepage now supports:

- Recommended auto-selection workflow
- Single-stock AI analysis
- Watchlist batch analysis
- Auto-selection result cards
- Trade plan / paper-trading / review center

Start it with:

```bash
bash start.sh web
```

Then open:

```text
http://127.0.0.1:8600
```

### 2. AI analysis

Supports:

- `quick`
- `deep`

Outputs are written to:

```text
results/<股票代码>/<日期>/
```

Important files include:

- `analysis_metadata.json`
- `decision.json`
- `message_tool.log`
- `share/<股票代码>_<日期>_share.html`

### 3. Embedded AI trade workflow

This repository now includes an embedded package:

```text
ai_trade_system/
```

It provides:

- signal ingestion from `decision.json`
- A-share risk rules
- paper-trading simulation
- daily trade-plan generation
- review report generation
- auto-selection pipeline

## Quick Start

### Option A: Use the Web UI

```bash
git clone https://github.com/TATDistance/TradeforAgents-minimal.git
cd TradeforAgents-minimal
bash start.sh web
```

In the page:

1. Fill in `API Key`
2. Use `步骤 1：自动选股与生成计划`
3. Check `自动选股摘要`
4. Check `候选卡片`
5. Check `交易计划`
6. Open the share page for names you want to review in detail

### Option B: Use the CLI

Single-stock analysis:

```bash
bash start.sh cli 600028 --quick
bash start.sh cli 000630 --deep
```

Initialize local paper account:

```bash
python3 -m ai_trade_system.scripts.bootstrap_db --cash 100000
```

Generate a daily trade plan:

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

Run the full after-close pipeline:

```bash
python3 -m ai_trade_system.scripts.run_auto_pipeline --mode quick --execute-sim
```

Generate a review report:

```bash
python3 -m ai_trade_system.scripts.run_review
```

## Recommended Daily Workflow

For personal A-share trading, the most practical loop is:

1. Run auto-selection after market close
2. Let the system analyze shortlisted names
3. Read the one-line summary
4. Check whether the plan has executable trades
5. If yes, place orders manually next day
6. Use paper-trading and review reports to validate signal quality

## Project Structure

```text
TradeforAgents-minimal/
├── ai_trade_system/
├── docs/
├── results/
├── scripts/
├── start.sh
└── README.md
```

Important files:

- `scripts/minimal_web_app.py`
- `scripts/minimal_deepseek_report.py`
- `ai_trade_system/scripts/run_auto_pipeline.py`
- `ai_trade_system/scripts/run_daily_plan.py`
- `ai_trade_system/scripts/run_review.py`

## Output Paths

AI analysis output:

```text
results/<symbol>/<date>/
```

Trade plans:

```text
ai_trade_system/reports/daily_plan_YYYY-MM-DD.md
```

Auto-selection reports:

```text
ai_trade_system/reports/auto_candidates_YYYY-MM-DD.md
```

Paper-trading review:

```text
ai_trade_system/reports/paper_review.md
```

Paper-trading database:

```text
ai_trade_system/data/db.sqlite3
```

## Notes on Data and Stability

- Main market screening uses Eastmoney-style public data
- Enhancement dimensions can use AKShare when available
- The system tolerates partial failures
- One failed stock in a batch no longer invalidates the whole pipeline if others succeeded

## Documentation

- [AI Trade Workflow](docs/ai_trade_workflow.md)
- [Cloud Deploy Guide](docs/minimal_cloud_deploy.md)
