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

The deploy's full check does this itself (pages.yml, "Requeue what the rules newly flag"): its
shards run validate_annotations.py --drift-out, letting a puzzle past its allowance in these rules
through and writing what it flagged, and --publish pushes the raises as a commit on master. So a
rule edit or the nightly lexicon rebuild needs no local survey; run this by hand to preview one
(report) or to queue without waiting for CI (--write).
Nothing is written when the run has an error other than an allowance.

    python3 tools/requeue_drift.py --backlog FIELD --drift-out F   # survey only FIELD's backlog
    python3 tools/requeue_drift.py --publish F --why "..."         # push what it found

--backlog surveys only the puzzles on a field's backlog (or every requeueable field's: `all`),
not the corpus, and queues every hit, as --all does. A grandfathered hit (within its allowance)
is otherwise never queued, and the burn's shape-rule backfill bags only queued clues: 11-03,
176 of wordplay.anagramCharade's puzzles had no row, so each ran alone (~18k tokens a clue)
instead of in a bag of ~30 clues (tools/clue_bag.py). Allowances are set to the count found,
which never raises one (a puzzle within its allowance has at most that many hits).
"""
import argparse
import json
import multiprocessing
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json_merge
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
        if field.startswith("wordplay.") and rule in rules and rule != "unchecked_step" and rule not in Q.WARN_ONLY:
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
    return path.stem, V.flagged_clues(warnings, V.BACKLOG_MARKERS), bool(errors)


def survey_all(paths):
    # Two workers by default: it runs on the shared host beside the burn and the bridge, and a
    # cpu_count() fan-out starved them (10-22). VALIDATE_JOBS overrides.
    jobs = int(os.environ.get("VALIDATE_JOBS") or 2)
    if jobs < 2 or "fork" not in multiprocessing.get_all_start_methods():
        yield from map(survey, paths)
        return
    with multiprocessing.get_context("fork").Pool(jobs) as pool:
        yield from pool.imap(survey, paths, V.POOL_CHUNK)


def drift(surveyed, allowed, fields, everything=()):
    """{field: {puzzle: [clue keys]}} for each puzzle past its allowance in a requeueable field.
    A field in `everything` is a grandfathered one (--all): every puzzle with a hit counts, over
    its allowance or not, and a field with no allowance list yet gets one (a new rule)."""
    return {f: {stem: flagged[f] for stem, flagged, _ in surveyed
                if len(flagged.get(f, ())) > (0 if f in everything else allowed.get(f, {}).get(stem, 0))}
            for f in fields if f in allowed or f in everything}


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


QUEUE_FILE = "tools/data/shape_reannotate.json"
BACKLOG_FILE = "tools/annotation_backlog.json"


def raised_backlog(text, over):
    """The backlog file's text with each puzzle of `over` allowed the count of its flagged clues."""
    data = json.loads(text)
    for field, puzzles in over.items():
        for stem, keys in puzzles.items():
            data.setdefault(field, {})[stem] = len(keys)
        data[field] = dict(sorted(data[field].items(), key=V._sort_key))
    # The json-keys clean-filter layout: publish() stores blobs with plumbing, which skips the filter.
    return json_merge.dump_lines(data)


def merged_drift(paths):
    """{field: {puzzle: clue keys}} from the --drift-out files of validate_annotations.py's shards."""
    out = {}
    for p in paths:
        for field, puzzles in json.loads(Path(p).read_text()).items():
            out.setdefault(field, {}).update(puzzles)
    return {f: v for f, v in out.items() if v}


def _git(*args, stdin=None, env=None):
    return subprocess.run(["git", *args], input=stdin, capture_output=True, text=True, env=env)


DEPLOY_WHY = "Made by the deploy's full check (tools/requeue_drift.py --publish)."


def backlog_paths(fields, allowed):
    """The files of the puzzles on these fields' backlogs, each once."""
    from fetch_puzzle import resolve_puzzle
    out = []
    for pid in sorted({p for f in fields for p in allowed.get(f, {})}):
        try:
            out.append(resolve_puzzle(pid))
        except (SystemExit, OSError, ValueError, KeyError):
            continue
    return out


def publish(over, fields, tries=30, sleep=time.sleep, why=DEPLOY_WHY):
    """Push the allowance raises and queue rows for `over` as a commit of their own on origin/master,
    built on its tip from its copies of the two files (a plumbing commit: the checkout is the deploy's
    and stays as it is). A push that loses the race to the burn is built again on the new tip.
    Returns 0 when pushed or nothing was left to do, 1 when every try lost."""
    # --depth=1 only in a clone already shallow (the deploy's): in a full one it writes .git/shallow,
    # shared by every worktree, and the next rebase there replays the whole history (11-03).
    thin = ["--depth=1", "--filter=blob:none"] if _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true" else []
    for n in range(tries):
        if _git("fetch", "-q", "--no-tags", *thin, "origin", "master").returncode:
            sleep(5)
            continue
        old = {p: _git("show", f"origin/master:{p}").stdout for p in (QUEUE_FILE, BACKLOG_FILE)}
        rows, _ = requeue(over, fields, json.loads(old[QUEUE_FILE]))
        new = {QUEUE_FILE: Q.dump(rows), BACKLOG_FILE: raised_backlog(old[BACKLOG_FILE], over)}
        if new == old:
            print("requeue_drift: origin/master already holds the allowance raises and queue rows")
            return 0
        index = {**os.environ, "GIT_INDEX_FILE": os.path.join(tempfile.mkdtemp(), "index"),
                 "GIT_AUTHOR_NAME": "github-actions[bot]", "GIT_COMMITTER_NAME": "github-actions[bot]",
                 "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
                 "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}
        _git("read-tree", "origin/master", env=index)
        for path, text in new.items():
            blob = _git("hash-object", "-w", "--stdin", stdin=text).stdout.strip()
            _git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=index)
        tree = _git("write-tree", env=index).stdout.strip()
        msg = ("Requeue puzzles newly flagged by a validator rule or lexicon change\n\n"
               f"{why}\n")
        commit = _git("commit-tree", tree, "-p", "origin/master", "-m", msg, env=index).stdout.strip()
        pushed = _git("push", "-q", "origin", f"{commit}:refs/heads/master")
        if pushed.returncode == 0:
            print(f"requeue_drift: pushed {commit[:10]}: {sum(map(len, over.values()))} puzzle-field(s) raised")
            return 0
        print(f"requeue_drift: push {n + 1} lost the race ({pushed.stderr.strip()[-120:]}); building again")
        sleep(random.uniform(1, 6))
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--publish", nargs="+", metavar="DRIFT_JSON",
                    help="the deploy's step: push the drift the full check's shards found (validate_annotations.py "
                         "--drift-out files) as a commit on origin/master; surveys nothing")
    ap.add_argument("--all", action="append", default=[], metavar="FIELD",
                    help="queue every current hit of this backlog field (e.g. wordplay.halfLeaf), "
                         "not just the puzzles past their allowance: for a rule whose existing hits "
                         "were grandfathered by --tighten. Repeatable. Allowances are set to the count.")
    ap.add_argument("--backlog", action="append", default=[], metavar="FIELD",
                    help="as --all, but survey only the puzzles on FIELD's backlog (`all`: every "
                         "requeueable field's), not the corpus. Repeatable.")
    ap.add_argument("--drift-out", metavar="FILE", help="write what is found as --publish's JSON")
    ap.add_argument("--why", default=DEPLOY_WHY, help="--publish: the commit body")
    a = ap.parse_args()
    fields = rule_fields()
    if a.publish:
        over = merged_drift(a.publish)
        for field, puzzles in over.items():
            print(f"{field}: {len(puzzles)} puzzle(s), {sum(len(k) for k in puzzles.values())} clue(s) to queue")
        return publish(over, fields, why=a.why) if over else 0
    if a.backlog == ["all"]:
        a.backlog = sorted(fields)
    bad = [f for f in a.all + a.backlog if f not in fields]
    if bad:
        ap.error(f"--all/--backlog: not a requeueable backlog field: {', '.join(bad)}")
    allowed = V.load_backlog()
    if a.backlog:
        a.all = sorted(set(a.all) | set(a.backlog))
        fields = {f: r for f, r in fields.items() if f in a.backlog}
    surveyed = list(survey_all(backlog_paths(a.backlog, allowed) if a.backlog else V.puzzle_files()))
    if any(bad for _, _, bad in surveyed):
        print("requeue_drift: the corpus has errors of its own; fix them first (nothing written)")
        return 1
    over = drift(surveyed, allowed, fields, a.all)
    if a.backlog:  # only the puzzles on the backlog surveyed: never a new allowance
        over = {f: {s: k for s, k in v.items() if s in allowed.get(f, {})} for f, v in over.items()}
    for field, puzzles in over.items():
        print(f"{field}: {len(puzzles)} puzzle(s), {sum(len(k) for k in puzzles.values())} clue(s) flagged in puzzles over their allowance")
    if a.drift_out:
        Path(a.drift_out).write_text(json.dumps({f: v for f, v in over.items() if v}, indent=1) + "\n")
    if not a.write or not any(over.values()):
        return 0
    with Q.locked():
        rows, added = requeue(over, fields, json.loads(Q.PATH.read_text()))
        Q.write(Q.dump(rows))
    V.BACKLOG_PATH.write_text(raised_backlog(V.BACKLOG_PATH.read_text(), over))
    print(f"requeue_drift: queued {added} clue(s), raised the allowances of {sum(map(len, over.values()))} puzzle-field(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
