#!/bin/bash
# Does tools/vlm_reader.py stay out of the way when the desktop's VLM does
# not answer, cache what it asks, crop each clue column alone, and does
# file_archive_org_puzzles.py fill a blank clue with its reading and re-read
# an edition once it answers?
#
#     bash tools/test_vlm_reader.sh
#
# The VLM is mocked: no network, no scan, nothing written outside a temp dir.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" python3 - <<'EOF'
import io, json, os
from pathlib import Path
import vlm_reader as vlm
import file_archive_org_puzzles as f

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

T = Path(os.environ["TMP"])
vlm.CACHE = T / "vlm"

# Nothing listening: not reachable, and asked once.
vlm.URL = ""
check("an empty URL turns it off", False, vlm.reachable())
vlm.URL = "http://127.0.0.1:9"
vlm._UP.clear()
check("a server that does not answer is not reachable", False, vlm.reachable())

# A server that lists another model is not reachable either.
import urllib.request
real = urllib.request.urlopen
calls = []
def fake(req, timeout=None):
    calls.append(req.full_url)
    if req.full_url.endswith("/v1/models"):
        return io.BytesIO(json.dumps({"data": [{"id": "glimmer-30b"}]}).encode())
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ACROSS\n1 Clue (5)"}}]}).encode())
urllib.request.urlopen = fake
vlm._UP.clear()
check("a server without the model is not reachable", False, vlm.reachable())
vlm._UP.clear()
vlm.MODEL = "glimmer-30b"
check("a server listing the model is reachable", True, vlm.reachable())

from PIL import Image
img = Image.new("L", (400, 300), 255)
calls.clear()
check("ask returns the reply", "ACROSS\n1 Clue (5)", vlm.ask(img, "read it"))
check("a second ask of the same image is the cache's", ("ACROSS\n1 Clue (5)", 1),
      (vlm.ask(img, "read it"), len(calls)))
urllib.request.urlopen = real

# Each column cropped to its own lines, not the window's shared right edge.
wins = [(10, 200, 390, 0), (200, 390, 390, 0)]
readings = [[[(20, 40, 15, 180, "1 Left clue (5)")], [(30, 60, 210, 380, "2 Right (4)")]]]
check("crop boxes span each column's lines, padded",
      [(5, 10, 190, 50), (200, 20, 390, 70)], vlm.boxes(img, wins, readings))

# The pick fills a blank with the reply's words, its count cut off; a reply
# of no words, or none, leaves it blank.
texts = {"ch": "ACROSS\n1 Stop thief (4)\nDOWN\n2 Kettle (3)", "en5": "ACROSS\n1 Stop chief (4)\nDOWN\n2 Kettle (3)"}
laid = {"1-across": ("", "4", None)}
shown = []
for reply, want in (("Stop thief (4)", "Stop thief"), ("(4)", ""), (None, "")):
    def fake_pick(img, wins, readings, lid, cands, r=reply):
        shown.append(cands)
        return r
    vlm.pick = fake_pick
    got, blank = f.vlm_pick(img, wins, readings, texts, laid, {"1-across": "readings differ"})
    check(f"pick of {reply!r}", (want, not want), (got["1-across"][0], "1-across" in blank))
check("the pick is shown every reading's text for the light", ["Stop thief (4)", "Stop chief (4)"], shown[0])

# run(): an edition read without the VLM is read again once it answers;
# one read with it is not read again while it is down.
ed = T / "cache" / "NewsUK1990UKEnglish" / "1990-01-01_1"
ed.mkdir(parents=True)
(ed / "pages.json").write_text("{}")
reads = []
saved = (f.scan, f.read_puzzle, vlm.reachable, vlm.version)
f.scan = lambda d: {"date": "1990-01-01", "item": "NewsUK1990UKEnglish", "solutions": [],
                    "puzzles": [{"number": 18180, "leaf": 1, "box": None}]}
f.read_puzzle = lambda d, found, hit, sol: (reads.append(vlm.reachable()), ({"number": 18180}, None))[1]
vlm.version = lambda: "v1"
ledger = T / "ledger.jsonl"
def go(up):
    vlm.reachable = lambda: up
    f.run(cache=T / "cache", ledger=ledger, source=T / "src", out=open(os.devnull, "w"))
go(False); go(False)
check("without the VLM an edition is read once", [False], reads)
go(True); go(True)
check("the VLM answering reads it again, once", [False, True], reads)
go(False)
check("the VLM down again leaves its reading standing", [False, True], reads)
vlm.version = lambda: "v2"
go(True)
check("a new VLM model alone reads nothing again (--reread does)", [False, True], reads)
# The VLM gone during an edition: that edition is filed as read without it.
state = {"up": True}
def dies(d, found, hit, sol):
    reads.append("dies")
    state["up"] = False
    return {"number": 18180}, None
f.read_puzzle = dies
vlm.reachable = lambda: state["up"]
import scan_queue
f.run(cache=T / "cache", ledger=ledger, source=T / "src", out=open(os.devnull, "w"),
      reread=scan_queue.when("now"))
row = json.loads(ledger.read_text().splitlines()[-1])
check("an edition the VLM died during is filed as read without it", ("dies", None),
      (reads[-1], row.get("vlm")))
f.read_puzzle = lambda d, found, hit, sol: (reads.append(vlm.reachable()), ({"number": 18180}, None))[1]
go(True)
check("so it is read again once the VLM answers", True, reads[-1])
f.scan, f.read_puzzle, vlm.reachable, vlm.version = saved

print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_vlm_reader: failed"; exit 1; }
echo "test_vlm_reader: all passed"
