#!/bin/bash
# Does tools/scan_queue.py read the never-read first, never send the queue
# back to the start, keep N sources in flight, stop at its deadline, and let
# only one run hold a ledger?
#
#     bash tools/test_scan_queue.sh
#
# A filer that re-read the same first 150 editions every night, because each
# code change made every row stale and the queue restarted in disk order,
# never reached the other 2,600: the ordering is asserted here, on both
# filers' run(). Temp dirs only; no OCR, no network.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" python3 - <<'EOF'
import io, json, os, time
from pathlib import Path
import scan_queue as q

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

rows = {"a": {"readAt": "2026-10-02"}, "c": {"readAt": "2026-09-01"}, "d": {}}
check("never read first in the caller's order, then the stale oldest-read first (none: first)",
      ["b", "e", "d", "c", "a"],
      q.order(["a", "b", "c", "d", "e"], rows, lambda row: row is None))

got = sorted(r for _, r in q.parallel([(-1,), (-2,), (-3,)], abs, workers=2))
check("a pool of two reads every item", [1, 2, 3], got)
check("nothing starts after the deadline", [], list(q.parallel([(-1,)], abs, workers=2, deadline=time.monotonic() - 1)))
check("serial when one worker, in order", [1, 2], [r for _, r in q.parallel([(-1,), (-2,)], abs)])

ledger = Path(os.environ["TMP"]) / "filed.jsonl"
with q.lock(ledger) as first:
    with q.lock(ledger) as second:
        check("a second run on the same ledger does not get it", (True, False), (first, second))
with q.lock(ledger) as again:
    check("the ledger is free once the first run ends", True, again)

# The archive.org filer: a code change makes every row stale; the next run
# reads the never-read edition, then the one read longest ago.
import file_archive_org_puzzles as f
cache = Path(os.environ["TMP"]) / "cache"
eds = []
for name in ("1990-01-01_1", "1990-01-02_2", "1990-01-03_3"):
    d = cache / "NewsUK1990UKEnglish" / name
    d.mkdir(parents=True)
    eds.append(d)
f.edition_dirs = lambda cache, paper=None: eds
f.scan = lambda d: {"date": "1990-01-01", "item": "x", "solutions": [], "puzzles": []}
f.input_hash = lambda d, code: code[:4] or "files"
f.held_numbers = lambda series="times": set()
aledger = Path(os.environ["TMP"]) / "a.jsonl"
scan = f.scan(None)
aledger.write_text("".join(json.dumps(r) + "\n" for r in [
    {"edition": "NewsUK1990UKEnglish/1990-01-01_1", "hash": "old", "scan": scan, "filesHash": "files",
     "solutionsSeen": [], "verdicts": [], "readAt": "2026-10-01T00:00:00+00:00"},
    {"edition": "NewsUK1990UKEnglish/1990-01-02_2", "hash": "old", "scan": scan, "filesHash": "files",
     "solutionsSeen": [], "verdicts": [], "readAt": "2026-09-01T00:00:00+00:00"},
    {"edition": "NewsUK1990UKEnglish/1990-01-03_3", "scan": scan, "filesHash": "files"}]))
order = []
for limit in (1, 1, 1):
    before = {json.loads(l)["edition"]: json.loads(l).get("readAt") for l in aledger.read_text().splitlines()}
    f.run(cache, ledger=aledger, out=io.StringIO(), limit=limit)
    after = {json.loads(l)["edition"]: json.loads(l).get("readAt") for l in aledger.read_text().splitlines()}
    order += [e.split("_")[1] for e in after if after[e] != before[e]]
check("archive.org: never-read first, then stale oldest-read first, one edition a run", ["3", "2", "1"], order)

# The Trove filer, the same way.
import file_trove_puzzles as F
tcache = Path(os.environ["TMP"]) / "trove"
for a in ("100", "200", "300"):
    (tcache / a).mkdir(parents=True)
    (tcache / a / "meta.json").write_text("{}")
tledger = Path(os.environ["TMP"]) / "t.jsonl"
tledger.write_text(json.dumps({"article": "100", "hash": "old", "skip": "x", "readAt": "2026-10-01"}) + "\n"
                   + json.dumps({"article": "200", "hash": "old", "skip": "x", "readAt": "2026-09-01"}) + "\n")
read = []
def slow(d, taken):
    read.append(d.name)
    time.sleep(0.2)
    return {"skip": "test"}, None
F.consider = slow
F.run(tcache, ledger=tledger, out=io.StringIO(), seconds=0.1)
F.run(tcache, ledger=tledger, out=io.StringIO(), seconds=0.1)
F.run(tcache, ledger=tledger, out=io.StringIO(), seconds=0.1)
check("Trove: never-read first, then stale oldest-read first, the ledger saved after each", ["300", "200", "100"], read)

print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_scan_queue: failed"; exit 1; }
echo "test_scan_queue: all passed"
