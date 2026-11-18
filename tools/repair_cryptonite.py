#!/usr/bin/env python3
"""Repair the answers of held puzzles from the Cryptonite clue dataset.

    python3 tools/repair_cryptonite.py DATA_DIR                 # plan, write nothing
    python3 tools/repair_cryptonite.py DATA_DIR --fix           # write the puzzle files
    python3 tools/repair_cryptonite.py DATA_DIR --fix --only sundaytimes

The plan is tools/check_cryptonite.py's comparison turned into edits. For each
held puzzle (times, sundaytimes, telegraph, sundaytel) with dataset rows on its
date, every light is matched by number and direction, and an edit is made only
where OUR clue text equals the dataset row's (case and punctuation ignored, a
date holding two cryptics reduced to the row with our text) and the dataset's
answer is exactly the light's length. Edit classes:

  fill       we hold no answer: take the dataset's.
  truncated  ours is a cut-off of the dataset's (BEDSITTINGROO for
             BEDSITTINGROOM): take the dataset's. Where the dataset's is the
             cut-off one, ours stays.
  shifted    ours differs and equals the dataset's answer to the same light of
             another date of the paper (SHIFTS: the Sunday Times printed a
             solution three weeks after its puzzle, the Times' bug is a day or
             two off): the answers are another puzzle's; take this date's.

Never edited: a different word that is no shift (kept, listed under
"unresolved"), a same-length variant of one or two letters, or an anagram of
the dataset's (the dataset's rows are the scrambled ones there). An edit that
would put a letter against a crossing answer we keep is refused, and a puzzle whose
repaired answers still disagree at any crossing (puzzle_integrity's CROSS check) is
left whole and listed as refused with light "*". Puzzles whose
solutions.origin is not published, unsolved or unknown (a model's or a
write-up's answers) are left whole.

Provenance: the dataset's answers are the paper's own (file_cryptonite), so
solutions.origin stays "published" ("unsolved" becomes it once a light is
filled). The puzzle schema has no per-light origin, so each edit is listed in
docs/cryptonite_repairs.json (puzzle id -> light -> class, was, now), written
by --fix and read by nothing else.
"""
import argparse
import collections
import datetime
import json
import sys
from pathlib import Path

import check_cryptonite as cc
import file_cryptonite as fc

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "cryptonite_repairs.json"
TOOL = "tools/repair_cryptonite.py"
#: Days to look at, per series, for the date whose answers a puzzle may carry.
SHIFTS = {"sundaytimes": (-21, -14, -7, -28), "times": (-1, -2, -3, 1, 2),
          "telegraph": (-1, -2, 1, 2), "sundaytel": (-7, -14, -21, 7)}
#: Shifted lights that make a puzzle's other answers of that date suspect too.
STRONG = 3
REPAIRABLE ={None, "published", "unsolved", "unknown"}


def lid(key):
    return f"{key[0]}{key[1][0]}"


def other_answers(groups, series, day, key):
    """{offset: dataset answer} of this light on the dates SHIFTS names."""
    out = {}
    for off in SHIFTS[series]:
        rs = groups.get((series, day + datetime.timedelta(days=off)))
        if rs:
            for a, _ in cc.theirs_of(rs).get(key, ()):
                out.setdefault(off, set()).add(a)
    return out


def conflicts(puzzle, cells, e, word):
    """Whether `word` laid on light `e` disagrees with the letters in `cells`."""
    x, y = e["position"]["x"], e["position"]["y"]
    for i, ch in enumerate(word):
        pos = (x + i, y) if e["direction"] == "across" else (x, y + i)
        if cells.get(pos, ch) != ch:
            return True
    return False


def lay(cells, e, word):
    x, y = e["position"]["x"], e["position"]["y"]
    for i, ch in enumerate(word):
        cells[(x + i, y) if e["direction"] == "across" else (x, y + i)] = ch


def plan_puzzle(puzzle, series, day, groups):
    """([edit], [unresolved], [refused]) for one held puzzle. An edit is
    {"light", "class", "was", "now", "offset"}."""
    rows = groups.get((series, day))
    if not rows:
        return [], [], []
    theirs = cc.theirs_of(rows)
    wants, unresolved, refused = [], [], []
    for e in puzzle["entries"]:
        key = (e["number"], e["direction"])
        ours_text = cc.norm_text(cc.clue_text(e))
        cands = [c for c in theirs.get(key, ()) if c[1] == ours_text]
        oa = fc.letters(e.get("solution") or "")
        if not cands:     # a reworded clue: still the same light when the dataset's answer completes ours
            cands = [c for c in theirs.get(key, ()) if oa and len(c[0]) == e["length"] and c[0].startswith(oa)]
        if not cands:
            continue
        a = cands[0][0]
        if not a or oa == a:
            continue
        fits = len(a) == e["length"]
        if not oa:
            if fits:
                wants.append((e, key, "fill", None, a))
            continue
        if a.startswith(oa):
            if fits:
                wants.append((e, key, "truncated", None, a))
            continue
        if oa.startswith(a) or sorted(oa) == sorted(a):
            continue                        # the dataset's is the cut-off or scrambled one
        shifted = [off for off, ans in other_answers(groups, series, day, key).items() if oa in ans]
        if shifted and fits:
            wants.append((e, key, "shifted", shifted[0], a))
        else:
            unresolved.append({"light": lid(key), "ours": oa, "theirs": a,
                               "kind": cc.kind(oa, a)})
    # A puzzle with STRONG shift evidence carries another date's answers: any of ours that
    # equals that date's answer to the same light is that puzzle's, kept or not.
    offs = collections.Counter(w[3] for w in wants if w[2] == "shifted")
    strays = []
    if sum(offs.values()) >= STRONG:
        off = offs.most_common(1)[0][0]
        done = {id(w[0]) for w in wants}
        for e in puzzle["entries"]:
            key = (e["number"], e["direction"])
            oa = fc.letters(e.get("solution") or "")
            if oa and id(e) not in done and oa not in {c[0] for c in theirs.get(key, ())} and oa in other_answers(groups, series, day, key).get(off, ()):
                strays.append(e)
    # Lay the answers kept, then each edit that fits the crossings.
    changing = {id(w[0]) for w in wants} | {id(e) for e in strays}
    cells = {}
    for e in puzzle["entries"]:
        word = fc.letters(e.get("solution") or "")
        if word and id(e) not in changing and len(word) == e["length"]:
            lay(cells, e, word)
    edits = []
    for e, key, cls, off, a in wants:
        if conflicts(puzzle, cells, e, a):
            refused.append({"light": lid(key), "class": cls, "ours": fc.letters(e.get("solution") or ""),
                            "theirs": a})
            continue
        lay(cells, e, a)
        edits.append({"light": lid(key), "class": cls, "was": fc.letters(e.get("solution") or ""),
                      "now": a, "offset": off})
    for e in strays:       # another puzzle's answer, and the dataset has no row of ours to replace it
        edits.append({"light": lid((e["number"], e["direction"])), "class": "stripped",
                      "was": fc.letters(e["solution"]), "now": "", "offset": offs.most_common(1)[0][0]})
    return edits, unresolved, refused


def apply_edits(puzzle, edits):
    by = {e["light"]: e for e in edits}
    for e in puzzle["entries"]:
        ed = by.get(lid((e["number"], e["direction"])))
        if ed and ed["now"]:
            e["solution"] = ed["now"]
        elif ed:
            e.pop("solution", None)
    sol = puzzle.get("solutions")
    if isinstance(sol, dict) and sol.get("origin") == "unsolved":
        sol["origin"] = "published"


def crossing_defects(puzzle, edits):
    """puzzle_integrity's CROSS findings for `puzzle` once `edits` are applied
    (the whole puzzle, not only the edited lights, so a fill that disagrees with
    a kept answer or another fill is caught). The write is refused if any."""
    import copy

    import puzzle_integrity as pi
    after = copy.deepcopy(puzzle)
    apply_edits(after, edits)
    checkable = [e for e in after["entries"]
                 if fc.letters(e.get("solution") or "") and len(fc.letters(e["solution"])) == e["length"]]
    for e in checkable:
        e["solution"] = fc.letters(e["solution"])
    flags = []
    pi.check_cross(after, checkable, flags)
    return [f[2] for f in flags]


def dump(puzzle):
    return json.dumps(puzzle, indent=FORMAT, ensure_ascii=False) + "\n"


FORMAT = 1


def read_slim(root=ROOT):
    """{series: {date: puzzle}} holding only what the plan reads (the full files
    carry hints and are most of the memory); --fix rereads a file it edits."""
    out = {s: {} for s in cc.SERIES}
    for s in cc.SERIES:
        for p in (root / "puzzles" / s).glob("*/*.json"):
            j = json.loads(p.read_text(encoding="utf-8"))
            if not j.get("date"):
                continue
            out[s][datetime.date.fromisoformat(j["date"][:10])] = {
                "id": j["id"], "_path": str(p.relative_to(root)),
                "solutions": {"origin": (j.get("solutions") or {}).get("origin")},
                "entries": [{k: e[k] for k in ("number", "direction", "position", "length", "clue", "solution")
                             if k in e} for e in j.get("entries", ())]}
    return out


def near_held(groups, held):
    """`groups` cut to the held dates and the dates SHIFTS reach from them."""
    want = set()
    for s, by_day in held.items():
        for day in by_day:
            want |= {(s, day + datetime.timedelta(days=off)) for off in (0, *SHIFTS[s])}
    return {k: v for k, v in groups.items() if k in want}


def run(data_dir, fix=False, only=None):
    held = read_slim()
    groups = near_held(cc.cryptonite_groups(data_dir), held)
    table = collections.defaultdict(collections.Counter)
    ledger, unresolved_all, refused_all, skipped_origin = {}, [], [], collections.Counter()
    offsets = collections.defaultdict(collections.Counter)
    for series in cc.SERIES:
        if only and series != only:
            continue
        for day, puzzle in sorted(held[series].items()):
            edits, unresolved, refused = plan_puzzle(puzzle, series, day, groups)
            for u in unresolved:
                unresolved_all.append({"puzzle": puzzle["id"], "date": day.isoformat(), **u})
            for r in refused:
                refused_all.append({"puzzle": puzzle["id"], "date": day.isoformat(), **r})
            if not edits:
                continue
            bad = crossing_defects(puzzle, edits)
            if bad:      # the lights disagree among themselves: another puzzle's answers, whole
                refused_all.append({"puzzle": puzzle["id"], "date": day.isoformat(), "light": "*",
                                    "class": "crossing", "ours": "", "theirs": "; ".join(bad[:3])})
                continue
            origin = (puzzle.get("solutions") or {}).get("origin")
            if origin not in REPAIRABLE:
                skipped_origin[(series, day.year, origin)] += len(edits)
                continue
            for ed in edits:
                table[(series, str(day.year))][ed["class"]] += 1
                if ed["offset"] is not None:
                    offsets[(series, str(day.year))][ed["offset"]] += 1
            table[(series, str(day.year))]["puzzles"] += 1
            ledger[puzzle["id"]] = {"date": day.isoformat(), "lights": {
                ed["light"]: {k: ed[k] for k in ("class", "was", "now")} for ed in edits}}
            if fix:
                path = ROOT / puzzle["_path"]
                full = json.loads(path.read_text(encoding="utf-8"))
                apply_edits(full, edits)
                path.write_text(dump(full), encoding="utf-8")
    if fix and ledger:
        old = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
        old.update(ledger)
        LEDGER.write_text(json.dumps(old, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return table, offsets, unresolved_all, refused_all, skipped_origin, ledger


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_dir")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--only", choices=cc.SERIES)
    ap.add_argument("--report", default="/tmp/cryptonite_repair.json")
    args = ap.parse_args(argv)
    table, offsets, unresolved, refused, skipped, ledger = run(args.data_dir, args.fix, args.only)
    for key in sorted(table):
        print(" ".join(key), dict(table[key]), "offsets", dict(offsets.get(key, {})))
    total = collections.Counter()
    for c in table.values():
        total.update(c)
    print("total", dict(total), "| unresolved", len(unresolved), "| refused by crossings", len(refused),
          "| left whole (origin)", sum(skipped.values()))
    Path(args.report).write_text(json.dumps(
        {"unresolved": unresolved, "refused": refused,
         "origin_skipped": {" ".join(map(str, k)): n for k, n in skipped.items()}},
        indent=1) + "\n", encoding="utf-8")
    print("wrote" if args.fix else "would write", len(ledger), "puzzles; details in", args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
