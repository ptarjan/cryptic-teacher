#!/usr/bin/env python3
# Does a puzzle file carry keys that say nothing?
#
#     python3 tests/test_empty_keys.py
#
# Every key is written when it carries data and left out when it does not:
# the clue's `separators`, `italics` and `missing`, the entry's `group` and
# `annotation`. An empty form on every entry is megabytes of the corpus spent
# saying nothing, paid for again on every clone, CI checkout and page build.
# That only works if an absent key reads exactly like an empty one, which is
# what this tests on both sides — the writers must not emit the empty form, and the readers must take
# the absence as empty rather than throwing on it.
#
# The three groups of Python checks each run in a fresh interpreter (this file
# re-invoked with the group's name), since they stub parts of the writers.
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))


def writers():
    import fetch_puzzle as fetcher
    import puzzle_integrity
    from groups import entry_id
    # Two lights in an empty grid are not a whole puzzle; the write gate has its own test, tests/test_puzzle_invariants.py.
    puzzle_integrity.refuse_bad_write = lambda puzzle, old=None: None

    def guardian_entry(eid, num, seps=None):
        return {"id": eid, "number": num, "direction": "across",
                "position": {"x": 0, "y": 2 * (num - 1)}, "length": 8,
                "clue": f"A clue with words in it ({'4,4' if seps else '8'})",
                "separatorLocations": seps or {}, "solution": "ANSWERED",
                "group": [eid]}

    data = {"id": "crosswords/cryptic/30066", "number": 30066,
            "name": "Cryptic crossword No 30,066", "creator": {"name": "Tramp"},
            "date": 1784764800000, "dimensions": {"rows": 15, "cols": 15},
            "entries": [guardian_entry("1-across", 1),
                        guardian_entry("2-across", 2, {",": [4]})]}
    puzzle = fetcher.convert(data)
    by = {entry_id(e): e for e in puzzle["entries"]}
    print("PLAIN", "separators" in by["1-across"]["clue"], "annotation" in by["1-across"])
    print("BREAK", json.dumps(by["2-across"]["clue"].get("separators")))
    # Dropping a key must not shuffle the ones that stay, or the diff over 16,000
    # files is unreadable and no one can check it.
    print("ORDER", ",".join(by["2-across"]), ",".join(by["2-across"]["clue"]))

    # The file is the payload, so what comes back off disk has to be what went
    # down — absent keys and all — and the bytes must hold neither empty form.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cryptic-30066.json"
        fetcher.write_puzzle_file(path, puzzle)
        text = path.read_text(encoding="utf-8")
        back = fetcher.read_puzzle_file(path)
        print("TRIP", back["entries"] == puzzle["entries"])
        print("NOEMPTY", '"separators": []' in text, '"annotation": null' in text)

    # An annotation that could not be written is an absent key, not a null one.
    # grade_model_fill throws away an annotation written off a wrong answer and
    # leaves the key out rather than writing a null back.
    # Its ledger is stubbed: this is a test, and a test must not file a miss
    # against tools/data/blind_misses.json that no solve ever made.
    fetcher.record_misses = lambda *a, **k: None
    entries = [{"number": 1, "direction": "across", "clue": {"text": "x", "enumeration": "5"}, "solution": "WRONG",
                "annotation": {"type": ["anagram"]}}]
    fetcher.grade_model_fill({"id": "cryptic-1", "entries": entries},
                             {"1-across": "RIGHT"})
    print("BLANKED", "annotation" in entries[0])


def readers():
    import fetch_puzzle as fetcher
    import difficulty, build_seo_pages, make_og_card, craft_report

    puz = fetcher.read_puzzle_file(fetcher.resolve_puzzle("cryptic-30066"))
    for e in puz["entries"]:
        e["clue"].pop("separators", None)
        e.pop("annotation", None)
    print("DEVICE", difficulty.device(puz))
    print("MACHINERY", difficulty.machinery(puz))
    print("RARITY", difficulty.rarity(puz, difficulty.ranks()) is not None)
    print("CLUEHTML", bool(build_seo_pages.clue_html(puz["entries"][0])))
    print("CARD", make_og_card.plan(puz["entries"][0]))
    print("CRAFT", craft_report.annotated(puz))
    print("COVERAGE", fetcher.clue_coverage(puz)["present"] > 0)
    print("ANNOTATED", fetcher.puzzle_is_annotated(puz))


def schema():
    import fetch_puzzle as fetcher
    import puzzle_integrity, puzzle_schema, validate_annotations

    real = fetcher.read_puzzle_file(fetcher.resolve_puzzle("cryptic-30066"))

    # The write drops every empty form, however deep; a blank clue is {"missing": true}.
    gate = puzzle_integrity.refuse_bad_write
    puzzle_integrity.refuse_bad_write = lambda puzzle, old=None: None
    p = copy.deepcopy(real)
    p["setter"] = None
    e = p["entries"][0]
    e.update(solution=None, clue={"text": "", "separators": [], "italics": [], "missing": True})
    e["annotation"] = {"type": ["anagram"], "indicators": [],
                       "linkWords": [], "explanation": {"surface": ""}, "assembly": {"pieces": []},
                       "features": {"joke": None, "misdirectedWord": None,
                                    "answerInScene": False, "aptDefinition": False},
                       "blocks": [{"clueFragment": "x", "gives": ""}]}
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cryptic-30066.json"
        fetcher.write_puzzle_file(path, p)
        back = json.loads(path.read_text(encoding="utf-8"))
    b0 = back["entries"][0]
    print("PRUNED", "setter" in back, "solution" in b0, "annotation" in b0,
          sorted(b0["annotation"]), sorted(b0["annotation"]["features"]),
          b0["annotation"]["blocks"], b0["clue"])
    puzzle_integrity.refuse_bad_write = gate

    # Every object is written in the schema's key order, whatever order the
    # writer built it in, and a file in any other order fails the validator.
    def backwards(v):
        if isinstance(v, dict):
            return {k: backwards(v[k]) for k in reversed(list(v))}
        return [backwards(x) for x in v] if isinstance(v, list) else v
    scrambled = backwards(real)
    print("SCRAMBLED", any("the schema's order" in x for x in puzzle_schema.validate(scrambled)))
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cryptic-30066.json"
        fetcher.write_puzzle_file(path, scrambled)
        back = json.loads(path.read_text(encoding="utf-8"))
    print("REORDERED", puzzle_schema.validate(back), list(back)[:3])
    import blog_facts
    row = {"url": "u", "entries": {"2-down": {"blocks": [{"gives": "A", "clueFragment": "a"}], "type": ["charade"]},
                                   "1-across": {"inferred": ["type"], "type": ["anagram"]}},
           "name": "n", "blog": "fifteensquared"}
    print("BLOGORDER", blog_facts.row_line("p-1", row))

    # A key the schema does not know is refused at the write gate...
    bad = copy.deepcopy(real)
    bad["entries"][0]["clueCorrupt"] = "retired"
    try:
        puzzle_integrity.refuse_bad_write(bad)
        print("GATE wrote it")
    except ValueError as err:
        print("GATE", "SCHEMA" in str(err) and "clueCorrupt" in str(err))

    # An entry's id is derived from its number and direction, never stored: the
    # write gate refuses one and the validator fails one already on disk.
    stored = copy.deepcopy(real)
    stored["entries"][0] = {"id": "1-across", **stored["entries"][0]}
    try:
        puzzle_integrity.refuse_bad_write(stored)
        print("ENTRY_ID wrote it")
    except ValueError as err:
        print("ENTRY_ID", "SCHEMA" in str(err) and "id" in str(err))
    _, errors, _ = validate_annotations.validate_puzzle(stored)
    print("ENTRY_ID_VALIDATOR", any(x.startswith("schema: $.entries[0]") and "id" in x for x in errors))

    # ...and a null that reached disk some other way fails the validator.
    nulled = copy.deepcopy(real)
    nulled["setter"] = None
    _, errors, _ = validate_annotations.validate_puzzle(nulled)
    print("VALIDATOR", any(x.startswith("schema: $.setter") for x in errors))

    print("ENUMS", puzzle_schema.check_enums())
    print("CORPUS_SAMPLE", puzzle_schema.validate(real))

    # The small validator refuses a keyword it does not implement, so the schema
    # cannot come to promise a check nothing runs.
    try:
        puzzle_schema._check("x", {"format": "email"}, "$", [])
        print("KEYWORD accepted")
    except ValueError:
        print("KEYWORD refused")

    # Where the real jsonschema is installed, it agrees the file is 2020-12 and
    # that a real puzzle passes it and a nulled one does not.
    try:
        import jsonschema
    except ImportError:
        print("JSONSCHEMA skipped")
    else:
        jsonschema.Draft202012Validator.check_schema(puzzle_schema.SCHEMA)
        v = jsonschema.Draft202012Validator(puzzle_schema.SCHEMA)
        print("JSONSCHEMA", not list(v.iter_errors(real)) and bool(list(v.iter_errors(nulled))))


GROUPS = {"writers": writers, "readers": readers, "schema": schema}
if len(sys.argv) > 1:
    GROUPS[sys.argv[1]]()
    sys.exit(0)

fails = 0


def same(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    want {want}\n    got  {got}")
        fails += 1


def run(group):
    """Run a group in a fresh interpreter; return {first word: whole line}."""
    r = subprocess.run([sys.executable, __file__, group], capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(REPO / "tools")})
    lines = (r.stdout + r.stderr).splitlines()
    got = {}
    for ln in lines:
        got.setdefault(ln.split(" ", 1)[0], ln)
    if r.returncode != 0:
        print("\n".join(lines[-15:]))
    return got


def line(out, key):
    return out.get(key, "")


print("a fetched puzzle writes neither key when neither holds anything")
out = run("writers")
same("no separators and no annotation on a plain entry", line(out, "PLAIN"), "PLAIN False False")
same("but a real word break is still written", line(out, "BREAK"), 'BREAK [{"at": 4, "mark": ","}]')
same("and the surviving keys keep their order", line(out, "ORDER"),
     "ORDER number,direction,position,length,clue,solution text,enumeration,separators")
same("a puzzle written without the keys round-trips off disk", line(out, "TRIP"), "TRIP True")
same("and the bytes on disk hold neither empty form", line(out, "NOEMPTY"), "NOEMPTY False False")
same("blanking an annotation removes the key rather than nulling it", line(out, "BLANKED"), "BLANKED False")

print("the readers take an absent key as an empty one")
# Not asked of the source but of the functions: a real puzzle with both keys
# stripped from every entry, through the readers that weigh them. A KeyError or
# an AttributeError anywhere here is a reader that cannot take an absent key.
out = run("readers")
same("difficulty finds no device rather than crashing", line(out, "DEVICE"), "DEVICE None")
same("nor any machinery", line(out, "MACHINERY"), "MACHINERY None")
same("difficulty still scores rarity", line(out, "RARITY"), "RARITY True")
same("the crawlable page still renders the clue", line(out, "CLUEHTML"), "CLUEHTML True")
same("the social card declines the clue rather than throwing", line(out, "CARD"), "CARD None")
same("craft_report sees no annotated entries", line(out, "CRAFT"), "CRAFT []")
same("clue coverage is unaffected", line(out, "COVERAGE"), "COVERAGE True")
same("and the puzzle reads as un-annotated, which is what it is", line(out, "ANNOTATED"), "ANNOTATED False")

print("app.js reads both keys through a guard")
# app.js is the reader that matters most and cannot be imported here, so its
# guards are read out of the source. A bare e.clue.separators.forEach or
# e.annotation.type throws on every puzzle this repo ships.
app = (REPO / "app.js").read_text(encoding="utf-8", errors="replace").splitlines()
reads = sum(1 for ln in app if re.search(r"\be\.clue\.separators\b", ln))
guarded = sum(1 for ln in app if re.search(r"\be\.clue\.separators \|\| \[\]", ln))
same("app.js reads clue.separators only through a || []", reads, guarded)
# annotation needs no such guard anywhere: an absent key reads `undefined` and
# every use in the app is a truthiness test, which undefined and null both fail
# identically. The one thing that would tell them apart is an identity check,
# so that is what is forbidden here rather than a shape the code never has.
strict_re = re.compile(r"annotation\s*(===|!==)\s*null|['\"]annotation['\"]\s+in\b|hasOwnProperty\(['\"]annotation")
strict = 0
for f in ("app.js", "tools/smoke_test.js", "tools/make_hint_packets.js"):
    text = (REPO / f).read_text(encoding="utf-8", errors="replace").splitlines()
    strict += any(strict_re.search(ln) for ln in text)
same("nothing in the app tells a null annotation from an absent one", strict, 0)

print("and the corpus carries neither empty form")
# The whole point of the exercise, asked of the files rather than of the code
# that writes them: nothing is allowed to put empty forms back into puzzles/,
# one nightly fetch at a time. Read as bytes, because
# both strings are unambiguous at this indent and parsing 135 MB to learn it
# would be the slow way round.
g = subprocess.run(["grep", "-rlF", "--include=*.json", "-e", '"separators": []',
                    "-e", '"annotation": null', "puzzles"], capture_output=True, text=True)
found = " ".join(g.stdout.splitlines()[:5])
same("no puzzle file writes an empty separators or a null annotation", found or "none", "none")

print("every key obeys it: tools/data/puzzle.schema.json")
# The rule for all keys, not just the two above: the write prunes null and empty
# values, the write gate and the validator refuse whatever breaks the schema,
# and the schema's closed lists are the ones their sources hold.
out = run("schema")
same("the write drops every null and empty value and keeps a blank clue", line(out, "PRUNED"),
     "PRUNED False False True ['blocks', 'features', 'type'] ['answerInScene', 'aptDefinition'] [{'clueFragment': 'x'}] {'missing': True}")
same("a file in another key order fails the validator", line(out, "SCRAMBLED"), "SCRAMBLED True")
same("the write puts every key in the schema's order", line(out, "REORDERED"), "REORDERED [] ['id', 'number', 'setter']")
same("the blog facts writer puts every key in the schema's order", line(out, "BLOGORDER"),
     'BLOGORDER "p-1": {"blog": "fifteensquared", "name": "n", "url": "u", "entries": {"1-across": {"type": ["anagram"], "inferred": ["type"]}, "2-down": {"type": ["charade"], "blocks": [{"clueFragment": "a", "gives": "A"}]}}}')
same("the write gate refuses a key the schema does not have", line(out, "GATE"), "GATE True")
same("the write gate refuses a stored entry id", line(out, "ENTRY_ID"), "ENTRY_ID True")
same("the validator fails a stored entry id", line(out, "ENTRY_ID_VALIDATOR"), "ENTRY_ID_VALIDATOR True")
same("the validator fails a null on disk", line(out, "VALIDATOR"), "VALIDATOR True")
same("the schema's enums are their sources' lists", line(out, "ENUMS"), "ENUMS []")
same("a real puzzle matches the schema", line(out, "CORPUS_SAMPLE"), "CORPUS_SAMPLE []")
same("an unimplemented schema keyword is refused", line(out, "KEYWORD"), "KEYWORD refused")
js = line(out, "JSONSCHEMA")
if js != "JSONSCHEMA skipped":
    same("jsonschema agrees on the schema and the puzzle", js, "JSONSCHEMA True")

if fails:
    print(f"empty_keys: {fails} check(s) failed")
    sys.exit(1)
print("empty_keys: all checks passed")
