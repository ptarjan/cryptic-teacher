#!/bin/bash
# Does every shim put exactly browser_puzzle() into window.CRYPTIC_PUZZLES?
#
#     bash tools/test_shim_format.sh
#
# A shim packs each entry into an array (fetch_puzzle.pack_entry) and carries
# the JavaScript that unpacks it (fetch_puzzle.SHIM_UNPACK). The packer is
# Python and the unpacker is JavaScript, so nothing but this holds them to be
# inverses: every puzzle in the corpus, plus entries shaped to fall off the
# packed path, is written as a shim, evaluated the way the app and the Node
# harnesses evaluate one, and compared key for key with what Python says the
# browser should hold.
set -uo pipefail
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PYTHONPATH=tools python3 - "$TMP" <<'PY' || exit 1
import json, sys
from pathlib import Path
import fetch_puzzle as fp

out = Path(sys.argv[1])
(out / "shims").mkdir()
odd = {"id": "odd-1", "series": "odd", "number": 1, "dimensions": {"cols": 3, "rows": 3},
       "source": {"acquiredBy": "tools/test_shim_format.sh", "url": "x"},
       "entries": [
           # packed, with extras and an id that is not number-direction
           {"id": "1-across-2", "number": 1, "direction": "across",
            "position": {"x": 0, "y": 0}, "length": 3,
            "clue": {"text": "A b", "enumeration": "3", "separators": [{"at": 1, "mark": ","}],
                     "italics": [{"at": 2, "length": 1}]},
            "solution": "ABC",
            "annotation": {"type": ["anagram"], "answer": "ABC",
                           "assembly": {"pieces": ["A"], "anagrams": [{"fodder": "CAB", "gives": "ABC"}]},
                           "features": {"joke": None}}},
           # packed, nothing extra, a clue that is only text (packed as the string)
           {"id": "2-across", "number": 2, "direction": "across",
            "position": {"x": 0, "y": 2}, "length": 3, "clue": {"text": "f", "enumeration": "3"}, "solution": "FGH"},
           # packed, a blank clue
           {"id": "1-down", "number": 1, "direction": "down",
            "position": {"x": 0, "y": 0}, "length": 3, "clue": {"missing": True}, "solution": None},
           # not packable: no position, an unknown direction, a string number
           {"id": "2-down", "number": 2, "direction": "down", "length": 3,
            "clue": {"text": "c", "enumeration": "3"}, "solution": "CDE"},
           {"id": "3-sideways", "number": 3, "direction": "sideways",
            "position": {"x": 1, "y": 1}, "length": 1, "clue": {"text": "d", "enumeration": "1"}, "solution": "D"},
           {"id": "4-across", "number": "4", "direction": "across",
            "position": {"x": 2, "y": 2}, "length": 1, "clue": {"text": "e", "enumeration": "1"}, "solution": "E"},
       ]}
cases = [(Path(f"puzzles/{odd['id']}.json"), odd)]
cases += [(f, fp.read_puzzle_file(f)) for f in fp.puzzle_files()]
with open(out / "want", "w", encoding="utf-8") as want:
    for path, puzzle in cases:
        (out / "shims" / f"{puzzle['id']}.js").write_text(fp.shim_text(path, puzzle),
                                                        encoding="utf-8")
        want.write(json.dumps(fp.browser_puzzle(puzzle), ensure_ascii=False,
                              sort_keys=True, separators=(",", ":")) + "\n")
PY

node - "$TMP" <<'JS'
const fs = require("fs"), path = require("path");
const dir = process.argv[2];
const sorted = (v) => Array.isArray(v) ? v.map(sorted)
  : v && typeof v === "object"
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v;
const want = fs.readFileSync(path.join(dir, "want"), "utf8").split("\n").filter(Boolean);
const win = {};
let bad = 0, n = 0;
for (const line of want) {
  const id = JSON.parse(line).id;
  new Function("window", fs.readFileSync(path.join(dir, "shims", id + ".js"), "utf8"))(win);
  const got = JSON.stringify(sorted(win.CRYPTIC_PUZZLES[id]));
  n++;
  if (got !== line && bad++ < 3) {
    let i = 0;
    while (got[i] === line[i]) i++;
    console.log(`  FAIL: ${id} unpacks differently at char ${i}:\n    want ${line.slice(i - 60, i + 60)}\n    got  ${got.slice(i - 60, i + 60)}`);
  }
}
if (bad) { console.log(`shim_format: ${bad} of ${n} shims do not unpack to browser_puzzle()`); process.exit(1); }
console.log(`shim_format: all ${n} shims unpack to browser_puzzle()`);
JS
