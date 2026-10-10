#!/bin/bash
# Does a read unit the edition queue prepared (tools/edition_commit.py)
# write what the desktop decided and append the edition's row, loading no
# tree module past its MODULES as it commits; hand a title the desktop left
# undecided, a desktop gone LONG_GONE, or an edition read since it was
# prepared to the whole unit; retry a desktop lost mid-read and end deferred; and is ocr_remote's code hash kept only for the commit it
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

real_session = ocr_remote.session
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
    ocr_remote.session = lambda final=True: desk
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

# A desktop lost mid-read (its session reset): opened again and the read
# made there, BACKOFF apart; its tries spent, the unit ends deferred, and
# reads here only once the desktop has answered no one for LONG_GONE.
import time
ocr_remote.session = real_session
ocr_remote.desktop_busy.busy = lambda hosts: None
ocr_remote.SEEN = tmp / "seen"
naps = []
ocr_remote.time.sleep = naps.append
class Dropping(Desktop):
    host = "nohost"
    tries = 0
    def __init__(self, answer, drops):
        super().__init__(answer)
        self.drops = drops
    def edition(self, head, tar):
        Dropping.tries += 1
        if Dropping.tries <= self.drops:
            raise ocr_remote.Unavailable("ssh exited (255): Connection to nohost closed by remote host.")
        return super().edition(head, tar)
    def close(self):
        pass

def lost_run(drops, defer, seen_ago, off=False):
    Dropping.tries = 0
    naps.clear()
    execs.clear()
    ocr_remote.connect = lambda: None if off else Dropping({"results": [], "vlm": True, "decided": []}, drops)
    ocr_remote._state().update(pid=os.getpid(), session=None, retry=0.0)
    ocr_remote.SEEN.touch()
    os.utime(ocr_remote.SEEN, (time.time() - seen_ago,) * 2)
    os.environ.pop(ocr_remote.DEFER, None)
    if defer:
        os.environ[ocr_remote.DEFER] = "1"
    path = tmp / "z.brief"
    ec.save_brief(path, {"edition": ctx["rel"]}, b"tar", {**ctx, "ledgerSize": ledger.stat().st_size})
    try:
        rc = ec.main({"unit": {"kind": "read", "paper": "times", "rel": ctx["rel"]}, "brief": str(path)})
    except Became:
        rc = "whole"
    except ocr_remote.DesktopLost:
        rc = "deferred"
    return rc, Dropping.tries, list(naps)

check("lost twice mid-read, then answering: the read is made there, no whole unit",
      (0, 3, [10, 30], []), (*lost_run(2, True, 0), execs))
check("lost on every try in a deferring unit: it ends deferred, BACKOFF apart, nothing read here",
      ("deferred", 4, [10, 30, 90], []), (*lost_run(99, True, 0), execs))
check("a desktop off, but answering within LONG_GONE: deferred after BACKOFF, nothing read here",
      ("deferred", 0, [10, 30, 90], []), (*lost_run(0, True, 60, off=True), execs))
check("a desktop off past LONG_GONE: the whole unit reads here",
      ("whole", [10, 30, 90], ("the desktop is not reading", ["OCR_REMOTE"])),
      (*lost_run(0, True, ocr_remote.LONG_GONE + 60, off=True)[::2], execs[-1]))
check("a session that opens is the desktop answering: lost on every read, it still defers",
      ("deferred", 4), lost_run(99, True, ocr_remote.LONG_GONE + 60)[:2])
check("lost on every try in a process that does not defer: read here, the desktop held off RETRY",
      ("whole", 4, True), (*lost_run(99, False, 0)[:2], ocr_remote._state()["retry"] > time.monotonic() + 500))
check("an answer from the desktop marks it seen", True,
      (lost_run(0, True, 3600)[0], time.time() - ocr_remote.SEEN.stat().st_mtime < 60)[1])
os.environ.pop(ocr_remote.DEFER, None)
check("LAN hosts are tried before tailnet ones", ["micro@192.168.1.198", "box", "micro@100.68.145.15"],
      ocr_remote.by_path(["micro@100.68.145.15", "micro@192.168.1.198", "box"]))

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
