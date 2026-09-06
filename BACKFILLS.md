# Backfills

Work that is only worth doing with inference to spare and no puzzles waiting.
Everything here is a sweep over the existing corpus: none of it blocks a new
puzzle, none of it is a bug, and every item is already handled going forward —
the nightly annotation writes the new shape and the validator holds it. What is
left is the tail behind it.

The rule that puts something here: the fix is correct, the mechanism is shipped,
and the only remaining cost is re-reading clues we have already published. If a
new annotation would still come out wrong, it does NOT belong here — that is a
prompt or validator job and it happens now.

Ordered by what a solver would notice first.

## 1. `surface` on the existing 6,403 walkthroughs

Added 2026-09-06. The walkthrough rung shows **The joke** (`surface`, what the
clue pretends to be about) above **The trick** (`walkthrough`, what it is
doing). Only `everyman-4167` 26A has been split by hand; every other annotation
has no `surface` and renders as it always did, which is correct but poorer.

Not a mechanical split. A scan of all 6,403 that day found no phrase list can
tell a surface sentence from a mechanical one — "the donkey is scenery" and "the
definition is being coy" both describe a surface and match nothing — and about a
third of any proxy's hits are clues that paint no picture apart from their
mechanism, where inventing one is worse than leaving the field out. So this is a
per-clue model pass, not a regex: read the clue, decide whether it paints a
picture, write one sentence if it does, move any surface sentence already
sitting in `walkthrough` across.

Cost: ~6,400 clues. Scope it by puzzle so a killed run keeps what it finished.
