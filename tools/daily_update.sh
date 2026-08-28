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
# Re-exec in a checkout of nobody else's — see tools/nightly_worktree.sh for the
# whole argument. Everything below can then assume one writer: what is modified
# here was modified by this run. There used to be a DIRTY_BEFORE snapshot
# subtracted from the final status to guess that instead, and guessing it is
# what let this job swallow a half-written feature on 2026-08-10.
. "$(dirname "$0")/nightly_worktree.sh"
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

# Keep this run's output where the exit trap can read it back, and report any
# failure line nobody wrote an alert for. launchd's .update.log holds every run
# ever, so "grep the log" would re-report last week; this is tonight only.
RUN_LOG="$(mktemp -t cryptic-daily)"
exec > >(tee -a "$RUN_LOG") 2>&1
trap 'sleep 1; alert_run_failures "$RUN_LOG"; rm -f "$RUN_LOG"' EXIT

echo "=== cryptic-teacher update $(date '+%Y-%m-%d %H:%M') ==="

# --- 1. fetch the latest puzzle of every series (exit 3 = nothing new, fine) ---
# Three fetchers, run independently on purpose: one source going down should
# not cost us the other two. Neither failing stops the run — there is usually
# a backlog worth annotating regardless.
fetch_broken=""
for fetcher in fetch_puzzle fetch_independent fetch_observer; do
  python3 "tools/$fetcher.py" --latest
  fetch_rc=$?
  if [ $fetch_rc -ne 0 ] && [ $fetch_rc -ne 3 ]; then
    echo "$fetcher fetch failed (rc=$fetch_rc); continuing"
    fetch_broken="$fetch_broken $fetcher"
  fi
done
# One paper down is weather. All three down at once is us: a changed user agent,
# no network, a python that no longer starts. Nothing new would arrive for as
# long as that lasted, and a site that quietly stops updating looks exactly like
# a site with nothing to update.
if [ "$(printf %s "$fetch_broken" | wc -w)" -ge 3 ]; then
  alert "every fetcher failed tonight ($fetch_broken) — no new puzzle can arrive from any paper until this is fixed. The rc lines are in .update.log."
fi

# --- 2. pick up solutions that have since been published (prize puzzles, and
#     every Everyman — its competition window withholds answers for about a
#     week, same shape of problem as the Guardian prize below it) ---
python3 tools/fetch_puzzle.py --refresh-unsolved
python3 tools/fetch_observer.py --refresh-unsolved

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
# A bulk import gets no special treatment: 68 backfilled Everymans simply queue
# by date like everything else and are worked newest to oldest (Paul, 2026-08-16,
# on a hold flag that briefly existed here: "no need to do anything special for
# the backfill"). The rate limit below is what stops a big import from being a
# big bill, and it already did that job.
ANNOTATE_MAX="${ANNOTATE_MAX:-3}"
pending=$(python3 - "$ANNOTATE_MAX" <<'EOF'
import json, sys
idx = json.load(open("puzzles/index.json"))
# IDs, not numbers: puzzles/<id>.js is what every step below names, so no
# consumer has to resolve a number two papers could share.
todo = sorted(((p.get("date") or 0, p["id"]) for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")), reverse=True)
print(" ".join(i for _, i in todo[:int(sys.argv[1])]))
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
todo = sorted(((p.get("date") or 0, p["id"]) for p in idx["puzzles"]
               if not p.get("hasSolutions")), reverse=True)
print(" ".join(i for _, i in todo[:int(sys.argv[1])]))
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
annotated_nums=""
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
    claude -p "Solve the cryptic crossword in puzzles/$num.js in this repo. Its answers have not been published, so there is no key: follow tools/solve_prompt.md exactly, write your fill to $fill, and iterate against 'python3 tools/apply_solution.py $num --fill $fill --check-only' until every crossing agrees. Do not write to puzzles/ — the calling script applies the fill." \
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
      if claude -p "Annotate the cryptic crossword in puzzles/$num.js in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Every clue needs a definitionFit, and every indicator needs an indicatorNotes entry saying why THAT word carries THAT instruction. Do not commit — the calling script commits." \
        --model "$ANNOTATE_MODEL" \
        --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
        --max-turns 80 2>&1 | tee "$run_log"
      then
        annotated_ok=$((annotated_ok + 1))
        annotated_nums="$annotated_nums $num"
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

# A run that could not solve some of the clues still exits 0, still commits, and
# still looks like a good night — see tools/check_annotation_loss.py. Ask.
if [ -n "$annotated_nums" ]; then
  loss=$(python3 tools/check_annotation_loss.py $annotated_nums 2>&1) || \
    alert "tonight's annotation came back short — $loss. Those clues ship with \"auto hints\" and no teaching ladder. If this keeps happening the model is failing to solve the puzzle, which is a quality problem, not a spend one."
  echo "$loss"
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
  # Tonight's annotation is gone and the inference that produced it is spent.
  # This branch used to exit 1 in silence, which is the same shape of failure as
  # the seven authentication days: the log knew, and nobody did.
  alert "annotation validation failed, so tonight's puzzle hints were thrown away and nothing published. The ERROR lines are in .update.log; re-run \`python3 tools/validate_annotations.py\` to see them."
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

# The solver's abbreviation glossary, republished from the clue-writer's copy.
# Before the stamp, because a rebuild changes the bytes the stamp is of.
python3 tools/build_abbreviations.py

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
  smoke_log="$(mktemp -t cryptic-smoke)"
  node tools/smoke_test.js 2>&1 | tee "$smoke_log"
  smoke_rc=${PIPESTATUS[0]}
  # A WARNING in a log is not a warning to anyone. This ran for weeks printing
  # failures nobody read, and on 2026-08-25 it printed three while committing
  # and pushing the tree that caused them. Exit 2 is "no hints yet", not a fail.
  if [ "$smoke_rc" -ne 0 ] && [ "$smoke_rc" -ne 2 ]; then
    alert "the app's smoke test is failing on the tree this job just committed: $(grep -m3 '^FAIL' "$smoke_log" | tr '\n' ' ')"
  fi
  rm -f "$smoke_log"
fi

if [ -n "$(git status --porcelain)" ]; then
  # Everything, because this tree contains nothing else: the run started at
  # origin/master in a worktree of its own, so whatever is modified or new here
  # was made by this run.
  #
  # Never name files here. A pathspec is a list of what a run is ALLOWED to
  # change, and no such list can be right: an annotation run may loosen the
  # validator, extend the app's vocabulary, or add a glossary entry that
  # regenerates three more files. Worse, git add aborts on a pathspec that
  # matches nothing, so deleting any file on the list stages NOTHING and the
  # whole day is silently lost.
  git add -A
  git commit -m "$(printf 'Daily update: fetch latest cryptic / annotate backlog\n\n%s' "$ANNOTATE_TRAILER")"
  # Nothing may be left behind. With one writer this is no longer a judgement
  # call about whose file it was: anything still showing here after `add -A` and
  # a commit is a bug, and it is work that will never reach the site. Read with
  # cut, not awk $2 — a rename prints two paths and a filename may contain a
  # space, and both of those used to come out as the wrong filename.
  left=$(git status --porcelain | cut -c4- | tr '\n' ' ')
  [ -n "$left" ] && alert "the daily update committed, and left these behind in its own worktree: $left"
  # Push only if a remote exists (GitHub Pages picks it up from master).
  # --autostash and a rebase first: the remote is routinely ahead of the mini
  # (interactive sessions push to it all day), and this used to be a bare push
  # swallowed by `|| true`, so a rejected push looked exactly like a successful
  # one and the day's puzzle quietly never reached the site.
  if git remote get-url origin >/dev/null 2>&1; then
    # HEAD is detached in this worktree, so master is named explicitly on both
    # sides. --autostash still earns its place: a rebase refuses outright with
    # anything unstaged, and the leftover check above reports that case rather
    # than preventing it.
    if git fetch -q origin master &&
       git rebase -q --autostash origin/master &&
       git push -q origin HEAD:master
    then
      # Pushed is not published. GitHub Pages builds afterwards, and a build that
      # fails leaves the site serving yesterday with a green git log in front of
      # it — "can you always hold off on telling me to reload until it is
      # deployed" applies to the machine saying it too.
      python3 tools/wait_for_deploy.py ||
        alert "tonight's update pushed, but the site never came back with it — GitHub Pages has not published the new build. Check https://github.com/ptarjan/cryptic-teacher/actions."
    else
      alert "the daily update committed today's puzzle but could not push it, so the site is still showing yesterday's. See the tail of .update.log."
    fi
  fi
else
  echo "nothing to commit"
fi
echo "=== done ==="
