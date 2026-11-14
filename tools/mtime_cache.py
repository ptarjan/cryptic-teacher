"""Per-file results that survive between runs, re-read only when a file changed.

`scan(name, paths, fn)` returns {path: fn(path)}. A result is reused while the
file's (mtime_ns, size) is unchanged, so a run over ~57k puzzle files reads
the few that moved since the last run instead of every one (the whole-corpus
scans of coverage.py and fetch_telegraph.py were 100-200 MB/min of disk reads
each). fn must return something JSON-serialisable and depend on that file only.
The cache lives in /data/home/.cache (or $CT_MTIME_CACHE_DIR), best effort.
"""

import json
import os
from pathlib import Path


def _dir():
    return Path(os.environ.get("CT_MTIME_CACHE_DIR", "/data/home/.cache/ct-mtime"))


def scan(name, paths, fn):
    cache_file = _dir() / f"{name}.json"
    try:
        old = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    new, out, changed = {}, {}, False
    for p in paths:
        key = str(p)
        st = p.stat()
        stamp = [st.st_mtime_ns, st.st_size]
        hit = old.get(key)
        if hit and hit[0] == stamp:
            new[key] = hit
        else:
            new[key] = [stamp, fn(p)]
            changed = True
        out[p] = new[key][1]
    if changed or len(new) != len(old):
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(new), encoding="utf-8")
            tmp.replace(cache_file)
        except OSError:
            pass
    return out
