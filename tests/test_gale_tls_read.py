#!/usr/bin/env python3
# Does tools/gale_tls_read.py keep a clue list's numbers in its column (joined_numbers)?
# 1993-11-12 (Gale EX1200472083): the finer gutter split the "7", "8", "14" numbers
# of the second down column from their clues, a sliver the crop then left out,
# so eight down clues lost their numbers and were never laid.
#
#     python3 tests/test_gale_tls_read.py
import _path  # puzzles tools/ on sys.path
import gale_tls_read as t

lh = 26
# a number sliver (631-666), its clues (679-1075)
assert t.joined_numbers([(631, 666), (679, 1075)], lh) == [(631, 1075)]
# two real columns stay two
assert t.joined_numbers([(98, 585), (666, 1075)], lh) == [(98, 585), (666, 1075)]
# a sliver last has nothing to join: kept as it was
assert t.joined_numbers([(98, 585), (700, 730)], lh) == [(98, 585), (700, 730)]
assert t.joined_numbers([], lh) == []
assert t.VERSION >= 9
print("ok")
