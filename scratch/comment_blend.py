"""Stage 9: blend Times for the Times comment signals into the rating.

    nice -n 19 python3 scratch/comment_blend.py dump   # rows to ~/.cache/cryptic-blend-rows.json
    nice -n 19 python3 scratch/comment_blend.py test   # held out, both sets, Sunday, margin

The rule is fixed before it is measured (tools/difficulty.py blend()): a
puzzle with at least COMMENT_MIN_TIMES (3) stated solve times gets the mean of
its clue index's z and its comment signal's z, the comment signal being the
equal mean of the z of the log median stated minutes and the z of the DNF
share, every z against the puzzle's own series; the blend is restandardised
and put back on the scale of that series' clue index. Weights 1/2 and 1/4,
never fitted. A series with under 30 such puzzles is left alone.

Scored by scratch/snitch_stage4.py's heldout(): the annotated set under the
full index, the fresh (unannotated) set under the portable index, the Sunday
Times raw, each by date third. Leakage: the SNITCH and the comment minutes are
both solver times on the same puzzle, so the blend's gain over the index is
partly the target measured twice. "comments" is the comment signal alone, the
yardstick the blend must be read against: the index earns its keep in the
blend only where the blend beats that. The Times Quick Cryptic has comments
and no SNITCH; its check is the index against the comment signal.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scratch"))
import difficulty as D
import snitch_stage4 as S

S.CACHE = Path(os.environ.get("BLEND_ROWS") or Path.home() / ".cache" / "cryptic-blend-rows.json")


def dump():
    # The harness's own dump, without the WordNet candidates it screened.
    S.cand = lambda puz, facts: None
    S.dump()


def with_blend(rows, key, sel):
    """rows[r]["blend"], rows[r]["comments"] for base `key` over the rows `sel`
    picks; moments per series over those rows, as difficulty.py freezes them."""
    com = D.load_comments()
    vals = {r["pid"]: r[key] for r in rows if sel(r) and r.get(key) is not None}
    cm = D.comment_moments(vals, com)
    n = {}
    for r in rows:
        b = D.blend(r["pid"], r[key], com, cm) if r["pid"] in vals else None
        r["blend"] = r[key] if b is None else b
        c = D.comment_raw(com.get(r["pid"])) if r["pid"] in vals else None
        m = cm.get(r["pid"].rpartition("-")[0])
        r["comments"] = None if c is None or m is None else (
            (c[0] - m["log_minutes"]["mean"]) / m["log_minutes"]["sd"]
            + (c[1] - m["dnf"]["mean"]) / m["dnf"]["sd"]) / 2
        r["_blended"] = b is not None
        if b is not None:
            n[r["series"]] = n.get(r["series"], 0) + 1
    return n


def test():
    rows = json.loads(S.CACHE.read_text())
    for name, (bk, _, sel) in S.SETS.items():
        n = with_blend(rows, bk, sel)
        print(f"\n== {name} set: base {bk}; blended per series {n}")
        for series in ("times", "sundaytimes"):
            if name == "fresh" and series == "sundaytimes":
                continue
            for k in (bk, "blend", "comments"):
                print(f"  {series:12s} {k:9s} {S.fmt(S.heldout(rows, k, sel, series))}")
            # the blend against the index on only the puzzles it moved
            bl = lambda r, sel=sel: sel(r) and r["_blended"]
            for k in (bk, "blend", "comments"):
                print(f"  {series:12s} {k:9s} {S.fmt(S.heldout(rows, k, bl, series))}  (blended only)")
        if name == "annotated":
            for r in rows:
                r["_idx"] = r["index"]
            before = S.margin_of(rows)
            for r in rows:
                if r["index"] is not None:
                    r["index"] = r["blend"]
            print(f"  series-order margin {before:+.3f} -> {S.margin_of(rows):+.3f}")
            for r in rows:
                r["index"] = r["_idx"]
            qc = [r for r in rows if r["series"] == "timesquick" and r["comments"] is not None]
            if len(qc) >= 20:
                print(f"  timesquick (no SNITCH): index vs comment signal rho "
                      f"{D._spearman([r['index'] for r in qc], [r['comments'] for r in qc]):+.3f} (n={len(qc)})")
            tr = [r for r in rows if r["series"] == "times" and r["comments"] is not None]
            print(f"  times: index vs comment signal rho "
                  f"{D._spearman([r['index'] for r in tr], [r['comments'] for r in tr]):+.3f} (n={len(tr)})")


if __name__ == "__main__":
    {"dump": dump, "test": test}[sys.argv[1]]()
