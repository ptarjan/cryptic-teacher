#!/usr/bin/env python3
"""The pre-push check: the few CI failures a push can be refused for in seconds.

    python3 tools/pre_push.py <base> <head>    # what .githooks/pre-push runs
    python3 tools/pre_push.py --copies          # just the scratch-copy check, over every test

It judges the files <base>..<head> changes, read from the working tree, and
prints the cause of every failure it finds; exit 1 refuses the push.

A push that changes only puzzles/ and clues_only/ (the jobs push one every few
seconds) gets the per-file checks alone: tools/puzzle_schema.py on its ids and
tools/puzzle_integrity.py on its files, which weighs them against the rest of
the corpus (NEARDUP, DATE, DUPLICATE) through its cache.

A push that changes code also gets, each over the changed files only:
  - ruff's syntax and undefined-name rules on the changed .py files;
  - no `| grep -q` in a changed .sh that sets pipefail (SIGPIPE makes it 141);
  - the scratch-copy check: a test that copies tools/X.py into a scratch tree
    must copy every tools/ module X imports at module level, or X dies there
    with ModuleNotFoundError;
  - tools/test_ci_cache_deps.js, when tools/ changed;
  - up to MAX_TESTS test scripts: changed ones, each changed file's own
    test_<name>, then those importing a changed module, cheapest first, run side by side
    until DEADLINE. One still running then is stopped and left to CI, never
    counted as failed. Scripts that read the built pages or that CI charges
    more than SLOW seconds (tools/ci_shards.js COST) are left to CI outright.
"""

import ast
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
DEADLINE = 14.0
MAX_TESTS = 6
SLOW = 10
PARALLEL = 4
DATA_DIRS = ("puzzles/", "clues_only/")
PUZZLE_FILE = re.compile(r"^(?:puzzles|clues_only)/.+/([^/]+)\.json$")


def changed_files(base, head):
    out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=AMR", "-z", f"{base}...{head}"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def tests():
    return sorted(p for p in TOOLS.iterdir()
                  if re.fullmatch(r"test_.+\.(sh|js)|.+_test\.(sh|js)", p.name))


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


def ci_cost():
    """tools/ci_shards.js's COST table and PAGES set, read from the file."""
    text = (TOOLS / "ci_shards.js").read_text(encoding="utf-8")
    cost = {k: int(v) for k, v in re.findall(r'"(tools/[^"]+)":\s*(\d+)', text.split("const COST", 1)[1].split("};", 1)[0])}
    pages = set(re.findall(r'"(tools/[^"]+)"', text.split("const PAGES", 1)[1].split(";", 1)[0]))
    return cost, pages


def pick_tests(changed):
    """At most MAX_TESTS test scripts: a changed test itself first, then each
    changed file's own test_<name>, then those importing a changed module, each
    rank by CI cost."""
    cost, pages = ci_cost()
    stems = {Path(p).stem for p in changed if p.startswith("tools/") and p.count("/") == 1
             and Path(p).suffix in (".py", ".sh", ".js")}
    picked = {}
    for test in tests():
        rel = test.relative_to(ROOT).as_posix()
        if rel in pages or cost.get(rel, 3) > SLOW:
            continue
        text = test.read_text(encoding="utf-8")
        own = test.stem.removeprefix("test_").removesuffix("_test")
        if rel in changed:
            picked[rel] = 0
        elif own in stems:
            picked[rel] = 1
        elif any(re.search(rf"^\s*(?:import|from)\s+{re.escape(s)}\b", text, re.MULTILINE) for s in stems):
            picked[rel] = 2
    return sorted(picked, key=lambda r: (picked[r], cost.get(r, 3), r))[:MAX_TESTS]


def clean_env():
    env = dict(os.environ)
    names = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=False).stdout.split()
    for name in names:
        env.pop(name, None)
    return env


def run_tests(todo, deadline):
    env = clean_env()
    running, failed, unfinished, passed = {}, [], [], []
    queue = list(todo)
    while queue or running:
        while queue and len(running) < PARALLEL and time.monotonic() < deadline:
            t = queue.pop(0)
            log = tempfile.TemporaryFile()
            cmd = ["bash" if t.endswith(".sh") else "node", t]
            running[t] = (subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, start_new_session=True), log)
        for t, (proc, log) in list(running.items()):
            if proc.poll() is None:
                continue
            del running[t]
            if proc.returncode == 0:
                passed.append(t)
            else:
                log.seek(0)
                tail = log.read().decode("utf-8", "replace").splitlines()[-25:]
                failed.append((t, proc.returncode, tail))
            log.close()
        if time.monotonic() >= deadline:
            for t, (proc, log) in running.items():
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                log.close()
                unfinished.append(t)
            running = {}
            unfinished.extend(queue)
            queue = []
        time.sleep(0.05)
    return passed, failed, unfinished


def main(argv):
    if argv == ["--copies"]:
        problems = check_copies()
        for p in problems:
            print(f"pre-push: {p}", file=sys.stderr)
        return 1 if problems else 0
    base, head = argv
    started = time.monotonic()
    changed = changed_files(base, head)
    fails = []

    puzzles = [p for p in changed if PUZZLE_FILE.match(p) and (ROOT / p).is_file()]
    if puzzles:
        ids = [PUZZLE_FILE.match(p).group(1) for p in puzzles]
        r = subprocess.run([sys.executable, "tools/puzzle_schema.py", *ids], cwd=ROOT, capture_output=True, text=True, check=False)
        if r.returncode:
            fails.append(("tools/puzzle_schema.py on the pushed puzzles", (r.stdout + r.stderr).splitlines()[-25:]))
        published = [p for p in puzzles if p.startswith("puzzles/")]
        if published:
            r = subprocess.run([sys.executable, "tools/puzzle_integrity.py", "--quiet", *published],
                               cwd=ROOT, capture_output=True, text=True, check=False)
            if r.returncode:
                fails.append(("tools/puzzle_integrity.py on the pushed puzzles", (r.stdout + r.stderr).splitlines()[-25:]))

    code = [p for p in changed if not p.startswith(DATA_DIRS)]
    passed = unfinished = []
    if code:
        py = [p for p in code if p.endswith(".py") and (ROOT / p).is_file()]
        if py and shutil.which("ruff"):
            r = subprocess.run(["ruff", "check", "--no-cache", "--isolated", "--select", "E9,F63,F7,F82",
                                "--output-format", "concise", *py], cwd=ROOT, capture_output=True, text=True, check=False)
            if r.returncode:
                fails.append(("ruff (syntax errors, undefined names)", r.stdout.splitlines()[-25:]))
        sh = [p for p in code if p.endswith(".sh") and (ROOT / p).is_file()]
        grep_problems = check_pipefail_grep(sh)
        if grep_problems:
            fails.append(("`| grep -q` under pipefail", grep_problems))
        copy_problems = check_copies()
        if copy_problems:
            fails.append(("the scratch-copy check", copy_problems))
        if any(p.startswith(("tools/", "sync/", "vendor/")) or p.endswith(".js") for p in code):
            r = subprocess.run(["node", "tools/test_ci_cache_deps.js"], cwd=ROOT, capture_output=True, text=True, check=False)
            if r.returncode:
                fails.append(("tools/test_ci_cache_deps.js", (r.stdout + r.stderr).splitlines()[-25:]))
        passed, failed, unfinished = run_tests(pick_tests(code), started + DEADLINE)
        for t, rc, tail in failed:
            fails.append((f"{t} (exit {rc})", tail))

    took = time.monotonic() - started
    if unfinished:
        print(f"pre-push: left to CI, not finished in {DEADLINE:.0f}s: {' '.join(unfinished)}", file=sys.stderr)
    if fails:
        for what, lines in fails:
            print(f"pre-push: FAILED {what}:", file=sys.stderr)
            for line in lines:
                print(f"    {line}", file=sys.stderr)
        print(f"pre-push: {len(fails)} check(s) failed in {took:.1f}s; CI would go red. "
              "Fix and push again.", file=sys.stderr)
        return 1
    if code or puzzles:
        print(f"pre-push: ok in {took:.1f}s ({len(puzzles)} puzzle file(s), {len(passed)} test script(s) passed)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
