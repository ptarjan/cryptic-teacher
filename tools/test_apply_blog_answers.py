#!/usr/bin/env python3
"""apply_blog_answers reads an answer off a write-up line however the era prints it."""
import apply_blog_answers as a

CASES = [
    ("R.U. for Rugby Union before BY PORT for left = RUBY PORT.  A drink", 8, "RUBYPORT"),
    ("CARD + US for Sir John Frederick Neville Cardus CBE, music critic", 6, "CARDUS"),
    ("E[LE]VEN", 6, "ELEVEN"),
    ("MUZZLE=guard,LOADER=ordeal*", 12, "MUZZLELOADER"),
    ("(hu)T, W.O. = Warrant Officer, HANDED = passed", 9, "TWOHANDED"),
    ("THISTLE, TH(anagram of LIST)E. Fortunately, a well-known plant", 7, "THISTLE"),
    ("Omitted.  Ask if you can't pick it.", 4, None),
]

TABLE = """<table><tr><th colspan="2"><b>Across</b></th></tr>
<tr><td>1</td><td>R.U. = RUBY PORT</td></tr></table>
<table><tr><th colspan="2"><b>Down</b></th></tr>
<tr><td>2</td><td>Omitted.</td></tr></table>"""

BREAKS = ("<p><strong>ACROSS</strong><br />1 <strong>MEALY BUG</strong> *(a blue gym)<br />"
          "9 <strong>ACAPULCO </strong>Cha of A CAP</p><p><strong>DOWN</strong><br />"
          "2 <strong>ENVISAGE </strong>ENVy</p>")


def main():
    for text, length, want in CASES:
        got = a.candidates(text, length)
        assert (got[0] if got else None) == want, (text, got, want)
    assert a.table_lines(TABLE)[0] == ("across", 1, "R.U. = RUBY PORT")
    assert a.table_lines(TABLE)[1][:2] == ("down", 2)
    rows = a.break_lines(BREAKS)
    assert [(d, n) for d, n, _ in rows] == [("across", 1), ("across", 9), ("down", 2)], rows
    assert a.candidates(rows[0][2], 8) == ["MEALYBUG"]
    print("ok   apply_blog_answers reads table and <br> write-ups")

    daily = ("<p><strong>Across<br />\n</strong></p><p>1. Spider (5)<br />\n"
             "{<span style=\"color:#fff;\">WIDOW</span>} &#8211; hint</p>"
             "<p>9a &amp; 21d    Raging hell (6,4)<br />\n{<span>GRANGE HILL</span>} &#8211; anagram</p>"
             "<p><strong>Down</strong></p><p>2d  Typo (9)<br />\n{<span>DISORDERD</span>} &#8211; x</p>")
    assert [r[:3] for r in a.bigdave_rows(daily)] == [("across", 1, "WIDOW"), ("across", 9, "21d|GRANGE HILL"),
                                     ("down", 2, "DISORDERD")], a.bigdave_rows(daily)
    sunday = ("<p><strong>Across</strong></p><p>1a   Warship (10)<br />\n"
              "SUBMISSIVE &#8211; SUB + MISSIVE.</p><p>6a   Presidents (4)<br />\nThe first refers to Bush.</p>"
              "<p>24a   Perform (5,2)<br />\nSTAND-IN &#8211; hidden.</p>")
    assert [r[:3] for r in a.bigdave_rows(sunday)] == [("across", 1, "SUBMISSIVE"), ("across", 6, ""),
                                      ("across", 24, "STAND-IN")], a.bigdave_rows(sunday)
    linked = a.break_lines("<p><strong>Across</strong><br />28,7 <strong>FINGAL</strong> FIN GAL</p>", linked=True)
    assert linked == [("across", 28, "7|FINGAL – FINGAL FIN GAL")], linked
    puzzle = {"entries": [
        {"number": 28, "direction": "across", "length": 3, "position": {"x": 0, "y": 0}},
        {"number": 7, "direction": "across", "length": 3, "position": {"x": 0, "y": 2}}]}
    assert a.blog_fill(puzzle, {"rows": linked})[0] == {"28-across": "FIN", "7-across": "GAL"}
    print("ok   apply_blog_answers reads bigdave44 posts and linked clues")

    grid = {"entries": [
        {"number": 1, "direction": "across", "length": 3, "position": {"x": 0, "y": 0}},
        {"number": 3, "direction": "across", "length": 3, "position": {"x": 0, "y": 2}},
        {"number": 2, "direction": "down", "length": 4, "position": {"x": 1, "y": 0}}]}
    fill = {"1-across": "ABC", "3-across": "DEF"}
    a.prose_fill(grid, fill, {"2-down": "A drink, BREW or tea, no brew on its own"})
    assert fill["2-down"] == "BREW", fill
    # Two words fit the crossings, so the prose does not settle it.
    fill = {"1-across": "ABC", "3-across": "DEF"}
    a.prose_fill(grid, fill, {"2-down": "Either BREW or BLEW"})
    assert "2-down" not in fill, fill
    # One crossing letter is too little for a capitalised word.
    fill = {"1-across": "ABC"}
    a.prose_fill(grid, fill, {"2-down": "A drink, BREW"})
    assert "2-down" not in fill, fill
    print("ok   apply_blog_answers fills a light only from a unique prose word that fits its crossings")

    # "BREWS" typed for the four-letter BREW: dropping the S is the only word that fits.
    fill = {"1-across": "ABC", "3-across": "DEF"}
    a.repair_fill(grid, fill, {"2-down": "BREWS"})
    assert fill["2-down"] == "BREW", fill
    # A typed answer already the right length, or three letters off, is left alone.
    fill = {"1-across": "ABC", "3-across": "DEF"}
    a.repair_fill(grid, fill, {"2-down": "BREWERS"})
    assert "2-down" not in fill, fill
    print("ok   apply_blog_answers mends a misprinted answer only to a unique lexicon word")

    # A light the post leaves out is no disagreement with the file's answer;
    # a different answer for a light the post does give still is.
    real = a.blog_fill
    puz = {"entries": [
        {"number": 1, "direction": "across", "length": 3, "solution": "ABC",
         "position": {"x": 0, "y": 0}},
        {"number": 2, "direction": "down", "length": 3, "solution": "XYZ",
         "position": {"x": 2, "y": 0}}]}
    try:
        a.blog_fill = lambda p, r: ({"2-down": "XYZ"}, [])
        assert not any("disagrees" in x for x in a.judge(puz, {}, True)[1])
        a.blog_fill = lambda p, r: ({"1-across": "ABC", "2-down": "QQQ"}, [])
        assert a.judge(puz, {}, True)[1][0].startswith("disagrees"), a.judge(puz, {}, True)
    finally:
        a.blog_fill = real
    print("ok   apply_blog_answers: a left-out light does not clash with the file")

    # A post whose answers differ from the annotated answers is another puzzle's.
    ann = {"entries": [
        {"number": 1, "direction": "across", "length": 4, "position": {"x": 0, "y": 0},
         "annotation": {"spelling": "ALMS"}},
        {"number": 2, "direction": "down", "length": 6, "position": {"x": 0, "y": 0},
         "annotation": {"wordplay": {"op": "deletion", "gives": "LANCER"}}}]}
    assert "2-down" in a.annotation_clash(ann, {"2-down": "GALUMP"})
    assert a.annotation_clash(ann, {"1-across": "ALMS"}) == ""
    assert a.annotation_clash(ann, {"2-down": "LANCER"}) == ""
    assert "1-across" in a.annotation_clash(ann, {"1-across": "LAMP"})
    real = a.blog_fill
    try:
        a.blog_fill = lambda p, r: ({"1-across": "LAMP"}, [])
        assert a.judge(ann, {}, True)[1][0].startswith("disagrees with the annotated"), a.judge(ann, {}, True)
    finally:
        a.blog_fill = real
    print("ok   apply_blog_answers refuses a post that contradicts the annotated answers")


if __name__ == "__main__":
    main()
