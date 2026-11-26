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

    def test_site_skips_only_what_the_build_never_reads(self):
        for path in ("tests/test_burn_log.py", "docs/APP.md", ".github/workflows/tests.yml",
                     "tools/data/deploy_budgets.json"):
            self.assertEqual(S.decide([("M", P), ("M", path)], site=True)[0], "fast", path)
            self.assertEqual(verdict([("M", P), ("M", path)]), "full", path)
        for path in (".github/workflows/pages.yml", ".github/actions/setup/action.yml", "app.js",
                     "tools/build_seo_pages.py", "README.md"):
            self.assertEqual(S.decide([("M", P), ("M", path)], site=True)[0], "full", path)
        self.assertEqual(S.decide([("D", P), ("M", "tests/x.py")], site=True)[0], "full")

    def test_code_ok_names_tools_modules_and_nothing_else(self):
        code = lambda changes: S.decide(changes, site=True, code_ok=True)
        self.assertEqual(code([("M", P), ("M", "tools/fix_shape_notes.py")]), ("code", "tools/fix_shape_notes.py"))
        self.assertEqual(code([("M", P), ("A", "tools/new.py"), ("M", "tests/x.py")])[0], "code")
        self.assertEqual(code([("M", P)])[0], "fast")
        # Any file under tools/ is code: the stores' own keys say whether it moved them.
        for path in ("tools/data/other.json", "tools/sub/x.py", "tools/data/blog_answers.json"):
            self.assertEqual(code([("M", P), ("M", path)]), ("code", path), path)
        self.assertEqual(code([("M", P), ("D", "tools/data/keys.json")]), ("code", "tools/data/keys.json"))
        # Other workflows are inert for the site; pages.yml and the actions are not.
        self.assertEqual(code([("M", P), ("M", ".github/workflows/daily-units.yml")])[0], "fast")
        self.assertEqual(S.decide([("M", P), ("M", ".github/workflows/daily-units.yml")], site=True)[0], "fast")
        self.assertEqual(verdict([("M", P), ("M", ".github/workflows/daily-units.yml")]), "full")
        self.assertEqual(code([("M", P), ("M", ".github/actions/setup/action.yml")])[0], "full")
        for path in ("README.md", "puzzles/times/index.json", ".gitignore"):
            self.assertEqual(code([("M", P), ("M", path)])[0], "full", path)
        self.assertEqual(code([("D", P), ("M", "tools/x.py")])[0], "full")
        for path in ("style.css", "app-core.js", "index.html", "sync/merge.js", "tools/make_og.sh", ".github/workflows/pages.yml"):
            self.assertEqual(code([("M", P), ("M", path)]), ("code", path), path)
        # Without it a module is full, as before.
        self.assertEqual(S.decide([("M", P), ("M", "tools/x.py")], site=True)[0], "full")

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
        table = "tools/data/blog_disagree/times-07.json"
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

    def test_more_puzzles_than_the_fast_path_checks_is_full(self):
        many = [("M", f"puzzles/times/1954/times-{n}.json") for n in range(S.MAX_FILES + 1)]
        self.assertEqual(S.decide(many)[0], "full")
        self.assertEqual(S.decide(many[:-1])[0], "fast")


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
        data = {"puzzles/**/*.json", "puzzles/**/*.blog", *S.validate_scope.ENTRY_TABLES, *S.validate_scope.ENTRY_SHARD_GLOBS, *S.QUEUE_STATE,
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


class PagesPushScope(unittest.TestCase):
    """pages.yml starts on every push; tests.yml skips the burn paths check.yml runs on."""

    WF = ROOT / ".github/workflows"

    def test_tests_ignore_the_paths_check_runs_on(self):
        tests = (self.WF / "tests.yml").read_text(encoding="utf-8")
        block = tests[tests.index("paths-ignore:"):]
        block = block[: block.index("\n  pull_request:")]
        check = (self.WF / "check.yml").read_text(encoding="utf-8")
        check_paths = re.findall(r'- "([^"]+)"', check[check.index("paths:"):check.index("permissions:")])
        self.assertTrue(check_paths)
        self.assertEqual(re.findall(r'- "([^"]+)"', block), check_paths)

    def test_pages_starts_on_every_push_and_nothing_dispatches_it(self):
        pages = (self.WF / "pages.yml").read_text(encoding="utf-8")
        trigger = pages[pages.index("\non:\n"):pages.index("\n  schedule:")]
        self.assertNotIn("paths", trigger)
        check = (self.WF / "check.yml").read_text(encoding="utf-8")
        self.assertNotIn("workflow run pages.yml", check)

    def test_pages_jobs_fold_in_their_own_groups(self):
        pages = (self.WF / "pages.yml").read_text(encoding="utf-8")
        for group in ("pages", "pages-deploy", "pages-check"):
            self.assertRegex(pages, rf"(?m)^    concurrency:\n      group: {group}\n      cancel-in-progress: false$")
        self.assertNotIn("needs.scope", pages)
        self.assertNotIn("*/15", pages)

    def test_code_since_the_deploy_is_full_even_when_the_last_push_is_puzzles(self):
        since_deploy = [("M", "tools/ci_scope.py"), ("M", P)]
        self.assertEqual(verdict(since_deploy), "full")
        self.assertEqual(verdict([("M", P)]), "fast")


if __name__ == "__main__":
    unittest.main()
