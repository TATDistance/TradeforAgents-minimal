#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.venv310/bin/activate" ]]; then
  source "$PROJECT_ROOT/.venv310/bin/activate"
else
  source "$PROJECT_ROOT/.venv/bin/activate"
fi
cd "$PROJECT_ROOT"
PYTHONPATH="$PROJECT_ROOT" python -m pytest tests -q
