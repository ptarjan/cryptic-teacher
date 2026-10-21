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


if __name__ == "__main__":
    main()
