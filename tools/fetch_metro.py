#!/usr/bin/env python3
"""Fetch TODAY's Metro (UK) cryptic crossword and convert it to this app's
puzzle format.

Usage:
  python3 tools/fetch_metro.py            # fetch today's puzzle if not on disk
  python3 tools/fetch_metro.py --force    # re-fetch and overwrite today's file
  python3 tools/fetch_metro.py --latest   # same fetch, wired for daily_update.sh:
                                           # up-to-date <id> / exit 3 when nothing
                                           # new, else reindex() and print the id
  python3 tools/fetch_metro.py --wayback [--dry-run]
                                           # walk every Wayback Machine capture
                                           # of the live URL below and write
                                           # whatever day isn't on disk yet

There is exactly one live URL (metro.co.uk/puzzles/cryptic-crossword/) and it
always serves today's puzzle server-side — no date- or id-keyed URL exists —
so fetch_today() (bare invocation, --force, --latest) cannot backfill or
extend like tools/fetch_puzzle.py does; it can only ever get "today", whatever
day it is run. --wayback is the one exception: the Wayback Machine holds its
own independent captures of that same URL taken on past days, each still
carrying that day's `starting_puzzle` object, which is how it can recover
days fetch_today() never ran for. See backfill_wayback() below.

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
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (http_bytes, has_words, puzzle_path,  # noqa: E402
                          reindex, write_puzzle_file)
from fetch_wayback import maybe_gunzip, SLEEP_SECONDS  # noqa: E402 — shared Wayback plumbing
import series as series_meta  # noqa: E402 — for puzzle_id()/default_setter() only

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
URL = "https://metro.co.uk/puzzles/cryptic-crossword/"
SERIES = "metro"

# "id_" tells Wayback to serve a capture AS CAPTURED (no toolbar, no rewritten
# links) — see fetch_wayback.py's module docstring, which this reuses rather
# than re-deriving.
WAYBACK_CAPTURE_URL = "https://web.archive.org/web/{timestamp}id_/" + URL

# CDX is the Wayback Machine's own index of what it captured, queried directly
# rather than guessed at: collapse=digest drops a capture whose content hash
# matches the one immediately before it in time, so a page re-crawled several
# times in one day while nothing changed counts once. filter=statuscode:200
# excludes captures of an error response.
WAYBACK_CDX_URL = ("https://web.archive.org/cdx/search/cdx?url="
                    "metro.co.uk/puzzles/cryptic-crossword/&output=json"
                    "&fl=timestamp,digest,statuscode&filter=statuscode:200"
                    "&collapse=digest")


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
    # grid.pzlmap is absent on Metro pages from before it started shipping the
    # black-square mask alongside the clue items (only `items` existed then —
    # seen on Wayback captures, never on a live fetch). Without a mask there is
    # nothing independent to check the reconstructed grid against, so black and
    # light stay None and every check below keyed on them is skipped rather than
    # faked from data the page never sent.
    grid_field = gd.get("grid")
    pzlmap = grid_field.get("pzlmap") if grid_field else None
    if pzlmap is not None:
        if len(pzlmap) != rows * cols:
            raise SystemExit(f"pzlmap length {len(pzlmap)} != rows*cols {rows*cols}")
        black = {k for k, ch in enumerate(pzlmap) if ch == "*"}
        light = set(range(rows * cols)) - black
    else:
        black = light = None

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
        if black is not None and idx0 in black:
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
            if black is not None and cell in black:
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
    # grid we can't vouch for is worse than refusing to. Skipped when there was
    # no pzlmap to check against — the per-item crossing-conflict check above
    # is what's left to catch a bad start/dir reading in that case.
    if light is not None and set(grid.keys()) != light:
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
    path = puzzle_path(puzzle["series"], puzzle["number"])

    if path.exists() and not force:
        return puzzle, False

    PUZZLE_DIR.mkdir(exist_ok=True)
    write_puzzle_file(path, puzzle, generator="tools/fetch_metro.py")
    return puzzle, True


def http_bytes_patient(url):
    """http_bytes, retried past both a stalled read and an outage longer than
    http_bytes's own backoff covers.

    web.archive.org's CDX endpoint stalls mid-response often enough under
    this fetcher's load to matter: urllib raises that as a bare TimeoutError,
    not a urllib.error.URLError, so http_bytes's own HTTPError/URLError retry
    never sees it. Separately, CDX has been observed 503ing for minutes at a
    stretch — longer than http_bytes's own ~4.5 minutes of internal backoff —
    so a 503/429 that survives that internal retry is worth one more, slower,
    round here rather than giving up on what is otherwise a working query.
    """
    for wait in (30, 60, 120, 240, None):
        try:
            return http_bytes(url)
        except (TimeoutError, ConnectionError) as err:
            if wait is None:
                raise
            print(f"  {err} on {url} — waiting {wait}s")
            time.sleep(wait)
        except urllib.error.HTTPError as err:
            if wait is None or err.code not in (429, 503):
                raise
            print(f"  HTTP {err.code} (outlasted http_bytes's own retry) on {url} "
                  f"— waiting {wait}s")
            time.sleep(wait)


def wayback_snapshot_timestamps():
    """Every distinct Wayback capture timestamp of the live URL, oldest first
    (CDX returns rows in capture order; the first row is the field header)."""
    rows = json.loads(http_bytes_patient(WAYBACK_CDX_URL))[1:]
    return [row[0] for row in rows]


def fetch_wayback_snapshot(timestamp):
    """One archived capture's starting_puzzle data, by Wayback timestamp.

    maybe_gunzip (from fetch_wayback.py) undoes on-the-wire gzip the same way
    it does for Guardian captures — urllib never decompresses this for us,
    and archive.org applies it independently of what either fetcher asks for.
    """
    page = maybe_gunzip(http_bytes_patient(WAYBACK_CAPTURE_URL.format(timestamp=timestamp)))
    return extract_starting_puzzle(page.decode("utf-8", errors="replace"))


def backfill_wayback(dry_run=False):
    """Walk every Wayback capture of the live URL and write whichever day
    isn't on disk yet.

    Two different failure shapes are printed and skipped rather than stopping
    the walk, matching fetch_wayback.py's fetch_one(): a capture whose page
    has since changed shape past what extract_starting_puzzle/convert can
    read, and a capture that lands on a day already written (by an earlier
    capture in this same walk, or by a previous run). reindex() is not called
    here — see the module docstring on why --latest is the only mode that
    touches the site index.
    """
    written = already = failed = 0
    planned = set()  # paths already queued this run — dry-run never touches disk,
                      # so path.exists() alone can't catch a day two captures agree on
    for timestamp in wayback_snapshot_timestamps():
        try:
            data = fetch_wayback_snapshot(timestamp)
            date = publication_date(data)
        except SystemExit as err:
            print(f"SKIP {timestamp}: {err}")
            failed += 1
            continue

        number = int(date.strftime("%Y%m%d"))
        path = puzzle_path(SERIES, number)
        if path.exists() or path in planned:
            already += 1
        else:
            planned.add(path)
            try:
                puzzle = convert(data)
            except SystemExit as err:
                print(f"SKIP {timestamp} ({date}): {err}")
                failed += 1
                continue
            if dry_run:
                print(f"DRY RUN — would write {path}")
            else:
                PUZZLE_DIR.mkdir(exist_ok=True)
                write_puzzle_file(path, puzzle,
                                  generator="tools/fetch_metro.py --wayback",
                                  retrieved_url=WAYBACK_CAPTURE_URL.format(
                                      timestamp=timestamp))
                print(f"wrote {path}")
            written += 1

        time.sleep(SLEEP_SECONDS)

    print(f"done: {written} written, {already} already on disk, "
          f"{failed} failed to parse")
    return written


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

    if argv and argv[0] == "--wayback":
        backfill_wayback(dry_run="--dry-run" in argv[1:])
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
