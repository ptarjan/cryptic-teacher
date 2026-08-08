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
LINE = (145, 153, 163)      # --gridline
BLOCK = (20, 23, 26)        # --blockfill
ACCENT = (15, 92, 134)      # --accent, the "revealed letter" blue
BG = (250, 248, 244)        # page paper

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


def draw_grid(px, ox, oy, cell, gap, border):
    """Draw the 5x5 motif with its top-left at (ox, oy)."""
    span = 5 * cell + 4 * gap
    rect(px, ox - border, oy - border, ox + span + border, oy + span + border, BLOCK)
    rect(px, ox, oy, ox + span, oy + span, LINE)
    for r in range(5):
        for c in range(5):
            x = ox + c * (cell + gap)
            y = oy + r * (cell + gap)
            if (r, c) in BLOCKS:
                fill = BLOCK
            elif (r, c) in ACCENTS:
                fill = ACCENT
            else:
                fill = PAPER
            rect(px, x, y, x + cell, y + cell, fill)
    return span


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


def icon(size):
    """Square app icon at `size`px: paper background, motif inset ~8%."""
    px = canvas(size, size, BG)
    border = max(1, round(size * 0.016))
    gap = max(1, round(size * 0.008))
    inset = round(size * 0.09)
    cell = (size - 2 * inset - 4 * gap) // 5
    span = 5 * cell + 4 * gap
    off = (size - span) // 2
    draw_grid(px, off, off, cell, gap, border)
    return px


def write_ico(path, sizes):
    """ICO with PNG-compressed entries (every browser since IE11 groks this)."""
    images = []
    for s in sizes:
        tmp = ROOT / f".ico-{s}.png"
        data = write_png(tmp, icon(s))
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
    cell, gap, span = 10, 0.5, 52
    def xy(i):
        return round(i * (cell + gap), 1)
    squares = []
    for r in range(5):
        for c in range(5):
            fill = ("#14171a" if (r, c) in BLOCKS
                    else "#0f5c86" if (r, c) in ACCENTS else "#ffffff")
            squares.append(f'<rect x="{xy(c)}" y="{xy(r)}" width="{cell}" '
                           f'height="{cell}" fill="{fill}"/>')
    rows = "\n      ".join("".join(squares[i:i + 5]) for i in range(0, 25, 5))
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img"\n'
        '     aria-label="Cryptic Teacher">\n'
        '  <!-- GENERATED by tools/make_icons.py from BLOCKS/ACCENTS. Don\'t edit. -->\n'
        '  <rect width="64" height="64" fill="#faf8f4"/>\n'
        '  <g transform="translate(6 6)">\n'
        '    <rect x="-2" y="-2" width="56" height="56" fill="#14171a"/>\n'
        f'    <rect width="{span}" height="{span}" fill="#9199a3"/>\n'
        f'    <g>\n      {rows}\n    </g>\n'
        '  </g>\n</svg>\n', encoding="utf-8")


def check_motif():
    """Refuse to draw a mini-grid that isn't a legal one. Shares the social
    card's checker so the two artefacts can never disagree about the rules."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from grid_rules import check
    check([[(r, c) not in BLOCKS for c in range(5)] for r in range(5)])


if __name__ == "__main__":
    check_motif()
    for name, size in (("favicon-16.png", 16), ("favicon-32.png", 32),
                       ("icon-192.png", 192), ("apple-touch-icon.png", 180),
                       ("icon-512.png", 512)):
        write_png(ROOT / name, icon(size))
        print("wrote", name)
    write_ico(ROOT / "favicon.ico", (16, 32, 48))
    print("wrote favicon.ico")
    write_svg(ROOT / "favicon.svg")
    print("wrote favicon.svg")
