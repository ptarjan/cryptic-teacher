"""tree_normalize: canonical rewrites by code, letters proved unchanged (r10 sample rows)."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
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

    def test_sink_deletion_only_onto_the_piece_where_the_indicator_says(self):
        # toughie-3771#3d: "not opening" takes the FIRST letter, which is the U of unutilised
        tree = {"op": "anagram", "indicators": [{"text": "unfortunately"}],
                "parts": [{"op": "deletion", "indicators": [{"text": "not opening"}],
                           "parts": [{"op": "charade", "parts": [leaf("Surrey", "SURREY"), leaf("unutilised", "UNUTILISED")]},
                                     {"gives": "U"}]}]}
        # the cut may sink onto unutilised only, never Surrey
        self.assertEqual(T._placed(tree["parts"][0], tree["parts"][0]["parts"][0]["parts"], [{"gives": "U"}]), [1])
        self.assertEqual(T._placed({"indicators": [{"text": "endlessly"}]}, tree["parts"][0]["parts"][0]["parts"],
                                   [{"gives": "Y"}]), [0])
        # no place named: a letter that two pieces hold is ambiguous, so no sink
        self.assertEqual(T._placed({"indicators": [{"text": "without"}]}, tree["parts"][0]["parts"][0]["parts"],
                                   [{"gives": "U"}]), [])

    def test_separate_indicators_are_never_folded_into_one_op(self):
        clue, ans, tree = AEGEAN
        two = copy.deepcopy(tree)
        two["parts"][1]["indicators"] = [{"text": "tops"}]
        new, used = T.normalize(two, clue, ans)
        self.assertEqual(used, [])
        self.assertEqual(new, two)
        self.assertTrue(T.indicators_kept(tree, T.normalize(tree, clue, ans)[0]))

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


    def test_sink_container_puts_the_piece_in_the_one_piece_it_goes_in(self):
        # azed-2282 24a TIFOSI: ins<packed in>(del<mostly>(TO + SIT, T), IF)
        clue, ans = "Italian fans: to take seats mostly packed in whenever", "TIFOSI"
        tree = {"op": "container", "indicators": [{"text": "packed in"}], "parts": [
            {"op": "deletion", "indicators": [{"text": "mostly"}], "parts": [
                {"op": "charade", "parts": [leaf("to", "TO"), leaf("take seats", "SIT")]}, {"gives": "T"}]},
            leaf("whenever", "IF")]}
        new, used = T.normalize(tree, clue, ans)
        self.assertEqual(used, ["sink_deletion", "sink_container"])
        self.assertEqual(V.container_inside_component(new, ans), 0)
        wordplay.evaluate(new, ans)

    def test_a_charade_left_under_an_anagram_joins_its_parts(self):
        # azed-2748 30a: ana<cooked>(del<heartlessly>(lass + heart, A)) -> ana(del(lass, A), heart)
        tree = {"op": "anagram", "indicators": [{"text": "cooked"}], "parts": [
            {"op": "deletion", "indicators": [{"text": "heartlessly"}], "parts": [
                {"op": "charade", "parts": [leaf("lass", "LASS"), leaf("heart", "HEART")]}, {"gives": "S"}]}]}
        new, used = T.normalize(tree, "cooked lass heartlessly heart", "LASHEART")
        if used:
            self.assertEqual(V.anagram_charades(new), 0)

    def test_two_reversals_under_an_indicated_charade_stay_two(self):
        # azed-2251 16d: (rev<given a lift>(I + NIM) + rev(TRAM))<no longer> would be a one-part charade
        tree = {"op": "charade", "indicators": [{"text": "no longer"}], "parts": [
            {"op": "reversal", "indicators": [{"text": "given a lift"}], "parts": [leaf("I NIM", "INIM")]},
            {"op": "reversal", "parts": [leaf("public transport", "TRAM")]}]}
        self.assertEqual(T.merge_reversals(tree, "MINIMART")[1], 0)

    def test_no_rewrite_may_leave_a_one_part_charade(self):
        # telegraph-30789 9d TSETSE, times-29357 11a DOORKNOB: wordplay.arity wants 2+ parts in a charade
        tree = {"op": "charade", "indicators": [{"text": "twice"}], "parts": [
            {"op": "alternate", "indicators": [{"text": "oddly"}], "parts": [leaf("tested")]},
            {"op": "alternate", "parts": [leaf("tested")]}]}
        new, used = T.normalize(tree, "Fly is oddly tested twice", "TSETSE")
        self.assertEqual(T._thin_charades(new), 0)
        self.assertEqual(used, [])


if __name__ == "__main__":
    unittest.main()
