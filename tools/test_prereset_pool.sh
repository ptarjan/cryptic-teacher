#!/bin/bash
# Does the pre-reset backfill's rolling pool schedule the way it claims?
#
#     bash tools/test_prereset_pool.sh
#
# run_pool and its helpers are read out of tools/prereset_backfill.sh rather
# than copied, with run_claude replaced by a stub that sleeps a random short
# time and logs when it started and ended, and everything that touches git,
# the meters or the network stubbed out. Checked off that log:
#   - at no launch are more runs in flight than the width at that moment;
#   - a freed slot is refilled while other runs are still going;
#   - launches are at least POOL_LAUNCH_GAP apart;
#   - every id is handled exactly once, the failing one through the failure path;
#   - a width change at a checkpoint takes effect, growing and shrinking;
#   - at width 0 nothing starts, and the pool naps and resumes when it grows;
#   - the tree is only synced with nothing in flight;
#   - each checkpoint is handed the average in flight, measured.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO/tools/prereset_backfill.sh"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

tree="$(mktemp -d)"
trap 'rm -rf "$tree" /tmp/ct-prereset-pooltest-$$-*' EXIT
EVENTS="$tree/events"
WIDTH_FILE="$tree/width"

export POOL_LAUNCH_GAP=0.1
POOL_CHECK_SECS=0   # a checkpoint after every run, so a width change lands at once
POOL_SYNC_SECS=2    # and a mid-run drain for the sync, at least once
eval "$(grep -E '^(declare -A )?POOL_[A-Z_]+=' "$SCRIPT")"
for fn in pool_mark pool_launch pool_reap pool_drain pool_interval_start pool_checkpoint run_pool; do
  block="$(sed -n "/^$fn() {/,/^}/p" "$SCRIPT")"
  if [ -z "$block" ]; then echo "FAIL tools/prereset_backfill.sh no longer defines $fn()"; exit 1; fi
  eval "$block"
done

now() { echo "$EPOCHREALTIME"; }
FAIL_ID="pooltest-$$-5"
run_claude() {
  echo "start $1 $(now)" >>"$EVENTS"
  sleep "$(awk -v r="$RANDOM" 'BEGIN{printf "%.2f", 0.5 + (r % 40) / 100}')"
  echo "end $1 $(now)" >>"$EVENTS"
  echo "done $1" >"/tmp/ct-prereset-$1.txt"
  [ "$1" != "$FAIL_ID" ]
}
handled=0
# Width 2 to start; 4 after the fourth run is handled; 1 after the tenth; 0 for
# one checkpoint after the thirteenth, then 1 again.
handle() {
  echo "$1 $2" >>"$EVENTS"
  handled=$((handled + 1))
  [ "$handled" = 4 ] && echo 4 >"$WIDTH_FILE"
  [ "$handled" = 10 ] && echo 1 >"$WIDTH_FILE"
  [ "$handled" = 13 ] && echo 0 >"$WIDTH_FILE"
  return 0
}
commit_puzzle() { handle ok "$1"; }
handle_failed_run() { handle fail "$1"; }
echo 2 >"$WIDTH_FILE"
wave_width() {
  local w; w=$(cat "$WIDTH_FILE"); echo "width $w $(now)" >>"$EVENTS"; echo "$w"
  [ "$w" = 0 ] && echo 1 >"$WIDTH_FILE"
}
after_wave() { echo "after failed=$4 avg=$3 hours=$2 pool=$6" >>"$EVENTS"; return 0; }
requeue_failed() { :; }
sync_wave() { echo "sync inflight=${#POOL_RUNS[@]}" >>"$EVENTS"; }
past_deadline() { false; }
alert() { echo "ALERT $*" >>"$EVENTS"; }
python3() {
  case "$1" in
    tools/puzzle_paths.py) echo "puzzles/x/2026/$2.json" ;;
    tools/weekly_usage.py) echo 10 ;;
    *) echo "unexpected python3 $*" >&2; return 1 ;;
  esac
}
DRY_RUN=0 requeued=" " wide=""

ids=()
for i in $(seq 1 16); do ids+=("pooltest-$$-$i"); done
queue=("${ids[@]}") at=0
out=$(run_pool "Annotate" "Annotate @ in @PATH@" 0 2>&1)
check "run_pool returns 0 with nothing stopping it" 0 $?

# One verdict per property, computed from the event log in time order.
verdicts=$(awk -v gap="$POOL_LAUNCH_GAP" -v n="${#ids[@]}" '
  $1 == "width" { w = $2; if (w + 0 > maxw) maxw = w }
  $1 == "start" {
    inflight++; starts++
    if (inflight > w) over++
    if (inflight > peak[w]) peak[w] = inflight
    # runs still going that started before the latest end: a wave scheduler
    # never launches while any of those are in flight
    if (older > 0) refilled_while_busy++
    if (last != "" && $3 - last < gap - 0.03) close_launch++
    last = $3; started[$2]++
  }
  $1 == "end" { inflight--; older = inflight }
  $1 == "ok" || $1 == "fail" { handled[$2]++; kind[$1]++ }
  $1 == "sync" && $2 != "inflight=0" { dirty_sync++ }
  $1 == "sync" { syncs++ }
  $1 == "after" && $2 == "failed=1" { failure_checkpoints++ }
  $1 == "after" {
    split($3, a, "="); avg = a[2]
    if (avg !~ /^[0-9]+\.[0-9][0-9]$/ || avg + 0 > maxw) bad_avg++
    if (avg + 0 > 1) concurrent++
  }
  END {
    for (id in handled) if (handled[id] != 1) twice++
    for (id in started) if (started[id] != 1) twice++
    print "over=" over + 0
    print "refilled=" (refilled_while_busy > 0)
    print "spacing=" close_launch + 0
    print "handled=" length(handled) " ok=" kind["ok"] + 0 " fail=" kind["fail"] + 0 " twice=" twice + 0
    print "peak4=" peak[4] + 0 " peak1=" peak[1] + 0
    print "syncs=" (syncs >= 2) " dirty=" dirty_sync + 0
    print "failure_checkpoint=" failure_checkpoints + 0
    print "avg=" bad_avg + 0 " concurrent=" (concurrent > 0)
  }' "$EVENTS")
get() { printf '%s\n' "$verdicts" | grep "^$1=" | cut -d= -f2-; }

check "never more runs in flight at a launch than the width then" 0 "$(get over)"
check "a freed slot is refilled while other runs are still going" 1 "$(get refilled)"
check "launches are at least POOL_LAUNCH_GAP apart" 0 "$(get spacing)"
check "every id handled exactly once, one through the failure path" \
  "16 ok=15 fail=1 twice=0" "$(get handled)"
check "the width growing to 4 fills four slots" 4 "$(get peak4 | cut -d' ' -f1)"
check "the width shrinking to 1 runs one at a time" "peak1=1" "$(get peak4 | cut -d' ' -f2)"
check "the tree is synced, and only with nothing in flight" "1 dirty=0" "$(get syncs)"
check "a failed run is judged at a checkpoint of its own" 1 "$(get failure_checkpoint)"
check "each checkpoint logs a measured average in flight, within the width" \
  "0 concurrent=1" "$(get avg)"
check "at width 0 the pool naps with nothing in flight" 1 \
  "$(printf '%s\n' "$out" | grep -cm1 '^--- pool of 0: napping')"
check "the pool logs its width for the planner" 1 \
  "$(printf '%s\n' "$out" | grep -cm1 '^--- pool of [0-9][0-9]*: ')"
grep -q '^ALERT' "$EVENTS" && { echo "FAIL alert raised: $(grep '^ALERT' "$EVENTS")"; fails=$((fails + 1)); }

if [ "$fails" -gt 0 ]; then
  echo "--- events"; cat "$EVENTS"; echo "--- output"; printf '%s\n' "$out"
  echo "$fails failed"; exit 1
fi
echo "all pool checks pass"
