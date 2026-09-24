#!/bin/bash
# Does refresh_unsolved ever stop asking for an answer that is never coming?
#
# 367bc80 stopped the nightly annotate/solve queues retrying deterministic
# failures (tools/failed_inputs.py); refresh_unsolved was the other half —
# five Guardian prize puzzles from 2000-2006 and 78 Cyclops puzzles from
# 2006-2009 had no failure to record, just a source that will never publish
# an answer, so they were re-fetched (or re-searched on fifteensquared) every
# night forever. still_worth_refreshing in tools/fetch_puzzle.py is the fix:
# a puzzle already past REFRESH_WINDOW_DAYS since its own date — or since
# provenance.acquiredOn, for the handful still missing a date — drops out of
# the queue for good rather than on any kind of retry schedule.
#
#     bash tools/test_refresh_window.sh
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
tree_before=$(git status --porcelain)

out=$(PYTHONPATH=tools python3 - <<'PY'
from datetime import datetime, timezone
import fetch_puzzle as fetcher

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
DAY_MS = 86_400_000


def at(days_ago):
    return int(NOW.timestamp() * 1000) - days_ago * DAY_MS


# A Saturday prize puzzle 10 days old: still well inside the ~2-week window
# the Guardian actually publishes prize solutions in. Keep refreshing it.
recent = {"date": at(10)}
print("RECENT", fetcher.still_worth_refreshing(recent, now=NOW))

# cryptic-21900: dated 2000-05-18, over 9,600 days ago. No answer has come in
# a quarter of a century of nightly asking; stop.
old = {"date": at(9626)}
print("OLD", fetcher.still_worth_refreshing(old, now=NOW))

# Exactly the window's edge, both sides of it.
print("EDGE_IN", fetcher.still_worth_refreshing({"date": at(90)}, now=NOW))
print("EDGE_OUT", fetcher.still_worth_refreshing({"date": at(91)}, now=NOW))

# An un-backfilled Cyclops carries no `date` at all. Freshly acquired, it has
# no reason to be excluded yet, so it falls back to provenance.acquiredOn.
undated_recent = {"provenance": {"acquiredOn": "2026-09-18"}}
print("UNDATED_RECENT", fetcher.still_worth_refreshing(undated_recent, now=NOW))

# Acquired long ago and still dateless: the fallback ages out the same way a
# real date would.
undated_old = {"provenance": {"acquiredOn": "2020-01-01"}}
print("UNDATED_OLD", fetcher.still_worth_refreshing(undated_old, now=NOW))

# No date and no provenance at all: nothing anchors this puzzle in time, so
# nothing could ever make it "too old" — excluded outright rather than kept
# forever by default.
print("NO_ANCHOR", fetcher.still_worth_refreshing({}, now=NOW))
PY
)

echo "a puzzle within its source's publication window is still refreshed"
same "10-day-old prize puzzle" "$(grep '^RECENT ' <<<"$out")" "RECENT True"

echo "a puzzle no source will ever answer drops out of the nightly queue"
same "9,626-day-old cryptic-21900" "$(grep '^OLD ' <<<"$out")" "OLD False"

echo "the cutoff is exact"
same "90 days is still in" "$(grep '^EDGE_IN ' <<<"$out")" "EDGE_IN True"
same "91 days is out" "$(grep '^EDGE_OUT ' <<<"$out")" "EDGE_OUT False"

echo "an undated puzzle falls back to when this repo acquired it"
same "acquired 6 days ago" "$(grep '^UNDATED_RECENT ' <<<"$out")" "UNDATED_RECENT True"
same "acquired years ago" "$(grep '^UNDATED_OLD ' <<<"$out")" "UNDATED_OLD False"

echo "a puzzle with no date and no provenance is never refreshed"
same "no anchor at all" "$(grep '^NO_ANCHOR ' <<<"$out")" "NO_ANCHOR False"

echo "the working tree is untouched"
same "git status unchanged" "$(git status --porcelain)" "$tree_before"

if [ "$fails" -gt 0 ]; then echo "refresh_window: $fails check(s) failed"; exit 1; fi
echo "refresh_window: all checks passed"
