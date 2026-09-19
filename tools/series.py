#!/usr/bin/env python3
"""The one table that says what each crossword series IS.

Every series fact the tools need — who publishes it, what to call it, what to do
when the feed ships no setter name — lives here and nowhere else. Import it;
don't re-declare it.

This file exists because the same knowledge had already been copied into four
places by the third series: fetch_puzzle.py knew the Guardian URLs, the SEO
builder knew the publisher, the pre-reset backfill knew which puzzles to do
first, and each of them had grown its own `== "quiptic"` branch. Adding the
Independent would have meant finding all four. Now adding a series is one entry
below plus, if it needs a new fetcher, one module.

The one deliberate exception is the badge tooltip in app.js: that is prose
written for a solver deciding what to attempt next, not a machine fact, and it
lives next to the code that renders it. An unlisted series there simply goes
unbadged.
"""
import re

# No series-priority field. The backfill queues by date across every series at
# once (tools/prereset_backfill.sh), and puzzle difficulty is measured per puzzle
# in tools/difficulty.py — a per-series ranking here would be a third opinion
# nothing asks for.
# setter — used only when the source publishes no byline. Absent means the
#   feed always names a setter and a missing one is a scraping bug worth
#   showing as "Unknown".
SERIES = {
    "cryptic": {
        "kind": "Cryptic",
        "publisher": "Guardian",
        # The key is the Guardian's, from back when it was the only feed. Solvers
        # read the label, and "cryptic" names the genre rather than the paper.
        "badge": "guardian",
    },
    "quiptic": {
        "kind": "Quiptic",
        "publisher": "Guardian",
    },
    "everyman": {
        "kind": "Everyman",
        "publisher": "Observer",
        # "Everyman" IS the byline — the Observer has kept the setter anonymous
        # since 1945 — so the feed ships no creator. Without this every one of
        # them reads "Unknown", which looks like a scraping failure rather than
        # the deliberate anonymity it is.
        "setter": "Everyman",
    },
    # Ours. Not a paper, so it has no publisher's numbering and no feed — it is
    # here because "did we write this?" decides which rules a validator applies,
    # and that has to be a field rather than a guess about how an id is spelled.
    "authored": {
        "kind": "Cryptic",
        "publisher": "Cryptic Teacher",
        "setter": "Cryptic Teacher",
    },
    "independent": {
        "kind": "Cryptic",
        "publisher": "Independent",
    },
    "metro": {
        # Supplied to Metro by Puzzler Digital and printed with no byline at
        # all, so there is no name to scrape and a blank one is not a scraping
        # failure. The paper stands in as the attribution, the way "Everyman"
        # does for the Observer.
        "kind": "Cryptic",
        "publisher": "Metro",
        "setter": "Metro",
        "badge": "metro",
    },
    "cyclops": {
        # Private Eye ships the grid and the clues but strips the answers -- the
        # .puz solution grid is one repeated letter -- so these are filled from
        # fifteensquared's write-ups and carry a solutionSource saying so. The
        # setter is named in the file, hence no default here.
        "kind": "Cryptic",
        "publisher": "Private Eye",
        "badge": "cyclops",
    },
    "globeandmail": {
        # The Globe and Mail prints it, but the byline arrives stamped
        # "©News Licensing/Times Media Limited" — it is a Times of London
        # syndication, 13x13 rather than the Times' own 15x15. Publisher is the
        # masthead a solver sees; the setter name that comes with it is real.
        "kind": "Cryptic",
        "publisher": "Globe and Mail",
        "badge": "globe & mail",
    },
    "indysunday": {
        # The Independent on Sunday's own weekly sequence, ~1,900 and climbing
        # by one a week, served from the same feed as the daily (see
        # fetch_independent.py). A separate series because it is a separate
        # numbering: sharing "independent" would have put No 1,903 and No 12,438
        # in one sequence, and prev/next would have walked between them.
        #
        # Publisher stays "Independent" — the Sunday title folded into the daily
        # in 2016, and splitting it would make the archive page say "Guardian,
        # Independent, Independent on Sunday and Observer" for what a reader
        # thinks of as three papers. The kind carries the difference instead.
        "kind": "Sunday Cryptic",
        "publisher": "Independent",
        "badge": "indy sunday",
    },
}

# The New Penguin Book of The Guardian Crosswords: Guardian reprints, scanned
# and OCR'd, whose grids were reconstructed from the clue list and whose answers
# are solved here. A SERIES PER VOLUME, because every volume numbers its own
# puzzles from 1 — sharing one "penguin" key would put six different puzzles at
# No 3 in one sequence and walk prev/next between them, which is the reason
# indysunday is not part of independent.
#
# One table, not one hand-copied entry per book: the entries differ only in the
# volume number and its scan, so a sixth volume is one line added here and
# nothing else. Any volume with a puzzle on disk must be in it —
# tools/build_readme.py refuses a series it has no name for, and
# tools/test_reconstruct_grid.sh counts the (series, size) groups it samples.
#
# The value is the archive.org item the volume was scanned from, and it is PER
# VOLUME: each puzzle cites the book it was actually read out of. One literal
# written inside the loop below would give every volume the same scan, which is
# a claim about provenance that is false for four books out of five.
#
# No volume prints a Guardian puzzle number or a publication date, checked
# across all six books, so the number here is the book's own position and
# `date` is null. The kind says "Penguin book 5" rather than leaving it to the
# key, because the crawlable page's heading is "{publisher} {kind} Crossword No
# {number}" and "Guardian Cryptic Crossword No 3" would claim a Guardian number
# that this puzzle does not have and nobody can look up.
PENGUIN_VOLUMES = {
    2: "isbn_9780140176438",
    3: "isbn_9780140176445",
    5: "newpenguinbkguar0000perk",
    7: "isbn_9780140248098",
    11: "isbn_9780140277500",
}

for _volume, _identifier in PENGUIN_VOLUMES.items():
    SERIES[f"penguin{_volume}"] = {
        "kind": f"Penguin Book {_volume} Cryptic",
        "publisher": "Guardian",
        "badge": f"penguin {_volume}",
        "scan": _identifier,
        # The two facts that make this a BOOK rather than a feed, and the two
        # that every tool downstream needed and had nowhere to read: what the
        # book is called, and what one of its puzzles is called. They were a
        # BOOK_TITLE constant in provenance.py and an f-string in
        # file_penguin_puzzle.py, which is one book's worth of right.
        "bookTitle": f"The New Penguin Book of The Guardian Crosswords, "
                     f"volume {_volume}",
        "name": f"Guardian cryptic crossword, Penguin book {_volume} No {{number}}",
        # NOTHING WILL EVER GRADE THESE. Penguin prints its solutions as
        # answer-grid IMAGES that OCR to noise, and there is no Guardian number
        # or date to find a key by. It is a fact about the book, so it is stated
        # once here and copied onto each puzzle as solutionSource.officialKey by
        # whichever route fills the grid — tools/file_penguin_puzzle.py when the
        # answers arrive with the puzzle, tools/apply_solution.py when the
        # nightly cold solve finishes one filed without them. A puzzle that lost
        # it would have tools/build_seo_pages.py promise a reader that official
        # answers replace ours "as soon as those appear", which is a promise
        # nothing can keep.
        "officialKey": "never",
    }

# The Herald Crossword Book, Volume 2 (Black & White Publishing, 2005): the
# Glasgow Herald's own cryptics by seven named setters, scanned and OCR'd, grids
# reconstructed from the clue lists exactly as the Penguin volumes were. Not a
# Penguin volume, and the first book here that is not — which is why the fields
# above are fields rather than a pattern matched off the key. "penguin(N)" could
# never have matched this, and volume number alone cannot name a book once two
# publishers both print a volume 2.
#
# A series of its own for the same reason every Penguin volume is: the book
# numbers its puzzles from 1.
#
# kind carries "Book 2" rather than the publisher, because the crawlable page
# prints "{publisher} {kind} No {number}" — "Herald Book 2 Cryptic No 3" reads,
# "Herald Herald Book 2 Cryptic No 3" does not.
SERIES["herald2"] = {
    "kind": "Book 2 Cryptic",
    "publisher": "Herald",
    "badge": "herald 2",
    "scan": "heraldcrosswordb0000unse",
    "bookTitle": "The Herald Crossword Book, volume 2",
    "name": "Herald cryptic crossword, book 2 No {number}",
    # Same permanent fact as the Penguin volumes, reached differently: this book
    # DOES print its answers, as text at the back rather than as the answer-grid
    # images Penguin prints. But it prints them in a 2005 collection, nowhere a
    # publisher will ever serve, and no puzzle in it carries a Herald number or
    # a date to look one up by. No official key is coming.
    "officialKey": "never",
}

# Unlisted falls back to the Guardian cryptic, which is right both for the daily
# and for the Saturday prize that shares its number sequence and is recorded
# under the same series name.
DEFAULT = SERIES["cryptic"]


def meta(series):
    return SERIES.get(series or "cryptic", DEFAULT)


def kind(series):
    """The noun for this puzzle: "Cryptic", "Quiptic", "Everyman"."""
    return meta(series)["kind"]


def publisher(series):
    """The paper whose puzzle it is — NOT necessarily the site we fetched it
    from. Everyman is the Observer's, only syndicated onto the Guardian's."""
    return meta(series)["publisher"]


def default_setter(series):
    return meta(series).get("setter", "Unknown")


def badge(series):
    """What the picker chip and the archive row call this series.

    The key is a storage token and was being printed straight at solvers, which
    worked only while every key happened to read as a word. "indysunday" does
    not, so the label is a field. Mirrors SERIES_BADGE in app.js, which carries
    the prose that goes with it.
    """
    return meta(series).get("badge", series or "cryptic")


def official_key(series):
    """"never" where no publisher will ever print an answer key for this series.

    Absent everywhere else, which means "a key may yet arrive" — the Saturday
    prize whose answers land a week later is the whole reason the field is not a
    boolean on every series.
    """
    return meta(series).get("officialKey")


def scan_identifier(series):
    """The archive.org item id this series was scanned from, or None.

    None everywhere a puzzle comes off a feed rather than out of a book. The id
    belongs to the VOLUME, so it is read through the series key and never taken
    as a free argument: a caller-supplied identifier is how a puzzle comes to
    name one book in sourceUrl and another in provenance.book.
    """
    return meta(series).get("scan")


def scan_url(series):
    """The archive.org item page for this series' scan, or None.

    The whole 150-leaf volume — there is no URL for a single puzzle in a book,
    which is why provenance carries the volume and the number within it.
    """
    identifier = scan_identifier(series)
    return f"https://archive.org/details/{identifier}" if identifier else None


def book_title(series):
    """The printed book this series was scanned out of, or None for a feed.

    Its presence is what makes a series BOOK-SOURCED, and that is asked of this
    table rather than pattern-matched off the key: "penguin(N)" answered the
    question correctly only while every book was a Penguin volume, and it would
    have answered "no" for The Herald in three separate places — no book block
    on the puzzle, a grid recorded as the publisher's when it was reconstructed
    here, and an acquisition the provenance table had no row for.
    """
    return meta(series).get("bookTitle")


def puzzle_name(series, number):
    """The title on a book puzzle: the paper, the book, and the book's number.

    Templated beside the book it names, so acquiring one is an entry in this
    file rather than an entry here plus an f-string in the filing tool.
    """
    template = meta(series).get("name")
    if not template:
        raise KeyError(f"series {series!r} has no puzzle-name template; it is "
                       f"not a book series, and its puzzles are named by "
                       f"whatever feed fetched them")
    return template.format(number=number)


# ---------- ids ----------
# A puzzle's id is its series AND its number. The number alone is not unique:
# every paper numbers from its own 1, so the Guardian's 30,089 and the Times'
# 28,9xx sit in the same range the Guardian's own archive runs through, and the
# Guardian's Quiptic 1,395 will one day meet a backfilled cryptic 1,395. Until
# 2026-08-19 the id WAS the number, so puzzles/<n>.js was the whole namespace and
# the second paper to reach a number would have silently shared the first one's
# file — merging one paper's annotations into the other's grid.
#
# Numbers stay numbers everywhere they are DISPLAYED. This is the storage key.
#
# Series keys are one lowercase word, digits allowed, no hyphen — hence
# "indysunday" rather than "independent-sunday", and "penguin5" for a volume.
# The id is <series>-<number> and the LAST hyphen is the split, so a hyphenated
# key parses correctly but stops "^[a-z0-9]+-\d+$" being true, and that shape is
# asserted on filenames and on progress keys in tools/smoke_test.js — where the
# filename form is a FILTER rather than an assert, so a key that fails it is
# silently dropped from three corpus sweeps instead of failing one. That is why
# the shape is enforced here, at the one place ids are made, rather than left to
# be discovered: a key this refuses cannot reach the corpus at all.
def puzzle_id(series, number):
    assert re.fullmatch(r"[a-z0-9]+", series or "cryptic"), \
        f"series key {series!r} must be one lowercase word, digits allowed, no hyphen"
    return f"{series or 'cryptic'}-{number}"


def parse_id(pid):
    """("everyman", 4165) out of "everyman-4165".

    A bare number is a pre-namespacing id and says nothing about its series —
    every series used them — so resolving one means asking the index which
    puzzle has that number, not asking this function.
    """
    series, sep, number = str(pid).rpartition("-")
    return (series if sep else None), int(number)
