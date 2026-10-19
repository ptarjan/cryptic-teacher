#!/usr/bin/env python3
# Does tools/clue_repair.py give a clue whose bracket its own reading lost
# the count another reading prints, in its parts, so the scan filers file
# "3,6,5" and not the bare letter total "14"?
#
#     python3 tools/test_clue_repair.py
#
# The readings are real: the Times of 31 August 1990 (No 18,387), 17 across,
# SIR EDWARD ELGAR, as RapidOCR's two models read its clue column
# (~/.cache/archive_org_crops/rapid/1990-08-31_63799_18387.{ch,en5}.json):
# "composer (3,6.5)." and "composer (3.6.5).". Until 10-13 the repair kept
# only the total of a count in parts (count_only), file_trove_puzzles.match
# laid no count, and ocr_clues.reconcile filed the grid's "14". The Times of
# 7 May 1974 (No 13,681) prints 5 down's "(7, 2. 3, 3)."
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.environ["VLM_READER_URL"] = ""
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

# One clue's own slips (clue_repair.mend_text). Cases are the filed texts the
# Times 1998 "Update times-" rereads of 16-18 Oct 2026 changed (times-20866,
# -20976, -21009, -21013, -21210, -21262, -21069, -21007 ...): the text as
# first filed, and what the vision reread settled. Each must come out as the
# reread has it, and the reread (or a clue that was right) must not change.
for what, text, enum, want in (
        ("the count left after the words", "Mostly smart English group indulging in idle gossip 9.", "9",
         "Mostly smart English group indulging in idle gossip"),
        ("a neighbour's count and number in front",
         "Not all bound over can be set free (4) 101 Described the beautiful French diamonds", "8",
         "Described the beautiful French diamonds"),
        ("a neighbour's count and number in front, a count in parts",
         "Spirit that's characteristic of those moving East (5) 131 I can produce PR cons, and do it to order",
         "4,6", "I can produce PR cons, and do it to order"),
        ("a bar read as I before a capital", "I Gratuitous flattering", "13", "Gratuitous flattering"),
        ("a bar read as I before a capital, again", "I Long pair of shorts?", "6", "Long pair of shorts?"),
        ("a drop capital printed twice", "S Sound judgment to lift fuel to 'Berlin, say", "5",
         "Sound judgment to lift fuel to 'Berlin, say"),
        ("a word broken by a space", "Inspire learner to abandon de pressed profession?", "9",
         "Inspire learner to abandon depressed profession?"),
        ("a stop on its own between words", "Fodder for the right variety of grey . donkey", "6",
         "Fodder for the right variety of grey donkey"),
        ("a middle dot", "Broadcasts most of · Aida in specified amounts", "9",
         "Broadcasts most of Aida in specified amounts"),
        ("a stop after a lone a", "Fighter thrown in jail for a. short stretch", "8",
         "Fighter thrown in jail for a short stretch"),
        ("a letter swapped in a word nobody prints", "Erect after firm stfoke", "5", "Erect after firm stroke"),
        # What is left alone.
        ("a reference to a number", "Numbers will include zero and 5", "5", "Numbers will include zero and 5"),
        ("a count that is not the light's", "Sound lad with energy 7", "5", "Sound lad with energy 7"),
        ("a clue that is right", "Gratuitous flattering", "13", "Gratuitous flattering"),
        ("I as a word", "I dial a dept. about waste", "8", "I dial a dept. about waste"),
        ("a name after I", "I Claudius perhaps", "8", "I Claudius perhaps"),
        ("initials and their stops", "Mutant battles L.A. in The Gastropod Killer", "6",
         "Mutant battles L.A. in The Gastropod Killer"),
        ("a leader's two stops stand mid-clue", "Verse delivered in church office .. ahead of time", "5",
         "Verse delivered in church office .. ahead of time"),
        ("a trailer's two stops become an ellipsis", "Eccentric applies rum to testicle, ..", "5",
         "Eccentric applies rum to testicle, …")):
    check(f"mend_text: {what}", want, clue_repair.mend_text(text, enum))

# A count left in the text is named by fetch_puzzle.clue_leftovers, and only then.
import fetch_puzzle
leftovers = fetch_puzzle.clue_leftovers([
    {"number": 9, "direction": "across", "clue": {"text": "idle gossip 9.", "enumeration": "9"}},
    {"number": 10, "direction": "across", "clue": {"text": "Numbers include zero and 5", "enumeration": "5"}},
    {"number": 1, "direction": "down", "clue": {"text": "Next (4) 101 Our clue words", "enumeration": "8"}},
    {"number": 2, "direction": "down", "clue": {"text": "Plain clue", "enumeration": "5"}}])
check("clue_leftovers names the count and the neighbour, not a reference",
      {"9-across": "the clue's count left in its text",
       "1-down": "another clue's count and number run into it"}, leftovers)

# A reader's own number run into its clue (1948 Gale: "2 Foozle" for 22-down,
# "100 times it is almighty" for 18-down): only up to one figure over the light's.
check("a leaked clue number is taken off its clue", ["Foozle", "times it is almighty", "I have left the robber"],
      [clue_repair.leaked_number("2 Foozle", "22-down"), clue_repair.leaked_number("100 times it is almighty", "18-down"),
       clue_repair.leaked_number("2 1 have left the robber", "22-down").replace("1 have", "I have")])
check("a clue opening with more figures than its number is left", "1999 and all that",
      clue_repair.leaked_number("1999 and all that", "7-down"))
import ocr_clues
check("worn type's shared slips are put back to the lexicon word",
      "Men order some get-up for these receptions, a grim era, extenuate",
      ocr_clues.unworn("Men ordcr somo get-up for thesc rcccptions, a grim cra, cxtenuate"))
check("a known word, a name and a word with no lexicon spelling are left", "Aladdin cf xyzzy",
      ocr_clues.unworn("Aladdin cf xyzzy"))

import clue_text
_p = {"across": [{"tokens": [{23}], "text": "Unshipped blossom is much the same", "see": None, "enums": {"5"}},
                 {"tokens": [{24}], "text": "The talk of the town 25 5 Bury fat", "see": None, "enums": {"9"}},
                 {"tokens": [{26}], "text": "Extremes indicated", "see": None, "enums": {"4,3,6"}}], "down": []}
_got = clue_repair.split_run_on(_p)[0]["across"]
check("a next clue's number then this clue's lost count splits the two (times-5839 24A)",
      [("The talk of the town", {"5"}), ("Bury fat", {"9"})],
      [(c["text"], c["enums"]) for c in _got[1:3]])

sys.exit(1 if fails else 0)
