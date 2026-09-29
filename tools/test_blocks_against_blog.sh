#!/usr/bin/env bash
# check_blocks_against_blog and check_cryptic_definition_against_blog.
# A blog block our parse accounts for is silent, in
# every way the two can legitimately differ; one we lack is reported.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
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
raise SystemExit(fails)
PY
echo "all check_blocks_against_blog checks passed"
