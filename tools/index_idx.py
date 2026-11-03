"""The progressive index (DESIGN-progressive-index.md, phase 1): the files
puzzles/idx/ holds beside index.json, written by fetch_puzzle.write_index.

    head-static.<hash>.js      tables that rarely change; window.CRYPTIC_INDEX_STATIC
    head-live.json             latest, the newest rows, counts, percentile cut
                               points, and the manifest {"series/year": hash8}
    <series>-<year>.<hash8>.json   one list of compact rows each (flat, not in a
                               shards/ folder: puzzle_files() globs */*/*-N.json)
    bundle.<hash8>.json        every shard in one file, {"series/year": [rows]}

All of it is build output (gitignored, rebuilt by every --reindex), never
committed. index.json, index.js and index-core.js are untouched.

A row is compact: {n, d, v, s?, a?, h?, u?, df?, ...}. expand_row() rebuilds
the index.json row, with two losses by design: `v` is its first 5 hex chars,
and `percentile` is recovered from the cut points (percentile()). Everything
that is not derivable (a name off its series' template, an id off
series-number, an odd difficulty) is written as it is, so the encoding is
lossless otherwise.
"""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

COMPACT = (",", ":")
RECENT = 300
V_CHARS = 5
DATE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)$")
# Keys a compact row spells differently; anything else is copied as it is.
HANDLED = {"id", "number", "series", "name", "setter", "date", "year", "file", "v",
           "annotated", "hasSolutions", "solutionsUnofficial", "difficulty"}
# What the static head leaves to the live one, because they change per filing
# or per rating.
LIVE_KEYS = {"latest", "build", "snitchRanges"}
SKIP_KEYS = {"puzzles", "unlisted"}
DF_KEYS = {"band", "index", "percentile", "basis"}


def _hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=COMPACT)


def _render(template, number):
    return template.replace("{n}", str(number)).replace("{n:,}", f"{number:,}"
                                                       if isinstance(number, int) else str(number))


def _template(name, number):
    """name with its number put back as a placeholder, or None."""
    for form, mark in ((f"{number:,}" if isinstance(number, int) else None, "{n:,}"),
                       (str(number), "{n}")):
        if form and name.count(form) == 1:
            t = name.replace(form, mark)
            if _render(t, number) == name:
                return t
    return None


def vocab(rows):
    """(bands, basis): the band names and basis factors the rows use. Basis
    is sorted with "blog comments" last, the order difficulty.py writes."""
    bands, basis = set(), set()
    for r in rows:
        d = r.get("difficulty")
        if isinstance(d, dict):
            bands.add(d.get("band"))
            basis.update(d.get("basis") or [])
    return (sorted(bands, key=str),
            sorted(basis, key=lambda f: (f == "blog comments", f)))


def templates(rows):
    """{series: the name template most of its rows follow}."""
    seen = {}
    for r in rows:
        t = _template(r["name"], r["number"]) if isinstance(r.get("name"), str) else None
        if t:
            seen.setdefault(r["series"], Counter())[t] += 1
    return {s: c.most_common(1)[0][0] for s, c in sorted(seen.items())}


def percentile_cuts(rows):
    """101 cut points: cuts[k] is the lowest difficulty index whose percentile
    is k or more (None where none is). percentile() reads the rank back with a
    bisect. None when fewer than two puzzles are rated."""
    pairs = [(r["difficulty"]["index"], r["difficulty"]["percentile"]) for r in rows
             if isinstance(r.get("difficulty"), dict)
             and r["difficulty"].get("percentile") is not None
             and r["difficulty"].get("index") is not None]
    if not pairs:
        return None
    cuts = []
    for k in range(101):
        ok = [i for i, p in pairs if p >= k]
        cuts.append(min(ok) if ok else None)
    return cuts


def percentile(cuts, index):
    """The percentile of a difficulty index: the highest k with cuts[k] <= it."""
    if not cuts or index is None:
        return None
    best = None
    for k, c in enumerate(cuts):
        if c is not None and c <= index:
            best = k
    return best


def year_of(row):
    m = DATE.match(row.get("date") or "")
    if m:
        return m.group(1)
    return str(row["year"]) if isinstance(row.get("year"), int) else "none"


def shard_key(row):
    return f"{row['series']}/{year_of(row)}"


def compact_row(row, ctx):
    """The compact form of an index.json row. ctx: bands, basis, templates."""
    series, number = row["series"], row["number"]
    out = {"n": number}
    m = DATE.match(row.get("date") or "")
    if m:
        out["d"] = "".join(m.groups())
    elif isinstance(row.get("year"), int):
        out["d"] = row["year"]
    out["v"] = row["v"][:V_CHARS]
    if "setter" in row:
        out["s"] = row["setter"]
    rid = f"{series}-{number}"
    if row["id"] != rid:
        out["id"] = row["id"]
    if row["file"] != row["id"] + ".js":
        out["file"] = row["file"]
    t = ctx["templates"].get(series)
    if not (t and _render(t, number) == row["name"]):
        out["name"] = row["name"]
    if row["annotated"] is not True:
        out["a"] = 0 if row["annotated"] is False else row["annotated"]
    if row["hasSolutions"] is not True:
        out["h"] = 0 if row["hasSolutions"] is False else row["hasSolutions"]
    if row["solutionsUnofficial"] is not False:
        out["u"] = 1 if row["solutionsUnofficial"] is True else row["solutionsUnofficial"]
    df = row.get("difficulty")
    if "difficulty" not in row:
        out["nodf"] = 1
    elif df is not None:
        basis = df.get("basis") if isinstance(df, dict) else None
        if (isinstance(df, dict) and set(df) == DF_KEYS and df["band"] in ctx["bands"]
                and isinstance(basis, list) and basis == [f for f in ctx["basis"] if f in basis]
                and all(f in ctx["basis"] for f in basis)):
            mask = sum(1 << ctx["basis"].index(f) for f in basis)
            out["df"] = [ctx["bands"].index(df["band"]), df["index"], mask]
        else:
            out["df"] = df
    for k, v in row.items():
        if k not in HANDLED and k not in out:
            out[k] = v
    if "date" in row and not m:
        out["date"] = row["date"]
    if "year" in row and not (isinstance(row["year"], int) and not m):
        out["year"] = row["year"]
    return out


def expand_row(c, series, static, cuts=None):
    """The index.json row a compact row stands for (v and percentile aside)."""
    number = c["n"]
    rid = c.get("id", f"{series}-{number}")
    row = {"id": rid, "number": number, "series": series}
    t = static["templates"].get(series)
    row["name"] = c["name"] if "name" in c else _render(t, number)
    if "s" in c:
        row["setter"] = c["s"]
    d = c.get("d")
    if isinstance(d, str):
        row["date"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    elif d is not None:
        row["year"] = d
    row["file"] = c.get("file", rid + ".js")
    row["v"] = c["v"]
    row["annotated"] = c.get("a", True)
    row["annotated"] = False if row["annotated"] == 0 else row["annotated"]
    row["hasSolutions"] = c.get("h", True)
    row["hasSolutions"] = False if row["hasSolutions"] == 0 else row["hasSolutions"]
    row["solutionsUnofficial"] = True if c.get("u") == 1 else c.get("u", False)
    df = c.get("df")
    if isinstance(df, list):
        band, idx, mask = df
        basis = [f for i, f in enumerate(static["basis"]) if mask >> i & 1]
        df = {"band": static["bands"][band], "index": idx,
              "percentile": percentile(cuts, idx), "basis": basis}
    if "nodf" not in c:
        row["difficulty"] = df
    for k, v in c.items():
        if k not in {"n", "d", "v", "s", "id", "file", "name", "a", "h", "u", "df", "nodf", "k"}:
            row[k] = v
    return row


def build(index):
    """{relative path: text} of every file for this index."""
    rows = index["puzzles"] + index.get("unlisted", [])
    bands, basis = vocab(rows)
    ctx = {"bands": bands, "basis": basis, "templates": templates(rows)}
    shards = {}
    for r in rows:
        shards.setdefault(shard_key(r), []).append(compact_row(r, ctx))
    files, manifest, bundle = {}, {}, {}
    for key, compact in sorted(shards.items()):
        text = _dump(compact)
        manifest[key] = h = _hash(text)
        files[f"{key.replace('/', '-')}.{h}.json"] = text
        bundle[key] = compact
    static = {k: v for k, v in index.items()
              if k not in SKIP_KEYS | LIVE_KEYS}
    static.update(bands=bands, basis=basis, templates=ctx["templates"])
    static_text = ("// Generated by tools/index_idx.py from index.json — do not edit by hand.\n"
                   f"window.CRYPTIC_INDEX_STATIC = {_dump(static)};\n")
    sname = f"head-static.{_hash(static_text)}.js"
    files[sname] = static_text
    listed = index["puzzles"]
    counts = {"series": Counter(r["series"] for r in listed),
              "bands": Counter(r["difficulty"]["band"] for r in listed
                               if isinstance(r.get("difficulty"), dict)),
              "tags": Counter(t for r in listed for t in r.get("tags", []))}
    live = {k: index[k] for k in LIVE_KEYS if k in index}
    live.update(static=sname, percentileCuts=percentile_cuts(rows),
                recent=[dict(compact_row(r, ctx), k=r["series"]) for r in listed[:RECENT]],
                counts={k: dict(sorted(v.items())) for k, v in counts.items()},
                manifest=manifest)
    files["head-live.json"] = _dump(live)
    files[f"bundle.{_hash(_dump(manifest))}.json"] = _dump(bundle)
    return files


def write(index, puzzle_dir):
    """Write build(index) under puzzle_dir/idx and remove what it no longer
    names (an older shard). Returns {relative path: bytes written}."""
    root = Path(puzzle_dir) / "idx"
    files = build(index)
    sizes = {}
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
        sizes[rel] = len(data)
    for path in root.rglob("*"):
        if path.is_file() and path.relative_to(root).as_posix() not in files:
            path.unlink()
    return sizes
