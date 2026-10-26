#!/usr/bin/env python3
"""tools/audit_updates.py: each reread change classed introduced, fixed or
neutral, by glitch class; and the alerts the recurring runner wakes on.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import audit_updates as A

failed = []


def check(what, want, got):
    if want != got:
        failed.append(f"{what}: want {want!r}, got {got!r}")


def pair(old, new, old_enum="5", new_enum="5"):
    return {"old": old, "new": new, "old_enum": old_enum, "new_enum": new_enum}


# Seen in the 10-16..23 rereads: the new text has more of a class, so it is introduced.
for what, p, want in (
        ("furniture", pair("look up place", "look times, up place"), ["b:furniture"]),
        ("a leaked line-end hyphen", pair("Minehead looking for", "Minehead look- 2119. ing for"), ["c:hyphen-leak"]),
        ("E for £", pair("with £25 left", "with E25 left"), ["d:pound-as-E"]),
        ("1 for I", pair("newspaper. I live for danger", "newspaper. 1 live for danger"), ["h:zero-one"]),
        ("the count left in", pair("an unpleasant experience", "an unpleasant experience (5). code."),
         ["i:count-in-text"]),
        ("a blank", pair("Wine colour", ""), ["i:empty"]),
        ("another clue's words", pair("Bill's relations", "Virtue"), ["f:rewrite"]),
        ("word breaks lost", pair("Trustworthy, and still improving", "Trustworthy, and still improving",
                                  "2,3,2,3,2", "5,7"), ["g:enum-structure"]),
        ("an enumeration dropped", pair("Sally in plane", "Sally in plane", "4", None), ["g:enum-dropped"])):
    check(f"introduced: {what}", (want, []), A.classify(p))

# Mirror: the old text had it and the new one lost it, so it is fixed.
check("fixed: a stray stop and the count",
      ([], ["e:symbol-junk", "i:count-in-text"]),
      A.classify(pair("Bomb is not half . an experience (5). code.", "Bomb is not half an experience")))
check("fixed: word breaks gained", ([], ["g:enum-structure"]), A.classify(pair("Red wine", "Red wine", "7", "3,4")))
check("neutral: a word changed, no class", ([], []), A.classify(pair("Operatic spectacles we hear",
                                                                     "Operatic spectacles we bear")))
check("neutral: a lone count read over breaks is the print's (The Times 21,933 prints SHEEPSHEARING \"(13)\")",
      ([], []), A.classify(pair("Clip of audition?", "Clip of audition?", "5-8", "13")))
check("neutral: a cross-reference has no count of its own", ([], []),
      A.classify(pair("See ac", "See 1 ac", "5", None)))
check("verdicts", ["introduced-glitch", "fixed-glitch", "neutral"],
      [A.verdict(["b:furniture"], ["e:symbol-junk"]), A.verdict([], ["e:symbol-junk"]), A.verdict([], [])])

# Tally: per class (introduced, fixed), and per verdict.
rows = [{"introduced": ["b:furniture"], "fixed": [], "verdict": "introduced-glitch"},
        {"introduced": [], "fixed": ["b:furniture"], "verdict": "fixed-glitch"},
        {"introduced": [], "fixed": [], "verdict": "neutral"}]
by, v = A.tally(rows)
check("tally", ({"b:furniture": [1, 1]}, {"introduced-glitch": 1, "fixed-glitch": 1, "neutral": 1}), (by, dict(v)))


# Alerts: a class with none in a day or more of history is new; one over the
# floor and over twice its hourly mean is spiking; a steady class is quiet.
def row(cls, t, old="a", new="b"):
    return {"introduced": [cls], "fixed": [], "time": t, "old": old, "new": new, "path": "puzzles/times/x.json",
            "key": ["across", 1]}


day = 24 * 3600
history = [row("e:unbalanced", i * 3600) for i in range(0, 48, 2)]  # one per 2 hours over 2 days
quiet = [row("e:unbalanced", 2 * day)]
new = [row("b:furniture", 2 * day, "look up", "look times, up")]
spike = [row("e:unbalanced", 2 * day) for _ in range(5)]
check("alerts: a steady class is quiet", [], A.alerts(quiet, history, 0.5))
got = A.alerts(new + spike, history, 0.5)
check("alerts: a new class and a spike", [True, True],
      [any("b:furniture new" in a and "look times, up" in a for a in got),
       any("e:unbalanced spiking: 5" in a for a in got)])
check("alerts: no history long enough to call a class new", [], A.alerts(new, history[:3], 0.5))

if failed:
    print("\n".join(failed))
    sys.exit(1)
print("ok")
