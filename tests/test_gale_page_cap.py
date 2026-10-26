#!/usr/bin/env python3
# Is a Gale page laid out within gale_inbox.MAX_PAGE_PIXELS however small the
# grid it is scaled by (a crossword-centenary article's printed grid scaled
# the 2013-12-17 page to 363 MP), is a leaf staged before that cap shrunk to
# fit (its edition's input_hash moved, so its scan and read come due) and
# left alone the second time, and does a scan unit past its memory ceiling
# (edition_queue.UNIT_MEMORY_MB, RLIMIT_AS) end a failure naming it?
#
#     python3 tests/test_gale_page_cap.py
#
# Synthetic pages in a temp dir, a small cap: no OCR, nothing outside it.
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
os.chdir(TOOLS)
sys.path.insert(0, str(TOOLS))

tmp = Path(tempfile.mkdtemp())
try:
    # gale_inbox records each staged edition to the SSD manifests: a fresh one
    # here (CI has none), never the household's own.
    os.environ["CT_MANIFEST"] = str(tmp / ".manifest")
    (tmp / ".manifest").mkdir()
    (tmp / ".manifest" / "gale-editions.jsonl").write_text("")

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

    ed = tmp / "GaleTimes2013UKEnglish" / "2013-12-17"
    ed.mkdir(parents=True)
    Image.new("RGB", (3000, 2000), "white").save(ed / "leaf_0000.jpg", quality=92)
    (ed / "pages.json").write_text(json.dumps({"item": "GaleTimes2013UKEnglish", "crossword_pages": [
        {"leaf": 0, "width": 3000, "height": 2000, "file": "GALE_X.pdf"}]}))
    small = ed.parent / "2013-12-16"
    small.mkdir()
    Image.new("RGB", (1000, 800), "white").save(small / "leaf_0000.jpg")
    (small / "pages.json").write_text(json.dumps({"crossword_pages": [{"leaf": 0, "width": 1000, "height": 800}]}))
    before = (ed / "leaf_0000.jpg").stat().st_size
    got = g.shrink_oversized(tmp, out=io.StringIO())
    leaf = Image.open(ed / "leaf_0000.jpg")
    p = json.loads((ed / "pages.json").read_text())["crossword_pages"][0]
    check("an oversized staged leaf is shrunk to the cap, pages.json with it, the small one left",
          ([ed], True, (leaf.width, leaf.height)), (got, leaf.width * leaf.height <= cap, (p["width"], p["height"])))
    check("its leaf's size moved (input_hash keys an edition by its files' names and sizes), so it comes due",
          (True, ["leaf_0000.jpg", "pages.json"]), (before != (ed / "leaf_0000.jpg").stat().st_size, sorted(f.name for f in ed.iterdir())))
    check("a second pass shrinks nothing", [], g.shrink_oversized(tmp, out=io.StringIO()))
    print("FAILS", fails)
    if fails:
        sys.exit(1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# A unit past its ceiling: a MemoryError, logged naming the ceiling, rc 1.
CHILD = """
import edition_queue as eq
eq.cap_memory()
rc = eq.unit_status({"kind": "scan", "paper": "gale", "rel": "GaleTimes2013UKEnglish/2013-12-17"},
                    lambda: len(bytearray(3 << 30)))
print("rc", rc)
"""
r = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True,
                   env={**os.environ, "CT_UNIT_MEMORY_MB": "1024", "PYTHONPATH": str(TOOLS)})
out = r.stdout + r.stderr
if "hit its memory ceiling (1024 MB" in out and "rc 1" in out.splitlines():
    print("ok   a unit past its memory ceiling ends a failure naming it")
else:
    print("FAIL a unit past its memory ceiling ends a failure naming it:")
    print("\n".join(out.splitlines()[-5:]))
    sys.exit(1)
