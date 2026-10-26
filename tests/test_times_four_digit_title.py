#!/usr/bin/env python3
# The Times's crossword numbers ran four digits until No 10,000 (May 1962):
# the title and solution headings of those editions read as puzzles, and a
# five-digit title still reads as before.
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import file_archive_org_puzzles as f

def line(text):
    return [(i * 100, 0, i * 100 + 90, 20, w) for i, w in enumerate(text.split())]

for text, want in [("THE TIMES CROSSWORDPUZZLE NO.8,565", 8565), ("THE TIMES CROSSWORD PUZZLE NO. 8,565", 8565),
                   ("THE TIMES CROSSWORD PUZZLE No. 9 999", 9999), ("The Times Crossword No. 18,862", 18862),
                   ("THE TIMES CROSSWORD PUZZLE No. 10,000", 10000)]:
    got = [n for n, _, _ in f.times_headings([line(text)])[0]]
    assert got == [want], (text, got)
assert not f.times_headings([line("THE TIMES CROSSWORD PUZZLE No. 85")])[0]
sols = f.solution_headings([line("SOLUTION OF PUZZLE No. 8,564")], [8565])
assert [n for n, _ in sols] == [8564], sols
print("ok")
