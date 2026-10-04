#!/bin/bash
# Does tools/scan_queue.py read the never-read first, never send the queue
# back to the start, keep N sources in flight, stop at its deadline, and let
# only one run hold a ledger?
#
#     bash tools/test_scan_queue.sh
#
# A filer keys each source by its inputs alone; an explicit --reread BEFORE
# reads the rest again, oldest-read first, resuming across capped runs: the
# ordering and the keying are asserted here, on both filers' run(). Temp
# dirs only; no OCR, no network.
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

# One item that raises is logged with its error and stands as failed()'s
# result (or is left out), in a pool and serially; the rest still read.
import contextlib, io
def bad(x):
    if x == 2:
        raise ValueError("height and width must be > 0")
    return x
for workers in (1, 2):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = sorted((i[0], r) for i, r in q.parallel([(1,), (2,), (3,)], bad, workers=workers,
                                                      failed=lambda item, e: f"failed: {e}"))
        left = sorted(r for _, r in q.parallel([(1,), (2,), (3,)], bad, workers=workers))
    check(f"workers={workers}: a raising item stands as failed()'s result, the rest read",
          [(1, 1), (2, "failed: ValueError: height and width must be > 0"), (3, 3)], got)
    check(f"workers={workers}: without failed() it is left out", [1, 3], left)
    check(f"workers={workers}: the log names the item and the error", True,
          "failed 2: ValueError: height and width must be > 0" in err.getvalue())

ledger = Path(os.environ["TMP"]) / "filed.jsonl"
with q.lock(ledger) as first:
    with q.lock(ledger) as second:
        check("a second run on the same ledger does not get it", (True, False), (first, second))
with q.lock(ledger) as again:
    check("the ledger is free once the first run ends", True, again)

# The archive.org filer: a row keyed by code and files together reads as
# done for its files (a change of code alone makes nothing due); --reread
# BEFORE reads the rows last read before it, the never-read first, then the
# oldest-read, and a capped rerun resumes rather than restarts.
import file_archive_org_puzzles as f
f.vlm.reachable = lambda: False
cache = Path(os.environ["TMP"]) / "cache"
eds = []
for name in ("1990-01-01_1", "1990-01-02_2", "1990-01-03_3", "1990-01-04_4"):
    d = cache / "NewsUK1990UKEnglish" / name
    d.mkdir(parents=True)
    eds.append(d)
f.edition_dirs = lambda cache, paper=None: eds
f.scan = lambda d: {"date": "1990-01-01", "item": "x", "solutions": [], "puzzles": []}
f.input_hash = lambda d: "files"
f.held_numbers = lambda series="times": set()
aledger = Path(os.environ["TMP"]) / "a.jsonl"
scan = f.scan(None)
aledger.write_text("".join(json.dumps(r) + "\n" for r in [
    {"edition": "NewsUK1990UKEnglish/1990-01-01_1", "hash": "old", "scan": scan, "filesHash": "files",
     "solutionsSeen": [], "verdicts": [], "readAt": "2026-10-01T00:00:00+00:00"},
    {"edition": "NewsUK1990UKEnglish/1990-01-02_2", "hash": "old", "scan": scan, "filesHash": "files",
     "solutionsSeen": [], "verdicts": []},
    {"edition": "NewsUK1990UKEnglish/1990-01-03_3", "scan": scan, "filesHash": "files"},
    {"edition": "NewsUK1990UKEnglish/1990-01-04_4", "hash": "old", "scan": scan, "filesHash": "files",
     "solutionsSeen": [], "verdicts": [], "readAt": "2026-10-03T00:00:00+00:00"}]))
def aread(**kw):
    before = {json.loads(l)["edition"]: json.loads(l).get("readAt") for l in aledger.read_text().splitlines()}
    f.run(cache, ledger=aledger, out=io.StringIO(), **kw)
    after = {json.loads(l)["edition"]: json.loads(l).get("readAt") for l in aledger.read_text().splitlines()}
    return [e.split("_")[1] for e in after if after[e] != before[e]]
check("archive.org: after the key change only the never-read edition is read", ["3"], aread())
check("archive.org: and then nothing", [], aread())
stamp = q.when("2026-10-02T00:00:00+00:00")
check("archive.org: --reread BEFORE reads the oldest-read first (none: first), one a run, then stops",
      [["2"], ["1"], []], [aread(limit=1, reread=stamp) for _ in range(3)])
f.vlm.reachable, f.vlm.version = (lambda: True), (lambda: "v1")
aread()
check("archive.org: an edition read without the VLM is read again once it answers", ["v1"] * 4,
      [json.loads(l).get("vlm") for l in aledger.read_text().splitlines()])
f.vlm.version = lambda: "v2"
check("archive.org: a new VLM model alone makes nothing due", [], aread())

real_scan = f.scan
def raising(d):
    raise ValueError("height and width must be > 0")
f.scan = raising
f.input_hash = lambda d: "new files"
err = io.StringIO()
with contextlib.redirect_stderr(err):
    rows = f.run(cache, ledger=aledger, out=io.StringIO(), workers=2)
check("archive.org: an edition whose scan raises is logged and kept as failed, the run goes on",
      (4, True), (sum(1 for r in rows if r["scan"].get("failed")), "failed " in err.getvalue()))
f.scan, f.input_hash = real_scan, (lambda d: "files")

# The Trove filer, the same way.
import file_trove_puzzles as F
F.vlm.reachable = lambda: False
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
def tread(**kw):
    read.clear()
    F.run(tcache, ledger=tledger, out=io.StringIO(), **kw)
    return list(read)
check("Trove: after the key change only the never-read article is read", ["300"], tread())
check("Trove: --reread BEFORE reads the oldest-read first, one a slice, the ledger saved after each, then stops",
      [["200"], ["100"], []], [tread(seconds=0.1, reread=stamp) for _ in range(3)])
F.vlm.reachable, F.vlm.version = (lambda: True), (lambda: "v1")
check("Trove: an article read without the VLM is read again once it answers", 3, len(tread()))
F.vlm.version = lambda: "v2"
check("Trove: a new VLM model alone makes nothing due", [], tread())

print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_scan_queue: failed"; exit 1; }
echo "test_scan_queue: all passed"
