#!/bin/bash
# Does the clue vote (tools/ocr_clues.py) file each word, count, capital and
# hyphen as the readings print them, and settle a word the readings all
# misread differently on the one known word their slips point to?
#
#     bash tools/test_ocr_vote_checks.sh
#
# Each case is a scan clue the filer filed wrong or blank:
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
texts = {"en5": "ACROSS\n1 What Cleopatra did to the en-\nclosed reptile? (7)\nDOWN\n2 Pet (3)",
         "vlm": "ACROSS\n1 What Cleopatra did to the en-\nclosed reptile? (7)\nDOWN\n2 Pet (3)"}
laid, _ = oc.as_printed(texts, {"1-across": ("What Cleopatra did to the enclosed reptile?", "7", None)}, {},
                        fa.parse, {"1-across": 7})
check("as_printed: a line end's hyphen is not put in (times-19158 7D)",
      "What Cleopatra did to the enclosed reptile?", laid["1-across"][0])
texts = {k: t.replace("Cleopatra did to the en-", "Ride a horse-").replace("closed reptile", "race")
         for k, t in texts.items()}
laid, _ = oc.as_printed(texts, {"1-across": ("Ride a horse-race?", "7", None)}, {}, fa.parse, {"1-across": 7})
check("mirror: nor taken out of a compound a line end breaks", "Ride a horse-race?", laid["1-across"][0])
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
check("mirror: a word the lexicon lacks that the readings nearly agree on stays theirs (times-14794 1A)",
      None, oc.consensus(["camoeUbus", "camcelious", "camceljous", "cameelious", "cancellious"]))
check("mirror: a formed word most readings share stands (times-14583 12A)",
      None, oc.consensus(["unscared", "unscared", "uncared"]))
check("mirror: one reading alone settles nothing", None, oc.consensus(["auotber"]))

# A clue's start is lost when half the other readings see words before it,
# or two see the same ones; specks a few of many readings each see apart
# (the scan's and a reprint's readings voting together) lose nothing.
clean_ = lambda t: oc.marked(oc.clean(t), breaks=True)
plain = clean_("12 This man gets sat on (4) 13 X")
specks = [clean_("12 ry This man gets sat on (4) 13 X"), clean_("12 i This man gets sat on (4) 13 X")]
check("two readings' different specks among seven lose no start",
      "This man gets sat on", oc.agree("This man gets sat on", specks + [plain] * 5)[0])
check("two readings' different words among three lose the start (mirror)",
      None, oc.agree("This man gets sat on", specks + [plain])[0])
check("two readings' same words among seven lose the start (mirror)",
      None, oc.agree("This man gets sat on", [clean_("12 Long goad This man gets sat on (4) 13 X")] * 2 + [plain] * 5)[0])

# A clue the vote left blank is laid again from a reading that printed it
# whole, when that reading's count fills the light and the rest agree; a
# reading whose count does not fill the light, or that the rest do not
# bear out, lays nothing.
lists = lambda one: f"ACROSS\n1 {one}\n5 Hill (4).\nDOWN\n2 Ore (3).\n"
texts = {"djvu": lists("rifle Mary (5)."), "ch": lists("Lamb, I'd rifle Mary (5)."),
         "en5": lists("Lamb, I'd rifle Mary (5)."), "canberra:7:ocr": lists("Lamb, I'd rifle Mary (5).")}
lengths = {"1-across": 5, "5-across": 4, "2-down": 3}
laid = {"1-across": ("", "5", None), "5-across": ("Hill", "4", None), "2-down": ("Ore", "3", None)}
got, blank = oc.relaid(texts, laid, {"1-across": "starts mid-clue"}, fa.parse, lengths)
check("a blank clue laid again from a reading that printed it whole", ("Lamb, I'd rifle Mary", "5", {}),
      (got["1-across"][0], got["1-across"][1], blank))
got, blank = oc.relaid(texts, laid, {"1-across": "starts mid-clue"}, fa.parse, {**lengths, "1-across": 6})
check("a reading whose count does not fill the light lays nothing (mirror)", ("", ["1-across"]),
      (got["1-across"][0], sorted(blank)))
one_copy = {**{k: t for k, t in texts.items() if not k.startswith("canberra")}, "times": texts["ch"]}
got, blank = oc.relaid(one_copy, laid, {"1-across": "starts mid-clue"}, fa.parse, lengths)
check("one copy's readings alone lay nothing again (mirror)", ["1-across"], sorted(blank))
alone = {**texts, "ch": lists("Pigs might fly (5)."), "en5": lists("Cows can jump (5)."), "canberra:7:ocr": lists("Nothing here (5).")}
got, blank = oc.relaid(alone, laid, {"1-across": "starts mid-clue"}, fa.parse, lengths)
check("a reading the rest do not bear out lays nothing (mirror)", ["1-across"], sorted(blank))

# A word half the vote put in beside the whole word is a line-end split one
# copy made and another did not; a pair the clue itself prints stands.
check("a split half put in beside its word is named",
      [("bur", "burlesque"), ("plodding", "ding")],
      oc.split_added("Point to Marlowe's burlesque, plodding on", "Point to Marlowe's bur burlesque, plodding ding on"))
check("a pair the clue prints itself is not (mirror)", [], oc.split_added("Lost in India", "Lost in India"))

# A doubled word, a reading's line start voted in again and a stray letter
# are no print's (times-15684 13A "round t the heart"); each is mended from
# a reading without it, or the clue goes blank: never filed.
kinds = lambda t: [why for _, why in oc.stray(t)]
check("a word doubled", ["a word doubled"], kinds("Study the money of country country"))
check("a pair English doubles is not (mirror)", [], kinds("Last in in the river"))
check("a pair with a mark between is not (mirror)", [], kinds("Hear, hear - deal in canvas"))
check("an earlier word repeated inside the clue", ["an earlier word repeated inside the clue"],
      kinds("Plan is to Plan destroy"))
check("a repeat that reads as a phrase is not (mirror)", [], kinds("The art of The Times rush-hour commuter?"))
check("a repeat after a sentence's end is not (mirror)", [], kinds("Jack and Dora wrong? Jack might be"))
check("a stray letter inside the clue", ["a stray letter"], kinds("Ill temper visible round t the heart of Naples"))
check("a stray letter at the end", ["a stray letter"], kinds("Turned up as new t"))
check("the article, I, O and capitals are not (mirror)", [],
      kinds("A man in S Africa, O what I see is a X"))
check("a letter the clue names, e.g., 'e and v are not (mirror)", [],
      kinds("Spells sorcerers with a c, e g at 'e black v white"))
check("suspect() refuses a stray clue", True, bool(oc.suspect("Turned up as new t")))
check("a stray letter is taken out where a reading lacks it",
      "Ill temper visible round the heart of Naples",
      oc.unstrayed("Ill temper visible round t the heart of Naples",
                   ["Ill temper visible round the heart of Naples", "Ill temper visible round t the heart of Naples"]))
check("a doubled word is taken out where a reading prints it once", "Plan is to destroy",
      oc.unstrayed("Plan is to Plan destroy", ["Plan is to destroy"]))
check("a small letter a reading prints as a capital takes it", "Decoration for Brand X",
      oc.unstrayed("Decoration for Brand x", ["Decoration for Brand X"]))
check("with no reading that lacks it, the flag stands (mirror)", "Turned up as new t",
      oc.unstrayed("Turned up as new t", ["Turned up as new t", "Turned np as new t"]))
# A lone underscore touching a word is a speck read as one (times-17246's
# "love,_emperor", 280 held clues off scans): read without it, flagged where
# held so the edition is read again; a run of them, or one between spaces,
# may be the print's blank and stands.
check("a speck read as an underscore is read as nothing, or the space it stood in",
      ["Demanding love, emperor leads the country", "Male watch found during a short day", "Magic judge of beauty",
       "Out of prison fine"],
      [oc.clean(t) for t in ("Demanding love,_emperor leads the country", "Male watch found during_a short day",
                             "Magic judge _of beauty", "Out of prison fine_")])
check("a held one is a stray, and unstrayed takes the mark out, not the word",
      (["a speck read as an underscore"], "Demanding love, emperor leads the country"),
      (kinds("Demanding love,_emperor leads the country"), oc.unstrayed("Demanding love,_emperor leads the country", [])))
check("(mirror) a printed blank stands: a run, or one between spaces, at the clue's end too", [[], [], []],
      [kinds(t) for t in ("Freedom and _____ gang thegither", "And with no _ but a cry", "The cock's shrill _")])
check("and clean() keeps them", "And with no _ but a cry", oc.clean("And with no _ but a cry"))
two = lambda one: f"ACROSS\n1 {one} (5).\nDOWN\n2 Ore (3).\n"
lens = {"1-across": 5, "2-down": 3}
got, blank = fa.unfit_blanked(*oc.as_printed({"a": two("Turned up as new t"), "b": two("Turned up as new")},
                                             {"1-across": ("Turned up as new t", "5", None), "2-down": ("Ore", "3", None)},
                                             {}, fa.parse, lens), lens)
check("the vote files the clue a reading prints without the letter", ("Turned up as new", {}),
      (got["1-across"][0], blank))
got, blank = fa.unfit_blanked(*oc.as_printed({"a": two("Turned up as new t"), "b": two("Turned up as new t")},
                                             {"1-across": ("Turned up as new t", "5", None), "2-down": ("Ore", "3", None)},
                                             {}, fa.parse, lens), lens)
check("the vote files it blank when every reading has the letter (mirror)", ("", ["1-across"]),
      (got["1-across"][0], sorted(blank)))

# A held file's stray clue takes the new reading's, or goes blank, and the
# write path lets it go blank.
import json, tempfile
from pathlib import Path
import puzzle_integrity as pi
def held_file(text):
    return {"id": "times-1", "dimensions": {"cols": 5, "rows": 3},
            "source": {"acquiredBy": fa.TOOL, "retrievedFrom": "ocr"},
            "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0}, "length": 5,
                         "clue": {"text": text}},
                        {"number": 2, "direction": "down", "position": {"x": 2, "y": 0}, "length": 3,
                         "clue": {"text": "Ore (3)"}}]}
path = Path(tempfile.mkdtemp()) / "times-1.json"
path.write_text(json.dumps(held_file("Turned up as new t (5)")))
check("a held stray clue takes the reading's", {"1-across": "Turned up as new (5)"},
      (fa.mend_held(held_file("Turned up as new (5)"), path) or (None, None))[1])
check("a held stray clue with no clean reading goes blank", {"1-across": ""},
      (fa.mend_held(held_file(""), path) or (None, None))[1])
path.write_text(json.dumps(held_file("Turned up as new (5)")))
check("a held clean clue is left alone (mirror)", None, fa.mend_held(held_file(""), path))
import provenance
old = held_file("Turned up as new t (5)")
old["source"]["retrievedFrom"] = sorted(provenance.OCR_CHANNELS)[0]
flags = []
pi.check_rewrite(old, held_file(""), flags)
check("the write path lets a stray clue go blank", [], [x for x in flags if "1-across" in x[2]])
old["entries"][0]["clue"]["text"] = "Turned up as new (5)"
flags = []
pi.check_rewrite(old, held_file(""), flags)
check("and refuses blanking a clean one (mirror)", 1, len([x for x in flags if "1-across" in x[2]]))

# Gale's No 15 and No 9 (1930s Listener pages, uncounted lists): a reading
# that lost a clue still aligns it somewhere, and its words there are
# another clue's: no vote on this one's ends or words.
mark = lambda t: oc.marked(oc.clean(t), breaks=True)
check("a reading that lost a one-word clue says nothing of its end",
      "Stop.", oc.agree("Stop.", [mark("24 Stop. 25 A dugout."),
                                   mark("32 sad story was written in galliambics. 33 Squares"),
                                   mark("18 A storm cloud (German), 19 A script")])[0])
check("readings that print the clue with words after it still find its end lost (mirror)",
      None, oc.agree("Stop.", [mark("24 Stop. 25 A dugout."), mark("24 Stop the press. 25 A"),
                                mark("24 Stop it now. 25 A")])[0])
check("a figure run onto a word's start where a reading sees nothing is a speck",
      "A technical uncle of the B.B.C.",
      oc.agree("A technical 1uncle of the B.B.C.", [mark("29 A technical I uncle of the B.B.C. 30 And"),
                                                    mark("29 A technical uncle of the B.B.C. 30 And"),
                                                    mark("32 written in galliambics. 33 Squares of their body.")])[0])
check("a figure every reading sees as a number stays (mirror)", "Map 10 East",
      oc.agree("Map 10 East", [mark("3 Map 10 East 4 A"), mark("3 Map 10 East 4 A")])[0])
check("words another reading ran together count as its",
      "She eats junkets.", oc.agree("She eats junkets.", [mark("4 She eatsjunkets. 5 A"),
                                                          mark("2 called this enamelled 3 the name")])[0])
check("words this reading ran together that another prints apart are parted",
      "A starch from the roots of the plant.", oc.agree("A starch from the roots of theplant.",
                                                       [mark("36 A starch from the roots of the plant. 37 Your")])[0])
check("a stop run between two words another reading prints apart: a speck after a word",
      "An antidote to poison.", oc.agree("An antidote to.poison.", [mark("2 An antidote to poison. 3 An")])[0])
check("and an abbreviation's after no word", "Anag. of a lovely word",
      oc.agree("Anag.of a lovely word", [mark("7 Anag. of a lovely word 8 The")])[0])
check("a dictionary word another reading split stays whole (mirror)",
      "Somewhere to go.", oc.agree("Somewhere to go.", [mark("4 Some where to go. 5 A"), mark("4 Somewhere to go. 5 A")])[0])
check("a word no reading prints apart is still lost (mirror)",
      None, oc.agree("She eats junkets.", [mark("4 She junkets. 5 A"), mark("4 She junkets. 5 A")])[0])

print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_ocr_vote_checks: failed"; exit 1; }
echo "test_ocr_vote_checks: all passed"
