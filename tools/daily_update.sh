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
#      while the account's weekly usage window is under ANNOTATE_MAX_WEEKLY_PCT
#      (default 50) and its five-hour window is under ANNOTATE_MAX_SESSION_PCT
#      (default 70), re-read between puzzles. The Guardian publishes six puzzles
#      a week, so one per run never drains a backlog; it barely keeps up. Stops
#      early if a run fails rather than burning the rest of the quota on doomed
#      attempts.
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
# What was already dirty before this run touched anything. The leftover check at
# the end subtracts it: this checkout is shared with interactive sessions, and
# without the snapshot a half-written feature sitting in the working tree gets
# reported every night as "the daily update changed these files" — an alert that
# names innocent files, cannot be acted on, and trains you to ignore the one
# that matters (2026-08-10, mid-edit on the sync panel).
DIRTY_BEFORE="$(git status --porcelain --untracked-files=no | awk '{print $2}' | sort)"
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
#
# Newest by DATE, which the index carries, not by puzzle number. Sorting on the
# number silently means "Guardian dailies first, forever": every 30xxx outranks
# every quiptic 12xxx and every Everyman 4xxx no matter when it ran, so those
# two series could never reach the head of the queue while a single Guardian was
# pending — which is exactly what happened, all 16 quiptics unannotated
# including the day's own (found 2026-08-12). Number is only a tie-break, for
# the several series that publish on the same morning.
#
# `annotateHold` on an index entry keeps a puzzle off BOTH queues — no
# annotating and no cold-solving. Publishing a puzzle and spending inference on
# it are separate decisions, and until now they were the same one: a bulk import
# lands 59 puzzles that are newer than everything pending, they take the whole
# head of the queue by date, and the next morning the job quietly starts buying
# them (Paul, Everyman backfill, 2026-08-16: "for the backfill don't spend
# inference yet"). Import held, lift it when you mean to. tools/hold.py.
ANNOTATE_MAX="${ANNOTATE_MAX:-3}"
pending=$(python3 - "$ANNOTATE_MAX" <<'EOF'
import json, sys
idx = json.load(open("puzzles/index.json"))
todo = sorted(((p.get("date") or 0, p["number"]) for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")
               and not p.get("annotateHold")), reverse=True)
print(" ".join(str(n) for _, n in todo[:int(sys.argv[1])]))
EOF
)

# Puzzles the paper hasn't published answers for — Saturday prize crosswords,
# which withhold them for about a week. They used to be excluded from
# everything: no solutions means nothing for the annotator to explain, so the
# newest and most-visited puzzle on the site sat hintless for its whole first
# week and then took its turn at the back of a queue.
#
# So solve it instead. A model solves the grid cold, and tools/apply_solution.py
# writes it only if every entry is answered, every length fits and all ~58
# crossings agree — which is not proof, but is a check no accidental fill
# passes. The answers go in marked as ours (solutionSource), the site says so,
# the fetcher keeps re-checking every night, and when the official key lands the
# guess is graded against it and any entry we got wrong loses its annotation and
# gets rewritten. Being wrong is therefore recoverable and visible; the failure
# mode we refuse is being wrong and silent, which is why a fill that fails the
# check writes nothing at all.
#
# One a night by default. Solving cold costs far more inference than annotating
# a solved grid, and there is only ever one unsolved puzzle in the normal week.
SOLVE_MAX="${SOLVE_MAX:-1}"
unsolved=$(python3 - "$SOLVE_MAX" <<'EOF'
import json, sys
idx = json.load(open("puzzles/index.json"))
todo = sorted(((p.get("date") or 0, p["number"]) for p in idx["puzzles"]
               if not p.get("hasSolutions") and not p.get("annotateHold")), reverse=True)
print(" ".join(str(n) for _, n in todo[:int(sys.argv[1])]))
EOF
)

# Annotation is the only thing here that spends inference, and a crossword
# backlog is never worth being rate-limited for real work. Skip it once the
# account's weekly window is more than ANNOTATE_MAX_WEEKLY_PCT spent; steps 1,
# 2 and 4 still run, so the newest puzzle is still fetched and published, just
# without hints until the window resets.
#
# This gate used to fail OPEN — if it couldn't read the quota it annotated
# anyway and printed a warning — on the argument that overspending is visible
# while a stalled backlog isn't. That argument has now been tested twice and
# lost both times. From 2026-08-01 to 08-07 the read failed every night against
# a blanked keychain entry and the week ran to 68% with the gate wide open; on
# 08-08 it failed again, ran ungated at 82%, and the annotation died on a limit
# anyway — so fail-open didn't even buy the puzzle it was spending for.
#
# It fails CLOSED now, and the premise that made fail-open tempting is gone:
# a skipped night raises an alert into Discord, so "nothing says so" is no
# longer true. One day of backlog is recoverable; a week of someone's quota
# spent by a gate that had stopped gating is not.
#
# The verdict comes from weekly_usage.py rather than from arithmetic here,
# because "am I over the line" is answerable in cases where "what is the
# percentage" isn't: usage only rises within a window, so even a stale cached
# reading is a floor, and a floor above the limit is a decision. That is the
# case this gate actually met on 08-08 — it was holding a 10-hour-old 75%
# against a 50% limit and called itself blind.
ANNOTATE_MAX_WEEKLY_PCT="${ANNOTATE_MAX_WEEKLY_PCT:-50}"
# The annotating model, and the commit trailer derived FROM it rather than typed
# beside it. The trailer used to be a hardcoded "Claude Fable 5", which survived
# the 07-30 accidental switch to Opus and credited the wrong model in every
# commit for a week. One name, one place: change the model and the history
# follows.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
. "$REPO/tools/annotate_model.sh"
if [ -n "$pending$unsolved" ] && ! python3 tools/weekly_usage.py --self-test; then
  # The gate's own four cases, run offline before its verdict is believed. A
  # gate whose logic is broken says "spend" as confidently as a working one, so
  # a failing self-test is treated as the worst verdict rather than ignored.
  alert "the weekly usage gate is failing its own self-test, so annotation was skipped. The gate logic itself is wrong — see the SELF-TEST lines in .update.log."
  pending=""
  unsolved=""
fi
if [ -n "$pending$unsolved" ]; then
  case "$(python3 tools/weekly_usage.py --gate "$ANNOTATE_MAX_WEEKLY_PCT")" in
    spend)
      echo "weekly usage under ${ANNOTATE_MAX_WEEKLY_PCT}% — annotating $pending${unsolved:+, solving $unsolved}" ;;
    skip)
      echo "weekly usage over ${ANNOTATE_MAX_WEEKLY_PCT}% — skipping annotation of $pending${unsolved:+ and solving of $unsolved}"
      pending=""
      unsolved="" ;;
    *)
      alert "the weekly usage gate can't read the quota, so tonight's annotation was skipped rather than run ungated. Nothing is broken on the site — the newest puzzle still published, just without hints. See the \"cannot read weekly usage\" line in .update.log."
      pending=""
      unsolved="" ;;
  esac
fi

# The five-hour window is the one this loop actually spends, so it is re-read
# before every puzzle. Checking it once up front is worthless — it reads near
# zero at 06:15 by construction — and that is why runs kept annotating two
# puzzles and then dying on the third with "you've hit your limit", which is a
# quota being discovered by crashing into it rather than being budgeted.
ANNOTATE_MAX_SESSION_PCT="${ANNOTATE_MAX_SESSION_PCT:-70}"
annotated_ok=0
stop_reason=""

# --- 3a. solve the unsolved, so step 3b has something to annotate ---
# Runs before the annotation loop and feeds it: a grid solved tonight joins the
# front of tonight's queue, because it is by definition the newest puzzle and
# the one people are actually looking at. Same session gate as annotation, and
# the same trailer, since it is the same model spending the same quota.
solved_ok=0
if [ -n "$unsolved" ] && command -v claude >/dev/null 2>&1; then
  for num in $unsolved; do
    session=$(python3 tools/weekly_usage.py --group session)
    if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
      stop_reason="five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — solving $num waits for the reset"
      break
    fi
    fill="${TMPDIR:-/tmp}/cryptic-fill-$num.json"
    rm -f "$fill"
    echo "solving puzzle $num cold with Claude Code... (session ${session:-unknown}%)"
    claude -p "Solve cryptic crossword No $num in this repo. Its answers have not been published, so there is no key: follow tools/solve_prompt.md exactly, write your fill to $fill, and iterate against 'python3 tools/apply_solution.py $num --fill $fill --check-only' until every crossing agrees. Do not write to puzzles/ — the calling script applies the fill." \
      --model "$ANNOTATE_MODEL" \
      --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
      --max-turns 120 2>&1 | tail -40
    # The verdict comes from the checker, not from the model's own report. A
    # run can exit 0 having given up, and did — the check is what decides.
    if [ -s "$fill" ] && python3 tools/apply_solution.py "$num" --fill "$fill" --model "$ANNOTATE_MODEL"; then
      solved_ok=$((solved_ok + 1))
      pending="$num $pending"
    else
      echo "solve of $num rejected — nothing written, the paper's answers are due in a few days anyway"
    fi
    rm -f "$fill"
  done
  # Whatever solving cost, the annotation budget is still ANNOTATE_MAX puzzles.
  pending=$(echo $pending | tr ' ' '\n' | grep -v '^$' | head -"$ANNOTATE_MAX" | tr '\n' ' ')
fi

if [ -n "$pending" ]; then
  if command -v claude >/dev/null 2>&1; then
    run_log="$(mktemp -t cryptic-annotate)"
    for num in $pending; do
      session=$(python3 tools/weekly_usage.py --group session)
      if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
        stop_reason="five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — $num waits for the reset"
        break
      fi
      echo "annotating puzzle $num with Claude Code... (session ${session:-unknown}%)"
      # Pinned, not inherited. This used to name no model and take whatever
      # ~/.claude/settings.json defaulted to, which meant a settings edit made
      # for an interactive session silently retuned the nightly job — it moved
      # from Fable to Opus that way on 2026-07-30 without anyone deciding to.
      # Opus on purpose since 2026-08-09: benchmarked head-to-head against Fable
      # on 30078 (see STYLE.md), it matched — 23/25 types, 22/25 definitions,
      # zero cryptic definitions, both hard clues solved — in the same wall time
      # for a third of the cost, because the bill is nearly all output tokens.
      if claude -p "Annotate cryptic crossword No $num in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Do not commit — the calling script commits." \
        --model "$ANNOTATE_MODEL" \
        --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
        --max-turns 80 2>&1 | tee "$run_log"
      then
        annotated_ok=$((annotated_ok + 1))
      else
        # The CLI says why it stopped on its last line — a spend limit, an
        # expired login, a network failure. Carrying that sentence into the
        # alert is the difference between "go and read a 270k-line log" and
        # knowing whether this needs a /login or just needs tomorrow.
        stop_reason="$num failed: $(grep -v '^[[:space:]]*$' "$run_log" | tail -1 | cut -c1-200)"
        break
      fi
    done
    rm -f "$run_log"
  else
    stop_reason="claude CLI not on PATH ($PATH)"
  fi
fi

# Alert on the backlog not moving, not on a command exiting non-zero. A run that
# annotates two puzzles and then meets a rate limit has done its job; a run that
# annotates none has silently stalled, which is this repo's signature failure —
# it shipped that three times (no PATH to claude, oldest-first ordering, a gate
# reading a blanked keychain entry) and each time the log knew and nobody did.
if [ -n "$stop_reason" ]; then
  if [ "$annotated_ok" -eq 0 ]; then
    alert "no puzzle got hints today — $stop_reason. If that mentions authentication the CLI needs a fresh /login; see the CLAUDE_CONFIG_DIR note in daily_update.sh. Full output: .update.log."
  else
    echo "annotated $annotated_ok puzzle(s), then stopped: $stop_reason"
  fi
fi

# --- 4. validate, reindex, commit ---
python3 tools/fetch_puzzle.py --reindex
if ! python3 tools/validate_annotations.py; then
  echo "VALIDATION FAILED — reverting today's puzzle-file changes"
  git checkout -- puzzles/
  exit 1
fi

# Draw the social cards for any puzzle whose annotation landed tonight. Before
# build_seo_pages.py, which points each page at its own card only if the file is
# already on disk — a page built first would advertise the site card for a day
# and then quietly change its mind. Only redraws what changed, so this is one
# Chrome launch on most nights and none at all on a night with no annotation.
bash tools/make_og.sh --all

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
  # By pathspec, never `git add -A`: an interactive session shares this checkout
  # and a bare commit swallows its half-finished work. But the list has to cover
  # everything an annotation run is ALLOWED to change, and twice it hasn't:
  #   - tools/validate_annotations.py, which a run may loosen when a published
  #     clue turns out to be legal in a way it didn't know about (30045 26A
  #     hides its answer backwards). Committed the puzzle, left the loosening,
  #     and the committed tree then failed its own validator.
  #   - app.js and STYLE.md, which a run must edit when a clue needs a wordplay
  #     type the vocabulary doesn't have yet. On 2026-08-07 puzzle 30079 brought
  #     in `cycling` and `substitution`; the puzzle shipped and app.js did not,
  #     so the live site had two clues whose type matched no family and no
  #     blurb. The validator passed — it validates puzzles, not the app.
  git add puzzles/ index.html learn/ sitemap.xml app.js STYLE.md og.png og/ tools/validate_annotations.py
  # Then put back anything that was already modified before this run started.
  # The pathspec is not enough on its own: app.js and index.html are on it
  # because an annotation run legitimately edits them, and they are also exactly
  # what an interactive session has open. On 2026-08-10 this job swallowed a
  # half-written sync feature into "Daily update: fetch latest cryptic" — the
  # work survived, but it landed in the wrong commit with the wrong message,
  # and it could as easily have been committed broken.
  printf '%s\n' "$DIRTY_BEFORE" | while read -r f; do
    [ -n "$f" ] && git restore --staged -- "$f" 2>/dev/null
  done
  git commit -m "$(printf 'Daily update: fetch latest cryptic / annotate backlog\n\n%s' "$ANNOTATE_TRAILER")"
  # And name whatever is STILL modified. Both misses above were a file nobody
  # had thought of, and no amount of thinking harder about the list fixes the
  # third one; only noticing that something was left behind does. Untracked
  # files are excluded — scratch files are normal here — but a tracked file the
  # job modified and did not commit is work that will never reach the site.
  left=$(comm -23 <(git status --porcelain --untracked-files=no | awk '{print $2}' | sort) \
                  <(printf '%s\n' "$DIRTY_BEFORE") | tr '\n' ' ')
  [ -n "$left" ] && alert "the daily update changed these files and committed none of them: $left. Add them to the git add pathspec in daily_update.sh, or revert them."
  # Push only if a remote exists (GitHub Pages picks it up from master).
  # --autostash and a rebase first: the remote is routinely ahead of the mini
  # (interactive sessions push to it all day), and this used to be a bare push
  # swallowed by `|| true`, so a rejected push looked exactly like a successful
  # one and the day's puzzle quietly never reached the site.
  if git remote get-url origin >/dev/null 2>&1; then
    git pull --rebase --autostash -q && git push -q origin HEAD ||
      alert "the daily update committed today's puzzle but could not push it, so the site is still showing yesterday's. See the tail of .update.log."
  fi
else
  echo "nothing to commit"
fi
echo "=== done ==="
