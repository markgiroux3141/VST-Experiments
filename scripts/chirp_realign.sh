#!/usr/bin/env bash
# The 300-4 re-aligned on 0.25 um tape cells (docs/PERIOD_GEAR_BACKLOG.md PG1, the chirp):
# the channel's alignment, the deck regenerated, each channel's BIAS ADJUST trimmed on the
# deck, the deck regenerated again. A one-off run; logs to reports/multitrack/deck/realign.log.
set -euo pipefail
cd "$(dirname "$0")/.."
log=reports/multitrack/deck/realign.log
mkdir -p "$(dirname "$log")"
{
  echo "== $(date) align_300_4"
  OPENBLAS_NUM_THREADS=1 uv run --extra fast --extra listen python scripts/align_300_4.py
  echo "== $(date) make_ampex_300_4"
  uv run python scripts/make_ampex_300_4.py
  echo "== $(date) ampex_300_4_trim --bias --write"
  OPENBLAS_NUM_THREADS=1 uv run --extra fast --extra listen python scripts/ampex_300_4_trim.py --bias --write
  echo "== $(date) make_ampex_300_4"
  uv run python scripts/make_ampex_300_4.py
  echo "== $(date) done"
} >"$log" 2>&1
