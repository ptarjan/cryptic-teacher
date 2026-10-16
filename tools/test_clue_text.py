#!/usr/bin/env python3
"""clue_text: ACROSS/DOWN heading readings every old copy accepted."""
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
