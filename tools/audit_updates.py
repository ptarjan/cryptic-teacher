#!/usr/bin/env python3
"""Audit the clue text each reread ("Update ..." commit) wrote: glitches it brought in or took out.

    python3 tools/audit_updates.py                      # the Update commits since the cursor
    python3 tools/audit_updates.py --since 7.days --no-cursor --examples 2
    python3 tools/audit_updates.py --load /tmp/pairs.jsonl   # learn_postproc --pairs output, no git
    python3 tools/audit_updates.py --alerts             # also print ALERT lines (tools' runner wakes on them)

A reread (OCR + vision model) rewrites a held puzzle's clues and commits
"Update times-N" or "Update N puzzles". tools/learn_postproc.py mines those
rewrites for rules; this sorts each one by what it did to the clue: for every
glitch class (clue_text.GLITCHES, plus four read off the pair: a whole rewrite
to other words, an enumeration that lost its parts, a clue gone blank, a word
regressed) a change is INTRODUCED when the new text has more of it, FIXED
when fewer. A change with any introduced class is an introduced-glitch, else
one with a fixed class a fixed-glitch, else neutral.

Incremental: a cursor file holds the last origin/master sha audited, so each
run reads only the commits since (the first run, --since). Each change is a
row appended to audit.jsonl; the run prints a tally by class. With --alerts it
prints one "ALERT ..." line for a class this run introduced that is new (none
in the 7 days before) or spiking (more than SPIKE_FLOOR and more than twice
its 7-day hourly mean over the run's window), for the recurring runner (a
script outside the repo, every 30 minutes) to wake the room with. Nothing
here changes a puzzle.
"""
import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import clue_text
import enumeration
import learn_postproc

CACHE = Path(os.environ.get("POSTPROC_LEARN_DIR") or Path.home() / ".cache" / "postproc_learn")
DEFAULT_CURSOR = os.environ.get("AUDIT_CURSOR") or str(CACHE / "audit_cursor")
DEFAULT_OUT = os.environ.get("AUDIT_OUT") or str(CACHE / "audit.jsonl")

#: Below this share of like characters a changed clue is another clue's words.
REWRITE_RATIO = 0.5
#: An alert needs more than this many introduced in the window...
SPIKE_FLOOR = 3
#: ...and more than this times the 7-day hourly mean over the window.
SPIKE_FACTOR = 2
HISTORY_HOURS = 7 * 24


def commits(ref, since=None, cursor=None):
    """[(sha, parent, unix time, subject)] of the Update commits on `ref`,
    oldest first: after `cursor` when it is an ancestor of `ref`, else since
    `since`."""
    rng = [ref]
    if cursor and _is_ancestor(cursor, ref):
        rng = [f"{cursor}..{ref}"]
    elif since:
        rng = [ref, "--since=" + since]
    out = learn_postproc.git("log", *rng, "--no-merges", "--reverse", "--format=%H%x09%P%x09%ct%x09%s")
    got = []
    for line in out.splitlines():
        h, parents, ct, subj = (line.split("\t") + ["", "", ""])[:4]
        if subj.startswith("Update") and parents:
            got.append((h, parents.split()[0], int(ct), subj))
    return got


def _is_ancestor(a, b):
    import subprocess
    return subprocess.run(["git", "-C", ROOT, "merge-base", "--is-ancestor", a, b],
                          capture_output=True).returncode == 0


def pairs_of(sha, parent):
    """Each clue whose text or enumeration the commit changed:
    dicts {path, key, old, new, old_enum, new_enum}."""
    names = learn_postproc.git("diff-tree", "-r", "--no-renames", "--name-only", parent, sha,
                               "--", "puzzles").split()
    names = [n for n in names if n.endswith(".json")]
    if not names:
        return []
    got = learn_postproc.blobs([(parent, n) for n in names] + [(sha, n) for n in names])
    out = []
    for n in names:
        old, new = learn_postproc.clue_map(got[(parent, n)]), learn_postproc.clue_map(got[(sha, n)])
        for k, (nt, ne) in new.items():
            if k in old and (old[k][0] != nt or old[k][1] != ne):
                out.append({"path": n, "key": list(k), "old": old[k][0], "new": nt,
                            "old_enum": old[k][1], "new_enum": ne})
    return out


# ---- the pair classes ------------------------------------------------------

def rewrite_side(old, new):
    """For a change to other words (clue_text.likeness under REWRITE_RATIO),
    which side is the glitch: "introduced" (the held clue was whole: its
    words, its cross-reference) or "fixed" (the held one held more glitches).
    None when the change is no rewrite."""
    if not (old or "").strip() or not (new or "").strip() or clue_text.likeness(old, new) >= REWRITE_RATIO:
        return None
    # Not ocr_clues.bled: it takes an old clue's "(anag.)" for a bracket bled in.
    g_old, g_new = sum(clue_text.glitch_counts(old).values()), sum(clue_text.glitch_counts(new).values())
    if g_old > g_new:
        return "fixed"
    return "introduced"


SEE_ONLY = re.compile(r"^\W*see\s+\d", re.IGNORECASE)


def enum_side(old_e, new_e, new_text=""):
    """(class, side): g:enum-structure "introduced" when the new enumeration
    lost word breaks at the same total ("4-4" to "8", enumeration.structure_lost),
    "fixed" when it gained them; g:enum-dropped "introduced" when it went
    missing, "fixed" when it came back. A clue that is a cross-reference
    ("See 1 ac") has none of its own. (None, None) otherwise."""
    if old_e == new_e or SEE_ONLY.match(new_text or ""):
        return None, None
    if old_e and not new_e:
        return "g:enum-dropped", "introduced"
    if new_e and not old_e:
        return "g:enum-dropped", "fixed"
    if enumeration.structure_lost(old_e, new_e):
        return "g:enum-structure", "introduced"
    if enumeration.structure_lost(new_e, old_e):
        return "g:enum-structure", "fixed"
    return None, None


def classify(p, regressions=None):
    """(introduced classes, fixed classes) of one old -> new change.
    `regressions`: file_archive_org_puzzles.regressions, for i:regressed."""
    old, new = p.get("old") or "", p.get("new") or ""
    intro, fixed = [], []
    if old != new:
        a, b = clue_text.glitch_counts(old), clue_text.glitch_counts(new)
        for c in clue_text.GLITCHES:
            if b.get(c, 0) > a.get(c, 0):
                intro.append(c)
            elif b.get(c, 0) < a.get(c, 0):
                fixed.append(c)
        if old.strip() and not new.strip():
            intro.append("i:empty")
        elif new.strip() and not old.strip():
            fixed.append("i:empty")
        side = rewrite_side(old, new)
        if side:
            (intro if side == "introduced" else fixed).append("f:rewrite")
        if regressions and side is None and old.strip() and new.strip():
            if regressions(old, new):
                intro.append("i:regressed")
            elif regressions(new, old):
                fixed.append("i:regressed")
    cls, side = enum_side(p.get("old_enum"), p.get("new_enum"), new)
    if cls:
        (intro if side == "introduced" else fixed).append(cls)
    return intro, fixed


def verdict(intro, fixed):
    return "introduced-glitch" if intro else "fixed-glitch" if fixed else "neutral"


def _regressions():
    """file_archive_org_puzzles.regressions, or None when the lexicon is not to hand."""
    try:
        from file_archive_org_puzzles import regressions
        return regressions
    except Exception as e:  # pragma: no cover - a checkout without the corpus
        print("audit: no lexicon (%s): no i:regressed class" % e, file=sys.stderr)
        return None


def audit_rows(pairs, meta=None):
    regressions = _regressions()
    rows = []
    for p in pairs:
        intro, fixed = classify(p, regressions)
        rows.append({**(meta or {}), **{k: p.get(k) for k in ("commit", "time", "subject", "path", "key", "old",
                                                              "new", "old_enum", "new_enum") if k in p},
                     "introduced": intro, "fixed": fixed, "verdict": verdict(intro, fixed)})
    return rows


# ---- tally and alerts ------------------------------------------------------

def tally(rows):
    """{class: [introduced, fixed]} and {verdict: count}."""
    by = collections.defaultdict(lambda: [0, 0])
    v = collections.Counter(r["verdict"] for r in rows)
    for r in rows:
        for c in r["introduced"]:
            by[c][0] += 1
        for c in r["fixed"]:
            by[c][1] += 1
    return dict(sorted(by.items())), v


def examples(rows, cls, n=2):
    out = []
    for r in rows:
        if cls in r["introduced"]:
            e = "%s %s: %r -> %r" % (r.get("path", "").rsplit("/", 1)[-1].replace(".json", ""),
                                    "".join(str(x) for x in reversed(r.get("key") or [])), r["old"], r["new"])
            if cls.startswith("g:"):
                e += " (%s -> %s)" % (r.get("old_enum"), r.get("new_enum"))
            out.append(e)
            if len(out) >= n:
                break
    return out


def alerts(new_rows, history, window_hours):
    """[line] for each class `new_rows` introduced that is new (none in
    `history`, rows of the HISTORY_HOURS before) or spiking: more than
    SPIKE_FLOOR and more than SPIKE_FACTOR times its hourly mean in
    `history` over `window_hours`."""
    now_n = collections.Counter(c for r in new_rows for c in r["introduced"])
    if not now_n:
        return []
    times = [r["time"] for r in history if r.get("time")]
    span = max(1.0, min(HISTORY_HOURS, (max(times) - min(times)) / 3600)) if times else 0
    past = collections.Counter(c for r in history for c in r["introduced"])
    out = []
    for c, n in now_n.most_common():
        mean = past[c] / span if span else 0.0
        expect = mean * window_hours
        new = span >= 24 and past[c] == 0
        spike = n > SPIKE_FLOOR and n > SPIKE_FACTOR * expect
        if new or spike:
            ex = examples(new_rows, c, 1)
            out.append("ALERT %s %s: %d introduced in %.1fh (7-day mean %.2f/h)%s" % (
                c, "new" if new else "spiking", n, window_hours, mean, "; e.g. " + ex[0][:200] if ex else ""))
    return out


def read_rows(path):
    try:
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="origin/master")
    ap.add_argument("--since", default="1.day", help="first run (no cursor) or --no-cursor: how far back")
    ap.add_argument("--cursor", default=DEFAULT_CURSOR)
    ap.add_argument("--no-cursor", action="store_true", help="ignore and leave the cursor; read --since")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--load", help="audit learn_postproc --pairs JSONL instead of git; writes nothing")
    ap.add_argument("--examples", type=int, default=0, help="print N examples of each class introduced")
    ap.add_argument("--alerts", action="store_true")
    ap.add_argument("--reclassify", action="store_true",
                    help="class the rows of --out again with the detectors as they are now, in place; no git")
    a = ap.parse_args()

    if a.reclassify:
        old = read_rows(a.out)
        rows = audit_rows(old)
        with open(a.out + ".tmp", "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        os.replace(a.out + ".tmp", a.out)
        history, window = [], 0.5
    elif a.load:
        rows = audit_rows([json.loads(line) for line in open(a.load)])
        history, window = [], 0.5
    else:
        cursor = None
        prev_run = None
        if not a.no_cursor and os.path.exists(a.cursor):
            cursor = Path(a.cursor).read_text().strip() or None
            prev_run = os.path.getmtime(a.cursor)
        tip = learn_postproc.git("rev-parse", a.ref).strip()
        audited = {r.get("commit") for r in read_rows(a.out)}
        rows = []
        for sha, parent, ct, subj in commits(a.ref, a.since, cursor):
            if sha in audited:
                continue
            rows += audit_rows(pairs_of(sha, parent), {"commit": sha, "time": ct, "subject": subj})
        start = min((r["time"] for r in rows), default=time.time())
        history = [r for r in read_rows(a.out) if r.get("time") and start - HISTORY_HOURS * 3600 <= r["time"] < start]
        window = min(24.0, max(0.5, (time.time() - prev_run) / 3600)) if prev_run else 0.5
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        if not a.no_cursor:
            Path(a.cursor).write_text(tip + "\n")
    by, v = tally(rows)
    print("%d clue changes: %s" % (len(rows), ", ".join("%s %d" % kv for kv in sorted(v.items()))))
    for c, (i, x) in by.items():
        print("  %-22s introduced %4d  fixed %4d" % (c, i, x))
        for e in examples(rows, c, a.examples) if a.examples else ():
            print("      " + e[:220])
    if a.alerts:
        for line in alerts(rows, history, window):
            print(line)


if __name__ == "__main__":
    main()
