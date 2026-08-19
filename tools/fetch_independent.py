#!/usr/bin/env python3
"""Fetch an Independent cryptic crossword and convert it to this app's format.

Usage:
  python3 tools/fetch_independent.py --latest        # newest published day
  python3 tools/fetch_independent.py 260805          # one day, YYMMDD
  python3 tools/fetch_independent.py --backfill [N]  # the last N days (default 30),
                                                     # skipping days already on disk
  python3 tools/fetch_independent.py --sundays [N]   # the last N Sundays (default 52)
  python3 tools/fetch_independent.py --check         # is the feed still there?

One feed, two series: the daily Monday–Saturday and the Independent on Sunday's
own weekly sequence. See DAILY_MIN for how a file is told which it is.

Companion to fetch_puzzle.py, which does the Guardian. Separate module rather
than another SERIES entry there because nothing is shared but the output shape:
the Guardian ships JSON embedded in an article page, the Independent ships
Crossword Compiler XML from a CDN. The two converters have no code in common,
and pretending otherwise would have meant a fetcher full of "if series ==".

WHERE THIS FEED CAME FROM (2026-08-05). Paul asked for the Times; the Times
sends a signed-out browser no puzzle data at all, so we went looking for free
broadsheet cryptics instead. The Independent's puzzle is an Arkadium-hosted
game, and watching the page load tells you nothing — the grid arrives inside
the game engine's own code, not as a visible fetch. The endpoint is declared in
the *engine* bundle (arenaxstorage-blob/arenax-games/independentCrypticCrossword),
not in the page's wrapper bundle, which is only ads and analytics:

    {"puzzle": {"feedUrl": "//ams.cdn.arkadiumhosted.com/assets/gamesfeed/"
                           "independent/daily-crossword/",
                "prefix": "c_", "dateFormat": "YYMMDD", "postfix": ".xml"}}

So the feed is keyed by DATE, not by puzzle number — there is no way to ask for
"No. 12,426" directly, which is why everything here counts in days and the
puzzle number is read back out of the file. It needs no auth, no cookies and no
referer; plain curl works. Verified reachable back to 2020-01-01.

Writes puzzles/<series>-<number>.js (preserving any existing per-clue
annotations), then rebuilds the index via fetch_puzzle.reindex().
"""

import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, UA, flatten_clue,  # noqa: E402
                          merge_annotations, puzzle_files, read_puzzle_file,
                          reindex, write_puzzle_file)
import series as series_meta  # noqa: E402

FEED = ("https://ams.cdn.arkadiumhosted.com/assets/gamesfeed/independent/"
        "daily-crossword/c_{ymd}.xml")
# Where a reader would go to play it. Per-puzzle URLs don't exist — the game
# always serves "today" — so every puzzle points at the same page. Better than
# an empty sourceUrl: it still credits the publisher and shows where it's from.
PLAY_URL = "https://puzzles.independent.co.uk/games/cryptic-crossword-independent/"
NS = "{http://crossword.info/xml/rectangular-puzzle}"

# This one feed carries TWO series. Monday–Saturday it is the Independent daily
# cryptic, numbered ~12,400 and climbing by one a day. On Sundays it serves the
# Independent on Sunday cryptic, a separate weekly sequence numbered ~1,900.
#
# Which one a file holds is decided by its number, because the feed says nothing
# else about it — same XML, same 15x15 grid, same setters, and the date is the
# only other clue, which would make a bank holiday shuffle silently mislabel a
# puzzle. The threshold is safe for a century and a half: the Sunday sequence
# gains 52 a year from 1,903, the daily 313 a year from 12,438.
#
# Sundays were skipped entirely until 2026-08-19, and the reason was ids: they
# were bare numbers, so Sunday No 1,395 would have collided with Guardian Quiptic
# No 1,395 in the mid-2030s and one would have overwritten the other's file.
# Ids carry their series now, so the collision cannot happen and the reason is
# gone.
DAILY_MIN = 10000


def series_for(number):
    return "independent" if number >= DAILY_MIN else "indysunday"


def http_get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read()


def inner_xml(el):
    """An element's content with its child markup intact.

    Only so that plain_text() can take it straight back out again — the tags
    are how the space between "Case for" and an italicised "Turandot" survives
    the walk, and the stored clue is text, not HTML. See fetch_puzzle.plain_text
    for why keeping the markup was tried and abandoned.
    """
    parts = [el.text or ""]
    for child in el:
        tag = child.tag.split("}")[-1]
        parts.append(f"<{tag}>{inner_xml(child)}</{tag}>{child.tail or ''}")
    # No .strip() here, deliberately: the recursion runs on every nested element,
    # and the space before an italicised title lives at the END of the <span>
    # before it. Stripping inside welds "Nashville for" onto "American Idol".
    return "".join(parts)


def span(attr):
    """"1-5" -> (1, 5); "7" -> (7, 7). Cell coordinates are 1-based here."""
    lo, _, hi = attr.partition("-")
    return int(lo), int(hi or lo)


def separators(fmt, lengths):
    """Guardian-style separatorLocations from a Crossword Compiler `format`.

    "4,2,3" over one 9-letter entry -> [{",": [4, 6]}]; the final boundary is
    the end of the answer and is not a separator. For a linked clue the offsets
    are split across the entries and re-based on each one, which is what the
    Guardian's own data does: "4,3,5,5" over TURNTHE + OTHERCHEEK becomes
    {",": [4, 7]} and {",": [5]}.
    """
    out = [{} for _ in lengths]
    pos, at = 0, 0
    for piece in re.split(r"([,\-])", fmt or ""):
        if piece in (",", "-"):
            # Which entry does this boundary fall in? The last one that ends at
            # or after it, so a separator sitting exactly on an entry boundary
            # is recorded on the entry that ends there.
            end = 0
            for i, n in enumerate(lengths):
                end += n
                if pos <= end:
                    out[i].setdefault(piece, []).append(pos - (end - n))
                    break
        elif piece:
            pos += int(piece)
            at += 1
    return out


def parse(xml_bytes, ymd):
    root = ET.fromstring(xml_bytes)
    puz = root.find(f".//{NS}rectangular-puzzle")
    title = (puz.findtext(f"{NS}metadata/{NS}title") or "").strip()
    m = re.match(r"No\.?\s*([\d,]+)\s*(?:by\s*(.+))?$", title)
    if not m:
        raise ValueError(f"unrecognised title {title!r}")
    number = int(m.group(1).replace(",", ""))
    setter = (m.group(2) or "").strip() or "Unknown"

    grid = puz.find(f"{NS}crossword/{NS}grid")
    cols, rows = int(grid.get("width")), int(grid.get("height"))
    letters = {}
    for cell in grid.findall(f"{NS}cell"):
        if cell.get("solution"):
            letters[(int(cell.get("x")), int(cell.get("y")))] = cell.get("solution")

    # word id -> the cell runs it covers, in reading order. Usually one run; a
    # linked clue ("10/24") is one <word> with the second run as a <cells>
    # child, and each run becomes its own entry sharing a group.
    runs = {}
    for word in puz.findall(f"{NS}crossword/{NS}word"):
        segs = [word] + word.findall(f"{NS}cells")
        runs[word.get("id")] = [(span(s.get("x")), span(s.get("y"))) for s in segs]

    entries = []
    for clues in puz.findall(f"{NS}crossword/{NS}clues"):
        for clue in clues.findall(f"{NS}clue"):
            # "See 10" stubs carry no text of their own and no format; the
            # entry they refer to is built from the clue that owns the word.
            if clue.get("is-link"):
                continue
            # A period where a comma belongs — "(6.2)" for a two-word answer.
            # Setters' software emits it now and then, and no cryptic enumeration
            # uses a period as a real separator, so it is a typo and not a format.
            # Normalised at the source rather than papered over downstream:
            # int("6.2") raised, and because one bad clue aborts the whole parse,
            # the Independent on Sunday No 1,858 was simply absent (2026-08-19).
            fmt = (clue.get("format") or "").replace(".", ",")
            nums = [int(n) for n in clue.get("number", "").split("/") if n.strip()]
            segs = runs[clue.get("word")]
            if len(nums) != len(segs):
                raise ValueError(f"clue {clue.get('number')}: {len(nums)} numbers "
                                 f"for {len(segs)} grid runs")
            group, built = [], []
            for num, ((x1, x2), (y1, y2)) in zip(nums, segs):
                across = x2 > x1 or y1 == y2
                cells = ([(x, y1) for x in range(x1, x2 + 1)] if across
                         else [(x1, y) for y in range(y1, y2 + 1)])
                eid = f"{num}-{'across' if across else 'down'}"
                group.append(eid)
                built.append((eid, num, across, x1, y1, cells))
            seps = separators(fmt, [len(c[5]) for c in built])
            text, italics = flatten_clue(inner_xml(clue).strip())
            for i, (eid, num, across, x1, y1, cells) in enumerate(built):
                entries.append({
                    "id": eid,
                    "number": num,
                    "direction": "across" if across else "down",
                    "position": {"x": x1 - 1, "y": y1 - 1},   # 1-based -> 0-based
                    "length": len(cells),
                    # The enumeration is an attribute here, but the app (and the
                    # Guardian data it was built for) expects it inside the clue
                    # text, where a solver reads it. Continuations say "See 10",
                    # matching the Guardian's own wording for the same thing.
                    # The enumeration goes on the END, so it cannot disturb any
                    # italic range; a continuation carries none of either.
                    "clue": f"{text} ({fmt})" if i == 0 else f"See {nums[0]}",
                    **({"clueItalics": italics} if italics and i == 0 else {}),
                    "group": group,
                    "separatorLocations": seps[i],
                    "solution": "".join(letters.get(c, "") for c in cells).upper(),
                    "annotation": None,
                })
            # NOTE: clue elements also carry a `citation` attribute holding the
            # setter's own wordplay explanation. It is deliberately not read.
            # It is the Independent's editorial content, this repo is public,
            # and the whole point of the site is annotations written here.

    entries.sort(key=lambda e: (e["position"]["y"], e["position"]["x"], e["direction"]))
    when = datetime.strptime(ymd, "%y%m%d").replace(tzinfo=timezone.utc)
    series = series_for(number)
    paper = ("Independent on Sunday" if series == "indysunday" else "Independent")
    return {
        "id": series_meta.puzzle_id(series, number),
        "number": number,
        "series": series,
        "name": f"{paper} cryptic crossword No {number:,}",
        "setter": setter,
        "date": int(when.timestamp() * 1000),
        "dimensions": {"cols": cols, "rows": rows},
        "sourceUrl": PLAY_URL,
        "entries": entries,
    }


def fetch_day(ymd):
    """Fetch one date, whichever of the two series that day carries."""
    puzzle = parse(http_get(FEED.format(ymd=ymd)), ymd)
    path = PUZZLE_DIR / f"{puzzle['id']}.js"
    is_new = not path.exists()
    if not is_new:
        merge_annotations(puzzle, read_puzzle_file(path))
    write_puzzle_file(path, puzzle, generator="tools/fetch_independent.py")
    print(("fetched " if is_new else "refreshed ") + f"{puzzle['id']} ({ymd})")
    return puzzle


def days_back(n, end=None):
    end = end or date.today()
    return [(end - timedelta(days=i)).strftime("%y%m%d") for i in range(n)]


def sundays_back(n, end=None):
    """The last N Sundays, newest first.

    Its own walk rather than a filter over days_back: the Sunday puzzle is one
    day in seven, so asking for a year of them by days would download 365 files
    to keep 52. The feed is keyed by date and costs a request per day either
    way, and there is no reason to spend six of every seven on days we already
    have.
    """
    end = end or date.today()
    end -= timedelta(days=(end.weekday() + 1) % 7)     # Monday is 0; back to Sunday
    return [(end - timedelta(weeks=i)).strftime("%y%m%d") for i in range(n)]


def latest():
    """The newest day the feed has, if we don't already have it. Returns the
    puzzle, or None for "nothing new" — which the caller turns into exit 3, the
    same contract fetch_puzzle.py --latest has and daily_update.sh relies on to
    tell a quiet night from a broken feed.

    Walks back a few days rather than assuming today: the feed is stamped in UK
    time and this machine is not, so around midnight "today" may not exist yet,
    and one missing day shouldn't read as the feed being gone.
    """
    for ymd in days_back(4):
        try:
            puzzle = parse(http_get(FEED.format(ymd=ymd)), ymd)
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            continue
        if (PUZZLE_DIR / f"{puzzle['id']}.js").exists():
            # The newest day we can see is one we already have, so there is
            # nothing newer to find further back either.
            print(f"up-to-date {puzzle['id']}")
            return None
        return fetch_day(ymd)
    return None


def backfill(ymds):
    fetched = skipped = missing = 0
    # Keyed by id, not number: this feed alone carries two sequences, and a bare
    # number would have made Sunday No 1,903 look like one we already had the
    # day the Quiptic reaches 1,903.
    have = {p["id"] for p in (read_puzzle_file(f) for f in puzzle_files())}
    for ymd in ymds:
        try:
            # Cheap pre-skip is impossible — the feed is keyed by date and the
            # number only appears inside the file — so we always download, but
            # 12KB a day is nothing and it doubles as a re-check that old days
            # are still served.
            puzzle = parse(http_get(FEED.format(ymd=ymd)), ymd)
        except urllib.error.HTTPError as err:
            print(f"skip {ymd}: HTTP {err.code}")
            missing += 1
            continue
        except Exception as err:  # noqa: BLE001 — one bad day shouldn't stop the run
            print(f"skip {ymd}: {err}")
            missing += 1
            continue
        if puzzle["id"] in have:
            skipped += 1
        else:
            fetch_day(ymd)
            fetched += 1
        time.sleep(1)
    reindex()
    print(f"backfill done: {fetched} fetched, {skipped} skipped, {missing} unavailable")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--check":
        puzzle = parse(http_get(FEED.format(ymd=days_back(2)[1])), days_back(2)[1])
        print(f"feed ok: No {puzzle['number']:,} by {puzzle['setter']}, "
              f"{len(puzzle['entries'])} entries")
        return 0
    if argv[0] == "--backfill":
        backfill(days_back(int(argv[1]) if len(argv) > 1 else 30))
        return 0
    if argv[0] == "--sundays":
        backfill(sundays_back(int(argv[1]) if len(argv) > 1 else 52))
        return 0
    if argv[0] == "--latest":
        puzzle = latest()
        if not puzzle:
            return 3
        reindex()
        print(puzzle["id"])
        return 0
    if not re.fullmatch(r"\d{6}", argv[0]):
        raise SystemExit(f"Expected a YYMMDD date, got: {argv[0]}")
    if fetch_day(argv[0]):
        reindex()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
