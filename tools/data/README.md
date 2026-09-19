# tools/data

What is committed here, and what is fetched.

## Committed

| file | what |
| --- | --- |
| `abbreviations.json` | Hand-built table of standard British-cryptic abbreviations (H = hard, R = river…). A starter set, meant to grow — see the `_comment` inside it. |
| `unclueable.json` | Words a setter rejected as answers, with the reason. `tools/grid_fill.py` vetoes them. |
| `sample_fill_11.json` | The worked 11x11 fill (see `tools/AUTHORING.md`). |
| `annotate_attempts.json` | How many annotation runs each puzzle has lost, and the session the last one died in, so a failing puzzle is not re-annotated from scratch every night (`tools/annotate_attempts.py`). Written by the nightly job and committed by it — tracked rather than local like `.solve_attempts.json`, because that job runs in a throwaway worktree and only a tracked file survives its rebuild. |
| `penguin_partial_fills/` | Answers from a Penguin-book solve that was stopped before it finished. The puzzle itself is filed UNSOLVED — `tools/daily_update.sh`'s cold solve (step 3a) owns it — because `tools/apply_solution.py` refuses to write over a puzzle that already holds answers and no `solutionSource`, so a half-filled puzzle file would turn away the job meant to finish it. These sit here instead, so the work is not bought twice. Nothing reads them automatically; they are for a person finishing one by hand. |
| `book_candidates.json` | Which archive.org crossword books are worth acquiring in full, with the reason behind every refusal — see [Book candidates](#book-candidates) below. |
| `lexicon.tsv` | 192,738 British-cryptic words with a frequency rank, derived from the Lufz and Exet lexicons by `tools/build_lexicon.js` (MIT — see below). Committed, unlike the blobs it comes from, because `tools/difficulty.py` reads it for the obscurity component of every rating and those ratings are committed in `puzzles/index.json`: fetched, the score a puzzle got depended on whether the machine running `--reindex` happened to have the file. 4.9 MB. |

## Book candidates

`book_candidates.json` — which archive.org crossword books are worth acquiring
in full, and why every refusal is a refusal. Written by
`tools/rank_book_candidates.py`, which borrows each candidate through
`tools/fetch_ia_book.borrowed()` (one loan at a time, always returned), reads
**leaves 6-39 only**, and judges the sample with `tools/grid_verdict.py`'s own
thresholds rather than any of its own. One row per candidate, carrying the
identifier, title, estimated puzzle count, median lights per puzzle,
clue-number survival, the verdict, and for every refusal a reason that says
which KIND it is:

| verdict | means |
| --- | --- |
| `acquire` | the sample reconstructs; worth the full borrow. |
| `reject` / rejected-on-form | read fine, wrong shape — grids that are not 15x15, barred thematic grids, or prose that prints no clue lists. Permanent. |
| `reject` / rejected-on-availability | archive.org has no such item, or lends no copy this account can read. About access, not about the book. |
| `undetermined` | nothing about the book was established — archive.org would not say which refusal a refused loan was, or this repo's parser could not read the book's layout. Never collapsed into a rejection, because a readable book filed under "wrong shape" is a false statement nobody would re-check. |

Committed rather than left in `/tmp`, which is where the previous run's copy
was written and where it evaporated. It is a MEASUREMENT AND IT GOES STALE:
items get taken down, loan pools shrink and a rescan changes the OCR under the
numbers. Re-run the tool rather than trusting the figures past the `derived`
date inside the file — `--reuse-samples` re-judges cached samples without
spending another loan on every book.

## Fetched, never committed

`bash tools/fetch_lexicon.sh` downloads about 26 MB of JavaScript and derives
the word lists from it. These blobs are gitignored; `lexicon.tsv`, derived from
them, is not — see above.

| file | source | licence |
| --- | --- | --- |
| `lufz-en-lexicon.js`, `lufz-en-lexicon-stems.js` | [viresh-ratnakar/lufz](https://github.com/viresh-ratnakar/lufz) | MIT |
| `exet-lexicon.js` | [viresh-ratnakar/exet](https://github.com/viresh-ratnakar/exet) | MIT |
| `clueability.tsv` | derived by `tools/clueability.py --build` | derived from the above |

The Lufz lexicon is UKACD18 — J Ross Beresford's UK Advanced Cryptics
Dictionary, the classic British cryptic word list — cleaned up and augmented
with Wikipedia-derived importance ordering, CMUdict pronunciations and Porter2
stems. That combination (British vocabulary + a real score column + a clear
licence) is why it is used here rather than `/usr/share/dict/words`, which has
no scores and so cannot support a fairness floor at all.

The derived files are gitignored on purpose: they are reproducible in under a
minute, and a stale committed copy that disagreed with the scorer would be worse
than no copy. The filler rebuilds `clueability.tsv` automatically when its
`CACHE_VERSION` changes.
