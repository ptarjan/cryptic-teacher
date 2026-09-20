#!/bin/bash
# Does the pre-reset backfill still take over a lock nobody is holding?
#
#     bash tools/test_prereset_lock.sh
#
# The lock is a directory, and the only thing that removes it is an EXIT trap.
# A container restart on 2026-09-20 killed a run that held it at 20:15 the
# night before, and every hourly fire for the next three hours read the orphan
# as a healthy sibling and exited having done nothing — the job was locked out
# of its own queue by a directory with no process behind it.
#
# So the holder writes its pid inside, and the decision is lock_is_dead. It is
# read out of tools/prereset_backfill.sh rather than copied here, because a
# copy passes forever after the original changes. The cases are the ones that
# actually arise: an orphan, a lock taken before pids were written at all, a
# pid the kernel has since handed to something else, and a real live run.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

block="$(sed -n '/^lock_is_dead() {/,/^}/p' "$REPO/tools/prereset_backfill.sh")"
if [ -z "$block" ]; then
  echo "FAIL tools/prereset_backfill.sh no longer defines lock_is_dead()"
  exit 1
fi

tree="$(mktemp -d)"
trap 'rm -rf "$tree"' EXIT
LOCK="$tree/.prereset.lock"
mkdir "$LOCK"
eval "$block"

verdict() { lock_is_dead && echo dead || echo held; }

check "a lock with no pid in it is an orphan" "dead" "$(verdict)"
: > "$LOCK/pid"
check "a lock written before pids were is an orphan" "dead" "$(verdict)"
# Large enough to be out of range on Linux and macOS alike, so it names nothing.
echo 4194304 > "$LOCK/pid"
check "a pid nothing is running under is an orphan" "dead" "$(verdict)"
# A live process that is not this job: pids are reused, and a restart hands
# them out again from the bottom, so existence alone would read as held.
echo $$ > "$LOCK/pid"
check "a live pid running something else is an orphan" "dead" "$(verdict)"

# And the case the lock exists for. exec -a gives a real, live process the
# argv of a backfill without running one.
bash -c 'exec -a "bash tools/prereset_backfill.sh" sleep 30' &
holder=$!
echo "$holder" > "$LOCK/pid"
# The exec has to have landed before the command line is read.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  ps -o command= -p "$holder" 2>/dev/null | grep prereset_backfill >/dev/null && break
  sleep 0.2
done
check "a live backfill is left alone" "held" "$(verdict)"
kill "$holder" 2>/dev/null
wait "$holder" 2>/dev/null

if [ "$fails" -gt 0 ]; then echo "prereset lock: $fails check(s) failed"; exit 1; fi
echo "prereset lock: all checks passed"
