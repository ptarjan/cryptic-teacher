#!/usr/bin/env python3
"""Rewrite social cards as 64-colour palette PNGs, in place.

  python3 tools/og_palette.py og.png og/*.png

Chrome screenshots a card as 24-bit RGB, ~67 KB. A card is flat colour and
anti-aliased type, about 4,300 distinct colours. A median-cut palette without
dithering holds it at 256 colours in ~27 KB (~58 dB PSNR) and at 64 colours in
~21.5 KB (~46 dB average, ~44 dB worst over 80 cards), still indistinguishable
from the original at 2x zoom on the smallest type (2026-10-13). 64 it is: the
~19k puzzle cards were a fifth of the published site (~556 MB) and this takes
~105 MB off it. The size stays 1200x630, the size every unfurler asks for.

There is no sharing cards between puzzles instead: every card is a different
clue from its own puzzle (make_og_card.py), so all of them are distinct images
and each is referenced by exactly one page.

Palette PNG, not JPEG or WebP: on the same cards JPEG is ~48-55 KB at
quality 80 and WebP ~35-40 KB at 85, because flat colour and sharp type are
exactly what palette PNG stores cheaply and DCT stores badly.

A file that is already a palette PNG of at most COLOURS entries is left alone,
so re-running over a directory of cards costs one header read per card.
A card Chrome just drew (not a palette PNG) is always converted. One left
at 256 colours by the older scheme is converted too, but at most
OG_REPALETTE_LIMIT (1000) a run: each one changes its card's ?v= stamp and so
re-renders its page (tools/page_cache.py), and ~0.16s a card across the
cache's ~19k would hold one deploy past the card step's budget. They drain over
later runs instead, as OG_LIMIT does for drawing. Missing paths are skipped:
the caller passes a glob that may match nothing.
"""
import os
import struct
import sys
from pathlib import Path

from PIL import Image

import parallel  # the cards across the cores

COLOURS = 64
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def palette_size(path):
    """How many PLTE entries path has if it is a palette PNG (IHDR colour type
    3), else None. Read raw, chunk headers only, because opening each of ~19k
    cards with Pillow to ask was most of the ~8s this took on a deploy that
    drew one card."""
    with open(path, "rb") as f:
        head = f.read(33)
        if (len(head) < 33 or head[:8] != SIGNATURE or head[12:16] != b"IHDR"
                or head[25] != 3):
            return None
        while True:  # PLTE must come before IDAT; Pillow writes it straight after IHDR
            chunk = f.read(8)
            if len(chunk) < 8:
                return None
            length, kind = struct.unpack(">I4s", chunk)
            if kind == b"PLTE":
                return length // 3
            if kind == b"IDAT":
                return None
            f.seek(length + 4, os.SEEK_CUR)


def is_palette(path):
    """Whether path is already a palette PNG of at most COLOURS colours."""
    n = palette_size(path)
    return n is not None and n <= COLOURS


def palettise(path):
    """True if path was rewritten, False if it was already done."""
    path = Path(path)
    if is_palette(path):
        return False
    with Image.open(path) as im:
        q = im.convert("RGB").quantize(COLOURS, method=Image.Quantize.MEDIANCUT,
                                       dither=Image.Dither.NONE)
    tmp = path.with_name(path.name + ".tmp")
    q.save(tmp, "PNG", optimize=True)
    os.replace(tmp, path)
    return True


def todo(paths, limit):
    """The paths to rewrite: every non-palette PNG, then up to limit of the
    ones still at more than COLOURS colours."""
    fresh, older = [], []
    for p in paths:
        if not p.is_file():
            continue
        n = palette_size(p)
        if n is None:
            fresh.append(p)
        elif n > COLOURS:
            older.append(p)
    return fresh + older[:limit], len(older) - min(len(older), limit)


def main(paths):
    limit = int(os.environ.get("OG_REPALETTE_LIMIT", "1000"))
    work, left = todo([Path(p) for p in paths], limit)
    done = sum(parallel.pmap(palettise, [str(p) for p in work], chunksize=16))
    if done:
        print(f"og_palette: {done} card(s) rewritten as {COLOURS}-colour palette PNGs")
    if left:
        print(f"og_palette: {left} card(s) still above {COLOURS} colours, for later runs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
