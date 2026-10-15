#!/bin/bash
# Does refresh_unsolved ever stop asking for an answer that is never coming?
#
# refresh_unsolved skips puzzles whose source will never publish an answer
# (old Guardian prize puzzles, Cyclops puzzles): still_worth_refreshing in
# tools/fetch_puzzle.py drops a puzzle once it is past REFRESH_WINDOW_DAYS
# since its own date — or since source.acquiredOn, when it has no date —
# for good rather than on any retry schedule.
#
#     bash tools/test_refresh_window.sh
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
tree_before=$(git status --porcelain)

out=$(PYTHONPATH=tools python3 - <<'PY'
from datetime import datetime, timedelta, timezone
import fetch_puzzle as fetcher

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def at(days_ago):
    return (NOW - timedelta(days=days_ago)).date().isoformat()


# A Saturday prize puzzle 10 days old: still well inside the ~2-week window
# the Guardian actually publishes prize solutions in. Keep refreshing it.
recent = {"date": at(10)}
print("RECENT", fetcher.still_worth_refreshing(recent, now=NOW))

# cryptic-21900: dated 2000-05-18, over 9,600 days ago. Far past the window.
old = {"date": at(9626)}
print("OLD", fetcher.still_worth_refreshing(old, now=NOW))

# Exactly the window's edge, both sides of it.
print("EDGE_IN", fetcher.still_worth_refreshing({"date": at(90)}, now=NOW))
print("EDGE_OUT", fetcher.still_worth_refreshing({"date": at(91)}, now=NOW))

# An un-backfilled Cyclops carries no `date` at all. Freshly acquired, it has
# no reason to be excluded yet, so it falls back to source.acquiredOn.
undated_recent = {"source": {"acquiredOn": "2026-09-18"}}
print("UNDATED_RECENT", fetcher.still_worth_refreshing(undated_recent, now=NOW))

# Acquired long ago and still dateless: the fallback ages out the same way a
# real date would.
undated_old = {"source": {"acquiredOn": "2020-01-01"}}
print("UNDATED_OLD", fetcher.still_worth_refreshing(undated_old, now=NOW))

# No date and no source at all: nothing anchors this puzzle in time, so
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

echo "a puzzle with no date and no source is never refreshed"
same "no anchor at all" "$(grep '^NO_ANCHOR ' <<<"$out")" "NO_ANCHOR False"

out2=$(PYTHONPATH=tools python3 - <<'PY' 2>&1
import datetime
import fetch_puzzle as fetcher

# A file stores no `series`: refresh_unsolved holds the raw file,
# so it must read the series off the id, not crash with KeyError.
today = datetime.date.today().isoformat()
raw = {"id": "cryptic-99999", "number": 99999, "date": today,
       "entries": [{"solution": None}]}
asked = []
fetcher.puzzle_files = lambda *series: ["x"]
fetcher.read_puzzle_file = lambda path: raw
fetcher.fetch_number = lambda num, series, **kw: (asked.append((num, series)) or (raw, None))
fetcher.reindex = lambda: None
fetcher.time.sleep = lambda s: None
fetcher.refresh_unsolved()
print("ASKED", asked)
PY
)

echo "a file with no stored series is still refreshed"
same "series read from the id" "$(grep '^ASKED ' <<<"$out2")" "ASKED [(99999, 'cryptic')]"

out3=$(PYTHONPATH=tools python3 - <<'PY' 2>&1
import copy, json, tempfile
from pathlib import Path
import fetch_puzzle as fetcher, series

# A re-fetch builds the puzzle fresh, naming its series and name, and merges
# the held annotations onto it: the write stores neither. Nor does the write
# of a fresh puzzle with no annotation at all.
src = fetcher.resolve_puzzle("cryptic-30136")
old = fetcher.read_puzzle_file(src)
fresh = copy.deepcopy(old)
for e in fresh["entries"]:
    e.pop("annotation", None)
fresh.update(series="cryptic", name=series.display_name(old))
fetcher.merge_annotations(fresh, old)
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / src.name
    fetcher.write_puzzle_file(path, fresh)
    back = json.loads(path.read_text())
    bare = copy.deepcopy(fresh)
    for e in bare["entries"]:
        e.pop("annotation", None)
    path.unlink()
    fetcher.write_puzzle_file(path, bare)
    plain = json.loads(path.read_text())
held = sum(1 for e in old["entries"] if e.get("annotation"))
kept = sum(1 for e in back["entries"] if e.get("annotation"))
print("REFETCH", "series" in back, "name" in back, kept == held > 0)
print("FRESH", "series" in plain, "name" in plain)
PY
)

echo "a re-fetch is written in the format, its annotations kept; so is a fresh puzzle"
same "refetch written" "$(grep '^REFETCH ' <<<"$out3" || echo "$out3" | tail -3)" "REFETCH False False True"
same "fresh puzzle written" "$(grep '^FRESH ' <<<"$out3" || echo "$out3" | tail -3)" "FRESH False False"

out4=$(PYTHONPATH=tools python3 - <<'PY' 2>&1
import datetime, tempfile
from pathlib import Path
import fetch_puzzle as fetcher

# A reindex is a whole-corpus pass. A still-withheld puzzle whose re-fetch
# writes back the same bytes moves nothing in the index, so the refresh must
# not reindex for it, nor let fetch_number reindex per puzzle; a re-fetch that
# changes the file reindexes exactly once, after the lot.
today = datetime.date.today().isoformat()
d = Path(tempfile.mkdtemp())
raws = {n: {"id": f"cryptic-{n}", "number": n, "date": today,
            "entries": [{"solution": None}]} for n in (99998, 99999)}
for n in raws:
    (d / f"cryptic-{n}.json").write_text("held")
fetcher.puzzle_files = lambda *series: sorted(raws)
fetcher.read_puzzle_file = lambda path: raws[path]
fetcher.puzzle_path = lambda series, num: d / f"{series}-{num}.json"
fetcher.time.sleep = lambda s: None
reindexed, flags = [], []
fetcher.reindex = lambda: reindexed.append(1)

def refetch(changes):
    def fetch_number(num, series, reindexed=True):
        flags.append(reindexed)
        if num in changes:
            (d / f"{series}-{num}.json").write_text("new answers")
        else:
            (d / f"{series}-{num}.json").write_text("held")  # same bytes rewritten
        return raws[num], False
    return fetch_number

fetcher.fetch_number = refetch(set())
fetcher.refresh_unsolved()
print("UNCHANGED", len(reindexed), flags)
reindexed.clear(); flags.clear()
fetcher.fetch_number = refetch({99998})
fetcher.refresh_unsolved()
print("CHANGED", len(reindexed), flags)

import fetch_observer as obs
obs.puzzle_files = lambda *series: ["x"]
obs.read_puzzle_view = lambda path: {"series": "everyman", "number": 4173, "date": today,
                                     "entries": [{"solution": None}]}
obs.article_uuid = lambda num: "u"
obs.puzzle_manifest = lambda uuid: {}
obs.puzzle_data = lambda m: {"copy": {"settings": {"solution": None}}}
obs.time.sleep = lambda s: None
obs_reindexed = []
obs.reindex = lambda: obs_reindexed.append(1)
obs.refresh_unsolved()
print("OBSERVER_WITHHELD", len(obs_reindexed))
PY
)

echo "a refresh reindexes once, and only when a re-fetch changed a file"
same "same bytes back: no reindex, none per puzzle" "$(grep '^UNCHANGED ' <<<"$out4" || echo "$out4" | tail -3)" "UNCHANGED 0 [False, False]"
same "one file changed: one reindex after the lot" "$(grep '^CHANGED ' <<<"$out4" || echo "$out4" | tail -3)" "CHANGED 1 [False, False]"
same "an Everyman still in its window: no reindex" "$(grep '^OBSERVER_WITHHELD ' <<<"$out4" || echo "$out4" | tail -3)" "OBSERVER_WITHHELD 0"

echo "the working tree is untouched"
same "git status unchanged" "$(git status --porcelain)" "$tree_before"

if [ "$fails" -gt 0 ]; then echo "refresh_window: $fails check(s) failed"; exit 1; fi
echo "refresh_window: all checks passed"
