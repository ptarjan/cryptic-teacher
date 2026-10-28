#!/usr/bin/env python3
# Does tools/file_archive_org_puzzles.py find a grid whose heavy ink runs up
# into its title (touching_grid), which locate_grid refuses as "not a grid",
# and make such refused Times pages due once (touching_refused)?
#
#     python3 tests/test_touching_grid.py
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


def page(tall=False, gap=0):
    """A SCAN_WIDTH page: a solid title bar, a heavy 15x15 grid under it
    (`gap` pixels below the title's foot), with `tall` a solution grid fused
    under it."""
    img = Image.new("L", (f.SCAN_WIDTH, 2400), 255)
    d = ImageDraw.Draw(img)
    title = (300, 200, 900, 260)
    d.rectangle(title, fill=0)
    x0, y0, side = 250, 260 + gap, 690
    pitch = side / 15
    for k in range(16):
        w = 7
        d.rectangle((x0 + k * pitch - w // 2, y0, x0 + k * pitch + w // 2, y0 + side), fill=0)
        d.rectangle((x0, y0 + k * pitch - w // 2, x0 + side, y0 + k * pitch + w // 2), fill=0)
    for r, c in ((1, 1), (3, 5), (7, 7), (11, 9), (13, 13)):
        d.rectangle((x0 + c * pitch, y0 + r * pitch, x0 + (c + 1) * pitch, y0 + (r + 1) * pitch), fill=0)
    if tall:
        # A solution grid's frame fused to the grid's foot by a rule.
        d.rectangle((x0 + 300, y0 + side, x0 + 310, y0 + side + 60), fill=0)
        d.rectangle((x0 + 300, y0 + side + 60, x0 + 650, y0 + side + 410), outline=0, width=8)
    return img, title


img, title = page()
box, side = f.locate_grid(img, title)
check("a heavy grid whose ink runs into its title: locate_grid finds no side", None, side)
got = f.touching_grid(img, title, box)
check("touching_grid takes it, starting at the title's foot", True, got is not None and abs(got[1] - title[3]) <= f.TOUCH_GAP)
check("and it is grid-shaped", True, got is not None and f.shaped_on(img, got))

img, title = page(tall=True)
box, _ = f.locate_grid(img, title)
got = f.touching_grid(img, title, box)
check("a grid fused to a solution grid under it: its top square",
      True, got is not None and abs((got[3] - got[1]) - (got[2] - got[0])) <= 2 and got[1] <= title[3] + f.TOUCH_GAP)

blank = Image.new("L", (f.SCAN_WIDTH, 2400), 255)
ImageDraw.Draw(blank).rectangle((300, 200, 900, 260), fill=0)
ImageDraw.Draw(blank).rectangle((1500, 900, 1600, 1000), fill=0)
check("no grid under the title: None", None, f.touching_grid(blank, (300, 200, 900, 260), (1500, 900, 1600, 1000)))
check("a grid far under the title is not one touching it", None,
      f.touching_grid(img, title, (title[0], title[3] + 200, title[0] + 690, title[3] + 890)))
check("no ink box: None", None, f.touching_grid(img, title, None))

f.filed_state = lambda series, number: None
row = {"edition": "GaleTimes1982UKEnglish/1982-07-06", "readAt": "2026-10-20T00:00:00+00:00",
       "verdicts": [{"number": 15874, "cause": "not-a-grid", "refused": "the ink under the title is 718x714, not a grid"}]}
check("an unheld 1982 Times page refused for the ink under its title is due", True, f.touching_refused(row))
check("its reason", f.TOUCHING_GRID, f.fix_reason(row))
check("read since the fix: not due", False, f.touching_refused({**row, "readAt": "2026-10-29T00:00:00+00:00"}))
check("outside TOUCHING_YEARS: not due", False,
      f.touching_refused({**row, "edition": "GaleTimes1940UKEnglish/1940-05-18"}))
check("another paper: not due", False,
      f.touching_refused({**row, "edition": "FinancialTimes1986UKEnglish/1986-02-05_29847"}))
check("another refusal: not due", False, f.touching_refused(
    {**row, "verdicts": [{"number": 15874, "cause": "no-reading-parses", "refused": "no reading parses"}]}))
f.filed_state = lambda series, number: (False, True)
check("a held puzzle: not due", False, f.touching_refused(row))
check("the reason is ranked", 2, f.RANKS.get(f.TOUCHING_GRID))

sys.exit(1 if fails else 0)
