#!/usr/bin/env python3
"""Read qr.js's output back with a real QR decoder.

The encoder in qr.js is hand-written (its header says why the sync code cannot
be handed to an image service), and a wrong QR code is wrong silently: it draws,
it looks like a QR code, and phones simply decline to see it. So the check is
the only one that means anything — render the modules and decode the picture,
over the join URLs the sync panel really builds plus the payload lengths either
side of every version boundary the encoder claims.

Hand-run, not part of the smoke test: it needs a decoder the site does not.

  pip install opencv-python-headless numpy
  python3 tools/qr_check.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    import cv2
    import numpy as np
except ImportError:
    sys.exit("qr_check needs a decoder: pip install opencv-python-headless numpy")

SCALE = 8      # pixels per module
QUIET = 4      # modules of white margin, as the standard requires

# The join URLs, then the largest payload each version takes and the one below
# it, so an off-by-one in the capacity table shows up as a version that will not
# encode or one that overflows.
CAPACITY = [14, 26, 42, 62, 84, 106, 122, 152, 180, 213]
CASES = [
    "https://paultarjan.com/cryptic-teacher/?sync=ABCD2345",
    "https://paultarjan.com/cryptic-teacher/?sync=99999999",
    "http://localhost:8000/?sync=ABCD2345",
    "A",
]
for n in CAPACITY:
    CASES.append("x" * n)
    CASES.append(("Cryptic Teacher 12345/" * 12)[:n])


def modules(text):
    out = subprocess.run(
        ["node", "-e",
         "process.stdout.write(JSON.stringify(require(process.argv[1]).encode(process.argv[2])))",
         str(ROOT / "qr.js"), text],
        capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"qr.js failed on {len(text)} bytes: {out.stderr.strip()}")
    return json.loads(out.stdout)


def decode(rows):
    size = len(rows)
    img = np.full(((size + 2 * QUIET) * SCALE, (size + 2 * QUIET) * SCALE), 255, np.uint8)
    for r, row in enumerate(rows):
        for c, on in enumerate(row):
            if not on:
                continue
            y, x = (r + QUIET) * SCALE, (c + QUIET) * SCALE
            img[y:y + SCALE, x:x + SCALE] = 0
    return cv2.QRCodeDetector().detectAndDecode(img)[0]


bad = 0
for text in CASES:
    rows = modules(text)
    got = decode(rows)
    if got == text:
        continue
    bad += 1
    print(f"FAIL {len(text)} bytes, {len(rows)}x{len(rows)}: decoded {got[:60]!r}")

print(f"{len(CASES) - bad}/{len(CASES)} payloads decode back to what went in")
sys.exit(1 if bad else 0)
