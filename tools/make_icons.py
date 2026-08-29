#!/usr/bin/env python3
"""Generate the site icons from one source of truth: a 5x5 crossword motif.

No image libraries are installed on the Mac mini (no PIL), so this writes PNG
bytes directly — zlib + struct is all it takes for flat-colour art. Re-run after
changing the palette or the block pattern:

    python3 tools/make_icons.py

Outputs favicon.ico, favicon-16/32.png, icon-192/512.png, apple-touch-icon.png
into the repo root. The 1200x630 social card is separate: it needs real
type, so it is rendered from tools/og_card.html by tools/make_og.sh.
"""
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAPER = (255, 255, 255)
BLOCK = (20, 23, 26)        # --blockfill, and the field the motif sits on
ACCENT = (15, 92, 134)      # --accent, the "revealed letter" blue

# The motif: a 5x5 mini-grid, blocks symmetric about the centre, one accent
# square in the middle. Reads as a crossword even at 16px.
#
# The blocks used to sit at the edge midpoints — (0,2), (2,0), (2,4), (4,2) — a
# diamond, which looked tidier and was not a crossword: it left eight runs of two
# white cells, and no British cryptic has a two-letter entry. Moved inwards to
# the diagonal, which is legal: runs of ONE are fine (that is an unchecked square
# inside the perpendicular light), runs of two are not. check_motif() below is
# the same checker the social card uses, so neither can drift back.
BLOCKS = {(1, 1), (1, 3), (3, 1), (3, 3)}
ACCENTS = {(2, 2)}


def canvas(w, h, colour):
    return [[colour] * w for _ in range(h)]


def rect(px, x0, y0, x1, y1, colour):
    h, w = len(px), len(px[0])
    for y in range(max(0, y0), min(h, y1)):
        row = px[y]
        for x in range(max(0, x0), min(w, x1)):
            row[x] = colour


def fill_of(r, c):
    return BLOCK if (r, c) in BLOCKS else ACCENT if (r, c) in ACCENTS else PAPER


def hexc(rgb):
    """The PNGs and the SVG take their colours from the same three constants.
    The SVG used to spell its own hexes out, which is the drift this module
    already learned about once."""
    return "#%02x%02x%02x" % rgb


def write_png(path, px):
    h, w = len(px), len(px[0])
    raw = b"".join(
        b"\x00" + b"".join(struct.pack("BBB", *p) for p in row) for row in px)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return png


GAP_PCT = 0.013     # gridline
MASK_INSET = 0.10   # app icons: clear of the corner iOS and Android round off
TAB_INSET = 0.03    # favicons: nothing masks these, so give the cells the room


def icon(size, inset_pct=MASK_INSET):
    """Square icon at `size`px: the motif full-bleed on ink.

    Full bleed, and dark, because of where this is actually seen. It used to be
    the motif inset in a page-coloured square with hairline gridlines, which is a
    near-white tile on a Home Screen — no silhouette against a light wallpaper,
    and the mark itself only four fifths of an already small icon. iOS and Android
    both mask the corners into a shape of their own choosing, so the field has to
    run to the edge or the result looks like a sticker with a margin.

    The gridlines stay hairline and the frame does the work. Fat gutters were
    tried and are worse: at 5% of the icon the cells stop touching and read as
    five rows of loose tiles, and a block becomes indistinguishable from the gap
    beside it. A crossword is a solid white field cut by thin lines, so that is
    what this draws — the ink frame is what gives it an edge.

    The frame is also the mask allowance. Both platforms round the corners off an
    app icon, and at 10% the grid's own corner clears the arc with room to spare;
    at the 8% tried first it sat about two pixels inside it, which is the kind of
    margin that survives one phone and clips on the next.
    """
    px = canvas(size, size, BLOCK)
    gap = max(1, round(size * GAP_PCT))
    inset = round(size * inset_pct)
    cell = (size - 2 * inset - 4 * gap) // 5
    off = (size - (5 * cell + 4 * gap)) // 2
    for r in range(5):
        for c in range(5):
            x, y = off + c * (cell + gap), off + r * (cell + gap)
            rect(px, x, y, x + cell, y + cell, fill_of(r, c))
    return px


def write_ico(path, sizes):
    """ICO with PNG-compressed entries (every browser since IE11 groks this)."""
    images = []
    for s in sizes:
        tmp = ROOT / f".ico-{s}.png"
        data = write_png(tmp, icon(s, TAB_INSET))
        tmp.unlink()
        images.append((s, data))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32,
                               len(data), offset)
        blobs += data
        offset += len(data)
    path.write_bytes(header + entries + blobs)


def write_svg(path):
    """favicon.svg, from the same BLOCKS as the PNGs.

    It used to be hand-written, under a comment asking whoever edited it to keep
    the two in sync by hand. Generated instead: the drift it was warning about is
    exactly the sort nobody notices, and the SVG is the icon most browsers show.
    """
    side = 64
    gap = round(side * GAP_PCT, 2)
    inset = round(side * TAB_INSET, 2)
    cell = round((side - 2 * inset - 4 * gap) / 5, 2)

    def xy(i):
        return round(inset + i * (cell + gap), 2)
    squares = []
    for r in range(5):
        for c in range(5):
            squares.append(f'<rect x="{xy(c)}" y="{xy(r)}" width="{cell}" '
                           f'height="{cell}" fill="{hexc(fill_of(r, c))}"/>')
    rows = "\n  ".join("".join(squares[i:i + 5]) for i in range(0, 25, 5))
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img"\n'
        '     aria-label="Cryptic Teacher">\n'
        '  <!-- GENERATED by tools/make_icons.py from BLOCKS/ACCENTS. Don\'t edit. -->\n'
        f'  <rect width="{side}" height="{side}" fill="{hexc(BLOCK)}"/>\n'
        f'  {rows}\n</svg>\n', encoding="utf-8")


def check_motif():
    """Refuse to draw a mini-grid that isn't a legal one. Shares the social
    card's checker so the two artefacts can never disagree about the rules."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from grid_rules import check
    check([[(r, c) not in BLOCKS for c in range(5)] for r in range(5)])


if __name__ == "__main__":
    check_motif()
    for name, size, inset in (("favicon-16.png", 16, TAB_INSET),
                              ("favicon-32.png", 32, TAB_INSET),
                              ("icon-192.png", 192, MASK_INSET),
                              ("apple-touch-icon.png", 180, MASK_INSET),
                              ("icon-512.png", 512, MASK_INSET)):
        write_png(ROOT / name, icon(size, inset))
        print("wrote", name)
    write_ico(ROOT / "favicon.ico", (16, 32, 48))
    print("wrote favicon.ico")
    write_svg(ROOT / "favicon.svg")
    print("wrote favicon.svg")
