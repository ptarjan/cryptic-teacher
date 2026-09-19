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
# reads, "Herald Herald Book 2 Cryptic" does not. shelf keeps it, because shelf
# is printed where nothing else names the paper: see the rule below.
SERIES["herald"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Herald",
    "badge": "herald",
    "shelf": "Herald book {volume}",
    "bookTitle": "The Herald Crossword Book, volume {volume}",
    "name": "Herald cryptic crossword, book {volume} No {position}",
    # Same permanent fact as the Penguin volumes, reached differently: this book
    # DOES print its answers, as text at the back rather than as the answer-grid
    # images Penguin prints. But it prints them in a 2005 collection, nowhere a
    # publisher will ever serve, and no puzzle in it carries a Herald number or
    # a date to look one up by. No official key is coming.
    "officialKey": "never",
    "volumes": {
        1: "heraldcrosswordb0000calu",
        2: "heraldcrosswordb0000unse",
    },
}

# ----------------------------------------------------------- the rest of the
# shelf
#
# Sixteen more book lines, registered before the scans that fill them:
# tools/data/book_acquisition_plan.json is the order they are being read in,
# and a volume has to be here before tools/acquire_book.py will file a puzzle
# citing it. Three rules decided every key below, and they are why there are
# sixteen of them rather than five.
#
# ONE KEY PER PRINTED LINE, not per publisher and not per paper. Everything
# above a `volumes` map is a TEMPLATE with {volume} written into it, so a key
# can only hold books whose titles differ by their number and by nothing else.
# The Telegraph alone prints five such lines — Pan's "Cryptic Crossword Book",
# Pan's "Big Book", Pan's "Big Book of Brain Sharpener", Octopus's "All New
# Cryptic Crosswords" and Octopus's "Cryptic Crosswords" — each numbering its
# own volumes from 1. One key for the five would have to name four of them
# wrongly in bookTitle, and four wrong book titles is not a saving.
#
# A BOOK KEY IS NEVER A LIVE SERIES' KEY. `independent` is a feed, 8,932-12,465
# on disk today and backfilling downwards, so the Penguin book of the
# Independent's crosswords is `penguinindy`: its volume 1 is numbers 1001-1099,
# which sits inside the daily's own sequence, and one key cannot be a feed and
# a book at once anyway — is_book() is "has a volumes map". Checked against
# every series' range rather than assumed: quiptic 1-1,399, cyclops 300-838,
# indysunday 1,320-1,907, everyman 2,965-4,169, globeandmail 3,106-3,369,
# cryptic 21,620-30,115, and metro's number is a date (20,250,403 up). No other
# new key below is a paper this repo fetches.
#
# THE VOLUME IS THE BOOK'S OWN PRINTED NUMBER, on twenty-two of the
# twenty-four, and every one of those was read off the cover scan rather than
# off a catalogue: archive.org and Open Library between them lost the number on
# four of these books, and invented none. The word counts as printed — "The
# First Penguin Book of the Independent Crosswords" is volume 1 and "The Ninth
# Penguin book of the Times crosswords" is volume 9. The two books that print
# no number anywhere, `morse` and `brainsharp`, say INVENTED here and again in
# the plan file, because a number nobody can check against a cover would
# otherwise sit in this table looking exactly like the twenty-two that can be.
#
# EVERY SHELF NAMES ITS OWN BOOK. display_number() is printed with no badge
# beside it in the homepage list that tools/build_seo_pages.py writes — just
# "{shelf} No {position}" and a setter — so a bare "book 2 No 7" would be the
# Herald's, the Scotsman's, the Sunday Telegraph's and the Daily Mail's at
# once. The Herald's shelf was bare while it was the only book with a plain
# number; it is "Herald book 2" now, for the same reason the nine below name a
# paper or a line. The ones that already read as one thing on their own —
# "Toughie book 1", "Brain Sharpener book 1", "Penguin FT book 1" — do not
# repeat the paper.
#
# KEYS ARE 4-12 LETTERS, NO DIGITS. sync/worker.js matches a vote id with
# [a-z]{4,12}-\d{1,6}, so `times1998` or `sundaytelegraph` would not fail —
# they would quietly drop this shelf's votes on the floor. Hence `timesbooks`
# and `sundaytel`.
#
# officialKey is "never" on every one of them, for the reason it is "never" on
# the two above: these are out-of-print reprint collections that number their
# puzzles from 1 in the book, so a puzzle here carries no paper number and no
# date, and there is nothing a publisher could ever serve an answer key
# AGAINST. The sample behind tools/data/book_candidates.json shows the same
# thing from the other end — every one of them parsed as book numbers 1, 2, 3.

# The Scotsman crossword book (Black & White Publishing, 2001): the Edinburgh
# broadsheet's own cryptics, the same publisher and the same format as the
# Herald books above. The volume is printed on it — the title is "The Scotsman
# crossword book. 2" — and leaves volume 1 a number to arrive at.
SERIES["scotsman"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Scotsman",
    "badge": "scotsman",
    "shelf": "Scotsman book {volume}",
    "bookTitle": "The Scotsman Crossword Book, volume {volume}",
    "name": "Scotsman cryptic crossword, book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        2: "scotsmancrosswor0000unse_i4i5",
    },
}

# Chambers book of Araucaria crosswords (Chambers, 2005): John Graham's own
# collection start to finish, which is why the key is the setter and not the
# publisher — "chambers" would have to hold the Morse book below too, and the
# two are not one line with two numbers. Volume 2 is printed on the cover;
# volume 3 is scanned (chambersbookofar0000arau_e6k7) and sits undetermined in
# tools/data/book_candidates.json, so this table grows rather than changes.
#
# Publisher is Chambers, not the Guardian. Araucaria set for the Guardian for
# fifty years, but the book names its setter and never a paper, and a masthead
# on every one of these pages would be a claim the book does not make.
SERIES["araucaria"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Chambers",
    "badge": "araucaria",
    "shelf": "Araucaria book {volume}",
    "bookTitle": "Chambers Book of Araucaria Crosswords, volume {volume}",
    "name": "Araucaria cryptic crossword, book {volume} No {position}",
    # The title is the byline: every puzzle in the book is his, so a blank
    # byline here is anonymity of the Everyman kind and not a scraping failure.
    "setter": "Araucaria",
    "officialKey": "never",
    "volumes": {
        2: "chambersbookofar0000arau",
    },
}

# Chambers book of Morse crosswords (Chambers, 2006), the crosswords Colin
# Dexter wrote around Inspector Morse. ONE BOOK, AND NO NUMBER ANYWHERE ON IT,
# so volume 1 is INVENTED — the numbering has nowhere else to put a book, and
# the plan file says so rather than letting a made-up 1 look like a printed
# one.
#
SERIES["morse"] = {
    "kind": "Morse Book {volume} Cryptic",
    "publisher": "Chambers",
    "badge": "morse",
    "shelf": "Morse book {volume}",
    "bookTitle": "Chambers Book of Morse Crosswords, volume {volume}",
    "name": "Morse cryptic crossword, book {volume} No {position}",
    # "by Colin Dexter" is the cover, and a default is only ever the fallback
    # for a puzzle that arrives with no byline of its own — so if the book
    # credits its puzzles individually, what it prints still wins.
    "setter": "Colin Dexter",
    "officialKey": "never",
    "volumes": {
        1: "chambersbookofmo0000dext",
    },
}

# The Times Cryptic Crossword Book (HarperCollins): the Times' daily cryptics,
# 80 to a volume and one volume a year. Both numbers here are printed on the
# covers, and the run they belong to is continuous — 12/2008, 13/2009, 15/2011,
# 17/2013, 18/2014, 19/2015, 20/2016, 21/2017, 22/2018, 24/2020 through
# 29/2025 in Open Library's edition records. That run is also the evidence for
# the key below it.
SERIES["times"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Times",
    "badge": "times",
    "shelf": "Times book {volume}",
    "bookTitle": "The Times Cryptic Crossword Book {volume}",
    "name": "Times cryptic crossword, book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        13: "timescrypticcros0000time_i0s6",
        21: "timescrypticcros0000time",
    },
}

# TWO BOOKS ON THIS SHELF ARE CATALOGUED "The Times Cryptic Crossword Book
# 21", and this is the other one. The catalogues are what collide; the covers
# do not. This book's cover reads "THE TIMES CROSSWORDS ... BOOK 21 — THE
# WORLD'S MOST FAMOUS CROSSWORD PUZZLE" (Times Books, January 1998, ISBN
# 1-902254-06-7, 144 pages), while `times` volume 21 is "The Times Cryptic
# Crossword Book 21" (HarperCollins, 2017, ISBN 978-0-00-817388-3, 246 leaves).
# Two different printed titles, and archive.org normalised the first into the
# second's.
#
# The dates say the same thing independently: the HarperCollins run is one
# volume a year with no gap in it — 12/2008 through 29/2025 — so 1998 falls
# eleven volumes before its 12 and cannot be a renumbering of it. Same paper's
# puzzles, two publishers' numberings, two keys; the title each cover prints is
# what the templates carry, so no page here can name the wrong book.
SERIES["timesbooks"] = {
    "kind": "Crosswords Book {volume} Cryptic",
    "publisher": "Times",
    "badge": "times books",
    "shelf": "Times Crosswords book {volume}",
    "bookTitle": "The Times Crosswords, book {volume} (Times Books)",
    "name": "Times cryptic crossword, Times Crosswords book {volume} "
            "No {position}",
    "officialKey": "never",
    "volumes": {
        21: "isbn_9781902254067",
    },
}

# The Penguin Book of The Times Crosswords (Penguin, 1988 and 1989): the same
# reprint-a-paper format as the Guardian Penguins at the top of this section,
# a different paper, and therefore a different key — `penguin` volume 9 would
# be a Guardian book, and the volume number alone cannot name a book once two
# papers both have a ninth. The covers print their volumes as words, "Ninth"
# and "Tenth"; the digits are those words.
SERIES["penguintimes"] = {
    "kind": "Penguin Book {volume} Cryptic",
    "publisher": "Times",
    "badge": "times penguin",
    "shelf": "Penguin Times book {volume}",
    "bookTitle": "The Penguin Book of The Times Crosswords, volume {volume}",
    "name": "Times cryptic crossword, Penguin book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        9: "ninthpenguinbook0000unse",
        10: "tenthpenguinbook0000unse",
    },
}

# The Penguin Book of Independent Crosswords (Penguin, 1990). NOT `independent`
# — that key is the live daily feed, and this is the collision the rule at the
# top of this section exists for. Volume 1 is printed, in the same way the
# Times Penguins print 9 and 10: the cover reads "THE FIRST PENGUIN BOOK OF THE
# INDEPENDENT CROSSWORDS".
SERIES["penguinindy"] = {
    "kind": "Penguin Book {volume} Cryptic",
    "publisher": "Independent",
    "badge": "indy penguin",
    "shelf": "Penguin Indy book {volume}",
    "bookTitle": "The Penguin Book of Independent Crosswords, volume {volume}",
    "name": "Independent cryptic crossword, Penguin book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        1: "penguinbookofind0000unse_y8k9",
    },
}

# The Penguin Book of Financial Times Crosswords (Penguin, 1973), the oldest
# book on the shelf by fifteen years, and "The First Penguin Book of" on the
# cover — volume 1, printed. The FT is a paper this repo has no feed for, so
# there is no key to collide with; the name still follows the Penguin pattern
# beside it rather than inventing a second shape for the same kind of book.
SERIES["penguinft"] = {
    "kind": "Penguin Book {volume} Cryptic",
    "publisher": "Financial Times",
    "badge": "ft penguin",
    "shelf": "Penguin FT book {volume}",
    "bookTitle": "The Penguin Book of Financial Times Crosswords, volume {volume}",
    "name": "Financial Times cryptic crossword, Penguin book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        1: "penguinbookoffin0000unse",
    },
}

# The Daily Telegraph Cryptic Crossword Book (Pan): the longest line here, past
# 60 volumes by 2010. Every number below is printed, including the one the
# catalogues had lost — isbn_9780330346429 is cased as an unnumbered "Daily
# Telegraph Cryptic Crossword Book" by archive.org and Open Library alike, and
# its own title page reads "Che Daily Telegraph / Cryptic Crossword Book / 32",
# first published 1996 by Pan. Read off the book, because the catalogue's
# silence was about the catalogue.
#
# That same leaf prints Pan's shelf, which is where the four keys under this
# one come from: "Cryptic Crossword Book 17-41", "Big Book of Cryptic
# Crosswords 1-5", "Big Book of Quick Crosswords 1-5", "Sunday Telegraph
# Cryptic Crossword Book 1-7". Four separately numbered lines from one
# publisher for one paper.
SERIES["telegraph"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Telegraph",
    "badge": "telegraph book",
    "shelf": "Telegraph book {volume}",
    "bookTitle": "The Daily Telegraph Cryptic Crossword Book {volume}",
    "name": "Telegraph cryptic crossword, book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        25: "isbn_9780330325868",
        28: "dailytelegraphcr0000dail",
        31: "isbn_9780330343763",
        32: "isbn_9780330346429",
    },
}

# The Daily Telegraph Big Book of Cryptic Crosswords (Pan): the same paper and
# the same publisher as `telegraph`, and a SEPARATE numbering — the 1996 ad
# page quoted above prints "Cryptic Crossword Book 17-41" and "Big Book of
# Cryptic Crosswords 1-5" as two lines of one shelf, so a shared key would file
# this book as a sixth of the other. Twice the size of a numbered book, which
# is why it opens the acquisition plan. The 6 is on the cover; the catalogues
# have it down as unnumbered.
SERIES["telbig"] = {
    "kind": "Big Book {volume} Cryptic",
    "publisher": "Telegraph",
    "badge": "telegraph big book",
    "shelf": "Telegraph big book {volume}",
    "bookTitle": "The Daily Telegraph Big Book of Cryptic Crosswords {volume}",
    "name": "Telegraph cryptic crossword, big book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        6: "dailytelegraphbi0000dail",
    },
}

# The Daily Telegraph Big Book of Brain Sharpener Cryptic Crosswords (Pan,
# 2007). VOLUME 1 IS INVENTED — the cover prints no number at all, and "Brain
# Sharpener" was a 2007 Pan sub-brand spread across puzzle types (there is a
# Brain Sharpener sudoku) rather than a numbered crossword line, so there is
# nothing for this to be the second of.
#
# Not a volume of `telbig`, though both are Pan "Big Books" of the same size:
# that line's numbers are printed and 6 is taken, so filing this one there
# would either collide or give it a number no cover carries.
SERIES["brainsharp"] = {
    "kind": "Brain Sharpener Book {volume} Cryptic",
    "publisher": "Telegraph",
    "badge": "brain sharpener",
    "shelf": "Brain Sharpener book {volume}",
    "bookTitle": "The Daily Telegraph Big Book of Brain Sharpener Cryptic "
                 "Crosswords, volume {volume}",
    "name": "Telegraph cryptic crossword, Brain Sharpener book {volume} "
            "No {position}",
    "officialKey": "never",
    "volumes": {
        1: "isbn_9780330451789",
    },
}

# The Telegraph All New Cryptic Crosswords (Octopus, 2012-2014): the paper's
# other book programme, numbered 1-8 from its own 1 while Pan's line was in its
# fifties. Volume 4 is on the cover.
SERIES["telallnew"] = {
    "kind": "All New Book {volume} Cryptic",
    "publisher": "Telegraph",
    "badge": "telegraph all new",
    "shelf": "Telegraph All New book {volume}",
    "bookTitle": "The Telegraph All New Cryptic Crosswords {volume}",
    "name": "Telegraph cryptic crossword, All New book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        4: "telegraphallnewc0000unse_a7j2",
    },
}

# Telegraph Cryptic Crosswords (Octopus, 2017 onwards, 1-15 and counting): the
# same publisher's NEXT line, and a third Telegraph numbering rather than a
# continuation of the one above — Octopus restarted at 1 under a new title in
# 2017, so an "All New" 2 and a "Cryptic Crosswords" 2 are two books. Volume 2
# is printed.
SERIES["telcryptic"] = {
    "kind": "Crosswords Book {volume} Cryptic",
    "publisher": "Telegraph",
    "badge": "telegraph cryptics",
    "shelf": "Telegraph Crosswords book {volume}",
    "bookTitle": "Telegraph Cryptic Crosswords {volume}",
    "name": "Telegraph cryptic crossword, Crosswords book {volume} "
            "No {position}",
    "officialKey": "never",
    "volumes": {
        2: "telegraphcryptic0000tele",
    },
}

# The Telegraph All New Toughie Crossword (Hamlyn, 2012), "Book 1" printed on
# it. The Toughie is the Telegraph's second daily cryptic and a markedly harder
# one, which is why it is a key and not a volume of `telallnew` beside it: a
# solver choosing a Toughie is choosing the difficulty, and that is the one
# thing a badge exists to say.
SERIES["toughie"] = {
    "kind": "Toughie Book {volume} Cryptic",
    "publisher": "Telegraph",
    "badge": "toughie",
    "shelf": "Toughie book {volume}",
    "bookTitle": "The Telegraph All New Toughie Crossword, book {volume}",
    "name": "Telegraph Toughie crossword, book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        1: "telegraphallnewt0000tele",
    },
}

# The Sunday Telegraph Book of Cryptic Crosswords (Pan): a different paper from
# the daily — its own masthead and its own setters — numbered to 14 by 2007.
# All three volumes here print their number on the cover in one house design,
# and only the 4 reached the catalogues: archive.org and Open Library both list
# 1 and 2 as untitled reprints, which would have made three numbered volumes
# look like three unnumbered ones and cost two invented numbers. Read the
# covers. The gap at 3 is a book nobody has scanned, not a mistake here.
SERIES["sundaytel"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Sunday Telegraph",
    "badge": "sunday telegraph",
    "shelf": "Sunday Telegraph book {volume}",
    "bookTitle": "The Sunday Telegraph Book of Cryptic Crosswords {volume}",
    "name": "Sunday Telegraph cryptic crossword, book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        1: "isbn_9780330339605",
        2: "sundaytelegraphb0000sund",
        4: "isbn_9780330350013",
    },
}

# Daily Mail New Cryptic Crosswords (Hamlyn, 2007): volume 2, printed on the
# cover, of a line that runs to at least 12. The only tabloid on the shelf, and
# the only book here that prints its own puzzle count — "A new compilation of
# 100 Daily Mail Crosswords", against the 123 the sample extrapolated. That gap
# is the over-count tools/data/book_candidates.json's own calibration warns
# about, measured for once against a number the book states.
SERIES["dailymail"] = {
    "kind": "Book {volume} Cryptic",
    "publisher": "Daily Mail",
    "badge": "daily mail",
    "shelf": "Daily Mail book {volume}",
    "bookTitle": "Daily Mail New Cryptic Crosswords, volume {volume}",
    "name": "Daily Mail cryptic crossword, book {volume} No {position}",
    "officialKey": "never",
    "volumes": {
        2: "isbn_9780600616405",
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
