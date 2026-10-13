#!/bin/bash
# Does tools/clue_repair.py give a clue whose bracket its own reading lost
# the count another reading prints, in its parts, so the scan filers file
# "3,6,5" and not the bare letter total "14"?
#
#     bash tools/test_clue_repair.sh
#
# The readings are real: the Times of 31 August 1990 (No 18,387), 17 across,
# SIR EDWARD ELGAR, as RapidOCR's two models read its clue column
# (~/.cache/archive_org_crops/rapid/1990-08-31_63799_18387.{ch,en5}.json):
# "composer (3,6.5)." and "composer (3.6.5).". Until 10-13 the repair kept
# only the total of a count in parts (count_only), file_trove_puzzles.match
# laid no count, and ocr_clues.reconcile filed the grid's "14". The Times of
# 7 May 1974 (No 13,681) prints 5 down's "(7, 2. 3, 3)."
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export VLM_READER_URL=
cd "$REPO/tools" && python3 - <<'EOF'
import sys
import clue_repair
import enumeration
import file_trove_puzzles as ftp
from file_penguin_puzzle import separators

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")


# The count after a clue's last words, as each reader prints it.
for seg, want in (("composer (3,6.5).", "3,6,5"), ("composer (3.6.5).", "3,6,5"),
                  ("by ihe sound of it (2.7).", "2,7"), ("Ide hlgh Living ? (7, 2. 3, 3).", "7,2,3,3"),
                  ("13 Little Mary rolls in ir? (5-6).", "5-6"), ("novel (8,6).", "8,6")):
    tail = seg[seg.index("("):]
    check(f"tail_enum reads {tail!r} as {want}", want, clue_repair.tail_enum(" " + tail, {19, 21}))

# The list's own reading lost 17 across's bracket ("(9)." is 15's, read on
# the line before); the ch and en5 readings of the column supply it.
clue = "A girl's rewarded for reforming a composer"
for name, line in (("ch", "composer (3,6.5)."), ("en5", "composer (3.6.5).")):
    stream = ("15 Harshly they covered the retreat (9). 17 A girl's rewarded for reforming a "
              f"{line} 19 Exult as poet is moved to protest (6).")
    parsed = {"across": [
        {"tokens": [{15}], "text": "Harshly they covered the retreat", "enums": {"9"}, "see": None},
        {"tokens": [{17}], "text": clue, "enums": set(), "see": None},
        {"tokens": [{19}], "text": "Exult as poet is moved to protest", "enums": {"6"}, "see": None}],
        "down": []}
    got, notes = clue_repair.repair(parsed, stream)
    c = got["across"][1]
    check(f"{name}: 17 across takes the count in its parts", ({"3,6,5"}, False),
          (c["enums"], bool(c.get("count_only"))))

    # Laid on a grid whose 17 across holds 14 letters, the parts are filed.
    grid =["." * 9 + "#" * 6, "#" * 15, "." * 14 + "#", "#" * 15, "." * 6 + "#" * 9]
    laid, why = ftp.match({"across": [dict(c2, tokens=[{n}]) for c2, n in zip(got["across"], (1, 2, 3))],
                           "down": []}, grid)
    check(f"{name}: match lays 3,6,5 on the 14-letter light, not a bare 14",
          ("3,6,5", None), ((laid or {}).get("2-across", (None, None))[1], why))
    enum = (laid or {}).get("2-across", (None, "14"))[1]
    seps = separators(["2-across"], {"2-across": {"number": 2, "direction": "across", "length": 14}}, enum)
    filed = enumeration.clue(f"{clue} ({enum})", separators=seps.get("2-across"))
    check(f"{name}: filed with its word breaks", ("3,6,5", [3, 9]),
          (filed.get("enumeration"), [s["at"] for s in filed.get("separators", [])]))

sys.exit(1 if fails else 0)
EOF
