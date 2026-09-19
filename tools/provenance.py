#!/usr/bin/env python3
"""Where a puzzle came from — and, the part that matters, where its ANSWERS came from.

Every puzzle already carried `sourceUrl`, which is a link, not a provenance
record. A link says which page the puzzle was printed on. It does not say how
the file got here, when, whether the grid's geometry was read off a published
diagram or worked out from the clue list, or — the question this module exists
for — whether the letters in the grid are the setter's answer key or OUR GUESS.

THAT LAST DISTINCTION IS THE WHOLE POINT. A grid the publisher answered is
ground truth: it can be used to grade a solver, to train on, to say "the answer
is BANANA" without qualification. A grid this repo cold-solved with a model is a
hypothesis that happens to be self-consistent. Both are 15x15 of capital
letters, and until now a file could be one or the other with nothing in it to
say which. A teaching site that cannot tell those apart eventually teaches a
guess as a fact, and nobody finds out, because a wrong answer that satisfies
every crossing looks exactly like a right one.

So: one `provenance` object per puzzle, with every value it can take enumerated
HERE and nowhere else. The schema is documented for humans in README.md under
"Puzzle file format"; the allowed values are the dicts below, and both the
validator (tools/puzzle_integrity.py) and the backfill
(tools/backfill_provenance.py) read them from here rather than restating them.
The prose in each dict IS the documentation of that value — a value added below
cannot be added without saying what it means.

    "provenance": {
     "publisher": "Guardian",
     "series": "cryptic",
     "acquiredBy": "tools/fetch_wayback.py",
     "acquiredOn": "2026-09-02",
     "retrievedFrom": "wayback",
     "retrievedUrl": "https://web.archive.org/web/2016id_/https://...",
     "gridOrigin": "published",
     "solutionOrigin": "published"
    }

THE CANONICAL URL IS NOT COPIED IN HERE. `sourceUrl` stays exactly where it has
always been, at the top level, meaning exactly what it always meant — the
puzzle's canonical page, the address a reader would cite — because several
tools read it expecting that and a second copy is a second thing that can be
wrong. What provenance adds is the RULE about it (check() refuses a puzzle that
has provenance and no sourceUrl) and the thing sourceUrl never said: WHERE THE
BYTES WERE ACTUALLY READ FROM. `retrievedFrom` is that channel, and
`retrievedUrl` is the address actually fetched when it differs — the Wayback
capture, which is what someone re-verifying the puzzle would need and which
sourceUrl, pointing at a page the paper has since dropped, will not give them.

ONE PUZZLE CAN HAVE THREE DIFFERENT ORIGINS, so they are three fields rather
than one "source". Cyclops is the ordinary case, not an edge case: the grid and
clues come from Private Eye's own .puz download, and the answers come from a
fifteensquared write-up, because Private Eye ships the puzzle with the solution
grid blanked. A book puzzle has three — clues off a book scan, geometry
reconstructed here from those clues, answers solved here by a model. Read
`retrievedFrom` for how the puzzle got here, `gridOrigin` for where its
geometry came from, and `solutionOrigin` for whose the answers are.

`solutionSource` IS NOT REPLACED EITHER, for the same reason in reverse. It
already exists on 443 puzzles and carries detail no enum can hold — which
fifteensquared write-up, which model, what the crossing check found, whether an
official key can ever exist at all. It stays the DETAIL record.
`provenance.solutionOrigin` is the coarse enum, and check() requires the two to
agree, so they cannot drift apart into two different answers to the same
question. Read solutionOrigin to branch on; read solutionSource for the story.

BUT solutionSource IS DELIBERATELY TRANSIENT, and that is why provenance needs
git. fetch_observer.py DELETES it the day the Observer finally publishes the
key, and fetch_puzzle.py only carries it across a re-fetch while the paper is
still silent — by design, because once the real answers land the file really is
the publisher's. The letters become ground truth and the file stops saying it
was ever anything else. Six grids in this corpus are in exactly that state: we
guessed them, the paper later confirmed them, and nothing on disk remembers.
`previousSolutionOrigin` is that memory. It does not weaken the current
answers — solutionOrigin still says "published", because they ARE the
publisher's — it records that this grid was once our guess, which is a
different object from one that was right the first time, and which is the only
evidence there will ever be about how good the guessing is.


WHAT IS NOT KNOWABLE IS WRITTEN AS UNKNOWN. Every field below has an "unknown"
value and the backfill uses it freely. An invented provenance is strictly worse
than an absent one: absent, someone goes and looks; invented, nobody ever does.
"""
import datetime
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import series as series_table  # noqa: E402

# One series per BOOK, with the volume in the number (series.py:
# volume * 1000 + position). Both questions — is this a book, and which volume
# is this puzzle — are asked of that table and never parsed out of the key: the
# key held the volume only while a book was one series per volume, and a key
# that ends in no digits is every book series now.
is_book = series_table.is_book
volume_of = series_table.volume_of
position_of = series_table.position_of

# ---------------------------------------------------------------- the enums
#
# One dict per field. The key is the value that may appear in a puzzle file; the
# value is what it asserts. Nothing else may appear, and nothing outside this
# file may restate the list — puzzle_integrity.py validates against
# GRID_ORIGINS/SOLUTION_ORIGINS/ACQUIRED_BY by membership, and README.md's table
# is generated from these same dicts by tools/build_readme.py.

GRID_ORIGINS = {
    "published": "the geometry is the publisher's own — read off the diagram or "
                 "the grid data the source shipped",
    "reconstructed": "no diagram was available; the black squares were derived "
                     "from the clue list's numbers and lengths by "
                     "tools/reconstruct_grid.py. A reconstruction that satisfies "
                     "every clue can still differ from the grid the paper "
                     "printed, so this is a claim about OUR geometry, not theirs",
    "authored": "the grid is ours — set here, not by a publisher",
    "unknown": "the corpus cannot say which of the above it was",
}

SOLUTION_ORIGINS = {
    "published": "the answers arrived with the puzzle, from the publisher. "
                 "Ground truth",
    "writeup": "the publisher withheld the answers and they were taken from a "
               "third party's published solution write-up (fifteensquared, for "
               "Private Eye's Cyclops). A human solver's word, not the setter's",
    "model": "cold-solved HERE by a model, from the clues alone. OUR GUESS — "
             "self-consistent, crossing-checked, and still a guess",
    "authored": "we wrote the fill as well as the grid",
    "unsolved": "the puzzle carries no answers at all. Not ignorance — a fact: "
                "there is nothing here to be wrong about",
    "unknown": "the grid holds answers and nothing in the corpus establishes "
               "whether they are the publisher's or ours",
}

# WHERE THE BYTES ACTUALLY CAME FROM — the publisher's own site, or somewhere
# else. This is the distinction `sourceUrl` cannot make and was never meant to:
# sourceUrl is the puzzle's CANONICAL page, the address a reader would cite, and
# several tools read it expecting exactly that. It stays that. But 492 Guardian
# puzzles and 50 of the 52 Metro ones were not read from those addresses at all
# — the paper had dropped the pages and they were recovered from Wayback
# captures. On disk that was invisible: a 2009 puzzle recovered from an archive
# looked identical to one fetched the morning it was published.
RETRIEVAL_CHANNELS = {
    "publisher": "read from the publisher's own live site or feed — sourceUrl is "
                 "both the canonical address and the address actually fetched",
    "wayback": "the publisher no longer serves the page; it was recovered from a "
               "Wayback Machine capture. sourceUrl is still the original "
               "address, which now 404s",
    "blog": "read from a third party's write-up rather than the publisher",
    "book": "read off a scanned and OCR'd printed book, not a web page at all",
    "authored": "not retrieved from anywhere — set in this repo",
    "unknown": "the corpus cannot say which of the above it was",
}

# The acquisition methods, named as the command that actually ran, each with the
# channel it reads through. The channel is a property of the TOOL, so it is
# stated here once and derived rather than stored twice — nothing may write a
# channel that disagrees with the tool that fetched it.
#
# A tool named here is a tool that exists — asserted by
# tools/test_provenance.sh, which checks each one resolves to a file in
# tools/. "tools/fetch_metro.py --wayback" is a separate entry from
# "tools/fetch_metro.py" on purpose: it is the same script reading a different
# channel, and the flag is the only thing that distinguishes them.
ACQUIRED_BY = {
    "tools/fetch_puzzle.py": {
        "channel": "publisher", "what": "the Guardian's crossword JSON feed"},
    "tools/fetch_independent.py": {
        "channel": "publisher", "what": "puzzles.independent.co.uk's feed"},
    "tools/fetch_privateeye.py": {
        "channel": "publisher", "what": "private-eye.co.uk's .puz download"},
    "tools/fetch_globeandmail.py": {
        "channel": "publisher", "what": "theglobeandmail.com's puzzle feed"},
    "tools/fetch_observer.py": {
        "channel": "publisher",
        "what": "observer.co.uk, where the Everyman moved in 2025"},
    "tools/fetch_metro.py": {
        "channel": "publisher", "what": "metro.co.uk's live puzzle page"},
    "tools/fetch_metro.py --wayback": {
        "channel": "wayback", "what": "a Wayback capture of metro.co.uk, which "
                                      "only serves the current day"},
    "tools/fetch_wayback.py": {
        "channel": "wayback", "what": "a Wayback capture of a Guardian page the "
                                      "paper no longer serves"},
    "tools/fetch_fifteensquared.py": {
        "channel": "blog", "what": "a fifteensquared solution write-up"},
    "tools/acquire_book.py": {
        "channel": "book",
        "what": "an archive.org book scan taken all the way to filed puzzles "
                "with no model in the loop"},
    "tools/file_penguin_puzzle.py": {
        "channel": "book",
        "what": "a scanned and OCR'd Penguin book (tools/fetch_ia_book.py -> "
                "tools/parse_penguin_book.py -> tools/reconstruct_grid.py -> "
                "a model solve)"},
    "tools/build_authored_puzzle.py": {
        "channel": "authored", "what": "set here, not fetched"},
    "unknown": {
        "channel": "unknown",
        "what": "the file no longer records which tool wrote it and the corpus "
                "cannot narrow it to one"},
}

# ------------------------------------------------- what each source can be
#
# Keyed by (series, sourceUrl host) because neither alone decides it: the
# Everyman is served BOTH from theguardian.com (by fetch_puzzle.py, and by
# fetch_wayback.py for the pages the Guardian dropped) and from observer.co.uk
# (by fetch_observer.py, from no. 4097 on), and theguardian.com serves three
# different series. The value is every tool that can legitimately produce that
# pair, primary first.
#
# This table exists because the tool a file claims is NOT reliable on its own:
# it can name the last tool to WRITE the file rather than the one that fetched
# it. So a globeandmail puzzle claiming fetch_puzzle.py is not a globeandmail
# puzzle fetched by fetch_puzzle.py — fetch_puzzle.py only knows the three
# Guardian series (its GUARDIAN_SERIES) and cannot reach theglobeandmail.com at
# all. The claim is believed when this table says it is possible, and overruled
# by the table when it is not.
ACQUISITION_BY_SOURCE = {
    ("cryptic", "www.theguardian.com"): ("tools/fetch_puzzle.py",),
    ("quiptic", "www.theguardian.com"): ("tools/fetch_puzzle.py",),
    ("everyman", "www.theguardian.com"): ("tools/fetch_puzzle.py",
                                          "tools/fetch_wayback.py"),
    ("everyman", "observer.co.uk"): ("tools/fetch_observer.py",),
    ("independent", "puzzles.independent.co.uk"): ("tools/fetch_independent.py",),
    ("indysunday", "puzzles.independent.co.uk"): ("tools/fetch_independent.py",),
    ("cyclops", "www.private-eye.co.uk"): ("tools/fetch_privateeye.py",),
    ("globeandmail", "www.theglobeandmail.com"): ("tools/fetch_globeandmail.py",),
    ("metro", "metro.co.uk"): ("tools/fetch_metro.py",
                               "tools/fetch_metro.py --wayback"),
}
# Every book is its own series (see series.py), and they all arrive the same
# way, so they are generated rather than typed — a book added to series.py must
# not also need adding here.
for _series in series_table.SERIES:
    if is_book(_series):
        ACQUISITION_BY_SOURCE[(_series, "archive.org")] = (
            "tools/file_penguin_puzzle.py", "tools/acquire_book.py")

# Series whose grid geometry is NOT the publisher's. Everything absent here is
# "published", and that is checked rather than assumed: file_penguin_puzzle.py
# is the only tool in the repo that BUILDS a puzzle out of
# reconstruct_grid.py's output — every other fetcher parses a grid the source
# shipped, and puzzle_integrity.py's use of reconstruct_grid is a check on
# geometry that already exists, not a source of it.
GRID_ORIGIN_BY_SERIES = {"authored": "authored"}

# ------------------------------------------------------ book-sourced puzzles
#
# A puzzle out of a book has no URL that identifies IT — archive.org's item page
# is the whole 150-leaf scan, the same link for all sixty puzzles in the volume.
# So the book block carries what actually pins the puzzle down: which scan,
# which volume, and the puzzle's number within that volume.
#
# Nothing about the book is kept here: series.py holds it, and this module
# reads it through series.book_title/scan_identifier/volume_of. Two tables
# keyed by volume can only drift, and a puzzle whose sourceUrl names one book
# while its provenance.book names another is exactly what that drift looks
# like.
def book_of(series, number):
    """The book block for one book-sourced puzzle, or None.

    Takes the number as well as the series because the volume is in the number
    — a series is a book now, not a book's volume — and every field below is
    the volume's, not the shelf's.

    A book series with no recorded scan raises. There is no placeholder
    identifier: a file saying "unknown" reads afterwards as a fact about the
    book rather than a gap, and it is a gap a human has to close by looking the
    volume up.
    """
    if not is_book(series):
        return None
    identifier = series_table.scan_identifier(series, number)
    if not identifier:
        raise ValueError(
            f"{series} volume {volume_of(series, number)} has no archive.org "
            f"identifier in tools/series.py — look up its own scan and add it "
            f"there; filing it without one makes the puzzle cite a book it did "
            f"not come from")
    return {
        "identifier": identifier,
        "title": series_table.book_title(series, number),
        "volume": volume_of(series, number),
    }


REQUIRED = ("publisher", "series", "acquiredBy", "acquiredOn",
            "retrievedFrom", "retrievedUrl", "gridOrigin", "solutionOrigin")

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def host_of(url):
    return urlparse(url or "").netloc


def series_of_id(pid):
    """The series from the id, never from the `series` field.

    35 files in this corpus (cryptic-30039..30073, the first ones ever fetched)
    carry no `series` field at all, and a provenance backfill that read the
    field would have silently filed them under the default. The id is the one
    statement every puzzle makes — see series.parse_id, which this defers to.
    """
    series, _ = series_table.parse_id(pid)
    return series or "cryptic"


def acquired_by(series, url, claimed):
    """Which tool fetched this, from the (series, host) table and the claim.

    `claimed` is the tool the file itself names. It is taken when the table
    agrees it is possible for this source. When it is not — because a later
    tool overwrote it — the table decides, and it can only decide when the
    source admits exactly one tool. Two candidates and a claim naming neither
    is genuinely unrecoverable: "unknown".
    """
    candidates = ACQUISITION_BY_SOURCE.get((series, host_of(url)))
    if not candidates:
        return "unknown"
    if claimed in candidates:
        return claimed
    return candidates[0] if len(candidates) == 1 else "unknown"


def solution_origin_from_file(puzzle):
    """The solution origin the file's OWN contents establish, or None.

    None means the file does not settle it — it holds answers and carries no
    solutionSource. That is not the same as "published": see the module
    docstring for the corpus argument that lets the backfill read it that way,
    and check() below for why an unbacked "model"/"writeup"/"unsolved" claim is
    refused while "published" and "unknown" are both allowed.
    """
    if not any((e.get("solution") or "").strip() for e in puzzle.get("entries") or []):
        return "unsolved"
    kind = (puzzle.get("solutionSource") or {}).get("kind")
    if kind == "model":
        return "model"
    if kind == "fifteensquared":
        return "writeup"
    return None


def grid_origin(series):
    """A book puzzle's geometry was worked out from its clue list; everything
    else arrives with the grid the source published."""
    if is_book(series):
        return "reconstructed"
    return GRID_ORIGIN_BY_SERIES.get(series, "published")


def channel_of(tool):
    """The retrieval channel a tool reads through — never stored twice."""
    return ACQUIRED_BY.get(tool, ACQUIRED_BY["unknown"])["channel"]


def derive(puzzle, claimed, acquired_on, previously=None):
    """The provenance object for a puzzle, from what is actually knowable.

    `claimed` is the tool the file already names as its acquirer;
    `acquired_on`
    is the ISO date the file first appeared in git, or None; `previously` is the
    origin this grid's answers had BEFORE the ones in it now — "model" for a
    grid we cold-solved and the paper has since confirmed, which only git
    remembers. Everything else comes off the puzzle and the tables above. Pure
    — it reads no files and no clock, so tools/backfill_provenance.py can be
    re-run to a fixed point.
    """
    series = series_of_id(puzzle["id"])
    origin = solution_origin_from_file(puzzle) or "published"
    tool = acquired_by(series, puzzle.get("sourceUrl"), claimed)
    prov = {
        "publisher": series_table.publisher(series, puzzle["number"]),
        "series": series,
        "acquiredBy": tool,
        "acquiredOn": acquired_on if acquired_on else "unknown",
        "retrievedFrom": channel_of(tool),
        # The address actually fetched, when it is not sourceUrl. Only the tool
        # that did the fetching can know it, so it is carried across from
        # whatever is already on the file rather than derived: fetch_wayback.py
        # and fetch_metro.py --wayback write it now, and for the 542 puzzles
        # they retrieved BEFORE this field existed it is null, because the
        # capture URL was printed to stdout and never stored. Null here means
        # "not recorded", and no reconstruction of it would be anything but a
        # guess at which capture was served that day.
        "retrievedUrl": (puzzle.get("provenance") or {}).get("retrievedUrl"),
        "gridOrigin": grid_origin(series),
        "solutionOrigin": origin,
    }
    # Carried across, not re-derived: which grids were once model-solved is
    # knowable only from git (see backfill_provenance.machine_solved_ever), so
    # an ordinary write must preserve what the backfill found rather than drop
    # it. Only worth saying when it differs from where the answers stand now —
    # recording "was model, is model" would be noise on every unresolved prize
    # puzzle in the corpus.
    previously = previously or (puzzle.get("provenance") or {}).get(
        "previousSolutionOrigin")
    if previously and previously != origin:
        prov["previousSolutionOrigin"] = previously
    book = book_of(series, puzzle["number"]) if is_book(series) else None
    if book:
        # The book's own number, not the file's: the file's carries the volume
        # (series.py, volume * 1000 + position) and the book prints No 18.
        book["numberInBook"] = position_of(series, puzzle["number"])
        # Which leaf of the scan the clues were read off. parse_penguin_book.py
        # knows it (it emits source_leaves) but the five puzzles filed before
        # provenance existed were written from solve records that no longer
        # exist, so theirs cannot be recovered. null, not a guess.
        book["leaf"] = (puzzle.get("provenance") or {}).get("book", {}).get("leaf")
        prov["book"] = book
    return prov


def place(puzzle, prov):
    """The puzzle with provenance sitting straight after sourceUrl.

    Rebuilt rather than assigned so the block lands where a human reading the
    file will see it — next to the link it qualifies — instead of after a few
    hundred entries.
    """
    out = {}
    for key, value in puzzle.items():
        if key == "provenance":
            continue
        out[key] = value
        if key == "sourceUrl":
            out["provenance"] = prov
    if "provenance" not in out:          # an authored puzzle has no sourceUrl
        out["provenance"] = prov
    return out


def stamp(puzzle, tool, retrieved_url=None):
    """Provenance for a puzzle being written right now, by `tool`.

    Called from fetch_puzzle.write_puzzle_file, which means EVERY write of a
    puzzle file goes through it and no fetcher can forget to record where its
    puzzle came from. That is the point: provenance that a tool has to remember
    to add is provenance that will be missing from whichever tool is written
    next, and the validator would then fail a puzzle for a bug in a fetcher
    nobody had touched.

    `acquiredOn` is today only for a file that has never carried provenance
    before. Anything already on the file is kept — the date a puzzle arrived
    does not change because something rewrote its annotations, and
    tools/backfill_provenance.py's git-derived dates must survive every later
    write.
    """
    existing = puzzle.get("provenance") or {}
    if retrieved_url:
        puzzle = {**puzzle,
                  "provenance": {**existing, "retrievedUrl": retrieved_url}}
    return place(puzzle, derive(puzzle, tool,
                                existing.get("acquiredOn") or today()))


# ------------------------------------------------------------ the validator
#
# Called by puzzle_integrity.check_provenance. Returns findings as strings, the
# shape every other check in that file returns.
def check(puzzle):
    findings = []
    pid = puzzle.get("id")
    prov = puzzle.get("provenance")
    if not isinstance(prov, dict):
        return ["no provenance object — where this puzzle and its answers came "
                "from is unrecorded (tools/backfill_provenance.py writes it)"]

    for key in REQUIRED:
        if key not in prov:
            findings.append(f"provenance is missing {key}")

    for key, allowed in (("gridOrigin", GRID_ORIGINS),
                         ("solutionOrigin", SOLUTION_ORIGINS),
                         ("previousSolutionOrigin", SOLUTION_ORIGINS),
                         ("retrievedFrom", RETRIEVAL_CHANNELS),
                         ("acquiredBy", ACQUIRED_BY)):
        value = prov.get(key)
        if key in prov and value not in allowed:
            findings.append(
                f"provenance.{key} is {value!r}, which is not one of: "
                + ", ".join(sorted(allowed)))

    # An optional field that repeats the current origin says nothing and would
    # let "was model, is model" and "was model, now published" look alike.
    if "previousSolutionOrigin" in prov \
            and prov["previousSolutionOrigin"] == prov.get("solutionOrigin"):
        findings.append(
            f"provenance.previousSolutionOrigin repeats solutionOrigin "
            f"({prov.get('solutionOrigin')!r}) — it is only written when the "
            f"answers have since been replaced by ones of a different origin")

    # The channel is a property of the tool, so it cannot be stated freely.
    expected_channel = channel_of(prov.get("acquiredBy"))
    if "retrievedFrom" in prov and prov.get("acquiredBy") in ACQUIRED_BY \
            and prov["retrievedFrom"] != expected_channel:
        findings.append(f"provenance.retrievedFrom is {prov['retrievedFrom']!r} but "
                        f"{prov.get('acquiredBy')!r} reads through "
                        f"{expected_channel!r}")

    # A capture URL on a puzzle fetched from the publisher would mean the two
    # fields describe different retrievals. Null on an archive channel is
    # allowed and means "not recorded" — see derive().
    url = prov.get("retrievedUrl")
    if url is not None and not isinstance(url, str):
        findings.append(f"provenance.retrievedUrl is {url!r} — want a URL or null")
    elif url and expected_channel == "publisher":
        findings.append("provenance.retrievedUrl is set but this was read from the "
                        "publisher, where sourceUrl IS the address fetched")

    # The canonical URL is not copied into provenance, so this is where the rule
    # about it lives: provenance without a link is provenance that cannot be
    # checked by a human. An authored puzzle has no source to link to.
    series = series_of_id(pid)
    if not puzzle.get("sourceUrl") and expected_channel != "authored":
        findings.append("provenance without a sourceUrl — nothing to check it against")

    if prov.get("series") != series:
        findings.append(f"provenance.series is {prov.get('series')!r} but the id "
                        f"says {series!r}")
    expected_publisher = series_table.publisher(series, puzzle["number"])
    if prov.get("publisher") != expected_publisher:
        findings.append(f"provenance.publisher is {prov.get('publisher')!r} but "
                        f"series.py says {series!r} is published by "
                        f"{expected_publisher!r}")

    acquired_on = prov.get("acquiredOn")
    if acquired_on != "unknown" and not (isinstance(acquired_on, str)
                                         and ISO_DATE.fullmatch(acquired_on)):
        findings.append(f"provenance.acquiredOn is {acquired_on!r} — want an "
                        f"ISO date or \"unknown\"")

    expected_grid = grid_origin(series)
    if prov.get("gridOrigin") not in (expected_grid, "unknown"):
        findings.append(f"provenance.gridOrigin is {prov.get('gridOrigin')!r} but "
                        f"{series!r} grids are {expected_grid!r}")

    # The agreement rule that keeps solutionSource and solutionOrigin from
    # becoming two different answers to the same question.
    stated = prov.get("solutionOrigin")
    implied = solution_origin_from_file(puzzle)
    if implied is not None and stated != implied:
        findings.append(
            f"provenance.solutionOrigin is {stated!r} but the file says "
            f"{implied!r} (" + ("no entry carries an answer"
                                if implied == "unsolved"
                                else f"solutionSource.kind is "
                                     f"{(puzzle.get('solutionSource') or {}).get('kind')!r}")
            + ")")
    elif implied is None and stated not in ("published", "unknown", "authored"):
        # Answers present, no solutionSource backing a claim about them. Saying
        # "model" or "writeup" here would assert a story the file does not tell,
        # and "unsolved" would contradict the answers sitting in it.
        findings.append(f"provenance.solutionOrigin is {stated!r} but the file "
                        f"carries answers and no solutionSource to back that")

    if is_book(series):
        book = prov.get("book")
        if not isinstance(book, dict):
            findings.append(f"{series} is book-sourced but provenance has no book block")
        else:
            for key in ("identifier", "title", "volume", "numberInBook"):
                if not book.get(key):
                    findings.append(f"provenance.book is missing {key}")
            # Both halves of the number are checked, because the number IS the
            # pair: a block that agreed on the position while naming another
            # volume would cite the wrong book and read as correct.
            want_volume = volume_of(series, puzzle["number"])
            want_position = position_of(series, puzzle["number"])
            if book.get("volume") != want_volume:
                findings.append(
                    f"provenance.book.volume is {book.get('volume')!r} but "
                    f"{puzzle.get('id')} is volume {want_volume}")
            if book.get("numberInBook") != want_position:
                findings.append(
                    f"provenance.book.numberInBook is {book.get('numberInBook')!r} "
                    f"but {puzzle.get('id')} is No {want_position} in its book")
    elif prov.get("book"):
        findings.append(f"provenance has a book block but {series!r} is not book-sourced")

    return findings


def today():
    return datetime.date.today().isoformat()
