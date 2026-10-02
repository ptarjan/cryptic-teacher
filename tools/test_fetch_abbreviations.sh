#!/usr/bin/env bash
# fetch_abbreviations.senses() reads what a wiktextract entry says an
# abbreviation stands for, and nothing it only mentions; list_senses() reads
# the crossword list's readings and skips the synonyms it mentions.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import fetch_abbreviations as f

def entry(word, *senses, pos="noun"):
    return {"word": word, "pos": pos, "senses": list(senses)}

def alt(*words, tags=("abbreviation", "alt-of")):
    return {"tags": list(tags), "alt_of": [{"word": w} for w in words]}

def gloss(text, tags=()):
    return {"tags": list(tags), "glosses": [text]}

cases = [
    ("the first alt_of word, a trailing remark dropped",
     entry("Co", alt("company", "alternative form of Co")), [("company", "CO")]),
    ("three or more alt_of words are one phrase cut apart, and name nothing",
     entry("TRBL", alt("top", "right", "bottom", "left")), []),
    ("X or Y is two clue words; dots drop out of the letters",
     entry("l.", alt("litre or liter")), [("litre", "L"), ("liter", "L")]),
    ("run(s) is run and runs", entry("R", alt("run(s)")), [("run", "R"), ("runs", "R")]),
    ("a leading article goes unless the letters spell it",
     entry("g", alt("the gram")), [("gram", "G")]),
    ("an article the letters spell stays", entry("th'one", alt("the one", tags=["contraction"])),
     [("the one", "THONE")]),
    ("a Symbol's short gloss, its opener cut",
     entry("Cu", gloss("Chemical element symbol for copper."), pos="symbol"), [("copper", "CU")]),
    ("a gloss up to its first comma", entry("N", gloss("newton, the SI unit of force."),
                                            pos="symbol"), [("newton", "N")]),
    ("a definition gloss is not an expansion",
     entry("A", gloss("A standard size of dry cell battery."), pos="symbol"), []),
    ("a sense without an abbreviation tag is skipped", entry("R", gloss("river")), []),
    ("non-ASCII forms are skipped", entry("⠽", gloss("you", ["contraction"])), []),
]
page = "intro <small>XX</small>\n==A==\n"
cases += [
    ("a list line's readings, a parenthetical ignored",
     page + "* Old – <small>O</small>, <small>OL</small> (e.g. \"good ol' boy\")",
     [("old", "O"), ("old", "OL")]),
    ("a line naming several clue words gives each the readings",
     page + "* Sleep, Snooze or Asleep - <small>Z</small>", [("sleep", "Z"), ("snooze", "Z"), ("asleep", "Z")]),
    ("a linked reading is what the link shows", page + "* Side – <small>[[Leg side|ON]]</small>",
     [("side", "ON")]),
    ("a dictionary word of three or more letters is a synonym, not an abbreviation",
     page + "* Sailor – <small>AB</small>, <small>TAR</small>", [("sailor", "AB")]),
    ("a short reading that is a word stays", page + "* At home – <small>IN</small>", [("at home", "IN")]),
    ("nothing above the A-to-Z lines is read", page, []),
]
fails = 0
for name, e, want in cases:
    got = list(f.list_senses(e, {"TAR", "IN"}) if isinstance(e, str) else f.senses(e))
    ok = got == want
    fails += not ok
    print(f"  {'ok' if ok else 'FAIL'}: {name}" + ("" if ok else f"\n    want {want}\n    got  {got}"))
raise SystemExit(fails)
PY
