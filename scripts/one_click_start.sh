#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
REQ_FILE="$PROJECT_ROOT/requirements.txt"
HASH_FILE="$VENV_DIR/.requirements.sha256"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

usage() {
  cat <<EOF
一键启动脚本

用法:
  bash scripts/one_click_start.sh web
  bash scripts/one_click_start.sh cli <股票代码> [YYYY-MM-DD] [额外参数]
  bash scripts/one_click_start.sh install

示例:
  bash scripts/one_click_start.sh web
  bash scripts/one_click_start.sh cli 600028
  bash scripts/one_click_start.sh cli 518880 --reasoner --request-timeout 120 --retries 2
EOF
}

log() {
  echo "[one-click] $*"
}

ensure_python() {
  if command -v python3 >/dev/null 2>&1; then
    return 0
  fi
  echo "错误: 未找到 python3，请先安装 Python 3.10+"
  exit 1
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
      cp "$ENV_EXAMPLE" "$ENV_FILE"
      log "已创建 .env（来自 .env.example）: $ENV_FILE"
      log "请编辑 .env 填入 DEEPSEEK_API_KEY 后重试"
    else
      touch "$ENV_FILE"
      log "已创建空 .env: $ENV_FILE"
    fi
  fi
}

ensure_venv_and_deps() {
  ensure_python

  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    log "创建虚拟环境: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi

  local current_hash
  current_hash="$(sha256sum "$REQ_FILE" | awk '{print $1}')"
  local installed_hash=""
  if [[ -f "$HASH_FILE" ]]; then
    installed_hash="$(cat "$HASH_FILE" || true)"
  fi

  if [[ "$current_hash" != "$installed_hash" ]]; then
    log "安装/更新依赖..."
    "$VENV_DIR/bin/pip" install -U pip
    "$VENV_DIR/bin/pip" install -r "$REQ_FILE"
    echo "$current_hash" >"$HASH_FILE"
    log "依赖安装完成"
  else
    log "依赖已是最新，跳过安装"
  fi
}

mode="${1:-web}"
if [[ "$mode" == "-h" || "$mode" == "--help" ]]; then
  usage
  exit 0
fi

ensure_venv_and_deps
ensure_env_file

case "$mode" in
  install)
    log "初始化完成"
    exit 0
    ;;
  web)
    shift || true
    log "启动 Web 模式..."
    exec bash "$PROJECT_ROOT/scripts/run_minimal_web_app.sh" "$@"
    ;;
  cli)
    shift || true
    if [[ $# -lt 1 ]]; then
      echo "错误: cli 模式需要股票代码"
      usage
      exit 1
    fi
    log "启动 CLI 模式..."
    exec bash "$PROJECT_ROOT/scripts/run_minimal_deepseek.sh" "$@"
    ;;
  *)
    echo "错误: 不支持的模式 $mode"
    usage
    exit 1
    ;;
esac

