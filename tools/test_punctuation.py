#!/usr/bin/env python3
# Does tools/punctuation.py find the marks no clue's print breaks ("by.clever",
# "''" for a double quote, ",.", "word , word") and mend only the certain ones,
# moving the clue's italics and annotation offsets with them? And do the OCR
# write gate (puzzle_integrity.check_new_punctuation), the write path's mend
# (fetch_puzzle.write_puzzle_file), edition_commit.strayed, corrects() and the
# vote (ocr_clues.agree / relay_doubt) use it?
#
#     python3 tools/test_punctuation.py
#
# Cases are clues the corpus held: book-17028 6A "Caught by.clever message",
# times-15602 1A "Author of "Crown and Roundhead''", times-15564 22D "over.a
# plant", times-13680 1D "Diffidence,. to Giant Despair". Pure functions and a
# temp file: no scan, no OCR.
import copy
import json
import pathlib
import sys
import tempfile

TOOLS = pathlib.Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import punctuation as p
import puzzle_integrity as pi
import edition_commit
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


rules = lambda t: [why for why, _ in p.faults(t)]
# Each rule fires.
check("a stop glued to a word", ["a stop glued to the next word"], rules("Caught by.clever message"))
check("a stop glued to 'a'", ["a stop glued to the next word"], rules("Airmen take one over.a plant"))
check("a stop glued to a capital", ["a stop glued to the next word"], rules("Big cat girl found in.Carroll's garden"))
check("two apostrophes", ["two apostrophes for a double quote"], rules('Author of "Crown and Roundhead\'\''))
check("comma then stop", ["two marks in a row"], rules("Diffidence,. to Giant Despair"))
check("semicolon then comma", ["two marks in a row"], rules("Cross between dog and mink in Sweden;, say"))
check("a word's stop then comma", ["two marks in a row"], rules("Good shot., Monsieur Noah"))
check("space before a comma", ["a space before a comma"], rules("Gaping , mouth heartily taking pate"))
# What the print sets itself does not.
for t in ["Warning issued from slur.com?", "Hon. member, e.g. Ph.D", "Shells etc., and more",
          "Despicable sort...., this", "Is the baker at work or not ?", "Note : this ; that !",
          "John Cage's 4'33\" piece", "A.B.C. here", "Lost on purpose, by talking,...", "See 4"]:
    check(f"no fault in {t!r}", [], rules(t))

# Certain mends; the rest stand.
for was, want in [("Caught by.clever message", "Caught by clever message"),
                  ("Airmen take one over.a plant", "Airmen take one over a plant"),
                  ("Weapons.kept up one's sleeve?", "Weapons kept up one's sleeve?"),
                  ("Shells etc.require money", "Shells etc. require money"),
                  ('Author of "Crown and Roundhead\'\'', 'Author of "Crown and Roundhead"'),
                  ("''Master Spy'' is in colour", '"Master Spy" is in colour'),
                  ("Welshman''s stand", "Welshman's stand"),
                  ("Diffidence,. to Giant Despair", "Diffidence, to Giant Despair"),
                  ("In the Middle East,.it makes", "In the Middle East, it makes"),
                  ("Made up song,, got tea", "Made up song, got tea"),
                  ("Good shot., Monsieur Noah", "Good shot, Monsieur Noah"),
                  # Not certain: left for a re-read.
                  ("Wiped floor wi.h woollen fabric", "Wiped floor wi.h woollen fabric"),
                  ("Big cat girl found in.Carroll's garden", "Big cat girl found in.Carroll's garden"),
                  # A "''" paired with a single "'" (book-28026 1A, book-28043 5D, book-27022 17D).
                  ("Symphony—from 'The Planets''?", "Symphony—from 'The Planets'?"),
                  ("The chief character in '*A Lady's Love''", "The chief character in '*A Lady's Love'"),
                  ("Being content, say: ''fits are violent'", "Being content, say: 'fits are violent'"),
                  ("Vulgar precis of Garbo's ''I want to be alone'", "Vulgar precis of Garbo's 'I want to be alone'"),
                  ("Rivals ''All about Eve'', ''Numberless Mines Explode'", 'Rivals "All about Eve", \'Numberless Mines Explode\''),
                  # A capital after a glued stop (times-17259 1A, times-15668 2D, times-20642 16D).
                  ("a native of.Scotland", "a native of Scotland"),
                  ("Forever.Amber?", "Forever Amber?"),
                  ("unlike Mr.Quiverful", "unlike Mr. Quiverful"),
                  # Not certain: left for a re-read.
                  ("Safe spaces arranged ''coz of monster'", "Safe spaces arranged ''coz of monster'"),
                  ("the boys' ''toy'", "the boys' ''toy'"),
                  ("located in Ursa.Minor?", "located in Ursa.Minor?"),
                  ("Mature Indo.European heard", "Mature Indo.European heard"),
                  ("In retrospect.America 5", "In retrospect.America 5"),
                  ("Stop.Then go", "Stop.Then go"),
                  ("Sweden;, say", "Sweden;, say"),
                  ("Store.,gruel", "Store.,gruel"),
                  ("Gaping , mouth", "Gaping , mouth")]:
    check(f"mend {was!r}", want, p.mended(was))

# mend_entry moves italics and the annotation with the text.
e = {"number": 6, "direction": "across",
     "clue": {"text": "Caught by.clever ''message'' here", "italics": [{"at": 19, "length": 7}]},
     "annotation": {"definitions": [{"at": 19, "length": 7, "text": "message"}], "explanation": "by.clever"}}
check("mend_entry changes it", True, p.mend_entry(e))
check("mend_entry text", 'Caught by clever "message" here', e["clue"]["text"])
check("mend_entry italics follow", [{"at": 18, "length": 7}], e["clue"]["italics"])
check("mend_entry definition offset follows", 18, e["annotation"]["definitions"][0]["at"])
check("definition still names its words", "message", e["clue"]["text"][18:25])
check("annotation prose mended too", "by clever", e["annotation"]["explanation"])


# The write gate: OCR channels, changed clue text only.
def puzzle(channel, text):
    return {"id": "times-1", "source": {"retrievedFrom": channel},
            "entries": [{"number": 1, "direction": "across", "clue": {"text": text}}]}


def gated(old, new):
    flags = []
    pi.check_new_punctuation(old, new, flags)
    return [f[0] for f in flags]


check("a new OCR clue with a fault is refused", ["SHAPE"], gated(None, puzzle("newspaper", "Sweden;, say")))
check("a book clue too", ["SHAPE"], gated(None, puzzle("book", "Gaping , mouth")))
check("a held clue as it was stands", [], gated(puzzle("newspaper", "Sweden;, say"), puzzle("newspaper", "Sweden;, say")))
check("a publisher's clue is not gated", [], gated(None, puzzle("publisher", "Sweden;, say")))
check("a clean OCR clue passes", [], gated(None, puzzle("newspaper", "Sweden, say")))

# strayed() makes a held file with a fault due; mend_puzzle mends it in place.
held = puzzle("newspaper", "Caught by.clever message")
check("strayed flags a fault", {"1-across"}, edition_commit.strayed(held))
check("not with spaces=False (the held path mends it)", set(), edition_commit.strayed(held, spaces=False))
check("mend_puzzle reports the light", {"1-across": "Caught by clever message"}, p.mend_puzzle(copy.deepcopy(held)))
# A mend that leaves its clue one the gate refuses as new is not made: the held words pass as they are, and the
# write that merges answers into the file stands (10-25: times-18300 "one . , owner", times-17709 "·at ... time;,").
for was in ("Composure of the number one . , owner", "Anxious about, ·at one time;, King Edward"):
    half = puzzle("newspaper", was)
    check(f"mend_puzzle leaves {was!r} as held", ({}, was), (p.mend_puzzle(half), half["entries"][0]["clue"]["text"]))
check("gate_refuses a clue the gate would", (True, False, True),
      (p.gate_refuses({"text": "one , owner"}), p.gate_refuses({"text": "one, owner"}), p.gate_refuses({"text": "a  b"})))
import fetch_puzzle
fp_old = puzzle("newspaper", "Gaping , mouth heartily  taking pate")
fp_new = puzzle("newspaper", "Gaping , mouth heartily taking pate")
check("a held clue the writer kept, that the write's mends turned into one the gate refuses, goes back as held",
      "Gaping , mouth heartily  taking pate",
      fetch_puzzle.kept_held_clues(fp_old, fp_new, {(1, "across"): "Gaping , mouth heartily  taking pate"})["entries"][0]["clue"]["text"])
check("... a clue the writer brought new is the gate's to judge",
      {}, fetch_puzzle.kept_clues(puzzle("newspaper", "Sweden;, say"), puzzle("newspaper", "Sweden, say;,")))

# corrects() takes a certain mend, and no reading that brings a fault.
check("corrects takes the mend", True, fa.corrects("Caught by.clever message", "Caught by clever message"))
check("corrects takes the quote mend", True, fa.corrects('Author of "Crown and Roundhead\'\'', 'Author of "Crown and Roundhead"'))
check("corrects refuses a reading with a fault", False, fa.corrects("Frontier cantonment", "A Frontier cantonment;,"))

# The vote's relay doubts a print with a fault the laid clue lacks.
check("relay_doubt names a new fault", "a punctuation fault the laid clue lacks",
      oc.relay_doubt("Sweden, say", "Sweden;, say", "Sweden;, say", {"sweden": 3, "say": 3}))

# Specks a reader made that the 16-18 Oct 2026 "Update times-" rereads cut:
# a middle dot, a stop alone between words, the stop after a lone "a", and
# ".." at a clue's end or start (dashes.py leaves ".." mid-clue alone).
for what, text, want in (
        ("a middle dot between words", "Broadcasts most of · Aida in specified amounts", "Broadcasts most of Aida in specified amounts"),
        ("a middle dot closing up a word", "Clerical establishment where young· servant goes around firing",
         "Clerical establishment where young servant goes around firing"),
        ("a middle dot before a mark", "Sacked for a kiss to the editor·?", "Sacked for a kiss to the editor?"),
        ("a stop alone between words", "Fodder for the right variety of grey . donkey", "Fodder for the right variety of grey donkey"),
        ("the stop after a lone a", "Fighter thrown in jail for a. short stretch", "Fighter thrown in jail for a short stretch"),
        ("initials keep their stops", "Mutant battles L.A. in The Gastropod Killer", "Mutant battles L.A. in The Gastropod Killer"),
        ("a trailer's two stops", "Eccentric applies rum to testicle, ..", "Eccentric applies rum to testicle, …"),
        ("a leader's two stops", ".. through Cornish town reportedly instead", "… through Cornish town reportedly instead"),
        ("two stops mid-clue stand", "Verse delivered in church office .. ahead of time", "Verse delivered in church office .. ahead of time"),
        ("three stops are dashes.py's", "Dead soon ... heading for tomb", "Dead soon ... heading for tomb")):
    check(f"mended: {what}", want, p.mended(text))

# The write path mends an OCR clue before the gate; a publisher's stands.
import fetch_puzzle
BOOK = REPO / "puzzles/book/1984/book-32002.json"
with tempfile.TemporaryDirectory() as d:
    for gen, want in [("tools/acquire_book.py", "Caught by clever message"),
                      ("tools/fetch_puzzle.py", "Caught by.clever message")]:
        pz = json.loads(BOOK.read_text())
        pz["entries"][0]["clue"] = {**pz["entries"][0]["clue"], "text": "Caught by.clever message"}
        pz["entries"][0].pop("annotation", None)
        path = pathlib.Path(d) / "book-32002.json"
        # Held as the corpus has it: its own unmended clue (23A) stands.
        path.write_text(BOOK.read_text())
        try:
            fetch_puzzle.write_puzzle_file(path, pz, generator=gen)
            got = json.loads(path.read_text())["entries"][0]["clue"]["text"]
        except Exception as err:  # broad on purpose: the reason is the finding
            got = f"{type(err).__name__}: {err}"[:200]
        check(f"write path via {gen}", want, got)

print(f"{fails} failures")
sys.exit(1 if fails else 0)
