#!/usr/bin/env bash
# check_blocks_against_blog: a blog block our parse accounts for is silent, in
# every way the two can legitimately differ; one we lack is reported.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import validate_annotations as v

def run(clue, blocks, theirs):
    puzzle = {"entries": [{"id": "1-across", "number": 1, "direction": "across",
                           "clue": clue, "annotation": {"blocks": blocks}}]}
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
check("same letters", False, run("x", [b("among", "IN"), b("group", "PACK")], [["PACK", "group"]]))
check("the blog's word before the reversal", False, run("x", [b("pulls back", "SWOT")], [["TOWS", "pulls"]]))
check("the blog's word heard", False, run("x", [b("Heard husky", "HORSE")], [["HOARSE", "husky"]]))
check("ours is the blog's less a deletion", False, run("x", [b("x", "IMPRE")], [["IMPURE", "zzz"]]))
check("the anagram's result against its fodder", False, run("x", [b("male", "MALE")], [["LAME", "zzz"]]))
check("a lone link word is the blog's parse", False, run("x", [b("x", "HI")], [["ARCHERY", "of"]]))
check("a piece nobody of ours spells or takes", True, run("x", [b("top", "CAP")], [["RED", "communist"]]))
raise SystemExit(fails)
PY
echo "all check_blocks_against_blog checks passed"
