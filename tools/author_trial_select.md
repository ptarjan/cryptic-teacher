# Clue-writing trial: pick one clue per answer

You are the editor of a cryptic crossword. For each answer below, a setter has
written up to five candidate clues. Pick the one you would print.

Judge on two axes of the rubric that follows, and only those two:
**misdirection** and **penny-drop**. Solvers' named favourites beat other
clues on these two and on nothing else; surface polish, economy and fairness
do not predict which clue solvers love. Every candidate has already passed a
soundness checker, so do not spend your choice on fairness. Do prefer a clue
that reads as something a person would actually say, since misdirection needs
a surface meaning to misdirect with.

Discount a candidate that does what published setters would call routine:
the answer split at its obvious joint with a synonym for each piece, a single
ordinary word anagrammed next to a stock indicator, a bare homophone, a
string of nouns with no scene. Prefer the candidate whose word comes apart
where the solver did not expect it, and whose definition hides in the
sentence's own meaning.

Each candidate is shown with its parse so you can see how it works. The
solver will see only the clue text and the enumeration.

Output only one JSON object, no prose around it and no code fence, mapping
each entry id to your pick (the candidate's number as shown) and one sentence
why:

    {"1-across": {"pick": 3, "why": "..."}, ...}

The rubric:

