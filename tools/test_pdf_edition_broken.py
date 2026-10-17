#!/usr/bin/env python3
# Does tools/fetch_archive_org_editions.py read the pages of an image PDF that
# archive.org holds zero-filled past some page (FT 1981-06-29/30), listing
# the broken ones in "unreadable" instead of raising; and does fetch_pdf fetch
# a PDF whose md5 is not the metadata's once more, keep a second copy equal
# to the first (archive.org's file as it stands), and raise when the two differ?
#
#     python3 tools/test_pdf_edition_broken.py
#
# A three-page PDF made here, no network, nothing written outside a temp dir.
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import hashlib, io
from PIL import Image
import fetch_archive_org_editions as fa

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

buf = io.BytesIO()
pages = [Image.new("1", (400, 600), 1) for _ in range(3)]
pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:])
whole = buf.getvalue()
fa.grid_boxes = lambda img: []  # no grids: only which pages read is under test

got, jpegs = fa.pdf_pages(whole)
check("whole PDF: every page read", (3, []), (got["leaves"], got["unreadable"]))

# Zero the last page's image from inside its stream through its endstream, as
# archive.org's copy is zeroed through the last page's (Pillow writes that
# page's dict after its image, so the zeros stop short of it here).
# Object numbers differ between Pillow versions, so find the last image object
# and the object after it rather than naming "7 0 obj" and "8 0 obj".
import re
image = whole.rindex(b"/Subtype /Image")
cut = whole.index(b"stream", image) + 20
end = re.compile(rb"\d+ 0 obj").search(whole, cut).start()
broken = whole[:cut] + b"\0" * (end - cut) + whole[end:]
got, _ = fa.pdf_pages(broken)
check("zero-filled tail: pages counted", 3, got["leaves"])
check("zero-filled tail: only the cut page unreadable", [2], [leaf for leaf, _ in got["unreadable"]])
got, _ = fa.pdf_pages(b"\0" * 5000)
check("no PDF at all: one unreadable row, no raise", (0, [None]), (got["leaves"], [l for l, _ in got["unreadable"]]))

# fetch_pdf: a short copy is fetched again once.
class FX:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0
    def get(self, url, what, retry=True):
        self.calls += 1
        return self.replies.pop(0)
name = "Jun 29 1981"
meta = {"files": [{"name": name + ".pdf", "md5": hashlib.md5(whole).hexdigest()}]}
fa.log = lambda *a: None
fx = FX([whole])
check("md5 matches: one fetch", (whole, 1), (fa.fetch_pdf(fx, meta, name, ["b"]), fx.calls))
fx = FX([whole[:100], whole])
check("cut-short copy fetched again", (whole, 2), (fa.fetch_pdf(fx, meta, name, ["b"]), fx.calls))
fx = FX([broken, broken])
check("same bytes twice: archive.org's file, kept", (broken, 2), (fa.fetch_pdf(fx, meta, name, ["b"]), fx.calls))
fx = FX([whole[:100], whole[:200]])
try:
    fa.fetch_pdf(fx, meta, name, ["b"])
    check("two differing bad copies raise", "RuntimeError", None)
except RuntimeError:
    check("two differing bad copies raise", 2, fx.calls)
print(f"FAILS {fails}")
