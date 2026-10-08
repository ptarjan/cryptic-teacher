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

import puzzle_integrity
def refuse(path, puzzle, generator): raise puzzle_integrity.RefusedWrite("refusing to write x-1: SHAPE", [])
def boom(path, puzzle, generator): raise OSError("disk full")
v = {}
check("a refused write is a verdict, not a crash", (False, {"refusedWrite": "refusing to write x-1: SHAPE"}),
      (q.file_puzzle(refuse, "t", "p", {"id": "x-1"}, v), v))
v = {}
import contextlib
with contextlib.redirect_stderr(io.StringIO()):
    ok = q.file_puzzle(boom, "t", "p", {"id": "x-1"}, v)
check("any other write error is a writeFailed verdict", (False, "OSError: disk full"), (ok, v.get("writeFailed")))
v = {}
check("a write that goes through says so", (True, {"wrote": True}),
      (q.file_puzzle(lambda path, puzzle, generator: None, "t", "p", {"id": "x-1"}, v), v))

# A clue holding another clue (two run together, or one read into its
# middle) or the page's text is never written, whatever the filer.
wrote = []
for what, text in (("another clue's number and text", "Did Newman, for the life of 2 Flower sacred to Lake Poet him, so express regret?"),
                   ("a list's heading", "Bilingual agreement on the DOWN board"),
                   ("a bracket it never pairs", "Just a Liberal) reformer beheaded!"),
                   ("the page's text", "There's some depression about the pages being spotty (6. The solution of Saturday's Prize Puzzle No 18,262 will appear next Saturday")):
    v = {}
    ok = q.file_puzzle(lambda path, puzzle, generator: wrote.append(path), "t", "p",
                       {"id": "x-1", "entries": [{"number": 23, "direction": "across", "clue": {"text": text}}]}, v)
    check(f"a clue holding {what} is a refusedWrite, nothing written", (False, True, []),
          (ok, v.get("refusedWrite", "").startswith("refusing to write x-1: 23-across holds"), wrote))

# The reading splits such a clue at its own count, closed or not, or at its
# own number after the page's text.
import ocr_clues
for text, enum, want in (
        ("There's some depression about the pages being spotty (6. The solution of Saturday's Prize Puzzle", "6",
         "There's some depression about the pages being spotty"),
        ("A sort of wave, with ins and outs (5 _ Concise crossword, page 9", "5", "A sort of wave, with ins and outs"),
        ("Turns leaves (4. _", "4", "Turns leaves"),
        ("Taken from Henry (2 Hen. IV) on stage (5) 7 Next", "5", "Taken from Henry (2 Hen. IV) on stage")):
    check(f"cut at its own count: {text[:30]!r}", want, ocr_clues.cut_at_count(text, enum))
for text, lid, want in (
        ("The solution of Saturday's Prize Puzzle No 18., 812 will appear next Saturday. Parker 27 Totally without "
         "vitality", "27-across", "Totally without vitality"),
        ("Sound of a bell. 13 Down's partner", "13-across", "Sound of a bell. 13 Down's partner"),):
    check(f"cut at its own number: {text[:30]!r}", want, ocr_clues.trimmed(text, lid))

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

# The VLM goes down mid-run: the editions read after it failed carry no
# "vlm", a pass while it is still down leaves them, and the first pass once
# it answers reads them again. read_edition's second value is the worker's
# vlm_reader.reachable(), which a failed ask turns False (checked below).
def vlm_rows():
    return {json.loads(l)["edition"][-1]: "vlm" in json.loads(l) for l in aledger.read_text().splitlines()}
real_read = f.read_edition
f.input_hash = lambda d: "files2"
f.read_edition = lambda d, found: ([], d.name < "1990-01-03")
aread()
check("archive.org: editions read after the VLM went down mid-run carry no vlm",
      {"1": True, "2": True, "3": False, "4": False}, vlm_rows())
f.vlm.reachable = lambda: False
check("archive.org: while it is still down, nothing is due", [], aread())
f.vlm.reachable = lambda: True
f.read_edition = lambda d, found: ([], True)
time.sleep(1.1)  # readAt is to the second, and aread() spots a read by it
check("archive.org: once it answers, the next pass reads them again", ["3", "4"], aread())
check("archive.org: and they carry the VLM now", {"1": True, "2": True, "3": True, "4": True}, vlm_rows())
f.read_edition, f.input_hash = real_read, (lambda d: "files")

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
tpuzzles = Path(os.environ["TMP"]) / "tpuzzles"  # not the corpus: reading it outlasts a 0.1s slice
tpuzzles.mkdir()
tledger.write_text(json.dumps({"article": "100", "inputs": F.inputs_of(tcache / "100"), "skip": "x", "readAt": "2026-10-01"}) + "\n"
                   + json.dumps({"article": "200", "inputs": F.inputs_of(tcache / "200"), "skip": "x", "readAt": "2026-09-01"}) + "\n")
read = []
def slow(d, taken):
    read.append(d.name)
    time.sleep(0.2)
    return {"skip": "test"}, None, None
F.consider = slow
def tread(**kw):
    read.clear()
    F.run(tcache, ledger=tledger, out=io.StringIO(), puzzles=tpuzzles, **kw)
    return list(read)
check("Trove: a read article stands, only the never-read one is read", ["300"], tread())
check("Trove: --reread BEFORE reads the oldest-read first, one a slice, the ledger saved after each, then stops",
      [["200"], ["100"], []], [tread(seconds=0.1, reread=stamp) for _ in range(3)])
F.vlm.reachable, F.vlm.version = (lambda: True), (lambda: "v1")
check("Trove: an article read without the VLM is read again once it answers", 3, len(tread()))
F.vlm.version = lambda: "v2"
check("Trove: a new VLM model alone makes nothing due", [], tread())
real_consider = F.consider_article
F.consider_article = lambda d: (read.append(d.name) or ({"skip": "test"}, None, None, d.name < "200"))
check("Trove: every article is read through a mid-run outage", ["100", "200", "300"], sorted(tread(reread=q.when("2100-01-01T00:00:00+00:00"))))
F.vlm.reachable = lambda: False
check("Trove: while the VLM is down, the articles read without it wait", [], tread())
F.vlm.reachable = lambda: True
check("Trove: once it answers, the next pass reads them again", ["200", "300"], sorted(tread()))
F.consider_article = real_consider
check("Trove: articles= reads those again, and no other", ["200"], tread(articles=["200"]))

# A failed ask is what turns a worker's reachable() False mid-run.
import importlib, vlm_reader
importlib.reload(vlm_reader)
from PIL import Image
vlm_reader.URL, vlm_reader._UP[vlm_reader.MODEL] = "http://127.0.0.1:9", True
vlm_reader.CACHE = Path(os.environ["TMP"]) / "vlm"
try:
    vlm_reader.ask(Image.new("L", (4, 4)), "outage test")
except RuntimeError:
    pass
check("a VLM that stops answering mid-run reads as down for the rest of that worker's run", False,
      vlm_reader.reachable())
print(f"FAILS {fails}")
EOF
)
echo "$out"
grep -q '^FAILS 0$' <<<"$out" || { echo "test_scan_queue: failed"; exit 1; }
echo "test_scan_queue: all passed"
