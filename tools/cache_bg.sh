#!/usr/bin/env bash
# actions/cache's own restore and save, run as background processes beside the
# steps that follow them instead of one step (and one wait) each.
#
#   CB_KEY=k CB_PATH=$'p1\np2' [CB_RESTORE_KEYS=$'k1\nk2'] [CB_UNPACK=1] \
#     bash tools/cache_bg.sh bg restore NAME          # returns at once
#   CB_KEY=k CB_PATH=p [CB_PACK=pages|shims] [CB_GATE=1] \
#     bash tools/cache_bg.sh bg save NAME             # returns at once
#   bash tools/cache_bg.sh wait restore NAME...       # a restore that failed is a warning: a cold cache
#   bash tools/cache_bg.sh wait save                  # every save started; one that failed fails the step
#   bash tools/cache_bg.sh output NAME cache-matched-key   # what the restore's step would have output
#
# The build's ~7 restores and ~6 saves are network waits that added up to ~3
# minutes of a job that holds the "pages" concurrency group, and so the next
# push's build, in series. Each action is a node program (dist/restore-only
# and dist/save-only in the action's checkout, which the runner downloads for
# any job that uses actions/cache@v5: the git store's steps do), reading its
# inputs from INPUT_* variables and its service credentials from ACTIONS_*,
# which .github/actions/cache-env copies into the job's environment. Its
# outputs (cache-hit, cache-matched-key) land in $RUNNER_TEMP/cacheout.* and
# `output` prints one. The cache's version is a hash of its paths, so CB_PATH
# is the path: input of the step it replaces, character for character.
#
# CB_UNPACK=1: unpack the restored tar (tools/cache_tar.sh unpack CB_PATH).
# CB_PACK: pack CB_PATH first (tools/cache_tar.sh pack CB_PACK CB_PATH).
# CB_GATE=1: save only once the site checks (pages.yml's Start the site
# checks, tools/bg_job.sh jobs links and indexnow) have both passed, which is what the
# save steps' `steps.checks.outcome == 'success'` said when they ran after
# Wait for the site checks.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="${RUNNER_TEMP:-/tmp}"

run() {  # run restore|save NAME: the foreground body of a background job
  local mode=$1 name=$2
  local action="${CB_ACTION_DIR:-$tmp/../_actions/actions/cache/v5}"
  local entry="$action/dist/$mode-only/index.js"
  [ -f "$entry" ] || { echo "cache_bg: no $entry (the job has to use actions/cache@v5 once)" >&2; return 1; }
  : "${ACTIONS_RUNTIME_TOKEN:?run .github/actions/cache-env first}"
  if [ "$mode" = save ]; then
    [ -z "${CB_PACK:-}" ] || bash "$here/cache_tar.sh" pack "$CB_PACK" "${CB_PATH:?}"
    if [ -n "${CB_GATE:-}" ]; then
      if ! BG_JOB_TIMEOUT=600 bash "$here/bg_job.sh" wait -q links indexnow; then
        echo "cache_bg: the site checks did not pass: not saving $CB_KEY"; return 0
      fi
    fi
  fi
  # The runner's own node 24, which the action declares; else the image's.
  local node
  node=$(find /home/runner -maxdepth 5 -path '*externals/node24/bin/node' 2>/dev/null | head -n 1 || true)
  node=${node:-$(command -v node)}
  local out="$tmp/cacheout.$mode-$name"
  : > "$out"
  : > "$out.state"
  echo "cache_bg: $mode $CB_KEY with node $("$node" --version)"
  local t0=$SECONDS
  env "INPUT_PATH=${CB_PATH:?}" "INPUT_KEY=${CB_KEY:?}" "INPUT_RESTORE-KEYS=${CB_RESTORE_KEYS:-}" \
    INPUT_ENABLECROSSOSARCHIVE=false "INPUT_FAIL-ON-CACHE-MISS=false" "INPUT_LOOKUP-ONLY=false" \
    "GITHUB_OUTPUT=$out" "GITHUB_STATE=$out.state" \
    "$node" "$entry"
  local t1=$SECONDS
  if [ "$mode" = restore ] && [ -n "${CB_UNPACK:-}" ]; then
    bash "$here/cache_tar.sh" unpack "$CB_PATH"
  fi
  # Where a restore's or save's seconds went: the cache service (download or
  # upload, with the archive's own tar) and then the tar of loose files.
  echo "cache_bg: $mode $name: cache service $(( t1 - t0 ))s, tar $(( SECONDS - t1 ))s"
  return 0
}

case "${1:-}" in
  run)
    [ $# -eq 3 ] || { echo "usage: $0 run restore|save NAME" >&2; exit 2; }
    run "$2" "$3" ;;
  bg)
    [ $# -eq 3 ] && { [ "$2" = restore ] || [ "$2" = save ]; } || { echo "usage: $0 bg restore|save NAME" >&2; exit 2; }
    [ "$2" != save ] || echo "$3" >> "$tmp/cache-saves.list"
    bash "$here/bg_job.sh" start "$2-$3" bash "$0" run "$2" "$3" ;;
  wait)
    [ $# -ge 2 ] || { echo "usage: $0 wait restore NAME... | wait save" >&2; exit 2; }
    mode=$2; shift 2
    if [ "$mode" = save ]; then
      names=$(cat "$tmp/cache-saves.list" 2>/dev/null || true)
    else
      names="$*"
    fi
    status=0
    for n in $names; do
      echo "--- $mode $n"
      if ! bash "$here/bg_job.sh" wait "$mode-$n"; then
        if [ "$mode" = save ]; then
          echo "::error title=Cache save failed::$n"; status=1
        else
          echo "::warning title=Cache restore failed::$n: carrying on as a cold cache"
        fi
      fi
    done
    exit "$status" ;;
  output)
    [ $# -eq 3 ] || { echo "usage: $0 output NAME KEY" >&2; exit 2; }
    # core.setOutput writes `key<<DELIM`, the value, then DELIM; accept `key=value` too.
    awk -v k="$3" '
      index($0, k "=") == 1 { v = substr($0, length(k) + 2) }
      index($0, k "<<") == 1 { getline v }
      END { print v }' "$tmp/cacheout.restore-$2" 2>/dev/null || true ;;
  *) echo "usage: $0 bg|wait|output ..." >&2; exit 2 ;;
esac
