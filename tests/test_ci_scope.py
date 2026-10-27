"""tools/ci_scope.py: which pushes may skip the sharded suite, and how tests.yml wires that in."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import ci_scope as S

ROOT = Path(__file__).resolve().parent.parent
P = "puzzles/times/1954/times-7619.json"
BACKLOG = "tools/annotation_backlog.json"


def verdict(changes, old=None, new=None):
    return S.decide(changes, (lambda p: old), (lambda p: new))[0]


class Decide(unittest.TestCase):
    def test_puzzle_data_alone_is_fast(self):
        self.assertEqual(verdict([("A", P), ("M", "puzzles/cryptic/2020/cryptic-1.json")]), "fast")
        self.assertEqual(verdict([("M", "tools/data/shape_reannotate.json"), ("M", P)]), "fast")

    def test_anything_else_is_full(self):
        for path in ("tools/smoke_test.js", "app.js", ".github/workflows/tests.yml", "README.md",
                     "clues_only/book/x.json", "tools/data/other.json", "puzzles/times/index.json",
                     "puzzles/times/1954/times-7619.js"):
            self.assertEqual(verdict([("M", P), ("M", path)]), "full", path)

    def test_a_puzzle_deleted_or_renamed_is_full(self):
        self.assertEqual(verdict([("D", P)]), "full")
        self.assertEqual(verdict([("R", P)]), "full")

    def test_backlog_only_when_it_tightens_a_changed_puzzle(self):
        old = json.dumps({"a": {"times-7619": 3, "x-1": 1}})
        tighter = json.dumps({"a": {"times-7619": 2, "x-1": 1}})
        self.assertEqual(verdict([("M", P), ("M", BACKLOG)], old, tighter), "fast")
        self.assertEqual(verdict([("M", BACKLOG)], old, tighter), "full")  # nobody re-checked it
        raised = json.dumps({"a": {"times-7619": 4, "x-1": 1}})
        self.assertEqual(verdict([("M", P), ("M", BACKLOG)], old, raised), "full")
        self.assertEqual(verdict([("M", P), ("M", BACKLOG)], old, "not json"), "full")
        self.assertEqual(verdict([("M", P), ("A", BACKLOG)], old, tighter), "full")

    def test_entry_table_rows_only_for_a_changed_puzzle_and_never_removed(self):
        table = "tools/data/blog_disagree.json"
        old = json.dumps({"times-7619/1-across": ["type", "x"], "x-1/2-down": ["type", "y"]})
        added = json.dumps({"times-7619/1-across": ["type", "x"], "x-1/2-down": ["type", "y"], "times-7619/3-down": ["definition", "z"]})
        self.assertEqual(verdict([("M", P), ("M", table)], old, added), "fast")
        self.assertEqual(verdict([("M", table)], old, added), "full")  # nobody re-checked times-7619
        dropped = json.dumps({"times-7619/1-across": ["type", "x"]})
        self.assertEqual(verdict([("M", P), ("M", table)], old, dropped), "full")
        self.assertEqual(verdict([("M", P), ("M", table)], old, "not json"), "full")

    def test_files_lists_only_added_and_modified_puzzles(self):
        got = S.puzzle_files([("A", P), ("M", "tools/x.py"), ("D", "puzzles/a/1/a-1.json"), ("M", "puzzles/a/1/a-2.json")])
        self.assertEqual(got, ["puzzles/a/1/a-2.json", P])


class Wiring(unittest.TestCase):
    """The workflow and the smoke cache agree with this module."""

    def setUp(self):
        self.text = "\n".join(l for l in (ROOT / ".github/workflows/tests.yml").read_text().splitlines()
                              if not l.lstrip().startswith("#"))

    def job(self, name):
        m = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", self.text, re.M | re.S)
        self.assertTrue(m, f"tests.yml has a {name} job")
        return m.group(1)

    def test_queue_state_is_inert_for_the_smoke_cache(self):
        js = (ROOT / "tools/ci_cache.js").read_text()
        m = re.search(r"const INERT = \[([^\]]*)\]", js)
        self.assertEqual(tuple(re.findall(r'"([^"]+)"', m.group(1))), S.QUEUE_STATE)

    def test_full_suite_jobs_run_only_when_scope_says_full(self):
        for name in ("generated", "test", "cache"):
            body = self.job(name)
            self.assertIn("needs.scope.outputs.mode == 'full'", body, name)
            self.assertIn("scope", re.search(r"needs:.*", body).group(0), name)

    def test_fast_job_runs_on_fast_only_and_checks_the_changed_ids(self):
        body = self.job("fast")
        self.assertIn("needs.scope.outputs.mode == 'fast'", body)
        for tool in ("tools/puzzle_schema.py", "tools/puzzle_integrity.py", "tools/validate_annotations.py --deploy"):
            self.assertIn(tool, body)
        self.assertIn("tools/ci_scope.py files", body)

    def test_scope_defaults_to_full_and_pull_requests_are_always_full(self):
        body = self.job("scope")
        self.assertIn('[ "$EVENT" = push ] && [ "$REF" = refs/heads/master ]', body)
        self.assertIn("mode=full", body)

    def test_verdict_job_needs_everything_and_accepts_a_skipped_branch_only_via_scope(self):
        body = self.job("tests-passed")
        needs = re.search(r"needs:\s*\[([^\]]*)\]", body).group(1)
        for j in ("scope", "fast", "generated", "test", "cache"):
            self.assertIn(j, needs)
        self.assertIn("SCOPE", body)


if __name__ == "__main__":
    unittest.main()


class PagesPushScope(unittest.TestCase):
    """pages.yml: a puzzle-only push still builds while earlier code is undeployed."""

    def test_push_scope_also_diffs_against_the_live_deploy(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        push = text[text.index('[ "$EVENT" = push ] || yes'):text.index("validate only, the scheduled tick")]
        self.assertIn('tools/last_deploy.py "$REPO"', push)
        self.assertIn('tools/ci_scope.py decide "$live"', push)
        self.assertIn('yes "code not deployed since', push)
        self.assertIn('"build" and .status == "in_progress"', push)

    def test_code_since_the_deploy_is_full_even_when_the_last_push_is_puzzles(self):
        since_deploy = [("M", "tools/ci_scope.py"), ("M", P)]
        self.assertEqual(verdict(since_deploy), "full")
        self.assertEqual(verdict([("M", P)]), "fast")
