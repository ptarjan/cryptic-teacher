#!/usr/bin/env python3
"""app.js's rung ladder and series blurbs, read out of app.js.

app.js is a browser file with no build step, so for the tables that live only
there it stays the source and the tools parse it rather than keep a copy. The
clue types and families are not here: they live in tools/data/clue_types.json,
which app.js and tools/clue_types.py both read.

    python3 tools/app_tables.py        # print the ladder and the series blurbs

If a parse comes back empty the table has moved or changed shape, and every
caller raises rather than quietly working from an empty table.
"""
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app.js"
# A count or a puzzle number: three digits or more, or digits grouped by a comma.
# Grid sizes (13x13) and a place in a book (No 18) stay writable.
COUNT = re.compile(r"\d[\d,]*\d{2}|\d,\d")


def _block(src, opener, closer):
    if opener not in src:
        raise SystemExit(f"app_tables: {APP.name} has no `{opener}` — the table "
                         f"moved or changed shape, and nothing else has a copy "
                         f"of it to fall back on.")
    return src.split(opener, 1)[1].split(closer, 1)[0]


def ladder(src=None):
    """[(rung key, button label), ...] in the order the app numbers the rungs.

    `LABELS` in app.js is written in ladder order and app.js sorts the rungs by
    `Object.keys(LABELS)`, so the map's key order is the order — the whole of it,
    with no second list anywhere to disagree. Every tool that needs to know which
    rung is first reads it from here; three of them used to keep a list of their
    own, and `tools/rung_report.py` was reporting a solver who took one rung as
    having climbed three.
    """
    src = src if src is not None else APP.read_text(encoding="utf-8")
    if not re.search(r"const RUNG_ORDER = Object\.keys\(LABELS\);", src):
        raise SystemExit("app_tables: app.js no longer orders the ladder by "
                         "`Object.keys(LABELS)`, so LABELS' key order is no "
                         "longer the ladder's order. Put the order back in "
                         "LABELS rather than in a list beside it.")
    out = re.findall(r'(\w+):\s*"([^"]+)"', _block(src, "const LABELS = {", "\n    };"))
    if not out:
        raise SystemExit("app_tables: LABELS parsed empty")
    return out


def series_blurbs(src=None):
    """{series key: the sentence app.js's picker shows about that series}."""
    src = src if src is not None else APP.read_text(encoding="utf-8")
    block = _block(src, "const SERIES_BADGE = {", "\n  };")
    out = {k: re.sub(r"\s+", " ", v).strip() for k, v in
           re.findall(r'^\s{4}(\w+): \["[^"]*",\s*`([^`]*)`\]', block, re.M)}
    if not out:
        raise SystemExit("app_tables: SERIES_BADGE parsed empty")
    for key, blurb in out.items():
        if m := COUNT.search(blurb):
            raise SystemExit(f"app_tables: SERIES_BADGE.{key} says {m.group(0)!r}. A blurb "
                             "says what the series is like, never how many puzzles or "
                             "issues it has: we hold part of each archive, so a count "
                             "describes our shelf, and a puzzle number goes stale.")
    return out


def main():
    print(" -> ".join(f"{i}. {label}" for i, (_, label) in enumerate(ladder(), 1)))
    print()
    for key, blurb in series_blurbs().items():
        print(f"{key}\n  {blurb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
