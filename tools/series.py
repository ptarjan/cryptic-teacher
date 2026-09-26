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

The scanned books are not here either, and for the opposite reason: there are
thirty of them and the difference between two is data, not code.
tools/data/books.json is one row per physical book and this module reads it —
see the books section below.
"""
import datetime
import json
import pathlib
import re

# No series-priority field. The backfill queues by date across every series at
# once (tools/prereset_backfill.sh), and puzzle difficulty is measured per puzzle
# in tools/difficulty.py — a per-series ranking here would be a third opinion
# nothing asks for.
# setter — used only when the source publishes no byline. Absent means the
#   puzzle's setter is null: nobody is known to have set it.
# group — the heading the puzzle picker files this series under. Absent means
#   the publisher. A Sunday sister paper sets its weekday paper's, so the
#   Sunday Times sits with the Times while its publisher stays "Sunday Times".
# bylined — the source names the setter on every puzzle, so a null setter is
#   one the fetcher failed to read (tools/puzzle_integrity.py SETTER).
# datedFromNeighbours — the source prints no date, so the filer derives each
#   from the numbers either side and may be unable to yet. Every other series
#   must carry a date (tools/puzzle_integrity.py SHAPE and DATE).
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
        # The Guardian's sister paper, and published on the Guardian's site.
        "group": "Guardian",
        "bylined": True,
        # "Everyman" IS the byline — the Observer has kept the setter anonymous
        # since 1945 — so the feed ships no creator. Without this every one of
        # them has a null setter, which hides a byline the paper really prints.
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
        "bylined": True,
    },
    "metro": {
        # Supplied to Metro by Puzzler Digital and printed with no byline at
        # all. The paper is not a setter: unlike "Everyman" it is no byline
        # anyone signs, so these have a null setter and no byline is shown.
        "kind": "Cryptic",
        "publisher": "Metro",
        "badge": "metro",
    },
    "cyclops": {
        # Private Eye ships the grid and the clues but strips the answers -- the
        # .puz solution grid is one repeated letter -- so these are filled from
        # fifteensquared's write-ups and carry a solutionSource saying so. The
        # setter is named in the file, hence no default here.
        "kind": "Cryptic",
        "publisher": "Private Eye",
        "bylined": True,
        # Dated off the Eye's covers and its fortnightly cadence.
        "datedFromNeighbours": True,
        "badge": "cyclops",
        # A linked clue's count covers its own light, not the whole answer
        # (fetch_puzzle.PER_LIGHT_ENUMERATION).
        "perLightEnumeration": True,
    },
    "globeandmail": {
        # The Globe and Mail prints it, but the byline arrives stamped
        # "©News Licensing/Times Media Limited" — it is a Times of London
        # syndication, 13x13 rather than the Times' own 15x15. Publisher is the
        # masthead a solver sees; the setter name that comes with it is real.
        "kind": "Cryptic",
        "publisher": "Globe and Mail",
        "bylined": True,
        "badge": "globe & mail",
        # It is the Times Quick Cryptic under the same number, about seven
        # weeks later and with the published grid and answers, so from its
        # first number on the Quick is filed here and not from the blog.
        "reprints": "timesquick",
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
        "bylined": True,
        "badge": "indy sunday",
    },
    # The Times publishes no grid and no answer key online, so these four are
    # filed by tools/file_times_puzzles.py from the times-for-the-times blog:
    # the clue list and answers are the blog's, the grid is rebuilt from them.
    # `blog` is the host that route reads, and what makes provenance call the
    # geometry reconstructed and the answers a write-up.
    #
    # Saturday's cryptic shares the daily's number sequence, so it files under
    # "times" the way the Guardian's prize does under "cryptic".
    "times": {
        "kind": "Cryptic",
        "publisher": "Times",
        # The daily cryptic prints no setter's name, so the setter is null
        # and not the paper's name.
        "badge": "times",
        "blog": "timesforthetimes.co.uk",
        # The blog counts a linked clue over its own light, as Private Eye does.
        "perLightEnumeration": True,
        "datedFromNeighbours": True,
    },
    "timesquick": {
        "kind": "Quick Cryptic",
        "publisher": "Times",
        "badge": "times quick",
        "blog": "timesforthetimes.co.uk",
        "perLightEnumeration": True,
        "datedFromNeighbours": True,
    },
    "timesjumbo": {
        "kind": "Jumbo Cryptic",
        "publisher": "Times",
        "badge": "times jumbo",
        "blog": "timesforthetimes.co.uk",
        "perLightEnumeration": True,
        "datedFromNeighbours": True,
    },
    # A separate paper with its own weekly sequence, ~5,200 against the
    # daily's ~29,600.
    "sundaytimes": {
        "kind": "Cryptic",
        "publisher": "Sunday Times",
        "group": "Times",
        "badge": "sunday times",
        "blog": "timesforthetimes.co.uk",
        "perLightEnumeration": True,
        "datedFromNeighbours": True,
    },
    # The FT prints no grid a script can reach, so tools/ft_puzzles.py files
    # these from fifteensquared's write-ups, the grid rebuilt from their clue
    # numbers as the Times' is. Saturday's prize shares the weekday numbering.
    "ftcryptic": {
        "kind": "Cryptic",
        "publisher": "Financial Times",
        "bylined": True,
        # Dated off the blog's post days (tools/ft_puzzles.py print_dates).
        "datedFromNeighbours": True,
        "badge": "FT",
        "blog": "fifteensquared.net",
    },
    # The Telegraph's archive is paywalled, so these four are filed by
    # tools/file_telegraph_puzzles.py from bigdave44.com the way the Times's
    # are from its blog. The back-page cryptic prints no setter's name, so its
    # setter is null; the Toughies are always bylined, and the blog names them.
    # Saturday's prize cryptic shares the daily's number sequence. A prize
    # puzzle whose hints post is missing is dated off its neighbours.
    "telegraph": {
        "kind": "Cryptic",
        "publisher": "Telegraph",
        "badge": "telegraph",
        "datedFromNeighbours": True,
        "blog": "bigdave44.com",
    },
    "toughie": {
        "kind": "Toughie",
        "publisher": "Telegraph",
        "badge": "toughie",
        "bylined": True,
        "datedFromNeighbours": True,
        "blog": "bigdave44.com",
    },
    # The Sunday Telegraph's two have their own weekly sequences, ~3,400 and
    # ~240 against the daily's ~31,300. A separate paper, picked beside the
    # daily's.
    "sundaytel": {
        "kind": "Cryptic",
        "publisher": "Sunday Telegraph",
        "group": "Telegraph",
        "badge": "sunday telegraph",
        "datedFromNeighbours": True,
        "blog": "bigdave44.com",
    },
    "sundaytough": {
        "kind": "Toughie",
        "publisher": "Sunday Telegraph",
        "group": "Telegraph",
        "badge": "sunday toughie",
        "bylined": True,
        "datedFromNeighbours": True,
        "blog": "bigdave44.com",
    },
}

# --------------------------------------------------------------------- books
#
# THE WHOLE SHELF IS ONE SERIES. `book` covers every scanned printed book here
# — one key, one badge, one pill and one colour however many books arrive —
# and WHICH book a puzzle came out of lives in its number:
# book_index * 1000 + position. book-17023 is the twenty-third puzzle of the
# book registered as index 17, and display_number() prints it as "Penguin book
# 5 No 18" off the registry. Thirty books were thirty keys and thirty chips the
# day before this, and a reader choosing what to solve next was reading a list
# of publishers' imprints rather than a list of crosswords.
#
# THE BOOKS ARE NOT IN THIS FILE. tools/data/books.json is the registry: one
# row per PHYSICAL BOOK, carrying its archive.org identifier, the volume number
# its own cover prints, the shelf label a reader sees, the publisher, the
# printed title, the lead its puzzles are named with, and a stable book_index.
# This module reads it, and app.js reads it too through the copy
# tools/fetch_puzzle.py --reindex writes into puzzles/index.json.
#
# NOTHING HAND-COPIES A ROW. An 18-key BOOK_SHELF object in app.js was mirrored
# by a `shelf` column here, and two copies of one fact is how a shelf comes to
# be spelled two ways — one of them on the page a reader is looking at.
#
# THE INDEX IS NOT THE VOLUME. A book_index is this repo's, permanent and never
# reused; a volume is the number the BOOK prints on itself, and two publishers'
# volume 2 are different books. The index is in the number so that one key can
# cover the shelf; the volume is on the page so that a reader can find the
# book. Neither is ever read as the other — volume_of() goes through the row.
#
# The books still have to be kept apart: every book numbers its own puzzles
# from 1, so one flat sequence would put thirty different puzzles at No 3 and
# walk prev/next from the Herald into the Daily Mail. The NUMBER does that, and
# nothing else has to.
#
# AN INTEGER, NOT A DECIMAL. `number` is a JSON number and String(5.10) is
# "5.1", so a book's puzzles 1 and 10 would collide in app.js's BY_NUMBER
# resolver and in build_seo_pages.legacy_redirects(). The integer also leaves
# every \d+ regex, int() and String() key in the repo working untouched:
# parse_id() below, tools/smoke_test.js's /^[a-z0-9]+-\d+\.json$/ over every
# filename, sync/worker.js's [a-z]{4,12}-\d{1,6} over every vote id.
POSITIONS_PER_BOOK = 1000

BOOKS_FILE = pathlib.Path(__file__).resolve().parent / "data" / "books.json"


def _load_books():
    """The registry, checked on the way in.

    Every rule here is one a wrong row would otherwise break silently and a
    long way from the row: a reused book_index points a saved grid, a vote and
    an indexed URL at another book's crossword, and a volume that has drifted
    out of the title beside it names the wrong book on a page that exists to
    say which book it is. Checked at import, which is the cheapest moment —
    before anything has filed a puzzle against a bad row.
    """
    rows = json.loads(BOOKS_FILE.read_text(encoding="utf-8"))["books"]
    by_index, by_identifier = {}, {}
    for row in rows:
        index, identifier = row["book_index"], row["identifier"]
        where = f"tools/data/books.json: book_index {index} ({identifier})"
        if index < 1:
            raise ValueError(f"{where}: a book_index starts at 1")
        if index in by_index:
            raise ValueError(
                f"{where} is already {by_index[index]['identifier']}. A "
                f"book_index is the high half of every puzzle number in its "
                f"book, so it is never reused — retire it with the book")
        if identifier in by_identifier:
            raise ValueError(
                f"{where} is registered twice, as book_index "
                f"{by_identifier[identifier]['book_index']} as well. One scan "
                f"is one book")
        # The volume is the number the BOOK prints on itself, and shelf and
        # kind have it written into them by the accessors below rather than
        # carried beside them a second time. `title` and `name` cannot be
        # built that way — a title is the publisher's own sentence, and the
        # papers that print several lines word theirs differently — so the two
        # that do hold it spelled out are checked against it instead.
        volume = str(row["volume"])
        if volume not in row["title"]:
            raise ValueError(f"{where}: volume {volume} is nowhere in its "
                             f"title {row['title']!r}; one of the two is wrong")
        if not row["name"].endswith(volume):
            raise ValueError(f"{where}: name {row['name']!r} has to end in "
                             f"volume {volume} — puzzle_name() appends "
                             f"\" No <position>\" to it")
        if not is_year(row.get("published")):
            raise ValueError(f"{where}: published {row.get('published')!r} has "
                             f"to be the imprint page's year as a \"YYYY\" "
                             f"string — it becomes every puzzle's date")
        by_index[index] = row
        by_identifier[identifier] = row
    return by_index


# A puzzle's `date` is epoch milliseconds (a day the paper printed it), a
# "YYYY" string (a book's year, the most its imprint page says), or null.
# Every reader goes through these rather than treating it as a number.
_YEAR = re.compile(r"\d{4}")


def is_year(value):
    """Whether a stored date is a bare year: "1995"."""
    return isinstance(value, str) and bool(_YEAR.fullmatch(value))


def date_ms(value):
    """A stored date as epoch milliseconds, for sorting and comparing: a bare
    year is its 1 January, UTC. None stays None."""
    if is_year(value):
        return int(datetime.datetime(int(value), 1, 1,
                                     tzinfo=datetime.timezone.utc).timestamp() * 1000)
    return value


BOOKS = _load_books()
BOOK_BY_IDENTIFIER = {row["identifier"]: row for row in BOOKS.values()}

# ONE ENTRY FOR THE SHELF. The eighteen that were here were one per printed
# line — Pan's "Cryptic Crossword Book" and Pan's "Big Book" are two lines of
# one publisher's shelf — and that distinction is real, but it belongs on the
# row that names the book and not on a key that also decides a badge, a colour
# and a chip in the picker. tools/data/books.json carries it, in the title and
# in the shelf label, where a reader can see it.
#
# `book` is not a key any feed could take, and it does not have to be: is_book()
# is asked of this table, never pattern-matched off the key. "penguin(N)"
# answered correctly only while every book was a Penguin volume, and it
# answered "no" for The Herald in three separate places.
#
# KEYS ARE 4-12 LETTERS, NO DIGITS: sync/worker.js matches a vote id with
# [a-z]{4,12}-\d{1,6}, so a key outside that shape would not fail — it would
# quietly drop this shelf's votes on the floor.
BOOK_SERIES = "book"
SERIES[BOOK_SERIES] = {
    # No "kind" and no "publisher": both are the BOOK's, and kind() and
    # publisher() read them off the row. The crawlable page's heading is
    # "{publisher} {kind} Crossword No {position}", so a shelf-wide answer to
    # either would put the wrong paper or the wrong book on thirty pages.
    "badge": "book",
    # officialKey is "never" for the whole shelf: these are out-of-print
    # reprint collections that number their puzzles from 1 in the book, so a
    # puzzle here carries no paper number and no date and there is nothing a
    # publisher could ever serve an answer key AGAINST. The book's own printed
    # answer grids are page images no job can read (see file_penguin_puzzle.py). Stated once and copied
    # onto each puzzle as solutionSource.officialKey by whichever route fills
    # the grid — a puzzle that lost it would have tools/build_seo_pages.py
    # promise a reader that official answers replace ours "as soon as those
    # appear", which is a promise nothing can keep.
    "officialKey": "never",
    # What makes this a book series, asked of the table rather than of the key.
    "books": True,
}

# Unlisted falls back to the Guardian cryptic, which is right both for the daily
# and for the Saturday prize that shares its number sequence and is recorded
# under the same series name.
DEFAULT = SERIES["cryptic"]


def meta(series):
    return SERIES.get(series or "cryptic", DEFAULT)


def kind(series, number=None):
    """The noun for this puzzle: "Cryptic", "Quiptic", "Penguin Book 5 Cryptic".

    A book series needs the number, because the book is in it and the book is
    what the heading has to name. Refusing rather than defaulting: a caller
    that forgot the number would otherwise name a different book on a page
    whose whole job is saying which puzzle it is.
    """
    if not is_book(series):
        return meta(series)["kind"]
    row = book_row(series, _require_number(series, number, "kind"))
    return f"{row['kind']} {row['volume']} Cryptic"


def publisher(series, number=None):
    """The paper whose puzzle it is — NOT necessarily the site we fetched it
    from. Everyman is the Observer's, only syndicated onto the Guardian's.

    A book's paper is the BOOK's, so it comes from the registry and needs the
    number. Without one the answer is "", not a guess: one shelf reprints a
    dozen papers, and "" is what puzzles/index.json's `papers` table wants
    anyway — the push fan-out prefixes a notification title with it, and every
    book puzzle's own name already opens with the paper that printed it.
    """
    if is_book(series):
        return book_row(series, number)["publisher"] if number is not None else ""
    return meta(series)["publisher"]


def group(series):
    """The picker heading this series is filed under: its `group`, else its
    publisher. A book series answers "", as publisher() does without a number.
    """
    if is_book(series):
        return ""
    return meta(series).get("group", meta(series)["publisher"])


def default_setter(series, number=None):
    """Used only where the source publishes no byline; None when nobody is known.

    Per BOOK for a book: the Araucaria and Morse collections are one setter
    from cover to cover, and a blank byline in either is anonymity of the
    Everyman kind rather than a scraping failure. What the book prints over an
    individual puzzle still wins — this is the fallback, not an override.
    """
    if is_book(series) and number is not None:
        return book_row(series, number).get("setter")
    return meta(series).get("setter")


def badge(series):
    """What the picker chip and the archive row call this series.

    The key is a storage token and was being printed straight at solvers, which
    worked only while every key happened to read as a word. "indysunday" does
    not, so the label is a field. Mirrors SERIES_BADGE in app.js, which carries
    the prose that goes with it.

    Per SERIES, and the shelf is one series: thirty books wore thirty chips,
    which is a list of publishers' imprints and not a list of crosswords. The
    book is named where it is useful — display_number() prints "Penguin book 5
    No 18" beside the chip that says "book".
    """
    return meta(series).get("badge", series or "cryptic")


def official_key(series):
    """"never" where no publisher will ever print an answer key for this series.

    Absent everywhere else, which means "a key may yet arrive" — the Saturday
    prize whose answers land a week later is the whole reason the field is not a
    boolean on every series.
    """
    return meta(series).get("officialKey")


# ---------- books ----------
# Everything below takes the NUMBER as well as the series, because for a book
# the number is where the book lives. A book series with no number is an
# error, never a default: the accessors that print — kind, book_title,
# puzzle_name, scan_identifier — would otherwise name the wrong book, and
# naming the wrong book is the one failure this registry exists to prevent.

def is_book(series):
    """Whether this series' puzzles were read out of a scanned printed book.

    Asked of the table, never pattern-matched off the key: "penguin(N)"
    answered correctly only while every book was a Penguin volume, and it
    answered "no" for The Herald in three separate places.
    """
    return "books" in meta(series)


def book_row(series, number):
    """The registry row for the book this puzzle was read out of.

    The one lookup. Every book fact a page prints — the shelf label, the
    volume, the publisher, the title, the scan, the puzzle's own name — comes
    through here, so a puzzle cannot cite one book in its heading and another
    in its provenance.
    """
    index, _ = split_number(series, _require_number(series, number, "book_row"))
    return BOOKS[index]


def _require_number(series, number, what):
    if number is None:
        raise ValueError(
            f"{series} is a book series, so {what} needs the puzzle's number "
            f"as well: the book is in it (book_index * "
            f"{POSITIONS_PER_BOOK} + position)")
    return number


def book_number(identifier, position):
    """The stored number for one puzzle, by the scan it was read out of.

    The one place the arithmetic is written, and the archive.org identifier is
    the only thing a caller may name the book with. A free identifier beside a
    free --volume is exactly how a puzzle came to cite one book in its
    sourceUrl and another in its provenance: the run reads one item's text, so
    that item decides the number, the title and the scan alike, and there is no
    second argument for it to disagree with.
    """
    row = BOOK_BY_IDENTIFIER.get(identifier)
    if row is None:
        raise ValueError(
            f"archive.org item {identifier} is not in tools/data/books.json — "
            f"register the book there, with the volume its cover prints and "
            f"the shelf it belongs on, before filing a puzzle out of it")
    if not 1 <= position < POSITIONS_PER_BOOK:
        raise ValueError(
            f"{row['title']}: position {position} is outside "
            f"1..{POSITIONS_PER_BOOK - 1}; no book here prints that many")
    return row["book_index"] * POSITIONS_PER_BOOK + position


def split_number(series, number):
    """(17, 23) out of book-17023's number: the book_index and the position.

    The FIRST half is this repo's index for the book, not the volume its cover
    prints — volume_of() reads that off the row. Raises on an index no row
    registers and on position 0, so a number that names no puzzle cannot be
    read back as if it did.
    """
    if not is_book(series):
        raise ValueError(f"{series} is not a book series, so its number is a "
                         f"publisher's number and holds no book")
    index, position = divmod(int(number), POSITIONS_PER_BOOK)
    if position == 0:
        raise ValueError(f"{series}-{number} has position 0; positions start at 1")
    if index not in BOOKS:
        raise ValueError(
            f"{series}-{number} is book_index {index}, which no row of "
            f"tools/data/books.json registers — add the book and its "
            f"archive.org identifier there")
    return index, position


def volume_of(series, number):
    """Which volume of its book this puzzle is: 5, for book-3018.

    The number the BOOK prints on its own spine — read off a cover scan for
    twenty-eight of the thirty — and two publishers' volume 2 are different
    books, which is why a volume is never a key and never an index.
    """
    return book_row(series, number)["volume"]


def position_of(series, number):
    """The puzzle's place in its book: 18, for book-3018.

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
    key covers the whole shelf and "No 3,018" would name a puzzle no book
    prints. Used everywhere a number is printed WITHOUT the kind beside it —
    archive rows, the homepage list, prev/next — where the badge says only
    "book", so this is the only thing on the row that names the book. Where the
    kind is printed too it already carries the volume, and the page prints
    position_of() so the volume is not said twice.

    Mirrored by displayNumber() in app.js for the picker and archive rows.
    """
    if not is_book(series):
        return f"No {int(number):,}"
    row = book_row(series, number)
    return f"{row['shelf']} {row['volume']} No {position_of(series, number)}"


def legacy_ids(series, number):
    """Every id this puzzle has ever had, newest first, or [] for a feed.

    Two so far, both from the days when a book was its own series:
    "penguin-5018" while each BOOK was a key and the volume was in the number,
    and "penguin5-18" before that, while each VOLUME was a key. /puzzles/
    penguin5-18/ and /puzzles/penguin-5018/ are indexed, are in links people
    have shared, and are the keys browsers saved progress under, so both have
    to keep resolving forever.

    Built out of the registry's `was` and `volume` rather than listed, so a
    book scanned after the collapse gets its pages without anyone remembering
    to add them — which writes redirects for ids that were never published,
    harmless for the same reason the bare-number pages say "is at" rather than
    "has moved": the page's job is to say which puzzle a name refers to.

    Read by build_seo_pages.legacy_ids() and mirrored by legacyIds() in app.js.
    """
    if not is_book(series):
        return []
    row = book_row(series, number)
    position = position_of(series, number)
    per_book = row["volume"] * POSITIONS_PER_BOOK + position
    return [f"{row['was']}-{per_book}", f"{row['was']}{row['volume']}-{position}"]


def scan_identifier(series, number):
    """The archive.org item id this puzzle's VOLUME was scanned from.

    Read through the series and the number, never taken as a free argument: a
    caller-supplied identifier is how a puzzle comes to name one book in
    sourceUrl and another in provenance.book. None for a feed.
    """
    if not is_book(series):
        return None
    return book_row(series, number)["identifier"]


def published(series, number):
    """The year this puzzle's book was published, "YYYY" — its `date`. None
    for a feed, whose date is the day its paper printed it."""
    if not is_book(series):
        return None
    return book_row(series, number)["published"]


def scan_url(series, number):
    """The archive.org item page for this puzzle's volume, or None.

    The whole 150-leaf volume — there is no URL for a single puzzle in a book,
    which is why provenance carries the volume and the number within it.
    """
    identifier = scan_identifier(series, number)
    return f"https://archive.org/details/{identifier}" if identifier else None


def book_title(series, number):
    """The printed book this puzzle was read out of, or None for a feed.

    The title the COVER prints, stored whole in the registry rather than
    templated off the volume: "The Times Cryptic Crossword Book 21" and "The
    Times Crosswords, book 21 (Times Books)" are two different books catalogued
    under one name, and a template that wrote the volume into a shared sentence
    could only name one of them correctly.
    """
    if not is_book(series):
        return None
    return book_row(series, number)["title"]


def puzzle_name(series, number):
    """The title on a book puzzle: the paper, the book, and the book's number.

    Stored in the registry as the lead — "Guardian cryptic crossword, Penguin
    book 5" — with the position appended here, so acquiring a book is one row
    in tools/data/books.json rather than a row there plus an f-string in the
    filing tool.
    """
    if not is_book(series):
        raise KeyError(f"series {series!r} has no puzzle-name lead; it is not "
                       f"a book series, and its puzzles are named by whatever "
                       f"feed fetched them")
    return f"{book_row(series, number)['name']} No {position_of(series, number)}"


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
# used: no key in the table has one, because a number in a key is a fact about
# a puzzle wearing a storage token's clothes. The books spelled their volume
# into the key once; it is in the registry and in the number now.
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


AUTHORED_ID = re.compile(r"[A-Z]\d+")


def parse_id(pid):
    """("everyman", 4165) out of "everyman-4165".

    A bare number is a pre-namespacing id and says nothing about its series —
    every series used them — so resolving one means asking the index which
    puzzle has that number, not asking this function.

    An authored draft's id ("A001") is also bare — no hyphen — but for the
    opposite reason: tools/build_authored_puzzle.py spells it that way
    deliberately, to stay off the "*-[0-9]*.json" glob the nightly sweep and
    puzzle_files() use, so an unpublished draft is never walked by mistake.
    It is still one puzzle in one series, so unlike a pre-namespacing number
    it resolves to "authored" here rather than to None, and its number is the
    id itself — the digits alone would drop the letter that makes it authored
    in the first place, and no caller has needed an int out of it.
    """
    series, sep, number = str(pid).rpartition("-")
    if sep:
        return series, int(number)
    if number.isdigit():
        return None, int(number)
    assert AUTHORED_ID.fullmatch(number), \
        f"id {pid!r} has no series and is not an authored id (letter + digits)"
    return "authored", number
