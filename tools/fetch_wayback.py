#!/usr/bin/env python3
"""Recover Guardian-hosted crosswords the Guardian no longer serves, from the
Wayback Machine.

Usage:
  python3 tools/fetch_wayback.py --series everyman --from 3550 --to 3560
  python3 tools/fetch_wayback.py --series cryptic --range 22000-22010
  python3 tools/fetch_wayback.py --series everyman --range 3550-3560 \\
      --out /tmp/somewhere --dry-run

Companion to fetch_puzzle.py and fetch_observer.py, for the numbers neither
of those can reach any more: everyman-4096-and-below (the Guardian pulled the
mirror when the Observer moved to Tortoise Media, see fetch_observer.py's
EARLIEST) and any Guardian cryptic whose own article page has since 404'd.
Both papers' article pages, when they existed, embedded the same crossword
JSON this reads; the Wayback Machine kept copies.

FETCH FORM. Only one URL shape works:
  https://web.archive.org/web/{YEAR}id_/https://www.theguardian.com/crosswords/{series}/{num}
"id_" tells Wayback to serve the page AS captured (no toolbar, no rewritten
links) and to pick whatever capture is nearest YEAR — it does not have to be
an exact hit. Wayback's own CDX and availability APIs 403/429 theguardian.com
and are not usable as a substitute; this direct form is the only door.

Responses are sometimes gzip-compressed on the wire; urllib does not
auto-decompress on read(), so a capture that happens to come back gzipped
silently mis-parses as garbage unless the magic bytes (1f 8b) are checked and
the body is gunzipped by hand — see maybe_gunzip.

PAGE FORMAT. The page carries an HTML attribute data-crossword-data="...".
Its value is the crossword JSON, HTML-escaped, followed immediately (inside
the same tag) by other attributes — so the attribute doesn't end at the
first literal '"' after it, and a naive [^"]* capture can end up short. This
reads everything up to the tag's own closing '>', HTML-unescapes it, then
cuts at the LAST '}' in that unescaped text: the JSON's own closing brace,
since ordinary HTML attribute values (classes, ids, urls) don't contain '}'.

SOLUTIONS. Everyman is a PRIZE puzzle: the Guardian withheld its solutions
for about a week even when it still hosted these, so the capture nearest
publication day has entries with no solutions. A later-year capture usually
does — YEAR=2023 was good for numbers 3550-3910 (measured); 4090 has
captures but was never seen solved even that late, so this walks a list of
years, escalating, and only accepts a capture where every entry has one.
Guardian cryptic solutions publish same-day (weekday) or ~1 week later
(Saturday prize), so the same escalation logic applies without extra cases.

A puzzle with any blank answer is never written — see has_full_solutions.

COVERAGE. Patchy in both directions and both series; a 404 just means "not
archived", never "does not exist" — measured samples: Everyman 3550-3910
came back solved; 3460 and below 404'd on every sample; Guardian cryptic
22000 came back fully solved, 22500 404'd. There is no boundary constant
here to encode because the two series' patchiness doesn't share one — walk
the range you want and read what actually skipped.

RATE LIMITING. web.archive.org throttles by IP; http_bytes (imported from
fetch_puzzle) already backs off on 429/5xx honouring Retry-After, but that
backoff is for when the throttle has already started. SLEEP_SECONDS is the
polite minimum between requests so it usually doesn't.

OUTPUT. Same file shape as every other fetcher here (see fetch_puzzle.convert
and write_puzzle_file) — this literally calls fetch_puzzle.convert() on the
recovered JSON, because the archived payload carries the same fields the live
CrosswordComponent props do (id, number, name, date, dimensions, entries[]
with position/length/clue/separatorLocations/solution, and creator when the
paper credited one). sourceUrl is therefore the ORIGINAL theguardian.com URL,
never the web.archive.org one; the schema convert() produces has no field for
an archive URL, so none is invented here — the archive URL a puzzle was
recovered from is only ever printed to stdout, not stored.

reindex() (puzzles/index.json + index.js) only runs when writing into the
real puzzle directory. Anything written to a --out override is a sample, not
part of the site, and must not touch the real index.
"""

import argparse
import gzip
import html
import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, convert, http_bytes,  # noqa: E402
                          reindex, write_puzzle_file)
import series as series_meta  # noqa: E402

WAYBACK_URL = ("https://web.archive.org/web/{year}id_/"
               "https://www.theguardian.com/crosswords/{series}/{num}")
SERIES_CHOICES = ("everyman", "cryptic")
# Escalating capture years to try per puzzle, oldest first, stopping at the
# first one whose entries are all solved. Everyman's prize window and the
# Guardian's own week-long withholding on Saturdays are both why the
# publication-day capture is the wrong one to want.
YEARS_TO_TRY = (2023, 2024, 2025, 2026)
SLEEP_SECONDS = 3
MARKER = 'data-crossword-data="'


def maybe_gunzip(raw):
    """A Wayback response is sometimes gzip on the wire regardless of what we
    asked for; urllib never decompresses it for us. Checked by magic bytes,
    not by trusting a Content-Encoding header we don't even have here —
    http_bytes returns only the body, and the previous attempt that trusted
    the header silently mis-parsed a capture as garbage."""
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def extract_crossword_data(page_html):
    """The crossword JSON out of a captured page's data-crossword-data
    attribute. See the module docstring for why this reads to the tag's own
    closing '>' rather than the first literal quote."""
    idx = page_html.find(MARKER)
    if idx == -1:
        raise ValueError("no data-crossword-data attribute in this capture")
    tag_end = page_html.find(">", idx)
    if tag_end == -1:
        raise ValueError("data-crossword-data attribute never closes")
    region = html.unescape(page_html[idx + len(MARKER):tag_end])
    cut = region.rfind("}")
    if cut == -1:
        raise ValueError("no closing brace found after data-crossword-data")
    return json.loads(region[:cut + 1])


def fetch_capture(series, num, year):
    """One Wayback capture's crossword JSON, plus the archive URL it came
    from (for logging only — see the module docstring on why that URL has
    nowhere to live in the puzzle schema)."""
    url = WAYBACK_URL.format(year=year, series=series, num=num)
    page = maybe_gunzip(http_bytes(url)).decode("utf-8", errors="replace")
    return extract_crossword_data(page), url


def has_full_solutions(data):
    entries = data.get("entries") or []
    return bool(entries) and all(e.get("solution") for e in entries)


def fetch_one(series, num, years=YEARS_TO_TRY):
    """Try each year in turn; return a converted puzzle dict for the first
    capture with every entry solved, or None if none qualified. Never raises
    on a 404 (not archived) — those are printed and skipped like every other
    fetcher's walk() does; anything else (a throttle after every retry, a
    malformed page) is printed and treated the same way rather than stopping
    the whole range for one bad number."""
    last_reason = "not archived in any year tried"
    for year in years:
        try:
            data, archive_url = fetch_capture(series, num, year)
        except urllib.error.HTTPError as err:
            last_reason = f"HTTP {err.code}"
            time.sleep(SLEEP_SECONDS)
            continue
        except Exception as err:  # noqa: BLE001 — one bad capture, not a stop
            last_reason = str(err)
            time.sleep(SLEEP_SECONDS)
            continue
        time.sleep(SLEEP_SECONDS)
        if not has_full_solutions(data):
            print(f"  {series}-{num} capture {year} ({archive_url}): "
                  f"no solutions in this capture — trying a later year")
            last_reason = "captured, but no solutions in any year tried"
            continue
        puzzle = convert(data)
        print(f"{series}-{num}: recovered from {archive_url} (capture year {year})")
        return puzzle
    print(f"SKIP {series}-{num}: {last_reason}")
    return None


def numbers_from_args(args):
    if args.range:
        lo, sep, hi = args.range.partition("-")
        if not sep:
            raise SystemExit(f"--range wants START-END, got {args.range!r}")
        return range(int(lo), int(hi) + 1)
    if args.from_ is None or args.to is None:
        raise SystemExit("give --range START-END, or both --from and --to")
    return range(args.from_, args.to + 1)


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--series", required=True, choices=SERIES_CHOICES)
    p.add_argument("--range", help="START-END, inclusive")
    p.add_argument("--from", dest="from_", type=int)
    p.add_argument("--to", type=int)
    p.add_argument("--year", type=int,
                    help="try only this capture year instead of escalating "
                         f"through {YEARS_TO_TRY}")
    p.add_argument("--dry-run", action="store_true",
                    help="fetch and report, but write nothing")
    p.add_argument("--out", type=Path, default=PUZZLE_DIR,
                    help="output directory (default: the repo's puzzles dir)")
    args = p.parse_args(argv)

    numbers = numbers_from_args(args)
    years = (args.year,) if args.year else YEARS_TO_TRY
    args.out.mkdir(parents=True, exist_ok=True)
    is_live_dir = args.out.resolve() == PUZZLE_DIR.resolve()

    recovered = skipped = already = 0
    for num in numbers:
        path = args.out / f"{series_meta.puzzle_id(args.series, num)}.js"
        if path.exists():
            print(f"skip {args.series}-{num}: already have {path}")
            already += 1
            continue
        puzzle = fetch_one(args.series, num, years)
        if puzzle is None:
            skipped += 1
            continue
        if args.dry_run:
            print(f"  DRY RUN — would write {path}")
        else:
            write_puzzle_file(path, puzzle, generator="tools/fetch_wayback.py")
            print(f"  wrote {path}")
        recovered += 1

    if recovered and not args.dry_run and is_live_dir:
        reindex()
    print(f"done: {recovered} recovered, {already} already on disk, "
          f"{skipped} unavailable (404 or no solutions in any year tried)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
