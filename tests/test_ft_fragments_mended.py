#!/usr/bin/env python3
"""FT_FRAGMENTS_MENDED: a reread takes the whole Gale FT clue for a held one cut inside
(tools/file_archive_org_puzzles.ft_fragments_mended); 2003-12-10's held clues.

Run as a plain script, as CI does (no pytest there).
"""
import _path  # puts tools/ on sys.path
import sys

import file_archive_org_puzzles as fa

FT = "Financial Times"
CUT = [
    ("Express disapproval, ing prohibition, for prim", "Express disapproval, during prohibition, for primate"),
    ("Moving boats with po from port", "Moving boats with poles from port"),
    ("Deal with drugs or do wi out?", "Deal with drugs or do without?"),
    ("Information in the p-1 on gas", "Information in the p-pipe on gas"),
    ("Type of butter unchar 100 in type of bog", "Type of butter unchanged in type of bog"),
    ("Home containing good st for baby", "Home containing good start for baby"),
]
HELD = ["River shed", "Divine drink with 10 for 100 in 2004", "Newspaperman rioted dis gracefully"]

failed = 0


def check(ok, name):
    global failed
    print(("ok   " if ok else "FAIL ") + name)
    failed += not ok


for was, now in CUT:
    check(fa.ft_fragments_mended(FT, was, now), f"cut clue replaced by the whole one: {was!r}")
    check(not fa.ft_fragments_mended("The Times", was, now), f"only the FT takes it: {was!r}")
for was in HELD:
    check(not fa.ft_fragments_mended(FT, was, was), f"a clue that reads as held stays: {was!r}")
check(not fa.ft_fragments_mended(FT, "Boy gets beaten", "Boy gets beater"), "a changed whole word is not a fragment")
check(not fa.ft_fragments_mended(FT, "Take it or leave it", "Take it or leave"), "a dropped whole word is not a fragment")

sys.exit(1 if failed else 0)
