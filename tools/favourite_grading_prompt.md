Score each cryptic crossword clue below from 0 to 5, in whole numbers, on five
axes:

- **surface**: does the clue read as a natural sentence someone might say or
  write? A clue that is visibly a list of instructions scores low, however
  sound its mechanism.
- **misdirection**: does the surface meaning pull away from the real parsing?
  If the definition and wordplay are obvious on first read, score low.
- **pennydrop**: how satisfying is the moment it resolves? Score the click,
  not the difficulty. A clue that is merely hard has no click.
- **economy**: is every word doing work? Padding scores low, and so does a clue
  compressed until it is unreadable.
- **fairness**: could a solver reach the answer from the clue alone, by rules
  they could defend afterwards? Stretched definitions and unindicated liberties
  score low.

Judge the writing, not the difficulty or whether you solved it. Score each clue
on its own, not against the others. An average published clue scores about 3.
Use the whole range: 5 is a clue you would quote to someone, and 0 is one that
does not work.

Output only a JSON array with one object per clue, in this shape:

[{"label": "c0123", "surface": 3, "misdirection": 4, "pennydrop": 3, "economy": 4, "fairness": 4}]

The clues follow, each with its answer:
