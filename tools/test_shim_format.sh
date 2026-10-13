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
           # packed, with extras
           {"number": 1, "direction": "across",
            "position": {"x": 0, "y": 0}, "length": 3,
            "clue": {"text": "A b", "enumeration": "3", "separators": [{"at": 1, "mark": ","}],
                     "italics": [{"at": 2, "length": 1}]},
            "solution": "ABC",
            "annotation": {"type": ["anagram"], "answer": "ABC",
                           "assembly": {"pieces": ["A"], "anagrams": [{"fodder": "CAB", "gives": "ABC"}]},
                           "features": {"joke": None}}},
           # packed, nothing extra, a clue that is only text (packed as the string)
           {"number": 2, "direction": "across",
            "position": {"x": 0, "y": 2}, "length": 3, "clue": {"text": "f", "enumeration": "3"}, "solution": "FGH"},
           # packed, a blank clue
           {"number": 1, "direction": "down",
            "position": {"x": 0, "y": 0}, "length": 3, "clue": {"missing": True}, "solution": None},
           # not packable: no position, an unknown direction, a string number
           {"number": 2, "direction": "down", "length": 3,
            "clue": {"text": "c", "enumeration": "3"}, "solution": "CDE"},
           {"number": 3, "direction": "sideways",
            "position": {"x": 1, "y": 1}, "length": 1, "clue": {"text": "d", "enumeration": "1"}, "solution": "D"},
           {"number": "4", "direction": "across",
            "position": {"x": 2, "y": 2}, "length": 1, "clue": {"text": "e", "enumeration": "1"}, "solution": "E"},
       ]}
cases = [(Path(f"puzzles/{odd['id']}.json"), odd)]
cases += [(f, fp.read_puzzle_file(f)) for f in fp.puzzle_files()]

# Format v2: a converted puzzle shows the browser what its legacy file did.
# browser_puzzle reads annotation.view_puzzle(), which derives name, series
# and every annotation field the app reads. Converted in memory (nothing is
# written), and those puzzles' shims below are the v2 ones, so the JavaScript
# unpack is held to them too.
import convert_v2
v2 = convert_v2.converted_samples(2)
bad = [] if len(v2) == 2 else [f"found {len(v2)} converted puzzles, want 2"]
def clue_ordered(e):
    # The one difference an exact conversion may show: view() lists
    # indicators in clue order, where a legacy file sometimes stored them otherwise.
    a = e.get("annotation")
    if not a or not a.get("indicators"):
        return e
    text = e["clue"]["text"]
    return {**e, "annotation": {**a, "indicators": sorted(a["indicators"], key=lambda i: text.find(i["text"]))}}
for old, new, status in v2:
    bo, bn = fp.browser_puzzle(old), fp.browser_puzzle(new)
    top = sorted(k for k in set(bo) | set(bn) if k != "entries" and bo.get(k) != bn.get(k))
    bad += [f"{old['id']}: browser puzzle-level fields differ: {top}"] if top else []
    exact = {int(w.split("[")[1].split("]")[0]) for w, s in status.items()
             if s == "exact" and ".alsoLeads" not in w}
    bad += [f"{old['id']} entries[{i}]: exact conversion, but the browser sees a different entry"
            for i in sorted(exact) if clue_ordered(bo["entries"][i]) != clue_ordered(bn["entries"][i])]
    bare = lambda e: {k: v for k, v in e.items() if k != "annotation"}
    bad += [f"{old['id']} entries[{i}]: differs outside its annotation"
            for i, (x, y) in enumerate(zip(bo["entries"], bn["entries"])) if bare(x) != bare(y)]
    print(f"shim_format: {old['id']} as format v2 shows the browser its legacy fields "
          f"({len(exact)} of {len(status)} annotations converted exactly, the rest normalised)")
if bad:
    print("  FAIL: " + "\n  FAIL: ".join(bad))
    sys.exit(1)
converted = {old["id"]: new for old, new, _ in v2}
cases = [(path, converted.get(p["id"], p)) for path, p in cases]
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
// The corpus's expected puzzles together outgrow one JS string (Node caps it near
// 512 MB), so "want" is read a line at a time, never whole.
function* lines(file) {
  const fd = fs.openSync(file, "r"), buf = Buffer.alloc(1 << 20);
  let rest = Buffer.alloc(0), got;
  while ((got = fs.readSync(fd, buf, 0, buf.length, null)) > 0) {
    rest = Buffer.concat([rest, buf.subarray(0, got)]);
    for (let nl; (nl = rest.indexOf(10)) >= 0; rest = rest.subarray(nl + 1)) {
      if (nl) yield rest.subarray(0, nl).toString("utf8");
    }
  }
  fs.closeSync(fd);
  if (rest.length) yield rest.toString("utf8");
}
const win = {};
let bad = 0, n = 0;
for (const line of lines(path.join(dir, "want"))) {
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
