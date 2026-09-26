#!/usr/bin/env python3
"""File the Telegraph grids rebuilt from bigdave44.com into puzzles/.

    python3 tools/file_telegraph_puzzles.py              # file every row not yet filed
    python3 tools/file_telegraph_puzzles.py --dry-run    # count what it would do
    python3 tools/file_telegraph_puzzles.py --newest 50  # the newest 50 of each series

Reads `tools/times_grids.py --blog bigdave44`'s grids.jsonl and the records
tools/parse_bigdave44.py writes beside it, and files them through
tools/file_blog_puzzles.py, which says what a row must pass. The parser has
already settled what is the Telegraph's: each record names its series key,
its setter (or null: the back-page cryptic prints none) and its print date
(or null where no post proves one), so this only hands them on.
"""
import argparse
import collections
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_wp_blog
import file_blog_puzzles
import parse_bigdave44
import series as series_meta

CACHE = fetch_wp_blog.BLOGS["bigdave44"].cache


def print_dates(recs, renumbered):
    """The parser's print dates, keyed by the number each post is filed under.
    A post the filer renumbered was undated under its typed number, so the
    paper's cadence is run again once it holds its real one."""
    by_series = collections.defaultdict(dict)
    for rec in recs:
        number = renumbered.get(rec["post_id"], rec["number"])
        day = rec.get("printed") and datetime.date.fromisoformat(rec["printed"])
        by_series[rec["series"]].setdefault(number, None)
        by_series[rec["series"]][number] = by_series[rec["series"]][number] or day
    dates = {}
    for series, known in by_series.items():
        known.update(parse_bigdave44.by_cadence(series, known))
        dates.update({(series, n): d for n, d in known.items() if d})
    return dates, []


SOURCE = file_blog_puzzles.Source(
    tool="tools/file_telegraph_puzzles.py",
    # Undated means null, never the post date: the parser already read the
    # post date wherever it is the print date.
    target=lambda row: (row["series"], False),
    print_dates=print_dates,
    setter=lambda rec, series: rec.get("setter") or series_meta.default_setter(series))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--newest", type=int, help="file at most N per series, newest first")
    ap.add_argument("--grids", type=Path, default=CACHE / "grids.jsonl")
    ap.add_argument("--parsed", type=Path, default=CACHE / "parsed.jsonl")
    args = ap.parse_args(argv)
    file_blog_puzzles.run(SOURCE, args.grids, args.parsed, write=not args.dry_run,
                          newest=args.newest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
