#!/usr/bin/env bash
# Same as scripts/run_ai_evals.ps1 for bash/WSL: every AI arm live on Nemotron.
set -euo pipefail
cd "$(dirname "$0")/.."
export NO_COLOR=1 RESILIMES_MODE=live PYTHONIOENCODING=utf-8
python -m resilimes.insight.study "${1:-all}" --provider nightshift --temperature "${2:-0.2}"
