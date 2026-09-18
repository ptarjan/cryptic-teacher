#!/bin/bash
# Can the Independent parser still name a puzzle whose <title> is not a title?
#
#     bash tools/test_fetch_independent.sh
#
# Two separate things decide a file's name, and this feed can get both wrong at
# once. The NUMBER comes off a title, and for everything before September 2015
# <metadata><title> is not one: usually empty, otherwise whatever the setter was
# using to keep track ("Hob 23"). The SERIES comes off the date key's weekday,
# and the number must never be allowed a vote — the daily and the Sunday
# sequences both ran under 10,000 before 2019, so any threshold over the number
# misfiles one as the other.
#
# The cases below are the real title strings, on their real date keys, around a
# grid small enough to read. Each asserts the whole id, so a right number under
# the wrong series fails exactly as loudly as a wrong number.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import sys

sys.path.insert(0, "tools")
import fetch_independent as fi

CELLS = "".join(
    '<cell x="%d" y="1" solution="%s"%s></cell>'
    % (i + 1, letter, ' number="1"' if i == 0 else "")
    for i, letter in enumerate("SOLVE"))


def doc(meta, heading, tail=""):
    """One day's feed file: a five-cell grid under the two titles under test."""
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<crossword-compiler xmlns="http://crossword.info/xml/crossword-compiler">'
            '<rectangular-puzzle xmlns="http://crossword.info/xml/rectangular-puzzle">'
            '<metadata><title>%s</title></metadata>'
            '<crossword><grid width="5" height="1">%s</grid>'
            '<word id="1" x="1-5" y="1"></word>'
            '<clues ordering="normal"><title>%s</title>'
            '<clue word="1" number="1" format="5">Work out this one</clue>'
            '</clues></crossword></rectangular-puzzle></crossword-compiler>%s'
            % (meta, CELLS, heading, tail)).encode("utf-8")


# (what it pins, date key, <metadata> title, Across-list heading, id, setter)
CASES = [
    ("an empty title falls back to the clue-list heading",
     "150701", "", "<b>Quixote-8958...Across</b>", "independent-8958", "Quixote"),
    ("a scratch note in the title does not beat the heading",
     "150605", "Hob 23", "<b>Hob-8936...Across</b>", "independent-8936", "Hob"),
    ("a title that is only the paper's name falls back too",
     "150607", "Independent Crossword", "<b>Hypnos-1320...Across</b>",
     "indysunday-1320", "Hypnos"),
    ("a heading with two dots instead of three still reads",
     "150719", "", "<b>Rorschach-8973..Across</b>", "independent-8973", "Rorschach"),
    ("a Monday before the feed's day-shift is the daily, not the Sunday paper",
     "150601", "", "<b>Punk-8932...Across</b>", "independent-8932", "Punk"),
    ("a Sunday inside the day-shift is the daily",
     "150726", "", "<b>Tees-8979...Across</b>", "independent-8979", "Tees"),
    ("a Monday inside the day-shift is the Sunday paper",
     "150727", "1327 by Kairos", "<b>Kairos-1327...Across</b>", "indysunday-1327", "Kairos"),
    ("a Sunday after the day-shift is the Sunday paper again",
     "150823", "", "<b>Klingsor-1330...Across</b>", "indysunday-1330", "Klingsor"),
    ("a number under 10,000 on a weekday is still the daily",
     "180703", "Raich 9897", "<b>Across</b>", "independent-9897", "Raich"),
    ("a heading that prints the date is still corrected to the real number",
     "150612", "", "<b>Phi-150613...Across</b>", "independent-8942", "Phi"),
]

fails = 0


def check(why, got, want):
    global fails
    if got == want:
        print("  ok: %s" % why)
    else:
        print("  FAIL: %s\n    want %r\n    got  %r" % (why, want, got))
        fails += 1


def named(xml, ymd):
    try:
        p = fi.parse(xml, ymd)
    except Exception as err:  # noqa: BLE001 — a raise here is a failure, not a crash
        return "%s: %s" % (type(err).__name__, err)
    return "%s/%s" % (p["id"], p["setter"])


for why, ymd, meta, heading, want_id, want_setter in CASES:
    check(why, named(doc(meta, heading), ymd), "%s/%s" % (want_id, want_setter))

# Some days are served as a complete document with a second, partial copy of
# the same puzzle appended. XML has one root, so the tail has to go or the day
# is unparseable and simply absent.
check("a second copy appended after the root is ignored",
      named(doc("", "<b>Quixote-8958...Across</b>", "\n/word>\n<clues>"), "150701"),
      "independent-8958/Quixote")

# The name is not all we want back: the fallback must not cost the puzzle.
p = fi.parse(doc("", "<b>Quixote-8958...Across</b>"), "150701")
check("the clue keeps its enumeration", p["entries"][0]["clue"], "Work out this one (5)")
check("the solution is read off the grid", p["entries"][0]["solution"], "SOLVE")
check("the daily is named as the Independent", p["name"],
      "Independent cryptic crossword No 8,958")
check("the weekly is named as the Independent on Sunday",
      fi.parse(doc("", "<b>Hypnos-1320...Across</b>"), "150607")["name"],
      "Independent on Sunday cryptic crossword No 1,320")

# A day with neither a usable title nor a numbered heading must refuse rather
# than invent a number: the feed is keyed by date, so a wrong number writes a
# real puzzle over another day's and nothing downstream would notice.
check("a day with no number anywhere is refused",
      named(doc("", "<b>Across</b>"), "150701").split(":")[0], "ValueError")

print("FAILED: %d" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
PY
