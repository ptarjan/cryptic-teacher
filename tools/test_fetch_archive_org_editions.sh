#!/bin/bash
# Does tools/fetch_archive_org_editions.py retry a 5xx only within the
# edition's ITEM_SECONDS, then raise so the run moves on? Does an edition
# whose text shows no daily crossword title also fetch the leaves the paper
# prints it on? Offline: urlopen is stubbed.
#
#     bash tools/test_fetch_archive_org_editions.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$REPO/tools" <<'PY'
import contextlib, io, sys, tempfile, time, urllib.error
sys.path.insert(0, sys.argv[1])
import fetch_archive_org_editions as fa
fa.RETRY_WAITS = (0, 0, 0)
calls = []
def script(*steps):
    it = iter(steps); calls.clear()
    def urlopen(req, timeout):
        calls.append(req.full_url); s = next(it)
        if isinstance(s, Exception): raise s
        return contextlib.nullcontext(io.BytesIO(s))
    fa.urllib.request.urlopen = urlopen
def e500():
    return urllib.error.HTTPError("u", 500, "boom", {}, None)
fails = 0
def check(what, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + what, file=sys.stderr); fails += not ok
fx = fa.Fetcher(tempfile.mkdtemp(), 0)
with contextlib.redirect_stdout(io.StringIO()):
    script(e500(), e500(), b"fine")
    check("500s retried within the edition's time", fx.get("https://x/a", "a") == b"fine" and len(calls) == 3)
    fx.deadline = time.monotonic() - 1
    script(e500(), b"never")
    try: fx.get("https://x/b", "b"); code = None
    except urllib.error.HTTPError as e: code = e.code
    check("no retry past the edition's deadline", code == 500 and len(calls) == 1)
    script(urllib.error.URLError("refused"), b"never")
    try: fx.get("https://x/c", "c"); msg = ""
    except urllib.error.URLError as e: msg = str(e)
    check("network error past the deadline raises too", "refused" in msg and len(calls) == 1)

# Page selection: an edition whose text shows no daily crossword title also
# fetches its last leaf and the leaves its item's other editions print the
# crossword on; one whose text shows the title fetches only that page.
import json, os
item = tempfile.mkdtemp()
for name, leaves, leaf in (("1980-04-15_1", 28, 27), ("1980-04-17_3", 30, 29), ("1980-04-18_4", 28, 21)):
    os.makedirs(f"{item}/{name}")
    with open(f"{item}/{name}/pages.json", "w") as f:
        json.dump({"leaves": leaves, "crossword_pages": [
            {"leaf": leaf, "headings": ["Times Crossword Puzzle No 15,138"]},
            {"leaf": 5, "headings": ["CONCISE CROSSWORD NO 2157"]}]}, f)
os.makedirs(f"{item}/1980-04-16_2")
prior = fa.prior_leaves(f"{item}/1980-04-16_2", 28)
check("prior leaves: the last, and the siblings' crossword leaves front and back", prior == [21, 27])
check("a sibling's Concise page is no prior", 5 not in prior)
page = lambda t: (100, 200, t)
blank = [page("news " * 60)] * 28
hits = fa.crossword_hits(blank, prior)
check("no page detected: the prior leaves are fetched, marked prior",
      [h["leaf"] for h in hits] == [21, 27] and all(h["prior"] for h in hits))
concise = list(blank); concise[5] = page("CONCISE CROSSWORD NO 2157\nACROSS\n1 Dog (3)")
hits = fa.crossword_hits(concise, prior)
check("only a Concise page detected: the prior leaves are fetched beside it",
      [h["leaf"] for h in hits] == [5, 21, 27] and not hits[0].get("prior"))
sol = list(blank); sol[9] = page("Solution of Puzzle No 15,138 ACROSS DOWN" + " (5)" * 20)
check("only the solution heading detected: the prior leaves are fetched too",
      [h["leaf"] for h in fa.crossword_hits(sol, prior)] == [9, 21, 27])
cryptic = list(blank); cryptic[13] = page("Times Crossword Puzzle No 15,139\nACROSS\n1 Dog (3)")
check("the daily title detected: no prior leaves",
      [h["leaf"] for h in fa.crossword_hits(cryptic, prior)] == [13])
ad = list(blank); ad[27] = page("CROSSWORD ENTHUSIASTS: Times Crossword Book 12,000 copies ACROSS")
check("a crossword book advert is no title", [h["leaf"] for h in fa.crossword_hits(ad, prior)] == [21, 27])
sys.exit(1 if fails else 0)
PY
