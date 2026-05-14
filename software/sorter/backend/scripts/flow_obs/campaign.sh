#!/bin/bash
# Multi-run baseline campaign.
# Usage: campaign.sh <label_prefix> <seconds_per_run> <num_runs> [rest_seconds_between]
# Example: campaign.sh baseline 60 10 5
set -euo pipefail
LABEL_PREFIX="${1:?label_prefix required}"
SECONDS_PER_RUN="${2:-60}"
NUM_RUNS="${3:-10}"
REST_S="${4:-5}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for i in $(seq 1 $NUM_RUNS); do
  LABEL="${LABEL_PREFIX}_$(printf '%02d' $i)"
  echo "==================== ${LABEL} =================="
  uv run --python python3 python "$SCRIPT_DIR/runner.py" "$SECONDS_PER_RUN" "$LABEL" --note "campaign $i/$NUM_RUNS"
  if [ "$i" -lt "$NUM_RUNS" ]; then
    echo "..resting ${REST_S}s before next run"
    sleep "$REST_S"
  fi
done
echo "campaign done"
