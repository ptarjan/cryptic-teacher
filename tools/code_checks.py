#!/usr/bin/env python3
"""The code lint CI runs (tests.yml, "generated files are current"). It was the
code half of the pre-push hook, which is gone; these are the checks only it ran.

    python3 tools/code_checks.py

Over every .py and .sh under tools/ and sync/, prints the cause of each failure
and exits 1:
  - ruff's syntax and undefined-name rules (E9, F63, F7, F82);
  - no `| grep -q` in a .sh that sets pipefail (SIGPIPE makes it 141);
  - the scratch-copy check: a test that copies tools/X.py into a scratch tree
    must copy every tools/ module X imports at module level, or X dies there
    with ModuleNotFoundError.
"""

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def tests():
    return sorted([p for p in (ROOT / "tests").iterdir()
                   if re.fullmatch(r"test_.+\.(sh|js)", p.name)]
                  + [p for p in TOOLS.iterdir() if re.fullmatch(r".+_test\.(sh|js)", p.name)])


def module_imports(path):
    """The tools/ modules `path` imports outside any function: the ones that
    must be importable for it to load at all."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    found = set()

    def walk(nodes):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(node, ast.Try) and any(
                    isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError")
                    for h in node.handlers):
                continue
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
            walk(ast.iter_child_nodes(node))

    walk(tree.body)
    return {m for m in found if (TOOLS / f"{m}.py").is_file()}


def import_closure(stem, memo):
    if stem not in memo:
        memo[stem] = set()
        todo = module_imports(TOOLS / f"{stem}.py")
        memo[stem] = set(todo)
        for dep in todo:
            memo[stem] |= import_closure(dep, memo)
    return memo[stem]


CP = re.compile(r"^\s*cp\s+(?P<args>[^|;&#]*)", re.MULTILINE)


def check_copies():
    """Every test that copies tools/X.py by name copies X's module-level
    imports too."""
    problems, memo = [], {}
    for test in tests():
        if test.suffix != ".sh":
            continue
        text = test.read_text(encoding="utf-8")
        copied, wholesale = set(), False
        for m in CP.finditer(text):
            args = m.group("args")
            if re.search(r'tools"?/\*\.py', args) or (
                    re.match(r"-\w*[rR]", args.strip()) and re.search(r'/tools"?/?\.?(\s|$)', args)):
                wholesale = True
            copied |= set(re.findall(r"tools/(\w+)\.py", args))
        if wholesale or not copied:
            continue
        for stem in sorted(copied):
            if not (TOOLS / f"{stem}.py").is_file():
                continue
            missing = sorted(import_closure(stem, memo) - copied)
            if missing:
                problems.append(f"{test.relative_to(ROOT)} copies tools/{stem}.py into a scratch tree "
                                f"without {', '.join(f'tools/{d}.py' for d in missing)}, which it imports; "
                                "copy those too or it fails there with ModuleNotFoundError")
    return problems


GREP_Q = re.compile(r"\|\s*grep\s+(?:-[A-Za-z]*\s+)*-[A-Za-z]*q")


def check_pipefail_grep(paths):
    """Under `set -o pipefail`, `cmd | grep -q PAT` fails even when PAT
    matches: grep exits at the first match, cmd dies of SIGPIPE, and the
    pipeline returns 141. `grep PAT >/dev/null` reads to the end instead."""
    problems = []
    for rel in paths:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if not re.search(r"set\s+-\S*o\s+pipefail|set\s+-o\s+pipefail|pipefail", text):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if not line.lstrip().startswith("#") and GREP_Q.search(line):
                problems.append(f"{rel}:{n}: `| grep -q` under pipefail returns 141 when the writer "
                                f"gets SIGPIPE; use `grep PAT >/dev/null`: {line.strip()}")
    return problems


def main():
    fails = []
    py = sorted(p.relative_to(ROOT).as_posix() for d in ("tools", "tests", "sync") if (ROOT / d).is_dir()
                for p in (ROOT / d).rglob("*.py") if "node_modules" not in p.parts)
    sh = sorted(p.relative_to(ROOT).as_posix() for d in ("tools", "tests", "sync") if (ROOT / d).is_dir()
                for p in (ROOT / d).rglob("*.sh"))
    if shutil.which("ruff"):
        r = subprocess.run(["ruff", "check", "--no-cache", "--isolated", "--select", "E9,F63,F7,F82",
                            "--output-format", "concise", *py], cwd=ROOT, capture_output=True, text=True, check=False)
        if r.returncode:
            fails.append(("ruff (syntax errors, undefined names)", r.stdout.splitlines()[-25:]))
    else:
        print("code_checks: ruff is not installed; skipping it", file=sys.stderr)
    for what, problems in (("`| grep -q` under pipefail", check_pipefail_grep(sh)),
                           ("the scratch-copy check", check_copies())):
        if problems:
            fails.append((what, problems))
    for what, lines in fails:
        print(f"code_checks: FAILED {what}:", file=sys.stderr)
        for line in lines:
            print(f"    {line}", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
