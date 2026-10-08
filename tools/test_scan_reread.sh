#!/bin/bash
# Does an annotation that meets a misread clue on an OCR'd puzzle ask its scan
# to be read again, does the burn leave that puzzle alone until the re-read
# lands, and does a re-read that agrees give it back without asking again?
#
#     bash tools/test_scan_reread.sh
#
# annotate_check.misread names what met a misread (a printedClue row HEAD
# lacks, check_anagram_letters); scan_queue.request_reread files one request
# per reading of the clues, only for an OCR channel whose source a filer's
# ledger names; the request is open until that ledger row's readAt passes it;
# prereset_plan --backlog leaves the open ones out. Temp files only.
set -uo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
out=$(TMP="$tmp" SCAN_REREAD_REQUESTS="$tmp/requests.jsonl" PYTHONPATH=tools python3 - <<'PY'
import contextlib, copy, io, json, os, shutil
from pathlib import Path
import annotate_check as AC
import fetch_puzzle as F
import prereset_plan as P
import scan_queue as q

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

tmp = Path(os.environ["TMP"])
pid = "times-18749"
src = F.puzzle_paths.find(pid)
path = tmp / src.name
shutil.copy(src, path)
puzzle = F.read_puzzle_file(path)
data = tmp / "data"
data.mkdir()
shutil.copy(AC.DATA / "source_clue_wrong.json", data / "source_clue_wrong.json")
AC.DATA = data

clues, why = AC.misread(path)
check("a clean annotation met no misread", [], why)
rows = json.loads((data / "source_clue_wrong.json").read_text())
eid = f"{puzzle['entries'][0]['number']}-{puzzle['entries'][0]['direction']}"
rows[f"{pid}/{eid}"] = ["shown", "printed", "OCR misread: test"]
(data / "source_clue_wrong.json").write_text(json.dumps(rows))
check("a printedClue row HEAD lacks is a misread", ["printedClue"], AC.misread(path)[1])
(data / "source_clue_wrong.json").write_text(json.dumps({k: v for k, v in rows.items() if k != f"{pid}/{eid}"}))
broken = copy.deepcopy(puzzle)
step = next(a for e in broken["entries"] for a in ((e.get("annotation") or {}).get("assembly") or {}).get("anagrams", ()))
step["fodder"] = "QQQ" + step["fodder"]
path.write_text(json.dumps(broken))
check("fodder that cannot give its letters is a misread", ["check_anagram_letters"], AC.misread(path)[1])
lost = copy.deepcopy(puzzle)
lost["entries"][0]["annotation"] = None
path.write_text(json.dumps(lost))
check("a clue the run left null is a misread", ["lostClue"], AC.misread(path)[1])

# The filers' ledgers: the archive.org edition this puzzle was filed from.
q.LEDGERS = {"archive": tmp / "a.jsonl", "trove": tmp / "t.jsonl"}
def ledger(read_at):
    q.LEDGERS["archive"].write_text(json.dumps(
        {"edition": "NewsUK1990UKEnglish/1990-01-02_1", "readAt": read_at,
         "verdicts": [{"number": 18749, "id": pid}]}) + "\n")
ledger("2026-10-01T00:00:00+00:00")

publisher = {**puzzle, "source": {**puzzle["source"], "retrievedFrom": "publisher"}}
check("a publisher's puzzle asks for no re-read", None, q.request_reread(publisher, clues, ["printedClue"]))
check("a puzzle no ledger names asks for no re-read", None,
      q.request_reread({**puzzle, "id": "times-1"}, clues, ["printedClue"]))
req = q.request_reread(puzzle, clues, ["check_anagram_letters"])
check("an OCR'd puzzle's misread asks for its edition", ("archive", "NewsUK1990UKEnglish/1990-01-02_1"),
      req and (req["filer"], req["source"]))
check("the same clues ask once", None, q.request_reread(puzzle, clues, ["printedClue"]))
check("it is open until the edition is read again", [pid], [r["id"] for r in q.open_requests()])
def requested(*argv):
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        q.main(["requested", *argv])
    return b.getvalue().split()
check("`requested archive times` names the edition", ["NewsUK1990UKEnglish/1990-01-02_1"],
      requested("archive", "times"))
check("`requested archive ft` does not", [], requested("archive", "ft"))

# The burn's queue leaves it out while the re-read is open.
index = tmp / "index.json"
index.write_text(json.dumps({"puzzles": [
    {"id": pid, "series": "times", "date": "1990-01-02", "annotated": False, "hasSolutions": True},
    {"id": "times-18750", "series": "times", "date": "1990-01-03", "annotated": False, "hasSolutions": True}]}))
P.INDEX = index
def backlog():
    b = io.StringIO()
    with contextlib.redirect_stdout(b), contextlib.redirect_stderr(io.StringIO()):
        P.print_backlog("", "")
    return b.getvalue().split()
check("the burn skips a puzzle waiting on its re-read", ["times-18750"], backlog())

# The re-read lands and reads the same clues: the puzzle is the burn's again,
# and failing on them again asks for nothing.
ledger("2099-01-01T00:00:00+00:00")
check("the re-read closes the request", [], q.open_requests())
check("then the burn takes it again", ["times-18750", pid], backlog())
check("and the same clues ask no second re-read", None, q.request_reread(puzzle, clues, ["printedClue"]))
other = [(e, t + " x") for e, t in clues]
check("a re-read that changed the clues may ask again", True, bool(q.request_reread(puzzle, other, ["printedClue"])))
print(f"FAILS {fails}")
PY
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_scan_reread: failed"; exit 1; }
echo "test_scan_reread: all passed"
