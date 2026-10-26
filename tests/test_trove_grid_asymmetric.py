#!/usr/bin/env python3
# Does trove_grid.read_grid keep a block whose 180-degree mirror is a light?
#
#     python3 tests/test_trove_grid_asymmetric.py
#
# A drawn 15x15 grid with blocks on every odd row and column plus one block
# (and no mirror for it): the read must give the block back, not average it
# with its white mirror into a light (Cyclops 121's row-10 bar).
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import trove_grid
from PIL import Image, ImageDraw

N, S, M = 15, 44, 60
want = [["#" if r % 2 and c % 2 else "." for c in range(N)] for r in range(N)]
want[9][4] = "#"  # its mirror, r5 c10, stays a light
img = Image.new("L", (N * S + 2 * M, N * S + 2 * M), 255)
d = ImageDraw.Draw(img)
for r in range(N):
    for c in range(N):
        box = (M + c * S, M + r * S, M + (c + 1) * S, M + (r + 1) * S)
        d.rectangle(box, fill=0 if want[r][c] == "#" else 255, outline=0, width=2)
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "g.png"
    img.save(path)
    got, why = trove_grid.read_grid(path)
rows = ["".join(r) for r in want]
if got == rows:
    print("ok   asymmetric block kept")
else:
    print(f"FAIL asymmetric block: {why}\n" + "\n".join(got or []))
    sys.exit(1)
