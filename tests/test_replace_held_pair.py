#!/usr/bin/env python3
# Does tools/replace_held_pair.py delete only the file of a held-out DATE pair whose
# count its filed neighbours now contradict, and make its edition due again?
#
#     python3 tests/test_replace_held_pair.py
#
# Fixtures in a scratch git tree and a fake HOME; no live ~/.cache, ledger or corpus.
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(tmp / "home")
import _path  # puts tools/ on sys.path
import file_archive_org_puzzles as fa
import replace_held_pair as rhp

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def git(tree, *a):
    subprocess.run(["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True,
                   capture_output=True)


def put(tree, n, day):
    p = Path(tree) / f"puzzles/independent/1998/independent-{n}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"id": f"independent-{n}", "number": n, "date": day}))
    return p.relative_to(tree).as_posix()


def tree_with_pair(name, first, second):
    """A tree whose filed 3659 (07-10) and 3668 (07-21) are committed and whose pair `first`,
    `second` ((number, day)) is new."""
    tree = tmp / name
    tree.mkdir()
    git(tree, "init", "-q")
    for n, day in ((3658, "1998-07-09"), (3659, "1998-07-10"), (3668, "1998-07-21"), (3669, "1998-07-22")):
        put(tree, n, day)
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "filed")
    paths = [put(tree, *first), put(tree, *second)]
    why = {}
    for p, other in ((paths[0], second), (paths[1], first)):
        hi, lo = (first, second) if first[0] > second[0] else (second, first)
        why[p] = f"DATE independent-{lo[0]}: dated {lo[1]}, not after independent-{hi[0]}'s {hi[1]}"
    return tree, paths, why


ledger = tmp / "filed.jsonl"
ledger.write_text("".join(json.dumps({"edition": f"GaleIndependent1998UKEnglish/{day}", "inputs": "x",
                                      "verdicts": [{"id": f"independent-{n}", "wrote": True}]}) + "\n"
                          for n, day in ((3661, "1998-07-20"), (3666, "1998-07-18"))))

tree, (p61, p66), why = tree_with_pair("a", (3661, "1998-07-20"), (3666, "1998-07-18"))
check("pair found", rhp.pairs_of(why) == [(p66, p61)] or rhp.pairs_of(why) == [(p61, p66)])
done = rhp.replace_pair(tree, why, fa, ledger)
check("the misread 3661 is deleted", [d[0] for d in done] == [p61] and not (tree / p61).exists())
check("the right 3666 stays held in the tree", (tree / p66).exists())
check("its edition is named", done and done[0][1] == "GaleIndependent1998UKEnglish/1998-07-20")
last = [json.loads(line) for line in ledger.read_text().splitlines()][-1]
check("a bare row makes it due 'never read'", "inputs" not in last and last["edition"].endswith("1998-07-20"))
check("due_reason says never read", fa.due_reason(last, "x", None, None) == "never read")

tree, (a, b), why = tree_with_pair("b", (3667, "1998-07-20"), (3666, "1998-07-18"))
check("both agree: nothing changes", rhp.replace_pair(tree, why, fa, ledger) == [] and (tree / a).exists() and (tree / b).exists())

tree, (a, b), why = tree_with_pair("c", (3661, "1998-07-20"), (3600, "1998-07-18"))
check("both contradicted: nothing changes", rhp.replace_pair(tree, why, fa, ledger) == [] and (tree / a).exists() and (tree / b).exists())

tree, (a, b), why = tree_with_pair("d", (3661, "1998-07-20"), (3666, "1998-07-18"))
git(tree, "add", "-A")
git(tree, "commit", "-q", "-m", "pair committed")
check("files already in HEAD are never deleted", rhp.replace_pair(tree, why, fa, ledger) == [] and (tree / a).exists())

check("a finding naming one file is no pair", rhp.pairs_of({p61: why[a]}) == [])

print(f"{fails} failed" if fails else "all passed")
sys.exit(1 if fails else 0)
