#!/usr/bin/env bash
# A clue typed anagram gets the anagram ring: app.js deals the whole-answer
# anagram's fodder, else the longest part-anagram's, and the validator warns
# (ratcheted as assembly.anagrams) when a clue typed anagram names no fodder.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import sys
sys.path.insert(0, "tools")
import validate_annotations as v

fails = 0
def check(name, ok):
    global fails
    fails += not ok
    print("ok  " if ok else "FAIL", name)

def warns(ann):
    w = []
    v.check_anagram_has_fodder("1A", ann, w)
    return w

check("typed anagram with no assembly.anagrams warns",
      len(warns({"type": ["anagram", "container"]})) == 1)
check("typed anagram with a part-anagram is fine",
      warns({"type": ["anagram", "container"],
             "assembly": {"anagrams": [{"fodder": "CODHE", "gives": "CHOED"}]}}) == [])
check("a cycling clue's permutation in assembly.anagrams needs no anagram type",
      warns({"type": ["cycling"], "assembly": {"anagrams": [{"fodder": "SEAT", "gives": "EATS"}]}}) == [])
w = warns({"type": ["anagram"]})
check("the warning is counted by the assembly.anagrams ratchet",
      v.count_backlog(w)["assembly.anagrams"] == 1)
check("over the puzzle's allowance it is an error",
      v.backlog_errors("p-1", w, {"assembly.anagrams": {}}) != [])
check("within the allowance it is not",
      v.backlog_errors("p-1", w, {"assembly.anagrams": {"p-1": 1}}) == [])
sys.exit(1 if fails else 0)
PY
node - <<'JS'
const src = require("fs").readFileSync("app.js", "utf8");
const s = src.indexOf("  const bareLetters"), e = src.indexOf("function ringFodder");
const f = new Function(src.slice(s, src.indexOf("\n  }\n", e) + 4) + "; return { ringFodder };")();
let fails = 0;
const check = (name, got, want) => {
  const ok = got === want; fails += !ok;
  console.log((ok ? "ok   " : "FAIL ") + name + (ok ? "" : ` (got ${got})`));
};
check("a whole-answer anagram deals its fodder",
  f.ringFodder({ answer: "ORDNELSON", assembly: { anagrams: [{ fodder: "LONDONERS", gives: "ORDNELSON" }] } }), "LONDONERS");
check("a part-anagram deals its fodder (CHO(MP)ED)",
  f.ringFodder({ answer: "CHOMPED", assembly: { anagrams: [{ fodder: "COD HE", gives: "CHOED" }] } }), "CODHE");
check("the whole-answer anagram wins over a longer part",
  f.ringFodder({ answer: "ABCDE", assembly: { anagrams: [{ fodder: "ZYXWVUT", gives: "TUVWXYZ" }, { fodder: "EDCBA", gives: "ABCDE" }] } }), "EDCBA");
check("no anagram, no fodder", f.ringFodder({ answer: "X" }), "");
process.exit(fails ? 1 : 0);
JS
