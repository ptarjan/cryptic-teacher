#!/usr/bin/env python3
# Does tools/file_archive_org_puzzles.py take the grid under a 1939-67 Times
# title that locate_grid passed over as a solution grid on a page wider than
# SCAN_WIDTH (scaled_under), and make the pages refused so due once
# (SCALED_UNDER_ERAS, scaled_due: pages wider than SCAN_WIDTH only)?
#
#     python3 tests/test_scaled_under.py
#
# Made-up pages drawn with PIL, nothing read off a scan.
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
os.chdir(TOOLS)
sys.path.insert(0, str(TOOLS))
from PIL import Image, ImageDraw
import file_archive_org_puzzles as f

fails = 0


def check(what, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": want {want!r}, got {got!r}"))


def page(width, side, frame=True):
    """A `width` px page: a title bar, a 15x15 grid `side` px wide 8px under it, and with
    `frame` a framed advert over the title, grid-shaped (the 1961-04-25 Times)."""
    img = Image.new("L", (width, 4500), 255)
    d = ImageDraw.Draw(img)
    title = (282, 1905, 1140, 1966)
    d.rectangle(title, fill=0)
    x0, y0 = 502, 1974
    pitch = side / 15
    for k in range(16):
        d.rectangle((x0 + k * pitch - 2, y0, x0 + k * pitch + 2, y0 + side), fill=0)
        d.rectangle((x0, y0 + k * pitch - 2, x0 + side, y0 + k * pitch + 2), fill=0)
    for r, c in ((1, 1), (3, 5), (7, 7), (11, 9), (13, 13)):
        d.rectangle((x0 + c * pitch, y0 + r * pitch, x0 + (c + 1) * pitch, y0 + (r + 1) * pitch), fill=0)
    if frame:
        d.rectangle((198, 758, 1226, 1902), outline=0, width=10)
    return img, title, (x0, y0, x0 + side, y0 + side)


def near(a, b, tol=6):
    return a is not None and b is not None and all(abs(p - q) <= tol for p, q in zip(a, b))


img, title, grid = page(4050, 700)
check("a 700px grid on a 4050px page measures as a solution grid", True, f.solution_shaped(img)(grid))
box, side = f.locate_grid(img, title)
check("so locate_grid takes the frame over the title", "above", side)
check("scaled_under takes the grid under the title", True, near(f.scaled_under(img, title), grid))

img, title, grid = page(4050, 700, frame=False)
check("no frame over it: scaled_under still finds the grid", True, near(f.scaled_under(img, title), grid))

img, title, grid = page(f.SCAN_WIDTH, 720)
check("a SCAN_WIDTH page's 720px grid is no solution grid: locate_grid finds it", "below", f.locate_grid(img, title)[1])
check("and scaled_under leaves it to locate_grid", None, f.scaled_under(img, title))

img, title, grid = page(4050, 560)
check("a grid a solution's size unscaled (455 at SCAN_WIDTH) is not taken", None, f.scaled_under(img, title))

blank = Image.new("L", (4050, 4500), 255)
ImageDraw.Draw(blank).rectangle((282, 1905, 1140, 1966), fill=0)
check("no ink under the title: None", None, f.scaled_under(blank, (282, 1905, 1140, 1966)))

check("SCALED_UNDER_YEARS are the 1939-67 pages", ("1939", "1967"), f.SCALED_UNDER_YEARS)

import json
import tempfile

cache = Path(tempfile.mkdtemp())
f.CACHE = cache


def laid(edition, width):
    d = cache / edition
    d.mkdir(parents=True, exist_ok=True)
    (d / "pages.json").write_text(json.dumps({"crossword_pages": [{"leaf": 0, "width": width, "height": 5000}]}))


_61 = {"edition": "GaleTimes1961UKEnglish/1961-04-25", "scan": {"item": "GaleTimes1961UKEnglish", "date": "1961-04-25"},
       "readAt": "2026-10-27T10:00:00+00:00",
       "verdicts": [{"number": 9662, "refused": "no reading parses", "cause": "no-reading-parses"}]}
laid(_61["edition"], 4031)
check("a 4031px 1961 page refused no reading parses before the fix is due again", True, f.scaled_due(_61))
check("its reason", "refused no-reading-parses before its fix", f.fix_reason(_61))
check("not once read since", None, f.fix_reason({**_61, "readAt": "2026-10-29T00:00:00+00:00"}))
check("nor a 1968 page", False, f.scaled_due({**_61, "scan": {"item": "GaleTimes1968UKEnglish", "date": "1968-04-25"}}))
_50 = {**_61, "edition": "GaleTimes1950UKEnglish/1950-04-25", "scan": {"item": "GaleTimes1950UKEnglish", "date": "1950-04-25"}}
laid(_50["edition"], 5108)
check("nor a 1942-54 page", False, f.scaled_due(_50))
_39 = {"edition": "GaleTimes1939UKEnglish/1939-12-20", "scan": {"item": "GaleTimes1939UKEnglish", "date": "1939-12-20"},
       "readAt": "2026-10-27T10:00:00+00:00",
       "verdicts": [{"number": 3068, "refused": "the ink under the title is 466x60, not a grid", "cause": "not-a-grid"}]}
laid(_39["edition"], 5150)
check("a 5150px 1939 page refused not a grid for the ink under its title is due again", "refused not-a-grid before its fix",
      f.fix_reason(_39))
check("not once read since", None, f.fix_reason({**_39, "readAt": "2026-10-29T00:00:00+00:00"}))
_40 = {**_39, "edition": "GaleTimes1940UKEnglish/1940-01-24", "scan": {"item": "GaleTimes1940UKEnglish", "date": "1940-01-24"}}
laid(_40["edition"], f.SCAN_WIDTH)
check("nor a 1940 page SCAN_WIDTH wide: its cap is unscaled", None, f.fix_reason(_40))
check("the reasons are ranked", (2, 2), (f.RANKS.get("refused not-a-grid before its fix"),
                                         f.RANKS.get("refused no-reading-parses before its fix")))

sys.exit(1 if fails else 0)
