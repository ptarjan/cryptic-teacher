#!/usr/bin/env python3
"""The one table that says what each crossword series IS.

Every series fact the tools need — who publishes it, what to call it, how gentle
it is, what to do when the feed ships no setter name — lives here and nowhere
else. Import it; don't re-declare it.

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

# gentleness — the order the pre-reset backfill annotates in, lowest first.
#   It is a teaching judgement, not a measurement: an un-annotated *beginner*
#   puzzle is the worst thing on the site, because the people it is for are
#   exactly the people who can't get through it unaided. The measured
#   difficulty in tools/difficulty.py is a separate thing and rates individual
#   puzzles; this rates the series' intent.
# setter — used only when the source publishes no byline. Absent means the
#   feed always names a setter and a missing one is a scraping bug worth
#   showing as "Unknown".
SERIES = {
    "cryptic": {
        "kind": "Cryptic",
        "publisher": "Guardian",
        "gentleness": 3,
    },
    "quiptic": {
        "kind": "Quiptic",
        "publisher": "Guardian",
        "gentleness": 1,
    },
    "everyman": {
        "kind": "Everyman",
        "publisher": "Observer",
        "gentleness": 2,
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
        "gentleness": 0,
        "setter": "Cryptic Teacher",
    },
    "independent": {
        "kind": "Cryptic",
        "publisher": "Independent",
        # Pitched at the same level as the Guardian daily — Phi, Quince, Lark
        # and the rest are not writing a beginner puzzle — so it queues with
        # the cryptic rather than ahead of it.
        "gentleness": 3,
    },
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


def gentleness(series):
    return meta(series)["gentleness"]


def default_setter(series):
    return meta(series).get("setter", "Unknown")


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
def puzzle_id(series, number):
    return f"{series or 'cryptic'}-{number}"


def parse_id(pid):
    """("everyman", 4165) out of "everyman-4165".

    A bare number is a pre-namespacing id and says nothing about its series —
    every series used them — so resolving one means asking the index which
    puzzle has that number, not asking this function.
    """
    series, sep, number = str(pid).rpartition("-")
    return (series if sep else None), int(number)
