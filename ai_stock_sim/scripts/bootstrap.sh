#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3.10 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.10)"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

VENV_DIR="$PROJECT_ROOT/.venv310"

"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
pip install -r "$PROJECT_ROOT/requirements.txt"

mkdir -p "$PROJECT_ROOT/data/logs" "$PROJECT_ROOT/data/cache" "$PROJECT_ROOT/data/reports/backtest"
PYTHONPATH="$PROJECT_ROOT" python - <<'PY'
from app.db import initialize_db, seed_account
from app.settings import load_settings

settings = load_settings()
initialize_db(settings)
seed_account(settings)
print(f"SQLite initialized: {settings.db_path}")
PY

echo "bootstrap 完成，当前解释器: $("${VENV_DIR}/bin/python" --version)"
