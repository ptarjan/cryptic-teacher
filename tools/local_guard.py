#!/usr/bin/env python3
"""PreToolUse hook for Bash: refuse heavy work on the home server.

Paul: "We shouldn't do much on this box." Test suites, the smoke test, whole-
corpus scans and full runs of the corpus jobs steal CPU from the quota burn,
and every one of them already runs in GitHub Actions (tests.yml, or a
workflow_dispatch). An agent that reaches for them locally gets a refusal
that says so, rather than a memory of a rule it has since forgotten.

Wired in .claude/settings.json (matcher "Bash"). Claude Code feeds the hook
JSON on stdin ({"tool_name": "Bash", "tool_input": {"command": ...}, ...});
a refusal is printed as a PreToolUse permissionDecision "deny" and exit 0.
Anything else (allowed, or input it cannot read) prints nothing and exits 0:
a guard that wedges every Bash call on a parse error is worse than a leak.

Only agent tool calls pass through a hook. The scheduled jobs (LaunchAgents,
tools/*.sh run from cron) never do, so they are not touched by this file.

What is refused (see `verdict`):
  - pytest, python -m pytest / unittest
  - node tools/smoke_test*.js, any tools/test_* or tests/test_* file, run by
    node, python or bash
  - the corpus jobs below, and the whole-corpus form of the checkers that
    take a file list (no file argument = the whole corpus)
  - python that loops over every puzzles/**/*.json (-c, heredoc or stdin)
What stays allowed: node --check, ruff, git, gh, reads, tools/prereset_*,
track-job.sh and wake.sh (track-job.sh --run is looked through: what it
wraps is judged like any other command).
"""
import json
import os
import re
import shlex
import sys

REASON = ("Paul: run it in CI, not on this box - push and let tests.yml (or a "
          "workflow_dispatch) do it. Blocked by tools/local_guard.py: %s")

# Scripts that are heavy however they are called (--help is always fine).
HEAVY = {
    "blog_facts.py", "difficulty_check.py", "snitch_report.py",
    "requeue_drift.py", "coverage.py", "coverage_report.py", "coverage.sh",
    "archive_coverage.py", "smoke_test.js", "build_seo_pages.py",
    "build_clue_joints.py", "build_fill_floors.py", "code_checks.py",
    "ci_shards.js", "check_shapes.js",
}
# Heavy only with no file argument (the whole corpus); with files they are
# the pre-commit hooks' per-file form and cheap.
HEAVY_UNSCOPED = {"validate_annotations.py", "puzzle_integrity.py",
                  "puzzle_schema.py"}
# Wrappers to see through to the command they run.
WRAPPERS = {"env", "time", "nohup", "setsid", "sudo", "nice", "ionice",
            "command", "exec", "stdbuf", "xargs"}
ALLOWED_PROGRAMS = {"git", "gh", "wake.sh", "track-job.sh"}
SHELLS = {"bash", "sh", "zsh"}
PYTHONS = re.compile(r"^python[\d.]*$")
PUZZLE_SCAN = re.compile(
    r"(puzzles/\*\*|rglob\(|os\.walk\(|glob\.(?:i?glob)\()", re.IGNORECASE)
PUZZLE_WORD = re.compile(r"puzzles", re.IGNORECASE)
JSON_WORD = re.compile(r"\.json|\*\*", re.IGNORECASE)
SPLIT = re.compile(r"\|\||&&|[;|\n&]")


def _tokens(seg):
    try:
        return shlex.split(seg, comments=False, posix=True)
    except ValueError:
        return seg.split()


def _strip(argv):
    """Drop env assignments and wrapper words; return argv starting at the program."""
    i = 0
    while i < len(argv):
        w = argv[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w) or w in WRAPPERS:
            i += 1
        elif w == "timeout":
            i += 2 if i + 1 < len(argv) else 1
        elif w.startswith("-") and i and argv[i - 1] in WRAPPERS:
            i += 1
        else:
            break
    return argv[i:]


def _script_hits(base, path):
    return base in HEAVY or any(
        re.search(p, path) for p in (r"(^|/)tools/smoke_test[^/]*\.js$",
                                     r"(^|/)tools/test_[^/]*$",
                                     r"(^|/)tests/test_[^/]*$",
                                     r"(^|/)tools/[^/]*_test\.(sh|js|py)$"))


def _argv_verdict(argv, depth):
    argv = _strip(argv)
    if not argv:
        return None
    prog = os.path.basename(argv[0])
    rest = argv[1:]
    if prog in ALLOWED_PROGRAMS or prog.startswith("prereset_"):
        if prog == "track-job.sh" and "--" in rest:
            return _command_verdict(" ".join(shlex.quote(a) for a in rest[rest.index("--") + 1:]), depth + 1)
        return None
    if prog in ("ruff", "ls", "cat", "head", "tail", "grep", "rg", "sed", "wc"):
        return None
    if prog in ("pytest", "py.test"):
        return "pytest"
    if prog in SHELLS and "-c" in rest[:3]:
        i = rest.index("-c")
        if i + 1 < len(rest):
            return _command_verdict(rest[i + 1], depth + 1)
    is_py = bool(PYTHONS.match(prog))
    if is_py and "-m" in rest:
        mod = rest[rest.index("-m") + 1:][:1]
        if mod and mod[0].split(".")[0] in ("pytest", "unittest"):
            return f"python -m {mod[0]}"
    helpish = any(a in ("-h", "--help") for a in rest)
    if prog == "node" and "--check" in rest[:2] or prog == "node" and "-c" in rest[:1]:
        return None
    if prog in SHELLS or is_py or prog in ("node", "uv", "poetry"):
        script = next((a for a in rest if not a.startswith("-")
                       and re.search(r"\.(py|js|sh)$", a)), None)
        if script and not helpish:
            base = os.path.basename(script)
            if _script_hits(base, script):
                return f"{prog} {script}"
            if base in HEAVY_UNSCOPED:
                files = [a for a in rest[rest.index(script) + 1:]
                         if not a.startswith("-")]
                if not files:
                    return f"{base} over the whole corpus (give it files, or use CI)"
        if script and os.path.basename(script) == "difficulty.py" and "--validate" in rest:
            return "difficulty.py --validate"
    elif prog.endswith((".sh", ".py", ".js")) and not helpish:
        base = os.path.basename(prog)
        if _script_hits(base, prog):
            return prog
    return None


def _command_verdict(cmd, depth=0):
    if depth > 4:
        return None
    first = _strip(_tokens(cmd.lstrip()))[:1]
    first = os.path.basename(first[0]) if first else ""
    if first in ALLOWED_PROGRAMS and "<<" in cmd:
        cmd = cmd.split("\n", 1)[0]  # a commit message body is prose, not commands
    # A python that scans every puzzle: inline (-c), heredoc or stdin.
    if (first not in ALLOWED_PROGRAMS and PUZZLE_SCAN.search(cmd)
            and PUZZLE_WORD.search(cmd) and JSON_WORD.search(cmd)
            and re.search(r"python[\d.]*\s+(-\w*c\b|-\s|-$)|python[\d.]*.*<<", cmd)):
        return "python scanning every puzzles/**/*.json"
    # $(...) and backticks run too: judge their bodies as commands.
    for sub in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", cmd):
        for body in sub:
            if body:
                v = _command_verdict(body, depth + 1)
                if v:
                    return v
    for seg in SPLIT.split(cmd):
        seg = seg.strip().lstrip("({ ").strip()
        if not seg:
            continue
        v = _argv_verdict(_tokens(seg), depth)
        if v:
            return v
    return None


def verdict(command):
    """Why `command` must not run here, or None if it may."""
    return _command_verdict(command or "")


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    why = verdict((data.get("tool_input") or {}).get("command", ""))
    if why:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON % why}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
