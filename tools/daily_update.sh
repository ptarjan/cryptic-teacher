#!/bin/bash
# Daily updater for Cryptic Teacher — designed for a cron job on the Mac mini.
#
# What it does:
#   1. Fetches the newest puzzle of every series we follow — the Guardian daily
#      cryptic, the Monday Quiptic (their beginner tier), the Sunday Everyman
#      from the Observer, and the Independent's daily — if we don't have it yet.
#   2. Re-fetches puzzles whose solutions weren't published yet (Saturday prize
#      crosswords publish theirs about a week late).
#   3. Asks Claude Code (headless) to annotate the newest un-annotated puzzles,
#      following tools/annotate_prompt.md — ANNOTATE_MAX per run (default 3),
#      and only while the account's weekly usage window is under
#      ANNOTATE_MAX_WEEKLY_PCT (default 50). The Guardian publishes six puzzles
#      a week, so one per run never drains a backlog; it barely keeps up. Stops
#      early if a run fails (usually a session limit) rather than burning the
#      rest of the quota on doomed attempts.
#   4. Validates, reindexes, rebuilds the static crawlable pages
#      (tools/build_seo_pages.py — one per puzzle, plus the hub, the tutorial
#      and the sitemap), and commits (and pushes, if a remote is set up).
#
# Install: this runs as the LaunchAgent ~/Library/LaunchAgents/com.pt.cryptic-teacher.plist,
# NOT as a crontab entry, and must stay that way. The `claude` CLI keeps its
# OAuth credentials in the *login* keychain; cron runs outside the GUI login
# session, cannot unlock it, and every run dies with "Not logged in".
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pt.cryptic-teacher.plist
#   launchctl kickstart -k gui/$(id -u)/com.pt.cryptic-teacher   # run it now
#
# Requirements: python3, git, and the `claude` CLI on PATH for the annotation step.

set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
# cron runs with a bare PATH (/usr/bin:/bin), so the `claude` CLI in ~/.local/bin
# was invisible and every run silently skipped annotation. Keep this list in sync
# with wherever the CLI actually installs.
export PATH="$HOME/.local/bin:$HOME/.claude/local:/usr/local/bin:/opt/homebrew/bin:$PATH"
# The CLI keys its keychain item by CLAUDE_CONFIG_DIR: the entry is named
# "Claude Code-credentials-<first 8 of sha256(configdir)>", and with the variable
# unset it reads the legacy un-suffixed "Claude Code-credentials" instead. A
# file-based /login on 2026-07-31 wrote the suffixed entry and emptied the legacy
# one, so from then until 2026-08-06 every run of this script died on "Failed to
# authenticate: OAuth session expired and could not be refreshed" and annotated
# nothing for seven days — while interactive sessions and the Discord bridge
# (which sets this variable, see com.pt.discord-claude.plist) kept working, so
# nothing looked broken. Set it here rather than only in the plist: the failure
# is silent and non-obvious, and this way it survives being run by hand too.
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# alert() — puts a failure in Discord instead of only in this log. See alert.sh
# for why: the seven silent days above are what a log-only failure looks like.
. "$REPO/tools/alert.sh"

echo "=== cryptic-teacher update $(date '+%Y-%m-%d %H:%M') ==="

# --- 1. fetch the latest puzzle of every series (exit 3 = nothing new, fine) ---
# Two fetchers, run independently on purpose: the Guardian's site going down
# should not cost us the Independent's puzzle, and vice versa. Neither failing
# stops the run — there is usually a backlog worth annotating regardless.
for fetcher in fetch_puzzle fetch_independent; do
  python3 "tools/$fetcher.py" --latest
  fetch_rc=$?
  if [ $fetch_rc -ne 0 ] && [ $fetch_rc -ne 3 ]; then
    echo "$fetcher fetch failed (rc=$fetch_rc); continuing"
  fi
done

# --- 2. pick up solutions that have since been published (prize puzzles) ---
python3 tools/fetch_puzzle.py --refresh-unsolved

# --- 2b. refresh the Minute Cryptic reference corpus ---
# Their hint ladder is the same shape as ours and better written, so we keep a
# local copy of their 55 worked examples to write against; it also archives
# their daily clue, which is only ever available on the day. Costs two HTTP
# requests and no inference, and lands in gitignored tools/data/minutecryptic/,
# so it runs unconditionally and never blocks the puzzle work. Failures print
# and are ignored — a scrape of somebody else's bundle is expected to break the
# day they change it, and that is not a reason to hold back tonight's puzzle.
if command -v node >/dev/null 2>&1; then
  node tools/fetch_minutecryptic.js --quiet || echo "WARNING: minutecryptic capture failed"
fi

# --- 3. annotate the newest un-annotated puzzles, if any and if claude exists ---
# Newest-first, deliberately. Oldest-first looks tidier — the backlog drains in
# order — but it means today's puzzle is always the LAST one to get hints, so the
# top of the site (where people actually land) is permanently unannotated while
# the job grinds through last month. Newest-first costs nothing: the backlog
# still drains, just from the other end.
ANNOTATE_MAX="${ANNOTATE_MAX:-3}"
pending=$(python3 - "$ANNOTATE_MAX" <<'EOF'
import json, sys
idx = json.load(open("puzzles/index.json"))
todo = sorted((p["number"] for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")), reverse=True)
print(" ".join(str(n) for n in todo[:int(sys.argv[1])]))
EOF
)

# Annotation is the only thing here that spends inference, and a crossword
# backlog is never worth being rate-limited for real work. Skip it once the
# account's weekly window is more than ANNOTATE_MAX_WEEKLY_PCT spent; steps 1,
# 2 and 4 still run, so the newest puzzle is still fetched and published, just
# without hints until the window resets.
#
# If the usage check itself fails we annotate anyway, loudly. A silent gate
# that can never open is the exact failure this repo has already shipped twice
# (cron with no PATH to claude, oldest-first ordering): the backlog stops
# draining and nothing says so. Overspending is visible; not running isn't.
ANNOTATE_MAX_WEEKLY_PCT="${ANNOTATE_MAX_WEEKLY_PCT:-50}"
if [ -n "$pending" ]; then
  weekly=$(python3 tools/weekly_usage.py)
  if [ -z "$weekly" ]; then
    echo "WARNING: weekly usage unknown — annotating anyway (see error above)"
  elif [ "$weekly" -gt "$ANNOTATE_MAX_WEEKLY_PCT" ]; then
    echo "weekly usage ${weekly}% > ${ANNOTATE_MAX_WEEKLY_PCT}% — skipping annotation of $pending"
    pending=""
  else
    echo "weekly usage ${weekly}% (limit ${ANNOTATE_MAX_WEEKLY_PCT}%) — annotating $pending"
  fi
fi

if [ -n "$pending" ]; then
  if command -v claude >/dev/null 2>&1; then
    for num in $pending; do
      echo "annotating puzzle $num with Claude Code..."
      # Pinned, not inherited. This used to name no model and take whatever
      # ~/.claude/settings.json defaulted to, which meant a settings edit made
      # for an interactive session silently retuned the nightly job — it moved
      # from Fable to Opus that way on 2026-07-30 without anyone deciding to.
      claude -p "Annotate cryptic crossword No $num in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Do not commit — the calling script commits." \
        --model "${ANNOTATE_MODEL:-fable}" \
        --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
        --max-turns 80 || {
          alert "annotation of $num failed — no puzzle got hints today. Check the tail of .update.log; if it says \"Failed to authenticate\", the CLI needs a fresh /login (and CLAUDE_CONFIG_DIR must be set, see the note in daily_update.sh)."
          break
        }
    done
  else
    alert "claude CLI not on PATH ($PATH) — annotation of $pending skipped. The backlog will never drain until this is fixed."
  fi
fi

# --- 4. validate, reindex, commit ---
python3 tools/fetch_puzzle.py --reindex
if ! python3 tools/validate_annotations.py; then
  echo "VALIDATION FAILED — reverting today's puzzle-file changes"
  git checkout -- puzzles/
  exit 1
fi

# Rebuild the crawlable pages: one per puzzle, the archive hub, the tutorial and
# the sitemap. After validation, deliberately — these pages publish the
# annotations as plain text, so a run that produced a bad annotation should have
# already bailed out above rather than putting it in front of a search engine.
python3 tools/build_seo_pages.py

# Re-stamp index.html so phones don't serve yesterday's cached assets. After
# build_seo_pages.py, because that rewrites part of index.html and the stamp has
# to reflect the file as it finally stands.
python3 tools/stamp_assets.py

# And prove every page's asset URLs carry their content hash. An unstamped
# reference isn't a broken page — it looks perfect locally — it's a fix that
# never reaches anyone whose browser, or whose chat app's link unfurler, still
# holds the old bytes. That is precisely how a corrected social card went on
# showing an impossible grid, so it gets shouted about rather than logged.
python3 tools/stamp_assets.py --check ||
  alert "unstamped asset URLs are shipping — caches will keep serving the old file. See the UNSTAMPED lines in .update.log."

# Boot the app against tonight's data. Nothing else ever runs this, which is how
# it came to sit broken for weeks: it had hard-coded one puzzle's answers, so it
# started failing the day the app stopped booting on that puzzle and nobody was
# looking. Dead last, after the pages are built and stamped, so it tests the
# tree as it is about to be committed — run any earlier and it reports the
# stale ?v= stamps that stamp_assets.py is about to fix. Warn rather than exit:
# a smoke failure means the app mishandles the new puzzle, which is worth
# shouting about but isn't a reason to withhold the puzzle itself. Skipped
# (exit 2) just means tonight's puzzle has no hints yet.
if command -v node >/dev/null 2>&1; then
  node tools/smoke_test.js
  smoke_rc=$?
  [ $smoke_rc -ne 0 ] && [ $smoke_rc -ne 2 ] && echo "WARNING: smoke test failed (rc=$smoke_rc) — the app may be broken for today's puzzle"
fi

if [ -n "$(git status --porcelain)" ]; then
  # The validator goes in too. Annotation runs are allowed to loosen it when a
  # published clue turns out to be legal in a way it didn't know about (30045
  # 26A hides its answer backwards). Staging only puzzles/ pushed the puzzle and
  # left the loosening behind, so the committed tree failed its own validator.
  git add puzzles/ index.html learn/ sitemap.xml tools/validate_annotations.py
  git commit -m "$(printf 'Daily update: fetch latest cryptic / annotate backlog\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>')"
  # Push only if a remote exists (GitHub Pages picks it up from master).
  git remote get-url origin >/dev/null 2>&1 && git push origin HEAD || true
else
  echo "nothing to commit"
fi
echo "=== done ==="
