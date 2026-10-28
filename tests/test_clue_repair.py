#!/usr/bin/env python3
# Does tools/clue_repair.py give a clue whose bracket its own reading lost
# the count another reading prints, in its parts, so the scan filers file
# "3,6,5" and not the bare letter total "14"?
#
#     python3 tests/test_clue_repair.py
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

# A linked head's later number is its own, never a clue the list lost (Gale 1954-06-19): another reading's
# "1, 9 But are there" reads its 9 before words, and split_lost cut clue 9 out of the head, leaving it no words.
_head = {"tokens": [{1}, {9}], "text": "But are there talking pictures in the gallery ?", "enums": {"8,8"}, "see": None}
_got, _ = clue_repair.repair({"across": [dict(_head), {"tokens": [{10}], "text": "One isn't sent there to peep",
                                                      "enums": {"8"}, "see": None}], "down": []},
                             "1, 9 But are there talking pictures in the gallery ? (8, 8). 10 One isn't sent there to peep (8).")
check("a linked head keeps its later number and its words (no clue 9 split off it)",
      [([1, 9], "But are there talking pictures in the gallery ?", {"8,8"}), ([10], "One isn't sent there to peep", {"8"})],
      [([n for t in c["tokens"] for n in t], c["text"], c["enums"]) for c in _got["across"]])

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
        # Rules learned from the Update commits of 17-22 Oct 2026 (tools/learn_postproc.py).
        ("a stroke stuck to a word's front", "Education initially by _the three Rs contains no fault", "9",
         "Education initially by the three Rs contains no fault"),
        ("a stroke stuck to a word's end", "Like an_ uneasy, lying head victim of a strike?", "8",
         "Like an uneasy, lying head victim of a strike?"),
        ("a figure for a speck before to", "On Naxos her song appears 2to end in reverse", "5",
         "On Naxos her song appears to end in reverse"),
        ("a figure for a speck before on", "Decide to change denims, with lipstick 0on?", "7",
         "Decide to change denims, with lipstick on?"),
        ("a figure for a speck before the opening I", "1I work in gallery to stimulate interest", "7",
         "I work in gallery to stimulate interest"),
        ("the count with a 1 glued on both sides", "That classical island language 151.", "5",
         "That classical island language"),
        ("the count with a 1 glued in front, three figures", "Each movement causes pain 141", "4",
         "Each movement causes pain"),
        ("a stub of the next word", "Run up loose dress as a tem temporary measure", "9",
         "Run up loose dress as a temporary measure"),
        ("a stub that is a word", "Go to town on the toothpaste", "9", "Go to town on the toothpaste"),
        ("a stub that is foreign", "A pas de deux", "7", "A pas de deux"),
        # What is left alone.
        ("blank letters", "C_A_C_?", "5", "C_A_C_?"),
        ("a blank letter after a capital", "Look grumpy? P_ off!", "5", "Look grumpy? P_ off!"),
        ("a run of underscores is a blank", "Craftiness that is ____ I rate as misrepresentation", "5",
         "Craftiness that is ____ I rate as misrepresentation"),
        ("a unit after a figure", "Moved tile 1mm — it fixed window", "5", "Moved tile 1mm — it fixed window"),
        ("a direction after a figure", "Agricultural power and 1down", "5", "Agricultural power and 1down"),
        ("a number the clue is about", "Painter, back, ran into 007", "7", "Painter, back, ran into 007"),
        ("a two-figure count with a 1 and no light list", "Mum not seen to follow 15", "5",
         "Mum not seen to follow 15"),
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

# A two-figure count with a 1 glued on ("robbing 81" for 8) is cut only when no
# light of the puzzle has that number: "follow 15" may be a reference to 15 across.
for what, text, enum, lights, want in (
        ("a speck, no light of that number", "One caught in the actual act of robbing 81", "8", {1, 2, 3, 22},
         "One caught in the actual act of robbing"),
        ("a speck, a light of that number", "Mum not seen to follow 15", "5", {1, 2, 15, 22},
         "Mum not seen to follow 15"),
        ("a speck, no light list", "One caught in the actual act of robbing 81", "8", None,
         "One caught in the actual act of robbing 81")):
    check(f"mend_text lights: {what}", want, clue_repair.mend_text(text, enum, lights=lights))

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

_is_word, _uses = clue_repair.lexicon()
for _was, _now in [("to be de rigueur", "to be de rigueur"), ("Train to le a", "Train to le a"),
                   ("ready for th summer", "ready for th summer"), ("known th in Scotland's", "known th in Scotland's"),
                   ("used tu be returned", "used tu be returned"), ("living al fresco, with", "living al fresco, with"),
                   ("Popular da ce -music", "Popular da ce -music"), ("motorist haled roughly", "motorist haled roughly"),
                   ("hes. tation", "hes. tation"), ("contra… dicting man's", "contra… dicting man's"),
                   ("cottage provid ing a", "cottage providing a"), ("fuel con tainers", "fuel containers"),
                   ("abandon de pressed profession?", "abandon depressed profession?"),
                   ("reluctant liarist", "reluctant diarist")]:
    check("mend_words on %r" % _was, _now, clue_repair.mend_words(_was, _is_word, _uses))
for _was, _now in [("D Day, camouflage?", "D Day, camouflage?"), ("1 Down's poet?", "1 Down's poet?"),
                   ("S Sound judgment", "Sound judgment"), ("I Long pair of shorts?", "Long pair of shorts?")]:
    check("lead_speck on %r" % _was, _now, clue_repair.lead_speck(_was, _is_word, _uses))
# A scan's "a" read as "&" (times-12467 FREELANCE: "by & weapon", reread "by & a weapon");
# a name's or a list's "&" is print.
for _was, _now in [("Lone wolf unimpeded by & a weapon", "Lone wolf unimpeded by a weapon"),
                   ("Israelite encampment is & mile up", "Israelite encampment is a mile up"),
                   ("For tendency to get worked up, & a moist lemon concoction-about one",
                    "For tendency to get worked up, a moist lemon concoction-about one"),
                   ("Something B & B could be?", "Something B & B could be?"),
                   ("Severe wound identified in A & E", "Severe wound identified in A & E"),
                   ("Mirage of old distracted Lilliputians & co", "Mirage of old distracted Lilliputians & co"),
                   ("Boatman & crew: visionaries", "Boatman & crew: visionaries"),
                   ("Agreed book & play need first half discarded", "Agreed book & play need first half discarded"),
                   ("I stick around & look the other way", "I stick around & look the other way"),
                   ("Destroyed padre's name almost & character", "Destroyed padre's name almost & character"),
                   ("in Calvin Klein briefs & a Rolex?!", "in Calvin Klein briefs & a Rolex?!"),
                   ("Giant comic used in a fish & chip shop", "Giant comic used in a fish & chip shop"),
                   ("He was an & one in the. 27, 3", "He was an & one in the. 27, 3"),
                   ("& & & & & &", "& & & & & &")]:
    check("stray_ampersand on %r" % _was, _now, clue_text.stray_ampersand(_was, _uses))
check("stray_ampersand without a corpus is a no-op", "Lone wolf unimpeded by & a weapon",
      clue_text.stray_ampersand("Lone wolf unimpeded by & a weapon"))
check("mend_text drops the & before a", "Lone wolf unimpeded by a weapon",
      clue_repair.mend_text("Lone wolf unimpeded by & a weapon", "9"))

sys.exit(1 if fails else 0)
