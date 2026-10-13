#!/bin/bash
# Is a social card redrawn only when what it shows could change?
#
#     bash tools/test_og_card_key.sh
#
# The card key used to salt in make_og_card.py's own bytes, so a read-path
# refactor (2026-10-13) called all ~17k cards stale and the deploy's card step
# went from about a minute to its 900s budget for the next ~30 runs, drawing
# identical pictures 600 at a time. The key is now a hash of the exact HTML
# Chrome screenshots. This checks, on one real puzzle and without Chrome:
#   - the key is that hash, and record() of the page drawn leaves it not stale
#   - an edit to make_og_card.py that moves no picture (a comment) keeps the key
#   - the site card's region of og_card.html, rewritten every deploy, keeps it
#   - a change to the clue, or to the template outside that region, moves it
#   - a card the old scheme drew is adopted once, not redrawn
#   - make_og.sh's batch flags (--out-dir, --record PID HTML...) round-trip
#   - og_list.py's cached rows are not keyed on every tools/data file, which
#     annotate commits touch many times a day (that re-listed all ~17k, ~45s)
set -uo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(TMPD="$tmp" PYTHONPATH=tools python3 - <<'PY' 2>&1
import importlib.util, json, os, shutil, sys
from pathlib import Path
import make_og_card as m
import puzzle_paths

tmp = Path(os.environ["TMPD"])
fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += 0 if ok else 1

# One real puzzle that gets a card, found without reading the whole corpus.
pid = next(f.stem for f in sorted(puzzle_paths.puzzle_files())[:3000] if m.pick(f.stem)[0])
key = m.card_key(pid)
check("the key is the hash of the page Chrome is handed",
      key == m.html_key(m.card_html(pid)) and key.startswith(m.KEY_PREFIX))

# The same script with a comment added, imported as a module of its own.
copy = tmp / "make_og_card_copy.py"
copy.write_text(Path(m.__file__).read_text(encoding="utf-8") + "\n# a comment moves no picture\n",
                encoding="utf-8")
spec = importlib.util.spec_from_file_location("make_og_card_copy", copy)
m2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2)
m2.REPO, m2.CARD = m.REPO, m.CARD
check("an edit to make_og_card.py that moves no picture keeps every key", m2.card_key(pid) == key)

# The site card's region of the template is whatever card was drawn last.
real_card = m.CARD
text = real_card.read_text(encoding="utf-8")
moved = tmp / "region.html"
moved.write_text(m.CARD_REGION.sub("<!--CARD-START--><p>another site card</p><!--CARD-END-->", text),
                 encoding="utf-8")
m.CARD = moved
check("redrawing the site card keeps every puzzle card's key", m.card_key(pid) == key)
styled = tmp / "styled.html"
styled.write_text(text.replace("</style>", "body{margin:1px}</style>", 1), encoding="utf-8")
m.CARD = styled
check("a template change outside the card region moves the key", m.card_key(pid) != key)
m.CARD = real_card

real_load = m.load
def reworded(p):
    puz = real_load(p)
    for e in puz["entries"]:
        e["clue"] = dict(e["clue"], text=e["clue"].get("text", "") + " Indeed")
    return puz
m.load = reworded
check("a reworded clue moves the key", m.card_key(pid) != key)
m.load = real_load

# A sandbox repo for the manifest: og/<pid>.png and og/.manifest.json.
m.REPO, m.MANIFEST = tmp, tmp / "og" / ".manifest.json"
(tmp / "og").mkdir()
m.eligible = lambda: [pid]
check("a card with no png is stale", list(m.stale()) == [pid])
(tmp / "og" / f"{pid}.png").write_bytes(b"png")
sys.argv = ["make_og_card.py", "--out-dir", str(tmp), pid]
m.main()
sys.argv = ["make_og_card.py", "--record", pid, str(tmp / f"{pid}.html")]
m.main()
check("--out-dir then --record leaves the card drawn", list(m.stale()) == [])
check("the manifest holds the html key",
      json.loads(m.MANIFEST.read_text())[pid] == key)

m.MANIFEST.write_text(json.dumps({pid: "0" * 64}))
check("an old-scheme entry with its png is adopted", m.adopt_legacy() == 1)
check("and is then not stale", list(m.stale()) == [])
m.MANIFEST.write_text(json.dumps({pid: "0" * 64}))
(tmp / "og" / f"{pid}.png").unlink()
check("an old-scheme entry with no png is not adopted", m.adopt_legacy() == 0)
check("and is drawn", list(m.stale()) == [pid])

# The list's rows: keyed on what a card reads, not on every tools/data file,
# which annotate commits touch many times a day.
import og_list, row_cache
salts = []
def fake_map(name, fn, paths, roots=(), salt="", deps=None, prepare=None):
    salts.append((fn.__name__, salt))
    return [False] * len(list(paths))
row_cache.cached_map = fake_map
m.blog_card_ids = lambda: []
m.prune = lambda: None
m.adopt_legacy = lambda: 0
og_list.main(["0"])
card_salt = dict(salts).get("card_row")
check("the card rows' salt is the template and tables, nothing more",
      card_salt == m._salt().hexdigest())
data = {p.name for p in row_cache.data_files("og_list", {"card_row"})}
check("a sidecar no card reads keys no row (setter_error.json, blog_disagree.json)",
      not data & {"setter_error.json", "blog_disagree.json", "deploy_budgets.json"})
sys.exit(1 if fails else 0)
PY
)
rc=$?
echo "$out"
if [ $rc -ne 0 ]; then echo "test_og_card_key: FAILED"; exit 1; fi
echo "test_og_card_key: all passed"
