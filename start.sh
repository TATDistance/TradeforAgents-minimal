#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$PROJECT_ROOT/scripts/one_click_start.sh" "$@"

