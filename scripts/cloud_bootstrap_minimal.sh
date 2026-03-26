#!/usr/bin/env bash
set -euo pipefail

# 一键部署 TradingAgents-CN 极简版到公网云服务器
# - 安装依赖
# - 拉代码/装Python依赖
# - 配置 .env
# - 创建 systemd 自启动
# - 可选配置 Nginx + HTTPS + BasicAuth

PROJECT_DIR="/opt/TradeforAgents-minimal"
REPO_URL=""
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
PORT="${MINIMAL_WEB_PORT:-8600}"
DOMAIN=""
EMAIL=""
AUTH_USER="friend"
AUTH_PASS=""

usage() {
  cat <<EOF
用法:
  sudo bash scripts/cloud_bootstrap_minimal.sh \\
    --repo-url <git地址> \\
    --api-key <deepseek_key> \\
    [--project-dir /opt/TradingAgents-CN] \\
    [--base-url https://api.deepseek.com] \\
    [--port 8600] \\
    [--domain your.domain.com --email you@example.com --auth-user friend --auth-pass '密码']

说明:
  1) 不传 --domain 时，仅启动 http://公网IP:端口
  2) 传 --domain + --email 时，会自动配置 Nginx + HTTPS + BasicAuth
  3) 未传 --auth-pass 时会自动生成随机密码
EOF
}

log() { echo "[deploy] $*"; }
err() { echo "[error] $*" >&2; exit 1; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "请使用 root 或 sudo 运行此脚本"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-dir)
        PROJECT_DIR="$2"; shift 2 ;;
      --repo-url)
        REPO_URL="$2"; shift 2 ;;
      --api-key)
        DEEPSEEK_API_KEY="$2"; shift 2 ;;
      --base-url)
        DEEPSEEK_BASE_URL="$2"; shift 2 ;;
      --port)
        PORT="$2"; shift 2 ;;
      --domain)
        DOMAIN="$2"; shift 2 ;;
      --email)
        EMAIL="$2"; shift 2 ;;
      --auth-user)
        AUTH_USER="$2"; shift 2 ;;
      --auth-pass)
        AUTH_PASS="$2"; shift 2 ;;
      -h|--help)
        usage; exit 0 ;;
      *)
        err "未知参数: $1" ;;
    esac
  done
}

upsert_env() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  if grep -qE "^${key}=" "$env_file"; then
    sed -i "s|^${key}=.*|${key}=${value}|g" "$env_file"
  else
    echo "${key}=${value}" >>"$env_file"
  fi
}

install_packages() {
  log "安装系统依赖"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y \
    git curl ca-certificates \
    python3 python3-venv python3-pip \
    nginx apache2-utils certbot python3-certbot-nginx
}

prepare_project() {
  log "准备项目目录: ${PROJECT_DIR}"
  mkdir -p "$(dirname "$PROJECT_DIR")"
  if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
    [[ -n "$REPO_URL" ]] || err "项目不存在，请传 --repo-url"
    git clone "$REPO_URL" "$PROJECT_DIR"
  fi

  cd "$PROJECT_DIR"
  if [[ ! -x ".venv/bin/python" ]]; then
    python3 -m venv .venv
  fi
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
}

configure_env() {
  [[ -n "$DEEPSEEK_API_KEY" ]] || err "请传 --api-key 或先导出 DEEPSEEK_API_KEY"
  log "写入 .env 配置"
  local env_file="${PROJECT_DIR}/.env"
  touch "$env_file"
  upsert_env "$env_file" "DEEPSEEK_API_KEY" "$DEEPSEEK_API_KEY"
  upsert_env "$env_file" "DEEPSEEK_BASE_URL" "$DEEPSEEK_BASE_URL"
}

configure_systemd() {
  log "创建 systemd 服务 tradingagents-minimal"
  cat >/etc/systemd/system/tradingagents-minimal.service <<EOF
[Unit]
Description=TradingAgents Minimal Web
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/scripts/run_minimal_web_app.sh
Restart=always
RestartSec=3
Environment=MINIMAL_WEB_HOST=0.0.0.0
Environment=MINIMAL_WEB_PORT=${PORT}
Environment=NO_PROXY=127.0.0.1,localhost

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now tradingagents-minimal
  systemctl restart tradingagents-minimal
  sleep 2
  systemctl --no-pager --full status tradingagents-minimal | sed -n '1,25p'
}

configure_nginx_https() {
  [[ -n "$DOMAIN" ]] || return 0
  [[ -n "$EMAIL" ]] || err "配置 HTTPS 时必须提供 --email"
  log "配置 Nginx 反向代理: ${DOMAIN}"

  if [[ -z "$AUTH_PASS" ]]; then
    AUTH_PASS="$(openssl rand -base64 18 | tr -d '\n')"
  fi

  htpasswd -bc /etc/nginx/.htpasswd_tradingagents_minimal "$AUTH_USER" "$AUTH_PASS"

  cat >/etc/nginx/sites-available/tradingagents-minimal.conf <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location / {
        auth_basic "TradingAgents Minimal";
        auth_basic_user_file /etc/nginx/.htpasswd_tradingagents_minimal;

        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600;
        proxy_send_timeout 600;
    }
}
EOF

  ln -sf /etc/nginx/sites-available/tradingagents-minimal.conf /etc/nginx/sites-enabled/tradingagents-minimal.conf
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx

  log "申请 HTTPS 证书"
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
}

print_summary() {
  log "部署完成"
  if [[ -n "$DOMAIN" ]]; then
    echo
    echo "访问地址: https://${DOMAIN}"
    echo "访问账号: ${AUTH_USER}"
    echo "访问密码: ${AUTH_PASS}"
  else
    echo
    echo "访问地址: http://<云服务器公网IP>:${PORT}"
    echo "提示: 建议后续加 --domain + --email 配置 HTTPS"
  fi
  echo
  echo "查看服务日志:"
  echo "  journalctl -u tradingagents-minimal -f"
}

main() {
  parse_args "$@"
  require_root
  install_packages
  prepare_project
  configure_env
  configure_systemd
  configure_nginx_https
  print_summary
}

main "$@"
