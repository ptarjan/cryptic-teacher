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
--shard K/N and --limit N run a slice; --ids FILE only the puzzles named in a JSON list; re-running skips what is already cleared. CT_JOBS sets the worker count (default 2). With --write each puzzle is committed on its own
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
import unchecked_repairs as R
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
        for key in ("select", "soundsLike"):  # unchecked-leaf fields: the schema refuses them on a checked leaf
            n.pop(key, None)
        if "op" in n:  # a checked op's letters are derived: the schema refuses `gives` there
            n.pop("gives", None)
        for p in n.get("parts") or []:
            if isinstance(p, dict):
                go(p)
    go(node)
    return node


def cleaned(wp, answer):
    """The tree to file: the flags stripped after the mechanical repairs of
    tools/unchecked_repairs.py, in the form that gives `answer` when one does."""
    base = stripped(R.unscramble(R.split_spoon(R.drop_wordless(wp))))
    return R.shaped(R.repaired(base, answer) or base, answer)


def surplus_words(tree, got):
    """Whether a selection that has its indicator still carries clue words it does not need:
    the pick it made (`got`, from the evaluator) can also be made from the leaf's words
    with the first or the last one left off. Those words are then the real indicator
    ('gastronome spilling guts' for GE), filed in the leaf while the op names another."""
    for node, _ in R.walk(tree):
        parts = node.get("parts") or []
        if (node.get("op") not in wordplay.SELECT or not node.get("indicators") or len(parts) != 1
                or "op" in parts[0] or "gives" in parts[0]):
            continue
        words = [w for w in (wordplay.letters(x) for x in (parts[0].get("words") or "").split()) if w]
        if len(words) < 2 or id(node) not in got:
            continue
        for sub in (words[1:], words[:-1]):
            if got[id(node)] in wordplay._select(node["op"], node.get("n"), "".join(sub), sub):
                return True
    return False


def bucket(wp, answer, ann=None, clue=None):
    """(outcome, reason bucket, detail): why a clue clears or does not. With the clue's
    annotation `ann` and its text, a tree the validator's shape rules would flag once
    the flag is gone (an indicator swapped into a leaf) does not clear either."""
    tree = cleaned(wp, answer)
    try:
        got = wordplay.evaluate(tree, answer)
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
    if V.scrambled_leaves(tree, min_len=3):  # evaluates only because a leaf's letters are pre-scrambled
        return "failing", "scrambled leaf", "a leaf gives its clue words' letters out of order"
    if ann is not None:
        shape = V.shape_warnings("clue", {**ann, "wordplay": tree}, clue)
        if shape:
            return "failing", "shape: " + _code(shape[0]), shape[0][:150]
    if surplus_words(tree, got):
        return "failing", "surplus leaf words", "a selection's leaf holds words the pick does not need: one is its indicator"
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
    trees = {}  # position -> the tree to file
    for i, (_, held, ann) in enumerate(puzzle_schema.annotations(puzzle)):
        wp = ann.get("wordplay")
        if not isinstance(wp, dict) or not flagged(wp):
            continue
        out, why, detail = bucket(wp, held.get("solution") or "", ann, (held.get("clue") or {}).get("text"))
        counts[out] += 1
        if out != "cleared":
            counts[WHY + why] += 1
            counts[f"{EX}{why}|{_label(held)} {held.get('solution')}: {detail}"] = 1
        if out == "cleared":
            fixed = cleaned(wp, held.get("solution") or "")
            trees[i] = fixed
            todo.append((i, _label(held), held.get("solution"), wordplay.render(fixed)))
    n_flagged = sum(counts[o] for o in OUTCOMES)
    if not todo:  # no validator run for a puzzle with nothing to clear: it is the slow part
        return puzzle, [], counts, n_flagged, n_flagged
    base = _problems(puzzle)

    def apply(chosen):
        trial = copy.deepcopy(puzzle)
        want = {t[0] for t in chosen}
        for i, (_, _, ann) in enumerate(puzzle_schema.annotations(trial)):
            if i in want:
                ann["wordplay"] = trees[i]
        return puzzle_schema.order(trial)  # the validator sees the key order that is written

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


def publish(pending):
    """Push the local commits in `pending` (oldest first) to origin, so a killed run loses none."""
    for sha in pending:
        r = subprocess.run(["tools/push_puzzle_commit.sh", sha], cwd=ROOT)
        if r.returncode:
            print(f"push failed for {sha} (exit {r.returncode})", file=sys.stderr, flush=True)
    pending.clear()


def run(paths, write, push_every=0):
    out = []
    pending = []
    with multiprocessing.Pool(jobs()) as pool:
        for r in pool.imap_unordered(_job, [(str(p), write) for p in paths], 8):
            if write and r[1]:
                commit(r[0])
                if push_every:
                    pending.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                                  text=True, check=True).stdout.strip())
                    if len(pending) >= push_every:
                        publish(pending)
            out.append(r)
            print(f"[{len(out)}/{len(paths)}] {Path(r[0]).stem}: {len(r[1])} cleared", file=sys.stderr, flush=True)
    if pending:  # the last batch, short of push_every
        publish(pending)
    return out


def shrink_allowance(left):
    """left: {puzzle: clues still flagged}. The field's list only ever tightens."""
    data = json.loads(V.BACKLOG_PATH.read_text())
    had = data.get(FIELD, {})
    new = {k: min(n, had.get(k, n)) for k, n in left.items() if n}
    new.update({k: n for k, n in had.items() if k not in left})
    data[FIELD] = dict(sorted(new.items(), key=V._sort_key))
    V.store_backlog(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the puzzles, one commit each, and shrink the allowance")
    ap.add_argument("--examples", type=int, default=10)
    ap.add_argument("--shard", default="1/1", help="K/N: only every Nth flagged puzzle, from the Kth; the allowance shrinks "
                    "per shard, so a killed or split --write run resumes by running the shards again")
    ap.add_argument("--limit", type=int, help="only the first N flagged puzzles (a dry-run slice)")
    ap.add_argument("--ids", help="JSON list of puzzle ids or clue ids (puzzle#label): only those puzzles are loaded")
    ap.add_argument("--start-after", help="puzzle id: skip the flagged puzzles up to and including this one, in file order "
                    "(resume a killed run from the last id its log shows)")
    ap.add_argument("--push-every", type=int, default=0, help="with --write, publish the commits every N puzzles "
                    "(tools/push_puzzle_commit.sh), so a kill loses at most N unpushed commits")
    a = ap.parse_args()
    k, n = (int(x) for x in a.shard.split("/"))
    paths = flagged_files()
    if a.start_after:
        stems = [p.stem for p in paths]
        if a.start_after in stems:
            paths = paths[stems.index(a.start_after) + 1:]
        else:  # already cleared and off the list: resume at the first file sorting after it
            paths = [p for p in paths if p.stem > a.start_after]
    paths = paths[k - 1::n][:a.limit]
    if a.ids:
        want = {i.split("#")[0] for i in json.loads(Path(a.ids).read_text())}
        paths = [p for p in paths if p.stem in want]
    results = run(paths, a.write, a.push_every if a.write else 0)
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
