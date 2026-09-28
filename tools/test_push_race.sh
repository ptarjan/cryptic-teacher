#!/bin/bash
# Does a fetch/push that loses the ref-lock race get retried, or does it just
# alert like 2026-09-27's nightly run did?
#
# daily_update.sh and prereset_backfill.sh each run in their own worktree of
# the SAME repo, sharing one .git and so one refs/remotes/origin/master. A
# fetch or push that lands while the other is mid-fetch/push fails with
# "cannot lock ref 'refs/remotes/origin/master': is at X but expected Y" —
# the ref moved under us, not a conflict — and that night the push's one
# attempt hit exactly this and gave up, stranding a finished commit until it
# was pushed by hand.
#
# push_race_retry (tools/nightly_worktree.sh) is what both scripts now route
# every fetch+rebase+push attempt through. It is read out of the real file
# and sourced directly — not copied here — so the thing under test is the
# thing that runs, the same convention tools/test_push_conflict.sh uses for
# its own function.
#
#     bash tools/test_push_race.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

# Sourcing pulls in the CT_IN_WORKTREE re-exec dance too, so it must see
# itself already "in the worktree" or it tries to exec a job that doesn't
# exist.
export CT_IN_WORKTREE=1
. tools/nightly_worktree.sh

# The backoff itself is not what these checks are about, and a real one would
# make this test the slowest thing in the suite for no reason (1+2+3+4s here).
sleep() { :; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
counter="$tmp/count"

echo "succeeds first try: called once, no retry noise:"
: > "$counter"
attempt_ok() { echo "$((0))" >>"$counter"; return 0; }
out="$(push_race_retry attempt_ok 2>&1)"; rc=$?
check "returns success" "$rc" "0"
check "called exactly once" "$(wc -l <"$counter" | tr -d ' ')" "1"
check "no retry message" "$(echo "$out" | grep -c 'retrying')" "0"

echo "a ref-lock failure is retried and then succeeds:"
: > "$counter"
attempt_lock_then_ok() {
  echo x >>"$counter"
  n=$(wc -l <"$counter")
  if [ "$n" -lt 3 ]; then
    echo "error: cannot lock ref 'refs/remotes/origin/master': is at ad49c99 but expected 7a24e5a" >&2
    return 1
  fi
  return 0
}
out="$(push_race_retry attempt_lock_then_ok 2>&1)"; rc=$?
check "eventually returns success" "$rc" "0"
check "retried the expected number of times" "$(wc -l <"$counter" | tr -d ' ')" "3"
check "says it is retrying a push race" "$(echo "$out" | grep -c 'push race')" "2"

echo "a real conflict is NOT retried:"
: > "$counter"
attempt_conflict() {
  echo x >>"$counter"
  echo "error: could not apply 1234567... some commit" >&2
  return 1
}
out="$(push_race_retry attempt_conflict 2>&1)"; rc=$?
check "returns the failure" "$rc" "1"
check "called exactly once — no retry on a real conflict" \
  "$(wc -l <"$counter" | tr -d ' ')" "1"
check "the caller still sees the real error" \
  "$(echo "$out" | grep -c 'could not apply')" "1"

echo "a lock error that never clears eventually gives up:"
: > "$counter"
attempt_always_locked() {
  echo x >>"$counter"
  echo "error: cannot lock ref 'refs/remotes/origin/master': is at aaa but expected bbb" >&2
  return 1
}
push_race_retry attempt_always_locked >/dev/null 2>&1; rc=$?
check "returns failure, not success" "$rc" "1"
check "stops retrying rather than looping forever" \
  "$([ "$(cat "$counter" | wc -l | tr -d ' ')" -le 5 ] && echo yes || echo no)" "yes"

if [ "$fails" -eq 0 ]; then echo "push race: all checks passed"; else
  echo "push race: $fails check(s) failed"; exit 1; fi
