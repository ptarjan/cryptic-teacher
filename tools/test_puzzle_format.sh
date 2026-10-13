#!/usr/bin/env bash
# Does the puzzle format hold: the schema refuses every field that can be
# derived from others (top-level name and series, an annotation's type, answer,
# blocks, ...), the validator evaluates each wordplay tree against its answer
# and ratchets unchecked steps, view() / view_puzzle() derive what readers
# need, and series.name_facts turns a fetched name into the prize, title or
# label display_name needs?
#
#     bash tools/test_puzzle_format.sh
#
# The puzzles here are tools/fixtures/format-puzzles (three Guardian cryptics
# and a book puzzle, frozen copies of corpus files), edited in memory or in temp
# dirs; nothing in the corpus is read or written.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import annotation
import fetch_puzzle as fp
import puzzle_integrity as PI
import puzzle_schema as S
import series as series_meta
import validate_annotations as V
import wordplay

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

def refused(puzzle, needle):
    probs = S.validate(puzzle)
    return any(needle in p for p in probs), probs

FIXTURES = Path("fixtures/format-puzzles")
cryptics = [fp.read_puzzle_file(f) for f in sorted((FIXTURES / "cryptic").glob("*.json"))]
book = fp.read_puzzle_file(sorted((FIXTURES / "book").glob("*.json"))[0])
check("found the format fixtures", len(cryptics) == 3, len(cryptics))
new = cryptics[-1]

# ---- the fixtures pass, and store nothing derivable ----
for p in cryptics + [book]:
    check(f"{p['id']}: passes the schema", S.validate(p) == [], S.validate(p)[:3])
    check(f"{p['id']}: stores no name or series", "name" not in p and "series" not in p)
    check(f"{p['id']}: no annotation stores a derived key",
          not [k for _, _, a in S.annotations(p) for k in annotation.DERIVED_KEYS if k in a and k != "definitions"])

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

# ---- every derived field is refused ----
for key, value in [("name", "Cryptic crossword No 30,136"), ("series", "cryptic")]:
    p = copy.deepcopy(new)
    p[key] = value
    ok, probs = refused(p, f"key {key!r} is refused")
    check(f"the schema refuses a stored top-level {key} on a puzzle file", ok, probs[:3])
p = copy.deepcopy(book)
p.update(series="book", name=series_meta.display_name(book))
ok, probs = refused(p, "key 'series' is refused")
check("and on a book puzzle, both at once", ok and refused(p, "key 'name' is refused")[0], probs[:3])
for key, value in [("type", ["charade"]), ("answer", "X"), ("linkWords", ["and"]), ("blocks", [{"clueFragment": "x"}]),
                   ("indicators", [{"text": "x", "for": "anagram"}]), ("assembly", {"pieces": ["A", "B"]})]:
    p = copy.deepcopy(new)
    _, a, _ = first_tree(p)
    a[key] = value
    ok, probs = refused(S.order(p), f"key {key!r} is refused: derived")
    check(f"the schema refuses a stored annotation {key}", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: n.get("indicators"))
node["indicators"][0]["for"] = "anagram"
ok, probs = refused(S.order(p), "key 'for' is refused")
check("the schema refuses an indicator's `for`", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: "op" in n and not n.get("unchecked"))
node["gives"] = "ABC"
ok, probs = refused(S.order(p), "key 'gives' is refused")
check("the schema refuses `gives` on a checked op (the evaluator works it out)", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: "words" in n and not n.get("unchecked"))
node["select"] = "first"
ok, probs = refused(S.order(p), "key 'select' is refused")
check("the schema refuses `select` on a checked leaf", ok, probs[:3])
p = copy.deepcopy(new)
e, a, _ = first_tree(p)
a["spelling"] = annotation.display_answer(e, p)
ok, probs = refused(S.order(p), "leave `spelling` out")
check("the schema refuses a `spelling` equal to the derived answer", ok, probs[:3])
a["spelling"] = annotation.display_answer(e, p).lower()
check("and keeps one that differs", not any("spelling" in x for x in S.validate(S.order(p))))
p = copy.deepcopy(new)
p["prize"] = True
check("a puzzle file may carry `prize` (a fact display_name needs)", S.validate(S.order(p)) == [], S.validate(p)[:3])

# ---- series.name_facts: a fetched name becomes the facts that rebuild it ----
for puzzle, want, why in [
        ({"id": "listener-4000", "number": 4000, "name": "Listener crossword No 4,000: Tobacco"},
         {"title": "Tobacco"}, "a Listener's printed title after the colon"),
        ({"id": "cryptic-30133", "number": 30133, "name": "Prize crossword No 30,133"},
         {"prize": True}, "a Guardian prize"),
        ({"id": "cryptic-30133", "number": 30133, "name": "Cryptic crossword No 30,133"},
         {}, "a name display_name derives as it is"),
        ({"id": "cryptic-30133", "number": 30133, "name": "Something the page called it"},
         {}, "a name no fact reaches is dropped for the derived one"),
        ({"id": "listener-4000", "number": 4000, "title": "Tobacco"},
         {"title": "Tobacco"}, "no name: the stored facts as they are")]:
    got = series_meta.name_facts(puzzle)
    check(f"series.name_facts: {why}", got == want, got)
dated = {"id": "canberra-670909", "number": 670909}
label = series_meta.display_name(dated) + " (Late edition)"
got = series_meta.name_facts({**dated, "name": label})
check("series.name_facts: a dated paper's edition in brackets is its label", got == {"label": "Late edition"}, (label, got))

# ---- view() and view_puzzle(): what every reader takes ----
v = annotation.view_puzzle(new)
check("view_puzzle derives series and name from the id",
      v["series"] == "cryptic" and v["name"] == series_meta.display_name(new), (v.get("series"), v.get("name")))
check("view_puzzle of a view is that view", annotation.view_puzzle(v) is v)
check("view_puzzle does not change the file it is given", "series" not in new)
e, a, _ = first_tree(new)
va = annotation.view(a, e, new)
check("view() derives type, answer and blocks from the tree",
      va["type"] and va["answer"].replace(" ", "") == V.letters(e["solution"]) and va["blocks"], va)
p = copy.deepcopy(new)
p["prize"] = True
check("view_puzzle folds `prize` into the name", annotation.view_puzzle(p)["name"].startswith("Prize crossword"),
      annotation.view_puzzle(p)["name"])
p = copy.deepcopy(new)
e, a, node = first_tree(p, lambda n: "words" in n and n.get("gives") and not n.get("unchecked"))
node["gives"] = node["gives"] + "Q"
problems = []
vp = annotation.view_puzzle(p, problems)
i = p["entries"].index(e)
check("view_puzzle leaves out an annotation whose tree does not give the answer, and says where",
      not vp["entries"][i].get("annotation") and problems, (problems[:2], bool(vp["entries"][i].get("annotation"))))
# The validator and the shim may run under any hash seed: view() may not lean on set order.
script = ("import json, sys; sys.path.insert(0, '.'); import annotation, fetch_puzzle as fp; from pathlib import Path\n"
          "print(json.dumps([annotation.view_puzzle(fp.read_puzzle_file(f)) for f in sorted(Path(sys.argv[1]).rglob('*.json'))],"
          " sort_keys=True, ensure_ascii=False))")
outs = {seed: subprocess.run([sys.executable, "-c", script, str(FIXTURES)], capture_output=True, text=True,
                             env={**os.environ, "PYTHONHASHSEED": seed}) for seed in ("1", "2")}
check("view_puzzle gives the same bytes under another hash seed",
      outs["1"].returncode == 0 and outs["1"].stdout == outs["2"].stdout, outs["1"].stderr[-300:])

# ---- from_model: the model's shape in, a stored annotation out ----
e = next(e for e in new["entries"] if e.get("annotation"))
try:
    annotation.from_model({"type": ["charade"], "answer": e["solution"], "blocks": [{"clueFragment": "x"}]}, e, new)
    got = None
except wordplay.WordplayError as err:
    got = str(err)
check("from_model refuses an old-prompt annotation, naming its unknown keys",
      got is not None and "unknown keys blocks, type" in got and "`wp`" in got, got)
check("is_model tells a model clue (def/wp) from a stored annotation",
      annotation.is_model({"def": "x", "wp": "y"}) and not annotation.is_model(e["annotation"]))

# ---- the write path (fetch_puzzle.write_puzzle_file -> puzzle_integrity.refuse_bad_write) ----
# A file stores no series: puzzle_integrity reads it off the id (series.of).
# In a temp dir outside the corpus.
def write(p, d):
    try:
        fp.write_puzzle_file(Path(d) / f"{p['id']}.json", p)
        return None
    except PI.RefusedWrite as e:
        return str(e)
with tempfile.TemporaryDirectory() as d:
    check("a puzzle file is written", write(new, d) is None, write(new, d))
    check("and written again over itself", write(new, d) is None, write(new, d))
with tempfile.TemporaryDirectory() as d:
    check("a book puzzle keeps its year and no date (series read off the id)", write(book, d) is None, write(book, d))
# A fetcher builds series and name fresh from the page: the writer files the
# puzzle without them, keeping only what name_facts says the name needs.
for name, want in [("Cryptic crossword No " + f"{new['number']:,}", {}),
                   ("Prize crossword No " + f"{new['number']:,}", {"prize": True})]:
    p = copy.deepcopy(new)
    p.update(series="cryptic", name=name)
    with tempfile.TemporaryDirectory() as d:
        got = write(p, d)
        on_disk = json.loads((Path(d) / f"{p['id']}.json").read_text()) if got is None else {}
    check(f"a puzzle written with series and name {name!r} is filed without them, with {want or 'no facts'}",
          got is None and "series" not in on_disk and "name" not in on_disk
          and {k: on_disk[k] for k in S.NAME_KEYS if k in on_disk} == want, (got, sorted(on_disk)[:12]))

# ---- the validator evaluates the tree, and ratchets unchecked steps ----
for p in cryptics + [book]:
    _, errs, _ = V.validate_puzzle(p, corpus=True)
    check(f"{p['id']}: no wordplay or schema error", not [x for x in errs if "wordplay:" in x or x.startswith("schema:")],
          errs[:3])
p = copy.deepcopy(new)
e, a, node = first_tree(p, lambda n: "words" in n and n.get("gives") and not n.get("unchecked"))
node["gives"] = node["gives"] + "Q"
_, errs, _ = V.validate_puzzle(p, corpus=True)
tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
check("a tree that does not give the answer is a validator error",
      any(x.startswith(f"{tag}: wordplay: ") for x in errs), errs[:3])
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

# ---- every reader of a derived field reads it through view_puzzle ----
# Each reader below reads name/series/type/blocks/answer/indicators/linkWords/
# assembly. Each runs on a puzzle file and on a file holding view_puzzle() of
# it: the same output proves the reader goes through view_puzzle and reads
# nothing the file lacks.
import await_preamble
import difficulty
import letter_facts
import puzzle_integrity
import puzzle_style
import showcase

tmp = Path(tempfile.mkdtemp(prefix="puzzle_format_readers_"))
for n in cryptics:
    pid = n["id"]
    paths = {}
    for shape, doc in (("file", n), ("view", annotation.view_puzzle(n))):
        d = tmp / shape
        d.mkdir(exist_ok=True)
        paths[shape] = d / f"{pid}.json"
        paths[shape].write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    check(f"{pid}: read_puzzle_view gives the file's series and name",
          fp.read_puzzle_view(paths["file"])["series"] == "cryptic"
          and fp.read_puzzle_view(paths["file"])["name"] == series_meta.display_name(n))
    check(f"{pid}: series.of reads a raw file", series_meta.of(n) == "cryptic")

    def flags_of(path):
        flags = []
        puzzle_integrity.check_puzzle(fp.read_puzzle_view(path), __import__("datetime").date(2099, 1, 1), flags)
        return flags
    readers = {
        "fetch_puzzle.corpus_row (the README's corpus line)": fp.corpus_row,
        "fetch_puzzle.index_row (the reindex's index row)":
            lambda p: {k: v for k, v in fp.index_row(p).items() if k != "hash"},
        "puzzle_style.style": lambda p: puzzle_style.style(fp.read_puzzle_view(p)),
        "difficulty.history_row": difficulty.history_row,
        "difficulty.clue_row": difficulty.clue_row,
        "showcase.file_facts": lambda p: showcase.file_facts(fp.read_puzzle_view(p)),
        "await_preamble.which": lambda p: await_preamble.which(p, fp.read_puzzle_file(p)),
        "puzzle_integrity._summary (the cross-file row)": puzzle_integrity._summary,
        "puzzle_integrity.check_puzzle flags": flags_of,
        "letter_facts.read_view": letter_facts.read_view,
    }
    for name, read in readers.items():
        try:
            got = {s: read(paths[s]) for s in paths}
        except Exception as e:
            check(f"{pid}: {name} runs on a file and its view", False, f"{type(e).__name__}: {e}")
            continue
        check(f"{pid}: {name}: the file gives what its view gives",
              got["file"] == got["view"], (str(got["file"])[:200], str(got["view"])[:200]))

    # The node harnesses read the generated shim, not the source: puzzle_paths.js
    # readView() loads puzzles/<id>.js, whose fields browser_puzzle derives.
    js = r"""
const pp = require(process.argv[1] + "/puzzle_paths.js");
const [file, dir] = [process.argv[2], process.argv[3]];
const p = pp.readView(file, dir);
process.stdout.write(JSON.stringify({series: p.series, name: p.name, ann: p.entries.map((e) => {
  const a = e.annotation; return a && {type: a.type, answer: a.answer, blocks: a.blocks, linkWords: a.linkWords,
  indicators: a.indicators, anagrams: (a.assembly || {}).anagrams}; })}));
"""
    outs = {}
    for shape in paths:
        shim = fp.shim_path(paths[shape])
        shim.write_text(fp.shim_text(paths[shape], fp.read_puzzle_view(paths[shape])), encoding="utf-8")
        run = subprocess.run(["node", "-e", js, str(Path.cwd()), str(paths[shape]), str(paths[shape].parent)],
                             capture_output=True, text=True)
        outs[shape] = run.stdout if run.returncode == 0 else run.stderr[-300:]
    check(f"{pid}: puzzle_paths.js readView gives the file the shim's derived fields (same as its view)",
          outs["file"] == outs["view"] and outs["file"].startswith("{"), (outs["file"][:200], outs["view"][:200]))

# ---- each fixture's shim unpacks in JavaScript to browser_puzzle() ----
want, shims = [], tmp / "shims"
shims.mkdir()
for f in sorted(FIXTURES.rglob("*.json")):
    p = fp.read_puzzle_file(f)
    (shims / f"{p['id']}.js").write_text(fp.shim_text(f, p), encoding="utf-8")
    want.append(json.dumps(fp.browser_puzzle(p), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
(tmp / "want").write_text("\n".join(want) + "\n", encoding="utf-8")
js = r"""
const fs = require("fs"), path = require("path");
const dir = process.argv[1];
const sorted = (v) => Array.isArray(v) ? v.map(sorted)
  : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v;
const win = {}, bad = [];
for (const line of fs.readFileSync(path.join(dir, "want"), "utf8").split("\n").filter(Boolean)) {
  const id = JSON.parse(line).id;
  new Function("window", fs.readFileSync(path.join(dir, "shims", id + ".js"), "utf8"))(win);
  if (JSON.stringify(sorted(win.CRYPTIC_PUZZLES[id])) !== line) bad.push(id);
}
process.stdout.write(bad.join(" "));
"""
run = subprocess.run(["node", "-e", js, str(tmp)], capture_output=True, text=True)
check(f"every fixture's shim unpacks to browser_puzzle() ({len(want)})",
      run.returncode == 0 and not run.stdout, run.stdout or run.stderr[-300:])

print("PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
PY
