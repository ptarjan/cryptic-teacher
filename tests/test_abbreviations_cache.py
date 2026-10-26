#!/usr/bin/env python3
# Does build_abbreviations.table() give the same table from its disk cache as
# from a build, and rebuild the moment an input's bytes change?
#
#     python3 tests/test_abbreviations_cache.py
#
# The cache is a temp file ($ABBREVIATIONS_CACHE); the real lexicons are read, not written.
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
os.environ["ABBREVIATIONS_CACHE"] = str(tmp / "table.json")
sys.path.insert(0, str(REPO / "tools"))
import build_abbreviations as b

fails = 0


def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what
          + ("" if want == got else f": expected {str(want)[:60]!r}, got {str(got)[:60]!r}"))
    fails += want != got


try:
    cache = tmp / "table.json"
    built = b.table()
    check("a first call writes the cache", True, cache.exists())
    check("the cache holds the table it built", built, json.loads(cache.read_text())["table"])
    b._TABLE = None
    b._build_table = lambda: sys.exit("rebuilt although no input changed")
    check("a second process-start reads the cache, same table", built, b.table())

    # An edited input changes the key: the stale table is not served.
    key = b._inputs_key()
    real = b.DICTIONARY
    edited = tmp / "abbreviations.json"
    edited.write_text(real.read_text(encoding="utf-8") + " ")
    b.DICTIONARY = edited
    check("an input's bytes change the key", True, b._inputs_key() != key)
    b._TABLE = None
    b._build_table = lambda: {"X": ["marker"]}
    check("a changed input rebuilds", {"X": ["marker"]}, b.table())
    check("and the cache now carries the new key", b._inputs_key(), json.loads(cache.read_text())["key"])

    # A corrupt cache is a miss, not an error.
    cache.write_text("{not json")
    b._TABLE = None
    b._build_table = lambda: {"Y": ["rebuilt"]}
    check("a corrupt cache rebuilds", {"Y": ["rebuilt"]}, b.table())
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
