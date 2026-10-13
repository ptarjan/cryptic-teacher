#!/usr/bin/env bash
# Does the schema and validator hold a format v2 file to v2's rules (no field
# that can be derived from others, a tree that gives the answer, no new
# unchecked steps) while every legacy file keeps passing as it is?
#
#     bash tools/test_format_v2.sh
#
# The shape is read off the file (tools/puzzle_schema.py format_problems): an
# annotation with `blocks` is legacy, one without is v2, and a file is wholly
# one shape. The v2 files here are legacy puzzles (tools/fixtures/legacy-puzzles,
# copies of corpus files from before the format v2 migration) run through
# tools/convert_v2.py convert_puzzle, in memory; nothing is written.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import json
import sys
from pathlib import Path

import annotation
import convert_v2
import fetch_puzzle as fp
import puzzle_schema as S
import validate_annotations as V

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

def refused(puzzle, needle):
    probs = S.validate(puzzle)
    return any(needle in p for p in probs), probs

# Two Guardian cryptics from the legacy fixtures that convert whole (one that
# no longer converts is skipped, not failed: the converter has its own test).
pairs = convert_v2.converted_samples(2)
check("found converted puzzles to test", len(pairs) == 2, len(pairs))
old, new, status = pairs[0]

# ---- legacy files keep passing, v2 files pass v2 ----
for o, n, _ in pairs:
    check(f"{o['id']}: the legacy file is legacy and passes", not S.is_v2(o) and S.validate(o) == [],
          S.validate(o)[:3])
    check(f"{o['id']}: its conversion is v2 and passes", S.is_v2(n) and S.validate(n) == [], S.validate(n)[:3])
    check(f"{o['id']}: the v2 file stores no name or series", "name" not in n and "series" not in n)

def first_tree(p, want=lambda node: True):
    """(entry, annotation, node) for the first node in a tree that `want` accepts."""
    for e in p["entries"]:
        a = e.get("annotation")
        stack = [a["wordplay"]] if a and a.get("wordplay") else []
        while stack:
            node = stack.pop(0)
            if want(node):
                return e, a, node
            stack += node.get("parts") or []
    raise SystemExit("no such node in " + p["id"])

# ---- every derived field is refused in a v2 file ----
for key, value in [("name", old["name"]), ("series", old["series"])]:
    p = copy.deepcopy(new)
    p[key] = value
    ok, probs = refused(p, f"key {key!r} is refused")
    check(f"v2 refuses a stored top-level {key}", ok, probs[:3])
for key, value in [("type", ["charade"]), ("answer", "X"), ("linkWords", ["and"]),
                   ("indicators", [{"text": "x", "for": "anagram"}]), ("assembly", {"pieces": ["A", "B"]})]:
    p = copy.deepcopy(new)
    _, a, _ = first_tree(p)
    a[key] = value
    ok, probs = refused(S.order(p), f"key {key!r} is refused: derived")
    check(f"v2 refuses a stored annotation {key}", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: n.get("indicators"))
node["indicators"][0]["for"] = "anagram"
ok, probs = refused(S.order(p), "key 'for' is refused")
check("v2 refuses an indicator's `for`", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: "op" in n and not n.get("unchecked"))
node["gives"] = "ABC"
ok, probs = refused(S.order(p), "key 'gives' is refused")
check("v2 refuses `gives` on a checked op (the evaluator works it out)", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: "words" in n and not n.get("unchecked"))
node["select"] = "first"
ok, probs = refused(S.order(p), "key 'select' is refused")
check("v2 refuses legacy `select` on a checked leaf", ok, probs[:3])
p = copy.deepcopy(new)
e, a, _ = first_tree(p)
a["spelling"] = annotation.display_answer(e, p)
ok, probs = refused(S.order(p), "leave `spelling` out")
check("v2 refuses a `spelling` equal to the derived answer", ok, probs[:3])
a["spelling"] = annotation.display_answer(e, p).lower()
check("and keeps one that differs", not any("spelling" in x for x in S.validate(S.order(p))))

# ---- one shape a file ----
p = copy.deepcopy(new)
i = next(i for i, e in enumerate(old["entries"]) if e.get("annotation"))
p["entries"][i]["annotation"] = old["entries"][i]["annotation"]
ok, probs = refused(p, "a legacy annotation (it has `blocks`) in a format v2 file")
check("a legacy annotation in a v2 file is refused", ok, probs[:3])
p = copy.deepcopy(old)
p["entries"][i]["annotation"] = copy.deepcopy(p["entries"][i]["annotation"])
p["entries"][i]["annotation"]["andLit"] = True
ok, probs = refused(S.order(p), "key 'andLit' is refused: a format v2 key")
check("a v2 key on a legacy annotation is refused", ok, probs[:3])
p = copy.deepcopy(old)
p["prize"] = True
ok, probs = refused(S.order(p), "key 'prize' is format v2's")
check("a legacy file may not carry v2's `prize`", ok, probs[:3])
p = copy.deepcopy(old)
del p["series"]
for e in p["entries"]:
    e.pop("annotation", None)
ok, probs = refused(p, "key 'name' is refused")
check("a file without series is read as v2, so its stored name is refused", ok, probs[:3])
p = copy.deepcopy(old)
del p["name"]
ok, probs = refused(p, "missing required key 'name'")
check("a legacy file still needs its name", ok, probs[:3])

# ---- the write path (fetch_puzzle.write_puzzle_file -> puzzle_integrity.refuse_bad_write) ----
# A v2 file stores no series: puzzle_integrity reads it off the id (series.of),
# so a v2 file can be written, over itself or over its legacy copy, while a
# broken legacy file is still refused. In a temp dir outside the corpus.
import tempfile
import puzzle_integrity as PI
def write(p, d):
    try:
        fp.write_puzzle_file(Path(d) / f"{p['id']}.json", p)
        return None
    except PI.RefusedWrite as e:
        return str(e)
with tempfile.TemporaryDirectory() as d:
    check("a v2 file is written", write(new, d) is None, write(new, d))
    check("and written again over itself", write(new, d) is None, write(new, d))
with tempfile.TemporaryDirectory() as d:
    write(old, d)
    check("a v2 file is written over its legacy copy (the migration's rewrite)", write(new, d) is None, write(new, d))
book = fp.read_puzzle_file(sorted((Path(convert_v2.LEGACY_FIXTURES) / "book").rglob("*.json"))[0])
if True:
    with tempfile.TemporaryDirectory() as d:
        bn, _ = convert_v2.migrate_puzzle(book)
        check("a v2 book puzzle keeps its year and no date (series read off the id)", write(bn, d) is None, write(bn, d))
for name, mutate, needle in (
        ("a legacy file without series", lambda p: p.pop("series"), "key 'name' is refused"),
        ("a legacy file without name", lambda p: p.pop("name"), "missing required key 'name'"),
        ("a legacy file whose series contradicts its id", lambda p: p.update(series="times"), "but the id says")):
    p = copy.deepcopy(old)
    mutate(p)
    with tempfile.TemporaryDirectory() as d:
        got = write(p, d)
    check(f"{name} is refused on write", got is not None and needle in got, got)
# A v2 puzzle handed to the writer with a series and name (a fetcher builds
# both fresh from the page) is written as v2: the writer drops them, and the
# schema still refuses them in the file itself.
p = copy.deepcopy(new)
p.update(series="cryptic", name="Cryptic crossword No " + str(p.get("number", "")))
check("a stored series in a v2 file is refused by the schema",
      refused(p, "key 'series' is refused")[0], S.validate(p)[:3])
with tempfile.TemporaryDirectory() as d:
    got = write(p, d)
    on_disk = json.loads((Path(d) / f"{p['id']}.json").read_text()) if got is None else {}
check("a v2 puzzle written with series and name is filed without them",
      got is None and "series" not in on_disk and "name" not in on_disk, (got, sorted(on_disk)[:12]))

# ---- the validator reads view(): same findings, and the tree is checked ----
for o, n, st in pairs:
    _, errs_old, _ = V.validate_puzzle(o, corpus=True)
    _, errs_new, warns_new = V.validate_puzzle(n, corpus=True)
    exact = [w for w, s in st.items() if s == "exact"]
    tags = {V._tag_of(o, w) for w in exact}
    pick = lambda errs: sorted(x for x in errs if x.split(":", 1)[0] in tags)
    check(f"{o['id']}: exact-converted clues get the same errors from either shape",
          pick(errs_old) == pick(errs_new), (pick(errs_old)[:3], pick(errs_new)[:3]))
    check(f"{o['id']}: no wordplay or schema error on the converted file",
          not [x for x in errs_new if "wordplay:" in x or x.startswith("schema:")], errs_new[:3])
p = copy.deepcopy(new)
e, a, node = first_tree(p, lambda n: "words" in n and n.get("gives") and not n.get("unchecked"))
node["gives"] = node["gives"] + "Q"
_, errs, _ = V.validate_puzzle(p, corpus=True)
tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
check("a tree that does not give the answer is a validator error",
      any(x.startswith(f"{tag}: wordplay: ") for x in errs), errs[:3])

# An unchecked step: a warning the ratchet counts, and an allowance of none.
p = copy.deepcopy(new)
e, a, _ = first_tree(p)
a["wordplay"] = {"op": "deletion", "unchecked": True, "gives": V.letters(e["solution"]),
                 "parts": [a["wordplay"]]}
_, errs, warns = V.validate_puzzle(S.order(p), corpus=True)
check("an unchecked step warns with the ratchet's marker",
      any(V.UNCHECKED_STEP in w for w in warns), warns[:3])
counts = V.count_backlog(warns)
check("and the ratchet counts its clue", counts["wordplay.unchecked"] >= 1, counts)
check("a puzzle the backlog allows none gets an error",
      bool(V.backlog_errors(p["id"], warns, {"wordplay.unchecked": {}})))

# What the site sees of a v2 file (browser_puzzle reads view()) is
# tools/test_shim_format.sh's and tools/smoke_test.js's to check.

# ---- every reader of a derived field gives the same output for either shape ----
# Each reader below reads name/series/type/blocks/answer/indicators/linkWords/
# assembly of a puzzle FILE. Two comparisons per reader, on temp copies:
#   same  - the legacy file against the v2 file. Holds for a reader that does not
#           look inside the wordplay (series, name, annotated or not, the preamble
#           flag, a clue's coverage).
#   plumb - the v2 file against a legacy file holding annotation.view_puzzle() of
#           it. The conversion rewrites wordplay on purpose (a derived type, no
#           assembly.pieces, the order of blocks), so a reader that counts types or
#           blocks gives different numbers for the two ORIGINAL files; against the
#           view as a legacy file it must give the same, which proves the reader
#           goes through view_puzzle and reads nothing the v2 file lacks.
import tempfile
import subprocess

import annotation
import await_preamble
import difficulty
import letter_facts
import puzzle_integrity
import puzzle_style
import series as series_meta
import showcase

samples = convert_v2.converted_samples(3)
check("found puzzles to hold the readers to", len(samples) >= 2, len(samples))
tmp = Path(tempfile.mkdtemp(prefix="format_v2_readers_"))
for o, n, _ in samples:
    pid = o["id"]
    paths = {}
    for shape, doc in (("legacy", o), ("v2", n), ("view", annotation.view_puzzle(n))):
        d = tmp / shape
        d.mkdir(exist_ok=True)
        paths[shape] = d / f"{pid}.json"
        paths[shape].write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    check(f"{pid}: the 'view' copy is legacy-shaped (name, series, blocks) and the v2 copy is not",
          not S.is_v2(json.loads(paths["view"].read_text())) and S.is_v2(json.loads(paths["v2"].read_text())))
    check(f"{pid}: read_puzzle_view gives a v2 file's series and name",
          fp.read_puzzle_view(paths["v2"])["series"] == o["series"]
          and fp.read_puzzle_view(paths["v2"])["name"] == o["name"])
    check(f"{pid}: read_puzzle_view leaves a legacy file as it is", fp.read_puzzle_view(paths["legacy"]) == o)
    check(f"{pid}: series.of reads a raw v2 file", series_meta.of(n) == o["series"])

    def flags_of(path):
        flags = []
        puzzle_integrity.check_puzzle(fp.read_puzzle_view(path), __import__("datetime").date(2099, 1, 1), flags)
        return flags
    readers = {
        "fetch_puzzle.corpus_row (the README's corpus line)": (fp.corpus_row, True),
        "fetch_puzzle.index_row (the reindex's index row)":
            (lambda p: {k: v for k, v in fp.index_row(p).items() if k != "hash"}, False),
        "puzzle_style.style": (lambda p: puzzle_style.style(fp.read_puzzle_view(p)), True),
        "difficulty.history_row": (difficulty.history_row, True),
        "difficulty.clue_row": (difficulty.clue_row, False),
        "showcase.file_facts": (lambda p: showcase.file_facts(fp.read_puzzle_view(p)), True),
        "await_preamble.which": (lambda p: await_preamble.which(p, fp.read_puzzle_file(p)), True),
        "puzzle_integrity._summary (the cross-file row)": (puzzle_integrity._summary, True),
        "puzzle_integrity.check_puzzle flags": (flags_of, False),
        "letter_facts.read_view": (letter_facts.read_view, False),
    }
    for name, (read, same) in readers.items():
        try:
            got = {s: read(paths[s]) for s in paths}
        except Exception as e:
            check(f"{pid}: {name} runs on every shape", False, f"{type(e).__name__}: {e}")
            continue
        check(f"{pid}: {name}: v2 file gives what its view gives as a legacy file",
              got["v2"] == got["view"], (str(got["v2"])[:200], str(got["view"])[:200]))
        if same:
            check(f"{pid}: {name}: and what the legacy original gives", got["v2"] == got["legacy"],
                  (str(got["v2"])[:200], str(got["legacy"])[:200]))

    # The node harnesses read the generated shim, not the source: puzzle_paths.js
    # readView() loads puzzles/<id>.js, whose fields browser_puzzle derives.
    # Write each shape's shim beside its file and read both through node.
    js = r"""
const pp = require(process.argv[1] + "/puzzle_paths.js");
const [file, dir] = [process.argv[2], process.argv[3]];
const p = pp.readView(file, dir);
process.stdout.write(JSON.stringify({series: p.series, name: p.name, ann: p.entries.map((e) => {
  const a = e.annotation; return a && {type: a.type, answer: a.answer, blocks: a.blocks, linkWords: a.linkWords,
  indicators: a.indicators, anagrams: (a.assembly || {}).anagrams}; })}));
"""
    outs = {}
    for shape in ("v2", "view"):
        shim = fp.shim_path(paths[shape])
        shim.write_text(fp.shim_text(paths[shape], fp.read_puzzle_view(paths[shape])), encoding="utf-8")
        run = subprocess.run(["node", "-e", js, str(Path(__file__).resolve().parent) if "__file__" in globals()
                              else str(Path.cwd()), str(paths[shape]), str(paths[shape].parent)],
                             capture_output=True, text=True)
        outs[shape] = run.stdout if run.returncode == 0 else run.stderr[-300:]
    check(f"{pid}: puzzle_paths.js readView gives a v2 file the shim's derived fields (same as its view)",
          outs["v2"] == outs["view"] and outs["v2"].startswith("{"), (outs["v2"][:200], outs["view"][:200]))

print("PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
PY
