#!/usr/bin/env bash
# Hidden-letter devices: each hiddenLetter agrees with its clue's blocks or
# text, a message is spelt by its clues' letters in order, a preamble naming
# a device without `messages` is counted by the ratchet, and the converter reads
# letters off existing blocks.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import hidden_messages as hm
import puzzle_schema
import validate_annotations as v

PREAMBLE = ("Wordplay in each across clue omits a letter from the entry. In order, "
            "the omissions form a hint, which must be written below the grid.")


def entry(n, direction, clue, answer, blocks, hidden=None):
    ann = {"type": ["charade"], "answer": answer, "definitions": [{"text": clue.split()[-1], "at": clue.rindex(" ") + 1}],
           "blocks": blocks, "explanation": {"walkthrough": "w"}}
    if hidden:
        ann["hiddenLetter"] = hidden
    return {"number": n, "direction": direction, "position": {"x": 0, "y": n},
            "length": len(answer), "clue": {"text": clue, "enumeration": str(len(answer))},
            "solution": answer, "annotation": ann}


def puzzle(entries, messages=None, preamble=PREAMBLE):
    p = {"id": "genius-1", "number": 1, "series": "genius", "name": "t", "date": "2026-01-01",
         "preamble": preamble, "dimensions": {"cols": 9, "rows": 9},
         "source": {"publisher": "Guardian", "url": "https://x.example/1", "retrievedFrom": "publisher",
                    "acquiredBy": "tools/genius_puzzles.py", "acquiredOn": "2026-01-01", "gridOrigin": "published"},
         "solutions": {"origin": "published"}, "entries": entries}
    if messages:
        p["messages"] = messages
    return p


# HI: 1-across omits H (a block with no clue words supplies it), 3-across
# omits I (its blocks give one letter fewer).
def entries(hidden=True):
    return [
        entry(1, "across", "Bat ox", "HOT",
              [{"gives": "H", "note": "the omitted letter"}, {"clueFragment": "Bat", "gives": "O"},
               {"clueFragment": "ox", "gives": "T"}],
              {"kind": "omitted", "letter": "H"} if hidden else None),
        entry(3, "across", "Sat in", "SIT",
              [{"clueFragment": "Sat", "gives": "ST"}],
              {"kind": "omitted", "letter": "I"} if hidden else None),
        entry(2, "down", "Tome hat", "TOME",
              [{"clueFragment": "Tome", "gives": "TOMEX"}],
              {"kind": "extra", "letter": "X"} if hidden else None),
    ]


MSG = [{"text": "HI", "kind": "omitted", "direction": "across", "order": "clues", "placement": "belowGrid"}]
fails = 0


def check(name, want, got):
    global fails
    ok = bool(got) == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)


def problems(p):
    p = puzzle_schema.order(p)
    return (puzzle_schema.validate(p) + hm.message_problems(p)
            + [x for e in p["entries"] for x in hm.letter_problems(e["annotation"], e)])


check("letters spell the message", False, problems(puzzle(entries(), MSG)))
bad = copy.deepcopy(MSG); bad[0]["text"] = "IH"
check("letters out of order", True, problems(puzzle(entries(), bad)))
un = copy.deepcopy(bad); un[0]["order"] = "unordered"
check("unordered reads them in any order", False, problems(puzzle(entries(), un)))
wrong = entries(); wrong[1]["annotation"]["hiddenLetter"]["letter"] = "A"
check("omitted letter the blocks do not lack", True, problems(puzzle(wrong, MSG)))
wrong = entries(); wrong[2]["annotation"]["hiddenLetter"]["letter"] = "T"
check("extra letter the blocks do not add", True, problems(puzzle(wrong, MSG)))
mis = entries(); mis[0]["annotation"]["hiddenLetter"] = {"kind": "misprint", "letter": "C", "printed": "B", "at": 0}
check("misprint at its printed letter", False, hm.letter_problems(mis[0]["annotation"], mis[0]))
mis[0]["annotation"]["hiddenLetter"]["at"] = 1
check("misprint at the wrong offset", True, hm.letter_problems(mis[0]["annotation"], mis[0]))
mis[0]["annotation"]["hiddenLetter"] = {"kind": "extra", "letter": "X", "at": 1}
check("extra takes no offset", True, hm.letter_problems(mis[0]["annotation"], mis[0]))
check("schema refuses an unknown kind", True,
      puzzle_schema.validate(puzzle_schema.order(puzzle(entries(), [{**MSG[0], "kind": "swapped"}]))))

# The ratchet: a preamble naming a device with no messages warns once, as
# `puzzle:`, so count_backlog counts it under "messages".
p = puzzle(entries(hidden=False))
warns = hm.check_preamble(p)
check("device without messages is counted", True, warns)
check("ratchet counts it once", True, v.count_backlog(warns)["messages"] == 1 or [])
check("with messages nothing is counted", False, hm.check_preamble(puzzle(entries(), MSG)))
for text in ["Seven solutions, not defined, are linked.",
             "Answers lose a letter before entry.",
             "Erratum: 12 across should read (5).",
             "The first letters of the unclued answers are irrelevant."]:
    check(f"not a device: {text!r}", False, hm.device_kinds(text))
for text in ["Each clue contains a misprint; the correct letters spell a quotation.",
             "One letter too many is generated by the wordplay in each clue; these extra letters spell an instruction.",
             PREAMBLE]:
    check(f"a device: {text[:40]!r}", True, hm.device_kinds(text))

# The converter reads the letters off the blocks and writes them back. A run
# of fewer than four letters is too short to tell from chance, so spell OPEN.
four = [entry(n, "across", f"Clue {n} word", ans,
              [{"gives": miss, "note": "the omitted letter"},
               {"clueFragment": "Clue", "gives": ans.replace(miss, "", 1)}])
        for n, ans, miss in [(1, "OAK", "O"), (3, "SPA", "P"), (5, "EAR", "E"), (7, "NIL", "N")]]
status, text, new = hm.convert(puzzle(four))
check("converter reads the across omissions", True, status == "converted" and text == "OPEN" or [])
if new:
    check("converted puzzle is clean", False, problems(new))
raise SystemExit(fails)
PY
echo "all hidden-message checks passed"
