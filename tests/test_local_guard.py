#!/usr/bin/env python3
"""tools/local_guard.py refuses heavy commands and lets the light ones by."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import local_guard

DENY = [
    "pytest", "pytest -q tests/", "python3 -m pytest --version",
    "python -m unittest discover", "cd x && python3 -m pytest",
    "node tools/smoke_test.js", "CT_FULL=1 node tools/smoke_test_extra.js",
    "node tests/test_anagram_line.js", "python3 tests/test_alteration.py",
    "python3 tools/test_foo.py", "bash tests/test_alert_claimed.sh",
    "python3 tools/blog_facts.py --measure", "python3 tools/blog_facts.py",
    "python3 tools/validate_annotations.py", "python3 tools/puzzle_integrity.py --quiet",
    "python3 tools/difficulty.py --validate", "python3 tools/requeue_drift.py --write",
    "python3 tools/coverage_report.py", "bash tools/coverage.sh",
    "git log | pytest", "echo hi; pytest", "timeout 60 pytest", "env A=1 nohup pytest",
    "bash -c 'python3 -m pytest'", "echo $(python3 -m pytest)",
    "track-job.sh ch --run lbl -- python3 -m pytest",
    "python3 -c \"import glob; [open(f) for f in glob.glob('puzzles/**/*.json', recursive=True)]\"",
    "python3 - <<'EOF'\nfrom pathlib import Path\nfor p in Path('puzzles').rglob('*.json'):\n pass\nEOF",
]
ALLOW = [
    "", "ls", "git status", "git commit -m 'run pytest in CI'",
    "git commit -F - <<'EOF'\nfix\npytest\nEOF",
    "gh run list", "node --check tools/smoke_test.js", "ruff check tools/x.py",
    "python3 tools/validate_annotations.py puzzles/times/times-1.json",
    "python3 tools/blog_facts.py --help", "grep -n pytest tools/x.py",
    "tools/prereset_backfill.sh", "bash tools/prereset_watch.sh",
    "track-job.sh ch --run lbl -- sleep 5", "wake.sh -q room",
    "cat puzzles/times/times-1.json | head", "python3 tools/ci_scope.py decide x",
]


class Guard(unittest.TestCase):
    def test_denied(self):
        for c in DENY:
            self.assertTrue(local_guard.verdict(c), c)

    def test_allowed(self):
        for c in ALLOW:
            self.assertIsNone(local_guard.verdict(c), c)

    def run_hook(self, payload):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "local_guard.py")],
                           input=payload, capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0)
        return r.stdout

    def test_hook_protocol(self):
        out = json.loads(self.run_hook(json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "pytest"}})))
        h = out["hookSpecificOutput"]
        self.assertEqual(h["permissionDecision"], "deny")
        self.assertIn("run it in CI", h["permissionDecisionReason"])
        self.assertEqual(self.run_hook(json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git status"}})), "")
        self.assertEqual(self.run_hook("not json"), "")
        self.assertEqual(self.run_hook(json.dumps(
            {"tool_name": "Read", "tool_input": {"command": "pytest"}})), "")

    def test_settings_wires_the_hook(self):
        with open(os.path.join(ROOT, ".claude", "settings.json")) as f:
            s = json.load(f)
        pre = s["hooks"]["PreToolUse"]
        self.assertTrue(any(e["matcher"] == "Bash" and "tools/local_guard.py" in
                            e["hooks"][0]["command"] for e in pre))


if __name__ == "__main__":
    unittest.main()
