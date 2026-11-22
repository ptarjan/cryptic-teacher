#!/usr/bin/env python3
# Does fetch_puzzle.sidecar_blob() give the git blob id of a puzzle's sidecar
# bytes, whether it comes off git's listing or off the file?
#
#     python3 tests/test_sidecar_blob.py
#
# A scratch git checkout with two puzzles and one committed sidecar: the
# listing (_clean_sidecar_blobs, which index_rows() holds while it maps) names
# the clean sidecar with git's own id; an edited one is left out and read, so
# it gets the new bytes' id; an untracked one is read; a puzzle with none is
# None. Each answer is held to `git hash-object` of the file.
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import _path  # puts tools/ on sys.path
import fetch_puzzle as fp
import puzzle_paths

fails = []


def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")


def git(*args):
    return subprocess.run(["git", "-C", str(tmp), *args], check=True, capture_output=True, text=True).stdout.strip()


def ids():
    """sidecar_blob of both puzzles as index_rows() asks: listing held."""
    fp._SIDECAR_BLOBS.update(fp._clean_sidecar_blobs())
    try:
        return fp.sidecar_blob(a), fp.sidecar_blob(b)
    finally:
        fp._SIDECAR_BLOBS.clear()


tmp = Path(tempfile.mkdtemp())
try:
    puzzle_paths.PUZZLE_DIR = tmp / "puzzles"
    d = puzzle_paths.PUZZLE_DIR / "times" / "2020"
    d.mkdir(parents=True)
    a, b = d / "times-1.json", d / "times-2.json"
    a.write_text("{}\n")
    b.write_text("{}\n")
    a.with_suffix(".blog").write_text('{"x": 1}\n')
    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")

    listed = fp._clean_sidecar_blobs()
    check("listing", listed, {"puzzles/times/2020/times-1.blog": git("rev-parse", "HEAD:puzzles/times/2020/times-1.blog")})
    check("clean, off the listing", ids(), (git("hash-object", str(a.with_suffix(".blog"))), None))
    check("clean, off the file", fp.sidecar_blob(a), git("hash-object", str(a.with_suffix(".blog"))))

    a.with_suffix(".blog").write_text('{"x": 2}\n')
    check("edited", ids()[0], git("hash-object", str(a.with_suffix(".blog"))))

    b.with_suffix(".blog").write_text('{"y": 1}\n')
    check("untracked", ids()[1], git("hash-object", str(b.with_suffix(".blog"))))

    a.with_suffix(".blog").unlink()
    check("deleted", ids()[0], None)
finally:
    shutil.rmtree(tmp, True)

if fails:
    print("test_sidecar_blob FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("test_sidecar_blob: ok")
