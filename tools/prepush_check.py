#!/usr/bin/env python3
"""The pre-push gate: refuse a push whose tools/ would break a job that reloads onto master.

    python3 tools/prepush_check.py              run every check, exit 1 on the first failures
    python3 tools/prepush_check.py --write-keys regenerate tools/data/keys.json (an intended key move)

tools/push_checked.sh runs it before pushing; CI may run it too. What it catches, each
a thing a bad merge or a hurried edit has done:

  1. a tools/*.py that does not parse, or holds a merge conflict marker at column 0;
  2. one name assigned twice at module level in edition_queue.py or file_archive_org_puzzles.py
     (11-18: a bad merge left three `NEWEST_LANDED = (...)`; the last silently won);
  3. a reason in edition_queue.UNFILED_FIRST / NEWEST_LANDED missing from RANKS, or neither a
     blanket pass, a solution fix nor a reason evidence_reason keeps (so the plan drops it with
     no log line); and new ruff F821/F811/F401 findings against origin/master (a constant that
     shadows another name);
  4. the solution key or a paper's scan key moving from tools/data/keys.json: a moved key
     rereads every row read under the old one, so pin it (the *_PINS / *_FIX tables) or, when
     the reread is intended, rerun --write-keys.

The key check needs nothing but the code (no ~/.cache, no media); it is skipped with a warning
when the modules cannot be imported or no keys file exists yet. The ruff check is skipped with a
warning when ruff or origin/master is not there.
"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
KEYS = TOOLS / "data" / "keys.json"
#: Modules whose module-level names are registries a bad merge can duplicate.
REGISTRY_MODULES = ("edition_queue.py", "file_archive_org_puzzles.py")
MARKERS = ("<<<<<<<", ">>>>>>>")
#: Duplicates already on master, tolerated until someone decides which one the code means:
#: CLUE_OPENING is a tile-opening regex at line ~3301 and a number-list regex at ~22466; every
#: function reads the later one at call time, so deleting either moves behaviour and keys.
KNOWN_DUPLICATES = {("file_archive_org_puzzles.py", "CLUE_OPENING")}
RUFF_SELECT = "F821,F811,F401"


def warn(msg):
    print(f"prepush_check: warning: {msg}", file=sys.stderr)


def conflict_markers(text):
    """[(line number, line)] of the merge conflict markers at column 0."""
    return [(n, line.rstrip()) for n, line in enumerate(text.splitlines(), 1)
            if line.startswith(MARKERS) or line.rstrip() == "======="]


def parse_problems(name, text):
    """What stops `text` (the module called `name`) from loading: a marker or a syntax error."""
    problems = [f"{name}:{n}: conflict marker `{line[:20]}`" for n, line in conflict_markers(text)]
    try:
        ast.parse(text, name)
    except SyntaxError as e:
        problems.append(f"{name}:{e.lineno}: does not parse: {e.msg}")
    return problems


def duplicate_assignments(name, text):
    """One problem per module-level name assigned more than once (a plain `NAME = ...` or
    `NAME: T = ...`; an augmented assignment or one in an if/try block is a different thing)."""
    try:
        tree = ast.parse(text, name)
    except SyntaxError:
        return []  # parse_problems says so
    seen = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for t in targets:
            seen.setdefault(t.id, []).append(node.lineno)
    base = name.rsplit("/", 1)[-1]
    return [f"{name}: {k} assigned {len(v)} times at module level (lines {', '.join(map(str, v))}); "
            "the last silently wins" for k, v in sorted(seen.items())
            if len(v) > 1 and (base, k) not in KNOWN_DUPLICATES]


def check_sources():
    problems = []
    for path in sorted(TOOLS.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        problems += parse_problems(f"tools/{path.name}", text)
        if path.name in REGISTRY_MODULES:
            problems += duplicate_assignments(f"tools/{path.name}", text)
    return problems


def registry_problems(unfiled_first, newest_landed, ranks, blanket, solution_fixes, kept):
    """Every reason queued first is ranked, and is a blanket pass, a solution fix or a kept one."""
    problems = []
    for label, reasons in (("UNFILED_FIRST", unfiled_first), ("NEWEST_LANDED", newest_landed)):
        for r in reasons:
            if r not in ranks:
                problems.append(f"{label}: {r!r} is not in file_archive_org_puzzles.RANKS")
            if r not in blanket and r not in solution_fixes and not kept(r):
                problems.append(f"{label}: {r!r} is in neither BLANKET_PASSES nor SOLUTION_FIXES, "
                                "and evidence_reason drops it at plan time")
    for r in unfiled_first:
        if not kept(r):
            problems.append(f"UNFILED_FIRST: {r!r} is not kept by evidence_reason (dropped at plan time, no log line)")
    return problems


def load_modules():
    sys.path.insert(0, str(TOOLS))
    import edition_queue as eq
    import file_archive_org_puzzles as fa
    return eq, fa


def check_registry(eq, fa):
    return registry_problems(eq.UNFILED_FIRST, eq.NEWEST_LANDED, fa.RANKS, fa.BLANKET_PASSES,
                             fa.SOLUTION_FIXES, eq.evidence_reason)


def git(*args):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return r.returncode, r.stdout


def ruff_findings(name, text):
    """Counter-like list of (code, message) ruff finds in `text`, line numbers left out, or None
    when ruff is missing."""
    try:
        r = subprocess.run(["ruff", "check", "--select", RUFF_SELECT, "--quiet", "--output-format", "concise",
                            "--stdin-filename", name, "-"], input=text, capture_output=True, text=True, cwd=REPO)
    except OSError:
        return None
    found = []
    for line in r.stdout.splitlines():
        m = re.match(r"^.*?:\d+:\d+: (F\d+) (.*)$", line)
        if m:
            found.append((m.group(1), m.group(2)))
    return found


def new_findings(old, new):
    """The (code, message) pairs `new` has more of than `old`."""
    left = list(old)
    out = []
    for f in new:
        if f in left:
            left.remove(f)
        else:
            out.append(f)
    return out


def check_ruff():
    rc, out = git("rev-parse", "--verify", "-q", "origin/master")
    if rc:
        warn("no origin/master: ruff check skipped")
        return []
    # Against the merge base, not origin/master's tip: a tree behind master would otherwise be
    # charged with what master changed since.
    rc, base_sha = git("merge-base", "HEAD", "origin/master")
    base_sha = base_sha.strip() if rc == 0 else "origin/master"
    rc, out = git("diff", "--name-only", "--diff-filter=AM", base_sha, "--", "tools/*.py")
    problems = []
    for rel in out.split():
        path = REPO / rel
        if not path.is_file():
            continue
        new = ruff_findings(rel, path.read_text(encoding="utf-8", errors="replace"))
        if new is None:
            warn("ruff is not installed: check skipped")
            return []
        rc, base = git("show", f"{base_sha}:{rel}")
        old = ruff_findings(rel, base) if rc == 0 else []
        problems += [f"{rel}: new ruff {code} {msg}" for code, msg in new_findings(old, new)]
    return problems


def current_keys(fa):
    papers = {p.key: p for p in (getattr(fa, a) for a in dir(fa)) if hasattr(p, "margin") and hasattr(p, "key")}
    return {"solution": fa.solution_key(), "scan": {k: fa.scan_key(p) for k, p in sorted(papers.items())}}


def flat(keys):
    out = {"solution": keys.get("solution")}
    out.update({f"scan:{k}": v for k, v in keys.get("scan", {}).items()})
    return out


def key_problems(pinned, now):
    """One line per key in `pinned` or `now` whose value differs (a paper's new key is a move too)."""
    old, new = flat(pinned), flat(now)
    problems = []
    for name in sorted(set(old) | set(new)):
        if old.get(name) != new.get(name):
            problems.append(f"key {name} moved {old.get(name)} -> {new.get(name)}: pin it (*_FIX table) "
                            "or rerun --write-keys if intended")
    return problems


def check_keys(fa):
    if not KEYS.is_file():
        warn(f"{KEYS.relative_to(REPO)} is missing: key check skipped (run --write-keys)")
        return []
    return key_problems(json.loads(KEYS.read_text(encoding="utf-8")), current_keys(fa))


def main(argv):
    write = "--write-keys" in argv
    problems = check_sources()
    if problems:
        # nothing below can import a module that does not parse
        print("\n".join(problems))
        return 1
    try:
        eq, fa = load_modules()
    except Exception as e:
        warn(f"edition_queue / file_archive_org_puzzles did not import ({type(e).__name__}: {e}): "
             "registry and key checks skipped")
        eq = fa = None
    if write:
        if fa is None:
            print("cannot compute keys: the modules do not import")
            return 1
        KEYS.write_text(json.dumps(current_keys(fa), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {KEYS.relative_to(REPO)}")
        return 0
    if eq is not None:
        problems += check_registry(eq, fa)
    problems += check_ruff()
    if fa is not None:
        try:
            problems += check_keys(fa)
        except Exception as e:
            warn(f"keys could not be computed ({type(e).__name__}: {e}): key check skipped")
    if problems:
        print("\n".join(problems))
        print(f"prepush_check: {len(problems)} problem(s); push refused")
        return 1
    print("prepush_check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
