#!/bin/bash
# Does a Canberra Times reprint of a London Times puzzle vote on the scan's
# clues like any other reading (file_archive_org_puzzles.reprint_readings),
# only for the London number tools/canberra_london_numbers.py maps it to and
# only in the Times series, and does a reprint downloaded or read after an
# edition make that edition due again (inputs_of), and no other?
#
#     bash tools/test_canberra_reprint_vote.sh
#
# A synthetic Trove cache in a temp dir: no scan, no OCR, nothing written
# outside it.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import json, sys
from pathlib import Path
import file_archive_org_puzzles as fa
import ocr_clues as oc

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

tmp = Path(sys.argv[1])
trove = tmp / "trove"
(trove / "101").mkdir(parents=True)
(trove / "102").mkdir(parents=True)
(trove / "london_numbers.json").write_text(json.dumps({
    "101": {"date": "1975-11-01", "how": "matched", "number": 14025},
    "102": {"date": "1975-11-03", "how": "bracketed", "number": 14026}}))
lists = "ACROSS\n1 Start from Hint (5).\n3 Top (3).\nDOWN\n1 Bun (3).\n2 Arc (3).\n"
(trove / "101" / "ocr.txt").write_text("Canberra Times, page 13\nTIMES CRYPTIC CROSSWORD\n" + lists)
zones = fa.ftp.clue_zones(trove / "101") / "101"
zones.mkdir(parents=True)
(zones / "read.ch.txt").write_text(lists)
fa.TROVE = trove

got = fa.reprint_readings(14025, "times")
check("a mapped reprint's Trove text and each reader's text vote", ["canberra:101:ocr", "canberra:101:read.ch"],
      sorted(got))
check("a reprint's reading parses as a scan reading does", 2, len(fa.parse(got["canberra:101:ocr"])[0]["down"]))
check("a number no reprint is mapped to has no reprint reading", {}, fa.reprint_readings(14027, "times"))
check("a reprint votes only in the series it reprints (FT numbers overlap)", {}, fa.reprint_readings(14025, "ftcryptic"))
check("a mapped reprint not downloaded yet has no reading", {}, fa.reprint_readings(14026, "times"))

# A reprint reading is set out as a column reading: the article's page text
# and the next puzzle cut off, a clue number misread "I" read as its list's
# order has it, a line-end hyphen kept at a line end.
page = ("Canberra Times, page 13\nTIMES CRYPTIC CROSSWORD\nACROSS\n1 Those who employ top-\nless nurses? (5).\n"
        "DOWN\nI They're not trustworthy,\nsang David (7).\n2 Price of make-up (5)\nSolution on Page 15.\n"
        "FIGURE IT OUT by J. A. H. Hunter\n")
check("a reprint reading is cut to its lists, one clue a line",
      "ACROSS\n1 Those who employ top-\nless nurses? (5)\nDOWN\n1 They're not trustworthy, sang David (7)\n"
      "2 Price of make-up (5)\n", fa.reprint_text(page))
check("a page with no lists is no reading", None, fa.reprint_text("Canberra Times, page 13\nNews of the day"))

# Every reading votes: where the scan's two readings split ("Hunt" /
# "Hint"), the laid one stands alone and the reprint's readings settle it;
# a clue the reprint prints as laid is left alone.
other = "ACROSS\n1 Start from Hint (5).\n3 Top (3).\nDOWN\n1 Bun (3).\n2 Arc (3).\n"
laid = {"1-across": ("Start from Hunt", "5", None), "3-across": ("Top", "3", None)}
lengths = {"1-across": 5, "3-across": 3}
alone, _ = oc.reconcile(laid, [other], lengths)
check("without the reprint a split vote keeps the laid misread", "Start from Hunt", alone["1-across"][0])
voted, _ = oc.reconcile(laid, [other] + list(got.values()), lengths)
check("with the reprint's readings the word is settled", "Start from Hint", voted["1-across"][0])
check("a clue the reprint prints as laid is left alone", "Top", voted["3-across"][0])

# An edition's inputs: unchanged for one with no reprint, so nothing else is
# read again; moved when its reprint is downloaded, and again when read.
fa._REPRINTS.clear()
found = {"puzzles": [{"number": 14026}]}
check("an edition with no reprint text keeps its files' hash as its inputs", "abc", fa.inputs_of("abc", found, "times"))
check("an FT edition of the same number keeps its files' hash", "abc",
      fa.inputs_of("abc", {"puzzles": [{"number": 14025}]}, "ftcryptic"))
(trove / "102" / "ocr.txt").write_text(lists)
first = fa.inputs_of("abc", found, "times")
check("a reprint downloaded after the edition was read makes it due", True, first != "abc")
z2 = fa.ftp.clue_zones(trove / "102") / "102"
z2.mkdir(parents=True)
(z2 / "read.en5.txt").write_text(lists)
check("a reprint's columns read after it makes the edition due again", True,
      fa.inputs_of("abc", found, "times") != first)
print("FAILS", fails)
sys.exit(1 if fails else 0)
PY
