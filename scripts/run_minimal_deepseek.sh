#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$PROJECT_ROOT/scripts/minimal_deepseek_report.py"

if [[ $# -lt 1 ]]; then
  echo "用法: bash scripts/run_minimal_deepseek.sh <股票代码> [YYYY-MM-DD] [其他参数]"
  echo "示例: bash scripts/run_minimal_deepseek.sh 600028"
  echo "示例: bash scripts/run_minimal_deepseek.sh AAPL 2026-03-26"
  echo "示例: bash scripts/run_minimal_deepseek.sh 518880 2026-03-26 --request-timeout 30 --retries 1"
  echo "示例: bash scripts/run_minimal_deepseek.sh 518880 --reasoner"
  echo "示例: bash scripts/run_minimal_deepseek.sh 600028 --deep"
  exit 1
fi

# 尝试从 .env 自动加载 DeepSeek Key（仅在当前环境未设置时）
if [[ -z "${DEEPSEEK_API_KEY:-}" && -f "$PROJECT_ROOT/.env" ]]; then
  ENV_KEY="$(grep -E '^DEEPSEEK_API_KEY=' "$PROJECT_ROOT/.env" | tail -n 1 | sed 's/^DEEPSEEK_API_KEY=//')"
  # 去掉可能包裹的单/双引号
  ENV_KEY="${ENV_KEY%\"}"
  ENV_KEY="${ENV_KEY#\"}"
  ENV_KEY="${ENV_KEY%\'}"
  ENV_KEY="${ENV_KEY#\'}"
  if [[ -n "$ENV_KEY" ]]; then
    export DEEPSEEK_API_KEY="$ENV_KEY"
  fi
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "错误: 未设置 DEEPSEEK_API_KEY"
  echo "请先执行: export DEEPSEEK_API_KEY='你的key'，或在项目 .env 中设置 DEEPSEEK_API_KEY"
  exit 1
fi

STOCK_SYMBOL="$1"
shift

if [[ "${1:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  ANALYSIS_DATE="$1"
  shift
else
  ANALYSIS_DATE="$(date +%F)"
fi

DEFAULT_MODEL="${DEEPSEEK_MODEL:-deepseek-chat}"
MODEL="$DEFAULT_MODEL"
MODE="${TA_MIN_MODE:-quick}"
HAS_MODEL_ARG=false
HAS_TIMEOUT_ARG=false
HAS_MODE_ARG=false

PASSTHRU_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --deep)
      MODE="deep"
      ;;
    --quick)
      MODE="quick"
      ;;
    --reasoner)
      MODEL="deepseek-reasoner"
      ;;
    --chat)
      MODEL="deepseek-chat"
      ;;
    --model|--model=*)
      HAS_MODEL_ARG=true
      PASSTHRU_ARGS+=("$arg")
      ;;
    --request-timeout|--request-timeout=*)
      HAS_TIMEOUT_ARG=true
      PASSTHRU_ARGS+=("$arg")
      ;;
    --mode|--mode=*)
      HAS_MODE_ARG=true
      PASSTHRU_ARGS+=("$arg")
      ;;
    *)
      PASSTHRU_ARGS+=("$arg")
      ;;
  esac
done

if ! $HAS_MODEL_ARG; then
  PASSTHRU_ARGS=(--model "$MODEL" "${PASSTHRU_ARGS[@]}")
fi

if ! $HAS_MODE_ARG; then
  PASSTHRU_ARGS=(--mode "$MODE" "${PASSTHRU_ARGS[@]}")
fi

# 深度模式或 reasoner 默认更慢，未显式指定超时时自动放宽
if [[ ("$MODEL" == "deepseek-reasoner" || "$MODE" == "deep") && "$HAS_TIMEOUT_ARG" == false ]]; then
  PASSTHRU_ARGS=(--request-timeout 120 "${PASSTHRU_ARGS[@]}")
fi

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" "$SCRIPT" "$STOCK_SYMBOL" --date "$ANALYSIS_DATE" "${PASSTHRU_ARGS[@]}"
