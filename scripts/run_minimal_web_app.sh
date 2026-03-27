#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_SCRIPT="$PROJECT_ROOT/scripts/minimal_web_app.py"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

# 尝试从 .env 自动加载 key
if [[ -z "${DEEPSEEK_API_KEY:-}" && -f "$PROJECT_ROOT/.env" ]]; then
  ENV_KEY="$(grep -E '^DEEPSEEK_API_KEY=' "$PROJECT_ROOT/.env" | tail -n 1 | sed 's/^DEEPSEEK_API_KEY=//')"
  ENV_KEY="${ENV_KEY%\"}"
  ENV_KEY="${ENV_KEY#\"}"
  ENV_KEY="${ENV_KEY%\'}"
  ENV_KEY="${ENV_KEY#\'}"
  if [[ -n "$ENV_KEY" ]]; then
    export DEEPSEEK_API_KEY="$ENV_KEY"
  fi
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "提示: 未设置 DEEPSEEK_API_KEY，将在网页里手动填写 API Key"
fi

export MINIMAL_WEB_HOST="${MINIMAL_WEB_HOST:-0.0.0.0}"
export MINIMAL_WEB_PORT="${MINIMAL_WEB_PORT:-8600}"

# 避免代理干扰本地 127.0.0.1/localhost 访问。
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-127.0.0.1,localhost}"

# 如果已经有旧的最小 Web 进程占着 8600，先清掉旧实例，避免用户重启后其实没有真正加载新页面。
if command -v pgrep >/dev/null 2>&1; then
  EXISTING_PIDS="$(pgrep -f "$APP_SCRIPT" || true)"
  if [[ -n "$EXISTING_PIDS" ]]; then
    echo "检测到旧的 Web 实例，先停止: $EXISTING_PIDS"
    pkill -f "$APP_SCRIPT" || true
    sleep 1
  fi
fi

echo "启动最小Web服务: http://${MINIMAL_WEB_HOST}:${MINIMAL_WEB_PORT}"
cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" "$APP_SCRIPT"
