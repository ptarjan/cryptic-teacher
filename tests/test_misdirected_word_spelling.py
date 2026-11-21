#!/usr/bin/env python3
# features.misdirectedWord is checked against the clue as the scan printed it: a word split
# by a hyphen or space, an inflected token, or a token run into its neighbour is still there.
#
#     python3 tests/test_misdirected_word_spelling.py
import _path  # puts tools/ on sys.path
from validate_features import word_in_clue as W

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


check("plain whole word", W("Fake", "Fake folio made a Tory"))
check("hyphenated word over a clue that breaks the hyphen", W("point-to-point", "Stuns tough female, on coming off at point-to point"))
check("word split by a scan hyphen and space", W("aggregate", "Pigment from mineral aggre- gate round church"))
check("hyphen spelt with a stray space", W("Top-liner", "Top -liner reorganized multinational bureau"))
check("underscore markup around the word", W("fine", "Out of prison _confinement ten riot-get fine_"))
check("inflected token", W("house", "Also housed party in London"))
check("token run into the next word", W("parts", "Maker of better partsin practice"))
check("token run into the next word, mid-clue", W("couple", "Viewpoint about last Gaelic couplein English"))
check("a word the clue never prints is still refused", not W("sheets", "Safety precautions for smokers in bed?"))
check("a substituted letter is still refused", not W("tar", "Taste of car?"))
check("a two-letter stem is never matched inside a token", not W("be", "Beg for keys"))
check("empty word", not W("-", "Beg for keys"))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
