#!/bin/bash
# Is the landing report keyed to the week's real reset, not to CT_SPEND_BY?
#
#     bash tools/test_prereset_landing.sh
#
# The burn records "meter at N%, week turns over at T" after every wave and
# reports the landing on the first fire past T. T must be the real reset: a
# spend-by deadline as T reports a turnover days before the meter resets.
#
# real_reset_at is read out of tools/prereset_backfill.sh rather than copied,
# and weekly_usage.py is stubbed to answer the way it does: the spend-by
# deadline when CT_SPEND_BY is set, the real reset when it is not.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

block="$(sed -n '/^real_reset_at() {/,/^}/p' "$REPO/tools/prereset_backfill.sh")"
if [ -z "$block" ]; then
  echo "FAIL tools/prereset_backfill.sh no longer defines real_reset_at()"
  exit 1
fi
eval "$block"

python3() { if [ -n "${CT_SPEND_BY:-}" ]; then echo 0.5; else echo "$REAL_HOURS"; fi; }
hours_away() { awk -v t="$1" -v n="$(date +%s)" 'BEGIN{printf "%d", (t - n) / 3600 + 0.5}'; }

REAL_HOURS=78.9
export CT_SPEND_BY="2026-09-26T21:45:00-06:00"
check "a spend-by deadline does not move the landing" "79" "$(hours_away "$(real_reset_at)")"
unset CT_SPEND_BY
check "without one the landing is the real reset" "79" "$(hours_away "$(real_reset_at)")"
REAL_HOURS=""
check "an unreadable reset writes no landing" "" "$(real_reset_at)"

if [ "$fails" -gt 0 ]; then echo "prereset landing: $fails check(s) failed"; exit 1; fi
echo "prereset landing: all checks passed"
