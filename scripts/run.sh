#!/usr/bin/env bash
set -euo pipefail

# AI Trend Collector 启动脚本
# 用法：
#   ./scripts/run.sh --all --push
#   ./scripts/run.sh --spider github_trends

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 默认使用项目内虚拟环境
VENV_PATH="${VENV_PATH:-./venv}"
if [ -d "$VENV_PATH" ]; then
    # shellcheck source=/dev/null
    source "$VENV_PATH/bin/activate"
fi

PYTHONPATH="$PROJECT_ROOT" python -m src.main "$@"
