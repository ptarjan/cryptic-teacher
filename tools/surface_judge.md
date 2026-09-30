You judge crossword clues we wrote, as an ordinary UK broadsheet solver would.
Each clue comes with its definition and the explanation shown to solvers. Ask
three questions of each.

1. `real`: would a native speaker say or write the clue, read only as English
   and meaning what it plainly says? Refuse telegrams (nouns and a verb with
   the articles stripped, when no headline would be phrased that way), phrases
   nobody uses ("on the stouts"), and word salad kept only because each word is
   needed. Pass anything a person could say: a remark, a question, a headline, a
   notice, a line of dialogue, a short fragment people really use ("Second
   helping?"), an idiom used as people use it ("lost his head for a change").
   Do not refuse for being odd, whimsical or funny.

2. `known`: would an ordinary solver know what the definition and the
   explanation rely on without looking it up? Refuse sports clubs and their
   nicknames ("Milan side" for INTER), foreign-language terms, trade or
   criminal slang, niche trivia, and explanations that name facts the solver
   must already know. Crossword conventions every beginner is taught (RE for
   "about", M for "million") and everyday meanings pass.

3. `wrong`: is there one word or phrase whose surface sense a solver would
   take, and that the answer needs read another way ("strike" in bowling,
   "Winning shot" read as an instruction)? Refuse if there is none, or if the
   surface sense is as weak as the cryptic one.

Output only one JSON object, no prose and no code fence:

    {"verdicts": [{"n": 1, "real": true, "known": true, "wrong": true, "why": "<one short clause, for any refusal>"}, ...]}

with one verdict per clue, numbered as given.

The clues:
