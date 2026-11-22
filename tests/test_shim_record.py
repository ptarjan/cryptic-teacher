#!/usr/bin/env python3
# Does shim_record.md5() answer every shim's true md5[:8], reading only the
# shims whose stat moved, and does its record survive the shim cache's tar?
#
#     python3 tests/test_shim_record.py
#
# A scratch puzzles/ dir: an old shim is read once and recorded; the record,
# saved and loaded again, answers it unread (proved by changing the bytes
# behind an unchanged stat, the one thing the record cannot see); its mtime
# cut to whole seconds, as tar keeps it, still matches; any real rewrite,
# even to the same size, is read again; a just-written shim is answered but
# not recorded; a missing one is None.
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import _path  # puts tools/ on sys.path
import puzzle_paths
import shim_record

fails = []


def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")


def h(data):
    return hashlib.md5(data).hexdigest()[:8]


def fresh_process():
    shim_record._LOADED.clear()


tmp = Path(tempfile.mkdtemp())
try:
    puzzle_paths.PUZZLE_DIR = tmp / "puzzles"
    puzzle_paths.PUZZLE_DIR.mkdir()
    shim = puzzle_paths.PUZZLE_DIR / "times-1.js"
    old_ns = time.time_ns() - 3600 * 10**9 + 123456789  # an hour ago, mid-second

    shim.write_bytes(b"AAAA")
    os.utime(shim, ns=(old_ns, old_ns))
    check("first read", shim_record.md5(shim), h(b"AAAA"))
    shim_record.save()
    check("record written", (puzzle_paths.PUZZLE_DIR / shim_record.RECORD).is_file(), True)

    # The bytes change behind the same stat: an answer of the old hash means
    # the record answered without reading.
    fresh_process()
    shim.write_bytes(b"BBBB")
    os.utime(shim, ns=(old_ns, old_ns))
    check("answered off the record", shim_record.md5(shim), h(b"AAAA"))

    # tar keeps whole seconds: the restored mtime still matches.
    fresh_process()
    whole = old_ns // 10**9 * 10**9
    os.utime(shim, ns=(whole, whole))
    check("whole-second mtime matches", shim_record.md5(shim), h(b"AAAA"))

    # A real rewrite of the same size stamps a new mtime: read again.
    fresh_process()
    shim.write_bytes(b"CCCC")
    check("rewrite read", shim_record.md5(shim), h(b"CCCC"))
    shim_record.save()
    fresh_process()
    check("just-written shim not recorded", shim.name in shim_record._record(puzzle_paths.PUZZLE_DIR)[0]
          and shim_record._record(puzzle_paths.PUZZLE_DIR)[0][shim.name][0] == h(b"CCCC"), False)
    check("just-written shim answered", shim_record.md5(shim), h(b"CCCC"))

    shim.unlink()
    check("missing shim", shim_record.md5(shim), None)

    # A shim outside PUZZLE_DIR (a fixture's) is read every time.
    other = tmp / "elsewhere.js"
    other.write_bytes(b"DDDD")
    os.utime(other, ns=(old_ns, old_ns))
    check("outside shim", shim_record.md5(other), h(b"DDDD"))
    other.write_bytes(b"EEEE")
    os.utime(other, ns=(old_ns, old_ns))
    check("outside shim not recorded", shim_record.md5(other), h(b"EEEE"))

    # An unreadable record costs reads, nothing else.
    (puzzle_paths.PUZZLE_DIR / shim_record.RECORD).write_text("{garbled", encoding="utf-8")
    fresh_process()
    shim.write_bytes(b"FFFF")
    os.utime(shim, ns=(old_ns, old_ns))
    check("garbled record", shim_record.md5(shim), h(b"FFFF"))
finally:
    shutil.rmtree(tmp, True)

if fails:
    print("test_shim_record FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("test_shim_record: ok")
