#!/usr/bin/env python3
# Does a blog-facts run that skips the letter pass keep the inferred fields?
#
#     python3 tools/test_blog_facts_skip.py
#
# blog_facts.regrafted(rec, old) is what a skip run writes: `rec`, the sidecar as
# the blogs alone give it, with the inferred layer of `old`, the sidecar there.
# The cases are clues of the sidecars the 2026-10-24 skip run stripped: a type the
# blog gave and the letter pass widened (azed-2105 4-down), a homophone block
# read as heard (cryptic-28363 27-across), a clue the blog added since, and one
# whose blog side moved.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")

import blog_facts

HEAD = {"blog": "fifteensquared", "name": "Fifteensquared", "url": "https://example.com/p/"}
OLD = {**HEAD, "entries": {
    "4-down": {"type": ["hidden_word", "reversal"],
               "blocks": [{"clueFragment": "mignonettes", "gives": "NONG", "inferred": True}],
               "inferred": ["blocks", "type"]},
    "5-down": {"type": ["anagram"]},
    "27-across": {"type": ["homophone"], "definitions": [{"text": "One attacking", "at": 0}],
                  "indicators": [{"text": "in speech", "for": "homophone"}],
                  "blocks": [{"clueFragment": "a holy book", "gives": "ASSAULTER", "soundsLike": "A PSALTER",
                              "inferred": True}],
                  "inferred": ["blocks"]},
    "11-down": {"type": ["container"], "blocks": [{"clueFragment": "winning", "gives": "UP"}],
                "indicators": [{"text": "in", "for": "container"}], "inferred": ["indicators"]},
}}
# What the blogs alone give: the same posts, nothing inferred.
REC = {**HEAD, "entries": {
    "11-down": {"type": ["container"], "blocks": [{"clueFragment": "winning", "gives": "UP"}]},
    "27-across": {"type": ["homophone"], "definitions": [{"text": "One attacking", "at": 0}],
                  "indicators": [{"text": "in speech", "for": "homophone"}],
                  "blocks": [{"clueFragment": "holy book", "gives": "A PSALTER"}]},
    "4-down": {"type": ["hidden_word"]},
    "5-down": {"type": ["anagram"]},
}}


def main():
    got = blog_facts.regrafted(REC, OLD)
    assert got is OLD, "a sidecar the blogs left as it was must come back as the one held, inferred fields and all"

    # A clue the blogs added: the new one is theirs alone, the others keep their inferred fields.
    more = {**REC, "entries": {**REC["entries"], "6-down": {"type": ["charade"]}}}
    got = blog_facts.regrafted(more, OLD)
    assert got["entries"]["6-down"] == {"type": ["charade"]}
    for eid in OLD["entries"]:
        assert got["entries"][eid] == OLD["entries"][eid], eid

    # A clue whose blog side moved loses its inferred fields; its neighbours do not.
    moved = {**REC, "entries": {**REC["entries"], "4-down": {"type": ["hidden_word", "container"]}}}
    got = blog_facts.regrafted(moved, OLD)
    assert got["entries"]["4-down"] == {"type": ["hidden_word", "container"]}
    assert got["entries"]["27-across"] == OLD["entries"]["27-across"]

    # A puzzle whose header moved is the blogs' alone.
    assert blog_facts.regrafted({**REC, "url": "https://example.com/other/"}, OLD)["url"] == "https://example.com/other/"
    print("ok")


if __name__ == "__main__":
    main()
