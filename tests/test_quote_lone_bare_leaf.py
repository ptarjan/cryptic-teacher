"""A lone bare letter piece with one spare clue word is quoted on that word."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import wordplay as W


def tree():
    return {"op": "charade", "parts": [{"words": "cat", "at": 0, "gives": "CAT"}, {"gives": "S"}]}


def test_lone_spare_word_is_quoted():
    t = tree()
    W._quote_lone_bare_leaf(t, "cat sixth", ())
    assert t["parts"][1]["words"] == "sixth" and t["parts"][1]["at"] == 4


def test_link_word_or_two_spares_stay_bare():
    for clue in ("cat and", "cat six more"):
        t = tree()
        W._quote_lone_bare_leaf(t, clue, ())
        assert "words" not in t["parts"][1]


def test_letters_a_deletion_names_stay_bare():
    # the 10-29 audit's 'missing blocks.note': H of del<Cut>([ready]CASH, H) was bound to the spare 'then'
    for op in ("deletion", "substitution", "move"):
        t = {"op": op, "parts": [{"words": "ready", "at": 4, "gives": "CASH"}, {"gives": "H"}]}
        W._quote_lone_bare_leaf(t, "Cut ready then", ())
        assert "words" not in t["parts"][1], op


if __name__ == "__main__":
    test_lone_spare_word_is_quoted(); test_link_word_or_two_spares_stay_bare(); test_letters_a_deletion_names_stay_bare(); print("ok")
