#!/usr/bin/env python3
"""Fold each held Globe and Mail file into the Times Quick it reprints.

    python3 tools/fold_reprints.py             # fold every one listed pending
    python3 tools/fold_reprints.py --dry-run   # check them, write nothing
    python3 tools/fold_reprints.py 3150 3151   # those numbers alone

The Globe's No N is the Times Quick Cryptic No N (tools/reprints.py). Each
globeandmail-N in tools/data/reprints_pending.json becomes timesquick-N: the
Globe's grid, clues, answers and annotations, dated with the Times print
date off the timesforthetimes blog's grids.jsonl (a number the blog lacks
takes the next printing day after its predecessor, checked against its
successor), its own print kept as source.reprintedIn. A number whose answers
the blog's write-up contradicts is left pending and named. Each fold removes
its id from the pending list as it lands, so a stopped run resumes.
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
REKEYED = ("tools/data/yt_solvers/cryptics_uncovered_moments.json",
           "tools/data/yt_solvers/cryptics_uncovered_unstick.json",
           "tools/data/yt_solvers/cryptics_uncovered_parse_check.json",
           "tools/data/yt_solvers/cryptics_uncovered_solve_times.json",
           "tools/blog_facts_gold.jsonl")


def rekey(pairs):
    """Move every table row keyed by a folded id onto its original's id:
    {reprint id: original id}."""
    import re
    import blog_facts as bf
    import validate_annotations as va
    if not pairs:
        return
    root = TOOLS.parent
    # An id is a whole string ("globeandmail-3334") or leads one
    # ("globeandmail-3334 2-down MOSS").
    pattern = re.compile(r'"(%s)(?=[" ])' % "|".join(map(re.escape, pairs)))
    sub = lambda text: pattern.sub(lambda m: f'"{pairs[m.group(1)]}', text)  # noqa: E731
    for name in REKEYED:
        path = root / name
        path.write_text(sub(path.read_text(encoding="utf-8")), encoding="utf-8")
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


def drop_pending(pid):
    data = json.loads(reprints.PENDING_PATH.read_text(encoding="utf-8"))
    data["ids"] = [i for i in data["ids"] if i != pid]
    reprints.PENDING_PATH.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("numbers", nargs="*", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rekey", action="store_true", help="re-key the tables for NUMBERS folded already")
    a = ap.parse_args(argv)
    dates, answers = blog_quicks()
    todo = sorted((i for i in reprints.pending() if i.startswith("globeandmail-")),
                  key=lambda i: int(i.rsplit("-", 1)[1]))
    if a.numbers:
        todo = [i for i in todo if int(i.rsplit("-", 1)[1]) in a.numbers]
    folded, pairs = 0, {}
    for gid in todo:
        path = puzzle_paths.find(gid)
        if path is None:
            print(f"{gid}: no file", file=sys.stderr)
            continue
        globe = fetch_puzzle.read_puzzle_file(path)
        n = globe["number"]
        date = print_date(n, dates)
        if date is None:
            print(f"{gid}: no Times print date for Quick {n}", file=sys.stderr)
            continue
        if bad := contradicted(globe, answers.get(n, {})):
            print(f"{gid}: the blog's answers differ at {', '.join(bad)}", file=sys.stderr)
            continue
        oid = reprints.original_of(globe)
        if puzzle_paths.find(oid):
            print(f"{gid}: {oid} is held already; fold by hand", file=sys.stderr)
            continue
        if a.dry_run:
            folded += 1
            continue
        # The Globe file goes first: its clues are the original's, and the
        # write path refuses a second holder of them.
        path.unlink()
        puzzle_paths.shim_path(path).unlink(missing_ok=True)
        fetch_puzzle.clue_index().discard(gid)
        fetch_puzzle.write_puzzle_file(fetch_puzzle.puzzle_path(*series_meta.parse_id(oid)),
                                       reprints.as_original(globe, date),
                                       generator="tools/fetch_globeandmail.py")
        drop_pending(gid)
        pairs[gid] = oid
        folded += 1
        print(f"{gid} -> {oid} ({date})", flush=True)
    if "--rekey" in (argv or sys.argv):
        pairs.update({f"globeandmail-{n}": f"timesquick-{n}" for n in a.numbers})
    rekey(pairs)
    print(f"{'would fold' if a.dry_run else 'folded'} {folded} of {len(todo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
