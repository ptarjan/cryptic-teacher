#!/usr/bin/env bash
# actions/cache's own restore or save, run as a plain command so it can go in
# the background (tools/bg_job.sh) beside the steps that follow it.
#
#   CB_KEY=k CB_PATH=$'p1\np2' [CB_RESTORE_KEYS=$'k1\nk2'] bash tools/cache_bg.sh restore|save NAME
#   bash tools/cache_bg.sh output NAME cache-matched-key
#
# A step that uses actions/cache blocks the job until it is done, and the
# build's ~7 restores and ~6 saves are network waits that add up to ~3
# minutes in series. Each action is a node program (dist/restore-only and
# dist/save-only in the action's checkout, which the runner has already
# downloaded for the job), reading its inputs from INPUT_* variables and its
# service credentials from ACTIONS_*, which the cache-env action copies into
# the job's environment. The outputs it would set (cache-hit,
# cache-matched-key) land in $RUNNER_TEMP/cacheout.NAME as `name=value` lines;
# `output` prints one.
set -euo pipefail
if [ "${1:-}" = output ]; then
  [ $# -eq 3 ] || { echo "usage: $0 output NAME KEY" >&2; exit 2; }
  sed -n "s/^$3=//p" "${RUNNER_TEMP:?}/cacheout.$2" | tail -n 1
  exit 0
fi
mode=${1:?usage: $0 restore|save NAME}
name=${2:?usage: $0 restore|save NAME}
case "$mode" in restore|save) ;; *) echo "usage: $0 restore|save NAME" >&2; exit 2 ;; esac
action="${CB_ACTION_DIR:-${RUNNER_TEMP:?}/../_actions/actions/cache/v5}"
entry="$action/dist/$mode-only/index.js"
[ -f "$entry" ] || { echo "cache_bg: no $entry (the job has to use actions/cache@v5 once)" >&2; exit 1; }
: "${ACTIONS_RUNTIME_TOKEN:?run the cache-env action first}"
# The runner's own node 24, which the action declares; else the image's.
node=$(find /home/runner -maxdepth 5 -path '*externals/node24/bin/node' 2>/dev/null | head -n 1 || true)
node=${node:-$(command -v node)}
out="$RUNNER_TEMP/cacheout.$name"
: > "$out"
: > "$out.state"
echo "cache_bg: $mode $CB_KEY with node $("$node" --version)"
env "INPUT_PATH=${CB_PATH:?}" "INPUT_KEY=${CB_KEY:?}" "INPUT_RESTORE-KEYS=${CB_RESTORE_KEYS:-}" \
  INPUT_ENABLECROSSOSARCHIVE=false "INPUT_FAIL-ON-CACHE-MISS=false" "INPUT_LOOKUP-ONLY=false" \
  "GITHUB_OUTPUT=$out" "GITHUB_STATE=$out.state" \
  "$node" "$entry"
echo "cache_bg: outputs:"
cat "$out"
