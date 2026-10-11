#!/usr/bin/env bash
# A dash between words is stored " — " and an ellipsis "…" (tools/dashes.py),
# whatever the source spelt; hyphens, blanks and a continued clue's leader
# stay; every offset into the clue moves with the text; the write gate refuses
# any other spelling.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import dashes
import puzzle_integrity

fails = 0
def check(name, want, got):
    global fails
    fails += want != got
    print(("ok  " if want == got else "FAIL"), name, "" if want == got else f"want {want!r} got {got!r}")

CASES = [
    # A dash between words, in any spelling.
    ("spaced hyphen", "Beer - or punch", "Beer — or punch"),
    ("spaced en", "Classic film – when Jack is dropped", "Classic film — when Jack is dropped"),
    ("house em stays", "Comb for sale — two pounds off", "Comb for sale — two pounds off"),
    ("double hyphen", "Bowler seen at Dover -- and at Boulogne", "Bowler seen at Dover — and at Boulogne"),
    ("triple hyphen", "nude review --- it's not customary", "nude review — it's not customary"),
    ("closed-up em (a book's)", "Job settled—stamp not required", "Job settled — stamp not required"),
    ("em before a quote", "Out—'now'", "Out — 'now'"),
    ("em after a quote", "'Firm has sacked man' – journalist's", "'Firm has sacked man' — journalist's"),
    ("half-spaced em", "One man is on shiftwork— showed distress", "One man is on shiftwork — showed distress"),
    ("half-spaced double hyphen", "not short of part --of a bridle", "not short of part — of a bridle"),
    ("spaced minus", "One − volume", "One — volume"),
    ("horizontal bar", "snakes ― these better?", "snakes — these better?"),
    ("two in one clue", "Least fine - or finest - way inside", "Least fine — or finest — way inside"),
    # Left alone.
    ("hyphen in a word", "Press-cutting a 20-look", "Press-cutting a 20-look"),
    ("hyphen broken at a line end", "the swings and rounda- bouts", "the swings and rounda- bouts"),
    ("hyphen closed on its word", "a pot -boiler?", "a pot -boiler?"),
    ("closed-up en: a compound", "a so–and–so", "a so–and–so"),
    ("closed-up en: a range", "5–10 strings", "5–10 strings"),
    ("closed-up double hyphen", "however--then", "however--then"),
    ("blank before a citation", "pamper'd Jades of - (2 Hen. IV)", "pamper'd Jades of - (2 Hen. IV)"),
    ("blank before a mark", 'Cry "—! and let slip"', 'Cry "—! and let slip"'),
    ("blank, long rule", "Young Lochinvar came \"to —— at our 23\"", "Young Lochinvar came \"to —— at our 23\""),
    ("blank, mixed rule", "or pins, if ———-", "or pins, if ———-"),
    ("blank, run of hyphens", 'down to a ---- sea', 'down to a ---- sea'),
    ("blank closed on its closing quote", '"Pretty-dimpled boys, like smiling --" (A & C)',
     '"Pretty-dimpled boys, like smiling --" (A & C)'),
    ("blank closed on its opening quote", "'—rank and gross in nature'", "'—rank and gross in nature'"),
    ("blank after an opening quote", '"— \'e \'asn\'t adapted"', '"— \'e \'asn\'t adapted"'),
    ("bowdlerised word ending", "or cut back? —k off!", "or cut back? —k off!"),
    ("nbsp before a hyphen", "finishing early\xa0- order staff", "finishing early — order staff"),
    ("bowdlerised word", "Perhaps Athens regime'll b-- off!", "Perhaps Athens regime'll b-- off!"),
    ("bowdlerised word, em", "I am after b— spicy stuff", "I am after b— spicy stuff"),
    ("stammer", "I—I can't say", "I—I can't say"),
    ("blank printed as the house dash", "Thus — doth make", "Thus — doth make"),
    ("leader dash", "— and 5", "— and 5"),
    ("trailer dash", "See 7 —", "See 7 —"),
    ("leader hyphen", "- 7 Wrongly report", "- 7 Wrongly report"),
    # Ellipses.
    ("three stops", "Bar open to gin...", "Bar open to gin…"),
    ("leader stops", "... and came to a conclusion", "… and came to a conclusion"),
    ("spaced stops", "I . . . I . . . imbeciles", "I … I … imbeciles"),
    ("four stops", "In the temple....", "In the temple…"),
    ("the character stays", "Bringing up a child causes …", "Bringing up a child causes …"),
    ("two stops are a speck", "Pope goes quietly on row ..", "Pope goes quietly on row .."),
    ("blank before an ellipsis", "Soap and -- ... more", "Soap and -- … more"),
    ("empty", "", ""),
]
for name, given, want in CASES:
    check(name, want, dashes.normal(given))
    check(f"{name}: a fixed point", want, dashes.normal(want))

text = "Job settled—stamp not ... required"
new, at = dashes.mapped(text)
check("the offset map is one longer than the text", len(text) + 1, len(at))
check("an offset after the change moves by its growth", new.index("stamp"), at[text.index("stamp")])
check("an offset before it stays", 4, at[4])
check("the text's end maps to the new end", len(new), at[len(text)])

entry = {
    "number": 1, "direction": "across",
    "clue": {"text": "Job settled—stamp not ... required", "italics": [{"at": 12, "length": 5}],
             "asPrinted": ["settled—stamp"]},
    "annotation": {
        "definitions": [{"text": "stamp not", "at": 12}, {"text": "not ... required", "at": 18}],
        "indicators": [{"text": "settled—stamp"}],
        "linkWords": ["Job"],
        "blocks": [{"clueFragment": "... required"}],
        "hiddenLetter": {"kind": "clue", "letter": "r", "at": 26},
    },
}
puzzle = {"id": "t-1", "entries": [entry]}
before = copy.deepcopy(puzzle)
out = dashes.normalise(puzzle)
check("normalise leaves the caller's puzzle as it was", before, puzzle)
e = out["entries"][0]
t = e["clue"]["text"]
check("the clue is normalised", "Job settled — stamp not … required", t)
it = e["clue"]["italics"][0]
check("italics move with the text", "stamp", t[it["at"]:it["at"] + it["length"]])
for d in e["annotation"]["definitions"]:
    check(f"definition {d['text']!r} is where its at says", d["text"], t[d["at"]:d["at"] + len(d["text"])])
check("a definition across the ellipsis is the new clue's words", "not … required",
      e["annotation"]["definitions"][1]["text"])
check("an indicator across the dash is the new clue's words", "settled — stamp",
      e["annotation"]["indicators"][0]["text"])
check("a block fragment follows the ellipsis", "… required", e["annotation"]["blocks"][0]["clueFragment"])
check("hiddenLetter still points at its letter", "r", t[e["annotation"]["hiddenLetter"]["at"]])
check("asPrinted keeps only tokens of the new text", ["settled", "stamp"], e["clue"]["asPrinted"])
flags = []
puzzle_integrity.check_annotation_quotes(out, flags)
check("every quoted phrase is still in the clue (no QUOTE)", [], flags)
check("a normal puzzle is returned as itself", True, dashes.normalise(out) is out)

flags = []
puzzle_integrity.check_dashes(puzzle, flags)
check("DASH flags a clue spelt another way", ["DASH"], [f[0] for f in flags])
flags = []
puzzle_integrity.check_dashes(out, flags)
check("mirror: the normalised clue passes", [], flags)
check("DASH is in the summary list", True, "DASH" in puzzle_integrity.FLAGS)

record = {"clues": {"across": [{"clue": {"text": "Beer - or punch..."}}], "down": []}}
check("clues-only records are normalised too", "Beer — or punch…",
      dashes.normalise_clues_only(record)["clues"]["across"][0]["clue"]["text"])

raise SystemExit(fails)
PY
