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
check("halves most readings print apart round a dash keep the dash (Azed scan)",
      "Hid in - cosmetician's case", oc.printed_words("Hid in-cosmetician's case",
                                                      ["Hid in - cosmetician's case"] * 3 + ["Hid in-cosmetician's case"]))
check("mirror: a hyphen more readings print than a dash stays a hyphen",
      "Ice does, when it re-forms - see!", oc.printed_words("Ice does, when it re-forms - see!",
                                                          ["Ice does, when it re-forms - see!"] * 2 + ["Ice does, when it re - forms - see!"]))
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

# No 2's 7D: a mark alone after the clue's last word sees no words there,
# so one reading running on into the next clue ("privilege. . A bleaching
# vat.", 8D's number lost) and one reading a comma lose no end; two
# readings with different words there do (mirror).
plain = clean_("7 Most scientists can exercise this privilege. 8 X")
comma = clean_("7 Most scientists can exercise this privilege, 8 X")
runon = clean_("7 Most scientists can exercise this privilege. . A bleaching vat. 9 X")
check("a comma and one run-on reading among three lose no end",
      "Most scientists can exercise this privilege.",
      oc.agree("Most scientists can exercise this privilege.", [comma, plain, runon])[0])
other = clean_("7 Most scientists can exercise this privilege. . A dyeing tub. 9 X")
check("two readings' different words among three lose the end (mirror)",
      None, oc.agree("Most scientists can exercise this privilege.", [comma, other, runon])[0])

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
check("an apostrophe read for an i is suspect (No 97 6D)", [("r'ddled", "an apostrophe for a letter")],
      oc.suspect("He r'ddled very prettily."))
check("a poet's elision, a contraction, a dialect word stand (mirror)", [],
      oc.suspect("Wand'ring heav'n o'er I'll it's we'll Em'ly Rob'n"))
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
check("a rare word another reading prints as two common ones is parted",
      "Ireland for a hill.", oc.agree("Ireland fora hill.", [mark("27 Ireland for a hill. 28 An")])[0])
check("a whole clue this reading ran together that another prints apart is parted",
      "Painted brown restaurant red instead of half rose",
      oc.parted("Paintedbrownrestaurantredinsteadofhalfrose",
                [mark("12 Painted brown restaurant red instead of half rose 13 A")]))
check("and over a word with an apostrophe", "Fruit's counterpart in bottles",
      oc.parted("Fruit'scounterpartinbottles", [mark("4 Fruit's counterpart in bottles 5 A")]))
check("a run-together no reading prints apart stays as read (mirror)", "Paintedbrown restaurant",
      oc.parted("Paintedbrown restaurant", [mark("12 Painted crown restaurant 13 A")]))
check("three words run together with a letter misread part as another reading prints them (No 4 21D)",
      "irritating feature of England's nationai game",
      oc.parted("irritating featureofEngland'snationai game", [mark("21 irritating feature of England's national game 26 A")]))
check("two words run together with a letter misread stay (mirror)", "an irritating featureofEngland",
      oc.parted("an irritating featureofEngland", [mark("21 an irritating featurc ofEngland 26 A")]))
glued = ["some", "consider", "this", "an", "irritating", "featureofengland'snationai", "game"]
at = [(i, i) for i in range(6)] + [(6, None)]
check("a reading prints a clue whose run-together word holds its word (No 4 21D)", True,
      oc.prints(at, glued, ["Some", "consider", "this", "an", "irritating", "feature", "of", "national", "game"]))
check("not where the run-together word holds none of it (mirror)", False,
      oc.prints(at, glued, ["Some", "consider", "this", "an", "irritating", "fit", "of", "national", "game"]))
check("a short word one reading has and the other dropped stands when the corpus prints it there (No 1880)",
      "Come to see me", oc.agree("Come to see me", [mark("6 Come see me 7 A")])[0])
check("not where the corpus prints its neighbours together as often (mirror)",
      (None, "no other reading has 'a'"), oc.agree("Sit in a car now", [mark("6 Sit in car now 7 A")]))
check("a dictionary word another reading split stays whole (mirror)",
      "Somewhere to go.", oc.agree("Somewhere to go.", [mark("4 Some where to go. 5 A"), mark("4 Somewhere to go. 5 A")])[0])
check("a dictionary word a reading broke over a line end stays whole",
      "Vain display with a severe hairstyle",
      oc.parted("Vain display with a severe hairstyle", [["Vain", "display", "with", "a", "severe", "hair", "Style"]]))
check("a non-word two readings print alike and none otherwise is the print's (No 17's misprint)",
      "the roots of the plant elecampeae.",
      oc.agree("the roots of the plant elecampeae.", [mark("36 the roots of the plant elecampeae. 37 Your")])[0])
check("but not when a reading spells it otherwise (mirror)", None,
      oc.agree("the roots of the plant elecampeae.", [mark("36 the roots of the plant elecampeae. 37 Your"),
                                                    mark("36 the roots of the plant elecampcac. 37 Your")])[0])
check("asPrinted: the non-word two readings hold, and a bracket none closes",
      (["elecampeae."], ["(from"]),
      (oc.printed_alike("the plant elecampeae.", ["the plant elecampeae.", "the plant elecampeae", None]),
       oc.printed_alike("Expressive slang (from Hollywood meaning", ["Expressive slang (from Hollywood meaning",
                                                                   "slang (from Hollywood", ""])))
check("asPrinted: one reading alone, or a bracket another reading closes, is none (mirror)",
      ([], []),
      (oc.printed_alike("the plant elecampeae.", ["the plant elecampeae.", "the plant elecampane."]),
       oc.printed_alike("slang (from Hollywood", ["slang (from Hollywood", "slang (from Hollywood)"])))
check("a token asPrinted keeps is no suspect, nor bled; others still are",
      ([], None, [("anatomatical", "not a word")], True),
      (oc.suspect("slang (from Hollywood elecampeae", printed=["(from", "elecampeae"]),
       oc.bled("slang (from Hollywood", ["(from"]), oc.suspect("An anatomatical term", printed=["(from"]),
       oc.bled("slang (from Hollywood") is not None))
check("an abbreviation's stop before a small word stands; a sentence's is a comma",
      "Anag. of a lovely word, then 20 rev. and", oc.clean("Anag. of a lovely word. then 20 rev. and"))
check("a bracket opening on a word gets its space back; a plural's (s) keeps none",
      "Expressive slang (from Hollywood, word(s)", oc.clean("Expressive slang(from Hollywood, word(s)"))
check("a quotation never closed: its end lost; an elision, a closed one, a plural's apostrophe are not",
      [0, 20, None, None, None, 31, None, None, None],
      [oc.unclosed_quote(t) for t in ("'Resting weary limbs at last on beds of", "A printer might say,'Give me a",
                                      "*'One shade the more, one ray the less'.", "'Tis true",
                                      "In the soldiers' tea", "And the-is heard above the lyre'.", "rock 'n' roll",
                                      "Hindustani for 'that much'.", "Hindustani for\u2018red'.")])
starling = "Anag. of the first syllable of a starling."
check("a dictionary word three readings print alike stands against a commoner slip (No 17 43A)",
      starling, oc.agree(starling, [mark("43 " + starling + " 44 The")] * 2)[0])
check("but a reading that dissents, or two readings alone, leave it to the corpus (mirror)",
      [starling.replace("starling", "starting")] * 2,
      [oc.agree(starling, [mark("43 " + starling + " 44 The"),
                           mark("43 " + starling.replace("starling", "starting") + " 44 The")])[0],
       oc.agree(starling, [mark("43 " + starling + " 44 The")])[0]])
check("but a two-letter word every reading shares still yields to its commoner slip (mirror)",
      "it does us a power of good.", oc.agree("it does us a power ot good.", [mark("13 it does us a power ot good. 14 The")] * 2)[0])
tea = "in the soldiers'tea for this purpose."
check("an apostrophe glued between two words another reading parts stays a possessive (No 15 39A)",
      "in the soldiers' tea for this purpose.",
      oc.agree(tea, [mark("39 in the soldiers' tea for this purpose. 40 The"),
                     mark("39 in the soldiers tea for this purpose. 40 The")])[0])
check("or opens a quotation; a known contraction stays whole (mirror)",
      ["A printer might say 'Give me", "they're here"],
      [oc.parted("A printer might say'Give me", [["A", "printer", "might", "say", "Give", "me"]]),
       oc.parted("they're here", [["they", "re", "here"]])])
check("a word no reading prints apart is still lost (mirror)",
      None, oc.agree("She eats junkets.", [mark("4 She junkets. 5 A"), mark("4 She junkets. 5 A")])[0])


# A printed blank ("——"): a thin rule, often fainter than the type, that no
# reader reads alike (No 15 30A "the-is", " - ", "—"; 23D and No 17 26A
# "——'" alone, which no reader returns at all).
from PIL import Image, ImageDraw
H = 20
def page(*draw):
    img = Image.new("L", (900, 200), 255)
    d = ImageDraw.Draw(img)
    for f in draw:
        f(d)
    return img
def words(d, y, *spans):
    for x0, x1 in spans:
        d.rectangle((x0, y, x1, y + H), fill=0)
LINE = (100, 40, 700, 60)
rule = lambda x0, x1, y, ink=150, t=1: (lambda d: d.rectangle((x0, y, x1, y + t), fill=ink))
SPANS = ((100, 160), (175, 230), (300, 360), (520, 700))
text = lambda d: words(d, 40, *SPANS)
WORDS = [(x0, 40, x1, 60, "word") for x0, x1 in SPANS]
check("a faint rule between words is a blank; one alone under a line, a quote after it, is \"——'\"",
      [(250, 50, 280, 52, "——"), (120, 75, 170, 77, "——'")],
      oc.blank_strokes(page(text, rule(250, 279, 50), rule(120, 169, 75, ink=60),
                            lambda d: d.rectangle((174, 68, 176, 73), fill=0)), [LINE], WORDS, H))
colon = lambda d: (d.rectangle((380, 44, 382, 46), fill=0), d.rectangle((380, 56, 382, 58), fill=0))
check("a hyphen, a rule run into a word or after a colon, an underline, a long rule and "
      "a grid's bar are none (mirror)", [],
      oc.blank_strokes(page(text, rule(236, 245, 50), rule(231, 262, 50), colon, rule(386, 415, 50),
                            rule(300, 360, 62), rule(100, 700, 120),
                            rule(400, 430, 160), lambda d: d.rectangle((395, 140, 396, 190), fill=0),
                            lambda d: d.rectangle((435, 140, 436, 190), fill=0)),
                       [LINE, (395, 150, 440, 175)], WORDS + [(395, 150, 440, 175, "grid")], H))
# No 4 9D "'——and here's": a two-em rule after an opening quote, run into
# the next word, under a box a reader stretched over it from the line above.
quote_mark = lambda d: d.rectangle((395, 42, 397, 47), fill=0)
letters = lambda x: (lambda d: [d.rectangle((x + k, 44, x + k, 58), fill=0) for k in range(0, 31, 6)])
run_in = lambda d: (d.rectangle((400, 50, 442, 52), fill=0), letters(443)(d))
check("a two-em rule run into the word after it, an opening quote above, is a blank (No 4 9D)",
      [(400, 50, 444, 53, "'——")],
      oc.blank_strokes(page(text, quote_mark, run_in), [LINE], WORDS + [(390, 10, 450, 52, "England.")], H))
check("with no quote before it, no quote is put in (mirror)", [(400, 50, 444, 53, "——")],
      oc.blank_strokes(page(text, run_in), [LINE], WORDS, H))
check("a one-em dash run into a word is none (mirror)", [],
      oc.blank_strokes(page(text, lambda d: (d.rectangle((400, 50, 422, 52), fill=0), letters(423)(d))),
                       [LINE], WORDS, H))
blank = (1202, 603, 1227, 605, "——")
readings = {"ch": [(1080, 588, 1473, 617, "And the-is heard above the")],
            "en5": [(1080, 588, 1473, 617, "And the - is heard above the")],
            "times": [(1156, 594, 1188, 611, "the"), (1202, 602, 1227, 605, "—"), (1246, 600, 1260, 610, "is")],
            "page": [(1156, 594, 1188, 611, "the"), (1246, 600, 1260, 610, "is")]}
check("each reading gets the blank where it stands, so the vote is unanimous (No 15 30A)",
      ["And the —— is heard above the", "And the —— is heard above the", "——", "——"],
      [oc.with_blanks(readings["ch"], [blank])[0][4], oc.with_blanks(readings["en5"], [blank])[0][4],
       oc.with_blanks(readings["times"], [blank])[1][4], oc.with_blanks(readings["page"], [blank])[2][4]])
check("a hyphen elsewhere in the line stays (mirror)", "Green-land and the —— is heard",
      oc.with_blanks([(1080, 588, 1473, 617, "Green-land and the-is heard")], [(1300, 603, 1325, 605, "——")])[0][4])
check("a quotation the vote kept shut but not open takes the mark a reading opens it with",
      "'And the —— is heard above the lyre'.",
      oc.reopened("And the —— is heard above the lyre'.", ["And the —— is heard above the lyre'.",
                                                           "\u2018And the —— is heard above the lyre\u2019."]))
check("none when no reading opens it, or it opens on another word (mirror)", [None, None],
      [oc.reopened("And the —— is heard above the lyre'.", ["And the —— is heard above the lyre'."]),
       oc.reopened("And the —— is heard above the lyre'.", ["'The —— is heard above the lyre'."])])
check("No 103: a stop left alone before the first word is an elided start, opened there",
      "rev. '. . . is a monster of so frightful mien'.",
      oc.reopened("rev. . is a monster of so frightful mien'.", ["rev. is a monster of so frightful mien'."]))
check("no stop before it, or one ending a word: nothing put back (mirror)", [None, None],
      [oc.reopened("rev. is a monster of so frightful mien'.", ["rev. is a monster of so frightful mien'."]),
       oc.reopened("A. B. is a monster of so frightful mien'.", [])])
death = "This word might be put into the mouth of Death."
check("No 10 41A: a quote a whole sentence opens and never closes, a reading prints bare, is a speck",
      death, oc.unquoted_speck("'" + death, ["'" + death, death]))
check("a quotation closed, its end lost, or opened in every reading keeps its quote (mirror)", [None, None, None],
      [oc.unquoted_speck("'The highest string of the violin'.", ["The highest string of the violin'."]),
       oc.unquoted_speck("'Resting weary limbs at last on beds of", ["Resting weary limbs at last on beds of"]),
       oc.unquoted_speck("'" + death, ["'" + death, "‘" + death])])
check("a quotation parted from the comma before it, and a dash after a colon spaced",
      ["A printer might say, 'Give me a", "Charade: — components I postpone."],
      [oc.clean("A printer might say,'Give me a"), oc.clean("Charade: -components I postpone.")])
check("a comma glued to a capitalised word is spaced (No 97 33D \"knot,I'm\")",
      "They'd cut the Gordian knot, I'm sure.", oc.clean("They'd cut the Gordian knot,I'm sure."))
check("an initialism's comma stays (mirror)", "U.S.,UK", oc.clean("U.S.,UK"))
check("a colon after a lone capital is spaced (No 4 12D \"Add a T:an island\")",
      "Add a T: an island in a river.", oc.clean("Add a T:an island in a river."))
check("a colon between capitals stays (mirror)", "An A:B ratio.", oc.clean("An A:B ratio."))
check("a hyphen within a word stays (mirror)", "A well-known man, I'd say.", oc.clean("A well-known man, I'd say."))

check("an opening quote glued to the word before opens the next (No 9 14A)",
      "Milton called this 'enamelled'.", oc.clean("Milton called this‘enamelled'."))
check("a name's quote after one capital stays put (mirror)", "O'Brien", oc.clean("O‘Brien"))
check("a ligature is its two letters (No 9 6D \"mediæval\")", "A mediaeval weapon.", oc.clean("A mediæval weapon."))
check("a ligature read apart still votes (No 9 6D)", ({"6-down": ("A medieval weapon.", None, None)}, {}),
      oc.reconcile({"6-down": ("A medieval weapon.", None, None)},
                   ["5. His first. 6. A mediæval weapon. 8. Peaty soil."], {}, uncounted=True))
check("most readings' non-word against a slip that is no word is as printed (No 9 31D)",
      ("Five-sevenths of a spongecake.", "as printed"),
      oc.agree("Five-sevenths of a spongecake.", [["five", "-", "sevenths", "of", "a", "spongecake", "."],
                                                   ["ive", "sevenths", "of", "a", "spongecalke", "."]]))
check("closed-up known words, not any non-word: elecampeae is no compound (mirror)",
      (True, False), (oc.closed_compound("spongecake"), oc.closed_compound("elecampeae")))
check("a reading that prints known words there still wins (mirror)", "Five-sevenths of a sponge cake.",
      oc.agree("Five-sevenths of a spongecake.", [["five", "-", "sevenths", "of", "a", "spongecake", "."],
                                                   ["five", "sevenths", "of", "a", "sponge", "cake", "."]])[0])

NO_103 = "42. This belongs to a wonderful 25.\n43. Wrote the 19.\nDOWN\n21. Medium.\n23. Wonderful 25.\n26. This way."
check("a short clue is put to the text after its own number, not another clue's (No 103 23D)",
      ({"23-down": ("Wonderful 25.", None, None)}, {}),
      oc.reconcile({"23-down": ("Wonderful 25.", None, None)}, [NO_103, NO_103], {}, uncounted=True))
LOST = "42. This belongs to a wonderful 25.\n23. Most wonderful 25.\n26. This way."
check("an opening the readings print after the number is still put back (mirror)",
      ({"23-down": ("Most wonderful 25.", None, None)}, {}),
      oc.reconcile({"23-down": ("Wonderful 25.", None, None)}, [LOST, LOST], {}, uncounted=True))

check("a double quote opening an elision is a single misread (No 97 46A)",
      "His poser guessed by means unfair, 'Tis said this hero lost his hair.",
      oc.paired('His poser guessed by means unfair, "Tis said this hero lost his hair.'))
check("a double quote a double closes stays, 'Tis inside it too (mirror)",
      'He said, "\'Tis I."', oc.paired('He said, "\'Tis I."'))
check("a double opening only a single closes was a single (No 103 18A)",
      "'That's a wonder . . .'s.", oc.paired('"That\'s a wonder . . .\'s.'))
check("a quote after a stop before a possessive s closes the quotation (No 103 18A)",
      None, oc.unclosed_quote("'That's a day longer than a wonder . . .'s."))
check("an apostrophe inside a word closes nothing (mirror)", 0, oc.unclosed_quote("'That's a day longer"))
check("an unclosed quotation takes back the closing one reading prints after its last words (No 103 18A)",
      "'That's a day longer than a wonder . . .'s.",
      oc.reclosed('"That\'s a day longer than a wonder. ..', ["", "a day longer than a wonder .. 's.\nake entitled"]))
check("no reading printing a closing there puts none back (mirror)", None,
      oc.reclosed('"That\'s a day longer than a wonder. ..', ["a day longer than a wonder.\n19. Cake"]))

# No 103 14D: two Tesseract readings print "tipper", two RapidOCR ones the
# printed "tripper". A tie split by engine goes to the engine whose slip
# the other spelling would take is far the likelier on the page.
fams = {"tipper": ["tesseract", "tesseract"], "tripper": ["rapidocr", "rapidocr"]}
seen = lambda lost, added, wrong=None: {"seen": 400, "wrong": wrong or lost + added, "lost": lost, "added": added}
check("an engine tie goes to the spelling whose letters the other engine lost (No 103 14D)",
      "tripper", oc.by_family(fams, {"tesseract": seen(4, 0), "rapidocr": seen(3, 0)}))
check("engines that slip alike leave the tie held (mirror)",
      None, oc.by_family(fams, {"tesseract": seen(1, 0), "rapidocr": seen(1, 1)}))
check("a tie inside one engine is no engine split (mirror)",
      None, oc.by_family({"tipper": ["tesseract", "rapidocr"], "tripper": ["rapidocr", "tesseract"]},
                         {"tesseract": seen(9, 0), "rapidocr": seen(0, 0)}))

# The same through reconcile: the page's other clues measure each engine,
# where one Tesseract reading ("page") drops a letter the other three keep.
import random
rng = random.Random(12)
pool = "the sign of this house wonder legend fidelity reverse ancient city noted language flower deity medium".split()
laid, page, rapid = {}, [], []
for n in range(1, 41):
    ws = [rng.choice(pool) for _ in range(6)]
    lost = [w[1:] if n % 3 == 0 and k == 2 else w for k, w in enumerate(ws)]
    laid[f"{n}-across"] = (" ".join(ws).capitalize() + ".", None, None)
    page.append(f"{n}. " + " ".join(lost).capitalize() + ".")
    rapid.append(f"{n}. " + " ".join(ws).capitalize() + ".")
def tie(page):
    lays = dict(laid) | {"41-across": ("A mark of the tipper.", None, None)}
    got, blank = oc.reconcile(lays, ["\n".join(page + ["41. A mark of the tipper."])]
                              + ["\n".join(rapid + ["41. A mark of the tripper."])] * 2,
                              uncounted=True, names=["page", "en5", "ch"], mine="times")
    return got["41-across"][0]
check("reconcile breaks an engine tie with the page's measured slips (No 103 14D)",
      "A mark of the tripper.", tie(page))
check("reconcile holds an engine tie when Tesseract lost no letters elsewhere (mirror)", "", tie(rapid))

# No 103: Tesseract ends clue after clue on a comma where RapidOCR prints the stop.
import archive_org_listener as al
lays_t = {f"{n}-down": (f"Clue number {n} here,", None, None) for n in range(1, 13)}
lays_r = {f"{n}-down": (f"Clue number {n} here.", None, None) for n in range(1, 13)}
check("an end comma one engine alone prints, often on the page, is its slip: the stop stands (No 103)",
      "Clue number 3 here.", al.end_stops(lays_t, [lays_t, lays_t, lays_r, lays_r], ["times", "page", "en5", "ch"])["3-down"][0])
# Mirror: RapidOCR ends four of the page's clues on a comma too, so a
# comma is no Tesseract slip there.
lays_v = {k: (t[:-1] + ",", e, g) if k in ("4-down", "6-down", "8-down", "10-down") else (t, e, g)
          for k, (t, e, g) in lays_r.items()}
check("an end comma both engines print on the page's other clues stands (mirror)",
      "Clue number 3 here,", al.end_stops(lays_w := lays_v | {"3-down": lays_t["3-down"]},
                                           [lays_w, lays_w, lays_v, lays_v], ["times", "page", "en5", "ch"])["3-down"][0])

# No 17 16D: "walls.from" is longer than any word of the clue, and parted()
# capped the words it joins at the clue's longest.
check("two words run together over a stop part when longer than any word (No 17 16D)",
      "*Used to preserve walls from damp.",
      oc.parted("*Used to preserve walls.from damp.", [["Used", "to", "preserve", "walls", "from", "damp"]]))
check("no reading printing the two words apart leaves them (mirror)",
      "*Used to preserve walls.from damp.",
      oc.parted("*Used to preserve walls.from damp.", [["Used", "to", "preserve", "wallsfrom", "damp"]]))

# No 9 6D: en5 alone prints the ligature, which ch and Tesseract read "e".
check("a word one reading prints with a ligature is filed as printed (No 9 6D)",
      "A mediæval weapon.", oc.ligatured("A medieval weapon.", ["A medieval weapon.", "A mediæval weapon."]))
check("no reading printing a ligature leaves the voted word (mirror)",
      "A medieval weapon.", oc.ligatured("A medieval weapon.", ["A medieval weapon.", "A mediaeval weapon."]))
check("a ligature word whose letters are a known word is no misread (No 9 6D)",
      [], oc.suspect("A mediæval weapon."))
check("a ligature in no known word is (mirror)", [("mædixval", "not a word")], oc.suspect("A mædixval weapon."))

# No 97 6D: a broken "i" read as an apostrophe by both RapidOCR readers.
check("an apostrophe one letter mends into a known word is that letter (No 97 6D)",
      "He riddled very prettily.", oc.letter_put_back("He r'ddled very prettily."))
check("a poet's elision and a contraction stay (mirror)",
      "The wand'ring heav'n you'll see.", oc.letter_put_back("The wand'ring heav'n you'll see."))

# No 103 9D: Tesseract lost "12. In" and ran 12D's line on after 9D's stop.
twelve = {"12-down": ("In legend wonderful test of fidelity.", None, None)}
check("a clue running on after its stop into another laid clue's words is cut there (No 103 9D)",
      "A pole was the sign of this house,",
      oc.run_on("A pole was the sign of this house, legend test of fidelity,", "9-down", twelve))
check("words after a stop that no other clue prints stay (mirror)",
      "A pole was the sign. Its house of fidelity.",
      oc.run_on("A pole was the sign. Its house of fidelity.", "9-down",
                {"12-down": ("Wonderful test of a mare.", None, None)}))

check("a tag other clues end on stays after the stop (mirror, No 17 38D)",
      "Wild or tipsy. Two letters missing.",
      oc.run_on("Wild or tipsy. Two letters missing.", "38-down",
                {"43-across": ("Anag. of the first syllable of a starling. *One letter missing.", None, None)}))
check("a few words another clue shares stay after the stop (mirror, No 103 41D)",
      "Half girl half hag, a wonder of the Nile.",
      oc.run_on("Half girl half hag, a wonder of the Nile.", "41-down",
                {"27-down": ("Not many wonders surpass the modern one here.", None, None)}))
# No 4 22A: two readings lost "23." and ran 22A on into 23A's words.
isles = [["perhaps", "the", "most", "english", "of", "islands"]]
check("a reading's end running on into another laid clue is no end lost (No 4 22A)", "The name of an eagle.",
      oc.agree("The name of an eagle.", [mark("22 The name of an eagle. Inglish of islands, 36 An"),
                                         mark("22 The name of an eagle. 23 Perhaps the most English of islands."),
                                         mark("22 The name of an eagle. English of islands O hnooWIK 27 An")],
               clues=isles)[0])
check("an end no other clue prints is lost (mirror)", None,
      oc.agree("The name of an eagle.", [mark("22 The name of an eagle. Inglish of islands, 36 An"),
                                         mark("22 The name of an eagle. 23 Perhaps the most English of islands."),
                                         mark("22 The name of an eagle. English of islands O hnooWIK 27 An")],
               clues=[["perhaps", "the", "most", "scottish", "of", "lochs"]])[0])
check("a lead closing on another clue's words is that clue's (No 4 23A)", (True, False),
      (oc.elsewhere_run(("the", "name", "of", "an"), "start", [["the", "name", "of", "an", "eagle"]]),
       oc.elsewhere_run(("of", "an"), "start", [["the", "name", "of", "an", "eagle"]])))
london = "'London's lasting shame, but nevertheless part of our history."
check("a quotation closing mid-clue that a reading prints is closed there (No 4 8A)",
      "'London's lasting shame,' but nevertheless part of our history.",
      oc.reclosed(london, ["8. 'London's lasting shame,' but\nnevertheless part of our history."]))
check("not where no reading closes it (mirror)", None,
      oc.reclosed(london, ["8. 'London's lasting shame, but\nnevertheless part of our history."]))
check("a quotation opening on a printed blank is closed by its end quote (No 4 9D)", None,
      oc.unclosed_quote("'—— and here's a marvellous convenient place for our rehearsal'."))
check("one whose end quote is lost is open (mirror)", 0,
      oc.unclosed_quote("'—— and here's a marvellous convenient place for our rehearsal."))
check("a non-word every reading prints alike stands (No 4 15D \"busie\")", "The drones from busie bee no could draw.",
      oc.agree("The drones from busie bee no could draw.",
               [mark("15 The drones from busie bee no could draw. 16 A")] * 3)[0])
check("one reading's non-word alone is mended (mirror)", True,
      oc.agree("The drones from busie bee no could draw.",
               [mark("15 The drones from busy bee no could draw. 16 A")] * 3)[0] != "The drones from busie bee no could draw.")
days = {"5-down": ("St. George's Day, 1918.", None, None), "11-down": ("St. George's Day, 1915.", None, None)}
check("words after a stop another clue prints with other figures stay (No 4 30A)",
      "St. George's Day, 1564.", oc.run_on("St. George's Day, 1564.", "30-across", days))
check("words after a stop another clue prints with the same figures are cut (mirror)",
      "On St.", oc.run_on("On St. George's Day, 1918.", "30-across", days))

print(f"FAILS {fails}")
EOF
)
echo "$out"
grep -q '^FAILS 0$' <<<"$out" || { echo "test_ocr_vote_checks: failed"; exit 1; }
echo "test_ocr_vote_checks: all passed"
