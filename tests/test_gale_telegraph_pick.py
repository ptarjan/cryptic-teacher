#!/usr/bin/env python3
# Does tools/gale_docs.crossword pick the Telegraph's daily "Crossword / 21,0NN"
# (or "Prize Crossword") over its competition articles?
#
#     python3 tests/test_gale_telegraph_pick.py
import _path  # puts tools/ on sys.path
import gale_docs

DAILY = "Crossword / 21,053"


def pick(titles):
    k = gale_docs.crossword("TGRH", titles)
    return None if k is None else titles[k]


# The wrong articles came first in the contents on 1993-09-27..10-30.
assert pick(["How to Crack the Cryptic Crossword and Win £5,000", DAILY]) == DAILY
assert pick(["£5,000 answer for first win to Crossword", "Crossword Competition / 14", DAILY]) == DAILY
assert pick(["How to Crack the Cryptic Crossword Answers", "Prize Crossword"]) == "Prize Crossword"
assert pick(["Crossword Competition / 14", "Crossword / 21,070", "Prize Crossword"]) == "Crossword / 21,070"
# No daily title: the old behaviour (first title naming a crossword).
assert pick(["Weather", "How to Crack the Cryptic Crossword and Win £5,000"]) == \
    "How to Crack the Cryptic Crossword and Win £5,000"
assert pick(["Weather"]) is None
print("ok")
