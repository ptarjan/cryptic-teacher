#!/usr/bin/env python3
"""Where a puzzle came from, whose answers are in its grid, and who wrote its hints.

Three top-level keys, one question each:

    "source": {
     "publisher": "Private Eye",
     "url": "https://www.private-eye.co.uk/pictures/crossword/download/757.puz",
     "retrievedFrom": "publisher",
     "acquiredBy": "tools/fetch_privateeye.py",
     "acquiredOn": "2026-09-17",
     "gridOrigin": "published"
    },
    "solutions": {
     "origin": "writeup",
     "blog": "fifteensquared",
     "url": "https://fifteensquared.net/2024/03/01/private-eye-cyclops-757/",
     "date": "2024-03-01",
     "check": "28 entries verified against the grid (lengths, crossings)"
    },
    "annotatedBy": ["claude-opus-5-5"]

Every enumerated value is defined HERE and nowhere else: the dicts below are
the documentation of each value, puzzle_schema.py reads its enums from them,
and README.md's table is generated from them by tools/build_readme.py.

`source` is the puzzle: which paper (`publisher`), the page to cite (`url`;
absent only on an authored puzzle), the channel the bytes were actually read
through (`retrievedFrom`, a function of `acquiredBy`, the command that first
wrote the file), the day this repo first had it (`acquiredOn`), whether the
black squares are the publisher's or worked out here from the clue list
(`gridOrigin`), and for a book puzzle which scan and which puzzle in it
(`book`). Metro puzzles also name their id in the PuzzleMe feed (`feedId`).

`solutions` is the answers, and THAT IS THE DISTINCTION THIS MODULE EXISTS FOR.
A grid the publisher answered is ground truth; a grid this repo cold-solved is
a self-consistent guess; both are 15x15 of capital letters. `origin` says which
(SOLUTION_ORIGINS). Answers not from the publisher carry the detail that backs
the claim: a write-up names its `blog` and `url`, a model solve its `model`, and
both the `date` and the crossing `check`. The detail keys imply the origin
(solution_origin_from_file) and check() holds `origin` to them. A Cyclops
puzzle is the ordinary mixed case: grid and clues from Private Eye, answers
from a fifteensquared write-up.

When the publisher later prints the key, the detail goes (drop_solution_detail)
and `origin` becomes "published". `previousOrigin` keeps the one fact nothing
else would: this grid was once our guess. It is written only when it differs
from `origin`.

`annotatedBy` says who wrote the hints: exact model ids ("claude-opus-5",
never the "opus" alias a script passed) or one of ANNOTATORS, in the order the
runs happened, each once. Present exactly when the puzzle has hints; a puzzle
annotated from scratch starts the list afresh. tools/apply_annotations.py
writes it, reading the model off the running session's transcript;
tools/build_authored_puzzle.py is told with --annotated-by.

WHAT IS NOT KNOWABLE IS WRITTEN AS UNKNOWN. An invented provenance is worse
than an absent one: absent, someone goes and looks; invented, nobody does.
"""
import datetime
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import puzzle_schema  # noqa: E402
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

# Who wrote a puzzle's hints, when it was not a model. Everything else in
# `annotatedBy` is an exact model id and must match MODEL_ID.
ANNOTATORS = {
    "human": "written by hand by a person, with no model drafting them",
    "published": "taken from a published explanation of the puzzle (the "
                 "setter's or a blogger's), not written here",
    "unknown": "the hints are here and nothing that survives says who wrote "
               "them",
}

# An exact model id as the API reports it: claude-opus-5, claude-opus-5-5,
# claude-haiku-4-5-20251001. An alias ("opus") is refused, because it is a
# pointer that moves.
MODEL_ID = re.compile(r"claude-[a-z]+(?:-\d+)+")


def has_hints(puzzle):
    return any(e.get("annotation") for e in puzzle.get("entries") or [])


def credit_annotator(puzzle, who, had_hints):
    """The puzzle with `who` added to annotatedBy.

    `had_hints` is whether the file carried any hints BEFORE this write. When
    it did not, this run wrote every hint now in it, so the list restarts
    rather than keeping credits for hints that were removed.
    """
    if who not in ANNOTATORS and not MODEL_ID.fullmatch(who or ""):
        raise ValueError(f"{who!r} is neither an exact model id (claude-...) "
                         f"nor one of: " + ", ".join(sorted(ANNOTATORS)))
    credits = list(puzzle.get("annotatedBy") or []) if had_hints else []
    if who not in credits:
        credits.append(who)
    return place({**puzzle, "annotatedBy": credits})


# WHERE THE BYTES ACTUALLY CAME FROM — the publisher's own site, or somewhere
# else. source.url is the puzzle's CANONICAL page, the address a reader would
# cite, which is not always the address read. 492 Guardian
# puzzles and 50 of the 52 Metro ones were not read from those addresses at all
# — the paper had dropped the pages and they were recovered from Wayback
# captures. On disk that was invisible: a 2009 puzzle recovered from an archive
# looked identical to one fetched the morning it was published.
RETRIEVAL_CHANNELS = {
    "publisher": "read from the publisher's own live site or feed — source.url is "
                 "both the canonical address and the address actually fetched",
    "wayback": "the publisher no longer serves the page; it was recovered from a "
               "Wayback Machine capture. source.url is still the original "
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
    "tools/fetch_telegraph.py": {
        "channel": "publisher",
        "what": "puzzlesdata.telegraph.co.uk, the Telegraph Puzzles app's data bucket"},
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
    "tools/file_times_puzzles.py": {
        "channel": "blog",
        "what": "a times-for-the-times write-up's clue list and answers, the "
                "grid rebuilt from them by tools/times_grids.py"},
    "tools/file_telegraph_puzzles.py": {
        "channel": "blog",
        "what": "a bigdave44.com write-up's clue list and answers, the grid "
                "rebuilt from them by tools/times_grids.py"},
    "tools/ft_puzzles.py": {
        "channel": "blog",
        "what": "a fifteensquared write-up's clue list and answers, the grid "
                "rebuilt from them by tools/times_grids.py's search"},
    "tools/indy_puzzles.py": {
        "channel": "blog",
        "what": "a fifteensquared write-up of an Independent puzzle older than "
                "its feed, the grid rebuilt by tools/times_grids.py's search"},
    "tools/build_authored_puzzle.py": {
        "channel": "authored", "what": "set here, not fetched"},
    "unknown": {
        "channel": "unknown",
        "what": "the file no longer records which tool wrote it and the corpus "
                "cannot narrow it to one"},
}

# ------------------------------------------------- what each source can be
#
# Keyed by (series, source.url host) because neither alone decides it: the
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
    # Before the feed began (No 8,978) the only clue lists are fifteensquared's.
    ("independent", "fifteensquared.net"): ("tools/indy_puzzles.py",),
    ("indysunday", "fifteensquared.net"): ("tools/indy_puzzles.py",),
    ("cyclops", "www.private-eye.co.uk"): ("tools/fetch_privateeye.py",),
    ("telegraph", "www.telegraph.co.uk"): ("tools/fetch_telegraph.py",),
    ("toughie", "www.telegraph.co.uk"): ("tools/fetch_telegraph.py",),
    ("sundaytel", "www.telegraph.co.uk"): ("tools/fetch_telegraph.py",),
    ("sundaytough", "www.telegraph.co.uk"): ("tools/fetch_telegraph.py",),
    ("globeandmail", "www.theglobeandmail.com"): ("tools/fetch_globeandmail.py",),
    ("metro", "metro.co.uk"): ("tools/fetch_metro.py",
                               "tools/fetch_metro.py --wayback"),
    # Ours: set in this repo and never fetched, so there is no url and no host.
    ("authored", ""): ("tools/build_authored_puzzle.py",),
}
#: The tool that files a blog series' puzzles, by the blog it reads. A series
#: naming a blog missing here fails at import.
BLOG_FILER = {"timesforthetimes.co.uk": "tools/file_times_puzzles.py",
              "fifteensquared.net": "tools/ft_puzzles.py",
              "bigdave44.com": "tools/file_telegraph_puzzles.py"}
# Every book is its own series (see series.py), and they all arrive the same
# way, so they are generated rather than typed — a book added to series.py must
# not also need adding here.
for _series in series_table.SERIES:
    if is_book(_series):
        ACQUISITION_BY_SOURCE[(_series, "archive.org")] = (
            "tools/file_penguin_puzzle.py", "tools/acquire_book.py")
    if "blog" in series_table.meta(_series):
        _blog = series_table.meta(_series)["blog"]
        ACQUISITION_BY_SOURCE[(_series, _blog)] = (BLOG_FILER[_blog],)

# Series whose grid geometry is NOT the publisher's. Everything absent here is
# "published", and that is checked rather than assumed: the book filers and
# the blog filers are the only tools that BUILD a puzzle out of
# reconstruct_grid.py's output (grid_origin below) — every other fetcher parses
# a grid the source shipped, and puzzle_integrity.py's use of reconstruct_grid
# is a check on geometry that already exists, not a source of it.
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
# keyed by volume can only drift, and a puzzle whose source.url names one book
# while its source.book names another is exactly what that drift looks
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


# ------------------------------------------------------------ the file shape
#
# Key order is the schema's (puzzle_schema.order), not listed here.
SOURCE_REQUIRED = ("publisher", "retrievedFrom", "acquiredBy", "acquiredOn",
                   "gridOrigin")
#: The keys that back a claim that the answers are not the publisher's.
SOLUTION_DETAIL = ("blog", "url", "model", "date", "check", "officialKey")
#: What each non-published origin must carry.
DETAIL_REQUIRED = {"writeup": ("blog", "url", "date", "check"),
                   "model": ("model", "date", "check")}

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def source_url(puzzle):
    return (puzzle.get("source") or {}).get("url")


def host_of(url):
    return urlparse(url or "").netloc


def series_of_id(pid):
    """The series from the id, which every puzzle states — see series.parse_id,
    which this defers to. check() holds the `series` field to it."""
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


#: solutions.blog: the write-up sites answers are taken from.
WRITEUP_KINDS = ("fifteensquared", "timesforthetimes", "bigdave44")


def solution_detail(puzzle):
    """The keys of `solutions` that back a non-published origin; {} when none."""
    solutions = puzzle.get("solutions") or {}
    return {k: solutions[k] for k in SOLUTION_DETAIL if k in solutions}


def with_solution_detail(puzzle, detail):
    """The puzzle with its solution detail replaced by `detail` ({} drops it).

    `origin` and `previousOrigin` are kept for stamp() to re-derive, which is
    how a grid replaced by the publisher's key remembers it was once a guess.
    """
    solutions = {k: v for k, v in (puzzle.get("solutions") or {}).items()
                 if k not in SOLUTION_DETAIL}
    return {**puzzle, "solutions": {**solutions, **detail}}


def drop_solution_detail(puzzle):
    return with_solution_detail(puzzle, {})


def solution_origin_from_file(puzzle):
    """The solution origin the file's OWN contents establish, or None.

    None means the file does not settle it — it holds answers and no solution
    detail, which check() allows to be "published", "unknown" or "authored".
    """
    if not any((e.get("solution") or "").strip() for e in puzzle.get("entries") or []):
        return "unsolved"
    detail = solution_detail(puzzle)
    if "blog" in detail:
        return "writeup"
    if "model" in detail:
        return "model"
    return None


def grid_origin(series, url=None):
    """A book or blog puzzle's geometry was worked out from its clue list;
    everything else arrives with the grid the source published. The source's
    host decides as well as the series: a series whose own feed ships grids
    can hold puzzles read off a blog (the Independent before its feed began),
    and a blog series can hold puzzles read off its publisher's feed (the
    Telegraph's bucket, tools/fetch_telegraph.py)."""
    host = host_of(url)
    if is_book(series) or host in BLOG_FILER:
        return "reconstructed"
    if "blog" in series_table.meta(series) and not any(
            channel_of(t) == "publisher" for t in ACQUISITION_BY_SOURCE.get((series, host), ())):
        return "reconstructed"
    return GRID_ORIGIN_BY_SERIES.get(series, "published")


def channel_of(tool):
    """The retrieval channel a tool reads through."""
    return ACQUIRED_BY.get(tool, ACQUIRED_BY["unknown"])["channel"]


def derive(puzzle, claimed, acquired_on, previously=None):
    """The `source`, `solutions` and `annotatedBy` for a puzzle, from what is
    actually knowable.

    `claimed` is the tool the file already names as its acquirer; `acquired_on`
    is the ISO date the file first appeared in git, or None; `previously` is the
    origin this grid's answers had BEFORE the ones in it now — "model" for a
    grid we cold-solved and the paper has since confirmed, which only git
    remembers. Everything else comes off the puzzle and the tables above. Pure
    — it reads no files and no clock, so tools/backfill_provenance.py can be
    re-run to a fixed point.
    """
    series = series_of_id(puzzle["id"])
    old_source = puzzle.get("source") or {}
    old_solutions = puzzle.get("solutions") or {}
    tool = acquired_by(series, old_source.get("url"), claimed)
    source = {
        "publisher": series_table.publisher(series, puzzle["number"]),
        "url": old_source.get("url"),
        "retrievedFrom": channel_of(tool),
        "acquiredBy": tool,
        "acquiredOn": acquired_on if acquired_on else "unknown",
        "gridOrigin": grid_origin(series, old_source.get("url")),
        "feedId": old_source.get("feedId"),
    }
    book = book_of(series, puzzle["number"]) if is_book(series) else None
    if book:
        # The book's own number, not the file's: the file's carries the volume
        # (series.py, volume * 1000 + position) and the book prints No 18.
        book["numberInBook"] = position_of(series, puzzle["number"])
        source["book"] = book
    source = {k: v for k, v in source.items() if v is not None}

    origin = solution_origin_from_file(puzzle) or (
        "authored" if series == "authored" else
        old_solutions.get("origin") if old_solutions.get("origin") in
        ("unknown", "authored") else "published")
    solutions = {"origin": origin}
    # Carried across, not re-derived: which grids were once model-solved is
    # knowable only from git (see backfill_provenance.machine_solved_ever), and
    # the write that replaces a model fill is the last thing that knows it was
    # one. Only written when it differs from where the answers stand now.
    previously = (previously or old_solutions.get("previousOrigin")
                  or (old_solutions.get("origin") == "model" and "model"))
    if previously and previously != origin:
        solutions["previousOrigin"] = previously
    if origin in DETAIL_REQUIRED:
        solutions.update(solution_detail(puzzle))
    # Only the run that wrote the hints knew its model; dropped with the hints.
    credits = puzzle.get("annotatedBy") if has_hints(puzzle) else None
    return {"source": source, "solutions": solutions,
            "annotatedBy": credits or None}


def place(puzzle, fields=None):
    """The puzzle with `fields` set, its keys in the schema's order. A field
    set to None is removed."""
    return puzzle_schema.order({k: v for k, v in {**puzzle, **(fields or {})}.items()
                                if v is not None})


def stamp(puzzle, tool):
    """source/solutions/annotatedBy for a puzzle being written right now, by
    `tool`.

    Called from fetch_puzzle.write_puzzle_file, so EVERY write of a puzzle file
    goes through it and no fetcher can forget to record where its puzzle came
    from. `acquiredOn` is today only for a file that has never had it:
    the date a puzzle arrived does not change because something rewrote its
    annotations, and tools/backfill_provenance.py's git-derived dates must
    survive every later write.
    """
    acquired = (puzzle.get("source") or {}).get("acquiredOn") or today()
    return place(puzzle, derive(puzzle, tool, acquired))


# ------------------------------------------------------------ the validator
#
# Called by puzzle_integrity.check_provenance. Returns findings as strings, the
# shape every other check in that file returns.
def check(puzzle):
    findings = []
    pid = puzzle.get("id")
    source = puzzle.get("source")
    solutions = puzzle.get("solutions")
    if not isinstance(source, dict) or not isinstance(solutions, dict):
        return ["no source or no solutions block — where this puzzle and its "
                "answers came from is unrecorded (tools/backfill_provenance.py "
                "writes them)"]

    for key in SOURCE_REQUIRED:
        if key not in source:
            findings.append(f"source is missing {key}")
    if "origin" not in solutions:
        findings.append("solutions is missing origin")

    for block, name, key, allowed in (
            (source, "source", "gridOrigin", GRID_ORIGINS),
            (source, "source", "retrievedFrom", RETRIEVAL_CHANNELS),
            (source, "source", "acquiredBy", ACQUIRED_BY),
            (solutions, "solutions", "origin", SOLUTION_ORIGINS),
            (solutions, "solutions", "previousOrigin", SOLUTION_ORIGINS),
            (solutions, "solutions", "blog", WRITEUP_KINDS)):
        if key in block and block[key] not in allowed:
            findings.append(
                f"{name}.{key} is {block[key]!r}, which is not one of: "
                + ", ".join(sorted(allowed)))

    origin = solutions.get("origin")
    if "previousOrigin" in solutions and solutions["previousOrigin"] == origin:
        findings.append(
            f"solutions.previousOrigin repeats origin ({origin!r}) — it is only "
            f"written when the answers have since been replaced by ones of a "
            f"different origin")
    detail = solution_detail(puzzle)
    for key in DETAIL_REQUIRED.get(origin, ()):
        if key not in detail:
            findings.append(f"solutions.origin is {origin!r} but solutions has "
                            f"no {key}")
    implied = solution_origin_from_file(puzzle)
    if detail and origin not in DETAIL_REQUIRED and implied is None:
        findings.append(f"solutions.origin is {origin!r} but solutions carries "
                        f"{', '.join(detail)}, which only back a writeup or a "
                        f"model solve")
    if "blog" in detail and "model" in detail:
        findings.append("solutions names both a blog and a model")

    credits = puzzle.get("annotatedBy")
    if has_hints(puzzle) and not credits:
        findings.append("the puzzle has hints but annotatedBy does not say who "
                        "wrote them — tools/apply_annotations.py records it "
                        "when it writes them")
    elif credits is not None and not has_hints(puzzle):
        findings.append(f"annotatedBy is {credits!r} but the puzzle has no "
                        f"hints for anyone to have written")
    if credits is not None and has_hints(puzzle):
        if not isinstance(credits, list) or not credits:
            findings.append(f"annotatedBy is {credits!r} — want a non-empty list")
        else:
            for who in credits:
                if who not in ANNOTATORS and not (isinstance(who, str)
                                                  and MODEL_ID.fullmatch(who)):
                    findings.append(
                        f"annotatedBy has {who!r}, which is neither an exact "
                        f"model id (claude-...) nor one of: "
                        + ", ".join(sorted(ANNOTATORS)))
            if len(set(map(str, credits))) != len(credits):
                findings.append(f"annotatedBy repeats a name: {credits!r}")

    # The channel is a property of the tool, so it cannot be stated freely.
    expected_channel = channel_of(source.get("acquiredBy"))
    if "retrievedFrom" in source and source.get("acquiredBy") in ACQUIRED_BY \
            and source["retrievedFrom"] != expected_channel:
        findings.append(f"source.retrievedFrom is {source['retrievedFrom']!r} "
                        f"but {source.get('acquiredBy')!r} reads through "
                        f"{expected_channel!r}")

    # A source without a link cannot be checked by a human. An authored puzzle
    # has no source to link to.
    series = series_of_id(pid)
    if not source.get("url") and expected_channel != "authored":
        findings.append("source has no url — nothing to check it against")

    if puzzle.get("series") != series:
        findings.append(f"series is {puzzle.get('series')!r} but the id says "
                        f"{series!r}")
    expected_publisher = series_table.publisher(series, puzzle["number"])
    if source.get("publisher") != expected_publisher:
        findings.append(f"source.publisher is {source.get('publisher')!r} but "
                        f"series.py says {series!r} is published by "
                        f"{expected_publisher!r}")

    acquired_on = source.get("acquiredOn")
    if acquired_on != "unknown" and not (isinstance(acquired_on, str)
                                         and ISO_DATE.fullmatch(acquired_on)):
        findings.append(f"source.acquiredOn is {acquired_on!r} — want an ISO "
                        f"date or \"unknown\"")

    expected_grid = grid_origin(series, source.get("url"))
    if source.get("gridOrigin") not in (expected_grid, "unknown"):
        findings.append(f"source.gridOrigin is {source.get('gridOrigin')!r} but "
                        f"{series!r} grids are {expected_grid!r}")

    if implied is not None and origin != implied:
        findings.append(
            f"solutions.origin is {origin!r} but the file says {implied!r} ("
            + ("no entry carries an answer" if implied == "unsolved"
               else "from its " + ", ".join(detail)) + ")")
    elif implied is None and origin not in ("published", "unknown", "authored"):
        findings.append(f"solutions.origin is {origin!r} but the file carries "
                        f"answers and no solution detail to back that")

    if is_book(series):
        book = source.get("book")
        if not isinstance(book, dict):
            findings.append(f"{series} is book-sourced but source has no book block")
        else:
            for key in ("identifier", "title", "volume", "numberInBook"):
                if not book.get(key):
                    findings.append(f"source.book is missing {key}")
            # Both halves of the number are checked, because the number IS the
            # pair: a block that agreed on the position while naming another
            # volume would cite the wrong book and read as correct.
            want_volume = volume_of(series, puzzle["number"])
            want_position = position_of(series, puzzle["number"])
            if book.get("volume") != want_volume:
                findings.append(
                    f"source.book.volume is {book.get('volume')!r} but "
                    f"{puzzle.get('id')} is volume {want_volume}")
            if book.get("numberInBook") != want_position:
                findings.append(
                    f"source.book.numberInBook is {book.get('numberInBook')!r} "
                    f"but {puzzle.get('id')} is No {want_position} in its book")
    elif source.get("book"):
        findings.append(f"source has a book block but {series!r} is not book-sourced")

    return findings


def today():
    return datetime.date.today().isoformat()


# ---------------------------------------------------------- commit trailers
#
# A job's commit credits the models its commit ADDS to annotatedBy, read off
# the staged files, so the trailer names the model that ran rather than the
# alias the script passed it.
def display_name(model_id):
    """claude-opus-5-5 -> "Claude Opus 5.5"; a trailing date stamp is dropped."""
    family, *version = model_id.split("-")[1:]
    version = [v for v in version if len(v) < 8]
    return " ".join(["Claude", family.title()] + ([".".join(version)] if version else []))


def staged_annotators():
    """Model ids the staged puzzle files credit that HEAD's copies did not."""
    import json
    import subprocess

    def credits(spec):
        shown = subprocess.run(["git", "show", spec], capture_output=True, text=True)
        if shown.returncode:
            return []
        return json.loads(shown.stdout).get("annotatedBy") or []

    # A puzzle whose date moved it to another year folder is a rename; its
    # HEAD copy is the one it was renamed from.
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-M", "--", "puzzles/*/*/*.json"],
        capture_output=True, text=True, check=True).stdout.splitlines()
    added = []
    for line in staged:
        status, *paths = line.split("\t")
        if status == "D":
            continue
        old = credits(f"HEAD:{paths[0]}")
        for who in credits(f":{paths[-1]}"):
            if MODEL_ID.fullmatch(who) and who not in old and who not in added:
                added.append(who)
    return added


if __name__ == "__main__":
    if sys.argv[1:] != ["trailer"]:
        sys.exit("usage: python3 tools/provenance.py trailer   (one Co-Authored-By "
                 "line per model the staged puzzles newly credit)")
    for who in staged_annotators():
        print(f"Co-Authored-By: {display_name(who)} <noreply@anthropic.com>")
