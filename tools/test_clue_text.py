#!/usr/bin/env python3
"""clue_text: ACROSS/DOWN heading readings every old copy accepted."""
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
assert ct.clue_number_opening("I7 More") == "17 More" and ct.clue_number_opening("IA fruitful") == "1A fruitful"
assert ct.clue_number_opening(". 1 Miss") == "1 Miss" and ct.clue_number_opening("*1 Land") == "1 Land"
assert ct.clue_number_opening("IPheasant") == "1 Pheasant" and ct.clue_number_opening("JTool") == "1 Tool"
assert ct.clue_number_opening("!What makes") == "1 What makes" and ct.clue_number_opening("|What") == "1 What"
assert ct.clue_number_opening("1'In the") == "1 In the" and ct.clue_number_opening("1.Associate's") == "1 Associate's"
assert ct.clue_number_opening(") With") == "With" and ct.clue_number_opening("12 Fish") == "12 Fish"
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
print("clue_text ok")
