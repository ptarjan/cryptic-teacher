#!/usr/bin/env python3
# Does tools/validate_annotations.py refuse an annotation that prints the puzzle's
# hidden-letter message or the "(7 + 24 = 31)" pairing sum, and pass one that only
# says a letter is omitted or spare?
#
#     python3 tests/test_message_leak.py
import _path  # puts tools/ on sys.path
import sys
from hidden_messages import leak_problems, names_message


def puzzle(walk, note="the letter the wordplay omits", letter=True):
    ann = {"wordplay": {"op": "charade", "parts": [{"gives": "S", "note": note}]},
           "explanation": {"walkthrough": walk}}
    if letter:
        ann["hiddenLetter"] = {"kind": "omitted", "letter": "S"}
    return {"messages": [{"text": "SUM TO FINAL", "kind": "omitted"}],
            "entries": [{"number": 7, "direction": "across", "annotation": ann}]}


checks = [
    ("plain omitted letter passes", 0, puzzle("The wordplay gives LOOE; the entry needs the omitted S.")),
    ("message in walkthrough", 1, puzzle("The omitted S starts the message SUM TO FINAL.")),
    ("message ignoring case and spaces", 1, puzzle("it spells sum-to final")),
    ("message in a part note", 1, puzzle("fine", note="starts SUM TO FINAL")),
    ("pairing sum", 1, puzzle("The omitted S turns up in 24 down (7 + 24 = 31).")),
    ("arithmetic without a hidden letter is not a pairing", 0,
     puzzle("Add 7 + 24 = 31 letters.", letter=False)),
]
bad = [f"{name}: got {len(leak_problems(p))}, want {want}"
       for name, want, p in checks if len(leak_problems(p)) != want]
if names_message("Nobel laureate sharing", "NOBELLAUREATES"):
    bad.append("a message spanning the middle of words counts as named")
for b in bad:
    print("  FAIL:", b)
if bad:
    sys.exit(1)
print(f"  ok: {len(checks) + 1} message-leak cases")
