#!/usr/bin/env python3
# Does tools/gale_docs.crossword pick the Independent's daily puzzle over a
# feature, offer or magazine puzzle its issue's contents list first, and are
# editions laid out from such an article looked up and fetched again?
#
#     python3 tests/test_gale_independent_pick.py
import _path  # puts tools/ on sys.path
import gale_docs
import gale_inbox


def pick(titles, sunday=False):
    k = gale_docs.crossword("INDA", titles, sunday=sunday)
    return None if k is None else titles[k]


# 1998-05-09's contents, in Gale's order: the Weekend games page's feature
# (p.36, the Concise beside it) came first, so its page was fetched for the day.
MAY_9 = ["Crossword Puzzlers out for a Duck: Don Manley Explains Himself", "Concise Crossword",
         "The Independent Crossword", "Crossword 152"]
assert pick(MAY_9) == "The Independent Crossword", pick(MAY_9)
# The others stay behind it for the fetcher to try (gale_docs.entry's "others").
assert [MAY_9[i] for i in gale_docs.crosswords("INDA", MAY_9)] == \
    ["The Independent Crossword", "Crossword Puzzlers out for a Duck: Don Manley Explains Himself", "Crossword 152"]
for feature, daily in [("How to Solve the Independent Crossword", "The Independent Crossword"),
                       ("Crossword Guide Offer", "The Saturday Crossword"),
                       ("Cryptic confessions of a crossword addict", "The Tuesday Crossword"),
                       ("Polo Crossword", "The Friday Crossword"),
                       ("Seiko Oxford Pocket Thesaurus, Crossword Solver and ?", "The Wednessday Crossword"),
                       ("Solve the proposal puzzle?do it by crossword", "Cryptic Crossword 7684")]:
    assert pick([feature, daily]) == daily, (feature, daily)
# Gale's OCR'd "Concisc" is the Concise all the same.
assert pick(["Concisc crossword #8071 28 August 2012", "Cryptic crossword #8072 28 August 2012"]) == \
    "Cryptic crossword #8072 28 August 2012"
# No puzzle title: the first title naming a crossword, as before.
assert pick(["Weather", "Crossword"]) == "Crossword"
# The Sunday's ranking is untouched.
assert pick(["The Prize Crossword", "Beelzebub Crossword No 954"], sunday=True) == "Beelzebub Crossword No 954"

for t in ("The Independent Crossword", "The Independent Crossword in association with Charles Wells",
          "The Saturday Prize Crossword by Tyrus #1234", "The Thur'sday Crossword", "The Tuseday Crossword",
          "Weekend Crossword #4567", "Prize cryptic crossword #7812", "Crytic Crossword 7700",
          "Cryptic Cross Word 7610", "Beelzebub Prize Crossword No 954", "The Prize Crossword"):
    assert gale_docs.inda_puzzle(t), t
for t in MAY_9[:2] + ["Crossword 152", "How to Solve the Independent Crossword", "Crossword Guide Offer",
                      "May Bank Holiday Crossword", "The Independent Crosswords", "Concisc crossword #8071"]:
    assert not gale_docs.inda_puzzle(t), t

# A cache entry an older matcher picked a feature for is looked up again; a
# puzzle title, or a pick by this matcher, stays.
old = gale_docs.MATCHER["INDA"] - 1
assert gale_docs.stale("INDA", {"doc": "FQ4200621580", "title": MAY_9[0], "matcher": old})
assert not gale_docs.stale("INDA", {"doc": "FQ4200621657", "title": "The Independent Crossword", "matcher": old})
assert not gale_docs.stale("INDA", {"doc": "FQ4200621580", "title": MAY_9[0], "matcher": gale_docs.MATCHER["INDA"]})

# The laid-out edition citing the feature is due again (gale_fetch.plan looks
# it up and fetches over it); one citing the puzzle, or a Sunday's, is not.
laid = {"GaleIndependent1998UKEnglish/1998-05-09": {"sources": [{"cited": MAY_9[0]}]},
        "GaleIndependent1998UKEnglish/1998-05-02": {"sources": [{"cited": "The Independent Crossword"}]},
        "GaleIndependentSunday1998UKEnglish/1998-05-10": {"sources": [{"cited": "Concise Crossword"}]}}
import datetime
assert gale_inbox.misfiled("INDA", laid) == [datetime.date(1998, 5, 9)], gale_inbox.misfiled("INDA", laid)
assert "INDA" in gale_inbox.PUZZLE_TITLE and "TGRH" in gale_inbox.PUZZLE_TITLE
print("ok")
