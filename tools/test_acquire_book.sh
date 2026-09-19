#!/bin/bash
# Does tools/acquire_book.py still recover the grids it recovered on 2026-09-18?
#
#     bash tools/test_acquire_book.sh
#
# Acquiring a book is meant to cost CPU and nothing else, which is only true
# while the parser keeps parsing the same way. tools/light_spec.py reads OCR
# that is wrong in a dozen specific ways and repairs it with three general
# rules, and a "harmless" tightening of any of them silently changes which
# books come out the far end. This is the gate that makes such a change
# visible, and tools/light_spec.py says in its own docstring that it is gated
# by this file.
#
# THE CONTROL is ten puzzles from Penguin volume 5, the set the September 2026
# sweep was measured on. Five of them (3, 18, 27, 44, 45) are in puzzles/ and
# were checked by hand; the other five are the interesting failures — an
# ambiguous pair, a ten-fill collapse, a no-solution, a second ambiguous pair —
# and they are in the control precisely because a change that "improves" the
# parser usually shows up first as one of those quietly becoming something
# else.
#
# IT GATES ON NODE COUNTS, NOT JUST GRIDS. The search is deterministic, so the
# number of nodes it visits is a fingerprint of the light spec that went into
# it. Two different specs can produce the same grid; they essentially never
# produce the same node count. Comparing grids alone would sleep through a
# parser change that happens not to move the answer on these ten — which is
# most parser changes.
#
# NO BOOK TEXT LIVES IN THIS REPO. tools/data/penguin5_control.json stores
# light specs (numbers and lengths), black-square patterns, and a sha256 over
# the parser's full output including clue text. So PART 2, which exercises the
# parser itself, needs the OCR text and SKIPS cleanly when it is absent —
# which is the normal case in CI. Part 1 runs everywhere and is the part that
# can fail the build.
#
# Set PENGUIN_TEXT to the OCR dump (or leave tools/fetch_ia_book.py's own
# output where it lands) to get parts 2 and 3 as well.
set -u
cd "$(dirname "$0")/.."

TEXT="${PENGUIN_TEXT:-/tmp/cryptic-teacher-ia-books/newpenguinbkguar0000perk.txt}"
export TEXT

python3 - <<'PYEOF'
import json, os, re, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, "tools")
import grid_verdict
from light_spec import build_spec
from reconstruct_grid import reconstruct

CONTROL = json.loads(Path("tools/data/penguin5_control.json").read_text())
PUZZLES = CONTROL["puzzles"]
failures = []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL {msg}")


# ---------------------------------------------------------------- part 1
# The reconstructor and the verdict, gated on the stored specs. No book text.
def run_one(item):
    bn, spec = item
    triples = ([(lg[0], "across", lg[1]) for lg in spec["across"]]
               + [(lg[0], "down", lg[1]) for lg in spec["down"]])
    found, info = reconstruct(triples, cols=15, rows=15, limit=40, symmetry=True,
                              max_nodes=8_000_000, fallback=False)
    return bn, [list(g) for g in found], info


print("part 1: the ten-puzzle vol-5 control, from stored light specs")
jobs = [(bn, p["light_spec"]) for bn, p in sorted(PUZZLES.items(), key=lambda kv: int(kv[0]))]
passed = 0
with ProcessPoolExecutor(max_workers=4) as pool:
    for bn, found, info in pool.map(run_one, jobs):
        want = PUZZLES[bn]
        ok = True
        if sorted(found) != sorted(want["expected_grids"]):
            fail(f"#{bn}: {len(found)} grid(s), expected {len(want['expected_grids'])}"
                 f" — the recovered geometry moved")
            ok = False
        if info["nodes"] != want["expected_nodes"]:
            fail(f"#{bn}: search visited {info['nodes']} nodes, expected "
                 f"{want['expected_nodes']} — the light spec that went in is "
                 f"not the one this control was measured with")
            ok = False
        if bool(info["truncated"]) != want["expected_truncated"]:
            fail(f"#{bn}: truncated={info['truncated']}, expected "
                 f"{want['expected_truncated']}")
            ok = False
        status, _ = grid_verdict.verdict([tuple(g) for g in found],
                                          bool(info["truncated"]))
        if status != want["expected_status"]:
            fail(f"#{bn}: verdict {status}, expected {want['expected_status']}")
            ok = False
        if ok:
            passed += 1
            print(f"  ok   #{bn:>2} lights={want['lights']} nodes={info['nodes']} "
                  f"{status}")
print(f"  {passed}/{len(jobs)} control puzzles reproduced exactly")

# The five in puzzles/ must come back as usable uniques, not as a shortlist.
for bn in CONTROL["known_good_in_corpus"]:
    got = PUZZLES[str(bn)]["expected_status"]
    if got != "exact-unique":
        fail(f"#{bn} is in the corpus by hand but the control expects {got}")

# ---------------------------------------------------------------- part 1b
# The thresholds are only worth what they cost on real grids, and every one of
# those costs is a claim this file will not let drift silently.
print("part 1b: the reject rules still do what they were measured to do")
for bn, p in PUZZLES.items():
    spec = p["light_spec"]
    reasons = grid_verdict.screen_spec(spec["across"], spec["down"])
    if reasons and p["expected_status"] in ("exact-unique",):
        fail(f"#{bn} reconstructs uniquely but screen_spec rejects it: {reasons[0]}")
for rule in ("across == down cell totals", "checked-cell fraction",
             "must have a 1-Across"):
    if rule not in grid_verdict.DISCARDED:
        fail(f"{rule!r} was measured false against the corpus and must stay "
             f"in grid_verdict.DISCARDED so nobody reinstates it")
short = [[1, 4, "plain"]] * 10
if not grid_verdict.screen_spec(short, []):
    fail("a 10-light list must be rejected: a 15x15 prints at least 24")

# ---------------------------------------------------------------- part 2
# The parser itself. Needs the OCR text, which is never committed.
text = Path(os.environ["TEXT"])
if not text.exists():
    print(f"part 2: SKIPPED — no OCR text at {text}")
    print("  (set PENGUIN_TEXT, or run tools/fetch_ia_book.py, to gate the parser)")
else:
    import hashlib
    from parse_penguin_book import parse_book
    print(f"part 2: the parser, against {text}")
    parsed = {p["book_number"]: p for p in parse_book(text)}
    for bn, want in sorted(PUZZLES.items(), key=lambda kv: int(kv[0])):
        p = parsed.get(int(bn))
        if p is None:
            fail(f"#{bn}: the book no longer splits into a puzzle with this number")
            continue
        a, d, notes, damage = build_spec(p)
        got = {"across": [[lg[0], lg[1], lg[2]] for lg in a],
               "down": [[lg[0], lg[1], lg[2]] for lg in d]}
        if got != want["light_spec"]:
            fail(f"#{bn}: the light spec moved — {len(a) + len(d)} lights now, "
                 f"{want['lights']} in the control")
            continue
        payload = json.dumps([[[lg[0], lg[1], lg[2], (lg[3] or {}).get("clue"),
                                 (lg[3] or {}).get("enumeration")] for lg in side]
                               for side in (a, d)], ensure_ascii=False)
        got_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if got_digest != want["clue_digest"]:
            fail(f"#{bn}: lengths and numbers match but the CLUE TEXT the "
                 f"parser attaches to them changed")
        else:
            print(f"  ok   #{bn:>2} spec and clue text both unchanged")

    # ------------------------------------------------------------ part 3
    # End to end: the five known-good puzzles must come out of the pipeline
    # matching what is in puzzles/, grid and clues, with no model involved.
    print("part 3: the five known-good puzzles, filed unsolved, against puzzles/")
    sys.path.insert(0, "tools")
    from acquire_book import file_unsolved
    MARKER = re.compile(r"/\*JSON-START\*/(.*)/\*JSON-END\*/", re.S)
    SKIP_ENTRY = {"solution", "annotation", "solutionConfidence"}
    with tempfile.TemporaryDirectory() as tmp:
        for bn in CONTROL["known_good_in_corpus"]:
            want = PUZZLES[str(bn)]
            a, d, _, _ = build_spec(parsed[bn])
            grid = tuple(want["expected_grids"][0])
            path, problems = file_unsolved(
                {"book_number": bn, "setter": want["setter"]}, grid, a, d, 5,
                Path(tmp))
            if path is None:
                fail(f"penguin5-{bn}: could not be filed — {problems[0]}")
                continue
            mine = json.loads(MARKER.search(path.read_text()).group(1))
            corpus = json.loads(MARKER.search(
                Path(f"puzzles/penguin5-{bn}.js").read_text()).group(1))
            if any(e["solution"] is not None for e in mine["entries"]):
                fail(f"penguin5-{bn}: filed with answers; --unsolved must file none")
            if "solutionSource" in mine:
                fail(f"penguin5-{bn}: carries solutionSource — an unsolved file "
                     f"must not, or reindex marks it model-solved")
            # provenance is stamped at WRITE time and records when this file
            # arrived, so the copy just written into /tmp says it arrived today
            # while the corpus copy carries its real git date. They are supposed
            # to differ; what must match is the puzzle.
            diffs = [k for k in set(mine) | set(corpus)
                     if k not in {"solutionSource", "entries", "provenance"}
                     and mine.get(k) != corpus.get(k)]
            # Not solutionOrigin: this files --unsolved and the corpus copies
            # have been solved since, so "unsolved" vs "model" is the pipeline
            # working, not drifting.
            for k in ("gridOrigin", "retrievedFrom", "publisher", "series"):
                if mine.get("provenance", {}).get(k) != corpus.get("provenance", {}).get(k):
                    diffs.append(f"provenance.{k}")
            me = {e["id"]: e for e in mine["entries"]}
            we = {e["id"]: e for e in corpus["entries"]}
            if set(me) != set(we):
                diffs.append("entry ids")
            for eid in set(me) & set(we):
                for k in (set(me[eid]) | set(we[eid])) - SKIP_ENTRY:
                    if me[eid].get(k) != we[eid].get(k):
                        diffs.append(f"{eid}.{k}")
            if diffs:
                # penguin5-18's 7-down is a KNOWN corpus error, not a pipeline
                # one: the book prints a hyphenated enumeration and the file in
                # puzzles/ carries a comma. The pipeline reads what is printed.
                known = {f"penguin5-18": {"7-down.clue", "7-down.separatorLocations"}}
                unexpected = sorted(set(diffs) - known.get(f"penguin5-{bn}", set()))
                if unexpected:
                    fail(f"penguin5-{bn}: differs from puzzles/ in "
                         f"{len(unexpected)} place(s): {unexpected[:4]}")
                else:
                    print(f"  ok   penguin5-{bn} matches puzzles/ apart from the "
                          f"known corpus error in 7-down")
            else:
                print(f"  ok   penguin5-{bn} matches puzzles/ exactly "
                      f"(grid and clues, {len(mine['entries'])} entries)")

print()
if failures:
    print(f"FAILED: {len(failures)} problem(s)")
    sys.exit(1)
print("PASSED")
PYEOF
