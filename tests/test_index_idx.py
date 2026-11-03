#!/usr/bin/env python3
# Does tools/index_idx.py write files that decode back to index.json's rows?
#
#     python3 tests/test_index_idx.py
#
# Decodes the bundle (and every shard, and head-live's recent rows) of a
# synthetic index, and of puzzles/index.json when a reindex has written one,
# and compares each row field for field: `v` to its first 5 chars, and
# `percentile` within 1 (the cut points make it exact for a monotone rank).
import json
import os
import tempfile
from pathlib import Path

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: F401
import index_idx as ix


def row(series, number, date=None, year=None, name=None, df=None, **extra):
    r = {"id": f"{series}-{number}", "number": number, "series": series,
         "name": name or f"{series.title()} cryptic No {number:,}"}
    if date:
        r["date"] = date
    if year:
        r["year"] = year
    r.update(file=f"{series}-{number}.js", v="0123456789abcdef"[:8][::-1],
             annotated=True, hasSolutions=True, solutionsUnofficial=False, difficulty=df)
    r.update(extra)
    return r


def df(band, index, pct, basis):
    return {"band": band, "index": index, "percentile": pct, "basis": basis}


def synthetic():
    rows = [
        row("cryptic", 30105, "2026-10-31", df=df("hard", 2.5, 100, ["clue length", "rarity"])),
        row("cryptic", 30104, "2026-10-30", df=df("easy", 0.5, 0, ["rarity"]), annotated=False),
        row("cryptic", 30103, "2026-10-29", df=df("medium", 1.5, 50, ["rarity", "blog comments"])),
        row("genius", 281, "2026-10-01", name="Genius 281 special", setter="Hob",
            hasSolutions=False, solutionsUnofficial=True, tags=["big-grid"]),
        row("genius", 280, "2026-09-01", df=df("medium", 1.6, 75, ["blog comments", "rarity"])),
        row("penguin", 5, year=1998, name="Penguin book 5", clues={"present": 1, "total": 2}),
        row("odd", 7, "2020-01-01", id="odd-seven", file="odd.js"),
    ]
    rows[-1]["id"], rows[-1]["file"] = "odd-seven", "odd.js"
    unlisted = [dict(row("secret", 1, "2019-05-05", df=None), unlisted=True)]
    return {"latest": "cryptic-30105", "build": {"commit": "abc"}, "snitchRanges": {"hard": [1, 2]},
            "papers": {"cryptic": "Guardian"}, "groups": {"cryptic": "Guardian"},
            "tags": {"big-grid": "x"}, "puzzles": rows, "reprints": [{"id": "r-1"}],
            "unlisted": unlisted}


def same(want, got, label):
    want, got = dict(want), dict(got)
    assert want.pop("v")[:5] == got.pop("v"), label + ": v"
    wd, gd = want.get("difficulty"), got.get("difficulty")
    if wd and gd:
        assert abs(wd["percentile"] - gd["percentile"]) <= 1, label + ": percentile"
        want["difficulty"], got["difficulty"] = dict(wd, percentile=0), dict(gd, percentile=0)
    assert want == got, f"{label}:\n{want}\n{got}"


def check(index, label):
    with tempfile.TemporaryDirectory() as tmp:
        sizes = ix.write(index, tmp)
        root = Path(tmp) / "idx"
        assert {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} == set(sizes)
        live = json.loads((root / "head-live.json").read_text(encoding="utf-8"))
        text = (root / live["static"]).read_text(encoding="utf-8")
        static = json.loads(text.split("= ", 1)[1].rsplit(";", 1)[0])
        assert static["reprints"] == index["reprints"] and "latest" not in static
        assert live["latest"] == index.get("latest")
        bundle_name, = [n for n in sizes if n.startswith("bundle.")]
        bundle = json.loads((root / bundle_name).read_text(encoding="utf-8"))
        assert set(bundle) == set(live["manifest"])
        cuts = live["percentileCuts"]
        # every shard on disk is its manifest entry's bytes, hashed as named
        for key, h in live["manifest"].items():
            shard = json.loads((root / f"{key.replace('/', '-')}.{h}.json")
                               .read_text(encoding="utf-8"))
            assert shard == bundle[key]
        out = {}
        for key, compact in bundle.items():
            series = key.split("/")[0]
            for c in compact:
                r = ix.expand_row(c, series, static, cuts)
                out[r["id"]] = r
        want = {r["id"]: r for r in index["puzzles"] + index["unlisted"]}
        assert set(out) == set(want), label + ": ids"
        for rid, r in want.items():
            same(r, out[rid], f"{label} {rid}")
        recent = [ix.expand_row(c, c["k"], static, cuts) for c in live["recent"]]
        assert [r["id"] for r in recent] == [r["id"] for r in index["puzzles"][:ix.RECENT]]
        assert sum(live["counts"]["series"].values()) == len(index["puzzles"])
        return sizes


check(synthetic(), "synthetic")
# the cut points give the percentile of every rated index
cuts = ix.percentile_cuts(synthetic()["puzzles"])
assert [ix.percentile(cuts, i) for i in (0.5, 1.5, 1.6, 2.5)] == [0, 50, 75, 100]
assert len(cuts) == 101

real = Path("puzzles/index.json")
if real.exists():
    sizes = check(json.loads(real.read_text(encoding="utf-8")), "real")
    print(f"real index: {len(sizes)} files, {sum(sizes.values())} bytes")
print("ok")
