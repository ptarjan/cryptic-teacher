#!/bin/bash
# Register the pre-reset burn as a status lane for the cryptic room. The label
# names the job only: which meter it is pacing (weekly or five-hour) changes
# with `prereset_plan.py --five-hour`, so the lane's text is the last line of
# .prereset.log, which states the mode, never a label typed here.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${TRACK_JOB:-/app/tools/track-job.sh}" --restart cryptic-crosswords --run "Burn" \
  "tail -1 .prereset.log" -- tools/prereset_backfill.sh
