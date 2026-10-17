#!/usr/bin/env python3
# Do the Trove clue vote (file_trove_puzzles.vote_anywhere) and the solution
# image match (trove_solution_ocr.fits_anywhere) take the desktop's answer
# when ocr_remote.call() gives one, the same answer here when it gives None
# (no desktop, a game, a failed call), and do CALLS name the functions that
# run there?
#
#     python3 tools/test_desktop_offload.py
#
# No ssh, no OCR: ocr_remote.call is replaced, the images are drawn.
import pickle
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from PIL import Image

import file_trove_puzzles as ftp
import ocr_remote
import trove_solution_ocr as tso

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print("ok  ", what)
    else:
        print(f"FAIL {what}: expected {want!r}, got {got!r}")
        fails += 1


@contextmanager
def calling(fn):
    """ocr_remote.call replaced by fn(name, *args, data=b'', **kw); local_slot a no-op."""
    real, slot = ocr_remote.call, ocr_remote.local_slot
    ocr_remote.call = fn
    ocr_remote.local_slot = contextmanager(lambda: (yield))
    try:
        yield
    finally:
        ocr_remote.call, ocr_remote.local_slot = real, slot


for name, target in (("clue_vote", "file_trove_puzzles.vote_there"), ("solution_fits", "trove_solution_ocr.fits_there")):
    check(f"CALLS names {name}", target, ocr_remote.CALLS.get(name))

# The vote: the stage's answer travels pickled; None (or an empty reply) runs it here.
ftp.VOTE_STAGES["probe"] = lambda *a: ("here", a)
asked = []


def desktop(name, *args, data=b"", **kw):
    asked.append((name, args))
    return {}, pickle.dumps(("there", pickle.loads(data)), protocol=4)


with calling(desktop):
    check("vote taken from the desktop", ("there", (1, {"k": ("t", None, None)})),
          ftp.vote_anywhere("probe", 1, {"k": ("t", None, None)}))
check("vote asked as clue_vote with its stage", [("clue_vote", ("probe",))], asked)
with calling(lambda *a, **k: None):
    check("vote falls back when the desktop is out", ("here", (1, 2)), ftp.vote_anywhere("probe", 1, 2))
with calling(lambda *a, **k: ({}, b"")):
    check("vote falls back on an empty reply", ("here", (3,)), ftp.vote_anywhere("probe", 3))
check("vote_there runs the stage on the pickled arguments", ({}, pickle.dumps(("here", (4, 5)), protocol=4)),
      ftp.vote_there(pickle.dumps((4, 5), protocol=4), "probe"))

# The match: a drawn 15x15 solution image, sent with one rival image.
tmp = Path(__file__).resolve().parent / "fixtures" / "trove"
solution = next(tmp.glob("*/grid.jpg"), None)
if solution is None:
    print("skip the match: no fixture images")
else:
    grid = ["".join(r) for r in ftp.trove_grid.read_grid(solution)[0] or []]
    gray = np.asarray(Image.open(solution).convert("L"))
    here = tso.fits(gray, grid, [solution]) if grid else None
    with calling(lambda *a, **k: None):
        check("match falls back to fits() here", here, tso.fits_anywhere(solution, grid, [solution]) if grid else None)
    packed = []

    def fits_desktop(name, *args, data=b"", **kw):
        packed.append((name, args[1]))
        got, back = tso.fits_there(data, *args)
        return {"fit": None if got["fit"] is None else [got["fit"][0], got["fit"][1]]}, back

    if grid:
        with calling(fits_desktop):
            check("match taken from the desktop, the same", here, tso.fits_anywhere(solution, grid, [solution]))
        check("match sends each image's size", [("solution_fits", [solution.stat().st_size] * 2)], packed)

print("all ok" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
