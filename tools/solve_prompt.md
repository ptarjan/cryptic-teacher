# Solving a puzzle the paper hasn't published answers for

Saturday prize crosswords appear without solutions and only get them about a
week later. Rather than leave the newest and most-visited puzzle on the site
with no hints for a week, we solve it here. This is the instruction set for
that job. `tools/annotate_prompt.md` takes over afterwards; it needs a solved
grid to work from, and this is where that grid comes from.

Solve it as a solver would, and be honest about the difference between an
answer you have worked out and an answer you have guessed.

## What you are given

    python3 tools/solve_packet.py <number>

prints every clue with its length, plus a crossing map: for each entry, which
of its letters are shared with which letter of which other entry. Read the
crossing map. It is most of the information in the grid, and it is the only
thing that can tell you an answer is wrong without an answer key.

## What you must produce

A JSON file mapping entry id to answer:

    {"1-across": "POPULAR FRONT", "9-across": "AGAIN", ...}

Spaces, hyphens and apostrophes are fine — they are stripped. Every entry must
be present.

## The check you run yourself

    python3 tools/apply_solution.py <number> --fill /tmp/fill-<number>.json --check-only

This reports missing entries, wrong lengths and disagreeing crossings, and
writes nothing. Run it, fix what it complains about, run it again. Do not stop
until it says every crossing agrees. The calling script runs it again for real
afterwards and will refuse the whole fill if it does not pass, so an unchecked
fill is simply a wasted night.

## How to actually solve

1. **First pass, cold.** Take every clue in order and answer the ones you are
   sure of. Skip freely — a wrong answer written early costs more than a blank,
   because every crossing it touches then argues against the right answers
   around it.
2. **Second pass, with crossings.** Now the checked letters constrain things.
   Work the entries with the most crossed letters filled. Most of the puzzle
   falls out here.
3. **Last few.** Where you have a pattern but no parse, say so rather than
   inventing wordplay. Where you have a parse but the crossings refuse it, the
   crossings win — the parse is wrong.
4. **Verify.** Run the check. Zero conflicts across every crossing, or keep
   going.

Two things a crossing map cannot catch, so watch for them yourself: a
consistent-but-wrong pair of answers that happen to share their crossing
letter, and an answer that fits the letters with no wordplay behind it at all.
Both show up as "I could not parse this", which is worth writing down.

## Confidence, and when to stop

Alongside the fill, report for each entry one of:

* **CONFIDENT** — the wordplay accounts for every letter.
* **LIKELY** — definition and crossings both fit, wordplay only partly parsed.
* **GUESS** — it fits the letters and nothing more.

An honest GUESS is a fine outcome and a useful signal. An answer dressed up as
CONFIDENT with invented wordplay is the one genuinely bad outcome, because the
annotation step will then explain, in detail and with authority, something that
never happened. If you cannot complete the grid, say which entries defeated you
and stop: a rejected fill costs one night, and the puzzle simply gets its
answers from the paper next week.

## Afterwards

These answers are published marked as ours, not the paper's, and the puzzle
keeps getting re-fetched every night until the official key appears — at which
point the fill is graded against it automatically and any entry you got wrong
has its annotation thrown away and rewritten. So the cost of being wrong is
paid later and in public. Prefer the blank.
