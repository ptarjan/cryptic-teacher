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

# No 3's 52D "A Frontier cantonment.": a reading that lost the clue votes
# on none of its words, so the letter the one printing reading shares stands,
# and the stop after it, which that reading lacks, goes as a speck;
# a letter most printing readings lack is a misread number (mirror).
ch = ["#", "A", "Frontier", "cantonment.", "#", "The", "King", "Emperor.", "#"]
lost = ["#", "A", "large", "number.", "#"]
check("an opening letter a printing reading shares stands, its lone stop goes", "A Frontier cantonment.",
      oc.agree("A. Frontier cantonment.", [ch, lost, lost])[0])
check("a stop after a lone letter is voted on like a comma", ["A", ".", "Conan", "Doyle", ",", "U", ".", "S", ".", "A"],
      oc.marked("A. Conan Doyle, U.S.A."))
check("an initial's stop every reading prints stands (mirror)", "A. Smith wrote it.",
      oc.agree("A. Smith wrote it.", [["#"] + oc.marked("A. Smith wrote it.") + ["#"]] * 2)[0])
check("an initial's stop one reading alone saw goes", "A Smith wrote it.",
      oc.agree("A. Smith wrote it.", [["#"] + oc.marked("A Smith wrote it.") + ["#"]] * 2)[0])
check("an opening letter most printing readings lack goes (mirror)", "Frontier cantonment.",
      oc.agree("A. Frontier cantonment.", [ch] + [["#", "Frontier", "cantonment.", "#"]] * 2 + [lost])[0])

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
check("a word one reading prints, the others garbles within reach of it, settles (NewsUK 1984-01-23)",
      "with", oc.consensus(["ujLh", "ujth", "with"]))
check("mirror: a word one reading prints settles nothing when another reading lies far from it (NewsUK 1975-09-29)",
      None, oc.consensus(["Nortuern", "North"]))

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
# A light no reading laid (times-15213 17D, the scan's own readings, no
# reprint): the scan's readers agreeing on its number, words and a count
# that fills it lay it; readings that do not agree still lay nothing.
downs = lambda one: f"ACROSS\n1 Hill (4).\nDOWN\n{one}\n19 European language could be French (6).\n"
own = {"djvu": downs("17 ( ran hard all over the place\nto get the old vixen IS)."),
       "ch": downs("17 ! ran hard all orer thc place\nto gct thc old vixen (8)."),
       "en5": downs("17 I ran hard all over the place\nto gct the old vixen (8)."),
       "times": downs("17 I ran hard all over the place\nto get the old vixen 8)"),
       "vlm": downs("17 I ran hard all over the place to get the old vixen (8).")}
lengths = {"1-across": 4, "17-down": 8, "19-down": 6}
laid = {"1-across": ("Hill", "4", None), "17-down": ("", None, None), "19-down": ("European language could be French", "6", None)}
why = {"17-down": "no reading laid a clue on it"}
got, blank = oc.relaid(own, laid, why, fa.parse, lengths, bare={"17-down"})
check("a light no reading laid takes the clue the scan's readers agree on",
      ("I ran hard all over the place to get the old vixen", "8", {}), (got["17-down"][0], got["17-down"][1], blank))
got, blank = oc.relaid(own, laid, why, fa.parse, lengths)
check("a light some reading laid still needs another copy (mirror)", ["17-down"], sorted(blank))
apart = {**own, "en5": downs("17 Pigs might fly (8)."), "times": downs("17 Cows can jump (8)."),
         "vlm": downs("17 Nothing here at all (8).")}
got, blank = oc.relaid(apart, laid, why, fa.parse, lengths, bare={"17-down"})
check("a light no reading laid takes nothing the readers do not agree on (mirror)", ["17-down"], sorted(blank))
# times-13821 2D: only the VLM and the Canberra reprint read it; two copies
# agreeing bear out a light no reading laid, two readings of one copy do not.
pair = {"vlm": downs("17 Appportion a good deal, we hear (8)."),
        "canberra:9:ocr": downs("17 Apportion a good deal, we hear (8)")}
got, blank = oc.relaid(pair, laid, why, fa.parse, lengths, bare={"17-down"})
check("the reprint alone bears out a light no reading laid", ("Apportion a good deal, we hear", {}),
      (got["17-down"][0], blank))
got, blank = oc.relaid({"vlm": pair["vlm"], "times": pair["canberra:9:ocr"]}, laid, why, fa.parse, lengths,
                       bare={"17-down"})
check("one other reading of the same copy does not (mirror)", ["17-down"], sorted(blank))
# 13821 24A: "singer." against the reprint's "singers" is a tie two
# readings cannot break, so the light stays blank.
tie = {"vlm": downs("17 It was about expectant singer. (8)."),
       "canberra:9:ocr": downs("17 It was about expectant singers (8)")}
got, blank = oc.relaid(tie, laid, why, fa.parse, lengths, bare={"17-down"})
check("two copies differing by a known word lay nothing (mirror)", ["17-down"], sorted(blank))

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
# A lone letter is a short word misread when the readings print one word
# between its neighbours, or their misreads of them (Times 1977 "He throws d
# sprightly", 1980 "said m go", 1981 "Restoration o the").
check("a stray letter takes the one word the readings print in its place",
      ["He throws a sprightly spanner in the works", "Typical signs said to go wrong on the airfield",
       "Restoration of the kidneys"],
      [oc.unstrayed("He throws d sprightly spanner in the works",
                    ["He dhrows d spirtghuly spanner", "He thirows a sprizhtly spauner", "He throws a sprightly spanner"]),
       oc.unstrayed("Typical signs said m go wrong on the airfield", ["Typical signs said to go wrong on the airfield"]),
       oc.unstrayed("Restoration o the kidneys", ["Resinration of the kiineys"])])
check("(mirror) readings printing two words there, or the letter itself, leave the flag",
      ["Where chopper descends n entrance to Hades?", "He should have no difficulty solving x and y"],
      [oc.unstrayed("Where chopper descends n entrance to Hades?",
                    ["Where chopper descends as entrance", "Where chopper descends at entramrce"]),
       oc.unstrayed("He should have no difficulty solving x and y", ["He should have no difficulty solving x and y"])])
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
check("a stop after a lone A before a lower-case word is a speck (No 3's 28D)",
      "A junction on the East Indian Railway.", oc.clean("A. junction on the East Indian Railway."))
check("an initial's stop, or one ending U.S.A., stands (mirror)",
      ["A. Conan Doyle", "the U.S.A. and"], [oc.clean("A. Conan Doyle"), oc.clean("the U.S.A. and")])
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
# times-13867: specks between words, read as a middle dot, a stop a space
# off the word, or after a real mark.
check("a middle-dot speck between words another reading prints apart is parted",
      "A bit of a step up", oc.agree("A bit of a\u00b7step up", [mark("29 A bit of a step up (5). 30")])[0])
check("a stop a space off the next word, after a capitalised word, is a speck",
      "The beggar whose fingers", oc.agree("The .beggar whose fingers", [mark("18 The beggar whose fingers 19")])[0])
check("a comma before a speck stays when another reading prints it",
      "It's a test, for him", oc.agree("It's a test,\u00b7for him", [mark("2 It's a test, for him (5). 3")])[0])
check("an abbreviation's stop stays though the abbreviation is a word",
      "Rev. of nothing", oc.agree("Rev.of nothing", [mark("2 Rev. of nothing (5). 3")])[0])
check("a speck between two words the corpus pairs is parted though no reading does",
      "Bits of the cake", oc.agree("Bits of.the cake", [mark("2 Bits of.the cake (5). 3")])[0])
check("a speck inside a misread word is no break (mirror)",
      "Snar.es", oc.parted("Snar.es", [mark("2 Snar.es (5). 3")]))
# A mark glued between two words (GLUED_MARK).
check("a double quote pairing nothing between small words is a speck",
      "Small creature to grow in body", oc.agree('Small creature to grow"in body', [mark("2 Small creature to grow in body (5). 3")])[0])
check("a double quote closing an opened one gets its space",
      'Meaning "voice" of course', oc.agree('Meaning "voice"of course', [mark("2 Meaning voice of course (5). 3")])[0])
check("a quote inside a non-word is no break (mirror)",
      'by the counte"foil', oc.parted('by the counte"foil', [mark("2 by the counte foil (5). 3")]))
check("a stop before a capital is a speck where a reading prints the words side by side",
      "Superficial judge of Shakespeare", oc.agree("Superficial judge of.Shakespeare", [mark("2 Superficial judge of Shakespeare (5). 3")])[0])
check("a stop before a capital after a word a sentence may end on stays (mirror)",
      "He left.Then", oc.parted("He left.Then", [mark("2 He left Then (5). 3")]))
check("a comma a reading prints gets its space",
      "Utter, a rival's name", oc.agree("Utter,a rival's name", [mark("2 Utter , a rival's name (5). 3")])[0])
check("a glued colon one reading prints is still a speck (mirror)",
      "You won't recover from a bad one", oc.agree("You won't recover from a:bad one",
                                                   [mark("# You won't recover from a : bad one #"), mark("# You won't recover from a bad one #")])[0])
check("hyphens run between two words are the dash",
      "riding up \u2014 least one", oc.agree("riding up---least one", [mark("2 riding up least one (5). 3")])[0])
check("hyphens run into a non-word stay (mirror)",
      "of Imprc--pianists", oc.parted("of Imprc--pianists", [mark("2 of Imprc pianists (5). 3")]))
check("a recogniser's ideograph one is the dash",
      "in chains \u2014 on the Bounty?", oc.agree("in chains \u4e00on the Bounty?", [mark("2 in chains on the Bounty ? (5). 3")])[0])
check("initials' possessive is printed, no stray mark", [], oc.suspect("The P.M.'s house"))
check("a dropped aitch is the setter's (times-21281 28A)", [],
      oc.suspect("'aving moved 'e 'astened 'ome 'ere? 'ow 'iggins at 'igher"))
check("an apostrophe before a word no aitch makes is still no word", [("'austic", "not a word")],
      oc.suspect("like 'austic soda"))
check("a stop then a hyphen after a word is a stray mark (times-13703 8D)",
      [("gear-housing.-", "a stray mark inside a word")], oc.suspect("Worn rubber gear-housing.- for a motorist"))
# times-13958 4D, times-13821 18D: a clue cut at a line wrap.
check("a lost end most readings print alike, misreads aside, goes in",
      ("greyhound", "track", "?"),
      oc.end_voted([("me", "nor"), ("greyhound", "track", "?"), ("greyhound", "track", "?")], 0, "end"))
check("a lost end the readings misread differently takes the one dictionary spelling",
      ("to", "bluebeard"),
      oc.end_voted([("to", "bluebeard"), ("to", "blucbeard"), ("to", "blucbeard")], 0, "end"))
check("no end is lost when this clue's last word holds it, run together (mirror)", None,
      oc.end_voted([("headed",), (",", "headed"), ("headed",)], 1, "end", ["them", "lighrheaded"]))
check("no end is lost when more readings print the clue with nothing there (mirror)", None,
      oc.end_voted([("headed",), ("headed",)], 2, "end", ["them", "light"]))
check("a short start is a misread number, not a lost word (mirror)", None,
      oc.end_voted([("is",), ("is",)], 0, "start", ["a", "word"]))
check("a short end is a misread count, not a lost word (mirror)", None,
      oc.end_voted([("si",), ("si",), ("si",)], 0, "end", ["notes"]))
check("an end that is the clue's own words again is misaligned, not lost (mirror)", None,
      oc.end_voted([("also", "foreign"), ("also", "foreign")], 0, "end", ["craft", "foreign"]))
check("an abbreviation's stop run into the next word is parted after its last letter",
      "E.g. sights and sounds", oc.agree("E.g.sights and sounds", [mark("3 E.g. sights and sounds (5) 4")])[0])
check("an end with no dictionary spelling stays lost (mirror)", None,
      oc.end_voted([("idiosyncracy",), ("idiosynericy",), ("idiosyncracy",)], 0, "end"))
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
# times-1978-10-02, times-1992-08-06: a word the readings print whole, filed in pieces.
check("a misread most readings print whole as a known word a letter off stays whole",
      "if reorgauized", oc.parted("if reorgauized", [mark("7 if reorganized 8 A"), mark("7 if reorganized 8 A"),
                                                     mark("9 Go re organ ized 10")]))
check("a run-together no word a letter off vouches is still parted (mirror)", "if the plant",
      oc.parted("if theplant", [mark("7 if theplant 8 A"), mark("7 if theplant 8 A"), mark("9 Go the plant 10")]))
check("a word's halves, once the next word is parted off, join as most readings print it",
      "imported originally by old",
      oc.agree("imported orig inallyby old", [mark("5 imported originally by old 6")] * 3)[0])
check("halves most readings print apart stay apart (mirror)", "imported orig inally by old",
      oc.agree("imported orig inallyby old", [mark("5 imported orig inally by old 6")] * 2
               + [mark("5 imported originally by old 6")])[0])
# times-1982-09-20, news-1974-11-01: a first letter read as a bracket the clue never closes.
check("a bracket the vote fills with the word's lost first letter goes",
      "Flat-bottomed boat from firm in Cornwall",
      oc.agree("Flat-bottomed boat from firm in (ornwall", [mark("5 Flat bottomed boat from firm in Cornwall 6 A")] * 3)[0])
check("a bracket the clue closes stays though the vote fills its word (mirror)",
      "and (this for protection)",
      oc.agree("and (his for protection)", [mark("5 and this for protection 6 A")] * 3)[0])
check("a bracket before a word the vote leaves stays (mirror)", "Fairly (slow movement",
      oc.agree("Fairly (slow movement", [mark("5 Fairly slow movement 6 A")] * 3)[0])
# news-1997-11-05, news-1977-12-24: a last letter read as a bracket the clue never opened.
check("a bracket the vote fills with the word's lost last letter goes",
      "Controller of vital beat who sets speed limits?",
      oc.agree("Controller of vita) beat who sets speed limits?",
               [mark("5 Controller of vital beat who sets speed limits ? 6 A")] * 3)[0])
check("a bracket the clue opened stays though the vote fills its word (mirror)",
      "Controller (of vital) beat",
      oc.agree("Controller (of vita) beat", [mark("5 Controller of vital beat 6 A")] * 3)[0])
check("a bracket after a word the vote leaves stays (mirror)", "olive grove) of",
      oc.agree("olive grove) of", [mark("5 olive grove of 6 A")] * 3)[0])
# news-1986-02-01, news-1981-02-05: a k's lost arm reads h; an h never reads k.
check("a k read as h is a confused letter", True, "king" in oc.confused("hing"))
check("an h is never a misread k (mirror)", False, "caneh" in oc.confused("canek"))
# news-1976-03-26, times-1987-04-10: a word broken at a line end, every reading broken.
check("halves that are no words across a mark join as the word they spell", "in nuclear physics",
      oc.join_split("in nuclear phy, sics", [mark("# in nuclear phy : sics #")] * 2))
check("halves across a dash join too", "to heavenly models",
      oc.join_split("to heav — enly models", [mark("# to heav — enly models #")] * 2))
check("two words across a comma stay apart (mirror)", "a dog, house",
      oc.join_split("a dog, house", [mark("# a dog, house #")] * 2))
# news-1974-06-19, news-1997-06-10: a corpus word no lexicon holds, one reading split.
check("a word the corpus knows stays whole though a reading split it", "embraced by St Ignatius",
      oc.parted("embraced by St Ignatius", [mark("# embraced by St Ignatius #"), mark("# cmbraced by St Ignat iuS #")]))
check("a misread the corpus does not know is parted as readings print it (mirror)", "embraced by St Ignat lus",
      oc.parted("embraced by St Ignatlus", [mark("# embraced by St Ignat lus #")] * 2))
check("a reading's split of a corpus word the clue prints is joined, no end lost", "greeting Italian composer",
      oc.agree("greeting Italian composer", [mark("# greeting Ital ian composer #")] * 2)[0])
check("de-, -ist and -ion for -or make known words", [True, True, True],
      [oc.formed(w) for w in ("decentralization", "collaborationist", "prestidigitation")])
check("a non-word with such an ending is none (mirror)", False, oc.formed("dexqztist"))
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
check("a word a reading broke is mended (No 4 2D, 4D, 26D, 11D)",
      ["An Englishman who", "the development of England", "This architectural", "St. George's Day, Mr. Smith"],
      [oc.clean(t) for t in ("An Engl ishman who", "the development ment of England", "T'his architectural",
                             "St.George's Day, Mr.Smith")])
check("two words, a common word ending the one before, a known elision and initials stand (mirror)",
      ["Engl and", "go nowhere here", "happiness ness", "O'er the hills, I'm", "The U.S.A. now"],
      [oc.clean(t) for t in ("Engl and", "go nowhere here", "happiness ness", "O'er the hills, I'm", "The U.S.A. now")])
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
# A rule touching the word before it too: "no——could".
ahead = lambda d: [d.rectangle((x, 44, x, 58), fill=0) for x in range(380, 399, 6)]
check("a two-em rule run into the words either side of it is a blank", [(400, 50, 444, 53, "——")],
      oc.blank_strokes(page(text, ahead, run_in), [LINE], WORDS, H))
check("a one-em dash run into the words either side of it is none (mirror)", [],
      oc.blank_strokes(page(text, ahead, lambda d: (d.rectangle((400, 50, 422, 52), fill=0), letters(423)(d))),
                       [LINE], WORDS, H))
# No 4 15D "bee no——" over "could draw.": a one-em rule run into the word
# before it, ending its line.
head = lambda d: words(d, 40, *SPANS[:2])
em = lambda d: d.rectangle((400, 50, 430, 52), fill=0)
check("a one-em rule run into the word before it, ending its line, is a blank (No 4 15D)",
      [[(400, 50, 431, 53, "——")]] * 2,
      [oc.blank_strokes(page(head, ahead, em), [(100, 40, 431, 60)], WORDS[:2] + box, H)
       for box in ([], [(380, 43, 431, 59, "no")])])
check("a rule through a word's middle is a mark on it, no blank (mirror)", [],
      oc.blank_strokes(page(head, ahead, em), [(100, 40, 431, 60)], WORDS[:2] + [(395, 43, 431, 59, "no")], H))
check("not where the line runs on after it, nor a hyphen ending its line (mirror)", [[], []],
      [oc.blank_strokes(page(head, ahead, em), [(100, 40, 700, 60)], WORDS[:2], H),
       oc.blank_strokes(page(head, ahead, lambda d: d.rectangle((400, 50, 412, 52), fill=0)),
                        [(100, 40, 413, 60)], WORDS[:2], H)])
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
check("a non-word every reading prints, a worn letter from a far commoner word, is that word (No 3 22D)",
      "Possible initials of a telegraph company.",
      oc.agree("Possible initials cf a telegraph company.",
               [mark("22 Possible initials cf a telegraph company. 23 A")] * 2)[0])
check("a worn letter is not put back where two words are about as common (mirror)", (None, None),
      (oc.worn("rcd"), oc.worn("tcn")))
check("two words run together over the quote opening the second are parted (No 3 44D)",
      ["#", "Hindustani", "for", "red", "#"], oc.unglued(mark("44 Hindustani for'red. 49"), ["hindustani", "for", "red"]))
check("a reading aligned on another laid clue's words lost this one: no vote (No 3 44D)", True,
      oc.another_clue(oc.align(["hindustani", "for", "red"], ["hindustani", "for", "cupboard"]), ["hindustani", "for", "red"],
                      ["Hindustani", "for", "cupboard"], [["hindustani", "for", "cupboard"]]))
check("a reading printing this clue's own words, the same as another's, still votes (mirror)", False,
      oc.another_clue(oc.align(["an", "exclamation"], ["an", "exclamation"]), ["an", "exclamation"],
                      ["An", "exclamation"], [["an", "exclamation"]]))
check("words run together over an apostrophe this clue prints stay one (mirror)", ["don't"],
      oc.unglued(["don't"], ["don't", "go"]))
check("a contraction is not parted into the stray letter another reading left (mirror, Canberra 14 July 1967 6D)",
      ["Rumour", "that's", "hardly"], oc.unglued(["Rumour", "that's", "hardly"], ["rumour", "that", "s", "hardly"]))

check("four words run together with one letter misread are parted (No 3 18D)",
      ["of", "the", "Moghul", "Empire", "foi", "many"],
      oc.unglued(["of", "theMoghulEmpirefoi", "many"], ["of", "the", "moghul", "empire", "fot", "many"]))
check("a token two letters from a run stays one (mirror)", ["theMoghulEmpirefxi"],
      oc.unglued(["theMoghulEmpirefxi"], ["the", "moghul", "empire", "fot"]))
check("a word another reading reads as a number pairs with it, the words after too (No 3 36A)",
      [(0, 1), (1, 2), (2, 3)], oc.align(["occurrence", "in", "india"], ["#", "occurrence", "#", "india", "#", "a"]))
check("a clue's last word is not paired with the next clue's number (mirror)",
      [(0, 1), (1, None)], oc.align(["occurrence", "india"], ["#", "occurrence", "#", "a"]))
check("No 3 36A, its 'in' read '111' by ch, agrees", "A not infrequent occurrence in India.",
      oc.agree("A not infrequent occurrence in India.", [mark("36 A not infrequent occurrence 111 India. 37 A town")])[0])

check("a word split at a kept line-end hyphen another reading has whole is joined (times-14057 23A)",
      "Suitable wear with a bowler?",
      oc.agree(oc.join_split("Suirable wear wtth a bow- Ier?", [["#", "Suitable", "wear", "with", "a", "bowler", "?", "#"],
                                                                ["Suitable", "wear", "with", "a", "bow", "ler", "?", "#"]]),
               [["#", "Suitable", "wear", "with", "a", "bowler", "?", "#"],
                ["Suitable", "wear", "with", "a", "bow", "ler", "?", "#"]])[0])
check("a word split at a speck read as a comma is joined (times-17868 18A)",
      "Letters to a girl in uniform giving directions?",
      oc.agree(oc.join_split("Letters to a girl in.uniform giy, ing directions?",
                             [["Letters", "to", "a", "girl", "in", "uniform", "giving", "directions", "?", "#"]]),
               [["Letters", "to", "a", "girl", "in", "uniform", "giving", "directions", "?", "#"]])[0])
check("two words with a comma between stay apart (mirror)", "Cats, dogs and mice",
      oc.join_split("Cats, dogs and mice", [["Cats", "catdogs", "and", "mice"]]))
check("pieces another reading has apart stay apart (mirror)", "a bow- Ier",
      oc.join_split("a bow- Ier", [["a", "bowler"], ["a", "bow", "ier"]]))
check("pieces two lexicon words could spell stay apart (mirror)", "a bow- Ier",
      oc.join_split("a bow- Ier", [["a", "bowler"], ["a", "bower"]]))
# times-14441 16D, 1976-08-04: a split one other reading shares, or two
# words, joins when most readings print the one word.
split = [["#", "as", "a", "post", "war", "Edwardian", "#"], ["#", "as", "a", "post", "war", "Edward", "ian", "#"],
         ["#", "as", "a", "post", "war", "Edwardian", "#"]]
check("a split another reading shares joins when more print the word whole", "as a post-war Edwardian",
      oc.agree(oc.join_split("as a post-war Edward, ian", split), split)[0])
split = [["Flight", "in", "disorderly", "speed"], ["Flight", "in", "dis", ",", "orderly", "speed"], ["Flight", "in", "disorderly", "speed"]]
check("two words a comma splits join when most readings print one", "Flight in disorderly speed",
      oc.agree(oc.join_split("Flight in dis, orderly speed", split), split)[0])
check("pieces as many readings have apart as whole stay apart (mirror)", "in dis, orderly",
      oc.join_split("in dis, orderly", [["in", "disorderly"], ["in", "dis", "orderly"]]))
check("two words one of three readings prints as one stay apart (mirror)", "in dis, orderly",
      oc.join_split("in dis, orderly", [["in", "disorderly"], ["in", "x"], ["in", "y"]]))
# Times 1977-09-19 "Rea dins of friend": halves a letter off the word most
# readings print whole join, and the vote then spells it.
split = [mark("# Reading uf fricnd abour certun tw rethre #"), mark("# Reading of fricnd about certun to retire #"),
         mark("# Reading of friend about certain to retire #")]
check("halves a letter off the word most readings print join", "Reading of friend about certain to retire",
      oc.agree(oc.join_split("Rea dins of friend about certain to retire", split), split)[0])
check("(mirror) two known words a letter off it, or halves most readings print apart, stay apart",
      ["the sea sun", "Rea dins of"],
      [oc.join_split("the sea sun", [["the", "season"]] * 2),
       oc.join_split("Rea dins of", [["Reading", "of"], ["Rea", "dins", "of"], ["Rea", "dins", "of"]])])

# Times 1976-03-25 "Put extinguisher on rapture?": the one printing reading
# splits the last word ("Tap : ture ?"), leaving its "?" past the clue's end.
lost = ["#", "Sign", "of", "a", "pastor", "turned", "innkeeper", "#"]
check("a clue-final ? past the rest of a split last word stands", "Put extinguisher on rapture?",
      oc.agree("I'ut extinguisher on rapture?", [lost, ["#", "Put", "extinguisber", "on", "Tap", ":", "ture", "?", "#"]])[0])
check("a clue-final ? past other words, or none, goes as a speck (mirror)",
      ["Put extinguisher on rapture"] * 2,
      [oc.agree("I'ut extinguisher on rapture?", [lost, ["#", "Put", "extinguisber", "on", "Tap", "Back", "portion", "?", "#"]])[0],
       oc.agree("I'ut extinguisher on rapture?", [lost, ["#", "Put", "extinguisber", "on", "Tap", "#"]])[0]])
# Times 1980-05-12: words lost from the clue's end come back with its "?"
# after them, printed once.
giant = ["#", "International", "Agreement", ",", "from", "retreat", "of", "the", "giant", "killer", "?", "#"]
check("a clue-final ? goes after the end words put in, once (mirror)",
      "International Agreement, from retreat of the giant killer?",
      oc.agree("Lnternational Agrecment, from retreat of the ganrkiller ?", [giant, giant])[0])

# Times 1977-09-26 (14716) and 1997-11-05 (20629): a count or clue number
# read as letters at the clue's edge, where the other readings read a number.
army = ["#", "Army", "leader", ",", "madly", "raring", "to", "charge", "#"]
check("a count misread as letters at the clue's end goes (times-14716 15A)",
      "Army leader, madly raring to charge", oc.agree("Army leader, madly ranng to charge IT", [army, army, army])[0])
check("a clue number misread as letters before the capital goes (times-14716 11A)",
      "Tricky way to summon Mephistopheles?",
      oc.agree("It Tricky way to summon Mephistophdes ?", [["#", "Tricky", "way", "to", "summon", "Mephistopheles", "?", "#"]] * 2)[0])
up = ["#", "Amount", "Marathon", "leader's", "up", "?", "#"]
check("the misread count's specks go with it (times-20629 5D)",
      "Amount Marathon leader's up?", oc.agree("Amount Marathon leader's up? PJ-", [up, up])[0])
novice = ["#", "could", "be", "raw", "to", "give", "this", "western", "novice", "#"]
check("a lower-case word at the clue's end is no count (mirror)", None,
      oc.agree("could be raw to give this western novice one", [novice, novice])[0])
check("a hyphen's second half is a split word's, no count (mirror, 1978-10-16)", None,
      oc.agree("Lumber one destroyed in Austr-lia", [["#", "Lumber", "one", "destroyed", "in", "Australia", "#"]] * 2)[0])
david = ["#", "Drink", "in", "David's", "hand", "#"]
check("a count read with its bracket needs one reading ending there (times-13971 22D)",
      "Drink in David's hand", oc.agree("Drink in David's hand fa).", [lost, lost, david])[0])
huge = ["#", "Some", "turned", "out", "to", "be", "huge", "#"]
check("specks after a misread count go with it (times-14792 8D)",
      "Some turned out to be huge", oc.agree("Some turned out to be huge UO). L", [lost, huge, lost, huge])[0])
check("a bracketed count no reading prints the clue around stays held (mirror)", None,
      oc.agree("Drink in David's hand fa).", [lost, lost])[0])
check("one reading ending the clue there is no majority (mirror)", None,
      oc.agree("Army leader, madly ranng to charge IT", [army, lost, lost])[0])

# Times 1996-06-24 (20202) 11A and 1980-09-10 (15318): the other readings
# read the clue's number or count as letters ("I I" for 11, "ig" for (4)),
# which the vote took for words the clue lost at a line wrap.
lucy = ["#", "I", "I", "Lucy", "Ashton", ",", "say", ",", "taking", "in", "key", "to", "be", "cut", "#"]
check("the clue's number read as letters before it is no start lost (times-20202 11A)",
      "Lucy Ashton, say, taking in key to be cut",
      oc.agree("Lucy Ashton, say, taking in key tobe cut", [lucy, lucy], number="11", count="6")[0])
check("mirror: letters that are not the clue's number are no number", False,
      oc.number_read(("i", "i"), "12", "start"))
gaunt = ["#", "De", "virtue", "like", "it", ",", "reasoned", "John", "of", "Gaunt", "ig", "#"]
check("the count read as letters after it is no end lost (times-15318)",
      "De virtue like it, reasoned John of Gaunt",
      oc.agree("De virtue like it, reasoned John of Gaunt", [gaunt, gaunt], number="9", count="4")[0])
check("mirror: with no count known, the letters are an end lost", None,
      oc.agree("De virtue like it, reasoned John of Gaunt", [gaunt, gaunt], number="9")[0])
alter = [["#", "It", "can", "alter", "number", "in", "line", "with", "charge", "#"]] * 2
check("mirror: before a clue opening small, 'It' is its lost first word (times 1984-01-23)",
      "It can alter number in line with charge",
      oc.agree("can alter number in line with charge", alter, number="11", count="6")[0])
# Times 1976-03-24 "Lacked by Chesterton's fallen sons of Eve" and 1979-12-18:
# with no number or count passed, figure-shaped specks at the clue's edge
# ("is" for "(5)", "down i" for "DOWN 1") that a reading printing the clue
# clean leaves out are no word lost.
eve = ["#", "Lacked", "by", "Chesterton's", "fallen", "sons", "of", "Eve", "is", "#"]
clean = ["#", "Lacked", "by", "Chesterton's", "fallen", "sons", "of", "Eve", "#"]
check("figure-shaped specks after the clue, one reading clean, are no end lost (times 1976-03-24)",
      "Lacked by Chesterton's fallen sons of Eve",
      oc.agree("Lacked by Chesterton's fallen sons of Eve", [eve, eve, clean, clean])[0])
downi = [["#", "DOWN", "I", "Clever", "Dick", "swots", "up", "about", "fiction", "#"]] * 2
check("a heading and a speck before the clue, one reading clean, are no start lost (times 1994-01-13)",
      "Clever Dick swots up about fiction",
      oc.agree("Clever Dick swots up about fiction", downi + [["#", "Clever", "Dick", "swots", "up", "about", "fiction", "#"]] * 2)[0])
trees = ["#", "This", "house", "is", "surrounded", "by", "trees", "#"]
terp = ["#", "Sfi", "Terpsichorean", "saint", "?", "#", "Can", "a", "farm", "perhaps", "or", "a", "battleship", "#"]
check("mirror: no edge specks pass in a clue with figures of its own (times 1978-08-15)", None,
      oc.agree("Terpsichorean saint ? (S) 27 Can a farm perhaps or a battleship",
               [terp, terp] + [["#"] + terp[2:]] * 2)[0])
check("mirror: a lost word is no figure, a clean reading or not (times 1983-12-20)", None,
      oc.agree("This house is surrounded", [trees, trees] + [["#", "This", "house", "is", "surrounded", "#"]] * 2)[0])
# Times 1977-11-24 "Equip musicians with brassards": figure specks no word
# ("fS" for its count) in one reading and words in one other are no end lost,
# as words in one reading of four alone are none; "is" may be a word lost.
brass = ["#", "Equip", "musicians", "with", "brassards"]
check("figure specks no word don't count as words seen at the edge (times 1977-11-24)",
      "Equip musicians with brassards",
      oc.agree("Equip musicians with brassards", [brass + ["fS", "#"], brass + ["#"], brass + ["surds", "#"], brass + ["#"]])[0])
check("mirror: specks that are a word ('is') count as words seen at the edge", None,
      oc.agree("Equip musicians with brassards", [brass + ["is", "#"], brass + ["#"], brass + ["surds", "#"], brass + ["#"]])[0])
check("a heading and the number ('DOWN 1') read as letters", True, oc.number_read(("down", "i"), "1", "start"))
check("a count read with its brackets ('isi' for (5))", True, oc.number_read(("isi",), "5", "end"))
check("mirror: a word is no count", False, oc.number_read(("silly",), "5", "end"))
check("mirror: a short word is no count ('money in it', not '(7)')", False, oc.number_read(("it",), "7", "end"))

# Times 1974-03-21 (13642) 13A and 1977-09 "said the1 Rev Trimmer": a figure
# run onto a word (the clue's number, a speck) that no reading prints.
isl = ["#", "Island", "is", "also", "without", "a", "carrier", "#"]
check("a clue number run onto the first word goes (times-13642 13A)",
      "Island is also without a carrier", oc.agree("3Island is also without a carrier", [isl, isl])[0])
rev = ["#", "Kings", "divinely", "so", ",", "sald", "the", "Rev", "Trimmer", "#"]
check("a figure run onto a word's end no reading prints goes",
      "Kings divinely so, said the Rev Trimmer", oc.agree("Kings divinely so, said the1 Rev Trimmer", [rev, rev, rev])[0])
check("mirror: a figure another reading reads there stays",
      "Kings divinely so, said the1 Rev Trimmer",
      oc.agree("Kings divinely so, said the1 Rev Trimmer", [rev, rev[:7] + ["#"] + rev[7:]])[0])
cry = ["#", "Alarming", "cry", "comes", "back", "tide", "is", "rising", "#"]
check("mirror: a word only one reading prints as voted keeps its figure (held)",
      "Alarming cry1 comes back tide is rising",
      oc.agree("Alarming crj1 comes back tide is rising", [cry, cry[:2] + ["csy"] + cry[3:]])[0])
mway = ["#", "M", "motorway", "jam", "#"]
check("mirror: a figure after a capital is the print's ('M1')", "M1 motorway jam", oc.agree("M1 motorway jam", [mway, mway])[0])
check("mirror: a figure before a capital is the print's ('4WD')", "4WD vehicle",
      oc.agree("4WD vehicle", [["#", "WD", "vehicle", "#"]] * 2)[0])
gentle = ["#", "Can", "be", "gentle", "as", "birds", "#"]
check("mirror: a clue with other specks keeps its figure (held)", "Can be8 gentle. 'as birds",
      oc.agree("Can be8 gentle. 'as birds", [gentle, gentle])[0])

# Times 1984-01-23 "for herl7", 1977-09-27 "say?14": the count or the next
# clue's number run onto the clue's last word or its "?".
her = ["#", "Morning", "suits", ",", "said", "O'Neill", ",", "for", "her", "#", "#", "Obliteration", "#"]
check("a figure run onto the clue's last word is the next number: gone",
      "Morning suits, said O'Neill, for her", oc.agree("Morning suits, said O'Neill, for her7", [her, her])[0])
check("a figure after the clue's '?' goes", "Laughter of a huntsman, say?",
      oc.agree("Laughter of a huntsman, say?14", [["#", "Laughter", "of", "a", "huntsman", ",", "say", "?", "#", "#", "Tips"]] * 2)[0])
dog = ["#", "Poor", "dog", ",", "third", "of", "#", "#", "#", "Count"]
check("mirror: more numbers after the last word than count and next is a reference (held)",
      "Poor dog, third of8", oc.agree("Poor dog, third of8", [dog, dog], count="3")[0])
check("mirror: a reading with a word after the last word keeps the figure (held)",
      "Morning suits, said O'Neill, for her7",
      oc.agree("Morning suits, said O'Neill, for her7", [her, her[:9] + ["lt"] + her[9:]])[0])

# Times 1976-10-27 "Result0f", 1983-12-20 "to0": a letter read as its
# look-alike figure, which the vote put back in the word it touches.
res = ["#", "Result", "of", "tax", "deducted", "#"]
check("a figure the vote read as the next word's letter goes ('Result0f')",
      "Result of tax deducted", oc.agree("Result0f tax deducted", [res, res])[0])
too = ["#", "Landseer's", "work", "has", "dignity", "too", "#"]
check("a figure the vote read as the word's last letter goes ('to0')",
      "Landseer's work has dignity too", oc.agree("Landseer's work has dignity to0", [too, too])[0])
ras = ["#", "Raises", "as", "a", "result", "of", "#", "perhaps", "?", "#"]
check("a figure read as the word's letter goes beside another figure ('a5' for 'as')",
      "Raises as a result of 21 perhaps?", oc.agree("Raises a5 a result of 21 perhaps?", [ras, ras])[0])
rat = ras[:2] + ["at"] + ras[3:]
check("mirror: a figure that is no look-alike of the letter put back stays",
      "Raises at5 a result of 21 perhaps?", oc.agree("Raises a5 a result of 21 perhaps?", [rat, rat])[0])
check("mirror: a clue with other figures keeps a lead one (a run-on)", "8Ruth's beer 151",
      oc.agree("8Ruth's beer 151", [["#", "Ruth's", "beer", "#"]] * 2)[0])

# A speck read as a stop on a word's start (Times holds "visionary.lose.his",
# "for .concealed", which the final close-up made "for.concealed").
vis = ["#", "Revolutionary", "device", "makes", "visionary", "lose", "his", "head", "#"]
check("a stop glued between two words no clue prints so becomes their space",
      "Revolutionary device makes visionary lose his head",
      oc.agree("Revolutionary device makes visionary.lose.his head", [vis, vis])[0])
mea = ["#", "Measures", "for", "concealed", "lighting", "#"]
check("a stop glued to a small word's start goes, not closed up onto the word before",
      "Measures for concealed lighting", oc.agree("Measures for .concealed lighting", [mea, mea])[0])
rec = ["#", "Railway", "device", "holds", "the", "record", "#"]
check("two stops a space apart on a small word's start go ('the. .record')", "Railway device holds the record",
      oc.agree("Railway device holds the. .record", [rec, rec])[0])
lov = ["#", "To", "whom", "his", "love", ",", "princess", "#"]
check("the voted word's small letter counts, not the misread capital ('his.Iove')", "To whom his love, princess",
      oc.agree("To whom his.Iove, princess", [lov, lov])[0])
duke = ["#", "Some", "bread", "for", "the", "Duke", "of", "Normandy", "#"]
check("a middle dot between words is their space, before a capital too",
      "Some bread for the Duke of Normandy", oc.agree("Some bread for the Duke of\u00b7Normandy", [duke, duke])[0])
fire = ["#", "Make", "firewood", "out", "of", "the", "old", "piano", "#"]
check("a stop before a quotation's mark goes, the mark stays", "Make firewood out of 'the old piano",
      oc.agree("Make firewood out of.'the old piano", [fire, fire])[0])
been = ["#", "No", "doubt", "his", "deeds", "have", "been", "witnessed", "#"]
check("mirror: an ellipsis is the print's", "No doubt his deeds have been...witnessed",
      oc.agree("No doubt his deeds have been...witnessed", [been, been])[0])
bull = ["#", "John", "Bull", "The", "greatest", "#"]
check("mirror: a stop before a capital may end a sentence", "John Bull.The greatest",
      oc.agree("John Bull.The greatest", [bull, bull])[0])
check("mirror: a lone letter's stop (e.g.) is no speck", "Fruit e.g. apple",
      oc.agree("Fruit e.g. apple", [mark("4 Fruit e.g. apple 5")] * 2)[0])
see = ["#", "See", "No", "l", "across", "#"]
check("mirror: a stop beside one letter that closes up to no word stays (1930 'No.l')", "See No.l across",
      oc.agree("See No.l across", [see, see])[0])
tur = ["#", "Turkish", "commander", "#"]
check("a stop beside one letter that closes up to a known word goes ('Turkis.h')", "Turkish commander",
      oc.agree("Turkis.h commander", [tur, tur])[0])
check("a stop before a lone 'a' is the words' space, not closed up ('fora')", "for a child",
      oc.agree("for\u00b7a child", [["#", "for", "a", "child", "#"]] * 2)[0])
check("suspect: a stop glued before a capitalised word is a speck ('by.Churchill'), not initials",
      ([("by.Churchill", "a stray mark inside a word")], []), (oc.suspect("by.Churchill"), oc.suspect("J.R.R. Tolkien")))

# Times asPrinted: readers sharing a detector share misreads, so only a word
# every reading (three or more) spells alike, no one letter from a known
# word, is the print's.
ign = "Like ignis fatuus, difficult to remember"
check("asPrinted unanimous: a word every reading of three prints is the print's (times 1992 'ignis')",
      ["ignis", "fatuus,"], oc.printed_alike(ign, [ign, ign, ign.replace(",", "")], unanimous=True))
check("mirror: two readings alone are a shared slip ('considcraie')", [],
      oc.printed_alike(ign, [ign, ign], unanimous=True))
check("mirror: a reading that spells it otherwise vouches none", ["fatuus,"],
      oc.printed_alike(ign, [ign, ign, ign.replace("ignis", "ignus")], unanimous=True))
bed = "Mother Adamson turns into a bediamite"
check("mirror: a word one letter from a known one is a shared misread ('bediamite' for bedlamite)", [],
      oc.printed_alike(bed, [bed] * 4, unanimous=True))
check("and without unanimous two readings still vouch it (the Listener's rule)", ["bediamite"],
      oc.printed_alike(bed, [bed, bed]))

# A count misread as figures after the clue's last word: cut when each
# reading prints only the count and the next clue's number there, or when
# the figures read as the count with its brackets read as ones.
line = ["#", "Head", "of", "this", "line", "?", "#", "#", "Like"]
check("figures standing after the last word where the readings print a count and the next number go (NewsUK 1978)",
      "Head of this line?", oc.agree("Head of this line 7", [line, line])[0])
ref = ["#", "Display", "list", "of", "#", "#", "#", "Social"]
check("mirror: a reference is followed by the count and the next number too ('list of 16')",
      "Display list of 16", oc.agree("Display list of 16", [ref, ref, ref])[0])
unit = ["#", "Goes", "down", "in", "#", "s", "#", "#"]
check("mirror: figures with a unit are the clue's ('in 8s')",
      "Goes down in 8s", oc.agree("Goes down in 8s", [unit, unit])[0])
girl = ["#", "Said", "to", "be", "transported", "by", "a", "girl", "#", "A", "stand", "#"]
check("figures that read as the count, its brackets as ones, go ('girl 151.' for '(5).')",
      "Said to be transported by a girl", oc.agree("Said to be transported by a girl 151.", [girl, girl], number="27", count="5")[0])
check("mirror: figures that are not the count stay when the readings do not show a count there",
      "Said to be transported by a girl 151.", oc.agree("Said to be transported by a girl 151.", [girl, girl], number="27", count="7")[0])
ship = ["#", "Fugitive", "from", "Hook", "perhaps", "in", "a", "phantom", "ship", "#", ",", "#", "#", "Next"]
check("a two-number count torn open at the end goes with its comma ('ship (6; 81')",
      "Fugitive from Hook perhaps — in a phantom ship",
      oc.agree("Fugitive from Hook perhaps — in a phantom ship (6; 81", [ship, ship, ship])[0])

# The clue's own edge word split or run apart in other readings is no
# word lost at that end; words they print past a whole edge word are.
split = ["#", "This", "stake", "is", "not", "a", "broom", "slick", "#"]
whole = ["#", "This", "stake", "is", "not", "a", "broomstick", "#"]
check("an edge word split by readings is no lost end ('broom slick' for broomstick, NewsUK 1977)",
      "This stake is not a broomstick", oc.agree("This stakc is not a broomsuick", [split, split, whole])[0])
pre = ["#", "Dr", "Grace's", "excessive", "prer", "criptious", "?", "#"]
check("and the clue's '?' past the split word stays its own ('prer criptious ?', NewsUK 1978)",
      "Dr Grace's excessive prescriptions?",
      oc.agree("Dr Gracc's excessive prescriptions?", [pre, pre, ["#", "Dr", "Grace's", "excessive", "prescriptions", "?", "#"]])[0])
nb = ["#", "Not", "by", "Bacchus", "and", "his", "pards", "#"]
check("mirror: words before a whole first word are lost ('Not by Bacchus')",
      "Not by Bacchus and his pards", oc.agree("Bacchus and his pards", [nb, nb])[0])
no = ["#", "No", "uniform", "for", "this", "law", "man", "#"]
check("mirror: two words the clue ran together stay apart ('Nouniform' for 'No uniform')",
      "No uniform for this law man", oc.agree("Nouniform for this law man", [no, no])[0])

# A capital S a reader runs onto a word (a speck, or the "?" after it)
# votes for the word, breaking a tie with the plural.
cs = ["#", "Bring", "about", "special", "celebration", "S", "#", "Pompous"]
cp = ["#", "Bring", "about", "special", "celebration", "#", "#", "Pompous"]
check("a capital S run onto a word votes for the word ('celebrationS', NewsUK 1993)",
      "Bring about special celebration", oc.agree("Bring about special celebration", [cs, cs, cp])[0])
check("and outvotes the one reading of the plural ('upwardS / upwards', NewsUK 1977)",
      "Retire with tail upward",
      oc.agree("Retire with tail upward", [["#", "Retire", "with", "tail", "upward", "S", "#", "He"],
                                            ["#", "Retire", "with", "tail", "upwards", "#", "He"],
                                            ["#", "Retire", "with", "tail", "upward", "#", "He"]])[0])
cw = ["#", "Bring", "about", "special", "celebrations", "#"]
check("mirror: a plural read with its small s stays a tie with the singular",
      None, oc.agree("Bring about special celebration", [cw, cw, cp])[0])

# Three letters run together ("toa") part where most readings print the
# two words side by side; a real word ("ago") does not.
ta = ["#", "Examination", "given", "by", "soldiers", "to", "a", "pupil", "#", "Bent"]
check("a three-letter run most readings print as two words parts ('toa pupil', NewsUK)",
      "Examination given by soldiers to a pupil", oc.agree("Examination given by soldiers toa pupil", [ta, ta, ta])[0])
ag = ["#", "Long", "a", "go", "in", "Egypt", "#"]
check("mirror: a three-letter word stays whole though readings split it ('ago')",
      "Long ago in Egypt", oc.parted("Long ago in Egypt", [ag, ag]))

# A count printed in the clue, past which no reading has a word, ends it.
fl = ["#", "A", "requisite", "one's", "incorporated", "in", "cake", "flavouring", "#", "#", "Completely"]
check("the clue ends at a count it prints when no reading has the words after ('(7). doefla')",
      "A requisite one's incorporated in cake flavouring",
      oc.agree("A requisite one's incorporated in cake flavouring (7). doefla", [fl, fl, fl])[0])
fd = ["#", "A", "requisite", "one's", "incorporated", "in", "cake", "flavouring", "doefla", "#", "Completely"]
check("mirror: a word after the count that a reading has is no cut",
      "A requisite one's incorporated in cake flavouring (7). doefla",
      oc.agree("A requisite one's incorporated in cake flavouring (7). doefla", [fl, fl, fd])[0])

# A laid clue too garbled for any reading to print it word for word is
# laid again from the clue most readings print between two numbers alike
# to it ("Yardous leaders of decad- caccin1 poeuy'", Times 1980s).
yv = [oc.marked(t, breaks=True) for t in (
    "4 Brain case is about scroop: drink, if one goes Into It 5 Various leaders of decadence in poetry 6 Head to tail",
    "4 Brala case is about strong drink, if one goes into it 5 Varlous leaders of decadence in I poetry 6 Head to tail",
    "4 Bralo case is about strong drink, if one goes into It 5 Various leaders of decad, ence in poetry 6 Head to tail")]
check("a garbled laid clue no reading prints is laid from the clue most print ('Yardous', Times)",
      "Various leaders of decadence in poetry", oc.agree("Yardous leaders of decad- caccin1 poeuy'", yv)[0])
check("mirror: a laid clue the readings print keeps its own words",
      "Various leaders of decadence in poetry", oc.agree("Various leaders of decadence in poetry", yv)[0])
check("mirror: one reading alone printing a like clue lays nothing",
      None, oc.agree("Yardous leaders of decad- caccin1 poeuy'", [yv[0], oc.marked("4 Head to tail 5 Brought forward", breaks=True)])[0])

# The re-lay drops a speck or heading the print has before the clue that
# the laid clue has none of ("DOWN I Clever Dick", Times 1994), keeps a
# hyphen the laid clue has where the print's letters agree
# ("roughly-made"), but not one beside an article ("when-the"), and holds
# a print that lost the laid clue's last word.
check("a re-laid print drops the heading and speck before it the laid clue lacks ('DOWN I', Times)",
      ["Clever", "Dick", "swots", "up"], oc.despecked(["DOWN", "I", "Clever", "Dick", "swots", "up"], ["Clever", "Dick", "swols"]))
check("mirror: a laid clue opening on no clue word keeps the print's short first word ('Sls sueh')",
      ["is", "such", "the"], oc.despecked(["is", "such", "the"], ["Sls", "sueh", "lhe"]))
check("a re-laid clue keeps the laid clue's hyphen where the letters agree ('roughly-made', Times)",
      "Doctor hurried to enter roughly-made notes",
      oc.remarked("Ductorlurriedtuenter roughly-made notes", "Doctor hurried to enter roughly made notes"))
check("mirror: a laid hyphen beside an article is a speck the re-laid clue drops ('when-the')",
      "Surprised when the lids are lifted", oc.remarked("Surprised when-the lids are li: ted", "Surprised when the lids are lifted"))
check("a re-laid clue keeps the laid brackets around a word the print reads ('(Hamlc)')",
      "He was a man, take him for (Hamlet)", oc.remarked("He was a man, take him for (Hamlc)", "He was a man, take him for Hamlet"))
sh = [oc.marked(t, breaks=True) for t in (
    "4 Check froot part of the 5 ship 6 Army leader", "4 Checl front part of the 5 ship 6 Army leader",
    "4 Check front part of the 5 ship 6 Army leader")]
check("mirror: a print that lost the laid clue's last word re-lays nothing ('die ship')",
      None, oc.agree("Check front part of die ship", sh)[0])

# The re-lay is skipped only for a reading that prints the laid clue word
# for word, every word in a row; one that misreads or loses a word ("This
# house is surrounded trees" for "This bouse is surrounded trees") does
# not block it (Times 1980s).
th = [oc.marked(t, breaks=True) for t in (
    "23 This house is surrounded by trees 24 25 Sahib, missing", "23 This house is surrounded trees 24 25 Sahib, sbows",
    "1 2 Tony joins company, but it's unstable Hail", "23 This house is surrounded by trees 24 25 Sahib, missing")]
check("a reading that prints the laid clue but for a misread word does not block the re-lay ('This bouse')",
      "This house is surrounded by trees", oc.agree("This bouse is surrounded trees", th)[0])
check("mirror: a reading that prints every laid word in a row, run together or not, blocks the re-lay",
      "She eats junkets.", oc.agree("She eats junkets.", [mark("4 She eatsjunkets. 5 A"), mark("4 She eats junkets. 5 A")])[0])

# The re-laid clue is held when it loses a dictionary word of any length
# from inside the laid clue, a comma the laid clue has, or a hyphen the
# laid clue ran together; or adds a colon it lacks.
import collections
def doubt(clue, text):
    return oc.relay_doubt(clue, text, text, collections.Counter({w.lower(): 3 for w in oc.tokens(text)}))
check("a re-lay that loses a long word inside the laid clue is held ('She junkets')",
      "lost eats", doubt("She eats junkets.", "She junkets."))
check("mirror: one that drops a speck inside the laid clue is not ('emphatically ly')",
      None, doubt("A single person emphatically ly feels no wrong", "A single person emphatically feels no wrong"))
check("a re-lay that loses the laid clue's comma is held ('elderl, leader,')",
      "a comma lost", doubt("Advice for elderl, leader, go quietly", "Advice for elderly leader go quietly"))
check("mirror: one that keeps the laid comma is not ('Drink,')",
      None, doubt("Drink, a feature of an cdu . rational SCMion", "Drink, a feature of an educational session"))
check("a re-lay that adds a colon the laid clue lacks is held",
      "a mark the laid clue lacks", doubt("Sailor in OK turn of slapstick comedy", "Sailor in OK turn of slapstick: comedy"))
check("a re-lay that parts a laid run-together compound clues hyphenate is held ('heavyhanided')",
      "parted heavy handed", doubt("Impeccable advice heavyhanided dyer?", "Impeccable advice to heavy handed dyer?"))
check("mirror: one that parts a laid run of two plain words is not ('ofconmission')",
      None, doubt("Go wrong and out ofconmission", "Go wrong and out of commission"))

# times-15602 8D: 7D's clue and its count "(6;3)." read in ahead of 8D's own.
seven = {"7-down": ("The main China-Korea Division", None, None)}
check("a clue read in ahead of another, its count and all, is cut off it (times-15602 8D)",
      "Covered inside as the tennis court is",
      oc.run_in("The main China-Korea Division (6;3). Covered inside as the tennis court is", "8-down", seven))
check("mirror: words before a count no other clue prints stay for bled() to refuse",
      "Odd words here (6;3). Covered inside",
      oc.run_in("Odd words here (6;3). Covered inside", "8-down", seven))
check("bled() refuses a count with ';' and ').' run in mid-clue",
      True, oc.bled("The main China-Korea Division (6;3). Covered inside") is not None)
check("mirror: a year in brackets after a comma is the clue's own words",
      None, oc.bled("After middle age (51), metal on US mobiles"))
import enumeration as en
check("a ';' between counts that fill the light is a misread ','", "6,3", en.comma_misread("6;3", 9))
check("mirror: a ';' whose counts do not fill the light is the paper's (two answers)", "7;8", en.comma_misread("7;8", 7))
check("a book reprint's marks replace the scan's specks where the words agree (times-15602 15D)",
      "Reverse some undertaking, as it were",
      oc.reprint_marked("Reverse, some undertaking, as it were", "Reverse  some  undertaking,  as  it  were"))
check("the scan's words stand where the book rewords them (times-15602 18D)",
      "Army takes a long time to get Americans freed",
      oc.reprint_marked("Army takes a long, time to get Americans freed", "Army takes a long time to get certain prisoners"))
check("mirror: another clue's reprint changes nothing",
      "Covered inside as the tennis court is", oc.reprint_marked("Covered inside as the tennis court is", "Neat-sounding passage"))
# The book's marks vote both ways with the scan's (times-15602 vs book-32043).
rm = oc.reprint_marked
check("a clue number the book's reader glued on is not taken ('.15 A blow')",
      "A blow to the head", rm("A blow to the head", ".15 A blow to the head"))
check("mirror: the book's marks still clear the scan's speck beside it",
      "A blow to the head", rm("A blow. to the head", ".15 A blow to the head"))
check("a run-together word in the book ('Ina') leaves the scan's words",
      "Bird in a tree", rm("Bird in a tree", "Bird Ina tree"))
check("mirror: the scan's own run-together is not parted by marks alone",
      "Bird Ina tree", rm("Bird Ina tree", "Bird in a tree"))
check("a capital the scan reads mid-clue takes the book's lower case ('To')",
      "Lift to the top", rm("Lift To the top", "Lift to the top"))
check("mirror: a capital after a colon stays",
      "Lift: To the top", rm("Lift: To the top", "Lift: to the top"))
check("where the paper ends 'Humbug?' and the book 'Humbug!', the paper's stands",
      "Humbug? Nonsense", rm("Humbug? Nonsense", "Humbug! Nonsense"))
check("mirror: a speck where the book prints '!' takes the book's",
      "Humbug! Nonsense", rm("Humbug . Nonsense", "Humbug! Nonsense"))
check("no space before '?', though the scan has more spaces",
      "Is this the way?", rm("Is this the way ?", "Is this the way?"))
check("mirror: nor from the book's space before '?'",
      "Is this the way?", rm("Is this the way?", "Is this the way ?"))
check("an unpaired curly quote in the book is no vote: the scan's pair stands",
      'He said "stop" now', rm('He said "stop" now', "He said \u201cstop now"))
check("mirror: a paired book quote mends the scan's lost half, spelt straight",
      "He said 'stop' now", rm("He said stop' now", "He said \u2018stop\u2019 now"))
check("a dash both prints read between words is the house em dash",
      "Run \u2014 fast away", rm("Run - fast away", "Run \u2014 fast away"))
check("mirror: a closed plain hyphen in either stays a hyphen ('20-look')",
      "A 20-look clue", rm("A 20-look clue", "A 20 \u2014 look clue"))
check("the book's count where the scan's lost its marks and the totals match (9 -> 5,4)",
      "5,4", oc.reprint_count("9", "5,4"))
check("mirror: totals that differ keep the scan's", "9", oc.reprint_count("9", "5,3"))
check("mirror: a scan count with marks keeps them", "5,4", oc.reprint_count("5,4", "9"))

# A run of spaces ("Toe  so", cryptic-20467 1995) is a join, never the print's.
check("a run of plain spaces is cut to one, italics moved with it",
      ("Toe so it", [{"at": 4, "length": 2}]), en.collapse_spaces("Toe  so it", [{"at": 5, "length": 2}]))
check("mirror: a typeset en space is the setter's and stays",
      "\u2002\u2002 9", en.collapse_spaces("\u2002\u2002 9")[0])
check("enumeration.clue builds the clue with one space",
      "wrong Elvis? Dead right!", en.clue("wrong Elvis?  Dead right! (3,6)")["text"])
spaced_e = {"clue": {"text": "Toe  so it"}, "annotation": {"definitions": [{"text": "Toe  so", "at": 0}, {"text": "so it", "at": 5}], "hiddenLetter": 8}}
en.collapse_entry_spaces(spaced_e)
check("an annotated clue's quoted phrases, definition offsets and hiddenLetter follow its spaces",
      ("Toe so it", "Toe so", 4, 7), (spaced_e["clue"]["text"], spaced_e["annotation"]["definitions"][0]["text"],
                            spaced_e["annotation"]["definitions"][1]["at"],
                            spaced_e["annotation"]["hiddenLetter"]))
check("corrects() takes a re-read that only cuts a run of spaces", True, fa.corrects("Toe  so it", "Toe so it"))
check("mirror: nor one that changes marks besides", False, fa.corrects("Toe  so it", "Toe, so it"))
import edition_commit as ec
two = {"entries": [{"number": 1, "direction": "across", "clue": {"text": "Toe  so it"}},
                   {"number": 2, "direction": "down", "clue": {"text": "Plain clue"}}]}
check("strayed() flags a clue with a run of spaces, so its edition comes due", {"1-across"}, ec.strayed(two))
check("mirror: spaces=False (the held file's lost lights) leaves it to be collapsed", set(), ec.strayed(two, spaces=False))
check("collapse_held_spaces cuts the held clue in place", ({"1-across": "Toe so it"}, "Toe so it"),
      (fa.collapse_held_spaces(two), two["entries"][0]["clue"]["text"]))
import puzzle_integrity as pi
gate_new = {"id": "times-1", "source": {"retrievedFrom": "newspaper"},
            "entries": [{"number": 1, "direction": "across", "clue": {"text": "Toe  so it"}}]}
flags = []; pi.check_new_spaces(None, gate_new, flags)
check("the write gate refuses an OCR clue with a run of spaces", 1, len(flags))
flags = []; pi.check_new_spaces(gate_new, gate_new, flags)
check("mirror: one the held file already had stays for its re-read", 0, len(flags))
flags = []; pi.check_new_spaces(None, {**gate_new, "source": {"retrievedFrom": "publisher"}}, flags)
check("mirror: a publisher feed is collapsed by its filer, not gated", 0, len(flags))

# A held file's count is mended alone, its words unchanged (times-15602 7D).
def held_count(enum, length=9, group=None):
    lights = [{"number": 7, "direction": "down", "length": length, "clue": {"text": "The main China-Korea Division", "enumeration": enum}}]
    if group:
        lights[0]["group"] = ["7-down", "9-down"]
        lights.append({"number": 9, "direction": "down", "length": group, "clue": {"text": "See 7"}})
    return {"entries": lights}
held = held_count("6;3")
check("a held ';' whose counts fill the light becomes ',' with its separator (times-15602 7D)",
      (["7-down"], {"text": "The main China-Korea Division", "enumeration": "6,3", "separators": [{"at": 6, "mark": ","}]}),
      (fa.book_counted(held, {}), held["entries"][0]["clue"]))
held = held_count("9")
check("a held bare count takes the book's marks at the same total", (["7-down"], "5,4"),
      (fa.book_counted(held, {"7-down": ("The main China-Korea Division", "5,4")}), held["entries"][0]["clue"]["enumeration"]))
held = held_count("7;8", length=7)
check("mirror: a ';' that does not fill the light is the paper's", ([], "7;8"), (fa.book_counted(held, {}), held["entries"][0]["clue"]["enumeration"]))
held = held_count("9")
check("mirror: a book count at another total changes nothing", [], fa.book_counted(held, {"7-down": ("x", "5,3")}))
held = held_count("4;5", length=4, group=5)
fa.book_counted(held, {})
check("a linked group's count puts a break on the boundary at the earlier light's end",
      ("4,5", [{"at": 4, "mark": ","}], None), (held["entries"][0]["clue"]["enumeration"], held["entries"][0]["clue"].get("separators"),
                            held["entries"][1]["clue"].get("separators")))

print(f"FAILS {fails}")
EOF
)
echo "$out"
grep -q '^FAILS 0$' <<<"$out" || { echo "test_ocr_vote_checks: failed"; exit 1; }
echo "test_ocr_vote_checks: all passed"
