#!/usr/bin/env python3
"""Check the puzzles we hold against the Cryptonite clue dataset.

    python3 tools/check_cryptonite.py DATA_DIR [--report /tmp/cryptonite_check.json]

Read-only: no puzzle file is touched. For every held puzzle in times,
sundaytimes, telegraph and sundaytel whose date has dataset rows (the loader,
the parse cache and the paper/date grouping are file_cryptonite's), the clues
are matched by number and direction and compared two ways: answers (letters
only, uppercase) and clue text (case and punctuation ignored).

Each puzzle gets flags and one primary class, the first that applies:

  other_date    the dataset's clues on this date are mostly some other held
                puzzle's clues (the answers or text of a different date of
                the same paper): our date, or its number, is likely wrong.
                The record names that date and the shift in days.
  no_match      under half the dataset's clues match ours and no other held
                puzzle explains them: the dataset's date or ours is unreliable.
  answers_differ  some answers differ; each is listed with how many of its
                crossings agree with each side (our grid decides who is right).
  text_differs  answers agree, clue text differs on some clues.
  fillable      we hold no answer for clues the dataset gives (flag, and the
                class when nothing differs).
  full          every clue agrees.

A date with two cryptics in the dataset (a repeated number and direction) is
flagged two_puzzles and compared on the candidate whose clue text is ours.
"""
import argparse
import collections
import datetime
import json
import re
import sys
from pathlib import Path

import file_cryptonite as fc

SERIES = ("times", "sundaytimes", "telegraph", "sundaytel")
ROOT = Path(__file__).resolve().parent.parent
#: Share of the dataset's clues that must match for two puzzles to be called the same.
SAME = 0.5


def norm_text(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clue_text(entry):
    clue = entry.get("clue")
    return clue.get("text") if isinstance(clue, dict) else clue


def read_held(root=ROOT):
    """{series: {date: puzzle dict}} (the full JSON, one read of each file)."""
    out = {s: {} for s in SERIES}
    for s in SERIES:
        for p in (root / "puzzles" / s).glob("*/*.json"):
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("date"):
                j["_path"] = str(p.relative_to(root))
                out[s][datetime.date.fromisoformat(j["date"][:10])] = j
    return out


def ours_of(puzzle):
    """{(number, direction): (answer letters or "", normalised clue text)}."""
    return {(e["number"], e["direction"]): (fc.letters(e.get("solution") or ""),
                                            norm_text(clue_text(e)))
            for e in puzzle.get("entries", ())}


ENUM = re.compile(r"\(\s*\d[^()]*\)\s*$")


def theirs_of(rows):
    """{(number, direction): [(answer letters, normalised clue text)]}: the dataset
    writes the enumeration after the clue, which is dropped. A date holding two
    cryptics gives a key two candidates."""
    out = collections.defaultdict(list)
    for r in rows:
        if not str(r["number"]).isdigit():      # the odd "3i" row
            continue
        out[(int(r["number"]), r["orientation"])].append(
            (fc.letters(r["answer"]), norm_text(ENUM.sub("", r["clue"].strip()))))
    return out


def overlap(ours, theirs):
    """Share of the dataset's clues whose text or answer equals ours at the same key."""
    if not theirs:
        return 0.0
    hit = sum(1 for k, cands in theirs.items()
              if k in ours and any(ours[k][1] == t or (a and ours[k][0] == a) for a, t in cands))
    return hit / len(theirs)


def crossings(puzzle, key, cand, trusted):
    """(agree, total): how many of entry `key`'s crossings take candidate
    answer `cand`'s letters, against the letters of the `trusted` answers."""
    cells = {}
    for e in puzzle["entries"]:
        k = (e["number"], e["direction"])
        word = trusted.get(k)
        if not word or len(word) != e["length"]:
            continue
        x, y = e["position"]["x"], e["position"]["y"]
        for i, ch in enumerate(word):
            cells.setdefault((x + i, y) if e["direction"] == "across" else (x, y + i), {})[k] = ch
    me = next((e for e in puzzle["entries"] if (e["number"], e["direction"]) == key), None)
    if me is None or len(cand) != me["length"]:
        return 0, 0
    agree = total = 0
    for i, ch in enumerate(cand):
        pos = (me["position"]["x"] + i, me["position"]["y"]) if key[1] == "across" \
            else (me["position"]["x"], me["position"]["y"] + i)
        for k, other in cells.get(pos, {}).items():
            if k != key:
                total += 1
                agree += other == ch
    return agree, total


def kind(ours, theirs):
    """Why two answers differ: one is a cut-off of the other ("truncated"), a
    same-length spelling variant of at most two letters, or a different word."""
    if ours.startswith(theirs) or theirs.startswith(ours):
        return "truncated"
    if len(ours) == len(theirs) and sum(x != y for x, y in zip(ours, theirs)) <= 2:
        return "variant"
    return "different"


def compare(puzzle, rows):
    """The flags and details for one held puzzle against the dataset's rows."""
    ours, theirs = ours_of(puzzle), theirs_of(rows)
    differ, text, fill, missing = [], [], [], 0
    two = any(len(v) > 1 for v in theirs.values())
    for k, cands in sorted(theirs.items()):
        if k not in ours:
            missing += 1
            continue
        oa, ot = ours[k]
        if two:                   # two cryptics on the date: only a row whose text is ours is ours
            cands = [x for x in cands if x[1] == ot]
            if not cands:
                continue
        a, t = cands[0]
        if not oa:
            fill.append({"key": f"{k[0]}{k[1][0]}", "answer": a})
        elif a and oa != a:
            differ.append({"key": k, "ours": oa, "theirs": a})
        if ot != t:
            text.append({"key": f"{k[0]}{k[1][0]}", "ours": ot, "theirs": t})
    trusted = {k: v[0] for k, v in ours.items()
               if v[0] and any(a == v[0] for a, _ in theirs.get(k, ()))}
    for d in differ:
        k = d["key"]
        d["ours_cross"] = crossings(puzzle, k, d["ours"], trusted)
        d["theirs_cross"] = crossings(puzzle, k, d["theirs"], trusted)
        d["kind"] = kind(d["ours"], d["theirs"])
        d["key"] = f"{k[0]}{k[1][0]}"
    return {"clues_dataset": len(theirs), "clues_ours": len(ours), "not_in_ours": missing,
            "answers_differ": differ, "text_differs": text, "fillable": fill,
            "overlap": round(overlap(ours, theirs), 3)}


def vote(rows, other):
    """The held date (a dict of date: puzzle) whose clues best match these rows:
    (date, share), or (None, 0)."""
    theirs = theirs_of(rows)
    best = (None, 0.0)
    for day, p in other.items():
        s = overlap(ours_of(p), theirs)
        if s > best[1]:
            best = (day, s)
    return best


def build_index(held_series):
    """{normalised clue text: {dates}} so a vote need not scan every puzzle."""
    idx = collections.defaultdict(set)
    for day, p in held_series.items():
        for e in p.get("entries", ()):
            t = norm_text(clue_text(e))
            if len(t) > 12:
                idx[t].add(day)
    return idx


def candidates(rows, idx):
    """The few held dates sharing the most clue texts with these rows."""
    count = collections.Counter()
    for r in rows:
        count.update(idx.get(norm_text(r["clue"]), ()))
    return [d for d, _ in count.most_common(3)]


def classify(c, other_date):
    if other_date:
        return "other_date"
    if c["overlap"] < SAME:
        return "two_puzzles_unmatched" if c.get("two_puzzles") else "no_match"
    if c["answers_differ"]:
        return "answers_differ"
    if c["text_differs"]:
        return "text_differs"
    if c["fillable"]:
        return "fillable"
    return "full"


def cryptonite_groups(data_dir):
    """The source adapter: {(series, day): [row]}, a row being a dict with
    number, orientation ("across"/"down"), clue and answer. Another source
    plugs in by returning the same shape (add it to SOURCES)."""
    import pickle
    cache = sorted(Path(data_dir).glob("rows-*.pickle"))
    if not cache:                      # first run: let the filer's loader parse and cache it
        fc.load(data_dir)
        cache = sorted(Path(data_dir).glob("rows-*.pickle"))
    with open(cache[-1], "rb") as fh:
        tuples = pickle.load(fh)
    # One publisher at a time (memory is tight): dicts are built lazily and the
    # per-publisher buckets are freed before the next.
    out = {}
    for pub in sorted({t[0] for t in tuples}):
        rows = (dict(zip(fc.FIELDS, t)) for t in tuples if t[0] == pub)
        groups, _ = fc.buckets(rows, collections.Counter())
        out.update(groups)
        del groups
    return out


SOURCES = {"cryptonite": cryptonite_groups}


def run(data_dir, root=ROOT, source="cryptonite"):
    groups = SOURCES[source](data_dir)
    held = read_held(root)
    idx = {s: build_index(held[s]) for s in SERIES}
    report, two = [], collections.Counter()
    for (series, day), rs in sorted(groups.items()):
        if series not in SERIES or day not in held[series]:
            continue
        if fc.two_puzzles(rs):
            two[(series, day.year)] += 1
        puzzle = held[series][day]
        c = compare(puzzle, rs)
        other = None
        if c["overlap"] < SAME:
            for d in candidates(rs, idx[series]):
                if d != day and overlap(ours_of(held[series][d]), theirs_of(rs)) >= SAME:
                    other = d
                    break
            if other is None:      # the clues may be absent from ours: try by answer
                d, s = vote(rs, {x: p for x, p in held[series].items() if x != day
                                 and abs((x - day).days) < 400})
                other = d if s >= SAME else None
        c.update({"two_puzzles": fc.two_puzzles(rs), "series": series, "date": day.isoformat(), "number": puzzle.get("number"),
                  "path": puzzle["_path"],
                  "other_date": other.isoformat() if other else None,
                  "shift_days": (other - day).days if other else None})
        c["class"] = classify(c, other)
        report.append(c)
    return report, two


def summary(report, two):
    table = collections.defaultdict(collections.Counter)
    for c in report:
        key = (c["series"], c["date"][:4])
        table[key][c["class"]] += 1
        for flag in ("answers_differ", "text_differs", "fillable"):
            if c[flag] and c["class"] != flag:
                table[key]["+" + flag] += 1
    for k, n in two.items():
        table[(k[0], str(k[1]))]["(of which two_puzzles)"] += n
    return table


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_dir")
    ap.add_argument("--source", choices=sorted(SOURCES), default="cryptonite")
    ap.add_argument("--report", default="/tmp/cryptonite_check.json")
    args = ap.parse_args(argv)
    report, two = run(args.data_dir, source=args.source)
    Path(args.report).write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    table = summary(report, two)
    for key in sorted(table):
        print(" ".join(key), dict(table[key]))
    print(f"{len(report)} held puzzles compared; report in {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
