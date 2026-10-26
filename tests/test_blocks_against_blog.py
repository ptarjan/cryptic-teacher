#!/usr/bin/env python3
# check_blocks_against_blog and check_cryptic_definition_against_blog.
# A blog block our parse accounts for is silent, in
# every way the two can legitimately differ; one we lack is reported.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import validate_annotations as v

def run(clue, blocks, theirs):
    puzzle = {"entries": [{"number": 1, "direction": "across",
                           "clue": {"text": clue}, "annotation": {"blocks": blocks}}]}
    v.blog_facts_for = lambda p: {"name": "Blog", "url": "u",
                                  "entries": {"1-across": {"blocks": theirs}}}
    warnings = []
    v.check_blocks_against_blog(puzzle, warnings)
    return warnings

fails = 0
def check(name, want, got):
    global fails
    ok = bool(got) == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)

b = lambda frag, gives: {"clueFragment": frag, "gives": gives}
fodder = lambda frag, gives: {"clueFragment": frag, "gives": gives, "anagramOf": True}
check("same letters", False, run("x", [b("among", "IN"), b("group", "PACK")], [b("group", "PACK")]))
check("the blog's word before the reversal", False, run("x", [b("pulls back", "SWOT")], [b("pulls", "TOWS")]))
check("the blog's word heard", False, run("x", [b("Heard husky", "HORSE")], [b("husky", "HOARSE")]))
check("ours is the blog's less a deletion", False, run("x", [b("x", "IMPRE")], [b("zzz", "IMPURE")]))
check("the anagram's result against its fodder", False, run("x", [b("male", "MALE")], [b("zzz", "LAME")]))
check("a lone link word is the blog's parse", False, run("x", [b("x", "HI")], [b("of", "ARCHERY")]))
check("the blog's anagram fodder against ours", False, run("x", [b("in hat", "INHAT")], [fodder("in hat", "IN HAT")]))
check("the blog's anagram fodder against our result", False, run("x", [b("in hat", "THAIN")], [fodder("in hat", "IN HAT")]))
check("a piece nobody of ours spells or takes", True, run("x", [b("top", "CAP")], [b("communist", "RED")]))
def typed(ours, theirs, **fact):
    puzzle = {"entries": [{"number": 1, "direction": "across",
                           "clue": {"text": "x"}, "annotation": {"type": ours}}]}
    v.blog_facts_for = lambda p: {"name": "Blog", "url": "u",
                                  "entries": {"1-across": {"type": theirs, **fact}}}
    warnings = []
    v.check_cryptic_definition_against_blog(puzzle, warnings)
    return warnings

check("a labelling choice between types is silent", False, typed(["anagram"], ["container"]))
check("a cryptic definition the blog also calls one is silent", False, typed(["cryptic_definition"], ["double_definition"]))
check("a cryptic definition the blog parses as an anagram is reported", True, typed(["cryptic_definition"], ["anagram"]))
core = {"inferred": ["type"], "typeCore": True}
check("an inferred core type is a lower bound, not a contradiction", False, typed(["container", "deletion"], ["container"], **core))
check("a cryptic definition against an inferred core type is reported as at least it", True,
      [w for w in typed(["cryptic_definition"], ["container"], **core) if "at least 'container'" in w])

# check_type_against_blog: a type family apart is reported, a label within one is not.
def family(ours, theirs, pid="x-1", **fact):
    puzzle = {"id": pid, "entries": [{"number": 1, "direction": "across",
                                      "clue": {"text": "x"}, "annotation": {"type": ours}}]}
    v.blog_facts_for = lambda p: {"name": "Blog", "url": "u",
                                  "entries": {"1-across": {"type": theirs, **fact}}}
    warnings = []
    v.check_type_against_blog(puzzle, warnings)
    return warnings

check("a container the blog calls a charade is silent", False, family(["container"], ["charade"]))
check("a double definition the blog calls cryptic is silent", False, family(["double_definition"], ["cryptic_definition"]))
check("a double definition the blog parses as a charade is reported", True, family(["double_definition"], ["charade"]))
check("an anagram the blog reads as a charade is reported", True, family(["anagram"], ["charade"]))
check("an &lit goes with anything", False, family(["and_lit", "anagram"], ["charade"]))
check("an inferred type is not the blogger's", False, family(["anagram"], ["charade"], inferred=["type"]))
check("ours as a cryptic definition against named wordplay is the other check's", False,
      family(["cryptic_definition"], ["anagram"]))
v.BLOG_DISAGREE[("x-2", "1-across")] = ("definition,type", "the blog's charade misses the second definition")
check("a clue filed as kept is silent", False, family(["double_definition"], ["charade"], pid="x-2"))
if fails:
    raise SystemExit(fails)
print("all check_blocks_against_blog checks passed")
