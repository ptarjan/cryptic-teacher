#!/usr/bin/env python3
# Does tools/indy_puzzles.py send each fifteensquared Independent post to the
# right paper, and date the Sunday puzzles in order?
#
#     python3 tests/test_indy_puzzles.py
#
# One blog category carries the daily and the Independent on Sunday, so a
# misrouted title files a puzzle under the other paper's numbering. Titles are
# real ones off the blog; nothing here reads the cache or the corpus.
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import indy_puzzles as I
import ft_puzzles as F

fails = 0


def check(what, expected, got):
    global fails
    if expected == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{expected}], got [{got}]")
        fails += 1


def route(title):
    return I.series_of(title, F.post_number(title))


daily = [route(t) for t in (
    "Independent 7,554 by Phi (Saturday Prize Puzzle, 01/01/11)",
    "Indy 7728 Klingsor (Sat 23-Jul-2011)",
    "Independent no 8340 by Donk.",
    "Independent  7,950 / Morph  (Saturday Prize Crossword 7/04/12)")]
sunday = [route(t) for t in (
    "Independent on Sunday 1218/Kairos", "IoS 1,246 / Poins")]
# A title and a number that disagree, and the magazine's barred puzzle.
none = [route(t) for t in (
    "Independent on Sunday 8,123 by Phi", "Independent 1,218 / Kairos",
    "Inquisitor 1234 by Schadenfreude", "Independent Magazine 9,001")]

setter = [I.setter_of(t) for t in (
    "Independent 8925 Sat 23-May-2015 Monk", "Independent 8,839 by Monk",
    "Independent 7,950 / Morph  (Saturday Prize Crossword 7/04/12)",
    "Independent 7,734 / Saturday Prize Puzzle 10 September 2011 by Mordred",
    "Independent on Sunday 1,102 / Poins. Heart to heart",
    "Independent 7,700 Saturday Prize Puzzle", "Independent on Sunday 1154/Glow-worm")]

# Titles with no "/" or dash before the setter. The setters filed on disk are
# stubbed: a title that names one anywhere is read for it.
I.known_setters = lambda: {"hypnos": "Hypnos", "phi": "Phi", "glow-worm": "Glow-worm"}
byline = [I.setter_of(t) for t in (
    "Independent on Sunday 1106, by Glowworm",
    "Independent on Sunday 1017 by Quixote  9 Aug 2009",
    "Independent Prize Crossword 8847 by Anax, 21/02/15",
    "Independent 6622 (Hypnos)", "Independent 6634 (Glow-Worm)",
    "Independent 6692 Phi / Weekend Warm Up",
    "Independent 7321, Sat 3 April – Merlin", "Independent 6540\\Virgilius",
    "Independent on Sunday 1,521/21 April", "Independent 9077")]

rows = [{"number": 1218, "date": "2013-06-30"},   # a Sunday: itself
        {"number": 1219, "date": "2013-07-09"},   # blogged late: the Sunday before
        {"number": 1220, "date": "2013-07-03"}]   # a date that falls back is dropped
dates = {n: d and d.isoformat() for n, d in sorted(I.sunday_dates(rows).items())}

# A file holding untidied clues is tidied on the next run,
# and only one this tool wrote, though its post is never parsed again: the
# grid row's record is gone, so the files are walked.
tmp = Path(tempfile.mkdtemp())
try:
    (tmp / "parsed.jsonl").write_text("")
    (tmp / "grids.jsonl").write_text(json.dumps({"post_id": 1, "number": 9000, "series": I.DAILY,
                                                 "date": "2016-01-04", "grid": []}) + "\n")
    (tmp / "held.json").write_text("{}")
    I.CACHE = tmp
    I.puzzle_path = lambda series, number: tmp / "held.json"
    (tmp / I.DAILY / "2016").mkdir(parents=True)
    (tmp / I.DAILY / "2016" / "independent-9000.json").write_text("{}")
    I.puzzle_files = lambda: sorted(tmp.glob("*/*/*.json"))
    held = {"id": "independent-9000", "source": {"acquiredBy": I.GENERATOR},
            "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0}, "length": 5,
                         "clue": {"text": "Spoil / steep-sided passage", "enumeration": "5"}, "solution": "GULLY"}]}
    I.read_puzzle_file = lambda path: json.loads(json.dumps(held))
    written = []
    I.write_puzzle_file = lambda path, puzzle, **kw: written.append(puzzle["entries"][0]["clue"]["text"])
    I.file([{"series": I.DAILY, "number": 9000, "date": "2016-01-04", "post_id": 1}], write=True)
    held["source"]["acquiredBy"] = "tools/fetch_independent.py"
    I.file([{"series": I.DAILY, "number": 9000, "date": "2016-01-04", "post_id": 1}], write=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

check("daily titles go to the daily",
      "['independent', 'independent', 'independent', 'independent']", str(daily))
check("Sunday titles go to the Sunday paper", "['indysunday', 'indysunday']", str(sunday))
check("a disagreeing title or another puzzle goes nowhere", "[None, None, None, None]", str(none))
check("a print date in the title is not the setter",
      "['Monk', 'Monk', 'Morph', 'Mordred', 'Poins', None, 'Glow-worm']", str(setter))
check("a byline anywhere, a filed setter's name, a lone name in brackets",
      "['Glowworm', 'Quixote', 'Anax', 'Hypnos', 'Glow-worm', 'Phi', 'Merlin', 'Virgilius', None, None]",
      str(byline))
check("Sunday dates rise with the numbers",
      "{1218: '2013-06-30', 1219: '2013-07-07', 1220: None}", str(dates))
check("a held file of this tool's is tidied; the feed's is not",
      "['Spoil steep-sided passage']", str(written))

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all passed")
