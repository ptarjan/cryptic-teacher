# Cryptic Teacher

A static, no-framework web app that teaches you to solve cryptic crosswords using real
broadsheet puzzles — the Guardian's cryptic and Quiptic, the Independent's daily, and
the Observer's Everyman — with an escalating **hint ladder per clue** instead of a bare
answer key. Each hint level teaches the next solving skill:

1. **Clue type** — anagram? charade? container? hidden word? …
2. **Definition** — the definition part of the clue is highlighted.
3. **Indicators** — the anagram/container/reversal/homophone signal words are highlighted.
4. **Building blocks** — the fodder and synonym breakdown ("host = ARMY; part of TV duo = ANT").
5. **Full walkthrough** — step-by-step assembly of the answer.
6. **Fill in answer** — writes the solution into the grid.

A separate "reveal one letter" escape hatch is available at any hint level (it doesn't
advance the ladder, but it does count against your score).

There are also check buttons (letter / entry / grid) that mark wrong letters without
revealing, a gentle score (clues solved with no hints, hint levels used), a collapsible
"How cryptic clues work" tutorial, and a puzzle picker. Progress is saved in
localStorage per puzzle.

**Flagship puzzles** — Guardian Cryptic **No 30,066 (Tramp)** and **No 30,067 (Imogen)**
are fully hand-annotated (every clue, all six hint levels, machine-validated). The other
bundled puzzles are un-annotated backlog: they show an <em>auto hints</em> badge and
degrade gracefully (checking and letter reveals still work; the teaching ladder appears
once a puzzle is annotated).

## Run it

No build step, no backend. Either:

- open `index.html` directly in a browser (works from `file://`), or
- `python3 -m http.server 8017` in the repo root and visit <http://localhost:8017/>, or
- host the repo as-is on GitHub Pages (all paths are relative; `.nojekyll` included).

## Repository layout

```
index.html, style.css, app.js   the app (vanilla HTML/CSS/JS)
tutorial.js                     the "How cryptic clues work" content
puzzles/index.json              manifest: one row per puzzle (latest first)
puzzles/index.js                the same manifest as a script (so file:// works)
puzzles/<number>.js             one puzzle per file, JSON between /*JSON-START*/ ... /*JSON-END*/
tools/fetch_puzzle.py           fetch/convert Guardian puzzles, --latest/--backfill/--reindex
tools/validate_annotations.py   proves every annotation actually spells its answer
tools/annotate_prompt.md        the prompt the daily Claude Code job follows to annotate
tools/daily_update.sh           daily script: fetch latest, annotate backlog, validate, commit
tools/com.pt.cryptic-teacher.plist  LaunchAgent that runs daily_update.sh at 06:15
```

## Puzzle file format

`puzzles/<number>.js` assigns one JSON object to `window.CRYPTIC_PUZZLES["<number>"]`.
The JSON sits between `/*JSON-START*/` and `/*JSON-END*/` markers so the Python tools can
read and rewrite it. Shape:

```jsonc
{
  "id": "30066", "number": 30066, "name": "Cryptic crossword No 30,066",
  "setter": "Tramp", "date": 1784764800000, "dimensions": {"rows": 15, "cols": 15},
  "sourceUrl": "https://www.theguardian.com/crosswords/cryptic/30066",
  "entries": [
    {
      "id": "16-across", "number": 16, "direction": "across",
      "position": {"x": 0, "y": 8}, "length": 10,
      "clue": "Destroying climate, sun reaches highest point (10)",
      "group": ["16-across"], "separatorLocations": {},
      "solution": "CULMINATES",
      "annotation": {
        "type": "anagram",
        "answer": "CULMINATES",
        "definition": "reaches highest point",
        "indicators": ["Destroying"],
        "anagram": {"fodder": "CLIMATE SUN"},
        "blocks": [{"clueFragment": "climate, sun", "gives": "CLIMATESUN", "note": "anagram fodder"}],
        "walkthrough": "…2-4 friendly sentences…"
      }
    }
  ]
}
```

Annotation rules (enforced by `tools/validate_annotations.py`):

- `definition` / `definition2` / each `indicators[]` string must occur **verbatim** in the
  clue text (Guardian clues use `’` and `–`).
- `answer` letters must equal the grid solution (for linked clues, the whole group).
- Letter mechanics must be machine-checkable: `anagram.fodder` must be a multiset match
  for the answer; `pieces` must concatenate to it; `subAnagrams`/`subReversals` verify
  embedded steps; hidden answers must occur inside the clue's letters.
- Linked entries: full annotation on the group's first entry with `"coversGroup": true`;
  the others get `{"linkedTo": "<first-id>"}`.
- Un-annotated entries keep `"annotation": null` — the app then offers auto hints only.

## Adding puzzles

```
python3 tools/fetch_puzzle.py 30123     # one puzzle
python3 tools/fetch_puzzle.py --latest  # newest cryptic (no-op if already present)
python3 tools/fetch_puzzle.py --backfill 30   # the last 30, skipping ones you have
```

Then annotate the new `puzzles/<n>.js` by hand or with Claude Code using
`tools/annotate_prompt.md`, and check your work:

```
python3 tools/validate_annotations.py 30123
python3 tools/fetch_puzzle.py --reindex
```

### Automated daily updates

`tools/daily_update.sh` runs once a day on a machine with the `claude` CLI: it fetches
the newest puzzle, re-fetches any puzzle still waiting on published solutions, has Claude
annotate the oldest un-annotated ones (`ANNOTATE_MAX` per run, default 3 — the tracked
series publish about fourteen puzzles a week between them, so one a day would never
catch up), validates, reindexes, commits, and pushes if a remote is configured.

The Guardian runs a cryptic Monday–Saturday, with Saturday's appearing as the *Prize*
crossword under a different URL; the fetcher watches both series. Prize solutions are
withheld for about a week, so those puzzles sit un-annotatable until
`--refresh-unsolved` picks up their answers.

**On macOS, schedule it with the bundled LaunchAgent — not with cron.** The `claude`
CLI stores its OAuth credentials in the macOS *login* keychain (item
`Claude Code-credentials`). `cron` runs outside the GUI login session and cannot unlock
that keychain, so every cron run dies with `Not logged in · Please run /login` and the
backlog never drains. A per-user LaunchAgent bootstrapped into `gui/<uid>` runs inside
the login session and authenticates fine. (Related trap: cron's bare `PATH` also hides
`~/.local/bin/claude`; the script and the plist both set an explicit `PATH`.)

```
cp tools/com.pt.cryptic-teacher.plist ~/Library/LaunchAgents/
# edit the absolute paths inside if your checkout is not at /Users/pt/github/cryptic-teacher
launchctl bootout  gui/$(id -u)/com.pt.cryptic-teacher 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pt.cryptic-teacher.plist
launchctl print    gui/$(id -u)/com.pt.cryptic-teacher | head   # verify

launchctl kickstart -k gui/$(id -u)/com.pt.cryptic-teacher      # run it now, to test
tail -f .update.log                                             # ~5-15 min per puzzle
```

Output (stdout and stderr) lands in `.update.log`, which is untracked on purpose.
On non-macOS hosts, where credentials live in `~/.claude/.credentials.json` rather than
a keychain, a plain cron entry is fine:

```
15 6 * * * /path/to/cryptic-teacher/tools/daily_update.sh >> /path/to/cryptic-teacher/.update.log 2>&1
```

## Credits

Puzzle grids and clues remain the copyright of their publishers — Guardian News &
Media (the Guardian's cryptic and Quiptic, and the Observer's Everyman as syndicated
there) and Independent Digital News & Media — and are fetched from their own sites for
personal study. All annotations, hints and tutorial content are original to this
project. Not affiliated with any of them.
