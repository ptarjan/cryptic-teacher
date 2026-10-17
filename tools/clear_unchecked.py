#!/usr/bin/env python3
"""Drop the `unchecked` flag from wordplay trees that evaluate to their answer without it,
so a flag filed as a precaution does not count against the backlog for good.

    python3 tools/clear_unchecked.py [--examples N]   # dry run over puzzles/: counts and samples
    python3 tools/clear_unchecked.py --write          # write, one commit per puzzle, shrink the allowance

For each clue whose wordplay tree carries an unchecked step, the tree is copied with every
flag stripped and run through tools/wordplay.py's evaluate against the clue's answer. A clue
is cleared when that gives the answer (still failing: a WordplayError, the flag stays;
crashed: any other exception, which is a bug in the evaluator, the flag stays). A puzzle is
written only when tools/validate_annotations.py then finds no error or warning it did not
already have (the unchecked-step warnings themselves aside); if the clues together would add
one, they are tried one at a time and only the clean ones are kept. The allowance for
wordplay.unchecked in tools/annotation_backlog.json drops to the clues still flagged.
--shard K/N and --limit N run a slice; re-running skips what is already cleared. CT_JOBS sets the worker count (default 2). With --write each puzzle is committed on its own
(tools/commit_puzzles.sh, subject by tools/commit_subject.py) and the allowance follows in one.
"""
import argparse
import collections
import copy
import json
import multiprocessing
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import puzzle_schema
import validate_annotations as V
import wordplay

ROOT = Path(__file__).resolve().parent.parent
FIELD = "wordplay.unchecked"
JOB = "Clear unchecked wordplay"


def flagged(node):
    """Whether the tree carries an unchecked step anywhere."""
    return bool(node.get("unchecked")) or any(flagged(p) for p in node.get("parts") or [] if isinstance(p, dict))


def stripped(node):
    """A copy of the tree without any unchecked flag."""
    node = copy.deepcopy(node)

    def go(n):
        n.pop("unchecked", None)
        if "op" in n:  # a checked op's letters are derived: the schema refuses `gives` there
            n.pop("gives", None)
        for p in n.get("parts") or []:
            if isinstance(p, dict):
                go(p)
    go(node)
    return node


def bucket(wp, answer):
    """(outcome, reason bucket, detail): why a clue clears or does not."""
    try:
        wordplay.evaluate(stripped(wp), answer)
    except wordplay.WordplayError as e:
        msg = str(e)
        if msg.startswith("the wordplay does not give"):
            return "failing", "eval: wrong string", msg[:150]
        if "the fodder already reads" in msg:
            return "failing", "eval: anagram fodder already the answer", msg[:150]
        if "takes" in msg and "part(s)" in msg:
            return "failing", "eval: " + msg.split("(")[0] + " part count", msg[:150]
        return "failing", "eval: " + " ".join(msg.split()[:4]), msg[:150]
    except Exception as e:
        return "crashed", "crashed: " + type(e).__name__, str(e)[:150]
    if V.scrambled_leaves(stripped(wp), min_len=3):  # evaluates only because a leaf's letters are pre-scrambled
        return "failing", "scrambled leaf", "a leaf gives its clue words' letters out of order"
    return "cleared", "cleared", ""


def verdict(wp, answer):
    """'cleared' (the stripped tree gives the answer), 'failing' (WordplayError) or 'crashed'."""
    return bucket(wp, answer)[0]


WHY = "why:"  # counts keys: WHY + bucket (a count) and EX + bucket + | + example (one each)
EX = "ex:"
OUTCOMES = ("cleared", "failing", "crashed")


def _label(held):
    return f"{held.get('number')}{str(held.get('direction') or '')[:1]}"


def _problems(puzzle):
    """(errors, warnings other than the unchecked ones, clues still flagged)."""
    _, errors, warnings = V.validate_puzzle(puzzle, corpus=True)
    keep = collections.Counter(w for w in warnings if V.UNCHECKED_STEP not in w)
    return collections.Counter(errors), keep, V.count_backlog(warnings)[FIELD]


def _code(finding):
    """A finding's leading words, to group gate failures."""
    return " ".join(re.sub(r"^\d+[AD]: ", "", finding).split()[:5])[:40]


def _worse(before, after):
    return bool((after[0] - before[0]) or (after[1] - before[1]))


def clear_puzzle(puzzle):
    """Clear `puzzle`. Returns (the puzzle, [(clue, answer, rendered tree)] cleared,
    {outcome: clues}, clues flagged before, clues flagged after)."""
    counts = collections.Counter()
    todo = []  # (position in annotations() order, clue label, answer)
    for i, (_, held, ann) in enumerate(puzzle_schema.annotations(puzzle)):
        wp = ann.get("wordplay")
        if not isinstance(wp, dict) or not flagged(wp):
            continue
        out, why, detail = bucket(wp, held.get("solution") or "")
        counts[out] += 1
        if out != "cleared":
            counts[WHY + why] += 1
            counts[f"{EX}{why}|{_label(held)} {held.get('solution')}: {detail}"] = 1
        if out == "cleared":
            todo.append((i, _label(held), held.get("solution"), wordplay.render(stripped(wp))))
    n_flagged = sum(counts[o] for o in OUTCOMES)
    if not todo:  # no validator run for a puzzle with nothing to clear: it is the slow part
        return puzzle, [], counts, n_flagged, n_flagged
    base = _problems(puzzle)

    def apply(chosen):
        trial = copy.deepcopy(puzzle)
        want = {t[0] for t in chosen}
        for i, (_, _, ann) in enumerate(puzzle_schema.annotations(trial)):
            if i in want:
                ann["wordplay"] = stripped(ann["wordplay"])
        return trial

    chosen = todo
    trial = apply(chosen)
    after = _problems(trial)
    if _worse(base, after):
        chosen = []
        for one in todo:
            if not _worse(base, _problems(apply(chosen + [one]))):
                chosen.append(one)
        trial = apply(chosen)
        after = _problems(trial) if chosen else base
    held_back = len(todo) - len(chosen)
    counts["cleared"] -= held_back
    counts["failing"] += held_back
    kept = {t[0] for t in chosen}
    for t in todo:
        if t[0] not in kept:
            new = (_problems(apply([t]))[:2])
            codes = sorted({_code(k) for c in (new[0] - base[0], new[1] - base[1]) for k in c})
            why = "gate: " + (", ".join(codes) or "combined")
            counts[WHY + why] += 1
            counts[f"{EX}{why}|{t[1]} {t[2]} = {t[3]}"] = 1
    if not chosen:
        return puzzle, [], counts, base[2], base[2]
    return puzzle_schema.order(trial), [t[1:] for t in chosen], counts, base[2], after[2]


def _job(args):
    path, write = args
    puzzle = V.read_puzzle_file(Path(path))
    puzzle, done, counts, before, after = clear_puzzle(puzzle)
    if done and write:
        part = Path(path).with_name(f".{Path(path).name}.part")
        part.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(part, path)
    return path, done, counts, before, after


def files():
    return sorted(p for p in (ROOT / "puzzles").glob("**/*.json") if not p.name.startswith("."))


def flagged_files():
    """The puzzle files the allowance lists for the field."""
    listed = set(json.loads(V.BACKLOG_PATH.read_text()).get(FIELD, {}))
    return [p for p in files() if p.stem in listed]


def jobs():
    return int(os.environ.get("CT_JOBS") or 2)


def commit(path):
    """Commit one written puzzle on its own."""
    rel = os.path.relpath(path, ROOT)
    subprocess.run(["git", "add", "--", rel], cwd=ROOT, check=True)
    subprocess.run(["bash", "-c", f'. tools/commit_puzzles.sh; ct_commit_puzzles "{JOB}"'], cwd=ROOT, check=True)


def run(paths, write):
    out = []
    with multiprocessing.Pool(jobs()) as pool:
        for r in pool.imap_unordered(_job, [(str(p), write) for p in paths], 8):
            if write and r[1]:
                commit(r[0])
            out.append(r)
    return out


def shrink_allowance(left):
    """left: {puzzle: clues still flagged}. The field's list only ever tightens."""
    data = json.loads(V.BACKLOG_PATH.read_text())
    had = data.get(FIELD, {})
    new = {k: min(n, had.get(k, n)) for k, n in left.items() if n}
    new.update({k: n for k, n in had.items() if k not in left})
    data[FIELD] = dict(sorted(new.items(), key=V._sort_key))
    V.BACKLOG_PATH.write_text(json.dumps(data, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the puzzles, one commit each, and shrink the allowance")
    ap.add_argument("--examples", type=int, default=10)
    ap.add_argument("--shard", default="1/1", help="K/N: only every Nth flagged puzzle, from the Kth; the allowance shrinks "
                    "per shard, so a killed or split --write run resumes by running the shards again")
    ap.add_argument("--limit", type=int, help="only the first N flagged puzzles (a dry-run slice)")
    a = ap.parse_args()
    k, n = (int(x) for x in a.shard.split("/"))
    paths = flagged_files()[k - 1::n][:a.limit]
    results = run(paths, a.write)
    total = collections.Counter()
    for r in results:  # update in place: sum() re-copies the whole Counter per puzzle
        total.update(r[2])
    n_total = sum(total[o] for o in OUTCOMES)
    cleared = sum(len(r[1]) for r in results)
    print(f"{n_total} unchecked clues in {len(results)} puzzles: "
          f"{cleared} {'cleared' if a.write else 'clearable'} in {sum(1 for r in results if r[1])} puzzles, "
          f"{total['failing']} still failing, {total['crashed']} crashed; "
          f"{sum(r[4] for r in results)} left flagged")
    whys = {k[len(WHY):]: v for k, v in total.items() if k.startswith(WHY)}
    for why, n in sorted(whys.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {why}")
        exs = sorted(k[len(EX):].split("|", 1)[1] for k in total if k.startswith(EX + why + "|"))
        for e in exs[:2]:
            print(f"         e.g. {e[:230]}")
    rows = [(Path(p).stem, c) for p, d, *_ in results for c in d]
    for pid, (clue, answer, tree) in random.Random(1).sample(rows, min(a.examples, len(rows))):
        print(f"  {pid} {clue}: {answer} = {tree}")
    if a.write:
        shrink_allowance({Path(p).stem: after for p, _, _, _, after in results})
    return 0


if __name__ == "__main__":
    sys.exit(main())
