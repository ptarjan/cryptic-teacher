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
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAPER = (255, 255, 255)
LINE = (145, 153, 163)      # --gridline
BLOCK = (20, 23, 26)        # --blockfill
ACCENT = (15, 92, 134)      # --accent, the "revealed letter" blue
BG = (250, 248, 244)        # page paper

# The motif: a 5x5 mini-grid with a symmetric diamond of blocked squares and one
# accent square in the middle. Reads as a crossword even at 16px.
BLOCKS = {(0, 2), (2, 0), (2, 4), (4, 2)}
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


if __name__ == "__main__":
    for name, size in (("favicon-16.png", 16), ("favicon-32.png", 32),
                       ("icon-192.png", 192), ("apple-touch-icon.png", 180),
                       ("icon-512.png", 512)):
        write_png(ROOT / name, icon(size))
        print("wrote", name)
    write_ico(ROOT / "favicon.ico", (16, 32, 48))
    print("wrote favicon.ico")
