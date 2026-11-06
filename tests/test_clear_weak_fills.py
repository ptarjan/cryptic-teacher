#!/usr/bin/env python3
# Lights our clue solve filled past a crossing nobody printed are cleared (tools/clear_weak_fills.py, WEAK_FILLS).
#
#     python3 tests/test_clear_weak_fills.py
import os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _path  # puts tools/ on sys.path
import clear_weak_fills as C
import file_archive_org_puzzles as archive

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


def entry(number, direction, x, y, solution, length=3):
    return {"number": number, "direction": direction, "position": {"x": x, "y": y}, "length": length,
            "clue": {"text": f"clue {number}", "enumeration": str(length)}, "solution": solution,
            "annotation": {"hint": "x"} if solution == "TEA" else None}


def puzzle(model=("TEA", "COW")):
    # 1A CAT across (0,0); 1D COW down (0,0); 2D TEA down (2,0); 1A and 2D cross at (2,0).
    return {"id": "times-1", "number": 1, "date": "2000-01-01", "dimensions": {"cols": 3, "rows": 3},
            "source": {"publisher": "Times", "retrievedFrom": "newspaper", "acquiredBy": archive.TOOL,
                       "acquiredOn": "2026-01-01", "gridOrigin": "published"},
            "solutions": {"origin": "model", "model": archive.CLUE_SOLVER, "date": "2026-11-06",
                          "check": "3 entries; agrees with the 1 answers the paper printed", "printed": {"1-across": "CAT"}},
            "entries": [entry(1, "across", 0, 0, "CAT"), entry(1, "down", 0, 0, model[1]),
                        entry(2, "down", 2, 0, model[0])]}


p = puzzle()
check("our lights are the answered ones outside printed", archive.our_lights(p) == {"1-down", "2-down"})
check("a light crossing the print's letter only is not weak", C.weak_lights(p, standing=lambda *a: False) == {})
p["entries"][0]["solution"] = None
check("a light whose crossing is blank is weak", set(C.weak_lights(p, standing=lambda *a: False)) == {"1-down", "2-down"})

q = puzzle()
q["solutions"]["printed"] = {}
weak = C.weak_lights(q, standing=lambda *a: False)
check("a light crossing only lights of ours is cleared", set(weak) == {"1-across", "1-down", "2-down"})
weak = C.weak_lights(q, standing=lambda text, enum, pattern, answer, pid: answer == "TEA")
check("a route that needs no printed crossing keeps its light", "2-down" not in weak and "1-down" in weak)

new, annotated = C.clear(q, {"2-down"})
check("clearing blanks the light and its annotation", new["entries"][2]["solution"] is None
      and "annotation" not in new["entries"][2] and annotated == ["2-down"])
new, _ = C.clear(q, {"1-across", "1-down", "2-down"})
check("a file left with none of ours loses its model detail", "model" not in new["solutions"]
      and "printed" not in new["solutions"])

print("FAILED" if fails else "ok")
raise SystemExit(1 if fails else 0)
