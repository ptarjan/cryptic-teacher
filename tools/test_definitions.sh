#!/usr/bin/env bash
# A definition's `at` is computed from its text by the rules in
# tools/definitions.py, refused where they leave it ambiguous, and checked by
# validate_annotations against the clue; a definitionFit that reads the
# definition back is refused.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import definitions as D
import puzzle_schema
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def at(clue, *texts):
    return [d["at"] for d in D.place([{"text": t} for t in texts], clue)]

check("once", [4], at("Big cat", "cat"))
check("whole words: not inside Part", [23], at("Part of medicine man’s art", "art"))
check("the enumeration is not in the text", [0], at("4, whichever way you look at it!", "4"))
check("at an end: last of two", [41], at("Speak about Irish city, but not northern city", "city"))
check("at an end: first of two", [0], at("Down, as in Watership Down?", "Down, as"))
check("no overlap with the other definition, in clue order", [0, 6],
      at("Down, as in Watership Down?", "Down", "as in Watership Down?"))
check("a given `at` that points at its text is kept", [22],
      [d["at"] for d in D.place([{"text": "Down", "at": 22}], "Down, as in Watership Down?")])
check("a wrong `at` is recomputed", [4],
      [d["at"] for d in D.place([{"text": "cat", "at": 1}], "Big cat")])
check("straight quotes typed for curly ones take the clue's spelling", ["Don\u2019t panic"],
      [d["text"] for d in D.place([{"text": "Don't panic"}], "Don\u2019t panic \u2014 and don\u2019t shave!")])
check("note is kept", "why", D.place([{"text": "cat", "note": "why"}], "Big cat")[0]["note"])

def refused(clue, *texts):
    try:
        D.place([{"text": t} for t in texts], clue)
    except ValueError as err:
        return str(err)
    return None
check("both ends is ambiguous", True, "occurs 3 times" in (refused("up and up and up", "up") or ""))
check("not in the clue", True, "not in the clue" in (refused("Big cat", "dog") or ""))

def errors(defs):
    puzzle = {"id": "t-1", "entries": [{"number": 1, "direction": "across",
              "clue": {"text": "Changes colour", "enumeration": "9"}, "solution": "TURNSTONE",
              "annotation": {"type": ["charade"], "answer": "TURNSTONE", "explanation": {"walkthrough": "w"},
                             "definitions": defs, "assembly": {"pieces": ["TURNS", "TONE"]},
                             "blocks": [{"clueFragment": "Changes", "gives": "TURNS"},
                                        {"clueFragment": "colour", "gives": "TONE"}]}}]}
    return [e for e in v.validate_puzzle(puzzle_schema.order(puzzle))[1] if "definition" in e]
check("validator: `at` on its text", [], errors([{"text": "Changes", "at": 0}]))
check("validator: `at` off its text", True,
      any("is not at 3" in e for e in errors([{"text": "Changes", "at": 3}])))

def fit_errors(answer, definition, fit):
    errs = []
    v.check_definition_fit("1A", {"answer": answer, "definitions": [{"text": definition}],
                                  "explanation": {"definitionFit": fit}}, errs, [])
    return [e for e in errs if "restates" in e]
check("definitionFit: one word beyond definition and answer is an explanation", [],
      fit_errors("CARDIFF", "City", "Cardiff is the capital city of Wales."))
check("definitionFit: a plain synonym with a gloss passes", [],
      fit_errors("SIP", "take a drink", "To sip is to drink in small mouthfuls."))
check("definitionFit: the definition read back is refused", 1,
      len(fit_errors("LION CUB", "young animal", "A lion cub is the young of a lion, so it is a young animal.")))
check("definitionFit: the army ant is refused", 1,
      len(fit_errors("CRAWLER", "army ant", "An army ant is a crawler, as it is.")))

# respell: the clue's own characters for the same run of clue words, from the
# failing first checks of headless annotate runs.
check("respell: a typed apostrophe", "we’re", D.respell("we're", "about certain we’re not"))
check("respell: case", "type of shirt", D.respell("Type of shirt", "Hung out type of shirt with"))
check("respell: a doubled space", "Spanish  port", D.respell("Spanish port", "Spanish  port-sour blend"))
check("respell: a comma the clue lacks", "that Parisian",
      D.respell("that, Parisian", "Fashionably petite and fit one, that Parisian"))
check("respell: a hyphen for a space", "brick-carrier", D.respell("brick carrier", "Strange brick-carrier"))
check("respell: case and quotes together", "One’s handle in one’s hand?",
      D.respell("ONE'S HANDLE in one’s hand?", "One’s handle in one’s hand?"))
check("respell: closing marks the clue prints are kept", "Make.it eight thousand,",
      D.respell("Make it eight thousand,", "Make.it eight thousand, say"))
check("respell: verbatim stays", "a cat", D.respell("a cat", "a cat sat"))
check("respell: other words stay", "a step", D.respell("a step", "Take a revolutionary step"))
check("respell: inside a word is no match", "Ate", D.respell("Ate", "Caterpillar"))
check("respell: two different spellings stay", "THE", D.respell("THE", "The cat and the dog"))

# verbatim_hint says what to write for each way a fragment misses its clue.
check("hint: the clue's spelling", True,
      "spells it 'Mammal’s'" in v.verbatim_hint("Mammal's", "Mammal’s covering"))
check("hint: the words skipped", True,
      "prints 'revolutionary' between them" in v.verbatim_hint("a step", "Take a revolutionary step in"))
check("hint: an ellipsis is a skip", True,
      "'out of the wood'" in v.verbatim_hint("Not ... say", "Not out of the wood say"))
check("hint: a misread word names printedClue", True,
      "'iumbled' where this has 'jumbled'" in v.verbatim_hint("jumbled crowd", "Very hot iumbled crowd")
      and "printedClue" in v.verbatim_hint("jumbled crowd", "Very hot iumbled crowd"))
check("hint: unrelated words get the plain rule", True,
      "character for character" in v.verbatim_hint("horserace", "Spectators see chap"))
raise SystemExit(fails)
PY
echo "all definition placement checks passed"
