#!/usr/bin/env bash
# Does the format v2 migration (tools/convert_v2.py --migrate, plan step 8)
# leave files every gate passes, and is it safe to kill and start again?
#
#     bash tools/test_migrate_v2.sh [PER_SERIES]     # default 2 annotated + 1 plain per series
#     CT_SMOKE=1 bash tools/test_migrate_v2.sh 7     # ~200 files, and smoke_test.js boots them all
#
# A random sample of every series is copied to a temp dir and migrated there
# (the real corpus is not touched, and nothing is committed). Then, file by
# file against its legacy copy:
#   * it is format v2 and puzzle_schema.validate finds nothing;
#   * puzzle_integrity.refuse_bad_write finds nothing it did not find on the legacy file;
#   * validate_annotations (the deploy's corpus rules) reports no error the legacy
#     file did not, and the ratchet passes on the backlog the migration wrote
#     (every unchecked step allowed under wordplay.unchecked, no other field over);
#   * the browser sees the same puzzle (browser_puzzle): puzzle-level fields
#     equal (name normalised where puzzle_names says so), nothing differs
#     outside an annotation, an exactly converted annotation is identical, and a
#     redone clue has no annotation;
#   * its shim unpacks in JavaScript to that browser puzzle.
# A second --migrate over the same dir finds nothing to do and changes nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
PER="${1:-2}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PYTHONPATH=tools python3 - "$TMP" "$PER" <<'PY'
import json, os, random, shutil, sys
tmp, per = sys.argv[1], int(sys.argv[2])
random.seed(per)
n = 0
for s in sorted(os.listdir("puzzles")):
    if not os.path.isdir(os.path.join("puzzles", s)):
        continue
    fs = sorted(os.path.join(dp, f) for dp, _, ff in os.walk(os.path.join("puzzles", s))
                for f in ff if f.endswith(".json"))
    ann, plain = [], []
    for f in random.sample(fs, min(len(fs), 40)):
        with open(f) as fh:
            p = json.load(fh)
        (ann if any(e.get("annotation") for e in p.get("entries", [])) else plain).append(f)
    for f in ann[:per] + plain[:1]:
        for d in ("legacy", "puzzles"):
            dst = os.path.join(tmp, d, os.path.relpath(f, "puzzles"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(f, dst)
        n += 1
print(f"migrate_v2: sampled {n} puzzle files")
PY
cp tools/annotation_backlog.json "$TMP/backlog.json"
mkdir "$TMP/seed" && cp -r "$TMP/legacy" "$TMP/seed/puzzles" && cp tools/annotation_backlog.json "$TMP/seed/backlog.json"
PYTHONHASHSEED=1 python3 tools/convert_v2.py "$TMP/puzzles" --migrate --backlog "$TMP/backlog.json" | sed 's/^/migrate_v2: /'
# The validator re-evaluates every tree in another process, so the converter
# and the evaluator may not lean on set order: another hash seed, the same bytes.
PYTHONHASHSEED=2 python3 tools/convert_v2.py "$TMP/seed/puzzles" --migrate --backlog "$TMP/seed/backlog.json" >/dev/null
find "$TMP/puzzles" -name '*.json' -exec md5sum {} + | sort > "$TMP/sums1"
again="$(python3 tools/convert_v2.py "$TMP/puzzles" --migrate --backlog "$TMP/backlog.json" 2>&1)"
find "$TMP/puzzles" -name '*.json' -exec md5sum {} + | sort > "$TMP/sums2"
fails=0
if diff -rq "$TMP/puzzles" "$TMP/seed/puzzles" >/dev/null && cmp -s "$TMP/backlog.json" "$TMP/seed/backlog.json"; then
  echo "ok   another hash seed migrates to the same bytes"
else
  echo "FAIL the migration depends on the hash seed: $(diff -rq "$TMP/puzzles" "$TMP/seed/puzzles" | head -3)"; fails=1
fi
if grep -q ", 0 to go" <<<"$again" && cmp -s "$TMP/sums1" "$TMP/sums2"; then
  echo "ok   a second --migrate finds nothing to do and changes nothing"
else
  echo "FAIL a second --migrate redid work or changed files: $(head -1 <<<"$again")"; fails=1
fi
mkdir "$TMP/shims"

PYTHONPATH=tools python3 - "$TMP" <<'PY' || fails=1
import json, sys
from pathlib import Path
import convert_v2
import fetch_puzzle as fp
import puzzle_schema as S
import validate_annotations as V
from wordplay import letters as fp_letters

tmp = Path(sys.argv[1])
allowed = V.load_backlog()
with open(tmp / "backlog.json") as fh:
    data = json.load(fh)
allowed = {f: data[f] for f in V.BACKLOG_MARKERS if f in data}
bad = {k: [] for k in ("shape", "schema", "integrity", "validator", "ratchet", "browser")}
counts = {"files": 0, "exact": 0, "redone": 0}

def clue_ordered(e):
    # What an exact conversion may still show differently: view() lists
    # indicators in clue order, and writes an anagram's fodder as bare letters
    # in its own order where a legacy file kept the words and their order (the ring deals
    # letters either way).
    a = e.get("annotation")
    if not a:
        return e
    text = e["clue"]["text"]
    a = {**a, "indicators": sorted(a.get("indicators") or [], key=lambda i: text.find(i["text"]))}
    if (a.get("assembly") or {}).get("anagrams"):
        a["assembly"] = {**a["assembly"], "anagrams": [{**x, "fodder": sorted(fp_letters(x.get("fodder") or ""))}
                                                       for x in a["assembly"]["anagrams"]]}
    return {**e, "annotation": a}

def errs(p):
    _, e, w = V.validate_puzzle(p, corpus=True)
    return e, w

with open(tmp / "want", "w", encoding="utf-8") as want:
    for f in sorted((tmp / "puzzles").rglob("*.json")):
        new = fp.read_puzzle_file(f)
        old = fp.read_puzzle_file(tmp / "legacy" / f.relative_to(tmp / "puzzles"))
        pid = new["id"]
        counts["files"] += 1
        if not S.is_v2(new):
            bad["shape"].append(pid)
        bad["schema"] += [f"{pid}: {p}" for p in S.validate(new)]
        extra = convert_v2._findings(new, old) - convert_v2._findings(old, old)
        bad["integrity"] += [f"{pid}: {fl} {w}" for fl, w in sorted(extra)]
        (eo, _), (en, wn) = errs(old), errs(new)
        bad["validator"] += [f"{pid}: {x}" for x in en if x not in eo]
        bad["ratchet"] += [f"{pid}: {x}" for x in V.backlog_errors(pid, wn, allowed)]
        bo, bn = fp.browser_puzzle(old), fp.browser_puzzle(new)
        _, renamed = convert_v2.puzzle_names(old)
        top = sorted(k for k in set(bo) | set(bn) if k != "entries" and bo.get(k) != bn.get(k)
                     and not (k == "name" and renamed))
        bad["browser"] += [f"{pid}: puzzle-level fields differ: {top}"] if top else []
        # A redone clue shows the blog's parse where it had ours (browser_puzzle's fallback).
        bare = lambda e, redone: {k: v for k, v in e.items() if k != "annotation" and not (redone and k == "blog")}
        for i, (x, y) in enumerate(zip(bo["entries"], bn["entries"])):
            redone = bool(x.get("annotation")) and not y.get("annotation")
            if bare(x, redone) != bare(y, redone):
                bad["browser"].append(f"{pid} entries[{i}]: differs outside its annotation")
            ann = old["entries"][i].get("annotation")
            if not ann:
                continue
            st = convert_v2.check(ann, old["entries"][i], old)[0]
            if st == "failed":
                counts["redone"] += 1
                if "annotation" in new["entries"][i]:
                    bad["browser"].append(f"{pid} entries[{i}]: a failed clue kept its annotation")
            elif st == "exact":
                counts["exact"] += 1
                if clue_ordered(x) != clue_ordered(y):
                    bad["browser"].append(f"{pid} entries[{i}]: exact conversion, but the browser sees it differently")
        if len(bo["entries"]) != len(bn["entries"]):
            bad["browser"].append(f"{pid}: entry count changed")
        (tmp / "shims" / f"{pid}.js").write_text(fp.shim_text(f, new), encoding="utf-8")
        want.write(json.dumps(bn, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

names = {"shape": "every migrated file is format v2",
         "schema": "puzzle_schema.validate finds nothing",
         "integrity": "puzzle_integrity's write check finds nothing new",
         "validator": "validate_annotations reports no new error",
         "ratchet": "the ratchet passes on the backlog the migration wrote",
         "browser": "the browser sees the same puzzles (exact clues identical, redone clues bare)"}
for k, why in names.items():
    print(("ok  " if not bad[k] else "FAIL"), why, "" if not bad[k] else
          f"({len(bad[k])}): " + "; ".join(bad[k][:5]))
print(f"migrate_v2: {counts['files']} files, {counts['exact']} exact annotations compared, "
      f"{counts['redone']} redone")
raise SystemExit(any(bad.values()))
PY

node - "$TMP" <<'JS' || fails=1
const fs = require("fs"), path = require("path");
const dir = process.argv[2];
const sorted = (v) => Array.isArray(v) ? v.map(sorted)
  : v && typeof v === "object"
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v;
const win = {};
let bad = 0, n = 0;
for (const line of fs.readFileSync(path.join(dir, "want"), "utf8").split("\n").filter(Boolean)) {
  const id = JSON.parse(line).id;
  new Function("window", fs.readFileSync(path.join(dir, "shims", id + ".js"), "utf8"))(win);
  n++;
  if (JSON.stringify(sorted(win.CRYPTIC_PUZZLES[id])) !== line && bad++ < 3) console.log(`  ${id} unpacks differently`);
}
console.log(bad ? `FAIL ${bad} of ${n} migrated shims do not unpack to browser_puzzle()`
  : `ok   all ${n} migrated shims unpack to browser_puzzle()`);
process.exit(bad ? 1 : 0);
JS

if [ -n "${CT_SMOKE:-}" ]; then
  if CT_SMOKE_V2="$TMP/legacy:$TMP/puzzles" node tools/smoke_test.js > "$TMP/smoke.out" 2>&1; then
    echo "ok   smoke_test.js boots every migrated puzzle and climbs its ladders ($(tail -1 "$TMP/smoke.out"))"
  else
    echo "FAIL smoke_test.js on the migrated sample:"; grep -E 'FAIL|format v2' "$TMP/smoke.out" | head -10; fails=1
  fi
fi
exit "$fails"
