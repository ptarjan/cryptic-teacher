"""tools/ci_scope.py: which pushes may skip the sharded suite, and how tests.yml wires that in."""
import json
import re
import unittest
from pathlib import Path

import _path  # puts tools/ on sys.path

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

    def test_burn_paths_are_the_same_in_check_and_tests(self):
        raw = (ROOT / ".github/workflows/tests.yml").read_text()
        chk = (ROOT / ".github/workflows/check.yml").read_text()

        def listed(t, key):
            return re.findall(r'^      - "([^"]+)"$', t[t.index(key) :], re.MULTILINE)

        ignored = listed(raw, "paths-ignore:")[:len(listed(chk, "paths:"))]
        self.assertEqual(ignored, listed(chk, "paths:"))
        data = {"puzzles/**/*.json", "puzzles/**/*.blog", *S.validate_scope.ENTRY_TABLES, *S.QUEUE_STATE,
                S.validate_scope.BACKLOG, *S.DERIVED_DATA}
        self.assertEqual(set(ignored), data)

    def test_full_suite_has_no_scope_job_and_one_static_matrix(self):
        self.assertNotIn("needs.scope", self.text)
        for name in ("generated", "test", "cache", "tests-passed"):
            self.job(name)
        self.assertRegex(self.job("test"), r"shard: \[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10\]")

    def test_verdict_job_needs_everything_and_is_red_unless_all_succeeded(self):
        body = self.job("tests-passed")
        needs = re.search(r"needs:\s*\[([^\]]*)\]", body).group(1)
        for j in ("generated", "test", "cache"):
            self.assertIn(j, needs)
        self.assertIn('.result == "success"', body)


if __name__ == "__main__":
    unittest.main()


class PagesPushScope(unittest.TestCase):
    """pages.yml: puzzle-data pushes do not start it; check.yml dispatches it."""

    @staticmethod
    def _ignored(text):
        block = text[text.index("paths-ignore:"):]
        block = block[: block.index("\n  schedule:") if "\n  schedule:" in block else block.index("\n  pull_request:")]
        return re.findall(r'- "([^"]+)"', block)

    def test_pages_and_tests_ignore_the_same_paths_as_check_runs_on(self):
        wf = ROOT / ".github/workflows"
        pages = self._ignored((wf / "pages.yml").read_text(encoding="utf-8"))
        tests = self._ignored((wf / "tests.yml").read_text(encoding="utf-8"))
        check = (wf / "check.yml").read_text(encoding="utf-8")
        check_paths = re.findall(r'- "([^"]+)"', check[check.index("paths:"):check.index("permissions:")])
        self.assertTrue(pages)
        self.assertEqual(pages, tests)
        self.assertEqual(pages, check_paths)

    def test_pages_has_one_workflow_group_and_no_scope_job(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^concurrency:\n  group: pages\n  cancel-in-progress: false$")
        self.assertNotIn("needs.scope", text)
        self.assertNotIn("*/15", text)

    def test_check_dispatches_pages_after_a_green_check(self):
        text = (ROOT / ".github/workflows/check.yml").read_text(encoding="utf-8")
        self.assertIn("gh workflow run pages.yml --ref master", text)
        self.assertIn("needs: check", text)

    def test_code_since_the_deploy_is_full_even_when_the_last_push_is_puzzles(self):
        since_deploy = [("M", "tools/ci_scope.py"), ("M", P)]
        self.assertEqual(verdict(since_deploy), "full")
        self.assertEqual(verdict([("M", P)]), "fast")
