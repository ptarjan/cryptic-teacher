#!/bin/bash
# Does tools/punctuation.py find the marks no clue's print breaks ("by.clever",
# "''" for a double quote, ",.", "word , word") and mend only the certain ones,
# moving the clue's italics and annotation offsets with them? And do the OCR
# write gate (puzzle_integrity.check_new_punctuation), the write path's mend
# (fetch_puzzle.write_puzzle_file), edition_commit.strayed, corrects() and the
# vote (ocr_clues.agree / relay_doubt) use it?
#
#     bash tools/test_punctuation.sh
#
# Cases are clues the corpus held: book-17028 6A "Caught by.clever message",
# times-15602 1A "Author of "Crown and Roundhead''", times-15564 22D "over.a
# plant", times-13680 1D "Diffidence,. to Giant Despair". Pure functions and a
# temp file: no scan, no OCR.
set -uo pipefail
cd "$(dirname "$0")"

out=$(python3 - <<'EOF'
import copy, json, tempfile, pathlib
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
                  ("Vulgar precis of Garbo's ''I want to be alone'", "Vulgar precis of Garbo's ''I want to be alone'"),
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

# corrects() takes a certain mend, and no reading that brings a fault.
check("corrects takes the mend", True, fa.corrects("Caught by.clever message", "Caught by clever message"))
check("corrects takes the quote mend", True, fa.corrects('Author of "Crown and Roundhead\'\'', 'Author of "Crown and Roundhead"'))
check("corrects refuses a reading with a fault", False, fa.corrects("Frontier cantonment", "A Frontier cantonment;,"))

# The vote's relay doubts a print with a fault the laid clue lacks.
check("relay_doubt names a new fault", "a punctuation fault the laid clue lacks",
      oc.relay_doubt("Sweden, say", "Sweden;, say", "Sweden;, say", {"sweden": 3, "say": 3}))

# The write path mends an OCR clue before the gate; a publisher's stands.
import fetch_puzzle
with tempfile.TemporaryDirectory() as d:
    for gen, want in [("tools/acquire_book.py", "Caught by clever message"),
                      ("tools/fetch_puzzle.py", "Caught by.clever message")]:
        pz = json.load(open("../puzzles/book/1984/book-32002.json"))
        pz["entries"][0]["clue"] = {**pz["entries"][0]["clue"], "text": "Caught by.clever message"}
        pz["entries"][0].pop("annotation", None)
        path = pathlib.Path(d) / "book-32002.json"
        # Held as the corpus has it: its own unmended clue (23A) stands.
        path.write_text(open("../puzzles/book/1984/book-32002.json").read())
        try:
            fetch_puzzle.write_puzzle_file(path, pz, generator=gen)
            got = json.loads(path.read_text())["entries"][0]["clue"]["text"]
        except Exception as err:  # noqa: BLE001 -- the reason is the finding
            got = f"{type(err).__name__}: {err}"[:200]
        check(f"write path via {gen}", want, got)

print(f"{fails} failures")
EOF
)
echo "$out"
echo "$out" | grep '^0 failures$' >/dev/null
