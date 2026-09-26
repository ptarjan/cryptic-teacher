#!/usr/bin/env python3
"""Fetch a Guardian crossword and convert it to this app's puzzle format.

Usage:
  python3 tools/fetch_puzzle.py 30066            # fetch by number, any series
  python3 tools/fetch_puzzle.py --latest         # newest of EVERY series (see GUARDIAN_SERIES)
  python3 tools/fetch_puzzle.py --backfill [N] [series]
                                                 # fetch the last N puzzles (default 30)
                                                 # of one series (default cryptic) ending at
                                                 # the newest; skips ones already on disk and
                                                 # 404s; ~1s delay per request
  python3 tools/fetch_puzzle.py --extend [N] [series]
                                                 # the same walk in the other direction: N
                                                 # puzzles OLDER than the oldest we hold.
                                                 # Where more annotation work comes from.
  python3 tools/fetch_puzzle.py --reindex        # rebuild puzzles/index.json + index.js
                                                 # from the puzzle files already on disk
  python3 tools/fetch_puzzle.py --refresh-unsolved  # re-fetch puzzles still missing
                                                 # solutions (Saturday prize puzzles
                                                 # publish theirs about a week late)

Covers weekday cryptics, Saturday prize crosswords (one number sequence, two
URLs — six a week), the Monday Quiptic (the Guardian's beginner tier) and the
Sunday Everyman from the Observer. Each of the three runs its own number
sequence. See GUARDIAN_SERIES below.

Writes puzzles/<series>-<number>.js (preserving any existing per-clue
annotations), then rebuilds puzzles/index.json and puzzles/index.js. Commands
that take a puzzle still accept the bare number while it names only one.

Exit status for --latest: 0 and prints the puzzle number if a NEW puzzle was
downloaded, prints "up-to-date <n>" and exits 3 if nothing new was found.
"""

import hashlib
import html
import itertools
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import series as series_meta  # noqa: E402 — what each series IS; see tools/series.py
import provenance  # noqa: E402 — where each puzzle came from; see tools/provenance.py
import corroborate  # every other source we hold; see tools/corroborate.py

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; personal educational use)"}
# The three series this fetcher can reach, each with its own number sequence and
# its own Guardian series page. What each series IS — publisher, display name,
# how gentle — lives in tools/series.py, because the SEO builder and the backfill
# need it too and the Independent (tools/fetch_independent.py) is not fetched
# from here at all.
#
# cryptic — the daily, Monday–Saturday (nothing on Sunday). Saturday's is the
#   PRIZE crossword: same number sequence, different URL. Looking only at
#   /cryptic/ silently loses one puzzle in six — 30044, 30050, 30056… were all
#   missing here until "prize" was added. Prize solutions are withheld for about
#   a week, so a freshly-fetched prize puzzle has hasSolutions=false until
#   --refresh-unsolved picks it up again later.
# quiptic — the Guardian's beginner tier, Mondays, "for beginners and those in a
#   hurry". Added 2026-08-01 (Paul: "are there any easier puzzles, I'm finding
#   the guardian ones pretty hard"). Same page shape, same converter, solutions
#   published same-day.
# everyman — the Observer's Sunday cryptic, syndicated onto the Guardian site and
#   free like the rest. Added 2026-08-05, when Paul asked whether we could scrape
#   the Times. We can't: the Times never sends the grid to a signed-out browser
#   at all, so there is nothing to parse without a Puzzles subscription (probed
#   with a headless browser — the page fires no puzzle request whatsoever, it
#   just renders the subscribe wall). Everyman is the closest free stand-in and
#   arguably the better one for this site: it is the gentlest broadsheet cryptic
#   in print, deliberately fair, and it fills Sunday — the one day the Guardian
#   cryptic doesn't publish, so it adds a puzzle rather than competing for a slot.
#
# Every series counts upward from its own 1, so the number alone names a puzzle
# only by luck of the ranges — and the luck runs out. Ids are namespaced by
# series (series.puzzle_id) for that reason, so nothing here has to reason about
# which sequences happen to be far apart today. Numbers are still what gets
# DISPLAYED, and a bare one is still accepted on the command line while it names
# only one puzzle (resolve_puzzle).
GUARDIAN_SERIES = {
    "cryptic": {
        "label": "Cryptic",
        "index": ["https://www.theguardian.com/crosswords/series/cryptic",
                  "https://www.theguardian.com/crosswords/series/prize"],
        "link_re": r"/crosswords/(?:cryptic|prize)/(\d+)",
    },
    "quiptic": {
        "label": "Quiptic",
        "index": ["https://www.theguardian.com/crosswords/series/quiptic"],
        "link_re": r"/crosswords/quiptic/(\d+)",
    },
    "everyman": {
        "label": "Everyman",
        "index": ["https://www.theguardian.com/crosswords/series/everyman"],
        "link_re": r"/crosswords/everyman/(\d+)",
        # The Guardian ships no creator for these; the fallback byline is in
        # tools/series.py, along with the reason there isn't one.
        #
        # The Guardian's mirror of this series is bounded at both ends, not
        # unfetchable end to end. EVERYMAN_FLOOR (below) is the oldest page it
        # holds; 4,096 (2025-04-20) is the newest, and every number in between
        # still serves full clue data — confirmed at 2,965, 3,000, 3,549 and
        # 4,096. 4,097 and up 404 here: the Observer went to Tortoise Media in
        # April 2025 and nothing published since is on theguardian.com, only at
        # observer.co.uk (tools/fetch_observer.py). The series index page still
        # links to those newer ones, so backfill (which walks down from
        # whatever the index page calls newest) would spend a run 404ing
        # through the moved-away tail before it reached real puzzles — hence
        # moved_to still gates --backfill and --latest below. --extend walks
        # the OTHER direction, into the still-live range this mirror actually
        # serves, so it reads EVERYMAN_FLOOR instead of moved_to.
        #
        # The entry STAYS, because series_of() reads a puzzle's series off this
        # table and puzzles on disk numbered above 4,096 still say "everyman".
        "moved_to": "tools/fetch_observer.py (observer.co.uk, from no. 4097 on)",
    },
}
# The oldest Everyman page theguardian.com still serves. Checked 2026-09-18:
# 2,965 (2003-07-27) 200s and parses 28 clues clean; 2,964 and every number
# tried below it — 2,960, 2,950, 2,930, 2,900, 2,600 — 404 under every URL
# scheme this fetcher or tools/fetch_wayback.py has ever used. A wall, not
# patchiness.
EVERYMAN_FLOOR = 2965
# The oldest Guardian cryptic page theguardian.com still serves: a site-wide
# date wall at 1999-06-23, corroborated by the Guardian quick crossword
# walling at No. 9,093 on the same day. tools/coverage_report.py's
# ARCHIVE_FLOOR carries the same number for the coverage audit.
CRYPTIC_FLOOR = 21620
# Read by extend() to stop a walk at the oldest number a series' mirror will
# ever 200 on, instead of learning that one 404 at a time. Quiptic has no
# entry: nobody has walked it to a wall yet, so no floor is honest here.
FLOORS = {"everyman": EVERYMAN_FLOOR, "cryptic": CRYPTIC_FLOOR}
FETCHABLE = [s for s, spec in GUARDIAN_SERIES.items() if not spec.get("moved_to")]
# Tried in order for a bare number; the first that isn't a 404 wins. Everyman
# is here too — moved_to only marks the series' NEW end as gone, not this
# mirror's historical range (EVERYMAN_FLOOR..4096), which 200s like any other.
PUZZLE_URLS = [
    "https://www.theguardian.com/crosswords/cryptic/{num}",
    "https://www.theguardian.com/crosswords/prize/{num}",
    "https://www.theguardian.com/crosswords/quiptic/{num}",
    "https://www.theguardian.com/crosswords/everyman/{num}",
]

# The enumeration, and nothing else: the last parenthesised run at the end of a
# clue. Anchored to the end because cryptics put bracketed asides mid-clue, and
# Private Eye opens a linked clue with "(& 27ac.)" — the count is always last.
# Lives here rather than in tools/puzzle_integrity.py, which imports it, so the
# fetcher that writes the clue and the check that weighs it read the same rule.
ENUMERATION = re.compile(r"\(([^()]*)\)\s*$")

# Series whose LINKED clues are enumerated one light at a time, so a leg's count
# is its own and not the answer's — `perLightEnumeration` in tools/series.py.
# Private Eye does this: Cyclops 401's 2-down reads "(& 22dn.) … (4-6)" for its
# own ten cells while 22-down reads "see 2dn. (6)" for its six. The Guardian and
# the Independent do the opposite — the whole count on the leading clue,
# nothing at all on the continuations ("See 3"). dissolve_false_groups() reads a
# group's counts as evidence and tools/puzzle_integrity.py weighs the same
# counts in check_length, and both read this set.
PER_LIGHT_ENUMERATION = {s for s, m in series_meta.SERIES.items()
                         if m.get("perLightEnumeration")}

JSON_START = "/*JSON-START*/"
JSON_END = "/*JSON-END*/"


# A throttled request and a missing puzzle look identical to a walk: both are
# an exception where a page should have been. Every walker here reads that as
# "this number was never published" and moves on, so without these a throttled
# stretch is written into the archive as a run of holes, and a long enough one
# looks like the end of the archive and retires the source for the run.
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_WAITS = (5, 20, 60, 180)


def http_bytes(url, timeout=30):
    """One GET, backing off on the statuses that mean "not now" rather than
    "not here". Retry-After wins over our own schedule when the server sends
    one, capped so a silly value cannot park the walk for an afternoon."""
    for wait in RETRY_WAITS + (None,):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as err:
            if wait is None or err.code not in RETRY_STATUSES:
                raise
            try:
                wait = max(wait, min(float(err.headers.get("Retry-After")), 600))
            except (AttributeError, TypeError, ValueError):
                pass
            print(f"  HTTP {err.code} on {url} — waiting {wait:.0f}s")
        except urllib.error.URLError as err:
            if wait is None:
                raise
            print(f"  {err.reason} on {url} — waiting {wait}s")
        time.sleep(wait)


def http_get(url):
    return http_bytes(url).decode("utf-8")


TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
ITALIC_TAGS = {"i", "em"}


def visible(s):
    """Drop Unicode format characters (U+200B zero-width space, U+200E
    left-to-right mark and friends).

    They are not clue text. They render as nothing, they survive a paste out of
    a word processor into a paper's CMS, and a clue made only of them looks
    like a clue to everything downstream and is unsolvable by anyone. They also
    take up offsets that every annotation fragment then has to step over.
    """
    return "".join(c for c in s if unicodedata.category(c) != "Cf")


def clue_words(clue):
    """A clue's words, which an annotation is written against: letters and
    digits only, accents folded, case dropped. Punctuation, quotes, dashes and
    spacing are typography; any other difference is a different clue, and an
    annotation written for one does not describe the other."""
    folded = unicodedata.normalize("NFKD", plain_text(clue) or "")
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def has_words(clue):
    """A clue is content plus an enumeration. Strip the enumeration and there
    has to be something left, or the paper published nothing to solve.

    Something, not a letter, and not even a digit. A bare cross-reference is a
    whole clue — "␣␣␣␣␣ 9 (5)" is cryptic-30059 14-down, where the printed gap IS
    the wordplay and the 9 points at the rest of it. So is a clue with no
    alphanumerics at all: ")" is the whole of CLOSE BRACKETS, "?" of I HAVEN'T A
    CLUE, a line of morse of MORSE. Any character the setter printed is a clue,
    and only an empty remainder means the paper printed nothing to solve.

    Unicode format characters are already gone by the time this sees a clue —
    visible() and the italic-aware parser beside it both drop category Cf — so a
    clue built out of zero-width spaces is the empty string here, and still reads
    as blank rather than as punctuation the setter chose.
    """
    return bool(re.sub(r"\([\d,\-. ]*\)", "", clue).strip())


# What a continuation leg's clue is made of once its enumeration is off: the
# word "see", the numbers it points at, and the words that join them. Nothing
# else — "See 5 across out to find another date" is wordplay that opens the
# same way and must not read as a pointer (cryptic 27,884, the puzzle
# dissolve_false_groups was written for).
# The space after "see" is optional because the paper's markup does not always
# print one: cryptic-23101's 9-across reads "See10" and cryptic-24418's 19- and
# 20-across both read "See17". A \b there matches nothing between "e" and "1",
# so those three legs read as wordplay and their answers were stored short.
CONTINUATION = re.compile(
    r"(?i)^see(?![a-z])[\s\d,&.]*(?:(?:across|down|and|or|above|dn|ac)\b[\s\d,&.]*)*$")


def is_continuation(clue):
    """Is this clue nothing but a pointer at the light that carries the answer?

    "See 2", "See 1 down and 7", "See 23 13 across, or 11" — what the paper
    prints on the legs of a linked answer, and a clue with no wordplay in it.

    It matters because a count riding along with one — "See 2 (6)" on
    cryptic-23578's 7-down LOYOLA, six cells of IGNATIUS LOYOLA "(8,6)" — is the
    leg's OWN cell count and not a statement about the answer. The Guardian
    printed those routinely before about 2015. So a counted continuation is
    neither evidence that a group is false (dissolve_false_groups), nor a claim
    to lead the group it sits in (reconcile_groups), nor a length contradiction
    when it disagrees with the group's total (tools/puzzle_integrity.py
    check_length); all three ask here.
    """
    # Stripped of the ellipsis the paper chains consecutive clues with, because
    # a pointer wears it too: cryptic-21642's 5-down is "... see 22", the tail of
    # 22-down's own "... not to mention their friend ... (2,3,7,2,3,3)", and the
    # dots are the chain and not wordplay. Anchored on "see" without this, that
    # leg read as a clue of its own and TO SAY NOTHING OF THE DOG was stored as
    # its first two words. Leading dots only ever join a clue to its neighbour;
    # anything else in front of "see" still refuses, which is what keeps
    # "Follow, see 12 across" wordplay.
    return bool(CONTINUATION.match(
        ENUMERATION.sub("", clue or "").strip(" .…\t\n")))


# The exemption every rule about linked groups needs, stated once. Read by
# prune_one_sided_members below and by tools/validate_annotations.py
# check_groups_agree, which must agree about which disagreements are the
# paper's doing rather than a fetch's.
LEADERS_NAMED = re.compile(r"\s*See\s+([\d,\s and]+?)\.?\s*", re.IGNORECASE)


def leaders_named(clue):
    """How many leading clues a bare continuation ("See 19, 22") points at.

    A light can end MORE THAN ONE answer. Cryptic 28,687's 1-down is CLUB, the
    second word of both GOLDFISH CLUB (8,4) at 19-down and MONDAY CLUB (6,4) at
    22-down, and its clue reads "See 19, 22" — it names both. `group` is one
    list, so whichever answer it records the other leading clue disagrees with
    it and always will, and that disagreement is the paper's and not a fetch's.

    Zero for a clue with words of its own, which is not a continuation, and zero
    for a pointer that says anything beyond the numbers it names — a count, a
    direction, "or". That narrowness is the point: a continuation naming ONE
    leader is an ordinary leg and stays held to its group, which is what keeps
    the rules downstream worth anything.
    """
    m = LEADERS_NAMED.fullmatch(clue or "")
    return len(re.findall(r"\d+", m.group(1))) if m else 0


def flatten_clue(s):
    """HTML clue text -> (plain text, italic ranges into that text).

    Both papers ship clues as HTML: an italicised title arrives as
    "<span>Case for </span><i>Turandot</i><span> lyrics…</span>". Storing that
    markup was tried and is wrong — the app escapes puzzle text, so the solver
    read the tags (Paul, on the Independent, 2026-08-15) — but so is throwing
    it away, because the italics are part of the clue: "<i>Times</i>
    desperately stifling question" is telling you the newspaper, not the plural
    of time.

    So the clue stays ONE plain string and the italics travel beside it as
    [start, length] ranges. The string has to stay plain because every
    annotation fragment is found in it with indexOf and highlighted by
    character offset; a tag in the middle would move every offset after it.
    Ranges are just a second list over the same offsets, so the two agree by
    construction, and app.js can cut the clue at the boundaries of both.

    The flatten runs character by character rather than as a regex sub so that
    unescaping entities and collapsing runs of whitespace — both of which
    change the length — carry the italic flags along with the characters they
    belong to.
    """
    # Nothing to flatten, so nothing is touched. Collapsing whitespace in a
    # clue that never had markup would edit the paper's own text — the
    # Independent really does print "Unsuitable pix?  I need ten developed" —
    # and worse, silently move every annotation offset in a file that had no
    # problem to fix.
    if "<" not in s and "&" not in s:
        return visible(s), []

    chars, depth, pos = [], 0, 0
    for m in TAG_RE.finditer(s):
        chars.extend((c, depth > 0) for c in html.unescape(s[pos:m.start()]))
        if m.group(2).lower() in ITALIC_TAGS:
            depth = max(0, depth + (-1 if m.group(1) else 1))
        pos = m.end()
    chars.extend((c, depth > 0) for c in html.unescape(s[pos:]))

    out = []
    for c, italic in chars:
        if unicodedata.category(c) == "Cf":
            continue
        if not c.isspace():
            out.append((c, italic))
        elif out and not out[-1][0].isspace():
            out.append((" ", italic))
    while out and out[-1][0].isspace():
        out.pop()

    ranges, start = [], None
    for i, (_, italic) in enumerate(out):
        if italic and start is None:
            start = i
        elif not italic and start is not None:
            ranges.append([start, i - start])
            start = None
    if start is not None:
        ranges.append([start, len(out) - start])
    return "".join(c for c, _ in out), ranges


def plain_text(s):
    """The text half of flatten_clue, for the strings that have no ranges to
    keep — annotation fragments, definitions, walkthroughs. Defined in terms of
    flatten_clue so the two can never disagree about where a character lands."""
    return flatten_clue(s)[0] if isinstance(s, str) else s


def extract_crossword_data(page_html):
    m = re.search(r'<gu-island name="CrosswordComponent"[^>]*props="([^"]*)"', page_html)
    if not m:
        # Not a SystemExit: walk()'s "malformed page etc. — keep going" handler
        # only catches Exception. A SystemExit here (found live 2026-09-17,
        # probing the pre-digitization archive floor) escapes that handler and
        # kills the whole backfill/extend walk on the first old-format page,
        # silently truncating every run after it to "whatever came before this
        # number" with no error attributed to the number that actually failed.
        raise ValueError("Could not find CrosswordComponent data in page")
    return json.loads(html.unescape(m.group(1)))["data"]


def puzzle_path(series, number):
    """The one place a puzzle's file name is spelled. Every other module asks
    here, so the day the id format changes again it changes once."""
    return PUZZLE_DIR / f"{series_meta.puzzle_id(series, number)}.json"


def puzzle_files():
    """Every puzzle file and nothing else in puzzles/ — not index.json, not the
    static answer pages, and not the generated .js shims. Matched off the id
    shape, so adding a series needs no change here."""
    return sorted(PUZZLE_DIR.glob("*-[0-9]*.json"))


def resolve_puzzle(arg):
    """A puzzle file from either a namespaced id ("everyman-4165") or the bare
    number a person types ("4165").

    Bare numbers are what every URL, prompt and habit used before namespacing,
    so they keep working — but only while one names exactly one puzzle. An
    ambiguous number is an error naming both candidates, never a guess: guessing
    would annotate one paper's grid from another paper's clues.
    """
    # Everything puzzle-shaped, not just what the nightly sweep walks: an
    # authored draft (puzzles/A001.json) is deliberately outside puzzle_files(),
    # and naming one by hand is exactly how it gets validated. index.json is the
    # generated manifest, not a puzzle, and it is the only sibling that would
    # otherwise answer to a bare name here.
    files = [p for p in sorted(PUZZLE_DIR.glob("*.json")) if p.stem != "index"]
    exact = [p for p in files if p.stem == str(arg)]
    if exact:
        return exact[0]
    hits = [p for p in files if p.stem.rpartition("-")[2] == str(arg)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"no puzzle {arg} in {PUZZLE_DIR}")
    raise SystemExit(f"{arg} names more than one puzzle — say which: "
                     + ", ".join(p.stem for p in hits))


def shim_path(path):
    """The generated script the browser loads for a puzzles/<id>.json."""
    return path.with_suffix(".js")


def write_shim(path, puzzle):
    """Regenerate puzzles/<id>.js from the puzzle in puzzles/<id>.json.

    The site is openable from file:// (README), where fetch() is blocked, so
    app.js loads each puzzle by injecting a <script> tag. That is the only
    reason this form exists: it is build output, gitignored, and hand edits to
    it are overwritten by the next --build-shims. The source of truth is the
    .json next to it.

    The bytes are deliberately the ones this project wrote before the .json
    became the committed form. index.json's ?v= hash and make_og_card's card_key
    are both taken off these bytes, so a gratuitous change to the banner would
    invalidate every cached OG card and every browser's copy of every puzzle at
    once, to say nothing new.
    """
    payload = json.dumps(puzzle, indent=1, ensure_ascii=False)
    acquirer = (puzzle.get("provenance") or {}).get(
        "acquiredBy") or "tools/fetch_puzzle.py"
    shim_path(path).write_text(
        f"// Generated by {acquirer} — puzzle © its original publisher.\n"
        "// Annotations (type/definition/indicators/blocks/walkthrough) are original\n"
        "// to this project. Edit the annotation objects freely; keep the JSON markers.\n"
        "window.CRYPTIC_PUZZLES = window.CRYPTIC_PUZZLES || {};\n"
        f'window.CRYPTIC_PUZZLES["{puzzle["id"]}"] = {JSON_START} {payload} {JSON_END};\n',
        encoding="utf-8")


def build_shims():
    """Every puzzle's script shim, for a checkout that has only the .json files.

    Called from reindex() rather than left as a step for each workflow to
    remember: the index hashes the shim bytes, so indexing without building is
    not a thing that can be correct.
    """
    built = 0
    for path in puzzle_files():
        write_shim(path, read_puzzle_file(path))
        built += 1
    return built


def read_puzzle_file(path):
    """The puzzle in puzzles/<id>.json. Plain JSON — the file IS the payload."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        raise SystemExit(f"{path}: not valid JSON — {err}")


def generator_of(path):
    """The tool provenance already names as the acquirer, or the default for a
    new file.

    This records what ACQUIRED the puzzle, which is a fact about the fetcher and
    not about whichever tool most recently rewrote the annotations inside it.
    Restamping it destroys the acquisition record — and did: four files ended up
    claiming apply_solution.py, and blind_annotate.py's restore path put the
    plain default back over whatever a non-Guardian fetcher had written.
    Preserving is therefore the DEFAULT below, so a caller cannot silently
    relabel a puzzle by forgetting an argument; a fetcher that really is the
    acquirer says so explicitly.

    provenance.acquiredBy is the record, and the only one. It used to be stated
    twice — here in a banner comment and again inside the JSON — and the two
    drifted apart on 108 files, every one of which had the banner wrong and
    provenance right, because provenance.acquired_by() derives the fetcher from
    the series while a banner only repeats whatever string a caller passed.
    """
    if not path.exists():
        return "tools/fetch_puzzle.py"
    prov = read_puzzle_file(path).get("provenance") or {}
    return prov.get("acquiredBy") or "tools/fetch_puzzle.py"


def write_puzzle_file(path, puzzle, generator=None, retrieved_url=None):
    # The file is named by the id, and the id carries the series, so two papers
    # that reach the same number cannot land on the same file — the collision is
    # impossible rather than guarded against. This assert is the one thing left
    # that could break that: a caller writing a puzzle to a path it did not get
    # from puzzle_path().
    assert path.name == f"{puzzle['id']}.json", (
        f"{path.name} is not where {puzzle['id']} goes — that is "
        f"{puzzle['id']}.json. Ask puzzle_path() for it.")
    old = read_puzzle_file(path) if path.exists() else None
    generator = generator or generator_of(path)
    # Every write is corroborated against the other sources we hold for the
    # puzzle, here, so that a new fetcher cannot skip it. See tools/corroborate.py.
    puzzle = corroborate.corroborate(puzzle)
    # A puzzle built fresh from a page has no provenance yet; the file's own
    # says when it was acquired, and re-fetching it does not change that.
    if old is not None and "provenance" not in puzzle and old.get("provenance"):
        puzzle = {**puzzle, "provenance": old["provenance"]}
    # Every write of a puzzle file records where the puzzle came from, here,
    # rather than in each of the nine tools that write one. See
    # provenance.stamp.
    puzzle = provenance.stamp(puzzle, generator, retrieved_url)
    # Every write goes through the corpus sweep's per-puzzle checks, so no
    # fetcher can write what tools/puzzle_integrity.py would report.
    import puzzle_integrity  # noqa: PLC0415 — it imports this module
    puzzle_integrity.refuse_bad_write(puzzle, old)
    path.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    # The browser cannot fetch() off file:// (README: the site runs from disk),
    # so it is fed a generated script instead. Written here as well as by
    # --build-shims because a fetcher that has just rewritten a puzzle must not
    # leave the copy the site loads showing yesterday's.
    write_shim(path, puzzle)


def series_of(page_id):
    """Which GUARDIAN_SERIES a puzzle belongs to, read off the page's own id
    ("crosswords/quiptic/1393") rather than off whichever URL happened to answer,
    so a re-fetch through a different route can never relabel a puzzle.

    Unrecognised means cryptic, and that is a fact rather than a guess: the
    cryptic is the only series with two URLs, because Saturday's PRIZE crossword
    shares its number sequence and its page id says "crosswords/prize/30074".
    Everything else lives under its own name. Written as a scan over GUARDIAN_SERIES so
    that adding a series is one dict entry and no branch anywhere needs finding.
    """
    for name in GUARDIAN_SERIES:
        if f"/{name}/" in "/" + page_id:
            return name
    return "cryptic"


def _cuts_into(counts, lengths):
    """Can `counts` be cut into consecutive runs summing to each of `lengths`?

    "(4,5,5,2,1,3)" over ROME / WASNT / BUILTIN / ADAY is 4 | 5 | 5,2 | 1,3 —
    one light can hold several enumerated words, so this is a partition test
    and not a pairing.
    """
    i = 0
    for n in lengths:
        got = 0
        while got < n and i < len(counts):
            got += counts[i]
            i += 1
        if got != n:
            return False
    return i == len(counts)


def _subset_that_fits(lead, rest, counts, by_id):
    """The lights of `rest` the leader's enumeration actually counts, and the ones
    it does not. Both empty when the answer is not decided by arithmetic alone.

    Asked only when NO arrangement of the whole closure cuts into the leader's
    count, which is the union having gone too far. The Guardian's older markup
    writes a themed puzzle's cross-references as pairs — cryptic-23228 hangs six
    lines of Wordsworth's Lucy off 9-across, each leg storing [9-across, itself]
    — and a union over pairs sharing one hub makes eight lights of what the clue
    counts as two. The leading clue counts its whole answer and nothing else, so
    the subset its counts cut into is the answer; the rest were never in it.

    Taken only when exactly one subset cuts, for reconstruct_groups' reason: two
    readings that both add up are two answers this data cannot tell apart.
    """
    if len(rest) > RECONSTRUCT_LIMIT:
        return [], []
    found = {}
    for size in range(1, len(rest)):
        for sub in itertools.combinations(rest, size):
            ok = [tail for tail in itertools.permutations(sub)
                  if _cuts_into(counts, [by_id[m]["length"] for m in (lead, *tail)])]
            if ok:
                found[frozenset(sub)] = ok
    if len(found) != 1:
        return [], []
    (keep, ok), = found.items()
    return ok, [m for m in rest if m not in keep]


def reconcile_groups(entries):
    """Make every member of a linked clue name the same group.

    The Guardian writes a `group` on each entry, and on one puzzle in the corpus
    the members disagree: Prize 29,069's 3-down says [3-down, 21-across] while
    13-across says [3-down, 13-across], so LONDON SYMPHONY ORCHESTRA is stored
    as two answers that hold 15 of the clue's promised 23 letters. A linked
    group is an equivalence class — if 13-across is grouped with 3-down then it
    is grouped with everything 3-down is — so the union is the only reading the
    paper's own data supports, and taking it costs nothing on the 4,339 groups
    whose members already agree (they are left untouched, order included).

    The union fixes membership; ORDER then comes from the clue, because the
    members' lists do not settle it. The leading light carries the enumeration
    for the whole answer, so the one arrangement whose lights the enumeration
    cuts into is the answer's own word order: (6,8,9) over LONDON 6, SYMPHONY 8,
    ORCHESTRA 9 admits 3-down, 13-across, 21-across and nothing else. If the
    enumeration leaves it open the leader's stated order is kept and the
    newcomers are appended in grid reading order, which is a guess — but a
    guess about display order only, after the membership is already right.
    """
    by_id = {e["id"]: e for e in entries}
    closure = {}
    for e in entries:
        for eid in e.get("group") or []:
            closure.setdefault(eid, set()).update(e["group"])
    merging = True
    while merging:                      # groups are tiny; this settles at once
        merging = False
        for eid, members in closure.items():
            grown = members.union(*(closure.get(m, {m}) for m in members))
            if grown != members:
                closure[eid], merging = grown, True

    for members in {frozenset(v) for v in closure.values()}:
        if len(members) < 2 or not members <= set(by_id):
            continue
        stated = [by_id[m].get("group") or [] for m in members]
        if all(set(s) == members for s in stated):
            continue                    # the paper already agrees with itself
        # A light whose own clue is a bare pointer does not lead, however the
        # paper ordered the pair it wrote. The Guardian's older markup writes
        # every link as a two-element group that names ITSELF first, so in a
        # chain (26 pairs with 8, 26 pairs with 17, 17 pairs with 20) the middle
        # light claims to lead on nothing but list order, and the count riding
        # on its "See 26 (7,8)" is its own legs' cells, never the answer's.
        # Counted as a claimant it wins the election against the real leading
        # clue and takes the whole group down with it: cryptic-22249 lost
        # EVERYONE SUDDENLY BURST OUT SINGING that way, 31 cells read as 8.
        leads = {s[0] for s in stated
                 if s and not is_continuation(by_id[s[0]].get("clue"))}

        # Several lights each claiming to lead. The enumeration settles it,
        # because a leading clue counts its WHOLE answer: weigh each claimant's
        # own count against the lights it own claims, and the claim that does not
        # add up is the one to drop. Cryptic 28,627 resolves its bare "See 22" to
        # 22-across, whose own finished clue reads "(6)" for a six-letter OPTICS,
        # making a ten-letter answer out of a six-letter count; 22-down's "(5-4)"
        # over ORANG and UTAN is exactly nine. So 22-down leads, and 22-across —
        # in the closure only because the paper put it there — has its group
        # removed and goes back to being its own answer.
        if len(leads) > 1:
            def adds_up(claim):
                said = ENUMERATION.search(by_id[claim]["clue"] or "")
                own = [m for m in by_id[claim].get("group") or []]
                return bool(said) and _cuts_into(
                    [int(n) for n in re.findall(r"\d+", said.group(1))],
                    [by_id[m]["length"] for m in own])
            winners = [c for c in sorted(leads) if adds_up(c)]
            if len(winners) != 1:
                # Every claim adds up, so they are all true and the light they
                # share is in more than one answer — cryptic 28,687's 1-down CLUB
                # ends both GOLDFISH CLUB (8,4) and MONDAY CLUB (6,4), and its own
                # clue says "See 19, 22". `group` holds one list, so it cannot say
                # that; each leading clue keeps its own reading, which is the most
                # the field can carry and is what the paper published.
                print(f"WARNING: {'/'.join(sorted(members))}: "
                      + ("a light shared by several answers — left as published"
                         if winners else "no claim on this group adds up — left alone"),
                      file=sys.stderr)
                continue
            keep = by_id[winners[0]].get("group") or []
            for m in members:
                by_id[m]["group"] = list(keep) if m in keep else None
                if by_id[m]["group"] is None:
                    del by_id[m]["group"]
            print(f"WARNING: {winners[0]}'s group was contested; reading it as "
                  + " + ".join(keep), file=sys.stderr)
            continue

        rest = sorted(members - leads, key=lambda m: (by_id[m]["position"]["y"],
                                                      by_id[m]["position"]["x"]))
        if not leads:
            continue
        lead = leads.pop()
        said = ENUMERATION.search(by_id[lead]["clue"] or "")
        counts = [int(n) for n in re.findall(r"\d+", said.group(1))] if said else []
        fits = [tail for tail in itertools.permutations(rest)
                if _cuts_into(counts, [by_id[m]["length"] for m in (lead, *tail)])]
        freed = []
        if not fits and counts:
            fits, freed = _subset_that_fits(lead, rest, counts, by_id)
            rest = [m for m in rest if m not in freed]
        if len(fits) == 1:
            order = [lead, *fits[0]]
        else:
            named = [m for m in by_id[lead].get("group") or []
                     if m != lead and m in rest]
            order = [lead, *named, *(m for m in rest if m not in named)]
        print(f"WARNING: {lead}'s group was stated inconsistently; reading it as "
              + " + ".join(order)
              + (f", leaving {' + '.join(freed)} out of it" if freed else ""),
              file=sys.stderr)
        for m in freed:
            del by_id[m]["group"]
        for m in order:
            by_id[m]["group"] = order


def _own_count(entry):
    """What an entry's own clue says its answer counts, or None if it says nothing."""
    said = ENUMERATION.search(entry.get("clue") or "")
    if not said:
        return None
    counts = [int(n) for n in re.findall(r"\d+", said.group(1))]
    return sum(counts) if counts else None


def prints_own_count(entry):
    """Is the count beside this clue its own light's cells, not the answer's?

    Two shapes, both from the Guardian's pre-2015 markup. A counted pointer —
    "See 2 (6)" — which is_continuation settles. And a leg the pointer was lost
    from altogether, left wordless over a single number that is exactly its own
    light: cryptic-21762's 26-across is " (8)" over the AURELIUS that finishes
    25-across MARCUS "(6,8)".

    An enumeration that cuts the light into WORDS is an answer's count and not a
    light's, wordless or not — cryptic-29345's "(1,6,3,1,4)" over I HAVEN'T GOT
    A CLUE is a finished answer whose joke is that nothing is printed to solve.

    Read by _spare_light, to know which wordless lights a linked answer may be
    put back together from, and by tools/puzzle_integrity.py check_length, so
    that a leg counting its own cells is not read as the group's enumeration and
    reported against it. One rule, because the two must agree about it.
    """
    clue = entry.get("clue")
    if is_continuation(clue):
        return True
    said = ENUMERATION.search(clue or "")
    if not said or ENUMERATION.sub("", clue or "").strip():
        return False
    return (_own_count(entry) == entry.get("length")
            and len(said.group(1).strip().split(",")) == 1)


def prune_one_sided_members(entries):
    """Drop every group that names a light not in it. Returns (id, group) per
    entry it frees.

    A group is the lights one answer is spread over, and the paper writes it on
    every one of them. So a light that is not in the puzzle at all, or that
    stores a group of its own instead, is not in this one — the membership is
    stated by one side only, and there is nothing on the other side to hold it
    up. The Guardian's pre-2015 markup produced both:

      A light that does not exist — cryptic-24640's 13-across and 17-across are
      grouped with "18-down", and the puzzle has an 18-ACROSS holding the NEW of
      FROM THE NEW WORLD. Which light was meant is not in the data, and reading
      the direction as a typo would be writing a membership the paper never
      stated.

      A light that is in another answer — cryptic-25126's 6-down "(4,5)" claims
      20-across for ASIA MINOR while 20-across stores MAJOR AND MINOR, and
      cryptic-27173's 25-across LINCOLN "(7)" claims 23-down OXFORD, which is a
      cathedral in the theme and not half of an answer.

    The whole group goes, never the naming alone: the lights that are left are
    an answer with a hole in it, and shortening the group to them would say the
    letters are all here when the paper said they are not. Cryptic-24640 is the
    case that settles it — drop "18-down" from 13-across's group and FROM THE +
    WORLD is stored as a finished answer with the NEW missing out of the middle.
    An unlinked light is a true statement about a puzzle; a short answer is not.

    What may be rebuilt from the paper's arithmetic is rebuilt by
    reconstruct_groups, which runs after this and is the one rule that decides
    which lights an enumeration covers. This one only takes away what nothing
    supports.

    A light whose own clue names SEVERAL leading clues is exempt and holds any
    group it is named in: it ends more than one answer, so it cannot store every
    group it is in and its silence is not evidence against anybody's claim. See
    leaders_named, which tools/validate_annotations.py check_groups_agree asks
    the same way — the fetcher and that check must exempt the same clues, or one
    of them is writing what the other rejects.

    Run AFTER reconcile_groups, which is the chance for a disagreement to be
    read rather than pruned: a group that survives reconcile contested is one it
    declined to settle, and every rule after this one — dissolve_false_groups,
    reconstruct_groups — reads a group its members agree about.
    """
    by_id = {e["id"]: e for e in entries}
    stated = {e["id"]: list(e["group"]) for e in entries if e.get("group")}
    pruned = []
    for eid, group in sorted(stated.items()):
        if len(group) < 2 or eid not in group:
            continue
        one_sided = [m for m in group
                     if m != eid and (m not in by_id
                                      or (stated.get(m) != group
                                          and leaders_named(by_id[m].get("clue")) < 2))]
        if not one_sided:
            continue
        del by_id[eid]["group"]
        pruned.append((eid, group))
        print(f"WARNING: {eid}: {' + '.join(one_sided)} is in no group with it, "
              f"so {' + '.join(group)} is an answer with a light missing "
              "— group dropped", file=sys.stderr)
    return pruned


def dissolve_false_groups(entries, series):
    """Take out of a linked group every light that is a whole answer already.
    Returns the lists of lights removed, one per group it touched.

    A linked answer is enumerated ONCE, on the leading light, for the whole
    phrase: cryptic-29069's 3-down says "(6,8,9)" and its two continuations say
    "See 3". So a light whose own clue counts exactly its own cells has already
    told the solver that light is finished, and it is not carrying part of
    anybody else's answer — whatever the paper's `group` says. Cryptic 27,884's
    20-across is "See 5 across out to find another date (10)", where "See 5" is
    the wordplay; the Guardian grouped it with 5-across LURCHED "(7)" and left
    RESCHEDULE stored as half of a seventeen-letter answer that nobody wrote.

    Weighed per light rather than over the whole group, because the two shapes
    it takes need different answers and the older markup is full of both:

      Every member counts itself — 27,884 above, and cryptic-23987's DIS, TEN,
      CON and TED, four three-letter answers the paper linked because three of
      them read "See 13". Nothing here is linked to anything; the group goes.

      One member counts itself and the rest are bare "See 22" continuations —
      cryptic-23468's 8-down HEAD "(4)" with 26-across LIGHT "See 8". HEAD is
      complete at four letters, so LIGHT is its own answer too and the group
      goes with it, there being nothing left for it to link.

      One member counts itself and two or more real legs remain — cryptic-25430,
      where the Guardian hung 19-down ALL RIGHT "(3,5)" off the group carrying
      NATURE I LOVED AND NEXT TO NATURE ART. Only the intruder leaves; the
      answer that was really there keeps its remaining lights.

    A bare continuation is never the intruder, however it is counted: "See 2 (6)"
    is the Guardian's older way of printing the leg's own cell count beside the
    pointer, and it says nothing about whether the link is real. See
    is_continuation.

    Gated off for PER_LIGHT_ENUMERATION series, where a full count on every leg
    is the house style rather than evidence of anything: dissolving Cyclops
    401's 2-down/22-down would break 1,538 clues that are exactly as published.

    Run AFTER reconcile_groups, and only over groups whose members already agree
    about their membership — a group still contested there is one reconcile
    declined to read, and reading it here would be a second opinion.
    """
    if series in PER_LIGHT_ENUMERATION:
        return []
    by_id = {e["id"]: e for e in entries}
    dissolved, seen = [], set()
    for e in entries:
        members = e.get("group") or []
        if len(members) < 2 or frozenset(members) in seen:
            continue
        seen.add(frozenset(members))
        if not set(members) <= set(by_id):
            continue
        if any(set(by_id[m].get("group") or []) != set(members) for m in members):
            continue
        # The paper's own arithmetic first: if any light's count covers the whole
        # group, the group IS one answer and nothing below applies. Cryptic
        # 29,069's 3-down says "(6,8,9)" over LONDON, SYMPHONY and ORCHESTRA,
        # and its legs may carry full clues and counts of their own — which is
        # the shape a false link has too, so the total is what tells them apart.
        total = sum(by_id[m].get("length") or 0 for m in members)
        if any(_own_count(by_id[m]) == total for m in members):
            continue
        carriers = [m for m in members if not is_continuation(by_id[m].get("clue"))]
        complete = [m for m in carriers
                    if _own_count(by_id[m]) == by_id[m].get("length")]
        if not complete and carriers:
            continue
        keep = [m for m in members if m not in complete]
        counters, every = list(complete), not keep
        if len(keep) < 2 or all(is_continuation(by_id[m].get("clue"))
                                for m in keep):
            # What is left is not an answer: one light cannot be a linked one,
            # and a set of bare "See 13" legs with nothing that carries a clue
            # is four answers the paper cross-referenced (cryptic-23987's DIS,
            # TEN, CON and TED), not one spread over four lights. Either way the
            # group goes; the pointer survives in the clue text, where the paper
            # put it.
            complete, keep = list(members), []
        for m in complete:
            del by_id[m]["group"]
        for m in keep:
            by_id[m]["group"] = keep
        dissolved.append(list(complete))
        if keep:
            print(f"WARNING: {' + '.join(complete)}: counts its own light in "
                  f"full, so it is not part of {' + '.join(keep)}'s answer — "
                  "taken out of the group", file=sys.stderr)
            continue
        print(f"WARNING: {' + '.join(members)}: "
              + ("every light carries a full enumeration of its own"
                 if every else
                 f"{' + '.join(counters)} counts its own light in full and "
                 "what is left carries no clue of its own")
              + ", so this is a cross-reference in the "
              "wordplay and not a linked answer — group dissolved",
              file=sys.stderr)
    return dissolved


# The number a pointer names, and the direction if it bothers to say: "See 16",
# "See 16 Down", "see 19 across", "See 23 13 across, or 11". Only ever applied to
# a clue is_continuation has already agreed is nothing but a pointer, so every
# number in it is a light it points at.
POINTER = re.compile(r"(\d+)\s*(across|down|ac|dn)?\b", re.I)
SHORT_DIRECTIONS = {"ac": "across", "dn": "down"}

# The most lights one answer may be reassembled over. The search is every subset
# of the spare lights against every order of the result, so it has to stop
# somewhere; the longest linked answer in the corpus runs to six lights, and
# nothing that needs more than this is being reconstructed from an enumeration
# anyway.
RECONSTRUCT_LIMIT = 9


def _points_at(entry, lead, entries):
    """Does this pointer name `lead`?

    A pointer that names no light at all — cryptic-23816's 10-across "See above",
    printed under the clue it continues — names whatever it turns out to fit, and
    the enumeration is left to say which. A pointer that names lights names only
    those, and a direction it states is held to: "See 16 Down" is not about
    16-across.

    A number no OTHER light in the grid carries names nothing either, and is
    dropped before that test: everyman-3306's 17-across is "See 17" over fourteen
    cells, and 17-across is the only light numbered 17, so the pointer has lost
    whatever it was printed to name. A number without a direction is the paper's
    ordinary way of naming the other light of that number — "See 1" on 1-down is
    1-across, thirteen times in this corpus — which is why the light's own number
    is dropped only when no other light answers to it. What is left when every
    number goes is "See above": the enumeration says which light it is, or
    nothing does.
    """
    named = [(int(n), SHORT_DIRECTIONS.get(d.lower(), d.lower()) or None)
             for n, d in POINTER.findall(ENUMERATION.sub("", entry.get("clue") or ""))]
    named = [(n, d) for n, d in named
             if any(o["id"] != entry["id"] and o["number"] == n
                    and d in (None, o["direction"]) for o in entries)]
    return not named or any(n == lead["number"] and d in (None, lead["direction"])
                            for n, d in named)


def _spare_light(entry, lead, entries):
    """Is this light free to be part of `lead`'s answer, on the paper's own say-so?

    Two shapes qualify, and both are the paper saying this light is not an answer
    by itself. A pointer naming the lead — "See 16", "See 1 across and 9" — is the
    Guardian's continuation leg, which is_continuation settles. And a light the
    paper printed NO clue for is a leg whose pointer the old markup lost outright:
    cryptic-23609's 8-down RUST arrives with an empty clue beside 7-down's "Doubt
    if small droplets corrode (8)", which counts eight cells over a four-cell
    light.

    Nothing else is spare. A light carrying words of its own is an answer of its
    own, whatever it crosses, and a blank one that still states a count is
    complete as it stands — cryptic-29345's 5-down is wordless over "(1,6,3,1,4)"
    because I HAVEN'T GOT A CLUE is the joke, and it is finished. A counted
    continuation is exempt from that, as everywhere else: "See 2 (6)" is the leg's
    own cell count printed beside the pointer, not a claim to be a whole answer.

    A light the paper has already put in somebody else's group is not spare
    either. One `group` field cannot say that a light ends two answers —
    cryptic-24951's 24-across THE is in both SET THE CAT AMONG THE PIGEONS and
    LET THE DOG SEE THE RABBIT — so taking it would be quietly deciding which
    answer loses it.
    """
    group = entry.get("group") or []
    if len(group) > 1 and lead["id"] not in group:
        return False
    clue = entry.get("clue")
    if is_continuation(clue):
        return _points_at(entry, lead, entries)
    if ENUMERATION.sub("", clue or "").strip():
        return False
    # Wordless, so the only question is what the count beside it counts. One
    # number equal to this light's own cells is the leg's cell count, printed
    # the way "See 2 (6)" prints it with the pointer gone: cryptic-21762's
    # 26-across is " (8)" over the AURELIUS that finishes 25-across MARCUS
    # "(6,8)". An enumeration that cuts the light into WORDS is an answer,
    # finished as it stands — cryptic-29345's "(1,6,3,1,4)" over I HAVEN'T GOT
    # A CLUE — and so is a count that is not this light's at all.
    return _own_count(entry) is None or prints_own_count(entry)


def _word_splits(counts, lengths):
    """How many of these lights start in the middle of an enumerated word.

    Zero is what _cuts_into calls a fit. Above zero the answer still holds every
    letter the enumeration counts, but at least one word straddles two lights —
    legal, and printed that way, so it is the tiebreak reconstruct_groups uses
    to order such a group rather than a reason to refuse it.
    """
    edges = set(itertools.accumulate(counts))
    return sum(1 for cut in itertools.accumulate(lengths[:-1]) if cut not in edges)


def _continues_it(lead, candidates, by_id):
    """Which of these sets of spare lights the clue list says is `lead`'s
    continuation, or None if it does not say.

    Asked only when the arithmetic leaves more than one reading — several sets of
    spare lights each holding exactly the letters the enumeration counts — and it
    is the clue list's own order that tells them apart: a leg the paper left
    unclued is one whose "See 7" went missing, and the clue it continues was
    printed EARLIER in the numbering. Every blank leg in the corpus is arranged
    that way, and ten of the twelve continue the clue immediately before them in
    their own direction.

    So a set is a candidate only if every light in it is numbered after the lead,
    and the one taken is the set that stays nearest to it — cryptic-23609 prints
    "Doubt if small droplets corrode (8)" at 7-down over four cells with two
    unclued four-cell lights in the grid, 8-down and 23-down, and MIST is finished
    by the RUST beside it, not by the DOWN eleven rows below that finishes
    22-down's "Pull out tail feathers (4,4)".

    Nearest means the set that reaches least far down the clue list, ties broken
    by the total distance, and a tie that survives both is not settled: two
    readings equally far from the lead are two answers this data cannot tell
    apart, and the enumeration is left to keep failing where
    tools/puzzle_integrity.py reports it.
    """
    reach = {}
    for extra in candidates:
        gaps = [by_id[m]["number"] - lead["number"] for m in extra]
        if min(gaps) > 0:
            reach[extra] = (max(gaps), sum(gaps))
    if not reach:
        return None
    nearest = min(reach.values())
    winners = [extra for extra, r in reach.items() if r == nearest]
    if len(winners) != 1:
        return None
    print(f"WARNING: {lead['id']}: {len(candidates)} sets of spare lights hold the "
          f"letters it counts; taking {' + '.join(sorted(winners[0]))}, the one "
          "that follows it in the clue list", file=sys.stderr)
    return winners[0]


def reconstruct_groups(entries, series):
    """Put back the lights a linked answer's enumeration counts and its group lost.
    Returns the rebuilt groups, one list of lights per group.

    The mirror of dissolve_false_groups, and the other half of the same damage:
    the Guardian's pre-2015 markup read cross-references in the wordplay as links,
    and failed to record links that were really there. What is left after the
    false ones go is an enumeration counting more letters than the lights the
    paper grouped — cryptic-23816's 9-across TREAD "(5,3,6)", fourteen letters over
    five cells, with THE BOARDS sitting in 10-across under the clue "See above" and
    in no group at all.

    The lights that may be put back are the spare ones — see _spare_light — and
    the enumeration is what chooses among them: a Guardian leading clue counts the
    whole answer word by word, so the lights of that answer are the ones its counts
    cut into (_cuts_into), one light per run of words. A membership is taken when
    it is the ONLY one that cuts, or — for the answers whose words straddle two
    lights, where nothing cuts at all — the only one that adds up. Several
    readings that all add up are separated by _continues_it, on the clue list's
    own order; a tie it declines to settle is two answers this data cannot tell
    apart, and a guess between them would be written into the file as fact, so the
    enumeration keeps failing to match instead, where tools/puzzle_integrity.py
    reports it.

    Order comes from the enumeration too when it is settled, and otherwise from
    reconcile_groups' rule — the stated order kept and the newcomers appended in
    grid reading order. Ambiguous ORDER is a display question, asked only after
    membership is already right.

    Gated off for PER_LIGHT_ENUMERATION series, where a leg's count is its own
    light's and says nothing about the rest of the answer, so there is no
    arithmetic here to reconstruct from.

    Run AFTER dissolve_false_groups, which is what decides which links are real:
    a group broken there is not one to be rebuilt here, and cannot be — a light
    it frees counts its own cells in full, which is exactly what _spare_light
    refuses.
    """
    if series in PER_LIGHT_ENUMERATION:
        return []
    by_id = {e["id"]: e for e in entries}
    claimed, rebuilt = {}, []
    # Two passes, because a spare light finishes one answer and not two. A lead
    # whose candidate sets the first pass cannot tell apart is asked again with
    # the lights another lead's enumeration already took removed, which is often
    # the whole of the ambiguity: cryptic-21673 prints two unclued six-cell
    # lights, and once 8-across's SPEAKERS has taken the CORNER that follows it,
    # VESTED is the only reading left for 26-across INTEREST's "(6,8)" — a count
    # whose spare light is numbered BEFORE the clue, where _continues_it can
    # never settle anything and elimination is the only thing that can.
    for _pass in (1, 2):
        spent = frozenset(m for _order, extra in claimed.values() for m in extra)
        for lead in entries:
            if lead["id"] in claimed:
                continue
            if is_continuation(lead.get("clue")):
                continue                    # a pointer counts its own light, not an answer
            said = ENUMERATION.search(lead.get("clue") or "")
            counts = [int(n) for n in re.findall(r"\d+", said.group(1))] if said else []
            if not counts:
                continue
            members = list(lead.get("group") or [lead["id"]])
            if lead["id"] not in members or not set(members) <= set(by_id):
                continue
            held = sum(by_id[m].get("length") or 0 for m in members)
            if sum(counts) == held:
                continue                    # the lights the paper grouped already hold it
            spare = [e["id"] for e in entries
                     if e["id"] not in members and e["id"] not in spent
                     and _spare_light(e, lead, entries)]
            if not spare or len(members) + len(spare) > RECONSTRUCT_LIMIT:
                continue
            tail = [m for m in members if m != lead["id"]]
            fits, adds_up = {}, {}
            for size in range(1, len(spare) + 1):
                for extra in itertools.combinations(spare, size):
                    if held + sum(by_id[m]["length"] for m in extra) != sum(counts):
                        continue
                    arrangements = list(itertools.permutations(tail + list(extra)))
                    adds_up[frozenset(extra)] = arrangements
                    orders = [rest for rest in arrangements
                              if _cuts_into(counts, [by_id[m]["length"]
                                                     for m in (lead["id"], *rest)])]
                    if orders:
                        fits[frozenset(extra)] = orders
            if fits:
                extra = (next(iter(fits)) if len(fits) == 1
                         else _continues_it(lead, fits, by_id))
                if extra is None:
                    continue
                orders = fits[extra]
            elif adds_up:
                # The letters are all accounted for, but no arrangement puts a light
                # boundary on every word boundary — because a WORD is split across
                # two lights. Quiptic 306's "(13)" is WOOL over 16-across and
                # GATHERING over 17-across, one word in two halves, and
                # cryptic-23182's "(5,3,4,5)" cuts START ALL into STAR and TALL.
                # _cuts_into is a word-boundary test, so it can only refuse these;
                # the arithmetic is what settles membership. Order is then the
                # arrangement that splits the fewest words, and a tie falls through
                # to the stated order as everywhere else — a display question, asked
                # after membership is already right.
                extra = (next(iter(adds_up)) if len(adds_up) == 1
                         else _continues_it(lead, adds_up, by_id))
                if extra is None:
                    continue
                arrangements = adds_up[extra]
                splits = {rest: _word_splits(counts, [by_id[m]["length"]
                                                      for m in (lead["id"], *rest)])
                          for rest in arrangements}
                fewest = min(splits.values())
                orders = [rest for rest in arrangements if splits[rest] == fewest]
            else:
                continue
            if len(orders) == 1:
                order = [lead["id"], *orders[0]]
            else:
                order = [lead["id"], *tail,
                         *sorted(extra, key=lambda m: (by_id[m]["position"]["y"],
                                                       by_id[m]["position"]["x"]))]
            claimed[lead["id"]] = (order, extra)

    # One light, one answer. Two leading clues whose enumerations both reach the
    # same spare light are the shared-light case again, arrived at from the other
    # side, and `group` still cannot hold it — so neither claim is written.
    taken = Counter(m for _order, extra in claimed.values() for m in extra)
    for lead_id, (order, extra) in sorted(claimed.items()):
        if any(taken[m] > 1 for m in extra):
            print(f"WARNING: {lead_id}: {', '.join(sorted(m for m in extra if taken[m] > 1))} "
                  "would finish more than one answer — left as published",
                  file=sys.stderr)
            continue
        for m in order:
            by_id[m]["group"] = list(order)
        rebuilt.append(list(order))
        print(f"WARNING: {lead_id}: its enumeration counts "
              f"{' + '.join(sorted(extra))}, which the paper left out of the group "
              f"— reading the answer as {' + '.join(order)}", file=sys.stderr)
    return rebuilt


def _day(ms):
    """An epoch-milliseconds date as a readable day, for error messages."""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


# How far two statements of one puzzle's date may disagree before the page is
# mis-filed rather than merely sloppy — see the date check at the end of
# convert(). Named because tools/repair_fetched.py measures already-written
# files against the same month, and a second number there could drift from
# this one into disagreeing about which stored puzzles are mis-filed.
MISFILED_MS = 30 * 86_400_000


# What a solution is allowed to hold: the capital letters a solver writes into
# the cells, and nothing else. Word breaks live in separatorLocations and
# accents are removed by bare_letters, so anything left that is not A-Z did not
# come from the grid. tools/puzzle_integrity.py imports this rather than
# spelling the rule again, so the fetcher that writes a solution and the check
# that weighs it can never disagree about what a solution looks like.
NOT_A_LETTER = re.compile(r"[^A-Z]")


def is_bare_letters(solution):
    """Is this string an answer as the grid holds it — A-Z only?"""
    return not NOT_A_LETTER.search(solution or "")


def bare_letters(solution):
    """A solution as the grid holds it: one capital letter per cell, unaccented.

    A crossword cell holds a letter, so neither the accent nor the case the paper
    sets in its own answer text is a character the solver writes. Everyman 3,847's
    2-down is published "ROSÉ" for four cells whose wordplay (gRoOmSmEn, regularly)
    spells ROSE; cryptic 28,323 is published with "eVEREST", "fORTNIGHT", "iLIAD"
    and "office", which is a shift key missed four times and not a theme — its
    28-across is EVE + REST, so the small "e" does not even fall where the wordplay
    divides. Normalised here rather than downstream because every reader of
    `solution` — the crossing check, the length check, the app's own grid —
    already assumes bare capitals, and one stray character breaks all of them.
    Only accent and case are touched; anything else non-alphabetic survives to be
    reported by tools/puzzle_integrity.py rather than silently rewritten.
    """
    if not solution:
        return solution
    return "".join(c for c in unicodedata.normalize("NFD", solution)
                   if unicodedata.category(c) != "Mn").upper()


# The answers the SOURCE got wrong, and what its own clues say they are.
#
# A key with one letter out is invisible to every check this repo has: both
# lights crossing the bad cell agree with each other, so tools/puzzle_integrity's
# CROSS check is silent; both still hold the letters their enumerations count, so
# LENGTH is silent too. The grid is perfectly self-consistent — it is the PAPER
# that is wrong, not the data made of it — and nothing downstream can tell.
#
# So the correction has to be stated somewhere, and the file on disk is not
# somewhere: carry_recovered_clues carries clue text across a re-fetch and
# nothing carries a solution, so one deliberate re-fetch of cryptic-23053
# silently restores the Guardian's letter. This is the statement, and
# correct_source_answers applies it every time an answer is read off a page,
# and corroborate.known_wrong on every write, whichever fetcher made it.
#
# Keyed by puzzle AND entry, holding BOTH values, because an entry is only good
# while the paper is still serving the wrong one. `served` is what the page
# sends, `corrected` is what goes in the file; a page since fixed no longer
# matches `served` and is warned about rather than rewritten — a stale key here
# must be deleted, exactly as a stale key in tools/puzzle_integrity.py's
# PUBLISHED_WRONG must. Liveness is checked at fetch time, the one moment the
# source is actually in front of us, because nothing in this repo's tests
# touches the network; tools/test_source_answer_wrong.sh holds the half that can
# be proved offline.
#
# This is for answers the source got WRONG, never for a guess or a preference.
# The note has to be evidence that settles it — an enumeration that splits into
# no words, a light that is not a word, the wordplay, the crossing — and an
# answer merely solved here belongs in solutionSource (tools/apply_solution.py),
# which marks a whole puzzle's fill unofficial. This table is the opposite case:
# an official key, published, with a known error in two of its letters.
SOURCE_ANSWER_WRONG = {
    ("cryptic-23053", "18-across"): (
        "GETSTEADY", "GETSREADY",
        'the clue "Prepares, if year were good, for yesterday" is printed (4,5) '
        "and GETSTEADY splits into no pair of words at all; GETS READY is the "
        "definition, and its R is the cell (4,8) 15-down crosses"),
    ("cryptic-23053", "15-down"): (
        "XETOPHILY", "XEROPHILY",
        "XETOPHILY is not a word; XEROPHILY, a liking for dry conditions, is the "
        '"hence home and dry" of the clue, its wordplay the unknowns X and Y '
        "keeping queen ER round O with duke PHIL — and its R is the same cell "
        "(4,8), where the Guardian's key holds T in both lights that cross"),
    ("cryptic-27235", "8-across"): (
        "IGNORED", "IGNORES",
        '"Part of pig (no residue) gives cold shoulder" hides p(IGNORES)idue, and '
        "gives is present tense; the last cell is unchecked, and fifteensquared "
        "has IGNORES"),
    ("everyman-3811", "21-down"): (
        "RIDDEN", "REDDEN",
        '"Well-mannered denizen muffling flush" hides manne(RED DEN)izen, and '
        "flush is REDDEN; the second cell is unchecked, and fifteensquared has "
        "REDDEN"),
    ("everyman-3814", "9-down"): (
        "MADEDO", "MAKEDO",
        "\u201cCope\u2019s poem, King, Before Noon, Rising\u201d is ODE+K+AM reversed, "
        "MAKE DO, and cope is MAKE DO; MADE DO has no K; the third cell is "
        "unchecked, and fifteensquared has MAKEDO"),
    ("everyman-3866", "26-across"): (
        "ROWINGCLUB", "BOXINGCLUB",
        '"Sportspeople fight in front of nightspot" is BOXING (fight) + CLUB '
        "(nightspot); rowing is no fight; both differing cells are unchecked, "
        "and fifteensquared has BOXINGCLUB"),
    ("everyman-3868", "22-down"): (
        "PEIR", "PEER",
        '"Announced seaside structure for aristocrat" is PEER, sounding like '
        "pier; PEIR is not a word; the third cell is unchecked, and "
        "fifteensquared has PEER"),
    ("independent-11963", "24-down"): (
        "LOAD", "LOUD",
        '"Flashy playing won Murray admirers in seconds" is the second letters '
        "of pLaying wOn mUrray aDmirers, LOUD, which is flashy; the third cell "
        "is unchecked, and fifteensquared has LOUD"),
}


def correct_source_answers(pid, entries):
    """Put SOURCE_ANSWER_WRONG's letters into answers just read off the page.

    Warns instead of rewriting when the table no longer describes the source:
    the entry is gone, or the page serves something other than the value the
    table names — including the corrected value itself, which is the paper
    having fixed its own key. Overriding an answer nobody disputes is how a
    correction outlives the error it was written for, so a stale entry is named
    and the published answer is left exactly as it arrived.

    An entry carrying no answer at all is not staleness: a prize puzzle is
    published without its key, and there is nothing yet to compare.
    """
    by_id = {e["id"]: e for e in entries}
    for (table_pid, eid), (served, corrected, _why) in SOURCE_ANSWER_WRONG.items():
        if table_pid != pid:
            continue
        entry = by_id.get(eid)
        if entry is None:
            print(f"WARNING: SOURCE_ANSWER_WRONG {pid} {eid}: this puzzle has no "
                  "such entry — stale key, delete it", file=sys.stderr)
            continue
        if not entry.get("solution"):
            continue
        if entry["solution"] == served:
            entry["solution"] = corrected
            continue
        print(f"WARNING: SOURCE_ANSWER_WRONG {pid} {eid} is STALE: the page "
              f"serves {entry['solution']}, not the {served} this table replaces "
              f"with {corrected} — leaving it as published, delete the key",
              file=sys.stderr)


# The publication dates the SOURCE got wrong, and the day its own sequence
# prints them on. A series publishes one puzzle per issue, in number order, so
# a date that is not after the number before it is wrong on one side or the
# other. Keyed by puzzle id
# and holding both days, as SOURCE_ANSWER_WRONG does: `served` is the page's
# `date`, `corrected` goes in the file, and a page no longer serving `served`
# is warned about and left as published. The evidence is the neighbours'
# dates, the setter's regular day, and fifteensquared's post for the puzzle.
SOURCE_DATE_WRONG = {
    "cryptic-22236": ("2001-06-25", "2001-06-15",
                      "22,235 is Thu 14 June and 22,237 the Sat 16 June prize"),
    "cryptic-24003": ("2007-02-21", "2007-02-17",
                      ("24,002 is Fri 16 Feb and 24,004 Mon 19 Feb; fifteensquared "
                       "blogged it as a prize on Sat 24 Feb")),
    "cryptic-24662": ("2009-04-03", "2009-04-01",
                      ("24,661 is Tue 31 Mar and 24,663 Thu 2 Apr; its own "
                       "webPublicationDate is the evening of 31 Mar, and "
                       "fifteensquared blogged it on 1 Apr")),
    "cryptic-24744": ("2009-07-14", "2009-07-06",
                      ("a Rufus between the Sat 4 July prize and 24,745 on Tue "
                       "7 July; fifteensquared blogged it on Mon 6 July")),
    "cryptic-24755": ("2009-07-20", "2009-07-18",
                      ("24,754 is Fri 17 July and 24,756 Rufus's Mon 20 July; "
                       "fifteensquared blogged it a week later, as a prize")),
    "cryptic-24849": ("2009-11-06", "2009-11-05",
                      ("24,848 is Wed 4 Nov and 24,850 Fri 6 Nov; fifteensquared "
                       "blogged it on Thu 5 Nov")),
    "cryptic-24874": ("2009-12-09", "2009-12-04",
                      ("24,873 is Thu 3 Dec and 24,875 the Sat 5 Dec prize; "
                       "fifteensquared blogged it on Fri 4 Dec")),
    "cryptic-24936": ("2010-02-18", "2010-02-17",
                      ("24,935 is Tue 16 Feb and 24,937 Thu 18 Feb; fifteensquared "
                       "blogged it on Wed 17 Feb")),
    "cryptic-24939": ("2010-02-22", "2010-02-20",
                      ("24,938 is Fri 19 Feb and 24,940 Rufus's Mon 22 Feb; "
                       "fifteensquared blogged it as a prize on Fri 26 Feb")),
    "quiptic-722": ("2013-09-09", "2013-09-16",
                    ("721 is Mon 9 Sept and 723 Mon 23 Sept; its own "
                     "webPublicationDate is the evening of 15 Sept")),
    "quiptic-780": ("2014-10-20", "2014-10-27",
                    ("779 is Mon 20 Oct and 782 Mon 10 Nov, one a week; "
                     "fifteensquared blogged 780 on 27 Oct and 781 on 3 Nov")),
    "quiptic-781": ("2014-10-27", "2014-11-03",
                    ("779 is Mon 20 Oct and 782 Mon 10 Nov, one a week; "
                     "fifteensquared blogged 780 on 27 Oct and 781 on 3 Nov")),
}


def correct_source_date(pid, when):
    """The date to file for `pid`, given the `when` its page serves."""
    if pid not in SOURCE_DATE_WRONG or when is None:
        return when
    served, corrected, _why = SOURCE_DATE_WRONG[pid]
    if str(_day(when)) != served:
        print(f"WARNING: SOURCE_DATE_WRONG {pid} is STALE: the page serves "
              f"{_day(when)}, not the {served} this table replaces with "
              f"{corrected} — leaving it as published, delete the key",
              file=sys.stderr)
        return when
    shift = (datetime.fromisoformat(corrected) - datetime.fromisoformat(served)).days
    return when + shift * 86_400_000


def fits_sequence(series, number, when):
    """Does `when` sit where the puzzles held either side of `number` put it?

    Both neighbours must be on disk within ARCHIVE_GAP numbers, so a page far
    from the continuous run (cryptic 1,183) never qualifies.
    """
    def nearest(step):
        for k in range(1, ARCHIVE_GAP + 1):
            path = puzzle_path(series, number + step * k)
            if path.exists():
                return read_puzzle_file(path).get("date")
        return None
    below, above = nearest(-1), nearest(1)
    return (below is not None and above is not None
            and below - MISFILED_MS <= when <= above + MISFILED_MS)


def convert(data):
    """Guardian data -> our puzzle object (no annotation on any entry yet)."""
    # Named before the entries are built: correct_source_answers is keyed by the
    # id this puzzle will be filed under, not by the page it arrived from.
    series = series_of(data["id"])
    pid = series_meta.puzzle_id(series, data["number"])
    entries = []
    for e in sorted(data["entries"], key=lambda e: (e["position"]["y"], e["position"]["x"], e["direction"])):
        clue, italics = flatten_clue(e["clue"])
        entries.append({
            "id": e["id"],
            "number": e["number"],
            "direction": e["direction"],
            "position": e["position"],
            "length": e["length"],
            "clue": clue,
            # Omitted rather than written empty: most clues have no italics and
            # a [] on every entry is 84 files of noise.
            **({"clueItalics": italics} if italics else {}),
            # Recorded, not re-derived. has_words is the one definition of "the
            # paper printed nothing here", and the app cannot import it, so the
            # answer travels in the file instead of a second rule in app.js
            # that could drift from this one.
            **({} if has_words(clue) else {"clueMissing": True}),
            # Only when it links clues. The paper writes a group on every entry,
            # singleton or not; an absent group here means "this clue is its own
            # answer", which is the overwhelming majority of them.
            **({"group": e["group"]} if len(e["group"]) > 1 else {}),
            # Written only when the paper actually marks a break, and the
            # annotation only once one exists: an empty object and a null
            # on every entry were 16 MB of nothing. Absent reads as empty
            # everywhere — app.js `|| {}`, the tools `.get(...) or {}`.
            **({"separatorLocations": seps} if (seps := e.get("separatorLocations") or {}) else {}),
            "solution": bare_letters(e.get("solution")),
        })
    # Before anything reads the answers: reconcile_groups and the length checks
    # downstream all weigh letters, and the paper's wrong one is not the letter
    # this corpus holds.
    correct_source_answers(pid, entries)
    reconcile_groups(entries)
    prune_one_sided_members(entries)
    dissolve_false_groups(entries, series)
    reconstruct_groups(entries, series)
    # Say it here, where the paper's own data is still in front of us.
    # Downstream a wordless clue is indistinguishable from a hard one: a cold
    # solve burns inference guessing it off the crossings, and the annotator
    # takes the blame for failing to solve nothing.
    wordless = [e["id"] for e in entries if not has_words(e["clue"])]
    if wordless and len(wordless) == len(entries):
        # Every clue blank is a different animal from a blank clue: the page is
        # a grid with no puzzle in it, and for the Guardian's 2005-08 prize
        # puzzles that is what the right page serves — see carry_recovered_clues.
        # Named so a backfill's log says which puzzle to go and get by hand
        # rather than burying it in a list of every light it has.
        print(f"WARNING: {data['id']}: all {len(entries)} clues blank — the paper's "
              "data has the grid and not the text. The clues are on the page its "
              "own special instructions link to.", file=sys.stderr)
    elif wordless:
        print("WARNING: published with no clue text: " + ", ".join(wordless),
              file=sys.stderr)

    # A MASKED solution is not a solution. The Guardian serves cryptic 28,691's
    # 3-down as "T?S?R" — the shape of the answer with its letters withheld —
    # and stored verbatim that is worse than no answer at all: the site
    # advertises full answers and then shows a wrong letter, and the annotator
    # spends a model building wordplay for a non-word.
    #
    # One masked light also means the page is not serving a key, so the puzzle
    # takes the route a Saturday prize crossword takes on the day it is
    # published: no solutions at all, which is the honest state and the one
    # every reader downstream already handles. Keeping the clean lights would
    # publish half a key — hasSolutions would be false either way, and
    # refresh_unsolved would stop re-fetching a puzzle whose answers might yet
    # appear. Written empty, it is re-fetched nightly and fills itself in the
    # day the paper publishes properly.
    masked = [e for e in entries if e["solution"] and not is_bare_letters(e["solution"])]
    if masked:
        print(f"WARNING: {data['id']}: solution masked on "
              + ", ".join(f"{e['id']} {e['solution']!r}" for e in masked)
              + f" — storing all {len(entries)} entries UNSOLVED", file=sys.stderr)
        for e in entries:
            e["solution"] = None

    # The paper states the publication date twice and they must agree. `date` is
    # the puzzle's day; `webPublicationDate` is when the article went up, always
    # the evening before — measured at under a day apart on every page sampled
    # from cryptic 21,621 (1999) to today, across all four series. A page whose
    # two dates disagree by more than a month is mis-filed at the Guardian's end
    # and nothing on it can be trusted: /crosswords/cryptic/1183 answers 200 with
    # Quiptic 1,183's clues, grid and answers under a `date` of 1934-01-18, while
    # its own webPublicationDate says 2022-07-14. Refusing is what makes that a
    # recorded gap instead of a fabricated puzzle — walk() catches Exception,
    # prints "skip 1183: …" and carries on.
    #
    # The article date alone is not proof, though: the Guardian re-published
    # whole runs of old pages at once (cryptic 26,651-26,764 all carry
    # webPublicationDate 2016-01-25), and those pages are the right puzzle.
    # So the page is refused only when its own `date` ALSO falls outside where
    # the sequence puts it — the same neighbour window, and the same month of
    # slack, that tools/repair_fetched.py measures stored files against.
    when, published = data.get("date"), data.get("webPublicationDate")
    if (when and published and abs(when - published) > MISFILED_MS
            and not fits_sequence(series, data["number"], when)):
        raise ValueError(
            f"{data['id']}: date {_day(when)} contradicts webPublicationDate "
            f"{_day(published)} — mis-filed page, refusing to write it")

    return {
        "id": pid,
        "number": data["number"],
        "series": series,
        "name": data["name"],
        "setter": (((data.get("creator") or {}).get("name") or "").strip()
                   or series_meta.default_setter(series)),
        "date": correct_source_date(pid, data.get("date")),
        "dimensions": data["dimensions"],
        "sourceUrl": "https://www.theguardian.com/" + data["id"],
        "entries": entries,
    }


def merge_annotations(new_puzzle, old_puzzle):
    """Carry our own work across a re-fetch: annotations always, and a model's
    solved grid until the paper publishes its own.

    A prize puzzle can be solved here before its answers are out (see
    tools/apply_solution.py), and refresh_unsolved re-fetches it every night
    until they are. Without the carryover each of those nightly re-fetches
    would wipe the fill and the annotations written off it; with it, the day
    the official key appears it simply replaces the model's, the unofficial
    marker comes off, and the differences get printed — which is the only
    grading of a blind solve that ever happens automatically.

    provenance travels the same way and for the same reason: new_puzzle is
    built fresh from whatever the fetcher just downloaded, so it never has a
    provenance block of its own. Left alone, provenance.stamp (called from
    write_puzzle_file right after this) reads that absence as "never stamped
    before" and dates the puzzle today — which is wrong the moment this is a
    re-fetch, and refresh_unsolved calls fetch_number on the very same pending
    puzzle every night until its answers land, so every one of those nights
    relabelled the puzzle's true, days-old arrival date as today's. Carrying
    the old block forward is what stamp() needs to see the real acquiredOn (and
    retrievedUrl, previousSolutionOrigin, book.leaf) instead of nothing; every
    field that should change with this fetch — solutionOrigin chief among
    them — is re-derived from new_puzzle's own content regardless of what
    provenance said before."""
    if old_puzzle.get("provenance"):
        new_puzzle["provenance"] = old_puzzle["provenance"]
    # The two hand-written fields on entries the annotation queue never touches.
    # A blank clue has no words for a model to read and a corrupt one has the
    # wrong words, so in both cases the explanation can only come from a person.
    # Carry them, or a re-fetch silently drops the single sentence that makes
    # that clue make sense and the page falls back to the generic line.
    for field in ("clueMissingNote", "clueCorrupt"):
        notes = {e["id"]: e.get(field) for e in old_puzzle.get("entries", [])}
        for e in new_puzzle["entries"]:
            if notes.get(e["id"]):
                e[field] = notes[e["id"]]

    carry_recovered_clues(new_puzzle, old_puzzle)

    # With the recovered clues back, an annotation crosses only to the same
    # words: a clue the paper corrected is re-annotated, not explained by notes
    # quoting the text it replaced.
    old = {e["id"]: e for e in old_puzzle.get("entries", [])}
    for e in new_puzzle["entries"]:
        held = old.get(e["id"])
        if (held and held.get("annotation") is not None
                and clue_words(held.get("clue")) == clue_words(e.get("clue"))):
            e["annotation"] = held["annotation"]

    was_model = (old_puzzle.get("solutionSource") or {}).get("kind") == "model"
    if not was_model:
        return None
    official = all(e.get("solution") for e in new_puzzle["entries"])
    guessed = {e["id"]: e.get("solution") for e in old_puzzle.get("entries", [])}
    if not official:
        # Paper still silent — keep the fill and stay flagged.
        for e in new_puzzle["entries"]:
            if not e.get("solution") and guessed.get(e["id"]):
                e["solution"] = guessed[e["id"]]
        new_puzzle["solutionSource"] = old_puzzle["solutionSource"]
        return None
    return grade_model_fill(new_puzzle, guessed)


def carry_recovered_clues(new_puzzle, old_puzzle):
    """Keep clue text a re-fetch would replace with nothing.

    The Guardian's crossword data for its 2005-08 PRIZE puzzles carries the grid
    and the answers and no clue text at all — the clues were published as prose
    on the paper's old site, which the puzzle page still links to ("click here
    to see the clues"), and they were never folded back into the data. Fetching
    one therefore writes a grid with no puzzle in it, which is what
    tools/puzzle_integrity.py's "all N clues are blank" reports.

    That is not a routing mistake and cannot be fixed by asking for a different
    URL: /crosswords/cryptic/<n> 404s for every one of them, and
    /crosswords/prize/<n> — the right page, the one whose number and date match
    — is the page serving the blanks.

    So the recovery is by hand, off those linked pages, and this is what keeps
    it: an entry whose stored clue has words and whose freshly-fetched one does
    not keeps the stored one. Without it, one --refresh-unsolved or one
    re-fetch silently empties sixteen recovered puzzles and the report that
    found them starts over.

    The group travels with the clue for the same reason. It is not the paper's
    group — the paper sent none — it is the statement of which lights the
    recovered clue's enumeration counts, and a clue that keeps its count while
    losing its group contradicts itself at the next length check.
    """
    old = {e["id"]: e for e in old_puzzle.get("entries", [])}
    for e in new_puzzle["entries"]:
        was = old.get(e["id"])
        if not was or has_words(e["clue"]) or not has_words(was.get("clue")):
            continue
        e["clue"] = was["clue"]
        e.pop("clueMissing", None)
        for field in ("clueItalics", "group"):
            e.pop(field, None)
            if was.get(field):
                e[field] = was[field]


def grade_model_fill(puzzle, guessed):
    """Mark a model's fill against the answers the paper has now published.

    `puzzle` already holds the official solutions; `guessed` maps entry id to
    what we filled it with before they were out. Returns the misses as
    (entry id, ours, theirs), which is the ONLY automatic grading a blind solve
    ever gets — see ANNOTATE_BLIND in tools/daily_update.sh.

    Shared with the Observer's refresh (tools/fetch_observer.py), which reaches
    the same moment by a different road: the Guardian re-fetches a whole page
    and merges, Everyman re-reads one hashed field and fills in place. They
    graded differently for as long as they graded separately — Everyman not at
    all — so the marking lives here and both call it."""
    wrong = [(e["id"], guessed.get(e["id"]), e["solution"])
             for e in puzzle["entries"] if guessed.get(e["id"]) != e["solution"]]
    # An annotation explains how the clue yields the answer, so an annotation
    # written off a wrong answer is wrong all the way through — definition,
    # blocks, walkthrough. Drop it and let the queue write it again against
    # the real answer, rather than leaving a confident explanation of a word
    # that was never the answer.
    missed = {eid for eid, _, _ in wrong}
    for e in puzzle["entries"]:
        if e["id"] in missed:
            e.pop("annotation", None)
    record_misses(puzzle["id"], wrong)
    return wrong


def record_misses(pid, wrong):
    """Write down which entries a grader blanked, for validate_annotations.py.

    Its check_every_clue_is_annotated errors on a missing annotation, because a
    blank is otherwise how an annotator escapes every other rule in the file.
    The blanks the graders make are the one kind it cannot choose: they are
    decided after the annotation run has ended, by comparing what the model
    derived against the published key.

    Lives here, beside grade_model_fill, because the blanking and the writing
    down of it have to happen together or the alert is a lie. They did not:
    blind_annotate.py recorded its blanks and the blind-solve grader did not, so
    everyman-4168 15A was dropped on 2026-09-14 for the intended reason and then
    reported as an unexplained blank in a published puzzle.

    Rewritten per puzzle rather than merged into, so a later pass that gets the
    clue right clears the exemption instead of leaving it standing for ever.
    """
    path = ROOT / "tools" / "data" / "blind_misses.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if wrong:
        data[pid] = {eid: mine for eid, mine, _theirs in wrong}
    else:
        data.pop(pid, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


def print_grade(puzzle, graded):
    """The grade, on stdout, in the shape tools/daily_update.sh alerts on.

    It greps for BLIND SOLVE GRADED, so this wording is load-bearing: a grade
    that only reaches .update.log is a measurement nobody reads."""
    total = len(puzzle["entries"])
    print(f"BLIND SOLVE GRADED {puzzle['id']}: {total - len(graded)}/{total} correct "
          f"against the published answers")
    for eid, mine, theirs in graded:
        print(f"  miss {eid}: model said {mine}, answer is {theirs}")


def puzzle_is_annotated(puzzle):
    """Every clue that CAN be annotated has been.

    A clue the paper published with no words in it is not a gap in this site's
    work and never will be: there is nothing to explain, and no annotator,
    model or human, can write a ladder for it. Counting one against its puzzle
    marks that puzzle permanently un-annotated, which buys a full annotation
    run on it every night, for ever, to solve the clues that were already done.

    A clue the paper published with the WRONG words costs exactly the same and
    is just as unfillable — the printed text does not lead to the printed
    answer, so a ladder over it would have to be invented. clueCorrupt is a
    person saying so, and it counts the same way.
    """
    return all(e.get("annotation") is not None or not has_words(e["clue"])
               or e.get("clueCorrupt") for e in puzzle["entries"])


def clue_coverage(puzzle):
    """How many of a puzzle's entries a solver can read, out of how many there are.

    A count and not a flag. "Has clues" collapses two cases that want opposite
    answers: a puzzle missing one clue of 28 is still a solvable grid, and one
    missing all 28 is a picture of a lattice. Only the ratio separates them, so
    the ratio is what the index carries and each reader picks its own line.

    Readable is has_words plus not clueCorrupt, the same pair puzzle_is_annotated
    excuses: printed-blank and printed-wrong are equally unsolvable, and a solver
    handed either has to invent the clue before it can answer it.

    A one-character clue counts as present, because it is one: ")" is the whole
    of CLOSE BRACKETS and a line of morse the whole of MORSE. What stays
    uncounted is an entry the paper printed nothing for. Even so, a reader
    deciding anything off this wants a ratio with room in it rather than a line
    at one missing entry — a setter who prints a blank clue on purpose leaves a
    grid that is still entirely solvable.
    """
    return {"present": sum(1 for e in puzzle["entries"]
                           if has_words(e["clue"]) and not e.get("clueCorrupt")),
            "total": len(puzzle["entries"])}


def reindex():
    """Rebuild puzzles/index.json and index.js from the puzzle files on disk.

    Both are generated and untracked, so this is the one entry point: every
    local tool rebuilds through it before reading the index, rather than each
    remembering to. `--reindex` on the command line is this function, and
    tools/reindex.js is the same call for the node harnesses."""
    # Difficulty needs every puzzle at once (each rating is relative to the
    # others), so it is scored in one pass here rather than per-file. It stays
    # optional so that a checkout missing any of its data still gets a working
    # index, with the ratings left off rather than the whole file unwritten.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from difficulty import all_scores
        ratings = all_scores()
    except Exception as err:  # noqa: BLE001 — never let this break the index
        print(f"difficulty scoring skipped: {err}")
        ratings = {}

    build_shims()
    puzzles = []
    for path in puzzle_files():
        p = read_puzzle_file(path)
        shim = shim_path(path)
        rating = ratings.get(p["id"])
        coverage = clue_coverage(p)
        puzzles.append({
            "id": p["id"],
            "number": p["number"],
            # Absent on every file written before quiptics existed, and every one
            # of those is a cryptic — so default rather than forcing a re-fetch
            # of 36 puzzles to add one string.
            "series": p.get("series", "cryptic"),
            "name": p["name"],
            "setter": p["setter"],
            "date": p.get("date"),
            # The generated shim, because that is what app.js injects — the
            # .json beside it is the source the shim was built from.
            "file": shim.name,
            # content hash → app.js appends it as ?v= so browsers never serve a
            # stale puzzle after a re-annotation (see APP.md, cache busting)
            "v": hashlib.md5(shim.read_bytes()).hexdigest()[:8],
            "annotated": puzzle_is_annotated(p),
            "hasSolutions": all(e.get("solution") for e in p["entries"]),
            # Clue coverage, written ONLY where some clue is unreadable: absent
            # means every entry carries a clue, which is 12,424 of 12,462
            # puzzles. index.js is 4 MB and the browser downloads all of it, so
            # a field that would say "28 of 28" twelve thousand times is 400 kB
            # on every first load to state the default. Readers take the absence
            # as full coverage; the 38 puzzles with a gap say so by name.
            **({"clues": coverage} if coverage["present"] < coverage["total"] else {}),
            # True where the grid was solved here by a model. The site says so
            # wherever it shows those answers: a learner checking their grid is
            # entitled to know whose answer they lost to. A blog's write-up
            # (timesforthetimes, fifteensquared) is a published solve that
            # anyone can look up, so it is not ours and is not badged.
            "solutionsUnofficial": (p.get("solutionSource") or {}).get("kind") == "model",
            # Absent for puzzles with too little to go on — an unrated puzzle
            # shows no badge rather than a made-up one.
            "difficulty": rating and {
                "band": rating["band"],
                "index": rating["index"],
                "percentile": rating["percentile"],
                "basis": rating["basis"],
            },
        })
    # Newest first BY DATE, not by number. With one series those agreed; with
    # three they don't — quiptic 1,393 and cryptic 30,073 came out the same week,
    # and sorting on the number would bury every quiptic below every cryptic
    # forever. Ties (a Monday publishes both) put the cryptic first, so the daily
    # cryptic stays the puzzle the site opens on.
    puzzles.sort(key=lambda p: (series_meta.date_ms(p.get("date")) or 0,
                                p["series"] == "cryptic", p["number"]),
                 reverse=True)
    # Which paper each series belongs to, carried here rather than looked up.
    # sync/worker.js has to name the paper in a push notification — "Cryptic
    # crossword No 30,106" never says Guardian — and a Worker cannot import
    # tools/series.py or app.js. One line per series in the file it already
    # fetches beats a second table of papers that would go stale.
    #
    # A book series answers "", because one shelf reprints a dozen papers and
    # there is no one answer. That is not a hole: every book puzzle's own name
    # opens with the paper that printed it ("Guardian cryptic crossword,
    # Penguin book 5 No 18"), so CTNotify.title() has nothing to add and adds
    # nothing.
    papers = {s: series_meta.publisher(s)
              for s in sorted({p["series"] for p in puzzles})}
    # The picker's heading for each series, beside `papers` rather than in it:
    # `papers` names the paper in a notification title, and "Times" is not the
    # Sunday Times' name.
    groups = {s: series_meta.group(s) for s in papers}
    # The browser's half of tools/data/books.json, for the same reason and by
    # the same route: app.js has to print "Penguin book 5 No 18" beside a
    # stored number and cannot read a file under tools/. Written from the
    # registry on every reindex, so the shelf is named in one place and
    # mirrored nowhere.
    books = {str(i): {"shelf": r["shelf"], "volume": r["volume"], "was": r["was"]}
             for i, r in sorted(series_meta.BOOKS.items())}
    index = {"latest": puzzles[0]["id"] if puzzles else None,
             "papers": papers, "groups": groups, "books": books, "puzzles": puzzles}
    (PUZZLE_DIR / "index.json").write_text(
        json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (PUZZLE_DIR / "index.js").write_text(
        "// Generated by tools/fetch_puzzle.py from index.json — do not edit by hand.\n"
        f"window.CRYPTIC_INDEX = {JSON_START} "
        + json.dumps(index, indent=1, ensure_ascii=False)
        + f" {JSON_END};\n",
        encoding="utf-8")
    # index.html names index.js by content hash, so the two are only ever
    # correct together. Stamp here rather than leaving it to the caller: CI
    # restamps before it builds, so a stale stamp fails nothing and surfaces
    # only as a deploy check that can never go green.
    from stamp_assets import INDEX_HTML, stamp
    INDEX_HTML.write_text(stamp(INDEX_HTML.read_text(encoding="utf-8")),
                          encoding="utf-8")
    return index


# Guardian numbers where the ordinary "try cryptic, then prize" order in
# fetch_page() lands on the wrong puzzle because two unrelated pages both
# claim the same number. cryptic/24451 answers 200 with a page dated
# 2008-11-20 (Brendan) — self-consistent (date and webPublicationDate agree),
# so convert()'s own mis-filed guard never fires — but 24451 is the single
# Saturday between cryptic-24450 (2008-07-25, Fri) and cryptic-24452
# (2008-07-28, Mon), and prize/24451 holds exactly that puzzle (Araucaria,
# 2008-07-26). The Brendan page is genuinely 24551: cryptic/24551 and
# prize/24551 both 404, and cryptic-24550 (2008-11-19) / cryptic-24552
# (2008-11-21) bracket the single day it belongs in. Keyed by the number
# actually wanted; valued with (url template to fetch instead of the default
# order, the number to trust over whatever that page's own data says — None
# to trust the page).
NUMBER_URL_FIXES = {
    24451: ("https://www.theguardian.com/crosswords/prize/{num}", None),
    24551: ("https://www.theguardian.com/crosswords/cryptic/24451", 24551),
}


def fetch_page(num):
    """Get a puzzle page by number, trying each series URL (cryptic, then prize)."""
    if num in NUMBER_URL_FIXES:
        return http_get(NUMBER_URL_FIXES[num][0].format(num=num))
    last = None
    for url in PUZZLE_URLS:
        try:
            return http_get(url.format(num=num))
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            last = err
    raise last


def fetch_number(num):
    data = extract_crossword_data(fetch_page(num))
    if num in NUMBER_URL_FIXES:
        forced_number = NUMBER_URL_FIXES[num][1]
        if forced_number is not None:
            data["number"] = forced_number
    puzzle = convert(data)
    # Through puzzle_path, never spelled here: this line said ".js" from the
    # day the fetcher was written, and the assert in write_puzzle_file is what
    # finally said so.
    path = puzzle_path(series_of(data["id"]), data["number"])
    is_new = not path.exists()
    graded = None
    if not is_new:
        graded = merge_annotations(puzzle, read_puzzle_file(path))
    # Named explicitly: this IS the acquiring fetcher, so it overwrites any
    # banner a recovery tool left, rather than inheriting it.
    write_puzzle_file(path, puzzle, generator="tools/fetch_puzzle.py")
    reindex()
    print(("fetched " if is_new else "refreshed ") + puzzle["id"])
    if graded is not None:
        print_grade(puzzle, graded)
    return puzzle, is_new


def walk(numbers, series, what="backfill"):
    """Fetch each number in turn, skipping what's on disk and what 404s.

    Guardian numbers are sequential within a series but not gapless, so a
    missing one is normal and must not stop the walk. Polite ~1s delay per
    request, paid only for numbers actually requested. Returns how many arrived.
    """
    fetched, skipped, missing = 0, 0, 0
    for num in numbers:
        if puzzle_path(series, num).exists():
            skipped += 1
            continue
        try:
            fetch_number(num)
            fetched += 1
        except urllib.error.HTTPError as err:
            # http_bytes has already backed off four times by here, so this is
            # not a blip. Recording it as a gap would bake a lie into the
            # archive; stopping costs one source for one run.
            if err.code in RETRY_STATUSES:
                print(f"STOPPING at {num}: HTTP {err.code} after every retry — "
                      f"{fetched} fetched before it started refusing")
                reindex()
                raise
            print(f"skip {num}: HTTP {err.code}")
            missing += 1
        except Exception as err:  # malformed page etc. — keep going
            print(f"skip {num}: {err}")
            missing += 1
        time.sleep(1)
    reindex()
    print(f"{what} done: {fetched} fetched, {skipped} already present, "
          f"{missing} unavailable")
    return fetched


def on_disk_numbers(series):
    """Every number of `series` we hold, read off the file names."""
    prefix = f"{series}-"
    return sorted(int(p.stem[len(prefix):]) for p in puzzle_files()
                  if p.stem.startswith(prefix) and p.stem[len(prefix):].isdigit())


def backfill(count, series="cryptic"):
    """Fetch the last `count` puzzles of one series ending at the newest,
    skipping ones we already have."""
    latest = find_latest_number(series)
    return walk(range(latest, latest - count, -1), series)


# Wider than any run of numbers a paper skips (the Independent's biggest is 1,
# the Guardian's 3) and far narrower than the 20,000 between the stray 1930s
# puzzles and the continuous archive.
ARCHIVE_GAP = 50


def extend(count, series="cryptic"):
    """Fetch `count` puzzles of one series OLDER than the oldest we hold.

    backfill's counterpart, and the one the annotation queue needs. backfill
    anchors at the newest, so on a deep archive it spends the run recognising
    files we already have and can never reach past the far end. The papers
    publish four or five a day between them and a good night annotates far more
    than that, so older is the only direction more work comes from.
    """
    have = on_disk_numbers(series)
    if not have:
        return backfill(count, series)
    # The floor of the RUN, not the smallest number on disk. The Guardian's
    # online archive is not one block: it hosts a handful of 1930s puzzles —
    # cryptic-1183 is one — twenty thousand numbers below where the continuous
    # run starts. min() therefore aimed the walk at 1182 and spent the whole
    # run 404ing through empty space, never touching the real frontier.
    #
    # Walking down from the newest and stopping at the first gap wider than a
    # paper's own skipped numbers also makes a hole self-healing: extend starts
    # just above it, fills it, and the next run carries on past it.
    oldest = have[-1]
    for n in reversed(have[:-1]):
        if oldest - n > ARCHIVE_GAP:
            break
        oldest = n
    # Clamped to the series' own honest floor where one is known, rather than
    # walking into 404s that would take a while to learn nothing from — the
    # same reasoning as fetch_observer.py's EARLIEST.
    floor = FLOORS.get(series, 0)
    if oldest <= floor:
        print(f"extend done: {series} starts at {floor}; nothing older exists here")
        return 0
    return walk(range(oldest - 1, max(oldest - 1 - count, floor - 1), -1), series, "extend")


# How long a nightly refresh keeps asking after a puzzle's real answers before
# giving up on ever seeing them. Every source this repo refreshes publishes far
# inside this window when it publishes at all — a Guardian prize crossword's
# solution lands roughly two weeks after the puzzle, an Observer Everyman's
# within a week of its competition closing, and a fifteensquared write-up of a
# Cyclops within weeks of the puzzle appearing there — so a puzzle already this
# old is not "still pending", it is a source that will never answer it: five
# Guardian prize puzzles from 2000-2006 and 78 Cyclops puzzles from 2006-2009
# were being asked for anyway, every night, forever, until this existed. One
# number for every source kept here, rather than three, because none of them
# is anywhere near this slow and a single constant is the one place to widen it
# if that ever stops being true. Read by refresh_unsolved below and by its
# equivalents in tools/fetch_observer.py and tools/fetch_privateeye.py, both of
# which import still_worth_refreshing from here rather than restating it.
REFRESH_WINDOW_DAYS = 90


def still_worth_refreshing(puzzle, now=None):
    """Should a nightly refresh still ask this puzzle's source for answers?

    Anchored on `date` — the puzzle's own publication day, epoch milliseconds —
    when the puzzle has one. A puzzle with no date (an un-backfilled Cyclops;
    see tools/fetch_privateeye.py's backfill_dates) falls back to
    provenance.acquiredOn, the day this repo first saw it: not the same fact,
    but the only other anchor a dateless puzzle has, and one that ages the same
    way. A puzzle with neither is never refreshed — nothing on it can ever
    become "too old" if nothing dates it in the first place, so without an
    anchor it would stay in the nightly queue forever, which is the exact
    failure REFRESH_WINDOW_DAYS exists to end.
    """
    when = None
    ms = series_meta.date_ms(puzzle.get("date"))
    if ms:
        when = datetime.fromtimestamp(ms / 1000, timezone.utc)
    else:
        acquired = (puzzle.get("provenance") or {}).get("acquiredOn")
        if acquired:
            try:
                when = datetime.strptime(acquired, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                when = None
    if when is None:
        return False
    return ((now or datetime.now(timezone.utc)) - when).days <= REFRESH_WINDOW_DAYS


def refresh_unsolved():
    """Re-fetch on-disk puzzles whose solutions weren't published yet.

    Saturday prize puzzles arrive without solutions and only get them about a
    week later; without this pass they would sit un-annotatable forever, since
    the daily job only annotates puzzles where hasSolutions is true.
    A puzzle we solved ourselves counts as unsolved here. It has a full grid of
    letters, so the "any entry missing a solution" test walks straight past it —
    and walking past it is exactly the failure worth avoiding, because it would
    mean the one puzzle whose answers are a guess is the one puzzle we stop
    checking. It stays on this list until the paper publishes and the merge can
    grade the guess — unless still_worth_refreshing has already given up on it,
    which is what keeps the queue from re-fetching puzzles no answer is ever
    coming for.

    Annotations are preserved by fetch_number's merge."""
    pending = []
    for path in puzzle_files():
        p = read_puzzle_file(path)
        # Only what this fetcher can actually fetch. It used to scan every file
        # in puzzles/, which after the Independent and the Observer arrived meant
        # asking theguardian.com for their numbers every night and printing
        # "refresh 4166 failed: HTTP 404" forever. Each of those papers has its
        # own fetcher with its own --refresh-unsolved; daily_update.sh runs all
        # three.
        if p.get("series") not in FETCHABLE:
            continue
        if not still_worth_refreshing(p):
            continue
        if not all(e.get("solution") for e in p["entries"]) or p.get("solutionSource"):
            pending.append(p["number"])
    filled = 0
    for num in pending:
        try:
            puzzle, _ = fetch_number(num)
            # A carried-over model fill fills every entry too, so "has letters
            # everywhere" is not the test — "the paper said so" is.
            if all(e.get("solution") for e in puzzle["entries"]) and not puzzle.get("solutionSource"):
                print(f"solutions now published for {num}")
                filled += 1
            elif puzzle.get("solutionSource"):
                print(f"{num}: solutions still withheld — keeping our own fill")
            else:
                print(f"{num}: solutions still withheld")
        except Exception as err:
            print(f"refresh {num} failed: {err}")
        time.sleep(1)
    if pending:
        reindex()
    print(f"refresh-unsolved: {filled}/{len(pending)} puzzle(s) gained solutions")


def find_latest_number(series="cryptic"):
    spec = GUARDIAN_SERIES[series]
    nums = []
    for url in spec["index"]:
        try:
            page = http_get(url)
        except Exception as err:
            print(f"series {url} unavailable: {err}")
            continue
        nums += [int(n) for n in re.findall(spec["link_re"], page)]
    if not nums:
        raise SystemExit(f"No {series} puzzle links found on series pages")
    return max(nums)


def main(argv):
    PUZZLE_DIR.mkdir(exist_ok=True)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--reindex":
        index = reindex()
        print(f"indexed {len(index['puzzles'])} puzzle(s); latest = {index['latest']}")
        return 0
    if argv[0] == "--refresh-unsolved":
        refresh_unsolved()
        return 0
    if argv[0] == "--backfill":
        count = int(argv[1]) if len(argv) > 1 else 30
        series = argv[2] if len(argv) > 2 else "cryptic"
        if series not in GUARDIAN_SERIES:
            raise SystemExit(f"Unknown series {series!r}; try {'/'.join(FETCHABLE)}")
        if GUARDIAN_SERIES[series].get("moved_to"):
            raise SystemExit(f"{series} is no longer published here — use "
                             f"{GUARDIAN_SERIES[series]['moved_to']}")
        backfill(count, series)
        return 0
    if argv[0] == "--extend":
        count = int(argv[1]) if len(argv) > 1 else 30
        series = argv[2] if len(argv) > 2 else "cryptic"
        if series not in GUARDIAN_SERIES:
            raise SystemExit(f"Unknown series {series!r}; try {'/'.join(GUARDIAN_SERIES)}")
        # No moved_to guard here, unlike --backfill just above: moved_to marks
        # that a series' NEWEST puzzles live elsewhere now, which is exactly
        # the direction --backfill walks and exactly the direction --extend
        # doesn't. Everyman's older numbers (down to EVERYMAN_FLOOR) still
        # 200 on theguardian.com — see the GUARDIAN_SERIES comment above.
        extend(count, series)
        return 0
    if argv[0] == "--latest":
        # Every series, not just the cryptic. A per-series loop rather than one
        # max() because the sequences are unrelated: 30,073 is not "newer" than
        # 1,393, and taking the larger would mean the quiptic never downloads.
        # One series being down doesn't stop the others.
        got, up_to_date = [], []
        for series in FETCHABLE:
            try:
                num = find_latest_number(series)
            except SystemExit as err:
                print(err)
                continue
            if puzzle_path(series, num).exists():
                up_to_date.append(f"{series} {num}")
                continue
            try:
                fetch_number(num)
                got.append(str(num))
            except Exception as err:
                print(f"{series} {num} failed: {err}")
        if up_to_date and not got:
            print("up-to-date " + ", ".join(up_to_date))
            return 3
        if not got:
            return 1
        print(" ".join(got))
        return 0
    m = re.search(r"(\d{3,})", argv[0])
    if not m:
        raise SystemExit(f"Don't understand argument: {argv[0]}")
    fetch_number(int(m.group(1)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
