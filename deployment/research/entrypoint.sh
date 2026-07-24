#!/usr/bin/env bash
set -euo pipefail

mkdir -p \
  "${RESEARCH_ROOT:-/research}/data/binance" \
  "${RESEARCH_ROOT:-/research}/results" \
  "${RESEARCH_ROOT:-/research}/models" \
  "${RESEARCH_ROOT:-/research}/logs" \
  "${RESEARCH_ROOT:-/research}/user_data"

if [[ "${RESEARCH_RUN_ON_START:-0}" == "1" ]]; then
  python /opt/research/scripts/run_research_baseline.py
fi

exec sleep infinity
