"""A grid whose rules are paler than trove_grid's paper line.

trove_grid.white_cells walls cells apart with ink and "not clearly paper"
(grey darker than the midpoint of Otsu's cut and the 90th percentile). The
1940-41 Gale Times pages print their cell rules in a grey as pale as the
paper's own shading: the rules fall on the paper side of that line, every
light joins its neighbours into one white patch (one patch of 165,000 pooled
pixels in a 1,050px grid), and the page was refused "only 9 white cells
found" or "too few neighbouring white cells to measure the lattice" (86 of
1940-41's pages, 1940-01-06 to 1941-07-15).

pale_read takes everything below the 90th percentile as not paper, ink and
rule alike (the image cut to black and white at that grey), and hands it to
trove_grid.read_grid: the blocks, the symmetry and the lights' checks are
read_grid's own, so a lattice that is no crossword's is still refused. It is
tried only after trove_grid's own read and the shrunk reads fail
(file_archive_org_puzzles.scaled_grid_read), so a grid read before is read
as it was.
"""
import io

import numpy as np
from PIL import Image

import trove_grid

#: The whys of trove_grid.white_cells that a paler paper line may mend.
PALE_WHYS = ("too few neighbouring white cells", "only ")
#: The percentile of the page's greys that is paper's own.
PAPER_PERCENTILE = 90


def pale_whys(why):
    """Whether `why` (a read_grid refusal) is one a paler paper line may mend."""
    return bool(why) and why.startswith(PALE_WHYS) and "white cells" in why


def pale_read(path):
    """(rows, None) or (None, why): trove_grid.read_grid of the crop at `path` cut to black and
    white at the PAPER_PERCENTILE grey."""
    gray = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    line = float(np.percentile(gray, PAPER_PERCENTILE))
    flat = np.where(gray < line, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(flat).save(buf, "PNG")
    buf.seek(0)
    return trove_grid.read_grid(buf)
