#!/usr/bin/env python3
"""Rewrite social cards as 256-colour palette PNGs, in place.

  python3 tools/og_palette.py og.png og/*.png

Chrome screenshots a card as 24-bit RGB, ~74 KB. A card is flat colour and
anti-aliased type, about 4,300 distinct colours, and a median-cut 256-colour
palette without dithering holds it at ~46 dB PSNR, indistinguishable at 2x
zoom, in ~28 KB. The size stays 1200x630, the size every unfurler asks for.

A file that is already a palette PNG is left alone, so re-running over a
directory of cards costs one header read per card. Missing paths are skipped:
the caller passes a glob that may match nothing.
"""
import os
import sys
from pathlib import Path

from PIL import Image


def palettise(path):
    """True if path was rewritten, False if it was already a palette PNG."""
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
