#!/usr/bin/env python3
"""What the deploy's validate job has to check, from what changed since the
last deployed commit.

    python3 tools/validate_scope.py BASE      # the diff BASE..HEAD, decided
    -> "full <reason>"                          one line: check every puzzle
    -> "files" then one puzzle path per line    check just these (maybe none)

A puzzle's check reads its own file plus the validator's code and the data
files that code opens, so a change can only alter another puzzle's answer if
it touches one of those. Nothing here is a list somebody keeps: the code is
what tools/code_reach.py says validate_annotations.main (and the authored
puzzle's builder) reach, and the data files are the names those modules'
sources mention. A tools/*.py edit that leaves every reached definition's
syntax tree alone (a comment, a helper nothing reached calls, a script that is
not imported) leaves the check incremental; so does any file no reached module
names (tests, other workflows, the budgets table).

Conservative by construction: a name that merely appears in a comment of a
reached module counts as read, an added or removed module that is reached is
a full check, and anything that cannot be compared (a base file git cannot
show) is a full check too.
"""
import re
import subprocess
import sys
from pathlib import Path

import code_reach

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
#: (module, root definition) the check starts from: the validator, and the
#: builder of the one puzzle the full check covers that is not a file.
ROOTS = (("validate_annotations", "main"), ("build_authored_puzzle", "main"))
#: Changed puzzle files are checked one by one; these folders no check reads.
UNREAD = ("clues_only/", "docs/")
WORKFLOW = ".github/workflows/pages.yml"
_HEAD = []


def reached(texts=None):
    """{(module, definition): hashed form} for everything ROOTS reach; the
    answer for tools/ as it stands is worked out once per process (it parses
    twenty modules)."""
    if texts is None and _HEAD:
        return _HEAD[0]
    out = {}
    for module, root in ROOTS:
        out.update(code_reach.reach(module, [root], texts))
    if texts is None:
        _HEAD.append(out)
    return out


def sources(modules, texts=None):
    """The text of each module's source, from `texts` or tools/."""
    texts = texts or {}
    return {m: texts[m] if m in texts else (TOOLS / f"{m}.py").read_text(encoding="utf-8") for m in modules}


def named_files(modules):
    """The data file names (anything with a .ext that is not .py) the reached
    modules' sources mention, plus the clues file the workflow feeds the
    authored builder: a change to a file with such a name may change a check."""
    names = set()
    for text in sources(modules).values():
        names.update(re.findall(r"[\w.\-]+\.(?:json|tsv|txt|md|csv|yaml|yml)\b", text))
    flow = ROOT / WORKFLOW
    if flow.exists():
        names.update(Path(m).name for m in re.findall(r"--clues\s+(\S+)", flow.read_text(encoding="utf-8")))
    return names


def decide(changes, base_text=None):
    """("full", reason) or ("files", [puzzle paths]) for `changes`, a list of
    (git status letter, path). base_text(path) is the file as at the base
    (None when git cannot show it); it is only called for a modified tools/
    module the check reaches."""
    head = reached()
    modules = {m for m, _ in head}
    names = None
    check, edited = [], {}
    for st, path in changes:
        if path.startswith(UNREAD):
            continue
        if re.fullmatch(r"puzzles/[^/]+/[^/]+/[^/]+\.json", path):
            if st in ("A", "M"):
                check.append(path)
            elif st != "D":
                return "full", f"{st} {path}"
            continue
        if path == WORKFLOW:
            return "full", f"{path} changed"
        m = re.fullmatch(r"tools/([^/]+)\.py", path)
        if m:
            if m.group(1) not in modules:
                continue  # not imported by anything the check runs (a deleted one included)
            if st != "M":
                return "full", f"{st} {path}"
            old = base_text(path) if base_text else None
            if old is None:
                return "full", f"{path} changed and its old text is not to hand"
            edited[m.group(1)] = old
            continue
        if names is None:
            names = named_files(modules)
        if Path(path).name in names:
            return "full", f"{path} changed, a file the check reads"
    if edited:
        before = reached(edited)
        after = head
        if before != after:
            moved = sorted(f"{m}.{d}" for m, d in set(before) ^ set(after)
                           | {k for k in before if k in after and before[k] != after[k]})
            return "full", "the check's code changed: " + ", ".join(moved[:6]) + (" ..." if len(moved) > 6 else "")
    return "files", check


def git_changes(base):
    out = subprocess.run(["git", "-C", str(ROOT), "diff", "--no-renames", "--name-status", base, "HEAD"],
                         check=True, capture_output=True, text=True).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if line]


def git_show(base):
    def show(path):
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"{base}:{path}"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None
    return show


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    changes = git_changes(argv[0])
    print(f"since {argv[0]} (last deployed): {len(changes)} path(s) changed", file=sys.stderr)
    for st, path in changes[:60]:
        print(f"  {st}\t{path}", file=sys.stderr)
    if len(changes) > 60:
        print(f"  ... and {len(changes) - 60} more", file=sys.stderr)
    mode, what = decide(changes, git_show(argv[0]))
    if mode == "full":
        print(f"full {what}")
    else:
        print("files")
        print("\n".join(what))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
