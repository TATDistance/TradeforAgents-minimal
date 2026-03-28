#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.venv310/bin/activate" ]]; then
  source "$PROJECT_ROOT/.venv310/bin/activate"
else
  source "$PROJECT_ROOT/.venv/bin/activate"
fi

STREAMLIT_HOME="$PROJECT_ROOT/.streamlit_home"
STREAMLIT_CONFIG_DIR="$STREAMLIT_HOME/.streamlit"
mkdir -p "$STREAMLIT_CONFIG_DIR"
cat > "$STREAMLIT_CONFIG_DIR/config.toml" <<'EOF'
[browser]
gatherUsageStats = false

[server]
headless = true
EOF
cat > "$STREAMLIT_CONFIG_DIR/credentials.toml" <<'EOF'
[general]
email = ""
EOF

export HOME="$STREAMLIT_HOME"
export STREAMLIT_BROWSER_GATHER_USAGE_STATS="false"
export STREAMLIT_SERVER_HEADLESS="true"

cd "$PROJECT_ROOT"
PYTHONPATH="$PROJECT_ROOT" streamlit run dashboard/dashboard_app.py --server.port 8610 --server.address 0.0.0.0 --browser.gatherUsageStats false
