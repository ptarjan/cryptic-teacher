"""Plain ok/FAIL checks of tools/byline.py and the TLS byline pattern (no pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import byline  # noqa: E402
import byline_backfill as bb  # noqa: E402

bad = 0


def check(name, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {name}: {got!r} != {want!r}")
    else:
        print(f"ok {name}")


check("independent weekday", byline.name_in("No.5466 Saturday 24 April by Phi ACROSS"), "Phi")
check("upper BY", byline.name_in("CRYPTIC CROSSWORD 7344 BY PHI ACROSS"), "Phi")
check("ft set by", byline.name_in("CROSSWORD No.7,124 Set by CINEPHILE"), "Cinephile")
check("not a day", byline.name_in("solutions received by Wednesday March 23"), None)
words = [(215, 1726, 567, 1763, "No.5466 Saturday 24 April"), (854, 1722, 956, 1767, "by Phi"),
         (1843, 1663, 2377, 1706, "CONCISE CROSSWORD by Eimi")]
check("near title", byline.near_title(words, (215, 1649, 1286, 1763), right=200), "Phi")
m = bb.TLS_TITLE.search("TLS Crossword 946 by Tantalus . 44")
check("tls", (m.group(1), m.group(2)), ("946", "Tantalus"))
check("ft 1980 unprinted", byline.is_unprinted("ftcryptic", "1982-01-02"), True)
check("ft 1990 printed", byline.is_unprinted("ftcryptic", "1990-01-02"), False)
check("tls 2008 unprinted", byline.is_unprinted("tls", "2008-05-16"), True)
check("independent printed", byline.is_unprinted("independent", "2004-04-24"), False)
sys.exit(1 if bad else 0)
