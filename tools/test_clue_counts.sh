#!/bin/bash
# Does a clue that carries its own letter count, or a stray letter, get refused?
#
#     bash tools/test_clue_counts.sh
#
# A source that prints the count in the clue, with the answer's count appended
# after it, leaves "Set meal ... (5,1’4)" over enumeration "5,5"; a feed can
# leave a stray "d" stuck to a "?". enumeration.split() cuts
# the echo, and puzzle_integrity (so every write) refuses what is left.
# A year or a quantity in brackets ("(1917)", "(500)") is the clue's words.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import copy, json, sys

sys.path.insert(0, "tools")
import enumeration
import puzzle_integrity as pi

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


check("echoed count is cut", enumeration.split("Set meal (5,1’4) (5,5)"), ("Set meal", "5,5"))
check("prime and non-breaking marks read", enumeration.split("Whip (3-1′-4-5)"), ("Whip", "3-1'4-5"))
check("echo behind a stray closing quote is cut (toughie-3684 6D)",
      enumeration.split("Hassled on and off outside quiet church recess (4)’ (4)"),
      ("Hassled on and off outside quiet church recess", "4"))
check("count behind a stray closing quote is unsplit",
      enumeration.unsplit({"text": "Hassled (4)’", "enumeration": "4"}, {4}), True)
check("a different total is not an echo", enumeration.split("Platform (7) (5)"), ("Platform (7)", "5"))
clue = {"text": "Set meal (5,1’4)", "enumeration": "5,5"}
check("count under an enumeration is unsplit", enumeration.unsplit(clue, {10}), True)
check("a year is kept", enumeration.unsplit({"text": "Exile (1917)", "enumeration": "5"}, {5}), False)
check("a quantity is kept", enumeration.unsplit({"text": "Sheets (500)", "enumeration": "5"}, {5}), False)
check("a cross-reference is kept", enumeration.unsplit({"text": "See (3dn.)", "enumeration": "5"}, {5}), False)

puzzle = json.load(open("puzzles/telegraph/2013/telegraph-27152.json"))


def shape(p):
    flags = []
    pi.check_shape(p, pi.datetime.now(pi.timezone.utc).date(), flags)
    return [w for _, _, w in flags if "enumeration" in w or "stray" in w or "prints (" in w]


check("filed puzzle is clean", shape(puzzle), [])
bad = copy.deepcopy(puzzle)
c = bad["entries"][0]["clue"]
c["text"] += f" ({c['enumeration']})"
check("a repeated count is refused", len(shape(bad)), 1)
bad = copy.deepcopy(puzzle)
bad["entries"][0]["clue"]["text"] += "?d"
check("a stray letter is refused", len(shape(bad)), 1)
for junk in ("))", "!", ";", ">", ".", "..", " –"):
    check(f"marks {junk!r} after the count are cut",
          enumeration.split(f"Consider a short period in river (7){junk}"),
          ("Consider a short period in river", "7"))
check("stray marks after a count are stray",
      enumeration.stray({"text": "Erotic troupe in seedy void (6)!", "enumeration": "6"}), True)
check("a bare count is not stray", enumeration.stray({"text": "Erotic troupe (6)", "enumeration": "6"}), False)
# cryptic-26430 prints "Mother's cross raised (3); (4)" under a preamble giving
# seven clues two counts: the "(3);" is the clue's, not markup.
dual = {"text": "Mother's cross raised (3);", "enumeration": "4"}
check("the first of two counts is not stray", enumeration.stray(dual, {4}), False)
check("the first of two counts is the clue's", enumeration.disagrees(dual, {4}), None)
check("two counts with one total are both kept (cyclops-537 60-across)",
      enumeration.split('Osborne right ... Mirth"? (6,5); (4,7)'), ('Osborne right ... Mirth"? (6,5);', "4,7"))
check("the first of two counts with one total is not unsplit",
      enumeration.unsplit({"text": "Mirth? (6,5);", "enumeration": "4,7"}, {11}), False)
check("two counts in one bracket are the clue's",
      enumeration.disagrees({"text": "Royal baby mould via singing comedian (6;6)", "enumeration": "5,6"}, {11}), None)
# ftcryptic-7261 8-down: the scan prints (7,6), the OCR read "(7.8) ' -".
misread = {"text": "Advice note can change ' prior announcement (7.8) ' -", "enumeration": "7,6"}
check("a count the light cannot hold is not stray", enumeration.stray(misread, {13}), False)
check("a count the light cannot hold disagrees", enumeration.disagrees(misread, {13}), "7.8")
check("a paper's first count before the entry's is the clue's (toughie-277)",
      enumeration.disagrees({"text": "Platform from up on high? (5)", "enumeration": "7"}, {7}), None)
check("a year is not a disagreeing count",
      enumeration.disagrees({"text": "Exile (1917)", "enumeration": "5"}, {5}), None)
check("a year behind a mark is the clue's words",
      enumeration.split("Be remembered as would Titanic (1912) or prices (1929)?"),
      ("Be remembered as would Titanic (1912) or prices (1929)?", None))
check("an echo behind marks is cut", enumeration.split("Dip in river (7)). (7)"), ("Dip in river", "7"))
bad = copy.deepcopy(puzzle)
c = bad["entries"][0]["clue"]
c["text"] += f" ({c['enumeration']})!"
check("stray marks behind the clue's own count are refused", len(shape(bad)), 1)
bad = copy.deepcopy(puzzle)
c = bad["entries"][0]["clue"]
c["text"] += f" ({bad['entries'][0]['length'] + 2}) –"
check("a count the entry cannot have is refused", len(shape(bad)), 1)
bad = copy.deepcopy(puzzle)
bad["entries"][0]["clue"]["text"] += " (3);"
check("the first of two counts is kept", shape(bad), [])
sys.exit(1 if fails else 0)
PY
