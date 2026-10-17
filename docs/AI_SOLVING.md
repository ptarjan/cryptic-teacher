# How the AI solves and hints the puzzles

Cryptic Teacher gives every clue a hint ladder: indicator, definition, clue
type, building blocks, full walkthrough. Nobody writes those hints by hand.
A language model writes them, a validator checks them, and scheduled jobs
spend a fixed weekly quota writing as many as the quota buys. This document
explains which models do what, how the procedure evolved from its start in
late July 2026, how the system fits together, where it falls short, and what
might come next. It describes how and why; live counts (puzzles filed,
solved, hinted) are on the site's /progress/ page, not here.

It is written for an outside technical reader. The operational details live
elsewhere: [NIGHTLY.md](NIGHTLY.md) covers the scheduled jobs,
[PUZZLE_FORMAT.md](PUZZLE_FORMAT.md) the file format and annotation rules,
[ARCHIVE_COVERAGE.md](ARCHIVE_COVERAGE.md) the scanned archive, and
[APP.md](../APP.md) how the site presents a hint.

## The problem in one paragraph

A cryptic clue has a definition at one end and wordplay that builds the same
answer a second way. Explaining a clue means finding both halves, naming the
mechanism (anagram, container, charade, hidden word ...), and accounting for
every letter. Most puzzles in the corpus come with a published answer key, so
the model's job is usually *explaining* a known answer. Some do not: prize
puzzles withhold their answers for a week, scanned archive editions often
lack a legible solution, and some books print none. Those must be *solved*
first, and a solved answer can be wrong in ways a crossing check cannot see.

## Models, by role

Two families of model do the work. Claude, called through the `claude` CLI
in non-interactive mode (`claude -p`), does everything that needs reasoning
about a clue. Small local models do everything that turns a page image into
text, so the scanned archive costs no Claude quota at all.

### Claude: the writing and reasoning roles

Every Claude role is a `claude -p` subprocess started by a shell or Python
script, with a role-specific system prompt, a short tool list and a pinned
model and reasoning effort, set in the script that starts it. Neither is
left to the CLI's default: the default effort differs per model, so it would
change silently whenever the alias moved.

| Role | Script / prompt | What it does |
|---|---|---|
| Solve + annotate | `tools/puzzle_worker.sh`, `tools/annotate_prompt.md`, `tools/solve_prompt.md` | One conversation per puzzle, in one pass. With no key, it fills the whole grid first (the crossings confirm each answer, checked by `apply_solution --check-only`), then turns the wordplay it already parsed while solving into every clue's hint ladder as JSON. |
| Graded-miss diagnosis | `tools/solve_misses.py`, `tools/solve_miss_prompt.md` | When the official key shows that a cold solve got a light wrong, this works out why, and whether a check could have caught it. |
| Bad-hint report fixes | `tools/report_fix_prompt.md`, from `tools/daily_update.sh` | Works through the hints that readers report from the site. The fix goes into the data, and into the renderer or validator where it can. |
| Clue-quality judge | `tools/grade_clues_judge.sh`, `tools/grade_clues_judge.md` | Three fresh judges per arm score clues blind on five axes, to compare clues we write with published ones. |
| Favourite grading | `tools/favourite_grading.sh`, `tools/favourite_grading_prompt.md` | Scores published clues on the same axes, to check those axes against solvers' favourite votes. |
| Authoring trials | `tools/author_trial.py`, `tools/author_trial_author.md`, `tools/author_trial_select.md` | Writes original clues: several candidates per answer from a fresh author with no tools, then a selector picks one. |
| Surface judge | `tools/surface_judge.md`, called by the authoring trials | Refuses an authored clue whose surface is not a real sentence. A refusal needs two calls to agree, because a single call false-refuses too often to trust alone. |

The annotation model is pinned once, as `ANNOTATE_MODEL` (with
`ANNOTATE_EFFORT`), in each scheduled job: `tools/daily_update.sh` and
`tools/prereset_backfill.sh`. It is an alias, so each run records the exact
model it resolved to in the puzzle's `annotatedBy`, and the provenance checks
refuse a bare alias there. The corpus itself, not this document, is the
record of which model wrote which puzzle's hints.

**Why Opus.** The pin was first chosen on 08-08 from a one-puzzle benchmark,
recorded in [APP.md](../APP.md) under "The annotator model". Opus 5 matched
Fable 5 on clue types and definitions (23 and 22 of 25), used no cryptic
definitions and solved both of the hardest clues, at about a third of Fable's
cost. Sonnet 5 was cheaper again, but it quietly filed the two clues it could
not solve as "cryptic definition", and its output was still validator-clean.
Haiku fabricated: it reported a puzzle complete when 17 of its 27 clues had
no wordplay at all.

The choice was re-tested on 10-12 with a paired A/B over the burn's own queue
(`tools/data/annotate_ab.json`):

- **Sonnet at medium effort, 20 puzzles.** Its tokens were 25% cheaper at list
  prices. It used more of the subscription quota, though, because it retried
  more. It passed its first check on 11 of 19 puzzles against Opus's 15 of
  19, failed one puzzle outright, and blind Opus judges ranked it last in 15
  of 20 comparisons.
- **Opus at low effort, 40 more puzzles.** It saved 14% of tokens per clue.
  It lost the blind judging 8 to 34, mostly because it wrote fewer and
  thinner walkthroughs.

So on 10-12 the default stayed Opus at medium. The blog cross-check and the answer key
could not tell the arms apart, because the validator already enforces both;
only judges reading the prose could.

### Local models: reading scans

Archive puzzles come from scanned newspaper pages and Trove. Their clue text
comes from several independent readers that vote, all run on the OCR host and
the GPU host (`tools/ocr_clues.py`):

- **RapidOCR, two recognisers.** These are the multilingual PP-OCRv4 model and
  the English PP-OCRv5 mobile model, run at twice the scan's size. They were
  picked because they misread the fewest clue words on hand-checked crops
  from 1974, 1990 and 1995: 22% and 26% of tokens, against 50% and 56% for the
  English PP-OCRv3 and v4 models.
- **Tesseract.** Its LSTM model is fine-tuned on the archive's own print
  (`tools/data/archive_org_tess.traineddata`, trained by
  `tools/train_archive_org_tesseract.py`), plus a whole-page read.
- **A vision-language model.** It runs in `tools/vlm_reader.py` at temperature
  0 and does two jobs. `tools/vlm_column_prompt.md` asks it to transcribe a
  whole clue column exactly as printed, and that reading becomes one more
  voter. `tools/vlm_pick_prompt.md` shows it a clue the other readers disagree
  on, together with their readings, and asks it to repeat the right one or to
  copy the clue from the image itself. Both prompts insist it must not
  "correct" an odd clue, because cryptic clues are odd on purpose. The VLM
  started as Qwen3-VL-8B on 10-02 and moved to a larger 27B model on 10-10;
  `MODEL` in `tools/vlm_reader.py` names the one in use.

No neural language model is used for text. To choose between OCR readings,
the vote uses a lexicon, WordNet and a count table of clue words and word
pairs built from the corpus (`tools/build_clue_lm.py`), which leaves out the
puzzles in the OCR gold set. Blog write-ups are parsed by rules, not a model
(`tools/blog_facts.py`, checked against a hand-labelled gold file).

## How the procedure evolved

Every puzzle's hints land in their own "Annotate <id>" commit, so those
commits counted by month tell the scaling story: a handful in July and
August, thousands a month once the burn ran in September and October. The
shifts below are the ones that changed how the model is used, not what it
produced.

### July: hand-run annotation and the first validator (07-26 to 07-31)

The first commit day added the Guardian fetcher, the six-level hint ladder,
the first two annotated puzzles and, the same day, a work-in-progress
`tools/validate_annotations.py`. From the start the annotation was a
structured JSON object (definitions, indicators, blocks of clue words with the
letters they give) rather than prose, precisely so that a program could check
it. Within days `STYLE.md` became a ledger of feedback, and each lesson in it
became either a validator rule or a sentence in the style guide. A nightly job
annotating newest-first appeared on 07-30.

### August: picking the annotator, adding a solver (08-02 to 08-29)

The annotator was first pinned to Fable, then moved to Opus on 08-08 after a
one-puzzle benchmark (the table in [APP.md](../APP.md)): Opus matched Fable's
structure at about a third of the cost, Sonnet quietly filed the clues it
could not solve as "cryptic definition", and Haiku fabricated. Two things in
that benchmark shaped everything after. A validator-clean annotation is not a
correct one, so the validator grew *cross-checks* (blocks must spell the
answer, an indicator cannot sit inside its own fodder, at most two cryptic
definitions per puzzle as a give-up tripwire). And the cost of a run is mostly
the model reasoning, so prompt length and turn count matter.

On 08-02 the first "spend the tail of the weekly window" script appeared: the
origin of the burn (below). On 08-09 hints began to be graded by blind solve
packets, asking whether a hint teaches rather than scoring it against a
rubric, and early rungs stopped giving the answer away. On 08-12
`tools/solve_prompt.md` was created so the model could cold-solve puzzles whose
answers were not yet published. On 08-29 the annotation rules moved from
"go and read STYLE.md" into a generated `tools/annotate_prompt.md`.

### September: resume, measure, and lean prompts

- **Resume, never re-buy (09-01, 09-07).** A run cut off by a usage lockout
  is resumed in its own conversation (`claude -p --resume`) instead of being
  restarted, so the reasoning already paid for is kept.
- **Cold solves capped (09-05).** At most two solve attempts per puzzle.
- **Fewer turns (09-06).** The run's questions to the tooling are answered in
  one turn rather than ten, and the run stops re-deriving the validator by
  reading its source.
- **The prompt shrinks (09-13).** The annotate prompt went from 548 lines to
  288; it was rewritten again on 09-25, and from 09-28 its generated
  reference section fails CI when stale.
- **Graded misses (09-14, 09-30).** When the official key arrives for a
  puzzle the model solved, each wrong light is recorded and a nightly unit has
  the model diagnose it (`tools/solve_misses.py`).
- **Corroboration (09-25 onward).** `tools/corroborate.py` checks every write
  against the other cached copies of the same puzzle, and on 09-27 a cold
  model fill that disagreed with a blog's answer started being refused.
- **Provenance (09-28).** Puzzle files split `source` (where the puzzle came
  from) from `solutions` (where the answers came from) and record the model in
  `annotatedBy`. From then on, every answer in the corpus says whether a
  publisher, a blog or a model supplied it.
- **Validator over prompt (09-30).** Paul's rule: every word in the solve or
  annotate prompt is paid for on every run, while a check in the validator
  costs nothing unless it fires. So a lesson from a miss or a bad-hint report
  becomes a mechanical check first, measured for false positives on correct
  work, and prompt text only when no check is possible. A test caps the
  solve prompt's length. The same day `tools/annotate_check.py` began
  telling a run when it is clean and finished, and the prompts moved into the
  system prompt.
- **Judges and authoring trials (09-29, 09-30).** Model judges were
  calibrated against solvers' favourite votes, and the checks the votes
  refuted were deleted (see the judge rows in the model table above).

### October: one burn, fallible sources, never discard

- **The burn becomes a pool (10-01).** The hourly backfill runs a rolling
  pool of annotation runs at full width until the weekly meter reaches 99%.
- **Sources can be wrong (10-01 to 10-04).** `tools/cross_validate.py`
  compares copies of a puzzle from several sources and lets a majority of
  three fix ours. Published answer keys turned out to have typos (MINISCULE
  for MINUSCULE, a T where both crossing clues need an R), so
  `tools/data/source_answer_wrong.json` records corrections, and from 10-04
  the annotator can file one itself with an `answerTypo` field when the
  wordplay plainly builds a real word one or two letters from a printed
  non-word. The validator refuses it if a crossing disagrees. Clue misprints
  and OCR misreads get the same treatment (`printedClue`, `setterError`).
- **Scans read by a vote (10-01 to 10-02).** Archive editions are read by
  several OCR engines and a vision-language model, and a clue is filed only
  when the readings agree or the VLM picks among them.
- **Answers that heal (10-03).** A model-solved answer the annotator cannot
  parse is *reopened*: blanked once and solved again, with the solver shown
  the answer that failed (`tools/reopen_answers.py`). A clue solved twice with
  no parse ships with its answer and no hint, without an alert.
- **Solve only when hinting (10-07).** Paul: "We shouldn't solve until we are
  hinting." A solved but unhinted puzzle is spend with nothing shipped, and
  splitting the solve and the hint into two conversations re-bought the
  reasoning. From then on one run solves the puzzle and annotates it in the same
  conversation, and both schedulers call the same per-puzzle worker
  (`tools/puzzle_worker.sh`).
- **Pacing modes (10-07).** The burn paces to the weekly reset by default, or
  to each five-hour window when Paul has resets to spend.
- **Blogs are read, not overwritten (10-09).** A puzzle with a solving blog's
  write-up takes its key from the blog; a model is refused there.
- **Never discard good work (10-08 to 10-12).** One clue failing validation
  used to throw away a run's other 28 hints. Since then every clue that
  validated is kept, only the failing entry goes back, a run cannot blank a committed hint,
  and before any discard the run's files are salvaged for two weeks
  (`tools/salvaged.sh`). Lost runs have even been rebuilt by replaying the
  writes in their session transcripts.
- **Doubt is an error (10-12).** Grading 120 model-solved puzzles against
  their later official keys found 6 wrong lights in 3,500, all on unchecked
  cells or cells two weak answers shared, and in one case the annotator had
  written "placeholder" and shipped. A hedged hint on a model answer became a
  validator error that reopens the answer.

The pattern across all of it: rules migrate out of prose and into code. A
sentence in a prompt is a request; a check in the validator is a guarantee,
and costs nothing on the runs that already comply.

## The shape of the system

```
 SOURCES                      FILING                    QUOTA-PACED CLAUDE RUNS
 publisher feeds ──┐
 solving blogs ────┼─> fetch / parse ──┐
 books, PDFs ──────┤                   ├─> cross-check ─> puzzles/<series>/<year>/<id>.json
 newspaper scans ──┴─> OCR vote ───────┘   (corroborate,       (source, solutions,
   (RapidOCR x2, Tesseract,                 cross_validate,     annotatedBy, entries)
    VLM pick)                               answer tables)              │
                                                                         v
                           daily tick (new arrivals) ──┐   annotation queue
                           hourly burn (backlog) ──────┴─> puzzle_worker.sh, one id
                                                                         │
                         ┌───────────────────────────────────────────────┘
                         v
          one `claude -p` run, sees only the VIEW_KEYS copy (no web if solving)
            1. if no answers: solve_packet -> fill -> apply_solution --check-only
            2. annotate -> tools/_ann_<id>.json -> annotate_check (loop until clean)
                         │
                         v
          worker re-applies fill from HEAD, re-validates, keeps what passed,
          reopens unparsed model answers once, salvages the rest
                         │
                         v
          "Annotate <id>" commit -> push -> static site hint ladder
                         │
          official key arrives later -> grade model fill -> wrong lights
          re-annotated, misses diagnosed (solve_misses)
```

### Getting the clues in

Puzzles arrive from publishers' feeds and archives, from solving blogs that
reproduce the clues with answers, from books and PDFs, and from scanned
newspaper pages. Every filer writes the same puzzle format, and
cross-checking happens at filing: a puzzle seen in more than one source is
compared field by field, and the corrections tables carry known misprints so
a refetch cannot revert them. How many puzzles each series has filed is on
the site's /progress/ page.

Scanned pages go through `tools/ocr_clues.py`. Each clue column is read by
several engines; `reconcile()` settles each word on the spelling the readings
share, then on a lexicon spelling, then on the word every reading's slips
point to, and files the clue blank when nothing wins. A blank clue's competing
readings are shown to a vision-language model, which picks one or transcribes
the clue itself. A final `suspect()` check refuses a puzzle with any clue no
reader could have meant. None of this uses Claude: the archive is read with
local models only.

**One home for text fixes.** A repair to clue, heading, preamble or count text
that undoes damage from the print, a scan, an OCR engine, a PDF or a page
encoding (letter-for-digit slips such as l/1 and O/0, dash, quote, ellipsis
and ligature normalisation, a number run into its word, see/run-on and count
repair) lives in `tools/clue_text.py` (or `quotes.py`, `dashes.py`,
`enumeration.py`), never in a paper's reader or fetcher, so a fix learned on
one source reaches them all. Per-source code keeps only what is the source's
own: page layout, finding the puzzle page, grid geometry, HTML parsing and URL
logic. `tools/test_ocr_text_central.py` enforces it in CI: it walks every
source-reading module (by name, or by importing an OCR, PDF or image library)
and fails on a `translate`/`maketrans`, a `sub`/`replace` on typographic marks,
a letter-for-digit regex class, or a single-character confusion table outside
the central modules. A hit that is not a text fix (a comparison key, a lookup
fold) goes in the test's `ALLOWED` list with a reason, one per function. The
test cannot see a digit-only repair under a plain name, so review a new `re.sub`
on clue text in a reader as a fix to move.

### Choosing what to hint

Two scheduled jobs annotate, and they split the quota deliberately (their
schedules and thresholds are generated into [NIGHTLY.md](NIGHTLY.md)):

- **The daily tick** (`tools/daily_update.sh`, on a short timer) annotates
  every new arrival, because a puzzle gets most of its visits in the week it
  is published. It runs only while the weekly and five-hour meters have
  headroom.
- **The burn** (`tools/prereset_backfill.sh`, hourly) spends everything
  else on the backlog. `tools/prereset_plan.py` sizes the pool so the weekly
  meter lands at its limit just as it resets, net of what interactive use
  spends, and waits out five-hour lockouts. It interleaves series
  round-robin, puts small series first (finishing a small series is more
  useful than another slice of the Times), and runs one lane of reprints
  last.

### The run

`tools/puzzle_worker.sh` gives one puzzle to one `claude -p` conversation
with `tools/annotate_prompt.md` as its system prompt, a tool list of Read,
Write, Edit and Bash, and a cap on turns. A run that must solve the puzzle
gets no web tools at all; a run explaining a published key may search the
web, to look up a name or a phrase. Neither reads the puzzle file directly:
each reads a *view* written
by `annotate_check.py --view`, which carries only the whitelisted
`annotate_check.VIEW_KEYS` (id, number, series, name, setter, dimensions,
preamble, unplaced clues, entries) plus a one-line-per-entry rendering of the
clues and answers. Everything about where the answers came from is withheld;
in particular a blog's URL, because a run that can see it fetches the blog
before trying a single clue. The blog's markings are disclosed only after the
run is stuck, as a "look again" prompt. A model-solved answer is marked
`(MODEL)` in the view so the annotator may correct it if its crossings agree.

If the puzzle has no answers, the same run first solves it from the clues and
crossing map that `tools/solve_packet.py` prints, iterating
`tools/apply_solution.py --check-only` until every entry is answered at the
right length and every crossing agrees, then grades each answer CONFIDENT,
LIKELY or GUESS. It then writes the fill in and annotates it.

Annotation is written to a JSON file a few clues at a time, so that a cut-off
run keeps what it wrote, and `tools/annotate_check.py` is run until it says
clean. Since 10-13 each clue is written in the model's shape: the definition
(`def`), the wordplay as one parse line (`wp`, `ins<in>([order]SORT, [Bird]TIT +
[Chinese]CH + [woman]W)`) and notes keyed by clue words; the checker translates it
(`annotation.from_model`, `tools/wordplay.py`) and refuses a parse whose letters
are not the answer, naming the step, so the clue type, link words, blocks and
assembly are never the model's to keep consistent (docs/PUZZLE_FORMAT.md). The
existing annotations it shows as context are rendered in the same notation.
That checker wraps the validator's checks and adds
repairs that are safe to apply mechanically (dropping a link word that
overlaps a definition, for example), each applied only if it clears the
check, adds nothing and is the unique best edit.

### After the run

The worker never trusts the run's working copy. It restores the puzzle from
the last commit, re-applies the fill through the applier, re-lands the
annotations through the checker, and keeps every clue that validated. A clue
the run left blank on a model answer is reopened once; a fill the applier
refuses is discarded and recorded in a ledger (`tools/failed_inputs.py`) so
the burn stops paying for it. The result is one "Annotate <id>" commit
holding both solve and hints, pushed on its own.

When the official key later lands for a model-solved puzzle, the key replaces
the model's answers, any clue the model got wrong loses its annotation and
goes back in the queue, and a separate unit diagnoses the miss.

### The site

The site is static. Each rung of the ladder is rendered from fields of the
annotation: indicators highlighted, then the definition, then the type, then
the blocks a piece at a time, then the walkthrough. The ladder asks before it
tells (tap the words you think are the definition and the rung is free if you
are right), so a rung must never do a later rung's work; that rule, too, is
enforced partly in the renderer and partly by validator checks. Puzzles not
yet annotated show hints marked up from a solving blog's write-up where one
exists, and only answers otherwise.

### Watching it

`tools/annotate_audit.py` runs daily over the burn's logs, ranks the
validator rules by how often a run's first check fails on them, and wakes an
agent with exactly one fix target: the rule costing the most retries. Fixes
usually take the form of a safe automatic repair or a hint in the check's
error message, not more prompt text. `tools/blog_compare.py` measures how
often our definitions, blocks and clue types disagree with the blogs that
cover the same puzzles.

## Shortcomings

**Quota is the bottleneck.** Everything is paced by a weekly subscription
meter, not by compute or by humans, so coverage grows only as fast as the
quota buys it while new puzzles keep arriving (the /progress/ page charts
both). The 10-12 cost analysis found a committed puzzle cost a median of
120,000 or so quota-weighted tokens, two thirds of it output, with roughly
40% of the annotation output being the model's thinking. Solving is
disproportionately expensive: in a five-day sample that October, solves were
a third of the spend for 7% of puzzles, and solves that never shipped were
15%.

**Blanks where the wordplay is not found.** A small share of clues in
annotated puzzles have no hint. They are clues the model could not parse
honestly, clues lost to OCR, or reopened model answers that
failed twice. The site shows the answer for those but cannot teach them.

**Validator-clean is not correct.** The checks catch inconsistency and
known failure shapes, not a plausible but wrong parse. In the 10-12 model
comparison, blind Opus judges reading 42 sampled clues found a wrong parse in
1 from the default configuration and 3 from the low-effort one, all of them
validator-clean. A run's first check often fails, mostly on letter accounting
(blocks that do not spell the answer, unmarked deletions), and the run then
fixes it, at a cost; the daily audit (below) ranks which rules cost most.

**Model solves can be wrong where nothing checks.** The 10-12 grading's 6
wrong lights in 3,500 is a low rate, but every one was on an unchecked cell or a cell two
weak answers shared, and some model-solved puzzles never get an official key
(books, scans, defunct series). Those answers are marked unofficial on the
site and stay unverified.

**OCR errors.** The vote files a clue blank rather than guess, so the
archive's error mode is mostly missing clues and editions held back rather
than wrong text; but a misread that every engine shares, and that the
lexicon accepts, gets through until the annotator notices that the wordplay
needs a different word. Editions read while the VLM host was down are re-read
when it returns.

**Source answer keys are not ground truth.** Publishers and blogs print
typos. The corrections are only found when the wordplay is read, so a puzzle
that is never annotated keeps its misprint.

**Difficulty has almost no ground truth.** Only the Times has an external
rating (the SNITCH, built from about a hundred reference solvers' times). The
difficulty index (`tools/difficulty.py`) is a fixed-weight combination of
features in the puzzle file, chosen by whether each beats the index without
it on held-out Times data. For every other series it is a transfer, not a
measurement.

**Hints that are right but do not teach.** An early reader said the hints
"didn't really help him learn how to solve": a correct walkthrough of one
clue is not a lesson in the general rule. Rungs were changed to state the
rule and link to the tutorial, but teaching quality is the hardest thing here to measure.

**Operational fragility.** The burn is a long-running shell pool with
worktrees, locks, a rebase every hour and re-exec on code change. Much of the
October history is fixes to it: runs that held pool slots after finishing,
a sync that drained the pool every hour, a nap that overslept a reset, a
new validator check that the running burn did not yet have. Each was fixed,
but the surface is large.

## Future work

- **Spend less per puzzle.** The 10-12 cost analysis ranked the levers:
  gate or salvage solves that cannot ship,
  trim the annotation JSON the model writes, and end the run the moment the
  check is clean. Lower reasoning effort was tested and rejected: 14% cheaper
  but blind judges preferred the default 34 to 8, mostly because its
  walkthroughs were thinner.
- **Keep turning lessons into checks.** Work down whatever the daily audit
  ranks top; on 10-12 that was letter accounting, with extra letters from
  unmarked deletions next.
- **Use the blogs harder.** Blog markings already serve as interim hints on
  unannotated puzzles and as a disagreement check; they could seed the
  annotation itself for the cheap series, leaving the model to write the
  teaching prose.
- **Grade the model against keys continuously.** Every model-solved puzzle
  that later gets a key is a free measurement of solve accuracy; extend that
  to a standing per-series accuracy report.
- **Better OCR for the oldest scans.** The 1970s and 1980s scans defeat clue
  layout; a stronger VLM pass over whole columns, or a grid read by image,
  would recover editions the vote holds back.
- **Measure teaching.** Blind solve packets (can a solver who reads only
  rung *n* get the answer?) exist for spot checks; making them a routine
  sample would put a number on the shortcoming above.
- **Difficulty from solvers.** The site's own anonymous solve data could, in
  time, give the non-Times series the ground truth the index lacks.
