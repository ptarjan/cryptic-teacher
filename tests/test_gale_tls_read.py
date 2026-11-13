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
assert t.VERSION >= 11
# 1992-10-02: 7-down's "(9)" read "(5)", 3-down's "(8)": the light's own count where the figures are lookalikes
lengths = {f"{i}-down": 9 for i in range(1, 9)}
laid = {f"{i}-down": ("a clue", "9", None) for i in range(1, 7)} | {
    "7-down": ("a clue", "5", None), "8-down": ("a clue", "4", None)}
mended = t.mended_counts(laid, lengths)
assert mended["7-down"][1] == "9"  # 5 and 9 are lookalikes
assert mended["8-down"][1] == "4"  # 4 for 9 is not a misread figure
# a linked count mends one group: 1993-11-12's 11-down "(4,6)" for 12 is (4,8)
assert t.mended_counts({"1-down": ("c", "4,6", None)} | {f"{i}-down": ("c", "9", None) for i in range(2, 5)},
                       {"1-down": 12} | {f"{i}-down": 9 for i in range(2, 5)})["1-down"][1] == "4,8"
# a page whose lights mostly miss their counts has a grid no count is mended by
assert t.mended_counts({"1-down": ("c", "5", None), "2-down": ("c", "5", None)},
                       {"1-down": 9, "2-down": 9}) == {"1-down": ("c", "5", None), "2-down": ("c", "5", None)}
# 1992-04-17: a correction notice and a grid, no clue lists, is no puzzle
words = [(0, 0, 10, 10, w) for w in "We apologize for the errors in the numbering".split()]
assert t.no_lists_why(words).startswith("no puzzle on the page: a correction notice")
assert t.no_lists_why([(0, 0, 10, 10, "ACROSS")]) == "no TLS clue lists found on the page"
# 1992-06-05: a second list set beside the first with no gutter is cut where its numbers start
side = [(10, 100 + 30 * i, 200, 120 + 30 * i, "text") for i in range(14)] + [(300, 100 + 30 * i, 330, 120 + 30 * i, str(i + 6)) for i in range(14)] + [
    (340, 100 + 30 * i, 400, 120 + 30 * i, "clue") for i in range(14)]
assert t.side_by_side(side, 700, 20) == 290
assert t.side_by_side(side[:14], 700, 20) is None
# 1992-02-07: three stray "3"s in prose under the lists are no second list
stray = [(10, 100 + 30 * i, 200, 120 + 30 * i, "text") for i in range(14)] + [
    (300, 100 + 30 * i, 330, 120 + 30 * i, "3") for i in range(3)]
assert t.side_by_side(stray, 700, 20) is None
# 1993-02-26: the pitch drifts, the next column clips the last found one's edge: set from that edge instead
drift_words = [(10 + 30 * i, 10, 30 + 30 * i, 30, "w") for i in range(50)]
drift = t.pitch_columns(drift_words, (1000, 0, 1400, 400), [(0, 0, 464, 900), (69, 420, 531, 900)])
assert drift and drift[0][0] == 531
print("ok")
