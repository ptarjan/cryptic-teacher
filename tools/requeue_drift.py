#!/usr/bin/env python3
"""Queue what a rule change or a lexicon rebuild newly flags, instead of letting it turn CI red.

    python3 tools/requeue_drift.py            # report: puzzles over their allowance, clues to queue
    python3 tools/requeue_drift.py --write    # raise those allowances, queue the clues

A shape rule's allowance (tools/annotation_backlog.json) is what a puzzle had when the rule
was recorded. Widening a rule (a new case in wordplay.wrongRole) or moving a threshold it
reads (the indicator lexicon is rebuilt nightly, and a word crossing
validate_annotations.MISPLACED_MIN_USES flags puzzles that were committed clean) makes
committed puzzles exceed it through no edit of theirs, and the deploy fails on them.

For every puzzle whose count of a rule's clues now exceeds its allowance, this raises the
allowance to the count and lists each flagged clue in tools/data/shape_reannotate.json with
the rule's reason (a clue already listed gets the rule appended to its reason, so it is not
pruned as stale while this rule still flags it). The allowance only ever rises here, and
only for clues the burn is now queued to redo: each redo is held to the rule by the redo
gate, and the next `validate_annotations.py --tighten` ratchets the allowance back down as
the queue drains. Only the rules the redo gate knows (shape_queue._validator_rules) are
requeued; any other field over its allowance is a real failure and is left to fail.

tools/daily_update.sh runs this after the lexicon is rebuilt; run it after editing a rule.
Nothing is written when the run has an error other than an allowance.
"""
import argparse
import json
import multiprocessing
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shape_queue as Q
import validate_annotations as V

#: The two backlog fields whose rule is named differently in shape_queue._validator_rules().
RULE_OF_FIELD = {"wordplay.anagramCharade": "anaCharade", "wordplay.anagramSynonym": "anaSynonym"}


def rule_fields():
    """{backlog field: the rule name a queue row's reason uses} for the fields the redo gate knows."""
    rules = Q._validator_rules()
    out = {}
    for field in V.BACKLOG_MARKERS:
        rule = RULE_OF_FIELD.get(field, field.removeprefix("wordplay."))
        if field.startswith("wordplay.") and rule in rules and rule != "unchecked_step":
            out[field] = rule
    return out


def clue_key(tag):
    """The queue's key ("22a") for a warning's tag ("22A")."""
    return tag.lower()


def survey(path):
    """(stem, {field: clue keys flagged}, whether the puzzle has an error besides an allowance)."""
    puzzle = V.read_puzzle_file(path)
    annotated, errors, warnings = V.validate_puzzle(puzzle, corpus=True)
    if not annotated:
        return path.stem, {}, bool(errors)
    flagged = {f: sorted({clue_key(w.split(":", 1)[0]) for w in warnings if any(m in w for m in ms)})
               for f, ms in V.BACKLOG_MARKERS.items()}
    return path.stem, flagged, bool(errors)


def survey_all(paths):
    jobs = int(os.environ.get("VALIDATE_JOBS") or os.cpu_count() or 1)
    if jobs < 2 or "fork" not in multiprocessing.get_all_start_methods():
        yield from map(survey, paths)
        return
    with multiprocessing.get_context("fork").Pool(jobs) as pool:
        yield from pool.imap(survey, paths, V.POOL_CHUNK)


def drift(surveyed, allowed, fields, everything=()):
    """{field: {puzzle: [clue keys]}} for each puzzle past its allowance in a requeueable field.
    A field in `everything` is a grandfathered one (--all): every puzzle with a hit counts, over
    its allowance or not."""
    return {f: {stem: flagged[f] for stem, flagged, _ in surveyed
                if len(flagged.get(f, ())) > (0 if f in everything else allowed.get(f, {}).get(stem, 0))}
            for f in fields if f in allowed}


def requeue(over, fields, rows):
    """The queue's rows with every clue of `over` listed under its rule's reason."""
    by_id = {r["id"]: r for r in rows}
    out, added = list(rows), 0
    for field, puzzles in over.items():
        rule = fields[field]
        reason = f"{rule}: {Q._why(rule)}"
        for stem, keys in puzzles.items():
            for key in keys:
                row = by_id.get(f"{stem}#{key}")
                if row is None:
                    out.append({"id": f"{stem}#{key}", "reason": reason})
                    added += 1
                elif rule not in [p.split(":")[0].strip() for p in row.get("reason", "").split("; ")]:
                    row["reason"] = f"{row.get('reason', '')}; {reason}".lstrip("; ")
                    added += 1
    return out, added


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--all", action="append", default=[], metavar="FIELD",
                    help="queue every current hit of this backlog field (e.g. wordplay.halfLeaf), "
                         "not just the puzzles past their allowance: for a rule whose existing hits "
                         "were grandfathered by --tighten. Repeatable. Allowances are set to the count.")
    a = ap.parse_args()
    fields = rule_fields()
    bad = [f for f in a.all if f not in fields]
    if bad:
        ap.error(f"--all: not a requeueable backlog field: {', '.join(bad)}")
    allowed = V.load_backlog()
    surveyed = list(survey_all(V.puzzle_files()))
    if any(bad for _, _, bad in surveyed):
        print("requeue_drift: the corpus has errors of its own; fix them first (nothing written)")
        return 1
    over = drift(surveyed, allowed, fields, a.all)
    for field, puzzles in over.items():
        print(f"{field}: {len(puzzles)} puzzle(s), {sum(len(k) for k in puzzles.values())} clue(s) flagged in puzzles over their allowance")
    if not a.write or not any(over.values()):
        return 0
    with Q.locked():
        rows, added = requeue(over, fields, json.loads(Q.PATH.read_text()))
        Q.write(Q.dump(rows))
    data = json.loads(V.BACKLOG_PATH.read_text())
    for field, puzzles in over.items():
        for stem, keys in puzzles.items():
            data[field][stem] = len(keys)
        data[field] = dict(sorted(data[field].items(), key=V._sort_key))
    V.BACKLOG_PATH.write_text(json.dumps(data, indent=1) + "\n")
    print(f"requeue_drift: queued {added} clue(s), raised the allowances of {sum(map(len, over.values()))} puzzle-field(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
