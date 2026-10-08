#!/usr/bin/env python3
"""Fold each held reprint file into the puzzle it reprints.

    python3 tools/fold_reprints.py             # fold every one listed pending
    python3 tools/fold_reprints.py --dry-run   # check them, write nothing
    python3 tools/fold_reprints.py 3150 3151   # those numbers alone
    python3 tools/fold_reprints.py canberra-740702   # that id alone

The Globe's No N is the Times Quick Cryptic No N (tools/reprints.py). Each
globeandmail-N in tools/data/reprints_pending.json becomes timesquick-N: the
Globe's grid, clues, answers and annotations, dated with the Times print
date off the timesforthetimes blog's grids.jsonl (a number the blog lacks
takes the next printing day after its predecessor, checked against its
successor), its own print kept as source.reprintedIn. A number whose answers
the blog's write-up contradicts is left pending and named. Each fold removes
its id from the pending list as it lands, so a stopped run resumes.

Each canberra-N names the times-N it reprints in source.reprintOf. Where that
is held, the Canberra copy's answers, counts, missing words and annotated
clues go into it (reprints.merged); where not, the Canberra copy is filed as
it, dated by its own archive.org reading or else its dated neighbours'
numbering, held files and readings alike (undated where a holiday leaves
that open). A copy on another grid, answering a light otherwise, or naming an
original another pending file names too, is left pending and named. Nothing
is written unless every light of the reprint survives (reprints.lost).
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import downloads  # noqa: E402
import fetch_puzzle  # noqa: E402
import puzzle_paths  # noqa: E402
import reprints  # noqa: E402
import series as series_meta  # noqa: E402

BLOG = downloads.TIMESFORTHETIMES
SUNDAY = 6


def blog_quicks():
    """({number: {post dates}}, {number: {(light number, direction): answer}})."""
    dates, answers = {}, {}
    for line in (BLOG / "grids.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r["series"] == "Quick Cryptic" and r["number"]:
            dates.setdefault(r["number"], set()).add(r["date"])
    for line in (BLOG / "parsed.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("series") == "Quick Cryptic" and r.get("number"):
            answers[r["number"]] = {(e["number"], e["direction"]): e.get("answer")
                                    for e in r["entries"]}
    return dates, answers


def print_date(n, dates):
    """The Times print date of Quick No `n`, or None."""
    if len(dates.get(n, ())) == 1:
        return next(iter(dates[n]))
    before = dates.get(n - 1, ())
    if len(before) != 1:
        return None
    d = datetime.date.fromisoformat(next(iter(before))) + datetime.timedelta(days=1)
    if d.weekday() == SUNDAY:
        d += datetime.timedelta(days=1)
    after = dates.get(n + 1, ())
    if len(after) == 1 and (datetime.date.fromisoformat(next(iter(after))) - d).days not in (1, 2):
        return None
    return d.isoformat()


def contradicted(puzzle, blog):
    """The lights whose answer the blog's write-up gives otherwise."""
    return sorted(f"{k[0]}{k[1][0]}" for e in puzzle["entries"]
                  if (k := (e["number"], e["direction"])) in blog
                  and blog[k] and e.get("solution") != blog[k])


#: Tables keyed by puzzle id, whose rows follow a folded id to its original.
#: Their JSON is rewritten by key (json_merge.dump_lines).
REKEYED_BY_KEY = ("tools/data/source_clue_wrong.json",)
REKEYED = ("tools/data/yt_solvers/cryptics_uncovered_moments.json",
           "tools/data/yt_solvers/cryptics_uncovered_unstick.json",
           "tools/data/yt_solvers/cryptics_uncovered_parse_check.json",
           "tools/data/yt_solvers/cryptics_uncovered_solve_times.json",
           "tools/blog_facts_gold.jsonl")


def rekeyer(pairs):
    """The text substitution that renames {reprint id: original id}: an id is
    a whole string ("globeandmail-3334") or leads one
    ("globeandmail-3334 2-down MOSS", "canberra-750213/11-across")."""
    import re
    pattern = re.compile(r'"(%s)(?=[" /])' % "|".join(map(re.escape, pairs)))
    return lambda text: pattern.sub(lambda m: f'"{pairs[m.group(1)]}', text)


def rekey(pairs):
    """Move every table row keyed by a folded id onto its original's id:
    {reprint id: original id}."""
    import blog_facts as bf
    import validate_annotations as va
    if not pairs:
        return
    root = TOOLS.parent
    sub = rekeyer(pairs)
    for name in REKEYED:
        path = root / name
        path.write_text(sub(path.read_text(encoding="utf-8")), encoding="utf-8")
    from json_merge import dump_lines
    for name in REKEYED_BY_KEY:
        path = root / name
        rows = json.loads(sub(path.read_text(encoding="utf-8")), object_pairs_hook=unique_keys)
        path.write_text(dump_lines(rows), encoding="utf-8")
    ninas = root / "tools" / "data" / "ninas.json"
    ninas.write_text(json.dumps(json.loads(sub(ninas.read_text(encoding="utf-8"))),
                                indent=1, sort_keys=True) + "\n", encoding="utf-8")
    backlog = json.loads(sub(va.BACKLOG_PATH.read_text(encoding="utf-8")))
    va.BACKLOG_PATH.write_text(json.dumps(
        {k: v if k == "_why" else dict(sorted(v.items(), key=va._sort_key))
         for k, v in backlog.items()}, indent=1) + "\n")
    by_file = {}
    for path in bf.OUT.glob("*.json"):
        by_file[path] = dict(bf.file_rows(path))
    moved, touched = {}, set()
    for path, rows in by_file.items():
        for old in [k for k in rows if k in pairs]:
            moved[pairs[old]] = rows.pop(old)
            touched.add(path)
    for new, row in moved.items():
        path = bf.OUT / f"{series_meta.parse_id(new)[0]}.json"
        by_file.setdefault(path, {})[new] = row
        touched.add(path)
    for path in touched:
        rows = by_file[path]
        if rows:
            bf.rewrite_rows(path, sorted(rows.items()))
        else:
            path.unlink()


def unique_keys(pairs):
    """A JSON object's pairs as a dict, refusing a key twice: a folded id's
    row landing on a row its original holds already."""
    out = dict(pairs)
    if len(out) != len(pairs):
        dup = sorted({k for k, _ in pairs if sum(1 for j, _ in pairs if j == k) > 1})
        raise SystemExit(f"rekey would put two rows on {', '.join(dup)}: merge them by hand")
    return out


def printing_day(d, step):
    """The Times printing day (Monday to Saturday) `step` days on from `d`."""
    d += datetime.timedelta(days=step)
    return d + datetime.timedelta(days=step) if d.weekday() == SUNDAY else d


def times_dates(readings=downloads.ARCHIVE_ORG_SOURCE):
    """{number: print date} of the held Times cryptics and of the archive.org
    readings of Times editions (each dated by its scan), a held file's date
    winning."""
    out = {}
    paths = [*sorted(Path(readings).glob("times-*.json")),
             *puzzle_paths.PUZZLE_DIR.joinpath("times").glob("*/times-*.json")]
    for path in paths:
        try:
            p = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if p.get("date") and isinstance(p.get("number"), int):
            out[p["number"]] = p["date"]
    return out


def counted_date(n, dates):
    """Times No `n`'s print date: its own where `dates` holds it, else
    counted in printing days from the nearest dated numbers either side, or
    None where the two counts disagree (a holiday between them leaves it
    open)."""
    if n in dates:
        return dates[n]
    lo = max((k for k in dates if k < n), default=None)
    hi = min((k for k in dates if k > n), default=None)
    if lo is None or hi is None:
        return None
    fwd = datetime.date.fromisoformat(dates[lo])
    for _ in range(n - lo):
        fwd = printing_day(fwd, 1)
    back = datetime.date.fromisoformat(dates[hi])
    for _ in range(hi - n):
        back = printing_day(back, -1)
    return fwd.isoformat() if fwd == back else None


def fold_globe(gid, globe, ctx):
    """(original id, its puzzle, generator) for Globe file `gid`, or an
    error string."""
    if "blog" not in ctx:
        ctx["blog"] = blog_quicks()
    dates, answers = ctx["blog"]
    n = globe["number"]
    date = print_date(n, dates)
    if date is None:
        return f"no Times print date for Quick {n}"
    if bad := contradicted(globe, answers.get(n, {})):
        return f"the blog's answers differ at {', '.join(bad)}"
    oid = reprints.original_of(globe)
    if puzzle_paths.find(oid):
        return f"{oid} is held already; fold by hand"
    return oid, reprints.as_original(globe, date), "tools/fetch_globeandmail.py"


def read_as(oid, claimants):
    """The one of `claimants` (pending ids naming `oid`) whose clues the
    archive.org reading of `oid` shares, by match_canberra's measure, or None
    when none or several do."""
    import file_archive_org_puzzles as aorg
    path = aorg.SOURCE / f"{oid}.json"
    if not path.exists():
        return None
    reading = aorg.shingles(json.loads(path.read_text(encoding="utf-8")))
    sure = []
    for cid in claimants:
        mine = aorg.shingles(fetch_puzzle.read_puzzle_file(puzzle_paths.find(cid)))
        if mine and len(mine & reading) >= aorg.MATCH_SHARE * min(len(mine), len(reading)):
            sure.append(cid)
    return sure[0] if len(sure) == 1 else None


def fold_canberra(cid, canberra, ctx):
    """(original id, its puzzle, generator) for Canberra file `cid`, or an
    error string."""
    oid = reprints.original_of(canberra)
    if oid is None:
        return "no source.reprintOf"
    if "claims" not in ctx:
        ctx["claims"] = {}
        for other in reprints.pending():
            if other.startswith("canberra-") and (path := puzzle_paths.find(other)):
                o = reprints.original_of(fetch_puzzle.read_puzzle_file(path))
                ctx["claims"].setdefault(o, []).append(other)
    if len(rivals := ctx["claims"].get(oid, [])) > 1 and read_as(oid, rivals) != cid:
        return f"{oid} is claimed by {', '.join(sorted(rivals))} too: name the true original by hand"
    if path := puzzle_paths.find(oid):
        held = fetch_puzzle.read_puzzle_file(path)
        if why := reprints.mismatch(held, canberra):
            return f"not {oid}'s print: {why}"
        return oid, reprints.merged(held, canberra), None
    if "dates" not in ctx:
        ctx["dates"] = times_dates()
    date = counted_date(series_meta.parse_id(oid)[1], ctx["dates"])
    return oid, reprints.as_original(canberra, date), "tools/file_trove_puzzles.py"


FOLDERS = {"globeandmail": fold_globe, "canberra": fold_canberra}


def drop_pending(pid):
    data = json.loads(reprints.PENDING_PATH.read_text(encoding="utf-8"))
    data["ids"] = [i for i in data["ids"] if i != pid]
    reprints.PENDING_PATH.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("which", nargs="*", help="pending ids, or Globe and Mail numbers")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rekey", action="store_true",
                    help="re-key the tables for the Globe and Mail WHICH folded already")
    a = ap.parse_args(argv)
    named = {w if "-" in w else f"globeandmail-{w}" for w in a.which}
    todo = sorted((i for i in reprints.pending() if series_meta.parse_id(i)[0] in FOLDERS),
                  key=lambda i: series_meta.parse_id(i))
    if named:
        todo = [i for i in todo if i in named]
    folded, ctx = 0, {}
    for rid in todo:
        path = puzzle_paths.find(rid)
        if path is None:
            print(f"{rid}: no file", file=sys.stderr)
            continue
        reprint = fetch_puzzle.read_puzzle_file(path)
        got = FOLDERS[series_meta.parse_id(rid)[0]](rid, reprint, ctx)
        if isinstance(got, str):
            print(f"{rid}: {got}", file=sys.stderr)
            continue
        oid, original, generator = got
        if gone := reprints.lost(reprint, original):
            print(f"{rid}: {oid} would lose {', '.join(gone)}", file=sys.stderr)
            continue
        if a.dry_run:
            folded += 1
            print(f"{rid} -> {oid} ({'merge' if puzzle_paths.find(oid) else 'file'})")
            continue
        # The reprint file goes first: its clues are the original's, and the
        # write path refuses a second holder of them.
        merge = puzzle_paths.find(oid) is not None
        shim = puzzle_paths.shim_path(path)
        kept = {f: f.read_bytes() for f in (path, shim) if f.exists()}
        path.unlink()
        shim.unlink(missing_ok=True)
        fetch_puzzle.clue_index().discard(rid)
        try:
            fetch_puzzle.write_puzzle_file(fetch_puzzle.puzzle_path(*series_meta.parse_id(oid)),
                                           original, generator=generator)
        except Exception as e:
            for f, data in kept.items():
                f.write_bytes(data)
            print(f"{rid}: {oid} refused, {rid} put back: {e}", file=sys.stderr)
            continue
        if gone := reprints.lost(reprint, fetch_puzzle.read_puzzle_file(puzzle_paths.find(oid))):
            raise SystemExit(f"{rid}: the write of {oid} lost {', '.join(gone)}; "
                             f"restore {rid} from git")
        drop_pending(rid)
        rekey({rid: oid})
        folded += 1
        print(f"{rid} -> {oid} ({'merged' if merge else 'filed'}, {original.get('date', 'undated')})", flush=True)
    if a.rekey:
        rekey({i: reprints.original_of({"id": i, "number": series_meta.parse_id(i)[1]})
               for i in named if series_meta.parse_id(i)[0] in reprints.REPRINTS})
    print(f"{'would fold' if a.dry_run else 'folded'} {folded} of {len(todo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
