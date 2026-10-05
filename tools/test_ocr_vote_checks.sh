#!/bin/bash
# Does the clue vote (tools/ocr_clues.py) file each word, count, capital and
# hyphen as the readings print them, and settle a word the readings all
# misread differently on the one known word their slips point to?
#
#     bash tools/test_ocr_vote_checks.sh
#
# Each case is a scan clue the filer once filed wrong or blank:
#   times-16752 2D "that's shoddy (5-4)" filed "thar's shoddy (9)";
#   times-16994 14D "Involve ..." filed "involve ...";
#   times-20988 25A "when it re-forms" filed "reforms".
# Pure functions on the readers' words: no scan, no OCR, no VLM.
set -uo pipefail
cd "$(dirname "$0")"

out=$(python3 - <<'EOF'
import ocr_clues as oc
import file_archive_org_puzzles as fa

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

# The lexicon ranks a word with "'s" as the word: "that's" is common.
check("rank of that's is that's", oc.rank("that"), oc.rank("that's"))

# times-16752 2D: four readings, four spellings, one of them a rare word.
streams = [["#", "Many", "a", "jalopy", "has", "an", "accessory", "foal's", "shoddy", "#"],
           ["drinks", "Many", "a", "jalopy", "has", "an", "accessory", "tbar's", "shoddy", "#"],
           ["#", "Pouring", "Many", "a", "jalopy", "two", "accessory", "scholars", "shoddy", "#"],
           ["#", "Many", "a", "jalopy", "has", "an", "accessory", "that's", "shoddy", "#"]]
check("a tie of votes goes to the known word the readings' slips point to, not a rare one",
      "Many a jalopy has an accessory that's shoddy",
      oc.agree("Many a jalopy has an accessory thar's shoddy", streams)[0])

# times-16994 14D: the reading laid lost the clue's capital; most others have it.
streams = [["#", "involve", "in", "charge", "#"], ["#", "Involve", "in", "charge", "#"],
           ["#", "Involve", "in", "charge", "#"], ["#", "Involve", "in", "charge", "#"]]
check("a word takes the case most readings print it in, a capital at the clue's start",
      "Involve in charge", oc.agree("lnvolve in charge", streams)[0])
check("mirror: no reading's capital, none put in",
      "involve in charge", oc.agree("involve in charge", [["#", "involve", "in", "charge", "#"]] * 2)[0])

# The count: the shape most readings print that fills the light.
check("a count lost to the light's length takes the readings' (5-4)",
      ("5-4", None), oc.printed_count("9", [{"5-4"}, set(), {"5-4"}], 9))
check("a hyphen one reading keeps beats a count one reading lost",
      ("5-4", None), oc.printed_count("9", [{"9"}, {"5-4"}], 9))
check("mirror: a count no reading parts stays whole",
      ("9", None), oc.printed_count("9", [{"9"}, {"9"}], 9))
check("a count that does not fill the light is no reading's vote",
      ("9", None), oc.printed_count("9", [{"5-3"}, {"9"}], 9))
check("two shapes no reading settles are no count",
      None, oc.printed_count("9", [{"5,4"}, {"4-5"}], 9)[0])
check("the laid count stands among the readings' tied shapes",
      ("5,4", None), oc.printed_count("5,4", [{"5,4"}, {"5-4"}], 9))

# The words: hyphens, capitals and spellings as the readings print them.
theirs = ["Ice does, when it re-forms - see?", "Ice does, wher1 it re-forrms - see!",
          "Ice does, when if re-forms - see!", "Ice does. when it reforms - see!"]
check("two words most readings hyphen are hyphened (times-20988 25A)",
      "Ice does, when it re-forms - see!", oc.printed_words("Ice does, when it reforms - see!", theirs))
check("mirror: a hyphen no reading prints is taken out where most join the word",
      "Ice does, when it reforms - see!",
      oc.printed_words("Ice does, when it re-forms - see!", ["Ice does, when it reforms - see!"] * 3))
check("a word split at a line end, the hyphen read as a mark, is joined (times-14583 19D)",
      "Mike Valon whom Wordsworth loved and left",
      oc.printed_words("Mike Valon whom Words worth loved and left",
                       ["Mhe Valon whcm Words, worth loved and left", "Mke Valon whom Words: worth loved and left",
                        "Mike Valon whom Wordsworth loved and left"]))
check("mirror: two words a reading prints apart stay apart",
      "Put in to land", oc.printed_words("Put in to land", ["Put into land", "Put in to land"]))
check("a clue's first word takes the capital a reading printed",
      "Involve in charge", oc.printed_words("involve in charge", ["Involve in charge", "involve in charge"]))
check("a non-word takes the known word most readings have there",
      "Shape of Western woodland",
      oc.printed_words("Shape of Westcrn woodland", ["Shape of Western woodland"] * 2 + ["Shape of Wcstern woodland"]))
check("mirror: a known word is not respelt by a known word the readings have",
      "Defeat the tight end", oc.printed_words("Defeat the tight end", ["Defeat the right end"] * 3))

texts = {"djvu": "ACROSS\n1 Many a jalopy has an accessory - foal's shoddy (5-4)\nDOWN\n2 Pet (3)",
         "en5": "ACROSS\n1 Many a jalopy has an accessory that's shoddy\nDOWN\n2 Pet (3)",
         "vlm": "ACROSS\n1 Many a jalopy has an accessory that's shoddy (5-4)\nDOWN\n2 Pet (3)"}
laid, blank = oc.as_printed(texts, {"1-across": ("Many a jalopy has an accessory that's shoddy", "9", None)}, {},
                            fa.parse, {"1-across": 9})
check("as_printed: the filed clue takes the count the readings print", ("5-4", {}),
      (laid["1-across"][1], blank))

# The lexicon's consensus: the one known word every reading's slips point to.
check("slips: two likely slips cost one change", 1.0, oc.slips("that's", "tbar's"))
check("consensus: three misreadings of one word", "another", oc.consensus(["anoibcr", "anotacr", "auotber"]))
check("consensus: the known word nearest every reading", "launderette",
      oc.consensus(["laundcrette", "launderette", "laundorette", "laundrette"]))
check("consensus: readings that agree give way to a word one slip off", "city", oc.consensus(["Ciry", "Ciry"]))
check("mirror: readings that agree keep a name more than a slip off", None, oc.consensus(["Jenkyns", "Jenkyns"]))
check("mirror: a short word has too many neighbours to settle", None, oc.consensus(["Sbc", "She", "Sbe"]))
check("an apostrophe two readers lost is the print's", "chef's", oc.consensus(["chefs", "chefs", "chef's", "chef's"]))
check("mirror: a tie the slips cannot break settles nothing", None, oc.consensus(["stud", "studs", "studs", "stud"]))
check("mirror: a name most readings share is not respelt as a known word (times-13957 2D)",
      None, oc.consensus(["Jaoucs", "Jaques", "Jaques", "Jaques"]))
check("mirror: nor a name three readings print (times-13957 20A)",
      None, oc.consensus(["Jcirkios", "Jorkins", "Jorkins", "Jorkins"]))
check("mirror: a reader's capital inside the clue is not voted in (times-19116 17D)",
      "Panic follows tricky situation in chess",
      oc.printed_words("Panic follows tricky situation in chess",
                       ["Panic follows tricky situation In dress", "Panic follows tricky situation In chess"]))
check("a word misread three ways settles on the one known word (times-14804 8D)", "that",
      oc.consensus(["thai", "that", "thar"]))
check("mirror: the clue's own word is not replaced by a longer one (times-20382 13D)",
      None, oc.consensus(["son", "lesson", "iesson", "son", "lesson"]))
check("mirror: a word as rare as the vote's pick does not unsettle it (times-20286 29A)",
      "English flier joins", oc.agree("English lier joins", [["#", "English", "flier", "joins"], ["#", "English", "Dier", "joins"]])[0])
check("mirror: words every reading runs together stay apart without a mark between (times-13678 16A)",
      "but not for a man", oc.printed_words("but not for a man", ["but not fora man"] * 3))
check("mirror: one reading alone settles nothing", None, oc.consensus(["auotber"]))

print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_ocr_vote_checks: failed"; exit 1; }
echo "test_ocr_vote_checks: all passed"
