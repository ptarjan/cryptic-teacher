#!/usr/bin/env python3
"""clue_text: ACROSS/DOWN heading readings every old copy accepted."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import re
import clue_text as ct

# fuzzy (the old file_archive_org_puzzles copy)
for line, want in [("ACROSS", "ACROSS"), ("DOWN", "DOWN"), ("DOW'N", "DOWN"), ("DOIN", "DOWN"),
                   ("AROSS", "ACROSS"), ("Across", "ACROSS"), ("Down", "DOWN"), ("ACR0SS", "ACROSS")]:
    assert ct.heading_of(line) == want, (line, ct.heading_of(line))
for line in ("", "Across 1, 4", "the clues", "12 Forcing", "CLUES ACROSS AND DOWN"):
    assert ct.heading_of(line) is None, line
assert ct.numbered_heading("No. 18,340 ACROSS") == "ACROSS"
assert ct.numbered_heading("Ko. 18.339 ACROSS") == "ACROSS"
assert ct.numbered_heading("No. 18-340ACROM") == "ACROSS"
assert ct.numbered_heading("No. 18,340 DOWN") == "DOWN"
assert ct.numbered_heading("ACROSS") is None

# exact (andlit_azed HEADING, ft_pdf SECTION)
for line, want in [("Across", "ACROSS"), ("across", "ACROSS"), ("A C R O S S", "ACROSS"),
                   ("D0WN", "DOWN"), ("d o w n", "DOWN"), ("acr0ss", "ACROSS"), ("  Down ", "DOWN")]:
    assert ct.exact_heading(line) == want, (line, ct.exact_heading(line))
for line in ("Across 1, 4", "AROSS", "DOW'N", "CROSS", ""):
    assert ct.exact_heading(line) is None, line

# leading (file_trove_puzzles HEADING_RE)
m = ct.LEADING_HEADING.match("Clues Across: Foo (4)")
assert ct.direction(m.group(2)) == "across" and "Clues Across: Foo (4)"[m.end():] == "Foo (4)"
assert ct.direction(ct.LEADING_HEADING.match("DOWN").group(2)) == "down"
assert ct.direction(ct.LEADING_HEADING.match("D0WN 1 x").group(2)) == "down"
assert not ct.LEADING_HEADING.match("Acrossword")

# DIRECTION (parse_penguin_book): repeated letters
import re
for w in ("ACROSS", "DOwNn", "AAcross", "D0WN"):
    assert re.fullmatch(ct.DIRECTION, w, re.I), w

# counts: torn, S for 5, I/l for 1 (file_archive_org_puzzles COUNT_END/TORN_COUNT/counts_mended,
# archive_org_listener RUN_ON)
for line, want in [("writer 17).", "writer (7)"), ("a clue (8", "a clue (8)"), ("a clue (5X", "a clue (5)"),
                   ("a clue T10", "a clue (10)"), ("a clue I6l", "a clue (6)"), ("a clue (S", "a clue (S)"),
                   ("a clue (7)", "a clue (7)"), ("a clue (3,7).", "a clue (3,7)."),
                   ("a clue 12)", "a clue 12)"), ("a clue 12l", "a clue 12l"), ("no count", "no count")]:
    assert ct.mend_count(line) == want, (line, ct.mend_count(line))
assert ct.is_count_end("a clue (S).") and ct.is_count_end("a clue (l0)") and not ct.is_count_end("a clue (8")
assert ct.COUNT_END.search("a clue (8") and ct.COUNT_END.search("a clue (3,7)") and not ct.COUNT_END.search("a clue")
assert ct.COUNT_INSIDE.search("saint? (S) 27 Can a farm") and not ct.COUNT_INSIDE.search("a clue (5)")
assert ct.COUNT_INSIDE.search("a (l0) b")

# cross-references (archive_org_listener tidy, privateeye_wayback)
for text, want in [("SeeI3.", "See 13."), ("See 13", "See 13"), ("See13", "See 13"), ("(seel3ac)", "(see 13ac)"),
                   ("(see13)", "(see 13)"), ("(see l3 ac)", "(see 13 ac)"), ("see you", "see you"),
                   ("foresee3", "foresee3")]:
    assert ct.see_numeral(text) == want, (text, ct.see_numeral(text))

# numerals
assert ct.as_digits("I3") == "13" and ct.as_digits("lO") == "10" and ct.as_digits("4S") == "45"
assert ct.as_digits("4S", s="8") == "48"
print("ok")

# shared by ocr_clues and file_archive_org_puzzles
assert ct.HEADING_LINE.sub("0", "Clues Across:\n1 Fish (4)\nD0WN\nDOWNN") == "0\n1 Fish (4)\n0\n0"
assert ct.HEADING_LINE.search("Across the board") is None
assert ct.CAPS_HEADING.search("on the DOWN board") and not ct.CAPS_HEADING.search("Down the hatch")
assert not ct.CAPS_HEADING.search("DOWNING")
m = ct.HEADING_BEFORE_ONE.match("Down i Beginning")
assert ct.direction(m[1]) == "down" and "Down i Beginning"[m.end():] == "Beginning"
assert ct.HEADING_BEFORE_ONE.match("ACROSS 1 Fish") and ct.HEADING_BEFORE_ONE.match("across 1 Fish")
assert ct.HEADING_BEFORE_ONE.match("D0WN l Fish")
assert not ct.HEADING_BEFORE_ONE.match("Across 1, 4")
assert ct.HEADING_AFTER_COUNT.search("chance (5) DOWN")[1] == "DOWN"
assert ct.ones_read("l9th-century and I3 more, still it") == "19th-century and 13 more, still it"
assert ct.strip_count("hair (8)") == "hair" and ct.strip_count("hair (8") == "hair"
assert ct.strip_count("writer 17).") == "writer" and ct.strip_count("two words (3,4).") == "two words"
assert ct.strip_count("Fish (S)") == "Fish" and ct.strip_count("no count") == "no count"
assert ct.is_stray_count("U0).") and ct.is_stray_count("5).") and not ct.is_stray_count("a word (5)")
assert ct.heading_of("AcRoss") == "ACROSS" and ct.heading_of("dOwN") == "DOWN"
assert ct.heading_of("acr0ss") == "ACROSS" and ct.heading_of("A C R O S S") == "ACROSS"
import re

# --- round 2: counts, numerals, torn brackets
assert ct.SEE_RE.match("See 13") and ct.SEE_RE.match("see 5 down") and not ct.SEE_RE.match("Seeing 13")
assert ct.number_digits("T8,339") == 18339 and ct.number_digits(" l8-340") == 18340 and ct.number_digits("18,340") == 18340
assert ct.NUMBER_LETTERS["8"] == "sb" and ct.DIGIT_LETTERS["1"] == "ilt" and "j" in ct.FIGURE_LETTERS
assert ct.COUNT_OPENS == "ijlft" and ct.COUNT_CLOSES == "ijl"
assert ct.LIGHT_WORD.match("Across") and ct.LIGHT_WORD.match("dn ") and not ct.LIGHT_WORD.match("acrobat")
assert ct.NUMBERED_IN.search("Poles 22 Affected by") and ct.NUMBERED_IN.search("Saturday 26 The point")
assert not ct.NUMBERED_IN.search("see 9 Across") and not ct.NUMBERED_IN.search("on 5 November")
assert re.search(ct.NEXT_CLUE, "floor? 2 Seek") and not re.search(ct.NEXT_CLUE, "in 1 Down it")
assert re.fullmatch(ct.COUNT_IN, "(3-2)") and re.fullmatch(ct.COUNT_IN, "(5,4)") and not re.fullmatch(ct.COUNT_IN, "(S)")
assert ct.PAGE_TEXT.search("Concise crossword, page 22") and ct.PAGE_TEXT.search("Prize Puzzle No 18,178")
assert ct.PAGE_TEXT.search("spotty (6. The solution") and ct.PAGE_TEXT.search("outs (5 _ Concise")
assert not ct.PAGE_TEXT.search("one (2 Hen. IV) here")
assert ct.cut_at_count("spotty (6. The solution", "6") == "spotty"
assert ct.cut_at_count("Entice Fortune? (5,4) - 18 &", "5,4") == "Entice Fortune?"
assert ct.cut_at_count("Entice Fortune? (5,4)", "5,4") == "Entice Fortune? (5,4)"
assert ct.cut_at_count("none (3) x", "") == "none (3) x" and ct.cut_at_count(None, "3") is None
assert ct.count_read("151", "5") and ct.count_read("15", "5") and not ct.count_read("17", "5")
assert ct.count_left("Song of joy 141", 4, {1}) == "Song of joy"
assert ct.count_left("restaurant? 15-41", 9, {1}) == "restaurant?"
assert ct.count_left("See 15", 5, {1, 15, 21}) is None and ct.count_left("it is 8s", 8, {1}) is None
assert ct.count_left("Mercenary backing Channel 5", 5, {5, 10}) is None
assert ct.count_left("Compare with a man who is under 51", 5, {5, 15}) == "Compare with a man who is under"
assert ct.count_closed("some hair 8j") == "some hair (8)" and ct.count_closed("hair (8)'") == "hair (8)"
assert ct.count_closed("hair (3,4)._") == "hair (3,4)" and ct.count_closed("no count here") == "no count here"
assert ct.count_closed_open("a word (5r") == "a word (5)" and ct.count_closed_open("a word (5") == "a word (5)"
assert ct.count_closed_open("a word (5)") == "a word (5)"
# A linked head's long count torn over a line break at a comma (Gale 1955-07-01): one line, its spaces closed.
assert ct.torn_counts_joined(["interchanges (1, 4, 2,", "3, 6).", "10 He moves men in a"]) == \
    ["interchanges (1,4,2,3,6)", "10 He moves men in a"]
assert ct.torn_counts_joined(["A culinary result (4,", "2, 3, 5, 4, 2)."]) == ["A culinary result (4,2,3,5,4,2)."]
# Not a line that ends on a closed count, nor one whose next line is a clue's number and words.
for _lines in (["word (5, 4).", "3, 6)."], ["word (5,", "3 Clue words (6)."], ["word (5)", "6)."]):
    assert ct.torn_counts_joined(_lines) == _lines, _lines
# With the linked-clue mends off (a window's first read, fa._read_page): the lines as read, the join noted.
_was = ct.set_linked_mends(False)
assert ct.torn_counts_joined(["interchanges (1, 4, 2,", "3, 6)."]) == ["interchanges (1, 4, 2,", "3, 6)."]
assert ct.linked_missed() == 1
ct.set_linked_mends(_was)
assert ct.linked_mends() and ct.linked_missed() == 0
assert "(1,4,2,3,6)" in ct.tidy_ocr_clues("ACROSS\n1, 9 A revolutionary\nstory, with capital\ninterchanges (1, 4, 2,\n3, 6).\n"
                                          "10 He moves men in a\nbig way (10).")
# A count's 1 read as a lower-case i (Times 1974-12-07's "gatherer (i1)."): a two-figure group read 10-15.
assert ct.ones_in_count("gatherer (i1).") == "gatherer (11)." and ct.ones_in_count("a word (1i)") == "a word (11)"
assert ct.ones_in_count("a word (il)") == "a word (11)" and ct.ones_in_count("a word (4, i0)") == "a word (4, 10)"
assert ct.count_closed("gatherer (i1).") == "gatherer (11)" and ct.count_closed("gatherer (i1).", ones=False) == "gatherer (i1)."
# Not a lone i, a group past 15, another letter, a figure touching the bracket, or a count inside the line.
for _left in ("a word (i)", "a word (4, i)", "a word (i6)", "a word (ix)", "blotting7(i0).", "a (i1) word here",
              "a word (11)"):
    assert ct.ones_in_count(_left) == _left, _left
assert ct.clue_number_opening("I7 More") == "17 More" and ct.clue_number_opening("IA fruitful") == "1A fruitful"
assert ct.clue_number_opening(". 1 Miss") == "1 Miss" and ct.clue_number_opening("*1 Land") == "1 Land"
assert ct.clue_number_opening("IPheasant") == "1 Pheasant" and ct.clue_number_opening("JTool") == "1 Tool"
assert ct.clue_number_opening("!What makes") == "1 What makes" and ct.clue_number_opening("|What") == "1 What"
assert ct.clue_number_opening("1'In the") == "1 In the" and ct.clue_number_opening("1.Associate's") == "1 Associate's"
assert ct.clue_number_opening(") With") == "With" and ct.clue_number_opening("12 Fish") == "12 Fish"
# 11 read as ones-shaped letters (Gale Times 2000-14): opened as 11; the word "Ill" is left.
assert [ct.clue_number_opening(s) for s in ("ll1 Red", "ll At", "1l After", "IIl Flier", "II Flier", "!! Examine")] \
    == ["11 Red", "11 At", "11 After", "11 Flier", "11 Flier", "11 Examine"]
assert ct.clue_number_opening("Ill Will") == "Ill Will" and ct.clue_number_opening("ll after") == "ll after"
assert ct.HEADING_ALONE.match("ACROSS") and ct.HEADING_ALONE.match(" - Down.") and not ct.HEADING_ALONE.match("Across 1")
assert ct.PLAIN_HEADING.match("Across:").group(1) == "Across" and not ct.PLAIN_HEADING.match("Across 1")
assert ct.OPENING_NUMBER.match("25Recipient")[1] == "25" and ct.OPENING_NUMBER.match("21.Measures")[1] == "21"
assert ct.OPENING_NUMBER.match("l7 Fish")[1] == "l7" and ct.OPENING_SPECK.match("151 Meta-")[1] == "151"
assert ct.unpaired("is (this") == 3 and ct.unpaired("for ) record") == 4 and ct.unpaired("fine (ok)") is None
assert ct.unpaired("[9)") == 2
assert ct.trim_torn_count("hair-dresser (6") == "hair-dresser" and ct.trim_torn_count("a clue 0,6)") == "a clue"
assert ct.trim_torn_count("currency 1 7).") == "currency" and ct.trim_torn_count("a clue [5]") == "a clue"
assert ct.trim_torn_count(") The man") == "The man" and ct.trim_torn_count("a clue (5)") == "a clue (5)"
assert ct.trim_torn_count("a clue ( 8 .") == "a clue" and ct.trim_torn_count("plain words") == "plain words"

# shared by privateeye_scans, parse_bigdave44, parse_penguin_book, gale_listener, privateeye_wayback, ocr_clues
assert ct.count_total("3,7") == 10 and ct.count_total("4-4") == 8 and ct.count_total(None) == 0 and ct.count_total("") == 0
for ok in ("a clue (8)", "a clue (3,7).", "a clue (4-4)", "a clue (2 , 3)", "a clue (4–4)"):
    assert ct.PRINTED_COUNT.search(ok), ok
for bad in ("a clue (8", "a clue (S)", "(8) and more", "a clue (x)"):
    assert not ct.PRINTED_COUNT.search(bad), bad
assert ct.PUZZLE_HEADING.search("end (5) Alphabetical Jigsaw 1") and not ct.PUZZLE_HEADING.search("an alphabetical jigsaw (5)")
assert ct.HEADING_IN.search("Fish ACROSS 1 more") and ct.HEADING_IN.match("Down i Beginning") and not ct.HEADING_IN.search("going down (5)")
for line, want in [("| ACROSS", "ACROSS"), ("DOwNn", "DOWN"), ("DOWN i", "DOWN"), ("Cryptic Across", "ACROSS"),
                   ("CryBHE Across", "ACROSS"), ("- DOWN -", "DOWN")]:
    assert ct.tolerant_heading(line) == want, (line, ct.tolerant_heading(line))
for line in ("13. See 14 Across", "See Across", "Fish and chips (5)", "", "Acid"):
    assert ct.tolerant_heading(line) is None, line
assert ct.PLAIN_HEADING.match("Across clues:").group(1) == "Across" and ct.PLAIN_HEADING.match("  Down.").group(1) == "Down"
assert not ct.PLAIN_HEADING.match("Down to earth")
m = re.compile(ct.SEE_DIRECTED, re.I).search("(see 14 Across)")
assert m.groups() == ("14", "Across") and re.compile(ct.SEE_DIRECTED, re.I).search("See 3").group(2) is None
for word, want in [("II.", "11."), ("I.", "1."), ("4S.", "48."), ("Io,", "10,"), ("I3.", "13."), ("O.", "O."), ("S.", "S."),
                   ("12.", "12."), ("Foo", "Foo")]:
    assert ct.old_figures(word) == want, (word, ct.old_figures(word))
for text, want in [("| Picture of crack (8) 4S Fish", " 1 Picture of crack (8) 45 Fish"),
                   ("(5) 12T he cat (3)", "(5) 12 The cat (3)"), ("1/Sac Fish", "1/5ac Fish"),
                   ("15 Monument (4) 20ac.They", "15 Monument (4) 20ac. They"), ("(see13)", "(see 13)"),
                   ("13 (see 1dn) : 15 Monument", "13 (see 1dn) 15 Monument")]:
    assert ct.mend_scan_text(text).replace("  ", " ").strip() == want.strip(), (text, ct.mend_scan_text(text))
for text, want in [("20rev.,24.Charade:", "20 rev., 24. Charade:"), ("1.An African", "1. An African"),
                   ("29A town", "29 A town"), ("28.tNot far", "28. \u2020Not far"), ("29tA town", "29 \u2020A town"),
                   ("fA famous", "\u2020A famous"), ("12 Forcing", "12 Forcing"), ("tent", "tent")]:
    assert ct.mend_opening(text) == want, (text, ct.mend_opening(text))
assert ct.clue_number_opening("28.tNot far from 13 (5)") == "28. \u2020Not far from 13 (5)"
assert re.compile(ct.ENUM_COUNT).search("a clue (3 and 4) x").group() == "(3 and 4)"
for ok in ("(5)", "(3,4)", "(4-4 )", "(5.)", "(2/3)"):
    assert re.fullmatch(ct.ENUM_COUNT, ok), ok
for bad in ("(and)", "(x)", "(see 3)"):
    assert not re.fullmatch(ct.ENUM_COUNT, bad), bad
assert re.fullmatch(ct.ENUM_OR_SEE, "(see 14 across)") and re.fullmatch(ct.ENUM_OR_SEE, "(4-4)")
assert ct.mend_scan_text("a clue (6, two words) 7 Next") == "a clue (6) 7 Next"
assert ct.WORDS_COUNT.sub(r"(\1)", "end (3-2, three words)") == "end (3-2)"
assert ct.NEXT_NUMBER.search("clue (5) 7 Next") and not ct.NEXT_NUMBER.search("clue see 7 next")
assert ct.ELLIPSIS_HEAD.sub(r"\1 ... ", "5... the cat\n6 . stabbed") == "5 ... the cat\n6 ... stabbed"
# see_one / mend_link_tails (Cyclops 80, 103, 179)
assert ct.see_one("26 (see lac)") == "26 (see 1ac)" and ct.see_one("10 See I across.") == "10 See 1 across."
assert ct.see_one("See 3 across") == "See 3 across"
page = ["11/14 Link head (4,7)", "12 Plain (3)", "14 Own clue (5)", "15 See 11"]
assert ct.mend_link_tails(page) == ["11/4 Link head (4,7)", "12 Plain (3)", "14 Own clue (5)", "15 See 11"]
assert ct.mend_link_tails(["11/14 Link (4,7)", "14 See 11"]) == ["11/14 Link (4,7)", "14 See 11"]
assert ct.mend_link_tails(["11/14 Link (4,7)", "12 Plain (3)"]) == ["11/14 Link (4,7)", "12 Plain (3)"]
assert ct.mend_link_tails(["11, 14 Link (4,7)", "4 Other (3)", "14 Own (5)"]) == ["11, 14 Link (4,7)", "4 Other (3)", "14 Own (5)"]
# A head whose tail prints "(see 16)" has no clue of its own: 11 stays 11 (Cyclops 29, "16/1/11")
assert ct.mend_link_tails(["11 (see 16)", "16/1/11 Top (5,10)", "19 Next (5)"]) == ["11 (see 16)", "16/1/11 Top (5,10)", "19 Next (5)"]
import time
# Digit runs once sent STANDING_FIGURES into catastrophic backtracking (the old form hung on this for minutes).
for hang in ("word " + "1234567890" * 8 + "!", "word" + " 12345678901234567890" * 30 + " x"):
    t0 = time.time()
    ct.STANDING_FIGURES.search(hang)
    ct.count_left(hang, 10, {})
    assert time.time() - t0 < 0.1, hang
# ---- tidy_ocr_clues: the one pipeline (column / clue / piece scopes)
col = ct.tidy_ocr_clues("{ACROSS}\n1Mythical king {9}\n2 Talks [3,2]\nDOW'N\nl0 See l3. (4)")
assert col.splitlines()[0] == "ACROSS", col
assert "1 Mythical king (9)" in col and "2 Talks (3,2)" in col, col
assert col.splitlines()[-2:] == ["DOWN", "10 See 13. (4)"], col
# headings first: a heading read onto a clue's line is a line of its own
assert ct.tidy_ocr_clues("Down i Beginning (5)").splitlines()[:2] == ["DOWN", "1 Beginning (5)"]
assert ct.tidy_ocr_clues("chance (5) DOWN\n2 Next (4)").splitlines() == ["chance (5)", "DOWN", "2 Next (4)"]
# a number lost after a count is marked; a wrapped line is not
assert ct.tidy_ocr_clues("ACROSS\nNymph (8)") == "ACROSS\n? Nymph (8)"
assert ct.tidy_ocr_clues("10 Nurse holding\nNote (7)") == "10 Nurse holding\nNote (7)"
# counts: torn at a clue's end, set wide, "(6, two words)"
assert ct.tidy_ocr_clues("9 Leggy beatera T10\n12 Only about (4)") == "9 Leggy beatera (10)\n12 Only about (4)"
assert ct.tidy_ocr_clues("3 Deal (1 1)") == "3 Deal (11)"
assert ct.tidy_ocr_clues("3 Colonist (6, two words)") == "3 Colonist (6)"
# slips from the listener: a split number, an ellipsis head, a middle dot
assert ct.tidy_ocr_clues("1 9 Nurse (5)") == "19 Nurse (5)"
assert ct.tidy_ocr_clues("6 3 put more negatively (4)") == "6 3 put more negatively (4)"
assert ct.tidy_ocr_clues("5... the vice (4-3)") == "5 ... the vice (4-3)"
assert ct.tidy_ocr_clues("2 study·money (5)") == "2 study money (5)"
# joins: a linked head's tail one digit too many (14 opens a clue of its own)
assert (ct.tidy_ocr_clues("ACROSS\n11/14 Link (4,7)\n14 Own (5)\nDOWN\n3 x (3)")
        == "ACROSS\n11/4 Link (4,7)\n14 Own (5)\nDOWN\n3 x (3)")
# running heads and publisher heading words are the source's to ask for
assert ct.tidy_ocr_clues("Cryptic Across\n1 A (3)").splitlines()[0] != "ACROSS"
assert ct.tidy_ocr_clues("Cryptic Across\n1 A (3)", running_head=True).splitlines()[0] == "ACROSS"
assert ct.tidy_ocr_clues("HORIZONTAL\n1 A (3)", extra_headings={"HORIZONTAL": "ACROSS"}).splitlines()[0] == "ACROSS"
# idempotent: a text already tidied comes back as it was
for t in ("ACROSS\n1 Mythical king (9)\n? Nymph (8)\nDOWN\n2 Talks (3,2)", col):
    assert ct.tidy_ocr_clues(t) == t, t
# clue scope: one clue's text, count policy named by the caller
assert ct.tidy_ocr_clues("(see I3) the l9th-century", scope="clue", torn_counts=None) == "(see 13) the 19th-century"
assert ct.tidy_ocr_clues("hair (8", scope="clue") == "hair (8)"
assert ct.tidy_ocr_clues("a clue (1 1)", scope="clue", torn_counts=None) == "a clue (11)"
# piece scope: an OCR word alone
assert ct.tidy_ocr_clues("II.", scope="piece") == "11."
assert ct.tidy_ocr_clues("25Recipient", scope="piece") == "25 Recipient"
assert ct.tidy_ocr_clues("O.", scope="piece") == "O."
# line / lines / run scopes: a scan reader's own shapes, one line, one list, one run
assert ct.tidy_ocr_clues("IA clue {5)", scope="line") == "1A clue (5)" or ct.tidy_ocr_clues("IA clue {5)", scope="line").endswith("(5)")
assert ct.tidy_ocr_clues("hair (8", scope="line") == "hair (8)"
assert ct.heading_in("ACROSS") == "ACROSS" and ct.heading_in("hair (8)") is None
assert ct.tidy_ocr_clues(["1 A (3)"], scope="lines") == ct.mend_link_tails(["1 A (3)"])
assert ct.tidy_ocr_clues("1 A clue (3) 2 Another (4)", scope="run") == ct.mend_scan_text("1 A clue (3) 2 Another (4)")
# cells: figures after the last word that are its count misread go, unless no words would be left
assert ct.tidy_ocr_clues("Song of joy 141", scope="clue", cells=4) == "Song of joy"
assert ct.tidy_ocr_clues("See 15", scope="clue", cells=15, lights=[15]) == "See 15"
# a lone full stop after a count is a speck like any other
assert ct.count_closed("More than two (5-8).") == "More than two (5-8)"
print("tidy_ocr_clues ok")
# one tolerant see core: SEE_RE, SEE_DIRECTED and BARE_SEE all read misreads, none read a real word
for t in ("See l5", "sce 15", "see I5", "See 1l down"):
    assert ct.SEE_RE.match(t), t
    assert re.compile(ct.SEE_DIRECTED, re.I).search(t), t
assert ct.see_number("l5") == 15 and ct.see_number("1l") == 11 and ct.see_number("I") == 1
assert re.compile(ct.SEE_DIRECTED, re.I).search("sce l5 Down").groups() == ("l5", "Down")
for t in ("see I", "See lamp", "see l", "see 1 lamp"):
    assert not ct.SEE_RE.match(t) or ct.SEE_RE.match(t).group(1) == "1", t
assert not re.compile(ct.SEE_DIRECTED, re.I).search("see I think")
assert ct.BARE_SEE.match("sce l5") and ct.BARE_SEE.match("(see I)") and not ct.BARE_SEE.match("see I think")
# run-on number core shared by RUN_ON_NUMBER and NEXT_NUMBER
assert ct.NEXT_NUMBER.search("clue (5) l] Next") and ct.RUN_ON_NUMBER.search("clue (5) l] Next")
assert not ct.NEXT_NUMBER.search("clue (5) 7 Across") and not ct.RUN_ON_NUMBER.search("clue (5) 7 Across")
# No 601 2D: a direction's letter ending the clue, or before its count, names a light.
assert not ct.NEXT_NUMBER.search("Playful division of the second of 1 A")
assert not ct.NEXT_NUMBER.search("Playful division of the second of 1 A. (4)")
assert ct.NEXT_NUMBER.search("Close up (4) 3 A tangle of hair")
# fixes moved out of per-source readers (see test_ocr_text_central.py)
assert ct.mac_punctuation("SantaÕs helpers Ð seamen") == "Santa’s helpers – seamen"
assert ct.mac_punctuation("Ð alone") == "Ð alone"
assert ct.enum_figures("5 \u2013 3") == "5-3"
assert ct.same_text_key("Ann\u2019s \u2014 clue") == "Ann'sclue"
assert ct.mend_list_start("1.Religion (5)") == "1 Religion (5)" and ct.mend_list_start("1-Chinese") == "1 Chinese"
assert ct.mend_between_clues("a (3-6). _ 3 It's") == "a (3-6). 3 It's"
assert ct.mend_between_clues("a (10). : 6 Angry") == "a (10). 6 Angry"
assert ct.mend_between_clues("a (5) 11.12A product") == "a (5) 11,12 A product"
# times-15827 (1982): the events column's heading read level with 7 down's last
# line, after its count, swallowed "8" into a clue whose number was lost.
assert ct.foreign_tail_cut("7 Princess of minor note (7). Walks\n8 Some batsman assaulted in\nWest Indies (6).") \
    == "7 Princess of minor note (7).\n8 Some batsman assaulted in\nWest Indies (6)."
assert ct.foreign_tail_cut("8 Some batsman assaulted in\nWest Indies (6). Bond Street station,\n9 Wanderings") \
    == "8 Some batsman assaulted in\nWest Indies (6).\n9 Wanderings"
# Not a lower number (a cross-reference or the list's own start), not a figure
# or bracket in the words, not words with a count of their own, not mid-line.
assert ct.foreign_tail_cut("9 Fish (5). Walks\n8 Some batsman") == "9 Fish (5). Walks\n8 Some batsman"
assert ct.foreign_tail_cut("7 Fish (5). Walks 1.30\n8 Some batsman") == "7 Fish (5). Walks 1.30\n8 Some batsman"
assert ct.foreign_tail_cut("7 Fish (5). Walks (4)\n8 Some batsman") == "7 Fish (5). Walks (4)\n8 Some batsman"
assert ct.foreign_tail_cut("7 Fish (5). 8 Some batsman") == "7 Fish (5). 8 Some batsman"
assert ct.foreign_tail_cut("7 Fish (5). one two three four five\n8 Some") == "7 Fish (5). one two three four five\n8 Some"
# times-15828: the clue holds the neighbour's bracket too ("Commons (2."): left whole.
_t = "19 Light Division troop-leader Commons (2.\nheads charge winning liber-\nation (7) stages..\n22 Office instruction"
assert ct.foreign_tail_cut(_t) == _t
# times-18519: the clue's number misread ("141" for 14), the weather column's "Nireland.." after its count.
assert ct.foreign_tail_cut("8 Change to author church sup-\nports (5).\n141 Little girl's sort of upper-class,\n"
                           "having noble rank (9). Nireland..\n16 Priest removing") \
    == "8 Change to author church sup-\nports (5).\n141 Little girl's sort of upper-class,\nhaving noble rank (9).\n16 Priest removing"
assert "Walks" not in ct.tidy_ocr_clues("DOWN\n7 Princess of minor note (7). Walks\n8 Some batsman assaulted in\nWest Indies (6).")
# times-23760 (Gale 2007-11-16): the clue window's left edge caught the line-end
# letters of the column to its left, before clue numbers and alone on a line, so
# 10, 11 and 12 across opened in no reading (edge_letter_cut, EDGE_LETTER_LINE).
_t = ct.tidy_ocr_clues("ACROSS\n9 Man with no end of criminal\ne record keeping the law? (10)\nS\n10 Bet placed about start"
                       " of National\n(4)\nS\ne 11 Office worker, former model (8)\nn 12 Eugene still below the limit after\n"
                       "this? (6)\nblue (4)\ne\nst\n24 Show disapproval").split("\n")
assert _t == ["ACROSS", "9 Man with no end of criminal", "e record keeping the law? (10)", "10 Bet placed about start of National",
              "(4)", "11 Office worker, former model (8)", "12 Eugene still below the limit after", "this? (6)", "blue (4)",
              "24 Show disapproval"], _t
assert ct.edge_letter_cut("a 10 Pained expression") == "10 Pained expression"
assert ct.edge_letter_cut("T 21 Important, grinding") == "21 Important, grinding"
# Not A or I (words), nor a figure's lookalike (I, l, Z: "l 5" may be 15), nor
# before anything but a number and a capital, nor a word (the printer's imprint
# "at 1 Virginia Street" is no clue 1).
for _s in ("A 1 over the eight (5)", "I 5 More", "l 5 More", "Z 1 Fish", "e record keeping", "e 11 office", "ON 5 Fish",
           "at 1 Virginia Street, London"):
    assert ct.edge_letter_cut(_s) == _s, _s
# A letter alone is dropped only where a clue opens (after a count or heading),
# and never A, I or a lookalike; mid-clue it is the clue's.
assert ct.tidy_ocr_clues("DOWN\n7 Fish (5)\nI\n9 Bird (4)").split("\n")[2] == "I"
assert ct.tidy_ocr_clues("DOWN\n7 Fish (5)\nA\n9 Bird (4)").split("\n")[2] == "A"
assert ct.tidy_ocr_clues("DOWN\n7 Fish clubs mis-\ns\ntakenly (5)").split("\n")[2] == "s"
assert ct.space_before_quote("in\u201cThe sire?(anag.)") == "in \u201cThe sire? (anag.)"
assert ct.mend_numbered_run("i Emma 2 Orgasm") == "1 Emma 2 Orgasm"
assert ct.mend_numbered_run("12Ethelred 18Hess_20 Clever 6/20d Ken 22.Panorama") == "12 Ethelred 18 Hess 20 Clever 6/20 Ken 22 Panorama"
import quotes
assert quotes.unligature("stu\ufb00 \u2019") == "stuff \u2019"
assert ct.number_figures("15,683 *") == "15683" and ct.FIGURE_SLIPS["3"] == "8"
assert ct.mark_counts("Ann\u2019s \u2014 clue, a") == ct.mark_counts("Ann's - clue, a") == {"'": 1, "-": 1, ",": 1}
# glitches a reread brings in (tools/audit_updates.py), each seen in the 10-16..23 rereads
for cls, text in [("a:space-before-mark", "Hold it, Mister !"),
                  ("b:furniture", "About to entertain lavishly, look times, up place to eat"),
                  ("c:hyphen-leak", "Knocks about Minehead look- 2119. ing for swindles"),
                  ("c:hyphen-leak", "Everyone's right at the sea- Wart seaside"),
                  ("d:pound-as-E", "Locks secured, in the end, with E25 left"),
                  ("d:glued-figures", "2A former emperor rebuffed the follower of another"),
                  ("d:lone-figure", "Sounds like a city's devices for 9 securing prisoners"),
                  ("e:unbalanced", 'Oriental girl stars in "The Special Agents'),
                  ("e:symbol-junk", "Best fete champ&tre?"),
                  ("h:zero-one", "Featured in the newspaper. 1 live for danger"),
                  ("h:zero-one", "Name held by fifth-rate foreign 0 nobleman"),
                  ("i:count-in-text", "Bomb is not half an unpleasant experience (5). code."),
                  ("i:leading-quote", '" Where drivers stand'),
                  ("i:spaced-hyphen", "Took a risk - part of church"),
                  ("i:doubled-word", "Gone with the the wind")]:
    assert cls in ct.glitch_counts(text), (cls, text)
# mirror: the print's own shapes are no glitch
for text in ["Locks secured, in the end, with \u00a325 left", "Lives in E8 back street", "Pass the 1st XV in the 1960s",
             "At times, I could weep", "A pre- and post-war tale", "See 1 across", "Gone with the wind",
             "Oriental girl stars in \"The Special Agents\"", "O come, all ye faithful", "30 per cent off"]:
    assert not ct.glitch_counts(text), (text, ct.glitch_counts(text))
assert ct.gains_glitch("Locks with \u00a325 left", "Locks with E25 left") == "d:pound-as-E"
assert ct.gains_glitch("Hold it, Mister!", "Hold it, Mister !") is None  # the old Times's own setting
assert ct.likeness("Bill's relations", "Virtue") < 0.5 < ct.likeness("Dry places ruined", "Dry places, ruined")
# pound_sign: "E" for "\u00a3" before a sum, never before a London postcode (E1-E20)
assert ct.pound_sign("with E25 left") == "with \u00a325 left" and ct.pound_sign("gets E1.000 for") == "gets \u00a31.000 for"
assert ct.pound_sign("Lives in E8 back street") == "Lives in E8 back street" and ct.pound_sign("Room E1?") == "Room E1?"
# count_in_text: the light's own count with a neighbour's scraps after it is cut
assert ct.count_in_text("Bomb is not half an unpleasant experience (5). code.", "5") == \
    "Bomb is not half an unpleasant experience"
assert ct.count_in_text("Surround streets in Dover and Calais? Sounds good (5,4) first", "5,4") == \
    "Surround streets in Dover and Calais? Sounds good"
# mirror: another count, a clue's own ending after it, or no enumeration stands
for text, enum in [("Event of 1917 (4)", "5"), ("Man's surrounded by it (5,3) madly protected?", "5,3"),
                   ("Bomb (5). code.", None)]:
    assert ct.count_in_text(text, enum) == text, text
print("clue_text ok")
