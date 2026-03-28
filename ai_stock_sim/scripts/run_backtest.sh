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
MODE_NAME="${3:-strategy_only}"
echo "运行回测: symbol=${SYMBOL} strategy=${STRATEGY} mode=${MODE_NAME}"
PYTHONPATH="$PROJECT_ROOT" python - <<PY
from app.backtest_service import BacktestService
from app.settings import load_settings

settings = load_settings()
service = BacktestService(settings)
report = service.run_simple_backtest(symbol="${SYMBOL}", strategy_name="${STRATEGY}")
path = service.save_backtest_report(report)
vnpy_path = service.export_vnpy_payload(symbol="${SYMBOL}", strategy_name="${STRATEGY}", mode_name="${MODE_NAME}")
print(f"Backtest saved to: {path}")
print(f"vn.py payload saved to: {vnpy_path}")
print(report)
PY
