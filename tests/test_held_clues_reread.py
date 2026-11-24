#!/usr/bin/env python3
# Does a reread keep the held clue text and count unless it corrects them?
#
#     python3 tests/test_held_clues_reread.py
#
# The 10-24 reread of two archive.org Financial Times 1981 editions laid
# neighbour-column words ("kind Peel of rubber", "Desk, musical instrument")
# and an l read as I ("Iosing interest", its "9" dropped) over held clues
# (ftcryptic-4624, -4642). keep_held_clues now holds a dropped count to the
# words' gate, and guard_held applies it to a reading decided elsewhere at
# write time. A held punctuation mend ("hus- , band" to "husband",
# ftcryptic-4184) still goes through mend_held. In memory and a temp dir,
# a fake HOME, no live ~/.cache.
import _path  # puts tools/ on sys.path
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="held_clues_reread_")
os.environ["HOME"] = TMP
os.environ["CT_DOWNLOADS"] = TMP
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import copy
import json
from pathlib import Path

import file_archive_org_puzzles as fa

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)


def entry(number, y, length, text, enum, solution=None):
    e = {"number": number, "direction": "across", "position": {"x": 0, "y": y}, "length": length,
         "clue": {"text": text, "enumeration": enum}}
    if solution:
        e["solution"] = solution
    return e


def puzzle(entries, solutions):
    return {"id": "ftcryptic-9999", "number": 9999, "date": "1981-07-20",
            "dimensions": {"cols": 15, "rows": 15},
            "source": {"publisher": "Financial Times", "acquiredBy": fa.TOOL},
            "solutions": {"origin": solutions}, "entries": entries}


HELD = [("In this way rob another kind of rubber", "5", "SORBO"),
        ("Speed appearance by musical instrument", "5", "TEMPO"),
        ("Frightful father turned back losing interest", "9", "APPALLING"),
        ("Second boy attending to part of paper", "8", "BACKPAGE")]
NEW = ["In this way rob another kind Peel of rubber",
       "Speed appearance by Desk, musical instrument",
       "Frightful father turned back Iosing interest",
       "Second boy attending to part of paper"]


def held_puzzle():
    return puzzle([entry(i + 1, 2 * i, int(en), t, en) for i, (t, en, _) in enumerate(HELD)], "unsolved")


def new_puzzle(drop_count=True):
    es = [entry(i + 1, 2 * i, int(en), NEW[i], en, s) for i, (_, en, s) in enumerate(HELD)]
    if drop_count:
        del es[2]["clue"]["enumeration"]
    return puzzle(es, "published")


def clue(p, n):
    return next(e for e in p["entries"] if e["number"] == n)["clue"]


# The dropped count: the held words and "9" stand.
held, new = held_puzzle(), new_puzzle()
kept = fa.keep_held_clues(new, held)
check("neighbour words refused", clue(new, 1)["text"] == HELD[0][0] and clue(new, 2)["text"] == HELD[1][0], clue(new, 1))
check("l read as I refused, count kept", clue(new, 3) == {"text": HELD[2][0], "enumeration": "9"}, clue(new, 3))
check("answers stay", all(e["solution"] for e in new["entries"]))
check("kept lights named", set(kept) >= {"1-across", "2-across", "3-across"}, kept)

# A dropped count with words the reread corrects keeps the count and takes the words.
held, new = held_puzzle(), new_puzzle()
clue(held, 4)["text"] = "Second boy attending to part paper"
del clue(new, 4)["enumeration"]
fa.keep_held_clues(new, held)
check("corrected words taken with the held count", clue(new, 4) == {"text": "Second boy attending to part of paper",
                                                                     "enumeration": "8"}, clue(new, 4))

# The same at write time, for a reading decided elsewhere.
path = Path(TMP) / "ftcryptic-9999.json"
path.write_text(json.dumps(held_puzzle()))
new, verdict = new_puzzle(), {}
fa.guard_held(new, path, verdict)
check("guard_held restores held clues", [clue(new, n)["text"] for n in (1, 2, 3)] == [h[0] for h in HELD[:3]]
      and clue(new, 3)["enumeration"] == "9", clue(new, 3))
check("guard_held names them", bool(verdict.get("heldClues")), verdict)
new, verdict = new_puzzle(), {"mended": {"1-across": "x"}}
fa.guard_held(new, path, verdict)
check("a held file's own mend is not guarded", clue(new, 1)["text"] == NEW[0], clue(new, 1))

# A held FT fragment mend (ftcryptic-4184 "hus- , band" to "husband", 4186 "in-' side" to "inside") passes the
# same gate as corrected_clues' (ft_fragments_mended), so a reading that improves() the file keeps it.
for was, now, printed in [("Dealing tactfully with hus- , band getting older", "Dealing tactfully with husband getting older", ["hus-"]),
                          ("Sensational ancient city in-' side cover", "Sensational ancient city inside cover", [])]:
    held, new = held_puzzle(), new_puzzle(drop_count=False)
    clue(held, 4).update(text=was, enumeration="8", **({"asPrinted": printed} if printed else {}))
    clue(new, 4).update(text=now, enumeration="8")
    fa.keep_held_clues(new, held)
    check("hyphen mend kept: " + now, clue(new, 4)["text"] == now, clue(new, 4))

# ft_cut_restored (also corrected_clues' gate) no longer takes a capitalised neighbour word as restored text.
FT = "Financial Times"
check("ft_cut_restored refuses Peel", not fa.ft_cut_restored(FT, HELD[0][0], NEW[0]))
check("ft_cut_restored refuses Desk", not fa.ft_cut_restored(FT, HELD[1][0], NEW[1]))
check("ft_cut_restored still restores lost words",
      fa.ft_cut_restored(FT, "Intend one entering receive care", "Intend one entering asylum to receive care"))
check("ft_cut_restored still restores a cut word",
      fa.ft_cut_restored(FT, "Fool pickpockets ment", "Fool pickpockets with deferred payment"))

print("FAIL" if fails else "all ok")
sys.exit(1 if fails else 0)
