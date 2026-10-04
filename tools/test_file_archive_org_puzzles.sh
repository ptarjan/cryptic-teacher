#!/bin/bash
# Does tools/file_archive_org_puzzles.py find the Times cryptic's title and
# not its neighbours', read the clue columns in order, keep only the clues
# both readings agree on, and match a Canberra reprint only when it is one?
#
#     bash tools/test_file_archive_org_puzzles.sh
#
# Pure functions on made-up words and puzzles: no scan, no RapidOCR, nothing
# written outside a temp dir.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" python3 - <<'EOF'
import json, os
from pathlib import Path
import file_archive_org_puzzles as f
import ocr_clues

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

def line(text, x=100, y=100):
    words, out = text.split(), []
    for w in words:
        out.append((x, y, x + 10 * len(w), y + 16, w))
        x += 10 * len(w) + 8
    return out

# The title: the daily cryptic's, its number, a box ending at the number.
hits = f.headings([line("THE TIMES CROSSWORD NO 19,742 1 1 times weathercall")], f.TITLE)
check("1990s title read, junk after the number left out", (19742, 100 + 10*3+8 + 10*5+8 + 10*9+8 + 10*2+8 + 10*6),
      (hits[0][0], hits[0][1][2]))
check("1970s title read", [13677], [n for n, _ in f.headings([line("The Times Crossword Puzzle No 13,677")], f.TITLE)])
check("Concise, Times Two and Jumbo titles are not the cryptic's", [],
      f.headings([line("CONCISE CROSSWORD NO 2065"), line("Times Two Crossword, page 32"),
                  line("Times Jumbo Crossword No 812")], f.TITLE))
# Real misread titles from scans the pass found no title on (1977-03-31,
# 1975-06-05, 1992-03-10, 1999-03-31).
check("misread titles read: first word, a mark before Crossword, a split number, a comma read as *",
      [14564, 14012, 18862, 21065],
      [n for t in ("Hie Times Crossword Puzzle No 14,564", "The Times 'Crossword Puzzle No 14,012",
                   "THE TIMES CROSSWORD PUZZLE NO 1 8,862", "THE TIMES CROSSWORD NO 21*065")
       for n, _ in f.headings([line(t)], f.TITLE)])
# A scan cached by older heading code is made again, and a title it finds
# that no verdict covers makes the edition due.
key, code = f.scan_key(), f.SCAN_CODE
f.SCAN_CODE = code - {"TITLE"}; f._SCAN_KEY.clear()
check("the title pattern is in the scan key", True, f.scan_key() != key)
f.SCAN_CODE = code; f._SCAN_KEY.clear()
check("a title no verdict covers makes the edition due", "titles changed",
      f.due_reason({"inputs": "h", "solutionsSeen": [], "verdicts": [], "vlm": "v",
                    "scan": {"puzzles": [{"number": 18862}]}}, "h", [], "v"))
check("a title run together with its \"The\" is read (1995-04-12)", [19827],
      [n for n, _ in f.headings([line("THETIMES CROSSWORD NO 19,827")], f.TITLE)])
f.SCAN_CODE = code - {"ocr_titles"}; f._SCAN_KEY.clear()
check("the title OCR is in the scan key", True, f.scan_key() != key)
f.SCAN_CODE = code; f._SCAN_KEY.clear()
words = [(2108, 2835, 2214, 2853, "Horthern Bank Ltd"), (2504, 2828, 2845, 2869, "CROSSWORD"),
         (2262, 2729, 2293, 2947, "*922393s93s"), (2108, 2896, 2183, 2914, "Rea Brothers"),
         (2468, 2892, 2882, 2924, "No.7,869 Set by CINEPHILE")]
got = [" ".join(w[4] for w in l) for l in f.printed_lines(words)]
check("OCR words make printed lines: a column apart is its own line, a column rule read as a word "
      "(FT 1992-06-10) does not join the title to its number line",
      (True, True, True), ("CROSSWORD" in got, "No.7,869 Set by CINEPHILE" in got, "Rea Brothers" in got))
check("the Sunday Times's title is not the daily's", [], f.headings([line("The Sunday Times Crossword No 2,345")], f.TITLE))
check("the cryptic's solution heading read", [18179],
      [n for n, _ in f.headings([line("Solution to Puzzle No 18,179"), line("SOLUTION TO NO 2064")], f.SOLUTION)])
check("1970s solution heading read", [13676],
      [n for n, _ in f.headings([line("Solution of Puzzle No 13,676 B.A. &so.")], f.SOLUTION)])

# The columns: left then right, a number read apart joined to its row, a
# second copy of words dropped, cut at the solution heading.
grid = (100, 100, 800, 800)
lines = [line("ACROSS", 100, 820), [(100, 842, 118, 858, "1")], line("Nymph with broken heart (8)", 130, 840),
         line("DOWN", 470, 820), line("2 Hermit is strangely secure (7)", 470, 840),
         line("2 Hermit is strangely secure (7)", 470, 841),
         line("Solution to Puzzle No 13,676", 100, 870), line("rubbish (3)", 100, 890)]
check("columns read left then right, a row joined, a copy dropped, cut at the solution",
      "ACROSS\n1 Nymph with broken heart (8)\nDOWN\n2 Hermit is strangely secure (7)",
      f.column_text(f.columns(lines, grid)))
far = [line("ACROSS", 100, 820), line("1 Nymph (8)", 100, 840), line("9 Gap (5)", 100, 840 + f.GAP + 40)]
check("a gap ends a column", "ACROSS\n1 Nymph (8)", f.column_text(f.columns(far, grid)))

# tidy(): OCR's slips in the print's shape.
check("braces and square brackets read as round ones", "1 Poet's way (5)\n2 Talks (3,2)",
      f.tidy("1 Poet's way {5}\n2 Talks [3,2]"))
check("a number run into its word split off", "1 Mythical king (9)", f.tidy("1Mythical king (9)"))
check("a number lost after a count marked for the grid", "10 Nurse (7)\n? Holds fast (5)",
      f.tidy("10 Nurse (7)\nHolds fast (5)"))
check("a number lost after the heading marked", "ACROSS\n? Nymph (8)", f.tidy("ACROSS\nNymph (8)"))
check("a wrapped line is not marked", "10 Nurse holding\nNote (7)", f.tidy("10 Nurse holding\nNote (7)"))
check("a count with a broken close read as one", "19 Stole pig (3)", f.tidy("19 Stole pig off3j".replace(" off", "")))

# Page text after the list's last count: a speck after the count ("(5). _")
# is no text, so the footer after it is dropped, not read as a clue.
check("a speck after a count is dropped and the footer with it",
      "DOWN\n24 Realism is the beauty of Keats\n(5)",
      f.tidy("DOWN\n24 Realism is the beauty of Keats\n(5). _\nConte crossword, base 22"))
check("a pointer to another page's puzzle ends the column",
      [True, True, True, False, False],
      [bool(f.STOP.match(t)) for t in ("Conte crossword, base 22", "Coacise crosswurd, page 22",
                                       "The solution to the Collins Competition", "Cross words about 22",
                                       "Crossed words, quite 2")])
# The list's last clue holding the next one (its count lost) is split.
p, _ = f.parse("ACROSS\n1 Walpole nominated as poet (6)\nDOWN\n22 No good having female in group\n"
               "24 Realism is the beauty of Keats\n(5)")
check("the last clue's run-on clue is split off",
      [({22}, "No good having female in group", set()), ({24}, "Realism is the beauty of Keats", {"5"})],
      [(c["tokens"][0], c["text"], c["enums"]) for c in p["down"]])
p, _ = f.parse("ACROSS\n1 Walpole nominated as poet (6)\nDOWN\n22 Rest at 2 Downing Street (5)")
check("a reference in the last clue is not split", ["Rest at 2 Downing Street"], [c["text"] for c in p["down"]])
# The columns under the grid split at their gutter, not the grid's middle:
# a right-hand clue whose number starts left of the middle is the right
# column's, never run into the left column's row (ftcryptic-9091).
grid = (2270, 3000, 2905, 3400)
words = [[(2253, 3462, 2565, 3486, "28 Take part of case for leisure")],
         [(2577, 3462, 2886, 3484, "22 Affected by American univer-")],
         [(2581, 3419, 2889, 3442, "20 Corrects sexually innocent")],
         [(2270, 3415, 2569, 3435, "1 Graduate teachers object to")]]
split = f.under_gutter(words, grid)
cols = f.columns(words, grid, split=split)
check("the gutter lies between the columns", True, 2569 < split < 2577)
check("a right-hand clue left of the grid's middle stays in its column",
      ["1 Graduate teachers object to", "28 Take part of case for leisure"], [l[4] for l in cols[0]])

# fault(): what the filer refuses to file, and what the print really has.
for text, enum, cells, want in [
        ("Corrects sexually innocent Poles 22 Affected by American", "8", 8, "holds a clue number"),
        ("The solution of Saturday's Prize Puzzle No 18,178 will appear next Saturday 26 The point is", "9", 9,
         "holds a clue number"),
        ("Conte crossword, page 22", "5", 5, "holds the page's text"),
        ("Untie reef knots (41. Times Two Crossword, page 44", "4", 4, "holds the page's text"),
        ("The solution to the Collins Competition will now Qualifier puzzle", "4", 4, "holds the page's text"),
        ("None", "5", 5, "the text is the word None"),
        ("Fine island, jolly compact", "5", 4, "its count"),
        ("Laugh immoderately as Jack gets into quarrel", "4,5", 9, None),
        ("3 3 on the watch", "5", 5, None),
        ("under twenty-one", "5", 5, None),
        ("Clumsy and old-fashioned in hack work", "11", 11, None),
        ("Mournful supporter in English lac", "7", 7, None),
        ("Basic material for 9 or Junius?", "9", 9, None),
        ("Making notes to phone about the 18", "9", 9, None),
        ("Removal of 25 I notice in distress outside", "8", 8, None),
        ("See 9 Across", None, 5, None),
        ("Market town supplying meat on 24 and 31 December?", "5", 5, None),
        ('"Hollow pamper\'d Jades of - (2 Hen. IV)', "4", 4, None),
        ('Thomas Huxley\'s 73 "organized common sense', "7", 7, None)]:
    got = ocr_clues.fault(text, enum, cells)
    check(f"fault {text[:30]!r}", want, got and got[:len(want)] if want else got)
laid, blank = f.unfit_blanked({"22-down": ("Poles 22 Affected by it", "6", None), "1-across": ("Fine", "6", None),
                               "3-across": ("Too long", "9", None)}, {}, {"22-down": 6, "1-across": 6, "3-across": 6})
check("an unfit clue is filed blank, its count kept when it fills the light",
      ({"22-down": ("", "6", None), "1-across": ("Fine", "6", None), "3-across": ("", None, None)},
       ["22-down", "3-across"]), (laid, sorted(blank)))
puz = {"entries": [{"number": 1, "direction": "across", "length": 6, "clue": {"text": "Fine", "enumeration": "6"}},
                   {"number": 2, "direction": "down", "length": 4, "group": ["2-down", "3-down"],
                    "clue": {"text": "Long 2 Joined", "enumeration": "4,3"}},
                   {"number": 3, "direction": "down", "length": 3, "clue": {"text": "See 2"}}]}
check("faults() counts a linked clue's lights together", ["2-down"], sorted(f.faults(puz)))
check("a puzzle with a fault is not complete", False, f.complete(puz))

# A word two other readings share that is no word goes in mended.
others = [ocr_clues.tokens("This lener may be umsigned it should be remembered"),
          ocr_clues.tokens("This ietter may be umsigned it should be remnembered"),
          ocr_clues.tokens("This letter be 14")]
check("a word lost from this reading goes in as the known word the others misread",
      "This letter may be unsigned it should be remembered",
      ocr_clues.agree("This letter may be it should be remembered", others)[0])

# agree(): only what both readings say, or what the dictionary settles.
stream = ocr_clues.tokens("8 Hope created this exalted 9 Bottom of a ship (3) 10 Nurse hoiding note (7) 11 Prinz Ahdk (5)")
check("both readings agree", ("Bottom of a ship", "agree"), ocr_clues.agree("Bottom of a ship", stream))
check("a misread settled by the other reading's dictionary word",
      ("Nurse holding note", "settled by the dictionary"), ocr_clues.agree("Nurse holding note", stream))
check("the clue's misread replaced by the other reading's word",
      ("Hope created this exalted", "settled by the dictionary"), ocr_clues.agree("Hope crealed this exalted", stream))
check("two non-words are a disagreement", None, ocr_clues.agree("Prinz Ahdq", stream)[0])
check("a word the other reading lacks is a disagreement", None, ocr_clues.agree("Bottom of a big ship", stream)[0])
check("both readers' one non-word mended to the known word a letter off", "Nurse holding note",
      ocr_clues.agree("Nurse hoiding note", stream)[0])

check("a capital only one reader saw inside the clue dropped", ("What is stated", "settled by the dictionary"),
      ocr_clues.agree("What Is stated", ocr_clues.tokens("27 What is stated (9)")))
got, _ = ocr_clues.reconcile({"25-across": ("As worn by agitator in back- street", "8", None)},
                     "25 As worn by agitator in back-\nstreet (8)")
check("a word hyphenated over a line end is joined as the corpus prints it", "As worn by agitator in backstreet",
      got["25-across"][0])
check("the clue's first word keeps its capital", ("Bottom of a ship", "agree"),
      ocr_clues.agree("Bottom of a ship", ocr_clues.tokens("bottom of a ship")))

# Three readings: a word the other two share outvotes mine; a mark no other
# reading has is dropped; a non-word all three read is kept.
two = [ocr_clues.marked("8 Wisdom shown by school-head when dress is questionable (10)"),
       ocr_clues.marked("8 Wisdom shown by school-head when dress is questionabie (10)")]
check("a lone comma no other reading has dropped",
      "Wisdom shown by school-head when dress is questionable",
      ocr_clues.agree("Wisdom shown by, school-head when dress is questionable", two)[0])
check("a comma two readings have kept", "Talk, about a fellow",
      ocr_clues.agree("Talk, about a fellow", [ocr_clues.marked("Talk, about a fellow"), ocr_clues.marked("Talk about a fellow")])[0])
check("the spelling the other two readings share outvotes mine (dictionary words both)",
      "Cashing in on Nigel's air", ocr_clues.agree("Cashing in on Nigel's ail",
                                           [ocr_clues.marked("Cashing in on Nigel's air")] * 2)[0])
check("a word one of two other readings has stands", "Sun god's not out",
      ocr_clues.agree("Sun god's not out", [ocr_clues.marked("Son god's not out"), ocr_clues.marked("Sun gods not out")])[0])
check("a non-word all three readings have, no letter from a word, kept", "Get production up qzxvbn",
      ocr_clues.agree("Get production up qzxvbn", [ocr_clues.marked("Get production up qzxvbn")] * 2)[0])
check("a name the corpus's clues know is a word", "Captain Hornblower at sea",
      ocr_clues.agree("Captain Hornblower at sea", [ocr_clues.marked("3 Captain Hornblower at sea (7)", breaks=True)] * 2)[0])
check("a lone letter no other reading has is a speck", "Annual production",
      ocr_clues.agree("Annual l production", [ocr_clues.marked("4 Annual production (5)", breaks=True)] * 2)[0])
got, blank = ocr_clues.reconcile({"8-down": ("Wisdom shown by, school-head", "10", None)},
                         ["8 Wisdom shown by school-head (10)", "8 Wisdom shown by school-head (10)"])
check("reconcile votes with every reading it is given", "Wisdom shown by school-head", got["8-down"][0])

# A real word misread as another (real readings off the gold editions).
def vote(clue, *readings):
    return ocr_clues.agree(clue, [ocr_clues.marked(t, breaks=True) for t in readings])[0]
check("a number standing for a word it looks like takes the word: \"10\" for \"to\" (Times 18,180 12A)",
      "When in quarters, be agreeable to forming a unit",
      vote("When in quarters, be agreeabie 10 forming a unit",
           "1 When in quartets , be agreeable to forming a unit 1",
           "1 When in quarters , be agreeable Io forming a unit 1",
           "yt be tempted by partnership 1 Smoothed an upset in"))
check("\"3\" for \"a\" where the other readings read \"a\" (Times 13,678 19A)", "A boy is backward, and not a girl",
      vote("A bny is backward, and not 3 girl", "1 A boy Is backward , and not a girl 1",
           "1 A bny is backward , and not a gir 1", "1 A boy is backward , and pot a girl 1"))
check("a number the other readings print as a number stays", "Like a don in trouble with Homer in 3",
      vote("Like a don in trouble with Homer in 3", "15 Like a don in trouble with Homer in 3 (5)",
           "15 Like a don in trouble with Homer in 3 (5)"))
check("a word one confused letter from a commoner one a reader has that fits far better (Times 16,786 20D)",
      "Innovator of single element in breakwater",
      vote("Innovator of single clement in breakwater", "1 Innovalor of singic clement in brcakwaleri 1",
           "1 Innovator of singie element in breakwaler 1", "1 Innovator of single clement in reakwater 1"))
check("\"ad\" for \"an\", one reader reading \"an\" (Times 13,682 23A)", "Its rate is adjusted for an entertainer",
      vote("Its rate is Jdijusted for ad entertainer", "1 Its rare is adjusted for ad entertainer f",
           "1 Irs rate is aujusted for ad cntertainer f", "1 tts rate is adjusted for an 1"))
check("a non-word every reader shares, one confused letter from a word (Times 13,682 13A)",
      "In its turn it does us a power of good",
      vote("In its turn it does us a power ot good", "1 In its turn it does us a power ot good f",
           "1 In its turn it does usa power ot good 1", "1 In its turn it does us a power ot good 1"))
check("two readings' \"al\" gives way to \"at\" (Times 18,179 22D)", "In the Orient reeds are served at dinner",
      vote("In the Orient reeds are served at dinner", "1 In the Orient reeds are served al dinner 1",
           "1 In the Orient reeds are served al dinner 1", "wros they or reckon are following the"))
check("a word three readings share is no slip of a commoner one that fits no better (Times 19,742 28A)",
      "Result may be tame but filling food",
      vote("Resull may be tame but filling food", "Times Two Crossword ,",
           "1 Result may be tame but filling food 1", "1 Result may be tame but hifing food 1"))
for clue in ("Chance it perhaps if over 50", "Lace it tight round top of stocking",
             "Excellent worker in firm, one co-opted originally", "Disturbed when riding on 19ac"):
    check(f"a word every reading has stays, however a confused letter would fit: {clue!r}", clue,
          vote(clue, f"4 {clue} (5)", f"4 {clue} (5)", f"4 {clue} (5)"))

# Words and marks this reading lost, and the print's commonest mark slips.
three = [ocr_clues.marked(t, breaks=True) for t in ("9 Hurtful stuff, nicer as a cocktail? (7)",
                                            "9 Hurtful stuff, nicer as a cocktail? (7)",
                                            "9 Hurtfui stuff nicer as a cocktail (7)")]
check("a comma most other readings have put in", "Hurtful stuff, nicer as a cocktail?",
      ocr_clues.agree("Hurtful stuff nicer as a cocktail?", three)[0])
lost = [ocr_clues.marked(t, breaks=True) for t in ("18 It's no go when caught (8)", "18 It's no go when caught (8)",
                                           "18 Its no go when caught (8)")]
check("lost opening words most readings have put in, with the capital", "It's no go when caught",
      ocr_clues.agree("Go when caught", lost)[0])
check("lost opening words the readings differ on blank the clue", None,
      ocr_clues.agree("Go when caught", [ocr_clues.marked(t, breaks=True) for t in
                                 ("18 It's no go when caught (8)", "18 Is so go when caught (8)")])[0])
check("lost closing words most readings have put in", "Girls were well sustained by it",
      ocr_clues.agree("Girls were well sustained by", [ocr_clues.marked("19 Girls were well sustained by it (7)", breaks=True)] * 2)[0])
check("a dictionary tie goes to the word the corpus's clues put there", "A boy is backward",
      ocr_clues.agree("A bny is backward", [ocr_clues.marked("19 A boy is backward (4)", breaks=True),
                                    ocr_clues.marked("19 A bay is backward (4)", breaks=True)])[0])
check("a dictionary tie no neighbour settles blanks the word", None,
      ocr_clues.agree("Qxv bny qxv", [ocr_clues.marked("1 Qxv boy qxv (3)", breaks=True),
                              ocr_clues.marked("1 Qxv bay qxv (3)", breaks=True)])[0])
check("one reading's far shorter dictionary word is no rival", "Chucked one in",
      ocr_clues.agree("Chucked one in", [ocr_clues.marked("24 Chuckeu one in (5)", breaks=True),
                                 ocr_clues.marked("24 Che one in (5)", breaks=True)])[0])
check("a rare word one ink slip from a far commoner one takes the commoner", "Bob hangs on to this",
      ocr_clues.agree("Bob hangs ou to this", [ocr_clues.marked("3 Bob hangs ou to this (5)", breaks=True)] * 3)[0])
check("the next clue run on is cut off, the count from the grid",
      ({"5-down": ("Twists ends of osier into knot", "7", None)}, {}),
      ocr_clues.reconcile({"5-down": ("Twists ends of osier into knot (7k 6 Protection for working", None, None)},
                  ["5 Twists ends of osier into knot (7) 6 Protection for working"], {"5-down": 7, "6-down": 3}))
check("a lone letter after the clue is its misread count, the count from the grid",
      ({"2-down": ("A bit of nice dark wood", "5", None)}, {}),
      ocr_clues.reconcile({"2-down": ("A bit of nice dark wood", None, None)},
                  ["2 A bit of nice dark wood s 3 Next", "2 A bit of nice dark wood a 3 Next"], {"2-down": 5}))
check("a mark dropped between two words leaves their space", "Lack of spirit after a storm",
      ocr_clues.agree("Lack of spirit:after a storm", [ocr_clues.marked("1 Lack of spirit after a storm (4)", breaks=True)] * 2)[0])
check("a misread clue number before the capital dropped", "Not small horse-pistols",
      ocr_clues.agree("I Not small horse-pistols", [ocr_clues.marked(t, breaks=True) for t in
                                            ("21 Not small horse-pistols (5)", "21 Not smal horse-pistols (5)")])[0])
check("a full stop before a lower-case word is a comma", "Let nine go loose, being merciful",
      ocr_clues.clean("Let nine go loose. being merciful"))
check("an ellipsis and an abbreviation keep their stops", "Oval . . . the C.I.D. man",
      ocr_clues.clean("Oval . . . the C.I.D. man"))
check("an I last before the count is an exclamation mark", "Flirted outrageously! (7)",
      ocr_clues.clean("Flirted outrageously I (7)"))
check("a word broken over a line end is joined", "Almost admire a lieutenant unknown",
      ocr_clues.clean("Almost admire a lieutenant un-\nknown"))
check("a line-end hyphen the corpus's clues print closed is the line break's", "agitator in backstreet",
      ocr_clues.clean("agitator in back-\nstreet"))
check("a line-end hyphen the corpus's clues print hyphenated is the compound's", "start is short-lived",
      ocr_clues.clean("start is short-\nlived"))
check("a name hyphenated over a line end is joined", "resembling Palgrave's Treasury",
      ocr_clues.clean("resembling Pal-\ngrave's Treasury"))
check("a compound the corpus never prints keeps its hyphen", "Wisdom shown by school-head",
      ocr_clues.clean("Wisdom shown by school-\nhead"))
check("a hyphen inside a line breaking a lexicon word is joined",
      ["Kohoutek's brilliant predecessor", "Becoming a supporter with obvious hesitation", "to do housework"],
      [ocr_clues.unhyphen(t) for t in ("Kohoutek's brilliant pre-decessor",
                                       "Becoming a supporter with ob-vious hesitation", "to do house-work")])
check("a hyphen inside a line stands where the corpus's clues print that form",
      ["in back-street", "Sea-bird", "It's breath-taking", "to co-operate", "is short-lived", "by school-head",
       "an Anglo-Saxon", "a well-to-do man"],
      [ocr_clues.unhyphen(t) for t in ("in back-street", "Sea-bird", "It's breath-taking", "to co-operate",
                                       "is short-lived", "by school-head", "an Anglo-Saxon", "a well-to-do man")])
import vlm_reader
_ask = vlm_reader.ask
vlm_reader.ask = lambda image, prompt, max_tokens=0: "14 Kohoutek's brilliant pre-decessor (7, 5)"
check("the VLM's column and pick readings have a line end's hyphen joined",
      ["14 Kohoutek's brilliant predecessor (7, 5)", "14 Kohoutek's brilliant predecessor (7, 5)"],
      [vlm_reader.read(None), vlm_reader.pick_in(None, "14-across", [])])
vlm_reader.ask = _ask
got, _ = ocr_clues.reconcile({"8-down": ("Odd minorities can with right bring counter-charges", "14", None)},
                             ["8 Odd minorities can with right bring counter-charges\n(14)"] * 2)
check("an OCR reading's hyphen inside a line is the print's own", "Odd minorities can with right bring counter-charges",
      got["8-down"][0])
check("a 1 standing as a word inside a clue is an I", "in letter I posted (4)", ocr_clues.clean("in letter 1 posted (4)"))
check("a 1 naming a light stays", ["see 1 down", "Cross 1 and 2 (5)", "in 1 Across (4)", "in 1982 film"],
      [ocr_clues.clean(t) for t in ("see 1 down", "Cross 1 and 2 (5)", "in 1 Across (4)", "in 1982 film")])
check("a lone I some reading lacks is a speck", ["Turn on at length an item", "Turn on at length an item"],
      [ocr_clues.agree("Turn on at length an item", [ocr_clues.marked(t, breaks=True) for t in (
           "8 Turn on at length 1 an item (6)", "8 Turn on at length 1 an item (6)", "8 Turn on at length an item (6)")])[0],
       ocr_clues.agree("Turn on at length I an item", [ocr_clues.marked(t, breaks=True) for t in (
           "8 Turn on at length an item (6)", "8 Turn on at length an item (6)", "8 Turn on at length I an item (6)")])[0]])
check("a lone I every reading has stands", "in letter I posted",
      ocr_clues.agree("in letter I posted", [ocr_clues.marked(ocr_clues.clean("8 in letter 1 posted (6)"), breaks=True)] * 3)[0])
got, blank = ocr_clues.reconcile({"1-down": ("Unusual way over the mountains", "7", None)},
                         ["25 Vanquished (8)\nDOWN\nI Unusual way over the mountains (7)"] * 2)
check("the DOWN heading over 1 down is no lost word of it", "Unusual way over the mountains", got["1-down"][0])
check("a heading read badly is still the heading; a stray capital word is not",
      ["DOWN", "DOWN", "ACROSS", None, None],
      [f.heading_of(t) for t in ("DOW'N", "DOIN", "AROSS", "Down in", "SOLUTION")])
check("a line starting a lower-case down carries on the line before", "9 Engineer tbe break down (8).\n10 Next (4)",
      f.tidy("9 Engineer tbe break\ndown (8).\n10 Next (4)"))
check("a possessive of a dictionary word is a word", True, ocr_clues.is_word("Lear's") and ocr_clues.is_word("bookie's"))

# The solution grid's blocks: a heavy print's block flecked with paper is a
# block; a light whose letter is fat is not.
import numpy as np, trove_solution_ocr as tso
rng = np.random.default_rng(1)
gray = np.full((300, 300), 255, np.uint8)
for k in range(6):
    gray[k * 60:k * 60 + 6, :] = 0
    gray[:, k * 60:k * 60 + 6] = 0
gray[60:120, 60:120] = 0
fleck = rng.random((60, 60)) < 0.15
gray[60:120, 60:120][fleck] = 255           # the block: 15% white flecks
gray[130:170, 140:160] = 0                  # a fat letter in the light at (2, 2)
gray[130:150, 125:175] = 0
gray = np.where(gray == 0, rng.integers(0, 40, gray.shape), rng.integers(200, 256, gray.shape)).astype(np.uint8)
grid5 = [".....", ".#...", ".....", ".....", "....."]
check("a flecked block read as a block, a fat letter's light as a light", 1.0,
      tso.block_agreement(gray, grid5, (0, 0, 60, 60)))

# improves(): a reading replaces a file this tool filed when it beats it.
pz = Path(os.environ["TMP"]) / "pz"; pz.mkdir()
def p3(texts, acq=f.TOOL):
    return {"source": {"acquiredBy": acq}, "dimensions": {"cols": 3, "rows": len(texts)},
            "entries": [{"number": i + 1, "direction": "across", "position": {"x": 0, "y": i}, "length": 3,
                         "clue": {"text": t}, "solution": None} for i, t in enumerate(texts)]}
(pz / "own.json").write_text(json.dumps(p3([""])))
(pz / "theirs.json").write_text(json.dumps(p3([""], "tools/acquire_book.py")))
(pz / "two.json").write_text(json.dumps(p3(["Top", "", ""])))
check("a fuller reading that blanks a clue the file has does not replace it", False,
      f.improves(p3(["", "Low", "Mid"]), pz / "two.json"))
check("a fuller reading replaces this tool's file, never another tool's or an equal one",
      [True, False, False], [f.improves(p3(["Top"]), pz / "own.json"),
                             f.improves(p3(["Top"]), pz / "theirs.json"),
                             f.improves(p3([""]), pz / "own.json")])

# expected_number(): a misdated item is caught, a dated one passes.
import datetime
check("numbers the dates imply, either side of the shutdown",
      [True, True, True, True, False],
      [abs(n - f.expected_number(datetime.date.fromisoformat(d))) <= f.NUMBER_SLACK
       for d, n in [("1974-05-02", 13677), ("1985-07-11", 16786), ("1995-01-03", 19742),
                    ("1998-07-25", 20853), ("1965-07-05", 20212)]])

# placed(): the edition's date fixes a misread number when its filed
# neighbours run unbroken, and refuses one out of date order (times-18873
# was read as 18879 between 18872 on Saturday and 18874 on Tuesday).
D = datetime.date.fromisoformat
held = {18872: D("1992-03-21"), 18874: D("1992-03-24")}
check("a number misread between unbroken neighbours files as the one its date fixes",
      (18873, None), f.placed(18879, D("1992-03-23"), held))
gap = {18872: D("1992-03-21"), 18880: D("1992-04-02")}
check("across a gap, a number out of date order is refused and one in order kept",
      [None, 18875], [f.placed(18890, D("1992-03-25"), gap)[0], f.placed(18875, D("1992-03-25"), gap)[0]])
check("a number filed for another day is refused",
      None, f.placed(18880, D("1992-03-25"), {18880: D("1992-04-02")})[0])
check("six issues a week, none on Sunday", [1, 6, 7], [f.issues_between(D("1992-03-21"), D("1992-03-23")),
      f.issues_between(D("1992-03-21"), D("1992-03-28")), f.issues_between(D("1992-03-21"), D("1992-03-30"))])

# lay_loose(): each clue alone on its own light; a misread count is not laid.
g = ["...", ".#.", "..."]
parsed = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                     {"tokens": [{3}], "text": "Bottom", "enums": {"5"}, "see": None}],
          "down": [{"tokens": [{1}], "text": "Left", "enums": {"3"}, "see": None},
                   {"tokens": [{2, 3}], "text": "Right", "enums": {"3"}, "see": None}]}
loose, bad = f.lay_loose(parsed, g)
check("clues laid on their own lights, a number read two ways on the one light it names; a wrong count not",
      ({"1-across": "Top", "1-down": "Left", "2-down": "Right"}, ["3-across"]),
      ({k: v[0] for k, v in loose.items()}, bad))

# A clue whose number was lost takes the one light its neighbours leave free.
g = ["...#...", ".......", "...#..."]
lost = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                   {"tokens": [set()], "text": "Lost", "enums": {"3"}, "see": None},
                   {"tokens": [{7}], "text": "Middle", "enums": {"7"}, "see": None},
                   {"tokens": [{8}], "text": "Low", "enums": {"3"}, "see": None},
                   {"tokens": [{9}], "text": "End", "enums": {"3"}, "see": None}],
        "down": []}
base = {"1-across": "Top", "7-across": "Middle", "8-across": "Low", "9-across": "End"}
check("a lost number laid between its neighbours only on the second pass, with every reading's numbered lights known",
      (base, {**base, "4-across": "Lost"}, {**base, "4-across": "Lost"}),
      tuple({k: v[0] for k, v in f.lay_loose(lost, g, *t)[0].items()} for t in ((), (set(),), ({"4-across"},))))

# Real readings whose list headings the OCR lost. The lists are put back
# where the clue numbers start rising again (file_trove_puzzles.heads).
# The Times, 1974-05-14, archive.org's reading: no ACROSS, and DOWN read
# "DORVN" (left out here: no heading at all).
times_13686 = """1 The sort of look to keEp a
pet in iuhpense ? |7).
5 Unconventionally mad sort
ot hcreen success (7).
9 No oao around for her (S).
10 Here's a Up i9>.
12 The poet has a donkey to gel
around 1 5).
15 Stress importance of tne
Tube (9).
25 Electrical effect of bringing
in the new vicar (9).
27 Unhappv Is the good man sei
aback by their cruelty (7).
2s Rose shade in ballet (7).
1 Are they too sweet to be
taken seriously? (?l-
2 Only two ducks in the team
of ISO It seems i4. 51-
3 Dog calls for silence 1 51. _
5 Fed np with getting dates
wrong (5).
6 Rare set-up for creating
openings (9).
14 Do they make for perfection
in the Health Service ? f9>*
16 Doctor Border's bed-clearing
operations (9)."""
p, why = f.parse(times_13686)
check("both headings lost: across runs 1 to 28 (read '2s'), down from 1 to 16 (split from 14, whose count reads 'f9>*')",
      ([{1}, {25, 28}], [{1}, {16}]),
      p and ([p["across"][0]["tokens"][0], p["across"][-1]["tokens"][0]],
             [p["down"][0]["tokens"][0], p["down"][-1]["tokens"][0]]) or why)
# The Times, 1974-05-04, archive.org's reading: ACROSS kept, DOWN lost
# along with 2-down's number. DOWN goes back before "3 Norfolk"; the
# unnumbered lines stay with 27-across, for the vote to cut.
import file_trove_puzzles as ftp
times_13679 = """ACROSS
1 Succeed In &«?mns apple, one
over ten feet f4. 4i-
24 Deceive lover with a torch
(81-
25 Article with two points gives
penetration (6L
27 However doctored tapes are
. distinct (81-
honoured "TOSeS
• whh Russell, an old Greek
(7J- .
3 Norfolk town lo register as !
nonconformist (91. I
4 Smuggled Benedictine — J
that’s Irregular <6i.
S Etisineer MP’S recall iSI.
7 After ten maybe drink makes
one weave about f7j."""
check("DOWN lost: put back where the numbers fall from 27 to 3",
      "(7J- .\nDOWN\n3 Norfolk town lo register as !",
      "\n".join(ftp.heads(times_13679.splitlines())[11:14]))
# 1984-01-02, RapidOCR: the grid's crop took ACROSS; DOWN is there.
times_16324 = """1 Meaningless sounds occur in nis
brig. perhaps (9).
6 Sciled opinion of an intelligent
judge (5).
9 Miss Wickfield(5).
10 Chichcsier. cg.or parts of
Cathy's island (9).
DOWN
1 A changc. mabe, for this
soldier?(9).
2 Ecccnirc bom an unknown
place (6)."""
check("ACROSS lost: put back before the first numbered line", "ACROSS",
      ftp.heads(times_16324.splitlines())[0])
check("a lone run of numbers gets no heading made up", ["1 One (3)", "2 Two (3)", "3 Three (5)"],
      ftp.heads(["1 One (3)", "2 Two (3)", "3 Three (5)"]))
# A speck or star before the first number after a heading (1977-01-08,
# 1985-01-02): the number still leads the clue.
check("a speck or star before a clue's number is not text",
      ["DOWN", "1 Miss Write's worried about everything (5)", "1 Land of Hope and—(7)"],
      f.tidy("DOWN\n. 1 Miss Write's worried about everything (5)\nDOWN\n*1 Land of Hope and—(7)")
      .splitlines()[:2] + f.tidy("DOWN\n*1 Land of Hope and—(7)").splitlines()[1:])

# A misread number ("74" for 4) or the list's lost last number: the clue
# takes the light its laid neighbours leave, when its count fills it; a
# clue that ran into the next ("(7) 9 Two") never does.
g = ["...#...", ".......", "...#..."]
mis = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                  {"tokens": [{74}], "text": "Misread", "enums": {"3"}, "see": None},
                  {"tokens": [{7}], "text": "Middle", "enums": {"7"}, "see": None},
                  {"tokens": [{8}], "text": "Low", "enums": {"3"}, "see": None},
                  {"tokens": [set()], "text": "End", "enums": {"3"}, "see": None}],
       "down": []}
check("a misread number and a lost last one laid by the grid's numbering",
      {"1-across": "Top", "4-across": "Misread", "7-across": "Middle", "8-across": "Low", "9-across": "End"},
      {k: v[0] for k, v in f.lay_loose(mis, g, set())[0].items()})
mis["across"][1]["text"] = "Misread (7). 9 Two clues"
check("a run-on clue is not laid by position", False,
      "4-across" in f.lay_loose(mis, g, set())[0])

# Short last line: "turn (6)" under a line whose box overhangs it is kept;
# a second copy of the line is not.
rows = f.merge_rows([(4264, 4302, 2279, 2590, "3 The friends got sea sick in"), (4286, 4315, 2303, 2382, "turn (6)"),
                     (4266, 4300, 2280, 2588, "3 The friends got sea sick in"), (4270, 4290, 2250, 2270, "5")])
check("a short line under an overhanging box kept, a copy dropped, a number beside joined",
      ["5 3 The friends got sea sick in", "turn (6)"], [r[4] for r in rows])

# A comma one reading lacks costs less than a word: the words after it pair.
others = [ocr_clues.marked(ocr_clues.clean(t), breaks=True) for t in ("27 Only. 28 A leisurely drink, doubtless, inside (8) 29 The",
                                                      "28 A leisurely drink, doubtless, inslde (8) 29 The")]
check("a lost comma put back, not the clue's end lost", "A leisurely drink, doubtless, inside",
      ocr_clues.agree("A leisurely drink, doubtless inside", others)[0])
check("a word split at a line end joined again; two words are not", (["people", "tastefully", "dressed"], ["lots", "of", "fish"]),
      (ocr_clues.rejoin(["people", "taste", ",", "fully", "dressed"], ["tastefully"]),
       ocr_clues.rejoin(["lots", "of", "fish"], ["offish"])))

laid = {"1-across": ("Bottom of a ship", "3", None), "2-across": ("Bottom of a ship", None, None),
        "3-across": ("Smoothed it 18 Warning of one", "7", None), "4-down": ("See 1", None, None),
        "5-down": ("s about a ship", "3", None)}
got, blank = ocr_clues.reconcile(laid, "Bottom of a ship (3)")
check("a clue without a count, holding another clue's number, or starting mid-clue filed blank; See kept",
      ({"1-across": "Bottom of a ship", "2-across": "", "3-across": "", "4-down": "See 1", "5-down": ""},
       ["2-across", "3-across", "5-down"]),
      ({k: v[0] for k, v in got.items()}, sorted(blank)))

# edition_dirs(): the years in turn, so a capped run reaches every decade.
cache = Path(os.environ["TMP"]) / "cache"
for item, eds in (("NewsUK1974UKEnglish", ["1974-05-01_1", "1974-05-02_2"]),
                  ("NewsUK1990UKEnglish", ["1990-01-02_3"]), ("FinancialTimes1975UKEnglish", ["1975-01-01_4"])):
    for e in eds:
        (cache / item / e).mkdir(parents=True)
        (cache / item / e / "pages.json").write_text("{}")
check("editions taken a year at a time, the FT left out", ["1974-05-01_1", "1990-01-02_3", "1974-05-02_2"],
      [d.name for d in f.edition_dirs(cache)])
check("the FT's editions are the FT phase's, and their paper is the FT",
      (["1975-01-01_4"], "ftcryptic", "times"),
      ([d.name for d in f.edition_dirs(cache, f.FT)], f.paper_of(cache / "FinancialTimes1975UKEnglish" / "x").series,
       f.paper_of(cache / "NewsUK1990UKEnglish" / "x").series))

# The FT: "CROSSWORD" over "No. 8,650 Set by DANTE" (1990s), one line in the
# 1970s; "Solution 8,650", or "SOLUTION TO PUZZLE" over "No. 2,765".
titles, sols = f.ft_headings([line("CROSSWORD", 2429, 2957), line("No. 8,650 Set by DANTE", 2417, 3017),
                              line("Solution 8,649", 2691, 3958),
                              line("Solution to Saturday's prize puzzle on Saturday January 14.", 2253, 4293),
                              line("No. 1,234 reasons to buy", 900, 100)])
check("1990s FT title over its number line, setter read, box the grid's width; prize-date line no heading",
      ([(8650, "Dante", f.FT_GRID_SPAN)], [8649]),
      ([(n, s, b[2] - b[0]) for n, b, s in titles], [n for n, _ in sols]))
check("a byline our files or the dictionary know stands without a second reading", ["Dante", "Vixen", None],
      [f.byline(None, {"setterRead": "Dante"}), f.byline(None, {"setterRead": "Vixen"}), f.byline(None, {})])
titles, sols = f.ft_headings([line("F.T. CROSSWORD PUZZLE No. 2,766", 200, 2841),
                              line("SOLUTION TO PUZZLE", 573, 4049), line("No. 2,765", 656, 4073)])
check("1970s FT title on one line, solution number on the line under", ([2766], [2765]),
      ([n for n, _, _ in titles], [n for n, _ in sols]))
check("FT numbers the dates imply, and our first ftcryptic's", [True, True, True, False],
      [abs(n - f.ft_expected_number(datetime.date.fromisoformat(d))) <= f.NUMBER_SLACK
       for d, n in [("1975-05-01", 2766), ("1992-06-11", 7870), ("2009-11-12", 13232), ("1995-01-03", 19742)]])

# The Guardian: "Guardian Crossword No 20,538" over "Set by Rufus" (1990s),
# "CROSSWORD 17,101" (1980s); the solution label under its grid; the Quick
# crossword's title is not the cryptic's.
titles, sols = f.guardian_headings([line("Guardian Crossword No 20,538", 1942, 3103), line("Set by Rufus", 1942, 3155),
                                    line("□□ CROSSWORD SOLUTION 20^537", 2592, 3510),
                                    line("CROSSWORD 17,101", 200, 900), line("QUICK CROSSWORD No. 4,575", 200, 200)])
check("Guardian titles with the setter under, the solution label with a comma read as ^, no Quick",
      ([(20538, "Rufus"), (17101, None)], [20537]), ([(n, s_) for n, _, s_ in titles], [n for n, _ in sols]))
check("a solution label whose number is misread is the page's one title's previous puzzle", [20926],
      [n for n, _ in f.guardian_headings([line("Guardian Crossword No 20,927", 1942, 3103),
                                          line("□□ CROSSWORD BOLUTION 20^27", 2592, 3510)])[1]])
check("the Guardian's editions file as cryptic, numbered as the feed's",
      ("cryptic", [True, True, True]),
      (f.paper_of(cache / "TheGuardian1996UKEnglish" / "x").series,
       [abs(n - f.guardian_expected_number(datetime.date.fromisoformat(d))) <= 5
        for d, n in [("1971-03-16", 12748), ("1996-01-02", 20538), ("1998-04-03", 21239)]]))
# Three columns: the third right of the grid from under the solution grid
# (its foot at 3530, its label 15px under);
# a speck left of the grid's margin and the imprint after "Solution
# tomorrow" (however misread) are not clues; "Across" in title case heads.
grid = (1954, 3263, 2586, 3865)
lines = [line("m", 1916, 3880), line("Across", 1957, 3880), line("1,4 Ancient patriarch (6,8)", 1973, 3909),
         line("Down", 2284, 3880), line("1 Called once (4,4)", 2284, 3909),
         line("20^39", 2700, 3545), line("10 Hell of a clue for Pi! (10,3)", 2617, 3726),
         line("22 Fishy drawing (5)", 2617, 3760), line("Soiuton tamorrow", 2617, 3790),
         line("Published by Guardian Newspapers", 2617, 3812)]
check("Guardian columns: left, right, then right of the grid; specks, label and imprint left out",
      "Across\n1,4 Ancient patriarch (6,8)\nDown\n1 Called once (4,4)\n10 Hell of a clue for Pi! (10,3)\n22 Fishy drawing (5)",
      f.column_text(f.columns(lines, grid, (f.GUARDIAN_THIRD, 3530 + f.LABEL_DROP), 15)))
check("a linked clue's numbers read, commas and 'dn' not taken for clue numbers",
      [[{1}, {4}], [{10}, {9}], [{26}, {27}, {14}], [{4}]],
      [c["tokens"] for c in f.parse("Across\n1,4 Ancient (6,8)\n10,9dn I am (4,10,3)\n"
                                    "26,27,14dn That which (10,4,7)\nDown\n4 See 26 ac\n6 Bound (6)")[0]
       ["across"] + f.parse("Across\n1 A (3)\nDown\n4 See 26 ac\n6 Bound (6)")[0]["down"][:1]])
check("a clue's opening A run into its next word split; a word, or a commoner word misspelt, kept",
      "15 A danger out east (5)\n3 Abed (4)\n4 Arived (7)", f.tidy("15 Adanger out east (5)\n3 Abed (4)\n4 Arived (7)"))
check("rn read as m mended", True, "carnivore" in ocr_clues.edits("camivore"))
g = ["...#...", "...#...", "......."]
pz = f.build(20540, datetime.date(1996, 1, 4), g, "image",
             {"1-across": ("Ancient patriarch", "3,3", ["1-across", "4-across"])}, "TheGuardian1996UKEnglish", 15,
             series="cryptic", name="Cryptic crossword No {:,}".format(20540))
check("a linked light the paper prints no clue for reads 'See 1'", "See 1",
      next(e["clue"]["text"] for e in pz["entries"] if (e["number"], e["direction"]) == (4, "across")))

# match_canberra(): the reading sharing the clue list, printed first, same grid.
def puzzle(pid, date, clues, cols=3):
    return {"id": pid, "date": date, "dimensions": {"cols": cols, "rows": 3},
            "entries": [{"number": i + 1, "direction": "across", "position": {"x": 0, "y": i},
                         "length": cols, "clue": {"text": t}} for i, t in enumerate(clues)]}
words = [chr(97 + i // 26) + chr(97 + i % 26) + "x" for i in range(30)]
clues = [" ".join(words[k * 10:k * 10 + 10]) for k in range(3)]
src = Path(os.environ["TMP"]) / "src"; src.mkdir()
(src / "times-13677.json").write_text(json.dumps(puzzle("times-13677", "1974-05-02", clues)))
(src / "times-13678.json").write_text(json.dumps(puzzle("times-13678", "1974-05-03", ["quite other words here and there", "x y z", "q r s"])))
can = Path(os.environ["TMP"]) / "canberra"; (can / "1975").mkdir(parents=True)
misread = [clues[0].replace("abx", "abz"), clues[1], clues[2]]
(can / "1975" / "canberra-750101.json").write_text(json.dumps(puzzle("canberra-750101", "1975-01-01", misread)))
(can / "1975" / "canberra-750102.json").write_text(json.dumps(puzzle("canberra-750102", "1975-01-02", clues, cols=4)))
(can / "1973").mkdir()
(can / "1973" / "canberra-730101.json").write_text(json.dumps(puzzle("canberra-730101", "1973-01-01", clues)))
import io
got = f.match_canberra(src, write=False, out=io.StringIO(), canberra=can)
check("a reprint matched through a misread; another grid, or a print before the London one, is not", {"canberra-750101": "times-13677"}, got)
(src / "times-13679.json").write_text(json.dumps(puzzle("times-13679", "1974-05-04", clues)))
got = f.match_canberra(src, write=False, out=io.StringIO(), canberra=can)
check("two readings sharing the clue list alike name neither: the best must lead MATCH_LEAD times over", {}, got)

# read_solution(): the solution grid under its heading, answers keyed as
# trove_solution_ocr.fill() looks them up, nothing from a grid of other blocks.
from PIL import Image, ImageDraw
ed = Path(os.environ["TMP"]) / "ed"; ed.mkdir()
im = Image.new("L", (1200, 1400), 255)
ImageDraw.Draw(im).rectangle((110, 160, 460, 510), fill=0)
im.save(ed / "leaf_0003.jpg")
f.CROPS = Path(os.environ["TMP"]) / "crops"
import trove_solution_ocr
seen = []
def fake(path, grid):
    seen.append(Image.open(path).size)
    return {(1, "across"): "ABC"}, {"blocks": stats_blocks}
trove_solution_ocr.read_answers = fake
sol = {"dir": ed, "leaf": 3, "number": 7, "box": (100, 100, 400, 140)}
stats_blocks = 1.0
got, _ = f.read_solution(sol, ["..."])
check("solution answers keyed as fill() reads them, the grid cropped tight at 3x",
      ({"1-across": "ABC"}, (352 * 3, 352 * 3)), (got, seen[0]))
stats_blocks = 0.9
got, info = f.read_solution(sol, ["..."])
check("a solution grid whose blocks are not the puzzle's gives no answers", ({}, True), (got, "refused" in info))

check("a complete puzzle goes to the corpus, with or without --out",
      [None, None], [f.destination("out", True), f.destination(None, True)])
check("a puzzle with a blank clue goes to --out or nowhere, never the corpus",
      ["out", False], [f.destination("out", False), f.destination(None, False)])
check("complete() is every clue having text, none with a made-up word", [True, False, False],
      [f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": "B"}}]}),
       f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": " "}}]}),
       f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": "Start trom Hint"}}]})])

import fetch_puzzle
ed_dir = Path(os.environ["TMP"]) / "runcache" / "NewsUK1990UKEnglish" / "1990-01-01_1"
ed_dir.mkdir(parents=True)
wrote = []
saved = (f.edition_dirs, f.scan, f.read_puzzle, f.input_hash, f.held_numbers,
         fetch_puzzle.puzzle_path, fetch_puzzle.write_puzzle_file)
f.edition_dirs = lambda cache, paper=None: [ed_dir]
f.scan = lambda d: {"date": "1990-01-01", "item": "NewsUK1990UKEnglish", "solutions": [],
                    "puzzles": [{"number": 18179, "leaf": 1, "box": None},
                                {"number": 18180, "leaf": 2, "box": None}]}
def fake_read(d, found, hit, solutions):
    blank = hit["number"] == 18179
    return {"number": hit["number"]}, {"id": f"times-{hit['number']}", "number": hit["number"],
            "entries": [{"clue": {"text": "Top"}}, {"clue": {"text": "" if blank else "Left"}}]}
f.read_puzzle = fake_read
f.input_hash = lambda d: "h"
f.held_numbers = lambda series="times": set()
fetch_puzzle.puzzle_path = lambda series, n: Path(os.environ["TMP"]) / "corpus" / f"times-{n}.json"
fetch_puzzle.write_puzzle_file = lambda path, puzzle, generator: wrote.append(path.parent.name + "/" + path.name)
rows = f.run(cache=ed_dir.parent.parent, puzzles=Path(os.environ["TMP"]) / "unfiled",
             source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"))
check("run files the complete puzzle in the corpus and the one with a blank clue in --out",
      ["unfiled/times-18179.json", "corpus/times-18180.json"], sorted(wrote, reverse=True))
wrote.clear()
rows = f.run(cache=ed_dir.parent.parent, ledger=Path(os.environ["TMP"]) / "l2.jsonl",
             source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"))
check("without --out a puzzle with a blank clue is written nowhere", ["corpus/times-18180.json"], wrote)
# One puzzle whose write raises is a verdict: the run files the rest, and
# its summary counts the failure.
import io
def failing_write(path, puzzle, generator):
    if puzzle["id"] == "times-18179":
        raise ValueError("times-18179 22-down: definition 'x' is not in the clue ''")
    wrote.append(path.parent.name + "/" + path.name)
wrote.clear()
fetch_puzzle.write_puzzle_file = failing_write
summary = io.StringIO()
rows = f.run(cache=ed_dir.parent.parent, puzzles=Path(os.environ["TMP"]) / "unfiled",
             ledger=Path(os.environ["TMP"]) / "l3.jsonl", source=Path(os.environ["TMP"]) / "src", out=summary)
failed = [v for r in rows for v in r["verdicts"] if v.get("writeFailed")]
check("a puzzle whose write raises is logged, counted and skipped; the rest are filed",
      (["corpus/times-18180.json"], [18179], True, True),
      (wrote, [v["number"] for v in failed], "is not in the clue" in failed[0]["writeFailed"],
       "1  write failed: ValueError" in summary.getvalue()))
(f.edition_dirs, f.scan, f.read_puzzle, f.input_hash, f.held_numbers,
 fetch_puzzle.puzzle_path, fetch_puzzle.write_puzzle_file) = saved

import cross_validate
a = cross_validate.ArchiveOrg()
check("archiveorg does not compare a file it filed with itself", [False, True],
      [a.covers({"source": {"acquiredBy": "tools/file_archive_org_puzzles.py"}}),
       a.covers({"source": {"acquiredBy": "tools/acquire_book.py"}})])
# A retrained Tesseract model gets its own cache name; RapidOCR's keep theirs.
model = Path(os.environ["TMP"]) / "m.traineddata"
saved = dict(ocr_clues.TESS_MODELS), dict(ocr_clues._MODEL_HASHES)
ocr_clues.TESS_MODELS["times"] = model
# The Telegraph: "No. 18,340 ACROSS" heads the left clue column, DOWN the
# right, the grid under both; "SOLUTION No. 18,339" over the last grid.
titles, sols = f.telegraph_headings([line("No. T8,338ACROSS", 168, 2517), line("Ko. 18.339 ACROSS", 217, 2492),
                                     line("No. 18-340ACROM", 210, 2335), line("SOLUTION No. 18,339", 991, 3698),
                                     line("QUICK CROSSWORD", 189, 3848), line("No. 12 Down Street", 900, 100)])
check("Telegraph titles however misread, the solution box the solution grid's width, no Quick",
      ([18338, 18339, 18340], [(18339, f.TELEGRAPH_SOLUTION_SPAN)]),
      ([n for n, _, _ in titles], [(n, b[2] - b[0]) for n, b in sols]))
check("the Telegraph's editions file as telegraph, numbered as the feed's",
      ("telegraph", "telegraph", [True, True]),
      (f.paper_of(cache / "TheDailyTelegraph1985UKEnglish" / "x").series,
       f.paper_of(cache / "SundayTelegraph1971UKEnglish" / "x").series,
       [abs(n - f.telegraph_expected_number(datetime.date.fromisoformat(d))) <= 5
        for d, n in [("1985-01-02", 18338), ("2009-02-07", 25846)]]))
check("a heading led by the puzzle's number, a zero read for O; a street name no heading",
      ["ACROSS", "ACROSS", None], [f.numbered_heading(t_) for t_ in ("No. 18.339ACR0SS", "No. T8,338ACROSS",
                                                                       "No. 12 Down Street")])
# Clues over the grid: split at the gutter, which the left column's long
# lines pass the grid's middle to reach; the right column overhangs the
# grid but ends before the next column's words; specks are no line.
grid = (200, 3100, 900, 3800)
lines = [line("No. 18,340ACROSS", 210, 2335), line("DOWN", 700, 2335),
         line("1 Plumber who puts on airs in", 215, 2365), line("Local", 570, 2365, ),
         line("trader providing people", 640, 2365), line("Lak", 935, 2365),
         line("Scotland (5)", 240, 2390), line("(8)", 600, 2390), line(", . .", 600, 2415)]
lines[3] = [(570, 2365, 620, 2381, "1"), (630, 2365, 680, 2381, "Local")]
top = 2325
split = f.gutter(lines, grid, top)
right = f.gutter(lines, grid, top, grid[2] - f.OVERHANG, grid[2] + f.OVERHANG)
check("gutter between the columns, right edge before the next column", (True, True),
      (520 <= split < 570, 866 <= right < 935))
check("clues-above columns: the title read as ACROSS, specks and the next column left out",
      "ACROSS\n1 Plumber who puts on airs in\nScotland (5)\nDOWN\n1 Local trader providing people\n(8)",
      f.column_text(f.columns(lines, grid, None, 15, (top, split, right))))
check("a 1 read as I or l at a clue's start, '<' for '(', specks after a count, a count left open at a list's end",
      "ACROSS\n1 A fruitful cause (5)\n17 More than two (5-8)\n29 Swallows (5)\nDOWN\n1 Some (5-\n4)",
      f.tidy("ACROSS\nIA fruitful cause <5)'\nI7 More than two (5-8).\n29 Swallows (5r\nDOWN\n1 Some (5-\n4)"))
g = ["...#...", "...#...", "......."]
laid, _ = f.lay_loose(f.parse("ACROSS\n1 & 4 Linked words (3,3)\nDOWN\n1 Down (3)")[0], g)
check("a linked clue laid on the lights its numbers name when one count fills them; the tail reads See",
      (("Linked words", "3,3", ["1-across", "4-across"]), "See 1"), (laid.get("1-across"), laid.get("4-across", ("",))[0]))
laid, _ = f.lay_loose(f.parse("ACROSS\n1 & 4 Linked words (7)\nDOWN\n1 Down (3)")[0], g)
check("a linked clue whose count does not fill its lights is not laid", None, laid.get("1-across"))
got, _ = ocr_clues.reconcile({"15-down": ("Entice Fortune, but provoke Nemesis? (5,4) - . 18 & 25 The point of", "9",
                                          ["15-down", "24-down"])},
                         ["15 & 24 Entice Fortune, but provoke Nemesis? (5,4)"], {"15-down": 5, "24-down": 4, "25-down": 5})
check("a run-on cut at the next clue; the count left inside ends the clue and is its count",
      ("Entice Fortune, but provoke Nemesis?", "5,4"), got["15-down"][:2])
check("text run in ahead of a clue's own number, with a number in it, is cut off",
      ["The point is there's a proposition", "One who acquires a farm building"],
      [ocr_clues.trimmed("The solution of Prize Puzzle No 18,178 will appear 26 The point is there's a proposition",
                         "26-across"),
       ocr_clues.trimmed("Tried to join paper 7. 4 Not fully understood 5 One who acquires a farm building", "5-down")])
check("a clue that prints its own number keeps it", "Like a don in trouble with Homer in 15 Down",
      ocr_clues.trimmed("Like a don in trouble with Homer in 15 Down", "15-across"))
check("a lone small i, a heading on 1 down and specks inside a line-end hyphen go",
      ["Religious system uniting man", "Poet's way to frame a line", "She reverts to foolish buying method",
       "One accepted as likewise a great artist"],
      [ocr_clues.trimmed(t, lid) for t, lid in (("Religious system i uniting man", "9-across"),
                                                ("Down i Poet's way to frame a line", "1-down"),
                                                ("She reverts to foolish buy- 4 ing method", "16-across"),
                                                ("One accepted as like- .wise a great artist", "19-down"))])
check("the newspaper i, a heading word in a later clue and a stutter stand",
      ["Showing true colours, posh editor supports this paper but not the i", "Across Aegean rain falls",
       "Gladly f-fib first"],
      [ocr_clues.trimmed(t, lid) for t, lid in (("Showing true colours, posh editor supports this paper but not the i",
                                                 "8-down"), ("Across Aegean rain falls", "21-across"),
                                                ("Gladly f-fib first", "21-across"))])
check("a broken count or symbols after the last word go; a percentage and a cross-reference stand",
      ["Girl named in a Lords amendment", "In memory of former days?", "Twice reduced by 50%", "Don't 23!"],
      [ocr_clues.trimmed(t, "5-down") for t in ("Girl named in a Lords amendment S).",
                                                "In memory of former days? &%S4),", "Twice reduced by 50%",
                                                "Don't 23!")])
got, blank = ocr_clues.reconcile({"1-across": ("19, we hear, in the crew", "5", None)},
                                 ["1 19, we hear, in the crew (5)"] * 2, {"1-across": 5, "19-across": 5})
check("a clue opening on another light's number is no lost opening", ("19, we hear, in the crew", {}),
      (got["1-across"][0], blank))
# Two clues run together win the vote when every reading runs them together
# the same way: the Times of 3 April 1985's 2 down and 1 May 1975's 28
# across filed as one clue each. Such a text is blanked, never filed.
merged_2d = "Where everybody goes in to sweep around the floor? 2 Seek fresh increases"
merged_28a = "Confused by a divine the Spanish backed (15) 2 Master of the Rolls surrounds aesthetic victim"
check("a voted clue with a clue number and another clue inside it is blanked",
      ({"2-down": ("", "8", None)}, {"2-down": "two clues run together"}),
      ocr_clues.reconcile({"2-down": (merged_2d, "8", None)}, [f"2 {merged_2d} (8)"] * 2, {"2-down": 8}))
check("a voted clue with a count and another clue after it is blanked",
      ({"28-across": ("", "6", None)}, {"28-across": "two clues run together"}),
      ocr_clues.reconcile({"28-across": (merged_28a, "6", None)}, [f"28 {merged_28a} (6)"] * 2, {"28-across": 6}))
check("numbers a setter writes are no merged clue", [None] * 7,
      [ocr_clues.merged(t) for t in ("Catch 22 Hero", "Over 18? Join", "Of the Vale, turn to Map 10 E",
                                     "Bird (4)", "Dad up to no good, scoffing (26) wild snappers?",
                                     "Massive commercial transaction? 3 Down!",
                                     "Halt opening exchange in No. 1 Court feature")])
check("two counts in one clue are two clues", "two clues run together",
      ocr_clues.merged("Harsh one (9) avoiding repetition (5) of"))
check("a clue cut at its own count when text follows it", ["Entice Fortune?", "Entice Fortune? (5,4)"],
      [ocr_clues.cut_at_count("Entice Fortune? (5,4) - 18 &", "5,4"), ocr_clues.cut_at_count("Entice Fortune? (5,4)", "5,4")])

# The desktop VLM's failures (Times heldout, VLM alone): a reading of another
# part of the page (No 20,989), a reading with every clue blank (No 19,742),
# and its pick's single-word misreads ("gain" for gait, "linner" for linnet).
g5 = ["....."] * 5
good = ("ACROSS\n1 Bird in a tree (5)\n6 Fish in the sea (5)\n7 Dog on a lead (5)\n"
        "DOWN\n1 Cat on a mat (5)\n2 Cow in a field (5)\n3 Hen in a coop (5)")
elsewhere = ("ACROSS\n1 Advantageous position not the first part (6,5)\n4 One accepted by Constable (7)\n"
             "12 Sounds like sort of horse (5)\nDOWN\n14 Encouragement after slipping (3-1-5)\n"
             "16 Improperly assigned to throne (2,3,4)")
same_slots = ("ACROSS\n1 Seize illegal drugs (5)\n6 Thoughts of leader (5)\n7 Tried to get editor (5)\n"
              "DOWN\n1 Again request harvest (5)\n2 Servant with carriage (5)\n3 Child looked after (5)")
kept, dropped = f.screened({"djvu": good, "ch": good.replace("tree", "trec"), "vlm": elsewhere}, g5)
check("a reading whose clues name no light of the grid with their count is dropped",
      (["ch", "djvu"], ["vlm"]), (sorted(kept), sorted(dropped)))
kept, dropped = f.screened({"djvu": good, "ch": good.replace("tree", "trec"), "vlm": same_slots}, g5)
check("a reading that fits the slots but disagrees with every other reading's clue of each number is dropped",
      ["vlm"], sorted(dropped))
kept, dropped = f.screened({"djvu": good, "ch": good, "vlm": "ACROSS\n1 (5)\n6 (5)\nDOWN\n1 (5)\n2 (5)"}, g5)
check("a reading with every clue blank is no reading", {"vlm": "no clue words"}, dropped)
kept, dropped = f.screened({"djvu": good, "vlm": "\n".join(good.splitlines()[:3] + ["DOWN"])}, g5)
check("a partial reading still votes: its clues lose to the others clue by clue", ({}, 2), (dropped, len(kept)))
got, _ = ocr_clues.reconcile({"21-across": ("Poet's", "6", None)},
                             ["21 Poet's uninteresting study (6)", "21 Poet's uninteresting study (6)"])
check("words a partial reading lost are put back from the others", "Poet's uninteresting study", got["21-across"][0])
check("a pick's real word no reading has, where every reading has one a letter off, takes theirs",
      "Walk the street unsteady gait", ocr_clues.held("Walk the street unsteady gain", ["Walk the street unsteady gait (6)"]))
check("a pick's non-word takes the lexicon word another reading has there",
      "For example, a linnet entangled in a bush",
      ocr_clues.held("For example, a linner entangled in a bush", ["For example, a linnet entangled in a bush (9)",
                                                                  "For exampie, a llnner entangled ia a bush"]))
check("a pick's non-word no reading has a lexicon word for fails the pick", "",
      ocr_clues.held("For example, a linner entangled in a bush", ["For example, a linner entangled in a bush (9)"]))
check("a pick that is another clue's text (No 20,989's 1 across read as 11 down) fails", "",
      ocr_clues.held("Advantageous position - not the first part of record?",
                     ["First issue in 1999, for example (5,6)"]))
laid, blank = ocr_clues.vlm_pick({"vlm": "x"}, {"13-across": ("", "9", None)}, {"13-across": "readings differ"},
                                 lambda t: ({"across": [{"tokens": [{13}], "text": "For example, a linner entangled",
                                                         "enums": {"9"}, "see": None}], "down": []}, None),
                                 lambda lid, cands: "For example, a linner entangled")
check("the VLM's pick of a non-word no reading corrects is not filed", ("", ["13-across"]),
      (laid["13-across"][0], sorted(blank)))

# Times 13,998 as an older reading filed it: the loose lay put 18 across's
# clue on 15 across too, where a misread number laid it, and 15 across's own
# clue ("An Athenian acted in any element", ANTIMONY) was lost.
laid_13998 = {"14-across": ("A man's man (if not hero's)", "5", None),
              "15-across": ("Occasional raid cops turn out for", "8", None),
              "18-across": ("Occasional raid cops turn out for", "8", None),
              "16-down": ("Picture by satellite has space problem", "9", None),
              "17-down": ("See 16", None, None), "19-down": ("See 16", None, None)}
laid, blank = f.one_light_each(laid_13998, {}, fits={"15-across", "18-across"})
check("one clue on two lights its count fills both: filed on neither, both read again (Times 13,998)",
      (["15-across", "18-across"], "", "", "A man's man (if not hero's)", "See 16"),
      (sorted(blank), laid["15-across"][0], laid["18-across"][0], laid["14-across"][0], laid["19-down"][0]))
laid, blank = f.one_light_each(laid_13998, {}, fits={"18-across"})
check("one clue on two lights its count fills one of: kept there, the other read again",
      (["15-across"], "", "Occasional raid cops turn out for"),
      (sorted(blank), laid["15-across"][0], laid["18-across"][0]))

# A held filing with one clue on two lights takes this reading's clue for
# each of them, blank where it has none; the rest of the file stands.
def held_13998(texts):
    return {"id": "times-13998", "source": {"acquiredBy": f.TOOL}, "dimensions": {"cols": 8, "rows": 3},
            "entries": [{"number": n, "direction": "across", "position": {"x": 0, "y": y}, "length": 8,
                         "clue": {"text": t, "enumeration": "8"} if t else {"text": "", "missing": True},
                         "solution": a}
                        for (n, y, a), t in zip([(14, 0, "VALETTTT"), (15, 1, "ANTIMONY"), (18, 2, "SPORADIC")],
                                                texts)]}
occasional = "Occasional raid cops turn out for"
path = Path(os.environ["TMP"]) / "times-13998.json"
path.write_text(json.dumps(held_13998(["A man's man", occasional, occasional])))
mended, now = f.mend_held(held_13998(["A man's man", "An Athenian acted in any element", occasional]), path)
check("a held clue on two lights takes this reading's clue for each, answers kept",
      (["A man's man", "An Athenian acted in any element", occasional], {"15-across": "An Athenian acted in any element", "18-across": occasional}, "ANTIMONY"),
      ([e["clue"]["text"] for e in mended["entries"]], now, mended["entries"][1]["solution"]))
mended, now = f.mend_held(held_13998(["A man's man", "", occasional]), path)
check("a light this reading has no clue for is filed blank", ("", True),
      (mended["entries"][1]["clue"].get("text", ""), mended["entries"][1]["clue"].get("missing")))
path.write_text(json.dumps(held_13998(["A man's man", occasional, occasional])))
mended, now = f.mend_held(None, path)
check("with no reading, each light a held clue sits on twice is blank", {"15-across": "", "18-across": ""}, now)
check("a held filing with no clue on two lights is left alone", None,
      f.mend_held(held_13998(["A man's man", "x", "y"]), path.write_text(json.dumps(
          held_13998(["A man's man", "An Athenian", occasional]))) and path))

# A refused held clue under an annotation (ftcryptic-9091 22 down): this
# reading's clue replaces it and the annotation, written against the old
# words, goes; with no clue read for it the held clue and its annotation
# stand, since check_rewrite refuses blanking a clue's words.
import copy, definitions, puzzle_integrity, puzzle_schema
held = held_13998(["A man's man", "Occasional raid 18 Cops turn out", "Sporadic"])
held["entries"][1]["annotation"] = {"definitions": [{"text": "Cops turn out", "at": 19}]}
held["source"]["retrievedFrom"] = "newspaper"
path.write_text(json.dumps(held))
mended, now = f.mend_held(held_13998(["A man's man", "An Athenian acted in any element", "Sporadic"]), path)
check("a held clue the filer now refuses takes this reading's clue, its annotation dropped",
      ({"15-across": "An Athenian acted in any element"}, None),
      (now, mended["entries"][1].get("annotation")))
check("a refused held clue no reading has is left alone, annotation and all", [None, None],
      [f.mend_held(None, path), f.mend_held(held_13998(["A man's man", "", "Sporadic"]), path)])
mended, now = f.mend_held(held_13998(["A man's man", "An Athenian acted in any element", "Sporadic"]), path)
flags = []
puzzle_integrity.check_rewrite(held, definitions.place_puzzle(puzzle_schema.prune(copy.deepcopy(mended))), flags)
check("a mended filing places its definitions and passes the rewrite check", [], flags)

check("a one read as l before a digit, and the space lost after a question mark, mended",
      "Worried? Pulse for a 19th-century school", ocr_clues.clean("Worried?Pulse for a l9th-century school"))

for body in (b"old", b"new"):
    model.write_bytes(body)
    ocr_clues._MODEL_HASHES.clear()
    check(f"reader_key hashes the model ({body.decode()})", True,
          ocr_clues.reader_key("times").startswith("times-"))
    if body == b"old":
        old_key = ocr_clues.reader_key("times")
check("a changed model changes the cache name", True, ocr_clues.reader_key("times") != old_key)
check("RapidOCR readers keep their name", "en5", ocr_clues.reader_key("en5"))
ocr_clues.TESS_MODELS.clear(); ocr_clues.TESS_MODELS.update(saved[0])
ocr_clues._MODEL_HASHES.clear(); ocr_clues._MODEL_HASHES.update(saved[1])

# Real page crops (tools/fixtures/archive-org-grids, cases.json gives each
# one's scan and title box): the grid is the one the title heads wherever it
# lies, whole.
from PIL import Image
fix = Path("fixtures/archive-org-grids")
cases = json.loads((fix / "cases.json").read_text())
def located(name):
    box, side = f.locate_grid(Image.open(fix / f"{name}.jpg"), cases[name]["title"])
    return side, f.grid_shaped(box), box
side, shaped, box = located("times-20117-below-far")
check("a grid further under its title than the first crop reaches is read whole (Times 20,117)",
      ("below", True, True), (side, shaped, abs((box[3] - box[1]) - (box[2] - box[0])) < 30))
side, shaped, box = located("times-17001-above")
check("a grid printed over its title is found (Times 17,001)", ("above", True), (side, shaped))
side, shaped, gbox = located("ftcryptic-8649-left")
check("a grid left of its title is found, not ink under the title (FT Monday Prize 8,649)",
      ("left", True), (side, shaped))
lines = [[tuple(w) for w in ws] for ws in cases["ftcryptic-8649-left"]["lines"]]
text = f.column_text(f.columns(lines, gbox, left=f.left_columns(lines, gbox)))
check("the clue columns left of the grid are read, across then down",
      (True, True), (text.startswith("ACROSS\nI Footwear"), "\nDOWN\n2 Fruit" in text))

side, shaped, box = located("times-16960-foot")
check("a grid box ends at the grid's foot frame, not under the ACROSS line touching it (Times 16,960)",
      ("below", 711), (side, box[3]))
side, shaped, box = located("times-16357-title")
check("a grid whose top frame reaches into its title's box is the title's grid (Times 16,357)",
      ("below", True), (side, shaped))

# Real clue readings (tools/fixtures/archive-org-clues: each edition's
# column texts as the readers read them and its scanned grid; times-16960
# also has RapidOCR's words and the grid box): the clue each reading spoils
# is filed whole.
import file_trove_puzzles as ftp
import reconstruct_grid as rg
clue_cases = json.loads(Path("fixtures/archive-org-clues/cases.json").read_text())
def readings_of(name):
    c = clue_cases[name]
    lengths = {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(c["grid"]).items()}
    return c["texts"], lengths
def parsed_of(name, reader):
    p, why = f.parse(clue_cases[name]["texts"][reader])
    assert p, why
    return {(n, d): c for d in ("across", "down") for c in p[d]
            for n in (c["tokens"][0] if len(c["tokens"][0]) == 1 else ())}
def voted(name, reader, lid, text, enum):
    texts, lengths = readings_of(name)
    return ocr_clues.reconcile({lid: (text, enum, None)}, [t for k, t in texts.items() if k != reader],
                               lengths)[0][lid][0]
check("a clue the print opens in lower case, every reading with its number before it, is filed (Times 15,122 13A)",
      "under twenty-one", voted("times-15122", "djvu", "13-across", "under twenty-one", "5"))
check("a clue opening on two cross-references is filed (Times 15,122 5D)",
      "3 3 on the watch", voted("times-15122", "djvu", "5-down", "3 3 on the watch", "5"))
check("a cross-reference read apart is one number where most readings have it (Times 16,376 19D)",
      "Agaric, maybe, confused with 15's first reformer",
      voted("times-16376", "djvu", "19-down", "Agaric, maybe, confused with 1 5's first reformer", "7"))
check("a cross-reference before \"I\" is no next clue run on (Times 16,357 16D)",
      "Removal of 25 I notice in distress outside",
      voted("times-16357", "ch", "16-down", "Removal of 25 I notice in distress outside", "8"))
d16960 = parsed_of("times-16960", "djvu")
check("a count read as a bracket and a digit on its own line ends its clue, the grid giving it (Times 16,960 20A)",
      ("What Ractatraw, in spite of all temptations, remained", set(), "Fine island, jolly compact"),
      (d16960[20, "across"]["text"], d16960[20, "across"]["enums"], d16960[21, "across"]["text"]))
check("a notice printed between two clues is in neither (Times 16,960 5D, 6D)",
      ("Be responsible for burning high church taper", "Peer inside the pearly gates"),
      (d16960[5, "down"]["text"], d16960[6, "down"]["text"]))
c = clue_cases["times-16960"]
text = f.column_text(f.columns([[tuple(w)] for w in c["chWords"]], tuple(c["gbox"])))
check("a line printed across both clue columns ends the column (Times 16,960)",
      (False, True), ("Collins" in text, "\nPeer inside the pearty gztes" in text))
d16626 = parsed_of("times-16626", "djvu")
check("\"Prize Crossword in\" between two clues is in neither (Times 16,626 3D, 4D)",
      ("Bones of little girl in centre of trail", "Of great significance to chaps in Missouri.all French"),
      (d16626[3, "down"]["text"], d16626[4, "down"]["text"]))
check("a count torn at a clue's end is read as its count: \"17).\", \"IS).\" (Times 16,626 5A, 19A)",
      (("Definitely the product of a writer", {"7"}), ("Souvenir exhibited by Kildare licensee", True)),
      ((d16626[5, "across"]["text"], d16626[5, "across"]["enums"]),
       (d16626[19, "across"]["text"], "5" in d16626[19, "across"]["enums"])))
check("a word split at a line end is joined where this clue misreads it by a letter (Times 16,626 20D)",
      "Half-clad and primitive, obviously",
      voted("times-16626", "djvu", "20-down", "Half-clad and primitive, obviousJy", "7"))
check("a speck read as a full stop gives way to the comma the other readings have (Times 16,626 4D)",
      "Of great significance to chaps in Missouri, all French",
      voted("times-16626", "djvu", "4-down", "Of great significance to chaps in Missouri.all French", "9"))
p, _ = f.parse(clue_cases["times-13683"]["texts"]["en5"])
p, _ = ftp.renumber(p)
nums = [next(iter(c["tokens"][0])) for c in p["across"] if len(c["tokens"][0]) == 1]
check("a clue number its list's order refuses is left for the grid to place (Times 13,683: 19 between 9 and 12)",
      (True, set()), (nums == sorted(set(nums)), next(c for c in p["across"] if c["text"].startswith("Man"))["tokens"][0]))

# Real page crops whose archive.org text has no crossword title
# (tools/fixtures/archive-org-titles; cases.json gives each one's scan, its
# paper and date, and the words our readers read in each title band, so no
# OCR runs here): the grid is found, the title read over or under it, and the
# number is the one its date implies.
import datetime
tfix = Path("fixtures/archive-org-titles")
tcases = json.loads((tfix / "cases.json").read_text())
band_words = f.band_words
for name, what in (("cryptic-21238", "Guardian 1998-04-02, its title over the grid's left"),
                   ("ftcryptic-9705", "FT 1998-06-11, its number line unread"),
                   ("ftcryptic-7869", "FT 1992-06-10, a column rule beside its title"),
                   ("times-19801", "Times 1995-03-13, its title 250px over the grid")):
    c = tcases[name]
    f.band_words = lambda img, band, which, path, c=c: [tuple(w) for w in c["bands"][",".join(map(str, band))][which]]
    paper, day = f.PAPERS[c["paper"]], datetime.date.fromisoformat(c["date"])
    got = f.ocr_titles(Image.open(tfix / f"{name}.jpg"), paper, day, name)
    want = int(name.split("-")[1])
    check(f"a title archive.org's text lacks is read by ours: {what}", ([want], True),
          ([t[0] for t in got], bool(got) and abs(got[0][0] - paper.expected(day)) <= f.NUMBER_SLACK))
f.band_words = band_words

# A grid at the page's top edge has a title band over it with no height
# (title_bands clips it to the page): it reads as no words, it does not
# stop the scan. No OCR runs: the band is empty before any reader sees it.
os.environ.pop("OCR_REMOTE", None)
page_img = Image.new("RGB", (400, 600), "white")
band = f.title_bands(page_img, (100, 0, 300, 200))[0]
check("a title band over a grid at the page's top edge has no height", 0, band[3] - band[1])
check("a band with no height reads as no words, not a crash", [],
      f.band_words(page_img, band, "times", Path(os.environ["TMP"]) / "band.json"))
check("an image with no width reads as no words", [], ocr_clues.read_words(Image.new("RGB", (0, 40)), "ch"))

# The desktop not answering: the crop is read here (None from ocr_remote),
# the reason logged, and no second attempt until RETRY has passed.
import contextlib, io, time
import ocr_remote
os.environ["OCR_REMOTE"] = "nobody@127.0.0.1"
ocr_remote.SSH = ocr_remote.SSH + ["-p", "1"]
ocr_remote.versions = lambda: {}
err = io.StringIO()
with contextlib.redirect_stderr(err):
    t = time.monotonic()
    first = ocr_remote.words(page_img, "ch")
    second = ocr_remote.words(page_img, "ch")
    took = time.monotonic() - t
check("a desktop that is off: read here, the reason logged, not retried at once, no hang",
      (None, None, True, True), (first, second, "unavailable (nobody@127.0.0.1: " in err.getvalue(), took < 30))
os.environ.pop("OCR_REMOTE")

print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_file_archive_org_puzzles: failed"; exit 1; }
echo "test_file_archive_org_puzzles: all passed"
