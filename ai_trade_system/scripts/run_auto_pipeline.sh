#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv310/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "未找到 ai_trade_system 的 Python 3.10 环境: $PYTHON_BIN"
  echo "请先创建 .venv310 并安装 AKShare。"
  exit 1
fi

export PYTHONPATH="$(dirname "$PROJECT_ROOT"):${PYTHONPATH:-}"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
exec "$PYTHON_BIN" -m ai_trade_system.scripts.run_auto_pipeline "$@"
