#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.venv310/bin/activate" ]]; then
  source "$PROJECT_ROOT/.venv310/bin/activate"
else
  source "$PROJECT_ROOT/.venv/bin/activate"
fi
cd "$PROJECT_ROOT"
SYMBOL="${1:-600036}"
STRATEGY="${2:-momentum}"
PYTHONPATH="$PROJECT_ROOT" python - <<PY
from app.backtest_service import BacktestService
from app.settings import load_settings

settings = load_settings()
service = BacktestService(settings)
report = service.run_simple_backtest(symbol="${SYMBOL}", strategy_name="${STRATEGY}")
path = service.save_backtest_report(report)
print(f"Backtest saved to: {path}")
print(report)
PY
