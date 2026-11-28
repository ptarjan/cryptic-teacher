#!/usr/bin/env python3
# A printedClue whose evidence is only "OCR misread: <word>" gets evidence built from the words
# that differ, so file_rows' length floor does not send it back to the model.
#
#     python3 tests/test_short_misread_evidence.py
import json
import tempfile
from pathlib import Path
import _path  # puts tools/ on sys.path
import annotate_check as AC
import puzzle_paths
import fetch_puzzle as fp
import validate_annotations as V

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

S = AC._short_misread_evidence
for shown, printed, said, want in [
    ("Customer parking on car newly spread!", "Customer parking on tar newly spread!", "tar",
     "OCR misread: the feed reads 'car' where the corrected clue has 'tar'"),
    ("Industry minus effort equals 19 flower", "Industry minus effort equals a flower", "a",
     "OCR misread: the feed reads '19' where the corrected clue has 'a'"),
    ("Stubborn Regiment's st Battalion", "Stubborn Regiment's 1st Battalion", "st for 1st",
     "OCR misread: the feed reads 'st' where the corrected clue has '1st'"),
    ("By noon remove sol soldiers now", "By noon remove soldiers now", "soldiers", None),
    ("By noon remove sol soldiers now", "By noon remove soldiers now", "sol",
     "OCR misread: the feed has a stray 'sol', which the corrected clue drops"),
    ("Some fine clue today", "Some fine clue today again", "again",
     "OCR misread: the feed lacks 'again', which the corrected clue has"),
    ("Docs this suggest it, and why?", "Does this suggest it, and why?", "Does",
     "OCR misread: the feed reads 'Docs' where the corrected clue has 'Does'"),
    ("Docs this suggest it, and wy?", "Does this suggest it, and why?", "Does", None),
    ("Docs this suggest it", "Does this suggest it", "something else", None),
]:
    got = S(shown, printed, "OCR misread: " + said)
    check(f"{said!r} on {shown!r}", got == want)
    if got:
        check("  and it clears the floor",
              not any("characters" in p for p in V.clue_row_problems(shown, printed, got)))

path = puzzle_paths.find("quiptic-619")
puzzle = fp.read_puzzle_file(path)
e0, e1, e2 = puzzle["entries"][:3]
id0, id1, id2 = AC.entry_id(e0), AC.entry_id(e1), AC.entry_id(e2)
w = e0["clue"]["text"].split()
fixed = " ".join(w[:-1] + [w[-1] + "x"])
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    f = d / "_ann_x.json"
    f.write_text(json.dumps({
        id0: {"printedClue": [fixed, "OCR misread: " + w[-1] + "x"]},
        id1: {"printedClue": ["A different clue", "OCR misread: nothing like it"]},
        id2: {"printedClue": ["Another different clue", "Scan reads: x"]},
    }))
    check("the short evidence is rewritten", AC.mend_short_misread_evidence(path, f, d) == [id0])
    left = json.loads(f.read_text())
    check("the evidence names both words", w[-1] in left[id0]["printedClue"][1]
          and w[-1] + "x" in left[id0]["printedClue"][1])
    check("an unrelated note stays", left[id1]["printedClue"][1] == "OCR misread: nothing like it")
    check("a scan read stays", left[id2]["printedClue"][1] == "Scan reads: x")
    check("a second pass changes nothing", AC.mend_short_misread_evidence(path, f, d) == [])
raise SystemExit(1 if fails else 0)
