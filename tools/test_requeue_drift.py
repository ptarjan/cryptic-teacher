"""tools/requeue_drift.py: a puzzle past its allowance gets its flagged clues queued once."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requeue_drift as R


class RequeueDrift(unittest.TestCase):
    def test_fields_map_to_the_redo_gate_rule_names(self):
        f = R.rule_fields()
        self.assertEqual(f["wordplay.anagramSynonym"], "anaSynonym")
        self.assertEqual(f["wordplay.misplacedIndicator"], "misplacedIndicator")
        self.assertNotIn("wordplay.unchecked", f)
        self.assertNotIn("indicators.note", f)

    def test_drift_is_only_puzzles_past_their_allowance(self):
        surveyed = [("a-1", {"wordplay.wrongRole": ["1a", "2d"]}, False),
                    ("a-2", {"wordplay.wrongRole": ["3a"]}, False),
                    ("a-3", {"wordplay.wrongRole": ["4a"]}, False)]
        allowed = {"wordplay.wrongRole": {"a-1": 1, "a-2": 1}}
        self.assertEqual(R.drift(surveyed, allowed, ["wordplay.wrongRole"]),
                         {"wordplay.wrongRole": {"a-1": ["1a", "2d"], "a-3": ["4a"]}})

    def test_all_queues_every_hit_of_a_grandfathered_field(self):
        surveyed = [("a-1", {"wordplay.halfLeaf": ["1a"], "wordplay.wrongRole": ["1a"]}, False),
                    ("a-2", {"wordplay.halfLeaf": []}, False)]
        allowed = {"wordplay.halfLeaf": {"a-1": 1}, "wordplay.wrongRole": {"a-1": 1}}
        fields = ["wordplay.halfLeaf", "wordplay.wrongRole"]
        self.assertEqual(R.drift(surveyed, allowed, fields), {"wordplay.halfLeaf": {}, "wordplay.wrongRole": {}})
        self.assertEqual(R.drift(surveyed, allowed, fields, ["wordplay.halfLeaf"]),
                         {"wordplay.halfLeaf": {"a-1": ["1a"]}, "wordplay.wrongRole": {}})

    def test_requeue_lists_a_clue_once_and_extends_a_row_that_misses_the_rule(self):
        fields = {"wordplay.wrongRole": "wrongRole"}
        over = {"wordplay.wrongRole": {"a-1": ["1a", "2d", "3a"]}}
        rows = [{"id": "a-1#1a", "reason": "wrongRole: x"}, {"id": "a-1#2d", "reason": "del_single: y"}]
        out, added = R.requeue(over, fields, rows)
        self.assertEqual(added, 2)
        self.assertEqual([r["id"] for r in out], ["a-1#1a", "a-1#2d", "a-1#3a"])
        self.assertTrue(out[1]["reason"].startswith("del_single: y; wrongRole: "))
        again, added = R.requeue(over, fields, out)
        self.assertEqual(added, 0)


class Publish(unittest.TestCase):
    """The deploy's step: the shards' drift files become one commit on origin/master."""

    def test_flagged_clues_lists_each_clue_once_in_lower_case(self):
        w = [f"22A: z {R.V.NO_INDICATOR}", f"22A: y {R.V.NO_INDICATOR}", "3d: other"]
        self.assertEqual(R.V.flagged_clues(w, ["wordplay.noIndicator", "features"]),
                         {"wordplay.noIndicator": ["22a"], "features": []})

    def test_raised_backlog_sets_the_count_and_keeps_the_order(self):
        text = json.dumps({"_why": "w", "wordplay.wrongRole": {"a-2": 1}})
        out = json.loads(R.raised_backlog(text, {"wordplay.wrongRole": {"a-1": ["1a", "2d"], "a-2": ["1a"]}}))
        self.assertEqual(list(out["wordplay.wrongRole"].items()), [("a-1", 2), ("a-2", 1)])

    def test_store_backlog_writes_the_stored_layout(self):
        """Every backlog writer (shrink, fill_spellings, clear_unchecked, ...) goes
        through V.store_backlog; a layout the clean filter would change shows up
        as a code edit in the pre-reset backfill."""
        import json_merge
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"
            R.V.store_backlog({"_why": "w", "wordplay.x": {"a-1": 2, "a-2": 1}}, p)
            text = p.read_text()
        self.assertEqual(json_merge.clean(text), text)
        self.assertEqual(len(text.splitlines()), 4)

    def test_raised_backlog_is_the_json_keys_clean_layout(self):
        import json_merge
        out = R.raised_backlog(json.dumps({"_why": "w", "wordplay.wrongRole": {"a-2": 1}}), {"wordplay.wrongRole": {"a-1": ["1a"]}})
        self.assertEqual(json_merge.clean(out), out)
        self.assertEqual(len(out.splitlines()), 4)

    def test_merged_drift_joins_the_shards_and_drops_empty_fields(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for i, body in enumerate(({"f": {"a-1": ["1a"]}, "g": {}}, {"f": {"a-2": ["2d"]}})):
                Path(d, f"drift.{i}.json").write_text(json.dumps(body))
            got = R.merged_drift([str(Path(d, f"drift.{i}.json")) for i in range(2)])
        self.assertEqual(got, {"f": {"a-1": ["1a"], "a-2": ["2d"]}})

    def test_publish_builds_on_the_tip_and_survives_a_lost_race(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            def git(*a, cwd=d):
                return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                      check=True, capture_output=True, text=True).stdout
            origin, mine, other = (os.path.join(d, n) for n in ("origin.git", "mine", "other"))
            git("init", "-q", "--bare", "-b", "master", origin)
            git("clone", "-q", origin, mine)
            os.makedirs(os.path.join(mine, "tools/data"))
            Path(mine, R.QUEUE_FILE).write_text("[\n]\n")
            Path(mine, R.BACKLOG_FILE).write_text(json.dumps({"_why": "w", "wordplay.wrongRole": {}}) + "\n")
            git("add", "-A", cwd=mine)
            git("commit", "-q", "-m", "base", cwd=mine)
            git("push", "-q", "origin", "HEAD:master", cwd=mine)
            git("clone", "-q", origin, other)
            over = {"wordplay.wrongRole": {"a-1": ["1a"]}}
            fields = {"wordplay.wrongRole": "wrongRole"}
            tries = []

            def sleep(_):
                tries.append(1)

            # The burn pushes between the fetch and the push once: the first try loses.
            real = R._git

            def racing(*a, **kw):
                if a[:1] == ("push",) and not tries:
                    Path(other, "x").write_text("burn")
                    git("add", "-A", cwd=other)
                    git("commit", "-q", "-m", "burn", cwd=other)
                    git("push", "-q", "origin", "HEAD:master", cwd=other)
                return real(*a, **kw)

            R._git = racing
            cwd = os.getcwd()
            os.chdir(mine)
            try:
                self.assertEqual(R.publish(over, fields, sleep=sleep), 0)
                self.assertEqual(R.publish(over, fields, sleep=sleep), 0)  # already there: nothing to push
            finally:
                os.chdir(cwd)
                R._git = real
            self.assertEqual(len(tries), 1)
            log = git("log", "--format=%s", "master", cwd=origin).splitlines()
            self.assertEqual(len(log), 3)
            self.assertIn("a-1#1a", git("show", f"master:{R.QUEUE_FILE}", cwd=origin))
            self.assertEqual(json.loads(git("show", f"master:{R.BACKLOG_FILE}", cwd=origin))["wordplay.wrongRole"],
                             {"a-1": 1})
            self.assertEqual(git("show", "master:x", cwd=origin), "burn")


if __name__ == "__main__":
    unittest.main()
