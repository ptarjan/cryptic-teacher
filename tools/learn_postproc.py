#!/usr/bin/env python3
"""Mine the clue-text rewrites in "Update ..." commits for post-processor rules.

    python3 tools/learn_postproc.py                       # last 5 days of origin/master
    python3 tools/learn_postproc.py --since 3.days --out /tmp/classes.tsv
    python3 tools/learn_postproc.py --ref origin/master --pairs /tmp/pairs.jsonl
    python3 tools/learn_postproc.py --rules               # score the shipped rules
    python3 tools/learn_postproc.py --after-mend          # only the classes no rule makes yet

A reread (OCR + vision model) rewrites clue text in a held puzzle file and the
commit is titled "Update times-N" or "Update N puzzles". Many rewrites are
mechanical: a character confusion, a lost space, a glued footer. This walks
those commits, pairs each clue's old and new text (same direction and number),
splits the change into word-level edits, and counts each edit by CLASS, so a new
class that keeps recurring shows up as a row to turn into a rule in the existing
homes (clue_text / punctuation / clue_repair; tools/repair_fetched.py for files
already held). Nothing here changes a puzzle.

Output: a TSV of  class, count, clues, example old -> new  (first few), sorted
by count. --rules re-scores each shipped rule against the same pairs: HITS is the
number of rewrites the rule alone reproduces exactly, CLOSER the ones it moves
nearer without finishing, WORSE the ones it moves away, and FIXPOINT the reread
texts it would still change (a text a reader left as right). The bar is
WORSE = FIXPOINT = 0. A class is worth a rule only when the new text follows from
the old text plus a lexicon or the clue's count or grid; a reread that adds or
drops a word, or flips a convention both ways (a space before "?"), is not.
"""
import argparse
import collections
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

# Rebuilt from git history on every run: a derived cache, so ~/.cache.
DEFAULT_OUT = os.environ.get("POSTPROC_LEARN_OUT") or str(
    Path.home() / ".cache" / "postproc_learn" / "classes.tsv")


def git(*args, check=True):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                          text=True, check=check).stdout


def update_commits(ref, since):
    out = git("log", ref, "--since=" + since, "--no-merges",
              "--format=%H%x09%P%x09%s")
    for line in out.splitlines():
        h, parents, subj = (line.split("\t") + ["", ""])[:3]
        if subj.startswith("Update") and parents:
            yield h, parents.split()[0]


def blobs(paths_by_rev):
    """{(rev, path): text or None} through one git cat-file --batch."""
    want = [f"{rev}:{p}" for rev, p in paths_by_rev]
    if not want:
        return {}
    proc = subprocess.run(["git", "-C", ROOT, "cat-file", "--batch"],
                          input=("\n".join(want) + "\n").encode(), capture_output=True)
    data, got, i = proc.stdout, {}, 0
    for key in paths_by_rev:
        nl = data.index(b"\n", i)
        head = data[i:nl].decode().split()
        if len(head) == 3 and head[1] == "blob":
            size = int(head[2])
            got[key] = data[nl + 1:nl + 1 + size].decode("utf-8", "replace")
            i = nl + 1 + size + 1
        else:
            got[key] = None
            i = nl + 1
    return got


def clue_map(text):
    if not text:
        return {}
    try:
        d = json.loads(text)
    except ValueError:
        return {}
    out = {}
    for e in d.get("entries") or []:
        c = e.get("clue") or {}
        if isinstance(c.get("text"), str):
            out[(e.get("direction"), e.get("number"))] = (c["text"], c.get("enumeration"))
    return out


def mine_pairs(ref, since):
    """Yield dicts {commit, path, key, old, new, old_enum, new_enum}."""
    for h, parent in update_commits(ref, since):
        names = git("diff-tree", "-r", "--no-renames", "--name-only", parent, h,
                    "--", "puzzles").split()
        names = [n for n in names if n.endswith(".json")]
        if not names:
            continue
        need = [(parent, n) for n in names] + [(h, n) for n in names]
        got = blobs(need)
        for n in names:
            old, new = clue_map(got[(parent, n)]), clue_map(got[(h, n)])
            for k, (nt, ne) in new.items():
                if k in old and old[k][0] != nt:
                    yield {"commit": h[:11], "path": n, "key": list(k),
                           "old": old[k][0], "new": nt,
                           "old_enum": old[k][1], "new_enum": ne}


# ---- classing -------------------------------------------------------------

def _shape(s):
    """Collapse a fragment to a short comparable shape."""
    s = re.sub(r"[A-Za-z]", "a", s)
    s = re.sub(r"\d", "9", s)
    return s


def classify_edit(a, b):
    """One word-level edit (old fragment a, new fragment b) -> class name."""
    if a == b:
        return "same"
    if a.replace(" ", "") == b.replace(" ", ""):
        return "space:lost" if len(b) < len(a) and False else (
            "space:added" if len(b) > len(a) else "space:removed")
    if a.lower() == b.lower():
        return "case"
    qa = re.sub(r"[‘’“”`\"']", "'", a)
    qb = re.sub(r"[‘’“”`\"']", "'", b)
    if qa == qb:
        return "quote-style"
    pa = re.sub(r"[\W_]", "", a)
    pb = re.sub(r"[\W_]", "", b)
    if pa == pb:
        if not b and re.fullmatch(r"[\W_]+", a):
            return "stray-token:" + (a if len(a) < 4 else "long")
        if not a and re.fullmatch(r"[\W_]+", b):
            return "added-token:" + (b if len(b) < 4 else "long")
        ops = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, a, b, autojunk=False).get_opcodes():
            if op != "equal":
                ops.append("%s[%s>%s]" % (op[0], a[i1:i2], b[j1:j2]))
        return "punct:" + ",".join(ops[:2])
    if not a:
        return "insert-word" if re.search(r"[A-Za-z]", b) else "insert-punct"
    if not b:
        if re.fullmatch(r"[\W_]+", a):
            return "delete-punct"
        if re.fullmatch(r"\(?\d[\d,\- ]*\)?", a):
            return "delete-number"
        return "delete-word"
    if len(a) == len(b):
        diffs = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diffs) == 1:
            return "char:%s>%s" % diffs[0]
        return "chars-same-length"
    if a.endswith(b) or a.startswith(b):
        return "trim-affix"
    if b.endswith(a) or b.startswith(a):
        return "add-affix"
    return "rewrite"


def edits(old, new):
    ta, tb = old.split(), new.split()
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a, b = " ".join(ta[i1:i2]), " ".join(tb[j1:j2])
        # a space edit shows as two words <-> one; glue back to compare
        out.append((a, b))
    return out


def clue_classes(old, new):
    if " ".join(old.split()) == " ".join(new.split()) and old != new:
        return ["whitespace-run"]
    cs = []
    for a, b in edits(old, new):
        cs.append(classify_edit(a, b))
    return cs or ["other"]


def table(pairs, limit=3):
    count = collections.Counter()
    clues = collections.defaultdict(set)
    ex = collections.defaultdict(list)
    for i, p in enumerate(pairs):
        for a, b in edits(p["old"], p["new"]) or [("", "")]:
            c = classify_edit(a, b)
            count[c] += 1
            clues[c].add(i)
            if len(ex[c]) < limit:
                ex[c].append("%s -> %s" % (a[:40], b[:40]))
    return [(c, n, len(clues[c]), " | ".join(ex[c])) for c, n in count.most_common()]


def write_table(rows, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write("class\tedits\tclues\texamples\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")


# ---- rule scoring ---------------------------------------------------------

def rule_registry():
    """name -> function(text, enum) -> text, one per shipped rule, each the
    function the rule lives in (so a rule moved or renamed is scored where it
    is). Add a row here when a class turns into a rule."""
    import clue_repair
    import clue_text
    is_word = clue_repair.lexicon()[0]
    return {
        "stray_underscore": lambda t, e: clue_text.stray_underscore(t),
        "speck_figures": lambda t, e: clue_text.speck_figures(t),
        "trailing_count (specked)": clue_repair.trailing_count,
        "stub_before_word": lambda t, e: clue_repair.stub_before_word(t, is_word),
        "mend_text (all rules)": lambda t, e: clue_repair.mend_text(t, e),
    }


def residual(pairs):
    """`pairs` with each old text run through clue_repair.mend_text first, and
    the pairs it makes whole dropped: what is left is what no rule does yet."""
    import clue_repair
    is_word, uses = clue_repair.lexicon()
    out = []
    for p in pairs:
        got = clue_repair.mend_text(p["old"], p["old_enum"], is_word, uses)
        if got != p["new"]:
            out.append(dict(p, old=got))
    return out


def _distance(a, b):
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in
               difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op != "equal")


def score(pairs, reg):
    """[(rule, hits, closer, worse, fixpoint)]. HITS: the rule alone turns
    the old text into the reread's. CLOSER: it moves the old text nearer the
    reread's (another slip remains). WORSE: it moves it away. FIXPOINT: it
    would change a reread's own text, a text a reader left as right. The bar
    for a rule is worse = fixpoint = 0."""
    rows = []
    for name, fn in reg.items():
        hits = closer = worse = fixpoint = 0
        for p in pairs:
            got = fn(p["old"], p["old_enum"])
            if got != p["old"]:
                if got == p["new"]:
                    hits += 1
                elif _distance(got, p["new"]) < _distance(p["old"], p["new"]):
                    closer += 1
                else:
                    worse += 1
            if fn(p["new"], p["new_enum"]) != p["new"]:
                fixpoint += 1
        rows.append((name, hits, closer, worse, fixpoint))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="origin/master")
    ap.add_argument("--since", default="5.days")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--pairs", help="dump the old/new pairs as JSON lines here")
    ap.add_argument("--load", help="read pairs from this JSONL instead of git")
    ap.add_argument("--rules", action="store_true")
    ap.add_argument("--after-mend", action="store_true",
                    help="class only what clue_repair.mend_text leaves: the rewrites no rule makes yet "
                         "(those mend_text already reproduces are dropped)")
    a = ap.parse_args()
    if a.load:
        pairs = [json.loads(l) for l in open(a.load)]
    else:
        pairs = list(mine_pairs(a.ref, a.since))
        if a.pairs:
            os.makedirs(os.path.dirname(a.pairs) or ".", exist_ok=True)
            with open(a.pairs, "w") as f:
                for p in pairs:
                    f.write(json.dumps(p) + "\n")
    if a.after_mend:
        pairs = residual(pairs)
    rows = table(pairs)
    write_table(rows, a.out)
    print("%d rewritten clues; classes -> %s" % (len(pairs), a.out))
    for r in rows[:15]:
        print("%7d %6d  %-22s %s" % (r[1], r[2], r[0], r[3][:80]))
    if a.rules:
        for name, hits, closer, worse, fixpoint in score(pairs, rule_registry()):
            print("rule %-26s hits=%d closer=%d worse=%d fixpoint=%d" % (name, hits, closer, worse, fixpoint))


if __name__ == "__main__":
    main()
