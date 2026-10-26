"""Does a CtC video title's date pin its puzzle when the year is short or absent?

    python3 tests/test_ctc_title_date.py

"24 Jan 18" is 2018; "21st December" with no year is the latest such date not
after the day after the video's publish date; with no publish date it names no
date.
"""
import sys

from ctc_transcripts import title_facts

CASES = [
    ('"Speed" solving The Times crossword: 24 Jan 18', None, ("times", "2018-01-24", None)),
    ("Solving the Times Crossword on 15th December", "2017-12-16", ("times", "2017-12-15", None)),
    ("Solving the Times Crossword on 22 September", "2017-09-23", ("times", "2017-09-22", None)),
    ("Solving the Times Crossword on 22 September", None, ("times", None, None)),
    ("Solving The Times crossword on 1 Dec 2017", None, ("times", "2017-12-01", None)),
    ("Working through the Quick Cryptic crossword from The Times on 18 Oct 2017", None,
     ("timesquick", "2017-10-18", None)),
    ("Times Crossword 27,089", None, ("times", None, 27089)),
    ("Deb (& Mark) solve the Times crossword 21st December", "2017-12-22", ("times", "2017-12-21", None)),
    ("Solving the Listener no 4,468", "2017-10-06", (None, None, 4468)),
    ("Solving the Guardian crossword on 28th December", "2017-12-29", ("cryptic", "2017-12-28", None)),
]

fails = 0
for title, published, want in CASES:
    got = title_facts(title, published)
    ok = got == want
    fails += not ok
    print(("  ok: " if ok else "  FAIL: ") + title + ("" if ok else f"\n    want {want}\n    got  {got}"))
print("all ok" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
