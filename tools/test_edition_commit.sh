#!/bin/bash
# Does a read unit the edition queue prepared (tools/edition_commit.py)
# write what the desktop decided and append the edition's row, loading no
# tree module past its MODULES as it commits; hand a title the desktop left
# undecided, the desktop lost, or an edition read since it was prepared to
# the whole unit; and is ocr_remote's code hash kept only for the commit it
# was made from?
#
#     bash tools/test_edition_commit.sh
#
# No ssh, no OCR: temp dirs only.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cd "$REPO/tools" && TMP="$tmp" OCR_REMOTE=nohost python3 - <<'PY'
import copy, json, os, sys
from pathlib import Path
import edition_commit as ec
ec.load()
loaded = set(sys.modules)
import fetch_puzzle, ocr_remote, scan_queue, vlm_reader

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

tmp = Path(os.environ["TMP"])
corpus = tmp / "corpus"
corpus.mkdir()
fetch_puzzle.puzzle_path = lambda series, n: corpus / f"times-{n}.json"
held = json.loads((Path("..") / "puzzles/times/1990/times-18184.json").read_text())
ledger = tmp / "filed.jsonl"
ledger.write_text(json.dumps({"edition": "other/1"}) + "\n")
found = {"puzzles": [{"number": 18184, "leaf": 3}], "solutions": []}
ctx = {"rel": "Item/1990-01-06", "ledger": str(ledger), "ledgerSize": ledger.stat().st_size, "series": "times",
       "puzzles": None, "source": str(tmp / "src"), "crops": str(tmp / "crops"), "found": found,
       "filesHash": "fh", "solutionsSeen": [], "scanKey": "sk", "vlmVersion": "v1", "reprints": ""}

class Desktop:
    def __init__(self, answer):
        self.answer, self.sent = answer, None
    def edition(self, head, tar):
        self.sent = head
        import io, tarfile
        buf = io.BytesIO()
        tarfile.open(fileobj=buf, mode="w").close()
        return self.answer, buf.getvalue()

execs = []
class Became(Exception):
    pass
def whole_unit(spec, why, env=None):
    execs.append((why, sorted(env or {})))
    raise Became
ec.whole_unit = whole_unit
vlm_reader.reachable = lambda: True

def run(answer, size=None):
    path = tmp / "x.brief"
    ec.save_brief(path, {"edition": ctx["rel"]}, b"tar", {**ctx, "ledgerSize": size or ledger.stat().st_size})
    desk = Desktop(answer)
    ocr_remote.session = lambda: desk
    execs.clear()
    try:
        rc = ec.main({"unit": {"kind": "read", "paper": "times", "rel": ctx["rel"]}, "brief": str(path)})
    except Became:
        rc = "whole"
    return rc, desk, path.exists()

decided = [[{"number": 18184, "id": "times-18184"}, [[None, held], [["held", 18184], held]]]]
rc, desk, left = run({"results": [], "vlm": True, "decided": decided})
row = json.loads(ledger.read_text().splitlines()[-1])
check("the desktop's writes are made and the brief removed", (0, True, True, False),
      (rc, (corpus / "times-18184.json").exists(), (tmp / "src" / "times-18184.json").exists(), left))
check("the row is the read's, with the VLM it was read with",
      {"edition": ctx["rel"], "inputs": "fh", "scan": found, "filesHash": "fh", "scanKey": "sk",
       "solutionsSeen": [], "verdicts": [{"number": 18184, "id": "times-18184", "wrote": True}], "vlm": "v1"},
      {k: v for k, v in row.items() if k != "readAt"})
check("this process's VLM answer goes in the request", True, desk.sent["vlm"])
tools = Path(".").resolve()
late = sorted(m for m in set(sys.modules) - loaded
              if Path(getattr(sys.modules[m], "__file__", None) or "/").resolve().parent == tools)
check("a commit loads no tree module past MODULES (they load under the code lock)", [], late)
import ocr_clues
check("nor the clue LM, for clues with no word printed twice (~3s a unit)", None, ocr_clues._LM)
check("a doubled word still asks it", ([("composer", "a word doubled")], True),
      (ocr_clues.stray("Plan composer composer here (5)"), ocr_clues._LM is not None))

rc, _, _ = run({"results": [[{"number": 18184}, held]], "vlm": False, "decided": None})
check("a title the desktop could not decide goes to the whole unit, the answer passed",
      ("whole", ["CT_EDITION_ANSWER"]), (rc, execs[0][1]))
answer = json.loads(Path(tmp / "x.brief.answer").read_text())
check("the answer passed is the desktop's readings", (ctx["rel"], [[{"number": 18184}, held]]),
      (answer["edition"], answer["results"]))
os.environ["CT_EDITION_ANSWER"] = str(tmp / "x.brief.answer")
ed = tmp / "Item" / "1990-01-06"
check("the whole unit takes that answer as read there, once", (([({"number": 18184}, held)], False, None), False),
      (ocr_remote.edition(ed, found, {}), (tmp / "x.brief.answer").exists()))

def lost(head, tar):
    raise ocr_remote.Unavailable("gone")
ocr_remote.lost = lambda e: None
desk_lost = Desktop(None)
desk_lost.edition = lost
ec.save_brief(tmp / "y.brief", {}, b"", {**ctx, "ledgerSize": ledger.stat().st_size})
ocr_remote.session = lambda: desk_lost
try:
    ec.main({"unit": {"rel": ctx["rel"]}, "brief": str(tmp / "y.brief")})
except Became:
    pass
check("a desktop lost mid-read: the whole unit reads here", ("the desktop was lost", ["OCR_REMOTE"]), execs[-1])

size = ledger.stat().st_size
scan_queue.append(ledger, [{"edition": ctx["rel"], "inputs": "x"}])
rc, _, _ = run({"results": [], "vlm": True, "decided": []}, size=size)
check("an edition read since it was prepared goes to the whole unit",
      ("whole", "its ledger row moved since it was prepared"), (rc, execs[0][0]))
check("rows of other editions since do not", False, ec.read_since(ledger, ledger.stat().st_size, ctx["rel"]))
check("a ledger that shrank (compacted) does", True, ec.read_since(ledger, size + 10**6, ctx["rel"]))

# ocr_remote.kept: made once per key, kept nowhere without one, and not kept
# when the key moved while it was made (the tree moved mid-hash).
ocr_remote.KEPT = tmp / "kept"
calls = []
def compute():
    calls.append(1)
    return len(calls)
check("kept: made once for a key", (1, 1), (ocr_remote.kept("t", lambda: "k1", compute),
                                             ocr_remote.kept("t", lambda: "k1", compute)))
check("kept: made afresh without a key", (2, 3), (ocr_remote.kept("t", lambda: None, compute),
                                                  ocr_remote.kept("t", lambda: None, compute)))
keys = iter(["k2", "k3"])
ocr_remote.kept("t", lambda: next(keys), compute)
check("kept: nothing kept when the key moved meanwhile", False, (ocr_remote.KEPT / "t-k2.json").exists())
sys.exit(1 if fails else 0)
PY
