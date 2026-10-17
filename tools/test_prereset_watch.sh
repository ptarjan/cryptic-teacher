#!/bin/bash
# Does tools/prereset_watch.sh see a burn that is alive but stuck, and one that
# is dead with orphans holding its tree lease?
#
#     bash tools/test_prereset_watch.sh
#
# Real processes stand in for the burn and the orphans (a sleep with the burn's
# script name in its argv, one holding the lease on fd 9); the lease, the lock,
# the logs and the .rc files are all in a temp dir.
#   - a burn with a recent log line, or no finished run waiting: silent;
#   - a burn with a quiet log and a finished run unreaped: logged and alerted,
#     and left running;
#   - no burn and an orphan holding the lease: the orphan killed, the lease free;
#   - no burn and a holder with a live parent (a start in progress): left alone.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}
tree="$(mktemp -d)"
pids=""
trap 'kill $pids 2>/dev/null; rm -rf "$tree"' EXIT
mkdir -p "$tree/rc" "$tree/logs" "$tree/lock"
export WATCH_LEASE="$tree/lease" WATCH_LOCK="$tree/lock" WATCH_RC_DIR="$tree/rc" WATCH_LOG_DIR="$tree/logs"
export WATCH_STUCK_MIN=15 WATCH_KILL_WAIT=3
export ALERT_ENV_FILE="$tree/.env" ALERT_STATE_DIR="$tree/state"   # no wake.sh there: alerts only print
: >"$WATCH_LEASE"

watch() { bash "$REPO/tools/prereset_watch.sh" 2>&1; }
old() { touch -d '30 minutes ago' "$@"; }

# A stand-in burn: a process whose command line names the script.
bash -c 'exec -a prereset_backfill.sh sleep 300' &
burn=$!; pids="$pids $burn"
echo "$burn" >"$tree/lock/pid"

: >"$tree/logs/cryptic-prereset.AAAA"
: >"$tree/rc/ct-prereset-puz-1.rc"; old "$tree/rc/ct-prereset-puz-1.rc"
out=$(watch)
check "a burn logging a line a minute ago is left alone, finished run or not" "" "$out"

old "$tree/logs/cryptic-prereset.AAAA"
out=$(watch)
check "a quiet log with a finished run waiting is logged as stuck" 1 \
  "$(printf '%s\n' "$out" | grep -c 'watchdog: the burn (pid '"$burn"') is alive but stuck.*puz-1')"
check "and alerted" 1 "$(printf '%s\n' "$out" | grep -c '^ALERT: the pre-reset burn (pid '"$burn"') is alive but stuck')"
check "and left running" 0 "$(kill -0 "$burn" 2>/dev/null; echo $?)"

rm -f "$tree/rc/ct-prereset-puz-1.rc"
: >"$tree/rc/ct-prereset-puz-2.rc"   # finished a moment ago: not stuck yet
out=$(watch)
check "a quiet log with only a just-finished run is not stuck" "" "$out"
rm -f "$tree/rc/ct-prereset-puz-2.rc"
out=$(watch)
check "a quiet log with no finished run (long runs in flight) is not stuck" "" "$out"

# A burn whose child is the startup reindex: a quiet log and a finished run are
# the reindex being slow, so it is said once in the log and alerted only past
# WATCH_REINDEX_MIN.
printf '%s\n' 'bash -c '"'"'exec -a "python3 tools/fetch_puzzle.py --reindex" sleep 300'"'"' &' 'wait' >"$tree/burn2.sh"
bash -c 'exec -a prereset_backfill.sh bash "$0"' "$tree/burn2.sh" &
burn2=$!; pids="$pids $burn2"
echo "$burn2" >"$tree/lock/pid"
sleep 0.5
: >"$tree/rc/ct-prereset-puz-3.rc"; old "$tree/rc/ct-prereset-puz-3.rc"
out=$(watch)
check "a quiet log inside the startup reindex is named as the reindex, not stuck" "1 0 0" \
  "$(printf '%s\n' "$out" | grep -c 'in its reindex.*not a stuck reap loop') $(printf '%s\n' "$out" | grep -c 'alive but stuck') $(printf '%s\n' "$out" | grep -c '^ALERT')"
out=$(WATCH_REINDEX_MIN=0 watch)
check "a reindex past the limit alerts, naming the reindex" "1 0" \
  "$(printf '%s\n' "$out" | grep -c '^ALERT: .*in fetch_puzzle.py --reindex') $(printf '%s\n' "$out" | grep -c 'alive but stuck')"
kill "$burn2"; rm -f "$tree/rc/ct-prereset-puz-3.rc"
echo "$burn" >"$tree/lock/pid"

# The burn dies; an orphan of it (its run, parent gone) keeps the lease.
kill "$burn"; wait "$burn" 2>/dev/null
cat >"$tree/orphan.sh" <<'EOF'
exec 9>"$1"
flock -n 9 || exit 1
setsid bash -c 'exec -a claude-orphan sleep 300' &
EOF
out=$(watch)
check "no burn and no lease holder: silent" "" "$out"

bash "$tree/orphan.sh" "$WATCH_LEASE"
sleep 0.5
orphan=$(ls -l /proc/*/fd/9 2>/dev/null | awk -v l="$WATCH_LEASE" '$NF == l { split($9, a, "/"); print a[3] }' | head -1)
pids="$pids $orphan"
check "the orphan holds the lease" 1 "$([ -n "$orphan" ] && echo 1)"
out=$(watch)
check "an orphan of a dead burn is killed, the lease freed" "dead free" \
  "$(kill -0 "$orphan" 2>/dev/null && echo alive || echo dead) $(flock -n "$WATCH_LEASE" true && echo free || echo held)"
check "it is logged and alerted" "1 1" \
  "$(printf '%s\n' "$out" | grep -c 'watchdog: no live burn, but orphans hold') $(printf '%s\n' "$out" | grep -c '^ALERT: the pre-reset burn was dead with orphaned runs')"

# A start in progress: it holds the lease under a live parent, before the lock.
bash -c 'exec 9>"$0"; flock -n 9; exec -a starting-burn sleep 300' "$WATCH_LEASE" &
starter=$!; pids="$pids $starter"
sleep 0.5
out=$(watch)
check "a lease holder with a live parent and no burn lock is a start in progress, left alone" \
  "1 0" "$(printf '%s\n' "$out" | grep -c 'start in progress') $(kill -0 "$starter" 2>/dev/null; echo $?)"

if [ "$fails" -gt 0 ]; then echo "$fails failed"; exit 1; fi
echo "all watchdog checks pass"
