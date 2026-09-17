#!/usr/bin/env python3
"""Fetch TODAY's Metro (UK) cryptic crossword and convert it to this app's
puzzle format.

Usage:
  python3 tools/fetch_metro.py           # fetch today's puzzle if not on disk
  python3 tools/fetch_metro.py --force   # re-fetch and overwrite today's file
  python3 tools/fetch_metro.py --latest  # same fetch, wired for daily_update.sh:
                                          # up-to-date <id> / exit 3 when nothing
                                          # new, else reindex() and print the id

There is exactly one URL (metro.co.uk/puzzles/cryptic-crossword/) and it always
serves today's puzzle server-side — no archive, no date- or id-keyed URL exists
— so this fetcher cannot backfill or extend like tools/fetch_puzzle.py does; it
can only ever get "today", whatever day it is run.

The puzzle's own id (pml_id) is an opaque token that cannot be verified across
days, so puzzles are keyed by their publication date instead, taken from the
page's own `rdate` field (e.g. "17 Sep 2026") rather than the machine's clock —
the page is UK-served and the fetching machine's notion of "today" can be a day
off near UK midnight. The id is metro-YYYYMMDD: a single digit run, not
YYYY-MM-DD with internal hyphens, because every other id in this codebase is
`<series>-<number>` split on the LAST hyphen (series.puzzle_id / parse_id,
asserted by tools/smoke_test.js as `^[a-z]+-\\d+$`) — a hyphenated date would
parse as series "metro-2026-09" number "17". YYYYMMDD keeps the id
date-derived and sortable while staying a plain integer, so it also sorts
correctly against every other series' number in tools/fetch_puzzle.py's
reindex() without a str/int comparison crash.

Bare invocation and --force write only the one puzzle file and never touch
puzzles/index.* — same as every other fetcher's single-puzzle commands, so a
one-off manual fetch doesn't also rebuild the site's index. --latest is the
exception, because it's the one daily_update.sh actually drives: it calls the
shared reindex() on success, matching the contract every other fetcher's
--latest honours (exit 3 + "up-to-date <id>" for nothing new, exit 0 + a
reindex + the bare id for a new puzzle).
"""

import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import http_bytes, has_words, reindex, write_puzzle_file  # noqa: E402
import series as series_meta  # noqa: E402 — for puzzle_id()/default_setter() only

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
URL = "https://metro.co.uk/puzzles/cryptic-crossword/"
SERIES = "metro"


def http_get(url):
    return http_bytes(url).decode("utf-8")


def extract_starting_puzzle(page_html):
    """Pull the `starting_puzzle: {...}` object literal out of the page and
    parse it as JSON.

    It sits inside a plain <script> tag as an argument to a JS function call
    (pml.startGame('dmg-puzzle', { ... starting_puzzle: {...} ... })), not as
    its own assignment or a <script type="application/json"> block, so there
    is no closing marker to regex for and no surrounding syntax to strip.
    Brace-matching from the opening `{` — respecting quoted strings so a `}`
    inside a clue's text can't end the object early — is the only way to find
    the real end.
    """
    m = re.search(r"starting_puzzle\s*:\s*", page_html)
    if not m:
        raise SystemExit("starting_puzzle not found in page — Metro changed its markup")
    i = m.end()
    if page_html[i] != "{":
        raise SystemExit(f"expected '{{' after starting_puzzle:, found {page_html[i:i+20]!r}")
    start = i
    depth = 0
    in_str = False
    esc = False
    quote = None
    while True:
        c = page_html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
        else:
            if c in "\"'":
                in_str = True
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
        i += 1
        if i >= len(page_html):
            raise SystemExit("ran off the end of the page brace-matching starting_puzzle")
    return json.loads(page_html[start:i])


# Metro's date, e.g. "17 Sep 2026" — %b is locale-sensitive on some platforms
# for parsing, but always accepts English abbreviations, which is what Metro
# sends regardless of where this runs.
RDATE_FORMAT = "%d %b %Y"


def publication_date(data):
    """The puzzle's publication date, from the page's own `rdate` field.

    Preferred over the fetching machine's clock: the page is UK-served and
    always "today's" puzzle by the SITE's clock, and a fetch run close to UK
    midnight from another timezone (or a slow/cached response) could disagree
    with the machine's own idea of today. `rdate` is what Metro itself says
    this puzzle is for.
    """
    rdate = data.get("rdate")
    if not rdate:
        raise SystemExit("no rdate on starting_puzzle — cannot date this puzzle")
    return datetime.datetime.strptime(rdate, RDATE_FORMAT).date()


def convert(data):
    """Metro's starting_puzzle -> our puzzle object (annotation: null throughout)."""
    gd = data["game_data"]
    rows, cols = gd["rows"], gd["cols"]
    pzlmap = gd["grid"]["pzlmap"]
    if len(pzlmap) != rows * cols:
        raise SystemExit(f"pzlmap length {len(pzlmap)} != rows*cols {rows*cols}")
    black = {k for k, ch in enumerate(pzlmap) if ch == "*"}
    light = set(range(rows * cols)) - black

    entries = []
    grid = {}  # cell index -> letter, built alongside entries as a cross-check
    for item in gd["items"]:
        # `start` is documented nowhere and was checked against this sample:
        # it is 1-BASED (start-1 lands on the item's own cell; start unmodified
        # lands one cell past it, sometimes onto a black square, sometimes into
        # the next entry — confirmed by brute-forcing offsets -1/0/+1 against
        # the mask until every entry's letters exactly filled every light cell
        # with zero crossing conflicts, which only happens at offset -1).
        idx0 = item["start"] - 1
        direction = "across" if item["dir"] == 0 else "down"  # dir 1 verified as down the same way
        answer = re.sub(r"[^A-Z]", "", item["answer"].upper())
        length = len(answer)
        row, col = divmod(idx0, cols)
        if idx0 in black:
            raise SystemExit(f"item {item['num']} {direction} starts on a black cell ({row},{col})")
        if direction == "across":
            cells = [idx0 + k for k in range(length)]
            if col + length > cols:
                raise SystemExit(f"item {item['num']} across runs past the row edge")
        else:
            cells = [idx0 + k * cols for k in range(length)]
            if row + length > rows:
                raise SystemExit(f"item {item['num']} down runs past the column edge")
        for cell in cells:
            if cell in black:
                raise SystemExit(f"item {item['num']} {direction} crosses a black cell")
            if cell in grid and grid[cell] != answer[cells.index(cell)]:
                raise SystemExit(f"item {item['num']} {direction} conflicts with another "
                                  f"entry's letter at cell {cell}")
        for cell, ch in zip(cells, answer):
            grid[cell] = ch

        clue = item["clue"].strip()
        entries.append({
            "id": f"{item['num']}-{direction}",
            "number": item["num"],
            "direction": direction,
            "position": {"x": col, "y": row},
            "length": length,
            "clue": clue,
            **({} if has_words(clue) else {"clueMissing": True}),
            "separatorLocations": {},  # Metro ships none; enumeration stays in the clue text
            "solution": answer,
            "annotation": None,
        })

    # The strongest available check that start/dir/pzlmap were read correctly
    # for THIS day's puzzle: every light cell got exactly one letter and no
    # light cell was left over. Anything else means today's puzzle broke an
    # assumption verified only against the one saved sample, and writing a
    # grid we can't vouch for is worse than refusing to.
    if set(grid.keys()) != light:
        missing = sorted(light - set(grid.keys()))
        extra = sorted(set(grid.keys()) - light)
        raise SystemExit(f"grid reconstruction mismatch — missing cells {missing[:10]}, "
                          f"unexpected filled cells {extra[:10]}")

    wordless = [e["id"] for e in entries if not has_words(e["clue"])]
    if wordless:
        print("WARNING: published with no clue text: " + ", ".join(wordless), file=sys.stderr)

    entries.sort(key=lambda e: (e["position"]["y"], e["position"]["x"], e["direction"]))

    date = publication_date(data)
    number = int(date.strftime("%Y%m%d"))
    epoch_millis = int(datetime.datetime(
        date.year, date.month, date.day, tzinfo=datetime.timezone.utc
    ).timestamp() * 1000)

    return {
        "id": series_meta.puzzle_id(SERIES, number),
        "number": number,
        "series": SERIES,
        "name": f"Metro cryptic crossword, {date.day} {date.strftime('%B %Y')}",
        # "metro" isn't in tools/series.py's SERIES table yet (that's the main
        # session's job when it registers this series). Until it is, meta()
        # falls back to the cryptic entry, which has no "setter" key either —
        # so this returns "Unknown" today for the right reason (Metro's feed
        # names no setter) and will pick up a real default automatically the
        # day someone adds one for "metro", with no change needed here.
        "setter": series_meta.default_setter(SERIES),
        "date": epoch_millis,
        "dimensions": {"cols": cols, "rows": rows},
        "sourceUrl": URL,
        # Provenance, not identity — see the module docstring for why the id
        # is date-keyed instead. Harmless extra key for every other tool here:
        # each reads named fields off the puzzle dict and ignores the rest.
        "pmlId": data.get("pml_id"),
        "entries": entries,
    }


def fetch_today(force=False):
    """Fetch whatever Metro is currently serving as "today's" puzzle.

    The one fetch-one function every entry point below shares. Returns
    (puzzle, is_new): is_new is False, and nothing is written, when the file
    already exists and force wasn't given.

    Nothing here walks back a few days the way fetch_independent.py's --latest
    does: there is only ever one URL and it only ever answers for "today" by
    Metro's own clock, so there is no earlier day this feed could be asked
    for. That skew is already handled one layer down — publication_date()
    dates the puzzle from the page's own rdate field rather than the fetching
    machine's clock, which is the whole reason the equivalent walk isn't
    needed here.
    """
    page = http_get(URL)
    data = extract_starting_puzzle(page)
    puzzle = convert(data)
    path = PUZZLE_DIR / f"{puzzle['id']}.js"

    if path.exists() and not force:
        return puzzle, False

    PUZZLE_DIR.mkdir(exist_ok=True)
    write_puzzle_file(path, puzzle, generator="tools/fetch_metro.py")
    return puzzle, True


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if argv and argv[0] == "--latest":
        puzzle, is_new = fetch_today()
        if not is_new:
            print(f"up-to-date {puzzle['id']}")
            return 3
        reindex()
        print(puzzle["id"])
        return 0

    force = "--force" in argv
    puzzle, is_new = fetch_today(force=force)
    if not is_new:
        print(f"up-to-date {puzzle['id']}")
        return 3
    print(f"fetched {puzzle['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
