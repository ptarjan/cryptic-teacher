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
print("ok")
