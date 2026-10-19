"""tree_normalize: canonical rewrites by code, letters proved unchanged (r10 sample rows)."""
import copy
import unittest

import clue_shapes as cs
import tree_normalize as T
import wordplay
import validate_annotations as V


def leaf(words, gives=None):
    return {"words": words, **({"gives": gives} if gives else {})}


SOLO = ("How one flies extremely close to ground, mostly", "SOLO",
        {"op": "deletion", "indicators": [{"text": "mostly"}],
         "parts": [{"op": "charade", "parts": [leaf("extremely", "SO"), leaf("close to ground", "LOW")]},
                   {"gives": "W"}]})
JALAPENO = ("German agreed with a single friend over something seedy and hot", "JALAPENO",
            {"op": "charade", "parts": [
                leaf("German agreed", "JA"),
                {"op": "reversal", "indicators": [{"text": "over"}], "parts": [leaf("friend", "PAL")]},
                {"op": "reversal", "parts": [leaf("a single", "ONE")]}]})
AEGEAN = ("Like an ancient civilisation on fringes of Argive Greece, Anatolian?", "AEGEAN",
          {"op": "charade", "parts": [
              {"op": "outer", "indicators": [{"text": "fringes of"}], "parts": [leaf("Argive")]},
              {"op": "outer", "parts": [leaf("Greece")]},
              {"op": "outer", "parts": [leaf("Anatolian")]}]})


class TreeNormalize(unittest.TestCase):
    def test_sink_deletion_moves_the_cut_onto_the_piece(self):
        clue, ans, tree = SOLO
        self.assertEqual(V.deletion_inside_component(tree, clue, ans), 1)
        new, used = T.normalize(tree, clue, ans)
        self.assertEqual(used, ["sink_deletion"])
        self.assertEqual(cs.compact(new), "([extremely]SO + del<mostly>([close to ground]LOW, W))")
        self.assertEqual(V.deletion_inside_component(new, clue, ans), 0)
        wordplay.evaluate(new, ans)

    def test_hoist_is_the_reverse(self):
        clue, ans, tree = SOLO
        new, _ = T.normalize(tree, clue, ans)
        back, n = T.hoist_deletion(copy.deepcopy(new), ans)
        self.assertEqual(n, 1)
        self.assertEqual(back, tree)

    def test_selections_under_one_indicator_become_one_op(self):
        clue, ans, tree = AEGEAN
        new, used = T.normalize(tree, clue, ans)
        self.assertEqual(used, ["merge_selects"])
        self.assertEqual(cs.compact(new), "outer<fringes of>([Argive], [Greece], [Anatolian])")
        wordplay.evaluate(new, ans)

    def test_adjacent_reversals_become_one_over_a_charade_in_clue_order(self):
        clue, ans, tree = JALAPENO
        new, used = T.normalize(tree, clue, ans)
        self.assertEqual(used, ["merge_reversals"])
        self.assertEqual(cs.compact(new), "([German agreed]JA + rev<over>(([a single]ONE + [friend]PAL)))")
        wordplay.evaluate(new, ans)

    def test_sink_deletion_keeps_the_charades_own_indicator(self):
        clue, ans, _ = SOLO
        tree = {"op": "deletion", "indicators": [{"text": "mostly"}],
                "parts": [{"op": "charade", "indicators": [{"text": "after"}],
                           "parts": [leaf("extremely", "SO"), leaf("close to ground", "LOW")]},
                          {"gives": "W"}]}
        new, used = T.normalize(tree, clue, ans)
        self.assertEqual(used, ["sink_deletion"])
        self.assertEqual(new["op"], "charade")
        self.assertEqual(new["indicators"], [{"text": "after"}])
        wordplay.evaluate(new, ans)

    def test_simplicity_key_prefers_fewer_ops_then_fewer_letters(self):
        clue, ans, tree = SOLO
        new, _ = T.normalize(tree, clue, ans)
        self.assertLess(T.simplicity(new), T.simplicity(tree))
        clue, ans, tree = JALAPENO
        new, _ = T.normalize(tree, clue, ans)
        self.assertLess(T.simplicity(new), T.simplicity(tree))

    def test_a_tree_whose_letters_fail_is_left_to_the_model(self):
        clue, _, tree = SOLO
        self.assertEqual(T.normalize(tree, clue, "SOLA")[1], [])


if __name__ == "__main__":
    unittest.main()
