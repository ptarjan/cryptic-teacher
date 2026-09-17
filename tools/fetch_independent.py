#!/usr/bin/env python3
"""Fetch an Independent cryptic crossword and convert it to this app's format.

Usage:
  python3 tools/fetch_independent.py --latest        # newest published day
  python3 tools/fetch_independent.py 260805          # one day, YYMMDD
  python3 tools/fetch_independent.py --backfill [N]  # the last N days (default 30),
                                                     # skipping days already on disk
  python3 tools/fetch_independent.py --sundays [N]   # the last N Sundays (default 52)
  python3 tools/fetch_independent.py --extend [N]    # N days OLDER than the oldest daily
                                                     # on disk (default 30)
  python3 tools/fetch_independent.py --extend-sundays [N]
                                                     # N Sundays older than the oldest (26)
  python3 tools/fetch_independent.py --check         # is the feed still there?

One feed, two series: the daily Monday–Saturday and the Independent on Sunday's
own weekly sequence. See series_for() for how a file is told which it is.

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
referer; plain curl works. Reachable back to at least 2017-02-06 (proven
2026-09-17, an --extend run that stopped on its own time cap, not on a 404);
the true floor is still unknown. --extend does not auto-detect it — it walks
exactly the N days it's given and reports what came back missing, and a lone
404 (Christmas Day, both years seen so far) is an editorial gap, not the
floor. Finding the floor means rerunning --extend with a larger N and reading
the summary.

Writes puzzles/<series>-<number>.js (preserving any existing per-clue
annotations), then rebuilds the index via fetch_puzzle.reindex().
"""

import codecs
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, UA, http_bytes, flatten_clue,  # noqa: E402
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
# cryptic; Sundays it is the Independent on Sunday cryptic, a separate weekly
# sequence — same XML, same 15x15 grid, same setters, nothing in the puzzle
# itself says which. In 2026 the daily is numbered ~12,400 and the Sunday
# ~1,900, so a fixed number threshold (used until this comment) looked like a
# safe way to tell them apart. It wasn't: walking the archive back past 2019
# found the DAILY series was ALSO under 10,000 back then (No 9,897 on
# 2018-07-03), which misfiled 539 daily puzzles as Sunday ones. A puzzle's
# weekday is the one fact that is always right — the Independent on Sunday is
# only ever printed on a Sunday — and it costs nothing extra since ymd is
# already in hand.
#
# Sundays were skipped entirely until 2026-08-19, and the reason was ids: they
# were bare numbers, so Sunday No 1,395 would have collided with Guardian Quiptic
# No 1,395 in the mid-2030s and one would have overwritten the other's file.
# Ids carry their series now, so the collision cannot happen and the reason is
# gone.


# Dates whose puzzle number the source prints wrong. The number is typed by
# hand and the feed is keyed by date, so a mistyped one would file a real
# puzzle under a number that belongs to another day — or, where that number is
# already held, drop the puzzle as a duplicate. The sequence decides, not the
# title: each date below is a publishing day (Monday–Saturday) whose immediate
# neighbours on disk are the number before it and the number after it, so there
# is exactly one number the day can hold. Keyed by the fetcher's date key, with
# what the title prints and the two puzzles that bracket it.
#
# One-offs only. A wrong number that repeats to a rule belongs in a rule, not in
# 31 copies of one line — see SATURDAY_LAG below. This dict is checked first, so
# a date listed here overrides that rule.
NUMBER_FIXES = {
    "190306": 10107,   # prints "10,007"; 10,106 Tue 5 Mar, 10,108 Thu 7 Mar
    "190426": 10151,   # prints "10,051"; 10,150 Thu 25 Apr, 10,152 Sat 27 Apr
    "191114": 10324,   # prints "10,234"; 10,323 Wed 13 Nov, 10,325 Fri 15 Nov
    "220421": 11083,   # prints "10,083"; 11,082 Wed 20 Apr, 11,084 Fri 22 Apr
    "221013": 11233,   # prints "11,223"; 11,232 Wed 12 Oct, 11,234 Fri 14 Oct
    # Prints "11,296", the number the day before already holds. Not a repeat of
    # that day: different setter (Hoskins, not Grecian), different grid,
    # different clues. 11,296 Mon 26 Dec, 11,298 Wed 28 Dec.
    "221227": 11297,
    "150806": 8988,    # prints "8,968"; 8,987 Wed 5 Aug, 8,989 Fri 7 Aug
    # Inside SATURDAY_LAG, but Christmas Day fell on the Friday and the paper
    # did not print, so that week ran five publishing days and the rule's six
    # would land on 9,111 — the Monday's number. Prints "9,105"; 9,109 Thu 24
    # Dec, nothing Fri 25 Dec, 9,111 Mon 28 Dec.
    "151226": 9110,
}


# Every Saturday from 2015-08-22 to 2016-03-26 printed the PREVIOUS Saturday's
# number: 31 Saturdays, one repeating fault, so a dated range rather than 31
# NUMBER_FIXES entries saying the same thing. A full Mon–Sat week is six
# publishing days, so the printed number sits six below the slot the sequence
# leaves free — Sat 2015-08-29 prints "9,003" between 9,008 Fri 28 Aug and 9,010
# Mon 31 Aug, and only 9,009 fits. Verified against the Friday before and the
# Monday after for every Saturday in the range and the two either side of each
# end; the Saturdays outside it need no correction. A week short a publishing
# day breaks the arithmetic, not the rule, and goes in NUMBER_FIXES above.
#
# The range opens a week before the first Saturday held on disk. 2015-08-22 was
# a resend of 8,997 and was deleted, but the fix still has to cover it: without
# one, re-fetching that date writes its 8,997 title over the real 8,997 and
# moves that puzzle to the wrong day. With it the resend lands on 9,003, the
# empty slot that is genuinely its own, where puzzle_integrity.py reports it as
# a DUPLICATE to be deleted again.
SATURDAY_LAG = ("150822", "160326")


# The feed ran a day out of step until Monday 2015-08-17. Before that date the
# SUNDAY key served the daily (8,979 on Sun 2015-07-26, then 8,980 on the Tue,
# six a week) and the MONDAY key served the weekly (1,327 / 1,328 / 1,329 on
# three consecutive Mondays, one a week). Both sequences are continuous across
# the changeover -- 8,997 Sun 08-16 then 8,998 Mon 08-17, 1,329 Mon 08-10 then
# 1,330 Sun 08-23 -- so it is the key that moved, not the papers.
SHIFTED_BEFORE = "150817"


# Enumerations the paper printed wrong, and still serves wrong. A cryptic's
# enumeration is a promise about the answer's shape, and one that contradicts
# the light it sits on teaches a learner to count wrong — so these are corrected
# here, at the source, rather than left for a reader to trip over.
#
# Keyed by (fetcher date key, the feed's own `word` id, the format it prints),
# valued with the format the grid demands. Including the wrong value in the KEY
# is what makes this safe to leave in place: the day Arkadium re-cuts the feed
# the key stops matching and the feed's own value is taken, so a corrected
# upstream can never be overwritten with a stale correction, and a shifted word
# id can never silently re-point a fix at an innocent clue.
#
# Every one below is the PAPER's error, confirmed against the light's own cell
# count, its wordplay, and the fifteensquared blog for the day:
#   150819 word 30 = 23dn BALSAM, "Plant maiden found under wood" — BALSA + M,
#     six cells, printed (5). A solver said so on the day (fifteensquared,
#     Independent 9,000 / Dac, comment 5: "My paper gives 23D as a five letter
#     answer, but of course there are six spaces").
#   160512 word 27 = 23dn INTRO, "Britons wanting borders sabotaged opening" —
#     anagram of (B)RITON(S), five cells, printed (7). Same again
#     (Independent 9228 / Nestor, comment 10: "Not helped by my printout having
#     (7) not (5) for 23dn"); the blog itself prints (5).
#   160512 word 28 = 27dn GOO, "Travel over slush" — GO + O, three cells,
#     printed (5). The blog prints (3). Nobody complained about this one, but
#     it is the same fault in the same puzzle.
FORMAT_FIXES = {
    ("150819", "30", "5"): "6",
    ("160512", "27", "7"): "5",
    ("160512", "28", "5"): "3",
}


def series_for(ymd):
    weekday = datetime.strptime(ymd, "%y%m%d").weekday()
    sunday_paper = 0 if ymd < SHIFTED_BEFORE else 6
    return "indysunday" if weekday == sunday_paper else "independent"


def true_number(ymd, printed):
    """The number a date actually holds, given the one its title prints."""
    if ymd in NUMBER_FIXES:
        return NUMBER_FIXES[ymd]
    saturday = datetime.strptime(ymd, "%y%m%d").weekday() == 5
    if saturday and SATURDAY_LAG[0] <= ymd <= SATURDAY_LAG[1]:
        return printed + 6
    return printed


def http_get(url):
    return http_bytes(url)


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


def _cp1252_byte(exc):
    """codecs error handler: decode just the byte(s) UTF-8 rejected as
    Windows-1252 rather than giving up on the whole document.

    The feed declares UTF-8 but a handful of older days (2017-03-20 is one)
    have a single raw cp1252 byte where a proper UTF-8 dash or quote
    belongs — 0x96 for an en dash, seen here. ET.fromstring is byte-exact
    about its declared encoding, so that one byte aborts the entire parse.
    Decoding only the rejected span leaves every valid UTF-8 sequence
    (accented setter names included) untouched.
    """
    bad = exc.object[exc.start:exc.end]
    return bad.decode("cp1252"), exc.end


codecs.register_error("independent_cp1252_fallback", _cp1252_byte)


def clean_xml_bytes(data):
    return data.decode("utf-8", errors="independent_cp1252_fallback").encode("utf-8")


def parse(xml_bytes, ymd):
    root = ET.fromstring(clean_xml_bytes(xml_bytes))
    puz = root.find(f".//{NS}rectangular-puzzle")
    title = (puz.findtext(f"{NS}metadata/{NS}title") or "").strip()
    # The title is typed by hand and arrives mistyped in four ways: "No."
    # dropped entirely ("1,514 by Raich"), a comma for its period ("No, 10,407
    # by Knut"), a stray pipe in front of it ("|No. 10,242 by Serpent"), and a
    # space inside the digits ("No. 1, 661 by Hoskins"). All are source-side
    # typos, not format changes, so the pipe, the prefix and its punctuation
    # and whitespace inside the digits are all optional.
    m = re.match(r"\|?\s*(?:No[.,]?\s*)?(\d[\d,\s]*\d|\d)\s*(?:by\s*(.+))?$", title)
    if m:
        setter = (m.group(2) or "").strip() or "Unknown"
        number_text = m.group(1)
    else:
        # A fifth, older shape drops "No." AND "by" both and just reverses the
        # order: "Raich 9897" (2018-07-03) — setter name, then the number bare.
        # The number is trustworthy (it slots exactly between 9896 the day
        # before and 9898 the day after); only the layout differs.
        m = re.match(r"([A-Za-z][\w.'-]*)\s+(\d[\d,\s]*\d|\d)$", title)
        if not m:
            raise ValueError(f"unrecognised title {title!r}")
        setter, number_text = m.group(1), m.group(2)
    number = true_number(ymd, int(re.sub(r"[,\s]", "", number_text)))

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
            # A comma is the only real separator in an enumeration besides the
            # hyphen, but the source types three other things in its place: a
            # period ("6.2"), a slash ("2/2") and a bare space ("5 2"). None of
            # them mean anything in a cryptic enumeration, so all three are
            # typos and are normalised to a comma at the source rather than
            # papered over downstream: int("6.2") raised, and because one bad
            # clue aborts the whole parse the puzzle was simply absent —
            # Independent on Sunday No 1,858 (2026-08-19), No 11,637 and
            # No 12,317. The collapse catches "4, 2", where the space follows a
            # comma that is already there.
            fmt = re.sub(r",+", ",",
                         re.sub(r"[./\s]", ",", (clue.get("format") or "").strip()))
            fmt = FORMAT_FIXES.get((ymd, clue.get("word"), fmt), fmt)
            # A linked clue's number can carry a trailing A/D ("7/21A/11") when the
            # bare number would collide with an unrelated clue elsewhere in the same
            # grid — the compiler's own disambiguation, not data we need: direction
            # is already read from grid geometry below. int("21A") raised and aborted
            # the whole parse, which is how Independent on Sunday No 1,840 went
            # missing (2026-09-10).
            nums = [int(n.rstrip("ADad")) for n in clue.get("number", "").split("/") if n.strip()]
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
                    **({"group": group} if len(group) > 1 else {}),
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
    series = series_for(ymd)
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


def oldest_held(series):
    """The earliest date we hold for one of the two series, or None.

    The anchor --extend walks back from. This feed is keyed by date and the
    number only appears inside the file, so unlike the number-based fetchers it
    cannot skip a day it already has without paying for the download — which
    makes anchoring at the far end of the archive the difference between
    fetching N days and re-fetching the entire history to reach them.
    """
    stamps = [p["date"] for p in (read_puzzle_file(f) for f in puzzle_files())
              if p["id"].startswith(f"{series}-")]
    if not stamps:
        return None
    return datetime.fromtimestamp(min(stamps) / 1000, timezone.utc).date()


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
    # The two --extend forms walk older instead of newer, one per series. Both
    # anchor a day before the oldest we hold: a Saturday for the daily, and for
    # the Sunday walk a day that sundays_back then snaps to the Sunday before.
    if argv[0] == "--extend":
        n = int(argv[1]) if len(argv) > 1 else 30
        held = oldest_held("independent")
        backfill(days_back(n, held - timedelta(days=1) if held else None))
        return 0
    if argv[0] == "--extend-sundays":
        n = int(argv[1]) if len(argv) > 1 else 26
        held = oldest_held("indysunday")
        backfill(sundays_back(n, held - timedelta(days=1) if held else None))
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
