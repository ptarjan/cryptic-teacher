# Adding puzzles

## Running the site

There is one build step. The puzzle list the app opens with, and the script
form of each puzzle, are generated from the committed puzzle files and are not
committed. After a fresh clone, build them once. It takes about ten seconds:

```
python3 tools/fetch_puzzle.py --reindex
```

This writes `puzzles/index.json`, `puzzles/index.js`, and one
`puzzles/<series>-<n>.js` per puzzle. It leaves `index.html` alone: the
`?v=` hashes are stamped by the deploy workflow (see "Cache busting" in
`APP.md`).

Then do one of these:

- Open `index.html` directly in a browser. It works from `file://`.
- Run `python3 -m http.server 8017` in the repo root and visit
  <http://localhost:8017/>.
- Host on GitHub Pages. `.github/workflows/pages.yml` runs the same reindex
  command on its own checkout before it builds, so there is nothing to commit.
  All paths are relative and `.nojekyll` is included.

Re-run the reindex after fetching or annotating anything, if you want to see it
in the browser. The tools rebuild the index themselves before reading it:
`tools/smoke_test.js`, `tools/test_push_hold.js`, `tools/puzzle_integrity.py`
and `tools/build_readme.py` all do.

## Fetching and annotating

For the Guardian series:

```
python3 tools/fetch_puzzle.py 30123           # one puzzle
python3 tools/fetch_puzzle.py --latest        # newest of every Guardian series (no-op if already present)
python3 tools/fetch_puzzle.py --backfill 30   # the last 30, skipping ones you have
```

Other papers have their own `tools/fetch_*.py` scripts, listed in
`docs/LAYOUT.md`.

Then annotate the new puzzle file (`python3 tools/puzzle_paths.py cryptic-30123`
its path), by hand or with Claude Code
using `tools/annotate_prompt.md`, and check it:

```
python3 tools/validate_annotations.py 30123
python3 tools/fetch_puzzle.py --reindex
```


## Checking your work

```
python3 tools/build_seo_pages.py        # the crawlable pages (generated, not committed)
node tools/smoke_test.js                # the app, driven headless against a sample of the corpus
python3 tools/validate_annotations.py   # no argument: every puzzle
python3 tools/build_readme.py --check   # the generated regions of the docs still describe this repo
```

The smoke test reads `/learn/` and `/abbreviations/` the way a visitor gets
them, so build those pages first (about half a minute). The smoke test tells
you if they are missing.

If you edit `style.css`, `app.js` or a puzzle file, rebuild and restamp the
static pages. Otherwise the suite fails on hundreds of stale `?v=` references:

```
python3 tools/build_seo_pages.py && python3 tools/stamp_assets.py
bash tools/make_og.sh --all         # only redraws cards whose page would come out different
```

`tools/smoke_test.js` is the most important check. It runs the real `app.js`
against a fake DOM and the real puzzle files, so bad data fails it as readily
as bad code. For example: a rung that gives the answer away early, a
highlight that does not sit where the annotation says, or a sound clue that
never prints what it sounds like. **Assertions match the markup the app
emits, never an English phrase.** Annotation prose is written by a model and
will eventually contain any sentence you might use as a signal.

CI runs it over the whole corpus on every push, in slices, through a
per-puzzle result cache (`tools/ci_cache.js`). A result stands while the
puzzle file and the files the smoke test reaches (`SMOKE_DEPS`, guarded by
`tools/test_ci_cache_deps.js`) are both unchanged, so a push that only adds
puzzles or edits docs re-runs just the new puzzles, and a change to the app,
the page build or the data re-runs everything.
`.github/workflows/nightly-smoke.yml` sweeps the corpus again each night
with no cache, for anything the cache could hide.

## Generated regions of the docs

`tools/build_readme.py` generates two regions of `README.md` (the hint
ladder and the corpus paragraph), one of `docs/NIGHTLY.md` (the scheduling
defaults) and the file table in `docs/LAYOUT.md`. Each region sits between `<!-- NAME-START -->` and
`<!-- NAME-END -->` markers. The sources are the puzzle files, `app.js`,
`git ls-files` and the shell scripts.

- **Do not hand-edit inside the markers.**
- `python3 tools/build_readme.py` rewrites the regions.
  `python3 tools/build_readme.py --check` exits 1 if they are out of date.
- The check fails instead of leaving a wrong sentence. That happens when a tool
  has no description line, a described tool has been deleted, a new series has
  no display name, or a quoted default has been renamed. A rung renamed in
  `app.js` renames itself in the README.
- Each region has one builder function in `tools/build_readme.py`:
  `build_corpus()` counts the puzzle files for the corpus paragraph,
  `build_ladder()` reads `LABELS` in `app.js` for the rung list, and
  `build_knobs()` parses the defaults out of the shell scripts (`KNOB_FILES`).
  `build_layout()` writes the table in `docs/LAYOUT.md` from `LAYOUT`.
- To put a number in the prose, add it to the builder in
  `tools/build_readme.py`. A number typed by hand is never checked again.
