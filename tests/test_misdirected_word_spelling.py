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
check("word run into a short word before it", W("tear", "Disowned tearabout member of the cat family"))
check("word run into a short word, off a lexicon word", W("Beam", "Beamset back in ground and rope about the neck"))
check("word run into two words", W("Gray", "Graylightof the Stoke Poges landscape"))
check("misread letter in a name", W("Quakers", "Amicably shake hands when Ouakers?"))
check("misread letter before an apostrophe", W("Wodehouse's", "Country homes of Wedehouse's, reportedly"))
check("a word split by a stray space and a misread letter", W("dissected", "Early look at viper we dissec red"))
check("a word the scan split in two", W("spelling", "The witch-doctor's bad spell ling?"))
check("a one-letter-off real word is a different word", not W("forte", "They display their force in a great many high places"))
check("a one-letter-off real word, rota for rote", not W("rote", "Confine by rota, say?"))
check("a three-letter word is never matched off by a letter", not W("hoy", "Modern sort of Eton boy"))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
