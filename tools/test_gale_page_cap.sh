#!/bin/bash
# Is a Gale page laid out within gale_inbox.MAX_PAGE_PIXELS however small the
# grid it is scaled by (a crossword-centenary article's printed grid scaled
# the 2013-12-17 page to 363 MP), is a leaf staged before that cap shrunk to
# fit (its edition's input_hash moved, so its scan and read come due) and
# left alone the second time, and does a scan unit past its memory ceiling
# (edition_queue.UNIT_MEMORY_MB, RLIMIT_AS) end a failure naming it?
#
#     bash tools/test_gale_page_cap.sh
#
# Synthetic pages in a temp dir, a small cap: no OCR, nothing outside it.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import io, json, sys
from pathlib import Path
from PIL import Image
import file_archive_org_puzzles as fa
import gale_inbox as g

fails = 0
def check(what, want, got):
    global fails
    print(f"{'ok  ' if want == got else 'FAIL'} {what}" + ("" if want == got else f": want {want!r}, got {got!r}"))
    fails += want != got

g.MAX_PAGE_PIXELS = cap = 4_000_000
# A page whose "grid" is 100px wide would be scaled 7.2x, to 104 MP.
g.page_grids = lambda img: [[10, 10, 110, 110]]
page, found = g.scaled(Image.new("RGB", (1200, 1000), "white"))
check("a page scaled by a tiny grid is laid out within the cap", (True, True),
      (found, page.width * page.height <= cap))
check("and as near the cap as it may be", True, page.width * page.height > 0.9 * cap)
g.page_grids = lambda img: [[0, 0, 720, 720]]
same, _ = g.scaled(Image.new("RGB", (1000, 800), "white"))
check("a page within the cap at its grid's scale is not scaled", (fa.SCAN_WIDTH, 800 + 2 * g.MARGIN), same.size)

ed = Path(sys.argv[1]) / "GaleTimes2013UKEnglish" / "2013-12-17"
ed.mkdir(parents=True)
Image.new("RGB", (3000, 2000), "white").save(ed / "leaf_0000.jpg", quality=92)
(ed / "pages.json").write_text(json.dumps({"item": "GaleTimes2013UKEnglish", "crossword_pages": [
    {"leaf": 0, "width": 3000, "height": 2000, "file": "GALE_X.pdf"}]}))
small = ed.parent / "2013-12-16"
small.mkdir()
Image.new("RGB", (1000, 800), "white").save(small / "leaf_0000.jpg")
(small / "pages.json").write_text(json.dumps({"crossword_pages": [{"leaf": 0, "width": 1000, "height": 800}]}))
before = (ed / "leaf_0000.jpg").stat().st_size
got = g.shrink_oversized(Path(sys.argv[1]), out=io.StringIO())
leaf = Image.open(ed / "leaf_0000.jpg")
p = json.loads((ed / "pages.json").read_text())["crossword_pages"][0]
check("an oversized staged leaf is shrunk to the cap, pages.json with it, the small one left",
      ([ed], True, (leaf.width, leaf.height)), (got, leaf.width * leaf.height <= cap, (p["width"], p["height"])))
check("its leaf's size moved (input_hash keys an edition by its files' names and sizes), so it comes due",
      (True, ["leaf_0000.jpg", "pages.json"]), (before != (ed / "leaf_0000.jpg").stat().st_size, sorted(f.name for f in ed.iterdir())))
check("a second pass shrinks nothing", [], g.shrink_oversized(Path(sys.argv[1]), out=io.StringIO()))
print("FAILS", fails)
sys.exit(1 if fails else 0)
PY
# A unit past its ceiling: a MemoryError, logged naming the ceiling, rc 1.
out=$(CT_UNIT_MEMORY_MB=1024 python3 - <<'PY' 2>&1
import sys
import edition_queue as eq
eq.cap_memory()
rc = eq.unit_status({"kind": "scan", "paper": "gale", "rel": "GaleTimes2013UKEnglish/2013-12-17"},
                    lambda: len(bytearray(3 << 30)))
print("rc", rc)
PY
) || true
if grep -q "hit its memory ceiling (1024 MB" <<<"$out" && grep -q "^rc 1$" <<<"$out"; then
  echo "ok   a unit past its memory ceiling ends a failure naming it"
else
  echo "FAIL a unit past its memory ceiling ends a failure naming it:"; echo "$out" | tail -5; exit 1
fi
