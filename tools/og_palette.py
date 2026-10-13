#!/usr/bin/env python3
"""Rewrite social cards as 256-colour palette PNGs, in place.

  python3 tools/og_palette.py og.png og/*.png

Chrome screenshots a card as 24-bit RGB, ~74 KB. A card is flat colour and
anti-aliased type, about 4,300 distinct colours, and a median-cut 256-colour
palette without dithering holds it at ~46 dB PSNR, indistinguishable at 2x
zoom, in ~28 KB. The size stays 1200x630, the size every unfurler asks for.

Palette PNG, not JPEG or WebP: on the same cards JPEG is ~48-55 KB at
quality 80 and WebP ~35-40 KB at 85, because flat colour and sharp type are
exactly what palette PNG stores cheaply and DCT stores badly.

A file that is already a palette PNG is left alone, so re-running over a
directory of cards costs one header read per card. Missing paths are skipped:
the caller passes a glob that may match nothing.
"""
import os
import sys
from pathlib import Path

from PIL import Image


def is_palette(path):
    """Whether path is a PNG whose IHDR says colour type 3 (palette): byte 25,
    after the 8-byte signature and IHDR's length, type, width, height and bit
    depth. Read raw because opening each of ~17k cards with Pillow to ask was
    most of the ~8s this took on a deploy that drew one card."""
    with open(path, "rb") as f:
        head = f.read(26)
    return head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR" and head[25] == 3


def palettise(path):
    """True if path was rewritten, False if it was already a palette PNG."""
    if is_palette(path):
        return False
    with Image.open(path) as im:
        if im.mode == "P":
            return False
        q = im.convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT,
                                       dither=Image.Dither.NONE)
    tmp = path.with_name(path.name + ".tmp")
    q.save(tmp, "PNG", optimize=True)
    os.replace(tmp, path)
    return True


def main(paths):
    done = sum(palettise(p) for p in map(Path, paths) if p.is_file())
    if done:
        print(f"og_palette: {done} card(s) rewritten as palette PNGs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
