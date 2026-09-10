Score each cryptic crossword clue below on five axes, 0-5, whole numbers.

- **surface** — does the clue read as a natural sentence or phrase someone might
  actually say or write? A clue that is visibly a list of instructions scores low
  however sound its mechanism.
- **misdirection** — does the surface meaning pull away from the real parsing?
  A clue whose definition and wordplay are obvious on first read scores low.
- **pennydrop** — how satisfying is the moment it resolves? Score the click, not
  the difficulty. A clue that is merely hard has no click.
- **economy** — is every word doing work? Padding scores low; so does a clue so
  compressed it is unreadable.
- **fairness** — could a solver reach the answer from the clue alone, by rules
  they could defend afterwards? Stretchy definitions and unindicated liberties
  score low.

Judge the writing, not the difficulty, and not whether you personally solved it.
Score each clue on its own terms; you are not ranking them against each other.
An average published clue should land around 3. Use the whole range: a 5 is a
clue you would quote to somebody, a 0 is one that does not work at all.

Output JSON only, an array with one object per clue, no prose before or after:

```json
[{"label": "c0123", "surface": 3, "misdirection": 4, "pennydrop": 3, "economy": 4, "fairness": 4}]
```

The clues, each with its answer and enumeration:
