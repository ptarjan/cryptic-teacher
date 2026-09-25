# Backfills

This file lists sweeps over already-published clues. Do them only when there is
inference to spare and no puzzles waiting.

An item belongs here only when all of these are true:

- the fix is correct;
- the mechanism is shipped, so every new annotation already comes out right
  (the nightly annotation writes the new shape and the validator holds it);
- the only remaining cost is re-reading clues already published.

None of these items blocks a new puzzle, and none is a bug. If a *new*
annotation would still come out wrong, the item does not belong here: that is a
prompt or validator fix, and it happens now.

Items are ordered by what a solver would notice first.

## 1. Add `surface` to existing walkthroughs

The walkthrough rung shows two labelled parts:

- **What it seems to say**: the `surface` field, what the clue pretends to be
  about.
- **The trick**: the `walkthrough` field, what the clue is actually doing.

An annotation without `surface` shows "The trick" alone. That is correct, but
poorer. `tools/annotate_prompt.md` asks for `surface` on new annotations, and
omits it only when the clue has no surface apart from its mechanism (double
definitions, cryptic definitions, idioms). On 2026-09-24, 11,111 of 17,769
annotated walkthroughs had a `surface`. The rest are the backlog, though some
of them correctly have none.

**This cannot be done mechanically.** No phrase list can tell a surface sentence
from a mechanical one: "the donkey is scenery" and "the definition is being
coy" both describe a surface and match nothing. About a third of any proxy's
hits are clues with no picture apart from their mechanism, and inventing a
surface for those is worse than leaving the field out.

So it is a per-clue model pass:

1. Read the clue and decide whether it paints a picture.
2. If it does, write one sentence of at most 25 words.
3. Move any surface sentence already in `walkthrough` into `surface`.

Scope each run by puzzle, so a killed run keeps what it finished.
