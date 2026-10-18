"""tools/requeue_drift.py: a puzzle past its allowance gets its flagged clues queued once."""
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


if __name__ == "__main__":
    unittest.main()
