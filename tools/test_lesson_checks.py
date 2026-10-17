#!/usr/bin/env python3
# Findings read off clues two annotation runs filed differently
# (tools/lesson_checks.py): a double definition that hides the answer, and an
# answer with an apostrophe or accent filed without its spelling.
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import lesson_checks as L
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

DD = {"definitions": [{"text": "a", "at": 0}, {"text": "b", "at": 2}]}
check("an anagram of whole clue words filed as a double definition",
      "anagram", L.dd_misses_wordplay(DD, "Strip, like piles do", "DESPOIL"))
check("a word hidden across clue words", "hidden", L.dd_misses_wordplay(DD, "Lift off is no longer early", "REAR"))
check("a word hidden backwards", "hidden", L.dd_misses_wordplay(DD, "Is pinching more than just a dram", "NIPS"))
check("a hidden word inside one clue word is chance", None, L.dd_misses_wordplay(DD, "One who is offering", "RING"))
check("the answer as a whole clue word is the definition", None, L.dd_misses_wordplay(DD, "Good news", "GOOD"))
check("a parsed clue is not a double definition", None, L.dd_misses_wordplay(
    {**DD, "wordplay": {"op": "charade", "parts": []}}, "Strip, like piles do", "DESPOIL"))
check("one definition is not a double definition", None, L.dd_misses_wordplay(
    {"definitions": [{"text": "a"}]}, "Strip, like piles do", "DESPOIL"))
# The collapsed double definitions of the study (ANUS from MEAN MUSE less MEME, AVE from
# AVERAGE less RAGE, SEEMED from SEE + MED, TARANDS from TARS round AND) hide nothing the
# clue's letters show, so these checks leave them alone.
check("a real double definition is left alone", None, L.dd_misses_wordplay(
    DD, "Appeared to be what you can do on Riviera", "SEEMED"))

prose = lambda text: {"explanation": {"walkthrough": text}}
check("a missing accent the prose writes (FLANEUR, once filed with its spelling)", "FLÂNEUR",
      L.spelling_unsaid(prose("A flâneur is an idle man-about-town"), "FLANEUR"))
check("the same answer with its spelling is fine", None, L.spelling_unsaid(
    {**prose("A flâneur is an idle man-about-town"), "spelling": "FLÂNEUR"}, "FLANEUR"))
check("an answer another annotation spelled with an apostrophe", "GET SOMEONE'S GOAT",
      L.spelling_unsaid(prose("to annoy someone"), "GETSOMEONESGOAT", "3,7,4"))
check("an apostrophe spelling in the prose of a phrase", "TEACHER'S PET",
      L.spelling_unsaid(prose("a teacher's pet is the favourite"), "TEACHERSPET", "8,3"))
check("a pun in the prose (she'd for SHED) is not a spelling", None,
      L.spelling_unsaid(prose("she'd sounds like shed"), "SHED", "4"))
check("a phrase that counts more words than the enumeration is not one", None,
      L.spelling_unsaid(prose("I'm port"), "IMPORT", "6"))
check("a known two-word spelling is not wanted by a one-word enumeration", None,
      L.spelling_unsaid(prose("a plain word"), "IMPATIENT", "9"))
check("an unaccented answer with nothing to say is fine", None, L.spelling_unsaid(prose("a plain word"), "PLAIN"))

spellings = L.known_spellings()
check("the spelling list is keyed by the letters of its values", [],
      [k for k, s in spellings.items() if L.letters(s) != k])
check("and holds only spellings with a mark", [], [s for s in spellings.values() if s.isascii() and "'" not in s])

for field in ("wordplay.ddMissesWordplay", "spelling.unsaid"):
    check(f"{field} is a ratchet field", True, field in v.BACKLOG_MARKERS)
held = {"clue": {"text": "Strip, like piles do", "enumeration": "7"}, "solution": "DESPOIL"}
warn = v.lesson_warnings("1A", DD, held)
check("the validator warns of a double definition that hides its answer", 1, len(warn))
check("the ratchet refuses one more than a puzzle is allowed", 1, len(v.backlog_errors("x-1", warn, {"wordplay.ddMissesWordplay": {}})))
check("and allows what it has", 0, len(v.backlog_errors("x-1", warn, {"wordplay.ddMissesWordplay": {"x-1": 1}})))
raise SystemExit(fails)
