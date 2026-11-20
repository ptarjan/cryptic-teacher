#!/usr/bin/env python3
"""The per-entry ledgers kept as a folder of small shard files, not one big file.

    tools/data/source_clue_wrong/<shard>.json
    tools/data/blog_disagree/<shard>.json

Each was one 1-2 MB object that a burn run rewrote many times a day, and git
stores a whole new blob per change: the two were the biggest source of repo
growth. A row lives in the shard its puzzle id picks (shard_of), so a commit
touching a few puzzles rewrites a few tens of kB.

A shard is "<series>-<bucket>": the id's series and its number divided into
buckets of BUCKET[series] (BUCKET_DEFAULT where unlisted), zero padded, so
`times-18749/3-down` is in `times-18.json` and `azed-1822/32-across` in
`azed-00.json`. The rule depends only on the key, so every writer agrees where a
row goes and a merge never sees one row in two files. Every shard is a flat
object keyed "puzzle id/entry id", one row per line (json_merge.dump_lines), and
merged per key by .gitattributes' json-keys driver.

load(name) is the whole table, save(name, rows) writes only the shards whose
rows changed and deletes a shard left empty. For a table not sharded they read
and write the one file tools/data/<name>.json, so a caller needs not know.
"""
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
#: The ledgers kept as folders.
SHARDED = ("source_clue_wrong", "blog_disagree")
#: Numbers per shard: times is most of both ledgers.
BUCKET = {"times": 1000}
BUCKET_DEFAULT = 5000
_ID = re.compile(r"([a-z][a-z0-9]*)-(\d+)")


def shard_of(key):
    """The shard name ("times-18") of a key "<puzzle id>[/<entry id>]"."""
    m = _ID.fullmatch(key.split("/", 1)[0])
    if not m:
        return "other"
    series, num = m.group(1), int(m.group(2))
    return f"{series}-{num // BUCKET.get(series, BUCKET_DEFAULT):02d}"


def sharded(name):
    return name in SHARDED


def folder(name, data=DATA):
    return Path(data) / name


def files(name, data=DATA):
    """The files holding table `name`, sorted."""
    if not sharded(name):
        p = Path(data) / f"{name}.json"
        return [p] if p.exists() else []
    d = folder(name, data)
    return sorted(d.glob("*.json")) if d.is_dir() else []


def rel_paths(name):
    """The repo-relative glob/path that names table `name`'s file(s)."""
    return f"tools/data/{name}/*.json" if sharded(name) else f"tools/data/{name}.json"


def table_of(rel):
    """The table a repo-relative path `tools/data/...` is a file of, or None."""
    m = re.fullmatch(r"tools/data/(\w+?)(?:/[\w\-]+)?\.json", rel)
    if not m:
        return None
    name = m.group(1)
    is_shard = rel.count("/") == 3
    return name if is_shard == sharded(name) else None


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(name, data=DATA):
    """Table `name` whole: {"puzzle id/entry id": row}."""
    rows = {}
    for p in files(name, data):
        rows.update(_read(p))
    return rows


def split(rows):
    """{shard: {key: row}} of a table's rows."""
    out = {}
    for k, v in rows.items():
        out.setdefault(shard_of(k), {})[k] = v
    return out


def save(name, rows, data=DATA):
    """Write table `name` as `rows`: a shard whose rows are unchanged is not
    touched, a shard with none left is removed. Returns the paths written."""
    from json_merge import dump_lines, write_atomic
    data = Path(data)
    if not sharded(name):
        p = data / f"{name}.json"
        write_atomic(p, dump_lines(rows))
        return [p]
    d = folder(name, data)
    d.mkdir(parents=True, exist_ok=True)
    wanted = split(rows)
    written = []
    for shard, part in wanted.items():
        p = d / f"{shard}.json"
        text = dump_lines(part)
        if not p.exists() or p.read_text(encoding="utf-8") != text:
            write_atomic(p, text)
            written.append(p)
    for p in d.glob("*.json"):
        if p.stem not in wanted:
            p.unlink()
            written.append(p)
    return written


def blob_paths(name, rows):
    """{repo-relative path: dump_lines text} for table `name` as `rows`: what
    to store for a caller writing blobs with git plumbing."""
    from json_merge import dump_lines
    if not sharded(name):
        return {f"tools/data/{name}.json": dump_lines(rows)}
    return {f"tools/data/{name}/{s}.json": dump_lines(p) for s, p in split(rows).items()}
