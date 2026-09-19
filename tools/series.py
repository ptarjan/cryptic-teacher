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

# --------------------------------------------------------------------- books
#
# A book series is ONE series per BOOK, not one per volume, and the volume lives
# in the number: `volume * 1000 + position`. penguin-5018 is volume 5's
# eighteenth puzzle, herald-2007 is Herald book 2's seventh; read one back with
# divmod(number, 1000).
#
# The volumes still have to be kept apart — every volume numbers its own puzzles
# from 1, so one shared sequence would put six different puzzles at No 3 and
# walk prev/next between books, which is the reason indysunday is not part of
# independent. The NUMBER does that now, and nothing else has to: one key means
# one badge, one colour, one tooltip and one entry here however many volumes the
# shelf grows to.
#
# AN INTEGER, NOT A DECIMAL. `number` is a JSON number and String(5.10) is
# "5.1", so volume 5's puzzles 1 and 10 would collide in app.js's BY_NUMBER
# resolver and in build_seo_pages.legacy_redirects(). The integer also leaves
# every \d+ regex, int() and String() key in the repo working untouched:
# parse_id() below, tools/smoke_test.js's /^[a-z0-9]+-\d+\.json$/ over every
# filename, sync/worker.js's [a-z]{4,12}-\d{1,6} over every vote id.
#
# A thousand positions per volume, and split_number() refuses a position of 0 or
# a volume this table has never heard of — so a number that names no puzzle
# cannot be built or read back, rather than quietly meaning something.
POSITIONS_PER_VOLUME = 1000

# `volumes` IS the per-volume table: volume -> the archive.org item that volume
# was scanned from. The identifier is PER VOLUME and each puzzle cites the book
# it was actually read out of — one identifier for the series would be a claim
# about provenance that is false for four books out of five.
#
# It is the only genuinely per-volume FACT. The book's title, a puzzle's name,
# the kind on its page and the shelf label a reader sees are the same sentence
# with the volume written into it, so they are templates here rather than a
# hand-copied entry per book — {volume} and {position} are filled in by the
# accessors below. A sixth Penguin volume is one line in `volumes`; a book from
# a publisher that is neither is one entry in SERIES.
#
# Any volume with a puzzle on disk must be listed: tools/build_readme.py refuses
# a series it has no name for, and split_number() refuses a number whose volume
# is not here.

# The New Penguin Book of The Guardian Crosswords: Guardian reprints, scanned
# and OCR'd, whose grids were reconstructed from the clue list and whose answers
# are solved here.
#
# No volume prints a Guardian puzzle number or a publication date, checked
# across all six books, so the position here is the book's own and `date` is
# null. The kind says "Penguin Book 5" because the crawlable page's heading is
# "{publisher} {kind} Crossword No {position}" and "Guardian Cryptic Crossword
# No 18" would claim a Guardian number that this puzzle does not have and
# nobody can look up.
SERIES["penguin"] = {
    "kind": "Penguin Book {volume} Cryptic",
    "publisher": "Guardian",
    "badge": "penguin",
    # What display_number() puts in front of the position where no kind is
    # printed beside it — the archive rows, the picker, prev/next. The publisher
    # is "Guardian" and the book is Penguin's, so the label has to name the
    # book; "book 5" alone would read as the Guardian's fifth of something.
    "shelf": "Penguin book {volume}",
    "bookTitle": "The New Penguin Book of The Guardian Crosswords, "
                 "volume {volume}",
    "name": "Guardian cryptic crossword, Penguin book {volume} No {position}",
    # NOTHING WILL EVER GRADE THESE. Penguin prints its solutions as answer-grid
    # IMAGES that OCR to noise, and there is no Guardian number or date to find
    # a key by. It is a fact about the book, so it is stated once here and
    # copied onto each puzzle as solutionSource.officialKey by whichever route
    # fills the grid — tools/file_penguin_puzzle.py when the answers arrive with
    # the puzzle, tools/apply_solution.py when the nightly cold solve finishes
    # one filed without them. A puzzle that lost it would have
    # tools/build_seo_pages.py promise a reader that official answers replace
    # ours "as soon as those appear", which is a promise nothing can keep.
    "officialKey": "never",
    "volumes": {
        2: "isbn_9780140176438",
        3: "isbn_9780140176445",
        5: "newpenguinbkguar0000perk",
        7: "isbn_9780140248098",
        11: "isbn_9780140277500",
    },
}

# The Herald Crossword Book (Black & White Publishing): the Glasgow Herald's own
# cryptics by seven named setters, scanned and OCR'd, grids reconstructed from
# the clue lists exactly as the Penguin volumes were. Not a Penguin volume, and
# the first book here that is not — which is why the lines above are fields
# rather than a pattern matched off the key. "penguin(N)" could never have
# matched this, and a volume number alone cannot name a book once two publishers
# both print a volume 2.
#
# kind carries "Book 2" rather than the publisher, because the crawlable page
# prints "{publisher} {kind} Crossword No {position}" — "Herald Book 2 Cryptic"
# reads, "Herald Herald Book 2 Cryptic" does not. shelf drops the publisher for
# the same reason: the badge beside it already says "herald".
SERIES["herald"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Herald",
    "badge": "herald",
    "shelf": "book {volume}",
    "bookTitle": "The Herald Crossword Book, volume {volume}",
    "name": "Herald cryptic crossword, book {volume} No {position}",
    # Same permanent fact as the Penguin volumes, reached differently: this book
    # DOES print its answers, as text at the back rather than as the answer-grid
    # images Penguin prints. But it prints them in a 2005 collection, nowhere a
    # publisher will ever serve, and no puzzle in it carries a Herald number or
    # a date to look one up by. No official key is coming.
    "officialKey": "never",
    "volumes": {
        2: "heraldcrosswordb0000unse",
    },
}

# Unlisted falls back to the Guardian cryptic, which is right both for the daily
# and for the Saturday prize that shares its number sequence and is recorded
# under the same series name.
DEFAULT = SERIES["cryptic"]


def meta(series):
    return SERIES.get(series or "cryptic", DEFAULT)


def kind(series, number=None):
    """The noun for this puzzle: "Cryptic", "Quiptic", "Penguin Book 5 Cryptic".

    A book series needs the number, because the volume is in it and the volume
    is what the heading has to name. Refusing rather than defaulting: a caller
    that forgot the number would otherwise print "Penguin Book {volume}
    Cryptic" at a reader, or silently drop the volume from a page whose whole
    job is saying which puzzle it is.
    """
    template = meta(series)["kind"]
    if not is_book(series):
        return template
    volume, _ = split_number(series, _require_number(series, number, "kind"))
    return template.format(volume=volume)


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

    Per SERIES, not per volume: five browns reading "penguin 2".."penguin 11"
    were one shelf spelled five ways, and the volume is on the number now.
    """
    return meta(series).get("badge", series or "cryptic")


def official_key(series):
    """"never" where no publisher will ever print an answer key for this series.

    Absent everywhere else, which means "a key may yet arrive" — the Saturday
    prize whose answers land a week later is the whole reason the field is not a
    boolean on every series.
    """
    return meta(series).get("officialKey")


# ---------- volumes ----------
# Everything below takes the NUMBER as well as the series, because for a book
# the number is where the volume lives. A book series with no number is an
# error, never a default: the accessors that print — kind, book_title,
# puzzle_name, scan_identifier — would otherwise name the wrong book, and
# naming the wrong book is the one failure this table exists to prevent.

def is_book(series):
    """Whether this series' puzzles were read out of a scanned printed book.

    Asked of the table, never pattern-matched off the key: "penguin(N)"
    answered correctly only while every book was a Penguin volume, and it
    answered "no" for The Herald in three separate places.
    """
    return "volumes" in meta(series)


def volumes(series):
    """volume -> archive.org identifier, empty for a series off a feed."""
    return meta(series).get("volumes", {})


def _require_number(series, number, what):
    if number is None:
        raise ValueError(
            f"{series} is a book series, so {what} needs the puzzle's number "
            f"as well: the volume is in it (volume * "
            f"{POSITIONS_PER_VOLUME} + position)")
    return number


def book_number(series, volume, position):
    """The stored number for one puzzle: volume 5's No 18 is 5018.

    The one place the arithmetic is written. Callers hold a volume and a
    position — that is what a book prints — and never build the number
    themselves.
    """
    if volume not in volumes(series):
        raise ValueError(
            f"{series} has no volume {volume} in tools/series.py — add it and "
            f"its archive.org identifier there, or its puzzles will cite a "
            f"book they did not come from")
    if not 1 <= position < POSITIONS_PER_VOLUME:
        raise ValueError(
            f"{series} volume {volume} position {position} is outside "
            f"1..{POSITIONS_PER_VOLUME - 1}; no book here prints that many")
    return volume * POSITIONS_PER_VOLUME + position


def split_number(series, number):
    """(5, 18) out of penguin-5018's number.

    Raises on a volume this table does not list and on position 0, so a number
    that names no puzzle cannot be read back as if it did.
    """
    if not is_book(series):
        raise ValueError(f"{series} is not a book series, so its number is a "
                         f"publisher's number and holds no volume")
    volume, position = divmod(int(number), POSITIONS_PER_VOLUME)
    if position == 0:
        raise ValueError(f"{series}-{number} has position 0; positions start at 1")
    if volume not in volumes(series):
        raise ValueError(
            f"{series}-{number} is volume {volume}, which is not in "
            f"tools/series.py — add the volume and its archive.org identifier "
            f"there")
    return volume, position


def volume_of(series, number):
    """Which volume of its book this puzzle is: 5, for penguin-5018.

    The number the BOOK prints on its own spine, and two publishers' volume 2
    are different books — which is why book-ness is asked of the table rather
    than read off the key, as it was while every book here was a Penguin volume.
    """
    return split_number(series, number)[0]


def position_of(series, number):
    """The puzzle's place in its book: 18, for penguin-5018.

    A feed puzzle's number IS its position — the publisher counted it — so this
    answers for every series and is what a page prints beside a kind that
    already names the volume.
    """
    if not is_book(series):
        return int(number)
    return split_number(series, number)[1]


def display_number(series, number):
    """The number as a reader is shown it, with the word that introduces it.

    "No 30,089" off a feed. "Penguin book 5 No 18" out of a book, because one
    key now covers every volume and "No 5,018" would name a puzzle no book
    prints. Used everywhere a number is printed WITHOUT the kind beside it —
    archive rows, the homepage list, prev/next — where the badge says only
    "penguin". Where the kind is printed too it already carries the volume, and
    the page prints position_of() so the volume is not said twice.

    Mirrored by displayNumber() in app.js for the picker and archive rows.
    """
    if not is_book(series):
        return f"No {int(number):,}"
    volume, position = split_number(series, number)
    return f"{meta(series)['shelf'].format(volume=volume)} No {position}"


def legacy_id(series, number):
    """The id this puzzle had while every volume was its own series, or None.

    "penguin5-18" for penguin-5018. /puzzles/penguin5-18/ is indexed and saved
    progress is keyed on it, so the id has to keep resolving: it is a rule here
    rather than a list of the 59 that existed, so a volume acquired later gets
    its redirect without anyone remembering to add one. Read by
    build_seo_pages.legacy_redirects() and mirrored by legacyId() in app.js.
    """
    if not is_book(series):
        return None
    volume, position = split_number(series, number)
    return f"{series}{volume}-{position}"


def scan_identifier(series, number):
    """The archive.org item id this puzzle's VOLUME was scanned from.

    Read through the series and the number, never taken as a free argument: a
    caller-supplied identifier is how a puzzle comes to name one book in
    sourceUrl and another in provenance.book. None for a feed.
    """
    if not is_book(series):
        return None
    return volumes(series)[volume_of(series, number)]


def scan_url(series, number):
    """The archive.org item page for this puzzle's volume, or None.

    The whole 150-leaf volume — there is no URL for a single puzzle in a book,
    which is why provenance carries the volume and the number within it.
    """
    identifier = scan_identifier(series, number)
    return f"https://archive.org/details/{identifier}" if identifier else None


def book_title(series, number):
    """The printed book this puzzle was read out of, or None for a feed."""
    if not is_book(series):
        return None
    volume = volume_of(series, _require_number(series, number, "book_title"))
    return meta(series)["bookTitle"].format(volume=volume)


def puzzle_name(series, number):
    """The title on a book puzzle: the paper, the book, and the book's number.

    Templated beside the book it names, so acquiring one is an entry in this
    file rather than an entry here plus an f-string in the filing tool.
    """
    if not is_book(series):
        raise KeyError(f"series {series!r} has no puzzle-name template; it is "
                       f"not a book series, and its puzzles are named by "
                       f"whatever feed fetched them")
    volume, position = split_number(series, number)
    return meta(series)["name"].format(volume=volume, position=position)


# ---------- ids ----------
# A puzzle's id is its series AND its number. The number alone is not unique:
# every paper numbers from its own 1, so the Guardian's 30,089 and the Times'
# 28,9xx sit in the same range the Guardian's own archive runs through, and the
# Guardian's Quiptic 1,395 will one day meet a backfilled cryptic 1,395. Until
# 2026-08-19 the id WAS the number, so puzzles/<n>.js was the whole namespace and
# the second paper to reach a number would have silently shared the first one's
# file — merging one paper's annotations into the other's grid.
#
# Numbers stay INTEGERS everywhere, displayed through display_number(). This is
# the storage key.
#
# Series keys are one lowercase word, digits allowed, no hyphen — hence
# "indysunday" rather than "independent-sunday". Digits are allowed rather than
# used: the books spelled their volume into the key until 2026-09-19 and carry
# it in the number now, so no key in the table has a digit in it today.
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
