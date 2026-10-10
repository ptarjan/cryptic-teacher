#!/bin/bash
# The nightly for Cryptic Teacher, as a queue of small units (tools/unit_queue.py).
#
#     tools/daily_update.sh                     # a tick: start every due unit, detached; returns in seconds
#     tools/daily_update.sh unit <key> [args]   # one unit, in a tree of its own (what a tick starts)
#     python3 tools/unit_queue.py status daily  # what ran, how it ended, what runs now
#     UNIT_QUEUE_DRY=1 tools/daily_update.sh    # a tick that says what it would start, and starts nothing
#
# The scheduler fires a tick every ten minutes. A tick chooses the puzzles to
# annotate (below, under the usage gates) and hands them with the phases'
# cadences to tools/daily_units.py, which says what is due; each due unit is
# then started as a process of its own, with its own lock, time limit, ledger
# row and worktree. One slow phase holds up only itself, a failed unit is
# retried on its own, and a puzzle that appears at 06:10 is fetched by 07:10
# and annotated at the tick after that, rather than at the next 04:45.
#
# The units (keys; cadences and limits in tools/daily_units.py):
#   fetch:<fetcher>    the newest puzzle of each series we follow — the
#                      Guardian daily cryptic, the Monday Quiptic, the Sunday
#                      Everyman, the Independent's daily, Cyclops, the Globe
#                      and Mail, Metro — if we don't have it yet.
#   blog:times, blog:telegraph, bucket:telegraph, xval:globe
#                      the Times and the Telegraph, rebuilt from the blogs
#                      that solve them, the Telegraph's own bucket, and the
#                      Globe's copies of the Times Quick Cryptic.
#   ft, azed           the FT from fifteensquared, Azed from the Guardian's
#                      printable copies. These and bucket:telegraph are
#                      backfills: one that stops with backlog left runs
#                      again at the next tick until it is drained.
#   blog-facts         the blog caches re-read into the site's blog hints,
#                      tools/data/blog_facts/, after any blog fetch.
#   ratings, checks    the SNITCH and comment ratings and the measures built
#                      over the day's answers; a series gone quiet, a corpus
#                      defect.
#   solutions          puzzles whose solutions weren't published yet (Saturday
#                      prize crosswords publish theirs about a week late), and
#                      the grade of our own fills against a key that lands.
#   minute             the Minute Cryptic reference corpus.
#   miss:<id>:<entry>  one graded miss, diagnosed by the headless model before
#                      any cold solve starts.
#   annotate:<id>      one puzzle annotated by Claude Code (headless),
#                      following tools/annotate_prompt.md; one with no key is
#                      solved cold first in the same run (tools/puzzle_worker.sh).
#                      Every new arrival — dated within the last two days, or
#                      given its official key since — however many there are;
#                      ANNOTATE_MAX (default 3) a day bounds only the rest:
#                      answerless puzzles plus the older backlog.
#                      All of it only while the account's weekly usage window is
#                      under ANNOTATE_MAX_WEEKLY_PCT (default 90) and its
#                      five-hour window under ANNOTATE_MAX_SESSION_PCT (default
#                      90), read at every tick and again as each unit starts.
#                      An annotation that fails the way that says nothing about
#                      the puzzle (the CLI's own failure) holds every
#                      annotation back ANNOTATE_PAUSE; one the wall-clock cap
#                      kills is lost on its own, and the queue carries on.
#                      A puzzle that fails, or whose annotation the validator
#                      throws away, is recorded with a hash of its inputs
#                      (tools/failed_inputs.py) and left out of the queue until
#                      those inputs change.
#   reports            the bad-hint queue solvers write to from the site,
#                      handed to the same headless model to fix; a person is
#                      alerted only about the ones it could not close.
# Every unit commits and pushes what it changed itself (unit_commit); an
# annotation is validated, committed and pushed by tools/puzzle_worker.sh, the
# same code the burn (tools/prereset_backfill.sh) runs. The site is built,
# tested and deployed by .github/workflows/ on that push.
#
# Only work driven by new inputs runs here: new puzzles, posts, keys,
# ratings and reports. A pass over the whole corpus that only a code change
# could alter (a better scan reader, a stricter validator) is run once by
# whoever changes the code, or by CI on the push that carries the change.
#
# Install: household-plugins/cryptic-daily/plugin.toml schedules the tick in
# the bridge container. That is the only schedule this job has, and a second
# one is not a fallback — two copies annotate the same backlog out of the same
# weekly quota. The container works because the credential is a file under
# CLAUDE_CONFIG_DIR. On a Mac it does not: there the `claude` CLI reads the
# *login* keychain, which cron cannot unlock, and every run dies with "Not
# logged in" — so scheduling this on a Mac means launchctl, and means removing
# the plugin rather than adding to it.
#
# Requirements: python3, git, and the `claude` CLI on PATH for the annotation step.

set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
# Re-exec in a checkout of nobody else's — see tools/nightly_worktree.sh for the
# whole argument. Everything below can then assume one writer: what is modified
# here was modified by this run.
# A tick runs in the tree daily_update; a unit in one of tools/daily_units.py's
# trees, daily_unit-1 .. -SLOTS, leased to it by tools/unit_queue.py (CT_JOB).
# A dropped unit's commits are pushed by the next unit to take its tree; its
# uncommitted annotation is not, since it is validated against that unit's
# HEAD and may be one it was rejecting.
# A tick rebuilds only the index, itself, below (CT_GENERATED=none): it reads
# nothing else generated, and every tick finds HEAD moved.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
[ $# -eq 0 ] && CT_GENERATED=none
# A unit gets them at start only if its kind reads them (daily_units.py
# GENERATED); an unknown kind gets them.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
[ "${1:-}" = unit ] && [ "$(python3 tools/daily_units.py generated "${2:-}")" = none ] && CT_GENERATED=none
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_SALVAGE_PATHS=""
. "$(dirname "$0")/nightly_worktree.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
# A scheduler runs with a bare PATH (/usr/bin:/bin), so the `claude` CLI is
# invisible and every run silently skips annotation.
. "$REPO/tools/claude_path.sh"
# The CLI keys its keychain item by CLAUDE_CONFIG_DIR: the entry is named
# "Claude Code-credentials-<first 8 of sha256(configdir)>", and with the variable
# unset it reads the legacy un-suffixed "Claude Code-credentials" instead. A
# file-based /login writes the suffixed entry and empties the legacy one, and
# then every run of this script dies on "Failed to authenticate: OAuth session
# expired and could not be refreshed" and annotates nothing — while interactive
# sessions and the Discord bridge (which sets this variable) keep working, so
# nothing looks broken. Set it here rather than only in the scheduler's
# environment: the failure is silent and non-obvious, and this way it survives
# being run by hand too.
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# The failure both of these were written for: thinking bills as output, and a
# turn that reasons past the output ceiling emits no tool call, makes no
# progress, and is retried verbatim until the run dies — so it can spend a whole
# puzzle's budget on nothing, and --max-turns never sees it, because a turn that
# calls no tool is not a turn as far as that limit is concerned.
# Measured over 10,823 turns (2026-08-23..09-06), grouped by the API's message
# id: 554 turns spent 8k-32k output tokens and every one of them ended in a tool
# call, and of the 101 above 32k, 91 did too. Big turns are working turns. Count
# by message id, not by line: the CLI writes one line per content block and
# stamps each with the whole turn's usage.
#
# MAX_THINKING_TOKENS DOES NOT CAP ANYTHING ON THIS MODEL. The CLI checks the
# model's adaptive_thinking capability before it reads this variable, and for
# claude-opus-5 it sends {type:"adaptive"} with no budget_tokens at all. The
# number here is ignored; only the value 0 still does something, and that turns
# thinking off entirely. Measured on the two Independent runs that died on
# 2026-09-11 and 09-12: usage.output_tokens_details.thinking_tokens reached
# 127,997-128,000 on nine separate turns while this said 31,999. It is left set
# because a future model without that capability would honour it, and because
# unsetting it reads as a decision that thinking need not be bounded.
# What actually bounds a runaway here is the wall clock — ANNOTATE_MAX_MINUTES,
# below — and what explains one afterwards is tools/annotate_postmortem.py,
# which the failure branches send to the channel.
#
# Defaults live here, not in the scheduler's environment: a value only the
# scheduler knows is a value the script cannot be run by hand with, and both of
# these are unset on this machine.
# 128000 is also the model's own maximum, and the CLI clamps to that rather
# than rejecting a larger number: this ceiling cannot be raised, only lowered.
# A turn truncated here is writing too much at once, so the only thing left to
# ask of it is smaller edits — which is what the one retry below asks.
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="${CLAUDE_CODE_MAX_OUTPUT_TOKENS:-128000}"
export MAX_THINKING_TOKENS="${MAX_THINKING_TOKENS:-31999}"

# claude-auth.sh is deliberately not sourced: the CLI finds its own stored
# login under CLAUDE_CONFIG_DIR, and that file's env token would override the
# stored one with a credential that cannot refresh.

# alert() — puts a failure in Discord instead of only in this log. See alert.sh
# for why.
. "$REPO/tools/alert.sh"

# session_id / session_exists — what lets a failed annotation resume instead of
# being bought a second time.
. "$REPO/tools/claude_session.sh"

# worker_annotate / worker_apply / worker_finish — one puzzle's model work and
# what is done with it, the same code the burn (tools/prereset_backfill.sh) runs.
. "$REPO/tools/puzzle_worker.sh"

# Keep this run's output where the exit trap can read it back, and report any
# failure line nobody wrote an alert for. The scheduler's .update.log holds every run
# ever, so "grep the log" would re-report last week; this is this run only.
# Spelled out rather than `mktemp -t cryptic-daily`: -t takes a bare prefix on macOS
# but a template that must contain X's on GNU, so the one spelling cannot mean
# the same thing on both. Every mktemp below is written this way.
RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/cryptic-daily.XXXXXX")"
exec > >(tee -a "$RUN_LOG") 2>&1
trap 'sleep 1; alert_run_failures "$RUN_LOG"; rm -f "$RUN_LOG"' EXIT

# Settings every unit and the tick share.
ANNOTATE_MAX="${ANNOTATE_MAX:-3}"
ANNOTATE_MAX_WEEKLY_PCT="${ANNOTATE_MAX_WEEKLY_PCT:-90}"
# The annotating model. An alias, so it names whichever model it points at
# today; the exact id that ran is recorded in each puzzle's
# annotatedBy, and the commit trailer is read back from there.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
# Explicit, because the CLI default differs per model (medium on Opus 5.5,
# high elsewhere) and would change silently when the alias moves.
ANNOTATE_EFFORT="${ANNOTATE_EFFORT:-medium}"
ANNOTATE_MAX_SESSION_PCT="${ANNOTATE_MAX_SESSION_PCT:-90}"
# Turns are the wrong unit to bound a run by, because one turn is not one price.
# A turn cut off for overrunning the output ceiling emits no tool call, so the
# CLI keeps its --max-turns budget intact and simply tries again; the ceiling is
# 128k output tokens and takes ~25 minutes to reach, so a run can loop for
# hours without writing one byte to the puzzle. Nothing in this script can see
# that: the retry below only fires when the CLI EXITS saying "output token
# maximum", and a run that absorbs the overrun never exits at all.
# So bound the wall clock as well. A puzzle that is going to be annotated is
# annotated in about an hour; one still going at ANNOTATE_MAX_MINUTES is not slow, it is lost,
# and it is recorded against the puzzle like any other failure.
ANNOTATE_MAX_MINUTES="${ANNOTATE_MAX_MINUTES:-90}"

# blog_chain <paper> <step>...: each step is a tools/ script and its arguments.
blog_chain() {
  local paper=$1 step out step_rc=0
  shift
  out="$(mktemp "${TMPDIR:-/tmp}/cryptic-blog.XXXXXX")"
  for step in "$@"; do
    step_start=$SECONDS
    # shellcheck disable=SC2086  # a step is a script and its arguments
    python3 tools/$step >"$out" 2>&1
    step_rc=$?
    cat "$out"
    echo "$step: rc=$step_rc in $((SECONDS - step_start))s"
    [ $step_rc -eq 0 ] && continue
    case "$step" in
      fetch_*)
        alert "the $paper fetch \`$step\` failed (rc=$step_rc), so the $paper puzzles are filed and dated from what is already cached:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$out" | cut -c1-200)"$'\n'"\`\`\`" ;;
      *)
        alert "the $paper chain stopped at \`$step\` (rc=$step_rc); the steps after it were skipped, so no new $paper puzzle is filed until it is fixed:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$out" | cut -c1-200)"$'\n'"\`\`\`"
        break ;;
    esac
  done
  rm -f "$out"
  return $step_rc
}

# Record a lost night against the puzzle's current inputs. failed_inputs.py
# refuses transient reasons (a usage lockout, an expired login, a network
# error), since those runs learned nothing about the grid. Extra arguments go
# straight through, which is how a validator's verdict says --judged.
record_annotate_failure() {   # id, reason, [--judged]
  echo "  $(python3 tools/failed_inputs.py record annotate "$1" --reason "$2" "${@:3}")"
}

# A dead annotation, reported where a person will see it and carrying the
# evidence rather than a pointer to it. "independent-12459 ran past 90m" tells
# its reader to go and open a 270k-line log on a machine they are not sitting
# at, which is the same as telling them nothing; the post-mortem says how many
# turns died at the output ceiling, what the run was doing, and where the
# transcript is. Every failure inside it is a no-op — see its docstring — so
# this cannot turn one bad night into two.
annotate_alert() {  # $1 = puzzle, $2 = what happened, $3 = session id
  local forensics msg
  forensics="$(python3 tools/annotate_postmortem.py "$3" --puzzle "$1" 2>&1)"
  msg=$(printf '%s\n```\n%s\n```' "$2" "$forensics")
  stop_alerted=1
  alert "$msg"
}

# --- the units: each runs from origin/master in a tree of its own ---------

unit_fetch() {  # fetcher: the newest puzzle of its series (exit 3 = nothing new, fine)
  # Every fetcher with a --latest belongs in tools/daily_units.py FETCHERS. A
  # series backfilled but left out of it stops at the day it was backfilled
  # and rots from there. Cyclops is fortnightly, so fetch_privateeye normally
  # returns 3 here; that is "nothing new", not a fault. One fetcher down is
  # weather; every one of them down at once alerts from the tick
  # (daily_units.after_tick).
  local rc
  python3 "tools/$1.py" --latest
  rc=$?
  [ $rc -eq 3 ] && return 0
  [ $rc -eq 0 ] || echo "$1 fetch failed (rc=$rc)"
  return $rc
}


# --- The Times and the Telegraph, rebuilt from the blogs that solve them ---
# Neither paper publishes its grids, so each puzzle is a chain rather than a
# fetch: cache the new blog posts, parse them, rebuild each grid from its
# light list, file what passes into puzzles/. Each step reads the one before
# it off <tools/downloads.py ROOT>/<blog>/, so a step that fails ends its chain --
# anything after it would read a half-written file -- except the fetches,
# whose failure only means the cache is as it was last night. The Times's
# second fetch is its own puzzle listing, as the Wayback Machine keeps it,
# which is what dates the prize puzzles the blog writes up a week late.
# The filers do not reindex; the next tick does, before it chooses.
# Both rebuilds are bounded by wall clock, newest due first: times_grids
# starts no post once its budget is spent, and the rest stay due for the next
# run. A parser change that makes hundreds of old posts due again (a changed
# light list re-dues its failure) drains as fast as the budget allows, and
# can never stretch a unit past its limit; a post already started runs to its node cap.
TIMES_GRID_SECONDS="${TIMES_GRID_SECONDS:-600}"
TELEGRAPH_GRID_SECONDS="${TELEGRAPH_GRID_SECONDS:-600}"
unit_blog_times() {
  blog_chain Times "fetch_wp_blog.py timesforthetimes" fetch_times_listing.py \
    parse_timesforthetimes.py "times_grids.py --budget-seconds $TIMES_GRID_SECONDS" \
    file_times_puzzles.py
}
unit_blog_telegraph() {
  blog_chain Telegraph "fetch_wp_blog.py bigdave44" parse_bigdave44.py \
    "times_grids.py --blog bigdave44 --budget-seconds $TELEGRAPH_GRID_SECONDS" \
    file_telegraph_puzzles.py
}
# From 2015 the Telegraph's own bucket is the primary source: today's
# puzzles, and blog-rebuilt files of the numbers it serves, refiled as printed.
# Every hole, oldest first, 2s apart (fetch_telegraph.py DELAY); a run starts
# no fetch past its budget, so it commits inside its limit, and one that
# stopped with holes left runs again at the next tick (backlog_left).
TELEGRAPH_BUCKET_SECONDS="${TELEGRAPH_BUCKET_SECONDS:-2400}"
unit_bucket_telegraph() {
  blog_chain Telegraph "fetch_telegraph.py --holes all --budget-seconds $TELEGRAPH_BUCKET_SECONDS"
}
# The Globe and Mail reprints the Times Quick Cryptic from No 3106: its copy
# witnesses the blog-rebuilt Quick the Times filer files for the same number,
# which is how a defect of that converter shows. Nothing is refiled from it.
# Daily; the fetch asks only for the copies not cached.
unit_xval_globe() {
  blog_chain Globe "cross_validate.py globe --fetch" "cross_validate.py globe"
}

# The Financial Times, rebuilt from fifteensquared's write-ups. The same chain
# in one tool: tools/ft_puzzles.py parses the cached posts, rebuilds the newest
# untried grids, newest first, and files what passes. The search is CPU, so a
# run starts no rebuild past FT_GRID_SECONDS and one that stopped with posts
# untried runs again at the next tick (backlog_left) until none is left. The
# searches run on Paul's desktop when it answers (tools/ocr_remote.py, which
# yields it the moment he games), ocr_remote.SEARCH_SLOTS posts at once;
# OCR_REMOTE= keeps them here.
FT_GRID_SECONDS="${FT_GRID_SECONDS:-1200}"
unit_ft() {
  local ft_out rc=0
  ft_out="$(mktemp "${TMPDIR:-/tmp}/cryptic-ft.XXXXXX")"
  if ! python3 tools/fetch_fifteensquared.py --category FT --posts-only >"$ft_out" 2>&1; then
    cat "$ft_out"
    alert "the fifteensquared FT fetch failed, so the FT puzzles are filed from the posts already cached:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$ft_out" | cut -c1-200)"$'\n'"\`\`\`"
  fi
  if OCR_REMOTE="${OCR_REMOTE-micro@100.68.145.15,micro@192.168.1.198}" \
      python3 tools/ft_puzzles.py --budget-seconds "$FT_GRID_SECONDS" >"$ft_out" 2>&1; then
    cat "$ft_out"
  else
    rc=1
    cat "$ft_out"
    alert "tools/ft_puzzles.py failed, so no new FT puzzle is filed until it is fixed:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$ft_out" | cut -c1-200)"$'\n'"\`\`\`"
  fi
  rm -f "$ft_out"
  return $rc
}

# The Observer's Azed from the Guardian's printable copies. tools/andlit_azed.py
# fetches the next copies andlit.org.uk's index links (2s apart, oldest unfiled
# first), starting none past AZED_FETCH_SECONDS, then files every cached copy
# whose grid and clue list agree. One that stopped with copies left to fetch
# runs again at the next tick (backlog_left) until andlit's index is drained.
# Scanned copies are read by the shared OCR on the desktop (OCR_REMOTE= keeps
# them here), starting none past AZED_SCAN_SECONDS.
AZED_FETCH_SECONDS="${AZED_FETCH_SECONDS:-900}"
AZED_SCAN_SECONDS="${AZED_SCAN_SECONDS:-1200}"
unit_azed() {
  local azed_out rc=0
  azed_out="$(mktemp "${TMPDIR:-/tmp}/cryptic-azed.XXXXXX")"
  if OCR_REMOTE="${OCR_REMOTE-micro@100.68.145.15,micro@192.168.1.198}" \
      python3 tools/andlit_azed.py nightly --budget-seconds "$AZED_FETCH_SECONDS" \
      --scan-seconds "$AZED_SCAN_SECONDS" >"$azed_out" 2>&1; then
    grep -v '^  No ' "$azed_out"
  else
    rc=1
    cat "$azed_out"
    alert "tools/andlit_azed.py failed, so no Azed is filed from the Guardian's copies until it is fixed:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$azed_out" | cut -c1-200)"$'\n'"\`\`\`"
  fi
  rm -f "$azed_out"
  return $rc
}


# Blog hints, re-read off the caches the blog units just topped up.
# tools/blog_facts.py joins every cached write-up to the puzzle it explains and
# writes tools/data/blog_facts/, which the site's hints and the validator's
# definition check read. A full parse is ~5 minutes, so --if-changed skips it
# when no cached post, clue or the parser itself has moved since the files were
# written. Its letter_facts pass builds the corpus-wide lexicons and reads the
# clues on the desktop (here, in local pools, when it is busy or off).
# Due after any blog unit ended well (tools/daily_units.py), so a new puzzle
# is validated against its blog. unit_commit's `git add -A` picks the files up.
unit_blog_facts() {
  local facts_out step_start step_rc
  facts_out="$(mktemp "${TMPDIR:-/tmp}/cryptic-facts.XXXXXX")"
  step_start=$SECONDS
  # Through tee, so each step's timing line reaches the log as it is printed,
  # and a run killed at its limit still shows where it was.
  python3 tools/blog_facts.py --if-changed 2>&1 | tee "$facts_out"
  step_rc=${PIPESTATUS[0]}
  echo "blog_facts: rc=$step_rc in $((SECONDS - step_start))s"
  [ $step_rc -eq 0 ] ||
    alert "tools/blog_facts.py failed (rc=$step_rc), so new puzzles get no blog hints:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$facts_out" | cut -c1-200)"$'\n'"\`\`\`"
  rm -f "$facts_out"
  return $step_rc
}

# The SNITCH's ratings of the Times, which the difficulty index is
# checked against and the Times badges quote a range from. One page, so a
# failure only means yesterday's ratings stand; unit_commit's `git add -A`
# picks up tools/data/snitch.json. Daily.
unit_ratings() {
  python3 tools/fetch_snitch.py || echo "fetch_snitch failed (rc=$?); continuing with the ratings already held"

  # Times for the Times comments: the newest month on disk and any after it are
  # refetched, and the comment table rebuilt from the whole cache.
  # The table feeds the Times badges, which blend in the solve times commenters
  # state (tools/difficulty.py blend()), so a puzzle re-rates as its post gains
  # comments at the next reindex. It leaves the committed table alone when the
  # cache is absent. The report is written to tools/data/snitch_report.txt, whose
  # history is the record of how the numbers move.
  python3 tools/fetch_wp_blog.py timesforthetimes --comments || echo "fetch_wp_blog --comments failed (rc=$?); the badges blend the comments already cached"
  python3 tools/blog_comment_difficulty.py || echo "blog_comment_difficulty: rc=$?; the badges and the per-clue check use the table already committed"
  python3 tools/snitch_report.py --write >/dev/null || echo "snitch_report failed (rc=$?); tools/data/snitch_report.txt is last night's"
  # The held-out scorecard /difficulty/ quotes. The page drops the numbers rather
  # than quote ones measured under other weights, so a missed night shows there.
  python3 tools/difficulty_check.py --write >/dev/null || echo "difficulty_check failed (rc=$?); /difficulty/ quotes tools/data/difficulty_check.json from last night"
  # The authoring checks' link and reversal-axis words, re-measured over the day's
  # annotations. Every annotated clue can move them, so they are refreshed here
  # rather than checked on each push.
  python3 tools/build_clue_joints.py >/dev/null || echo "build_clue_joints failed (rc=$?); the authoring checks use last night's tools/data/clue_joints.json"
  # The grid filler's per-length floors, re-measured over the day's answers.
  python3 tools/build_fill_floors.py >/dev/null || echo "build_fill_floors failed (rc=$?); grid_fill uses last night's tools/data/fill_floors.json"
  return 0
}

# A series that has stopped arriving, and the puzzles themselves. Daily.
unit_checks() {
  # A series that has stopped arriving. A feed that stops answering leaves its
  # series frozen at the day it broke, and the run cannot tell that from a quiet
  # night — it fetched, nothing failed. Only a series gone QUIET alerts; the full
  # table is `python3 tools/coverage_report.py`.
  coverage_stale=$(python3 tools/coverage_report.py --stale-only 2>&1) || alert "a series has stopped arriving:"$'\n'"\`\`\`"$'\n'"$coverage_stale"$'\n'"\`\`\`"

  # The puzzles themselves, as opposed to what we have written about them.
  # tools/puzzle_integrity.py forgives, by exact finding, the LENGTH sentences
  # that can never be fixed — PUBLISHED_WRONG and UNLINKED_IN_SOURCE — so this
  # alerts only on a NEW defect: two puzzles that are the same puzzle, an answer
  # that does not fit its clue's printed length, two crossing entries that
  # disagree.
  # 2>&1 because the failure that is not a finding — an import error, a missing
  # generated file — is on stderr, and an alert quoting an empty block says only
  # that something happened.
  integrity=$(python3 tools/puzzle_integrity.py --quiet 2>&1) ||
    alert "the corpus has picked up a defect:"$'\n'"\`\`\`"$'\n'"$integrity"$'\n'"\`\`\`"
  # How many turns a session is taking, logged every day. A number that only
  # exists when somebody goes looking is a number that gets quoted long after it
  # stopped being true, so it is computed here from the transcripts.
  python3 tools/turn_cost.py 2>&1 || true
  return 0
}

# Solutions that have since been published: prize puzzles, and every Everyman,
# whose competition window withholds answers for about a week. A puzzle we
# solved ourselves is refreshed too, and the day the paper's key lands our fill
# is marked against it: wrong answers lose the annotations written off them,
# and the score is alerted rather than left in .update.log. That grade is the
# only measurement of how often a derived answer is right — it happens once per
# puzzle, on a day nobody knows in advance, so it has to come and find us. A
# key that never comes from the paper comes from a solver's blog:
# cross_validate.py all --model grades every model-solved file against each
# cached copy that answers it (bigdave44, timesforthetimes, fifteensquared,
# georgeho, scans), through the same grader. A Cyclops its cover page misdates
# gets the fortnightly cadence's date.
# A puzzle given its key here is noted by unit_commit (daily_units.py keyed
# --record), and the tick's queue takes it as a new arrival.
unit_solutions() {
  local refreshed graded
  python3 tools/fetch_privateeye.py --backfill-dates
  refreshed=$( { python3 tools/fetch_puzzle.py --refresh-unsolved
                 python3 tools/fetch_observer.py --refresh-unsolved
                 python3 tools/fetch_privateeye.py --refresh-unsolved
                 python3 tools/cross_validate.py all --model --apply; } 2>&1 | tee /dev/stderr)
  graded=$(printf %s "$refreshed" | grep -E "^BLIND SOLVE GRADED|^  miss ")
  # A clean sweep and a bad night are not the same message. Both are worth
  # sending — the grade is the only measurement of derived answers and it
  # happens on a night nobody knows in advance — but the miss trailer is a lie
  # when there are no misses.
  if [ -n "$graded" ]; then
    if printf %s "$graded" | grep "^  miss " >/dev/null; then
      alert "a puzzle we solved ourselves has been graded against
published answers (the paper's key, or a solver's write-up):

$graded

Every miss listed above has had its annotation dropped, so those clues are back
in the queue and will be rewritten against the real answer."
    else
      ALERT_ICON="✅" alert "a puzzle we solved ourselves graded CLEAN against
published answers (the paper's key, or a solver's write-up):

$graded

Nothing was dropped and nothing is queued — every annotation on it was written
off the right answer."
    fi
  fi
  return 0
}

# The Minute Cryptic reference corpus. Every tree's tools/data/minutecryptic/
# is the main checkout's copy (tools/nightly_worktree.sh).
# Their hint ladder is the same shape as ours and better written, so we keep a
# local copy of their 55 worked examples to write against; it also archives
# their daily clue, which is only ever available on the day. Costs two HTTP
# requests and no inference, and lands in gitignored tools/data/minutecryptic/,
# so it runs unconditionally and never blocks the puzzle work. Failures print
# and are ignored — a scrape of somebody else's bundle is expected to break the
# day they change it, and that is not a reason to hold back the day's puzzle.
# The guard says so out loud. Their daily clue is only ever offered on the day,
# so a silent skip is not a deferral, it is a permanent hole in daily.jsonl.
unit_minute() {
  if command -v node >/dev/null 2>&1; then
    node tools/fetch_minutecryptic.js --quiet || echo "WARNING: minutecryptic capture failed"
  else
    echo "WARNING: no node on PATH ($PATH) — skipping the minutecryptic capture;" \
         "today's clue is only offered today and will not be recoverable"
  fi
  return 0
}

# One graded miss (tools/solve_misses.py pending; the tick lists them).
# A graded miss is a sample of a class: the reading, rule or check that let a
# wrong answer through will let the next one through too. Each miss gets one
# bounded run of tools/solve_miss_prompt.md, which fixes the class in
# tools/solve_prompt.md or tools/apply_solution.py, or records that nothing
# generalises. Every cold solve waits for the misses (tools/daily_units.py), so a
# fix already governs the next solve; the fix rides this unit's commit.
#
# The payload is the gate: tools/solve_misses.py pending lists only misses with
# no record in tools/data/diagnosed_misses.json, so a quiet night costs nothing
# and no miss is bought twice. A run that ends without recording a verdict is
# recorded as unfinished, alerted, and not retried: the same packet would buy
# the same failure.
SOLVE_MISS_MAX_MINUTES="${SOLVE_MISS_MAX_MINUTES:-30}"
unit_miss() {  # pid eid
  local miss_pid="$1" miss_eid="$2" miss_cap misslog session miss_rc miss_verdict miss_why
  command -v claude >/dev/null 2>&1 || { echo "miss diagnosis: no claude CLI on PATH ($PATH)"; return 1; }
  miss_cap="timeout ${SOLVE_MISS_MAX_MINUTES}m"
  command -v timeout >/dev/null 2>&1 || miss_cap=""
  misslog="$(mktemp "${TMPDIR:-/tmp}/cryptic-miss.XXXXXX")"
  session=$(python3 tools/weekly_usage.py --group session)
  if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
    echo "miss diagnosis: five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — waits for the reset"
    return 75
  fi
  if [ "$(python3 tools/weekly_usage.py --gate "$ANNOTATE_MAX_WEEKLY_PCT" 2>/dev/null)" != spend ]; then
    echo "miss diagnosis: weekly window not under ${ANNOTATE_MAX_WEEKLY_PCT}% — waits for the reset"
    return 75
  fi

  echo "diagnosing the graded miss $miss_pid $miss_eid with Claude Code... (session ${session:-unknown}%)"
  local miss_task miss_sid sess=()
  miss_task="Follow tools/solve_miss_prompt.md exactly (it is your system prompt's appendix; do not open the file). This is the miss it is about:

$(python3 tools/solve_misses.py packet "$miss_pid" "$miss_eid" 2>&1)"
  # A unit stopped mid-run leaves this, and the next attempt at the miss resumes it.
  miss_sid="$(worker_runs daily_update)/miss-$miss_pid-$miss_eid.sid"
  session_args "$miss_sid" sess miss_task
  # shellcheck disable=SC2086 # $miss_cap is a command and its argument, or nothing
  $miss_cap claude -p "$miss_task" "${sess[@]}" "${CLAUDE_HEADLESS[@]}" \
    --append-system-prompt-file tools/solve_miss_prompt.md \
    --exclude-dynamic-system-prompt-sections \
    --model "$ANNOTATE_MODEL" \
    --effort "$ANNOTATE_EFFORT" \
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(bash tools/test_*),Bash(grep *)" \
    </dev/null >"$misslog" 2>&1
  miss_rc=$?
  rm -f "$miss_sid"
  tail -20 "$misslog"
  miss_verdict=$(python3 tools/solve_misses.py verdict "$miss_pid" "$miss_eid")
  if [ -n "$miss_verdict" ]; then
    echo "  $miss_pid $miss_eid $miss_verdict"
  else
    miss_why="the run exited $miss_rc without recording a verdict"
    [ "$miss_rc" = 124 ] && miss_why="the run passed ${SOLVE_MISS_MAX_MINUTES}m and was stopped"
    python3 tools/solve_misses.py record "$miss_pid" "$miss_eid" --verdict unfinished --note "$miss_why"
    alert "diagnosing the graded miss $miss_pid $miss_eid failed: $miss_why. It is recorded as unfinished and will not be retried. Its last words:"$'\n'"\`\`\`"$'\n'"$(grep -v '^[[:space:]]*$' "$misslog" | tail -6 | cut -c1-200)"$'\n'"\`\`\`"
  fi
  rm -f "$misslog"
  return 0
}

# One puzzle, annotated; with `solve`, solved cold first in the same run. An
# answerless puzzle is solved only as the first half of annotating it: nothing
# else in this script runs a solve, because a grid solved and not hinted is
# spend the site never shows. Exit 0 when the puzzle is done or written off
# (failed_inputs.py holds it out of the queue), 1 when the CLI itself failed
# (daily_units.py then holds every annotation back), 75 when the five-hour
# window stopped it before it began.
annotated_ok=0
annotated_nums=""
stop_reason=""
# Set when the stop is the five-hour gate: a budget decision, never an alert.
stop_budget=""
# Set when a dead puzzle has already been reported WITH its post-mortem, so the
# summary below does not say the same failure again as a headline.
stop_alerted=""
lost_ids=""
unit_annotate() {  # id [solve]
  local pending="$1" unsolved=""
  [ "${2:-}" = solve ] && unsolved="$1"
  # Restate the controlled vocabulary in the prompt from the file that defines
  # it, BEFORE the run reads it. A rule the run has to go and grep for is a rule
  # the prompt did not state.
  python3 tools/build_annotate_prompt.py
  if command -v claude >/dev/null 2>&1; then
    run_log="$(mktemp "${TMPDIR:-/tmp}/cryptic-annotate.XXXXXX")"
    work_dir="$(mktemp -d "${TMPDIR:-/tmp}/cryptic-work.XXXXXX")"
    # Pinned, not inherited: taking whatever ~/.claude/settings.json defaults
    # to would let a settings edit made for an interactive session silently
    # retune the nightly job.
    # Opus on purpose: benchmarked head-to-head against Fable
    # on 30078 (see APP.md), it matched — 23/25 types, 22/25 definitions,
    # zero cryptic definitions, both hard clues solved — in the same wall time
    # for a third of the cost, because the bill is nearly all output tokens.
    WORKER_MODEL="$ANNOTATE_MODEL" WORKER_EFFORT="$ANNOTATE_EFFORT" WORKER_JOB="the nightly update"
    # Empty means no cap. `timeout` is GNU and the nightly runs in the Linux
    # container; a by-hand run on the Mac says so rather than silently going
    # uncapped.
    WORKER_WRAP="timeout ${ANNOTATE_MAX_MINUTES}m"
    if ! command -v timeout >/dev/null 2>&1; then
      WORKER_WRAP=""
      echo "  no timeout(1) here, so this run has no wall-clock cap"
    fi
    for num in $pending; do
      session=$(python3 tools/weekly_usage.py --group session)
      if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
        stop_reason="five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — $num waits for the reset"
        stop_budget=1
        break
      fi
      # The conversation's record, where a unit killed mid-run (its time limit,
      # a restart) leaves it for the next unit given this puzzle, in whichever
      # tree: that one resumes it (worker_put_back), its edits put back.
      sidfile="$(worker_runs daily_update)/$num.sid"
      ann_resume=""
      worker_put_back "$num" Annotate "$work_dir/$num.resume" "$sidfile" &&
        ann_resume=$(cat "$work_dir/$num.resume")
      [ "$(worker_kind "$sidfile")" = solve ] && unsolved="$unsolved $num"
      # An answerless puzzle is solved in the run that annotates it, and
      # nowhere else (see unit_annotate's header). That run writes the copy it annotates
      # (annotate_check.py --view) once its fill is in.
      fill="" verdict=""
      case " $unsolved " in
        *" $num "*)
          fill="${sidfile%.sid}.fill" verdict="$work_dir/$num.verdict"
          ann_file="tools/_puzzle_$num.json"
          echo "solving puzzle $num cold and annotating it with Claude Code... (session ${session:-unknown}%)" ;;
        *)
          echo "annotating puzzle $num with Claude Code... (session ${session:-unknown}%)"
          # The run reads a copy of the puzzle without its solutions detail, which
          # names the blog the key came from (see annotate_check.py VIEW_KEYS).
          # A crashed view leaves the run nothing to read, and the crash is in the
          # tool, so every later puzzle would crash the same way: stop annotating
          # and alert with the traceback rather than pay for sessions that work
          # around a broken checker.
          view_err="$(mktemp "${TMPDIR:-/tmp}/cryptic-view.XXXXXX")"
          if ! ann_file=$(python3 tools/annotate_check.py --view "$num" 2>"$view_err") || [ -z "$ann_file" ]; then
            alert "tools/annotate_check.py --view $num failed, so no puzzle is annotated until it is fixed:"$'\n'"\`\`\`"$'\n'"$(tail -n 20 "$view_err")"$'\n'"\`\`\`"
            rm -f "$view_err"
            stop_reason="annotate_check.py --view crashed on $num"
            break
          fi
          cat "$view_err" >&2
          rm -f "$view_err" ;;
      esac
      ann_task="Annotate the cryptic crossword $num in this repo, whose clues and answers are in $ann_file."
      ann_prompt="$ann_task Follow tools/annotate_prompt.md exactly (it is your system prompt's appendix; do not open the file), including running 'python3 tools/annotate_check.py <ID>' until it reports clean. Do not commit — the calling script commits."
      # The conversation is fixed before the first attempt and named in
      # $sidfile, because a run that dies has already been paid for: a retry
      # resumes it.
      ann_note="$ann_resume"
      ann_ok=""
      ann_retried=0
      ann_timeout=""
      while :; do
        worker_annotate "$num" "$run_log" "$sidfile" "$ann_prompt" "$ann_note" "$fill"
        ann_rc=$?
        cat "$run_log"
        ann_sid=$(worker_sid "$sidfile")
        [ "$ann_rc" = 0 ] && ann_ok=1
        [ -n "$ann_ok" ] && break
        # The cap fired. Say so here rather than below, because below reads the
        # reason off the CLI's last line and a killed CLI never printed one.
        # This puzzle is lost; the night is not. The cap firing says the model
        # is stuck on THIS grid — it says nothing about the next one, and the
        # loop re-reads the five-hour window at the top of every iteration, so
        # carrying on cannot outspend the gate. Stopping the run here would take
        # every puzzle after this one, untried, down with it.
        if [ "$ann_rc" = 124 ]; then
          ann_timeout="$num ran past ${ANNOTATE_MAX_MINUTES}m without finishing and was stopped"
          echo "  $ann_timeout"
          record_annotate_failure "$num" "$ann_timeout"
          worker_forget "$sidfile"
          annotate_alert "$num" "$ann_timeout" "$ann_sid"
          lost_ids="$lost_ids $num"
          break
        fi
        # Exactly one failure earns another attempt, and it is the one that
        # costs the most: a turn killed for overrunning the output ceiling
        # emits no tool call, so everything the run spent buys nothing at all.
        # Retry it ONCE, resuming that same conversation and told to write in
        # pieces. Splitting the write is the whole of the retry: the ceiling is
        # the model's own maximum, so there is no number to raise. A usage
        # lockout wants the next window rather than another attempt now, and an
        # expired login wants a person; both of those fall through to the alert
        # below unchanged.
        [ "$ann_retried" = 0 ] || break
        grep -q "output token maximum" "$run_log" || break
        session_exists "$ann_sid" || break
        ann_retried=1
        ann_note="Your last turn was cut off for going past the output token limit, so whatever it was writing was never saved. Everything you did BEFORE that turn is intact — read the files you were writing to see how far you actually got, and carry on from there rather than starting again. Write in several smaller edits instead of one large one: an edit big enough to hit that limit will be cut off again. Finish the task you were given and run 'python3 tools/annotate_check.py $num' until it reports clean. Do not commit."
        echo "  $num overran the output ceiling — resuming that same session, told to write in smaller edits, rather than paying for it twice"
      done
      # A cold solve's fill is checked again however the run ended, before
      # anything it wrote can ship. A rejected one ships nothing.
      if [ -n "$fill" ]; then
        worker_apply "$num" "$fill" "$run_log" "$verdict" "$sidfile"
        applied=$?
        cat "$verdict"
        if [ "$applied" -ne 0 ]; then
          echo "solve of $num rejected — nothing the run wrote ships"
          worker_forget "$sidfile"
          # The lines travel in the alert. A solve failure is a bug in this
          # repo far more often than a hard crossword, and the reader needs the
          # applier's complaint and the model's last words to tell which.
          [ "$applied" -eq 1 ] &&
            alert "solving $num failed and will not be tried again until its clues, tools/solve_prompt.md or tools/apply_solution.py change — the puzzle ships hintless until then or until the paper publishes its key. The applier said:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$verdict" | cut -c1-200)"$'\n'"\`\`\`"$'\n'"and the run's last words were:"$'\n'"\`\`\`"$'\n'"$(tail -6 "$run_log" | cut -c1-200)"$'\n'"\`\`\`"
          continue
        fi
      fi
      if [ -n "$ann_ok" ]; then
        # Validated, committed and pushed on its own, as the burn does: a
        # puzzle that is good is good whatever the next one does.
        if worker_finish "$num" Annotate "$sidfile" "$run_log"; then
          annotated_ok=$((annotated_ok + 1))
          annotated_nums="$annotated_nums $num"
        fi
      elif [ -n "$ann_timeout" ]; then
        # Already said and already written down. Go on to the next puzzle
        # rather than reading a reason off a log the killed CLI never wrote to.
        continue
      else
        # The CLI says why it stopped on its last line — a spend limit, an
        # expired login, a network failure. Carrying that sentence into the
        # alert is the difference between "go and read a 270k-line log" and
        # knowing whether this needs a /login or just needs tomorrow.
        stop_reason="$num failed: $(grep -v '^[[:space:]]*$' "$run_log" | tail -1 | cut -c1-200)"
        # A CLI killed from outside never got to print that last line, and
        # "independent-12456 failed:" with nothing after the colon tells whoever
        # reads it nothing at all. The exit code is always there.
        [ "$stop_reason" = "$num failed: " ] &&
          stop_reason="$num failed: the CLI exited $ann_rc without printing a reason"
        # And write that down against the puzzle, because tomorrow's queue is
        # otherwise identical to tonight's: this puzzle is still un-annotated and
        # still the newest, so it comes back to the head of the list and is
        # bought again from an empty context.
        record_annotate_failure "$num" "$stop_reason"
        # What it finished stays if it validates, for the closing commit and
        # tomorrow's run to build on; a half-written file is put back.
        worker_failed "$num" Annotate "$work_dir/$num.resume" "$sidfile" || true
        # Every dead puzzle is reported, not only a night that annotated none.
        # A run that got two and lost one is otherwise silent, and the first
        # anyone knows is the site being a day short.
        annotate_alert "$num" "$stop_reason" "$ann_sid"
        break
      fi
    done
    rm -rf "$run_log" "$work_dir"
  else
    stop_reason="claude CLI not on PATH ($PATH)"
  fi
  if [ -n "$stop_reason" ]; then
    [ -n "$stop_budget" ] && { echo "$stop_reason"; return 75; }
    # Already sent with the transcript's own post-mortem, or said here.
    [ -n "$stop_alerted" ] ||
      alert "annotating $pending stopped — $stop_reason. If that mentions authentication the CLI needs a fresh /login; see the CLAUDE_CONFIG_DIR note in daily_update.sh. Annotation waits ANNOTATE_PAUSE (tools/daily_units.py) before the next. Full output: .update.log."
    return 1
  fi
  return 0
}

# The bad-hint queue: fix what solvers reported, don't just relay it.
# An alert is a fix that has not happened yet: a solver reports a wrong hint, a
# human reads about it hours later, and the clue stays wrong until someone sits
# down with it. Run every two hours, the fix rides this unit's commit, push and
# deploy, and the report is answered on the site within hours. A human is
# woken only for what this pass could not close.
#
# The payload IS the alert: reports.py prints nothing when the queue is empty,
# and a failure to read it is worth waking for too — an unreadable queue looks
# exactly like an empty one from here. Each key costs a wrangler round trip, so
# --since bounds a bad week; anything older is still in `tools/reports.py` with
# no argument.
#
# Two alerts, not one. A read that failed is not a solver complaining, and
# saying "solvers reported bad hints" over a wrangler stack trace sends whoever
# answers it hunting for a clue to fix that nobody reported.
unit_reports() {
  local bad_hints attempted session fixlog fix_task fix_sid sess=()
  if bad_hints=$(python3 tools/reports.py --since 14 2>&1); then
    case "$bad_hints" in
      "no bad-hint reports"*|"") ;;
      *)
        attempted=0
        session=$(python3 tools/weekly_usage.py --group session)
        if ! command -v claude >/dev/null 2>&1; then
          echo "bad-hint queue: no claude CLI, so the reports only get an alert"
        elif [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
          echo "bad-hint queue: five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — the fix pass waits for the reset"
        else
          fixlog="${TMPDIR:-/tmp}/cryptic-reports.log"
          echo "fixing $(printf '%s' "$bad_hints" | grep -c '^  r:') reported hint(s) with Claude Code... (session ${session:-unknown}%)"
          fix_task="Follow tools/report_fix_prompt.md exactly (it is your system prompt's appendix; do not open the file). These are the reports it is about:

$bad_hints"
          # A unit stopped mid-run leaves this, and the next pass resumes it.
          # The fix pass runs the validators and node harnesses, which read
          # the generated files this unit skipped at start (daily_units.py).
          ct_generated "$REPO"
          fix_sid="$(worker_runs daily_update)/reports.sid"
          session_args "$fix_sid" sess fix_task
          claude -p "$fix_task" "${sess[@]}" "${CLAUDE_HEADLESS[@]}" \
            --append-system-prompt-file tools/report_fix_prompt.md \
            --exclude-dynamic-system-prompt-sections \
            --model "$ANNOTATE_MODEL" \
            --effort "$ANNOTATE_EFFORT" \
            --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
            --max-turns 120 >"$fixlog" 2>&1
          rm -f "$fix_sid"
          tail -40 "$fixlog"
          attempted=1
        fi
        # The verdict is the queue, not the model's account of itself. A key is
        # cleared only by reports.py --done, so whatever still lists after the pass
        # is exactly what nobody fixed, and that is what the alert carries.
        if [ "$attempted" = 1 ]; then
          bad_hints=$(python3 tools/reports.py --since 14 2>&1) || bad_hints="the queue could not be re-read after the fix pass: $bad_hints"
        fi
        case "$bad_hints" in
          "no bad-hint reports"*|"") echo "bad-hint queue: cleared by the fix pass" ;;
          *) alert "solvers reported bad hints that the fix pass did not close. Each one is a
sample of a class, not an incident — fix the clue, then measure the shape across
every walkthrough and make it a rule if it matches cleanly (see the docstring in
tools/reports.py). What the fix pass did try is in .update.log:

$bad_hints" ;;
        esac ;;
    esac
  else
    alert "the bad-hint queue could not be read, so reports are arriving and
nobody is seeing them. No solver is quoted below — this is why the read failed:

$bad_hints"
  fi
  return 0
}

# Commit what the unit changed, and push. (The index is untracked: the tree's
# was rebuilt at the unit's start, and the site's is built by CI.) The unit's tree started at
# origin/master and holds nothing else, so whatever is modified or new here
# was made by this unit. A unit that filed puzzles first puts every copy of
# them we hold to a vote (tools/cross_validate.py all): a majority of three
# or more fixes our file, its votes in the corroboration ledger; two copies
# that disagree are a lead in cross-validate/all-leads.jsonl. Cached sources
# only, nothing is fetched. A puzzle given its official key here is noted for
# the tick's annotation queue (daily_units.py keyed --record).
unit_commit() {  # subject
  python3 tools/daily_units.py keyed --record
  if git status --porcelain -- puzzles | grep . >/dev/null; then
    blog_chain Corroboration "cross_validate.py all --new --apply"
  fi
  # The annotation payloads apply_annotations.py consumed. Gitignored (tools/_*),
  # so this is housekeeping rather than safety — but nothing else clears them.
  rm -f "$REPO/tools/_ann_"*.json "$REPO/tools/_puzzle_"*.json

  if [ -n "$(git status --porcelain)" ] || [ -n "$(git rev-list origin/master..HEAD 2>/dev/null)" ]; then
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
    # A symlink resolves only on the machine that made it, and this tree is full
    # of them: nightly_worktree.sh links the shared state in from the main
    # checkout. Committed, they reach the Pages runner as dangling links, tar
    # refuses to archive the site, and the day is pushed but never published.
    # add -A cannot be narrowed (above), so the narrowing is here.
    symlinks=$(git ls-files -s | sed -n 's/^120000 [0-9a-f]* 0	//p')
    if [ -n "$symlinks" ]; then
      printf '%s\n' "$symlinks" | while IFS= read -r link; do git rm -q --cached "$link"; done
      alert "the daily update tried to commit machine-local symlink(s): $(printf '%s ' $symlinks)- unstaged, because committed they break the Pages build for everyone. Add them to .gitignore, spelled without a trailing slash."
    fi
    # The subject names what was filed (tools/commit_subject.py), the unit
    # after it (daily_units.py job: a backfill's commits say so, not "daily").
    git diff --cached --quiet ||
      git commit -m "$(printf '%s\n\n%s' "$(git diff --cached --name-status -M -- puzzles | python3 tools/commit_subject.py "$(python3 tools/daily_units.py job "$1")")" "$(python3 tools/provenance.py trailer)")"
    # Nothing may be left behind. With one writer this is not a judgement
    # call about whose file it was: anything still showing here after `add -A` and
    # a commit is a bug, and it is work that will never reach the site. Read with
    # cut, not awk $2 — a rename prints two paths and a filename may contain a
    # space, and awk would read either as the wrong filename.
    left=$(git status --porcelain | cut -c4- | tr '\n' ' ')
    [ -n "$left" ] && alert "the daily update committed, and left these behind in its own worktree: $left"
    # A rebase that stops here is rarely a disagreement. Every file this job writes
    # that an interactive session writes too is GENERATED — README.md and what is
    # still tracked of the built pages — so a
    # conflict in one is two rebuilds of the same inputs, not two opinions, and
    # resolving it by hand strands the run. Rebuild from the merged sources
    # instead.
    #
    # What makes that safe is not a list of generated filenames, which would drift
    # the moment a builder learns a new output: a path is only accepted once a
    # builder has actually rewritten it, and rewriting it is exactly what leaves no
    # conflict markers behind. A path still carrying markers is owned by no builder
    # — a real conflict — and the whole rebase is abandoned to the alert below
    # rather than half-resolved.
    rebuild_generated_conflicts() {
      # Nothing to continue unless the rebase stopped mid-pick; a rebase that
      # refused to start is not a conflict and must not be papered over. The state
      # directory is the only honest test of that: REBASE_HEAD is left behind
      # after a rebase finishes, so it says "in progress" for the rest of the day.
      [ -d "$(git rev-parse --git-path rebase-merge)" ] ||
        [ -d "$(git rev-parse --git-path rebase-apply)" ] || return 1
      # A path master deleted that this run wrote to (modify/delete; `DU`, since
      # in a rebase "us" is master) stays deleted: master retired the file, and
      # what this run wrote there came from tools master has since changed not to
      # write it. Before the builders, because a conflicted path is still in the
      # index, and build_readme.py refuses a tracked file with no layout row.
      local gone path
      gone=$(git status --porcelain --untracked-files=no | sed -n 's/^DU //p') || return 1
      while IFS= read -r path; do
        [ -n "$path" ] || continue
        echo "rebase: master deleted $path; tonight's write to it is dropped"
        git rm -q -- "$path" || return 1
      done <<GONE
$gone
GONE
      # No stamp_assets.py: index.html is committed unstamped and the deploy
      # workflow stamps its own checkout, so a stamp here would be committed.
      python3 tools/build_abbreviations.py >/dev/null &&
        python3 tools/fetch_puzzle.py --reindex >/dev/null &&
        python3 tools/build_readme.py >/dev/null || return 1
      # Collect the list before staging any of it. Fed in through a process
      # substitution, `git diff` is still running while the loop stages, and it
      # takes .git/index.lock to refresh the index — every add after the first
      # then dies on "Another git process seems to be running".
      local conflicted
      conflicted=$(git diff --name-only --diff-filter=U) || return 1
      while IFS= read -r path; do
        [ -n "$path" ] || continue
        [ -f "$path" ] && ! grep -q '^<<<<<<< ' "$path" || return 1
        git add -- "$path" || return 1
      done <<CONFLICTED
$conflicted
CONFLICTED
      # The builders also rewrite files the rebase never conflicted in — the
      # README's corpus counts move with every puzzle. A rebase refuses to
      # continue with those left unstaged, so stage them under the same rule: a
      # path only qualifies once a builder has rewritten it, and a rewrite is
      # exactly what leaves no conflict markers behind.
      local rebuilt
      rebuilt=$(git diff --name-only) || return 1
      while IFS= read -r path; do
        [ -n "$path" ] || continue
        [ -f "$path" ] && ! grep -q '^<<<<<<< ' "$path" || return 1
        git add -- "$path" || return 1
      done <<REBUILT
$rebuilt
REBUILT
      GIT_EDITOR=true git rebase --continue >/dev/null 2>&1
    }

    # Push only if a remote exists (GitHub Pages picks it up from master).
    # --autostash and a rebase first: the remote is routinely ahead of the mini
    # (interactive sessions push to it all day), and a rejected push must not look
    # like a successful one, or the day's puzzle quietly never reaches the site.
    if git remote get-url origin >/dev/null 2>&1; then
      # HEAD is detached in this worktree, so master is named explicitly on both
      # sides. --autostash still earns its place: a rebase refuses outright with
      # anything unstaged, and the leftover check above reports that case rather
      # than preventing it.
      attempt_push() {
        git fetch -q origin master &&
          { git rebase -q --autostash origin/master || rebuild_generated_conflicts; } &&
          push_or_raced
      }
      # push_race_retry (tools/nightly_worktree.sh) redoes this whole attempt a
      # few times if a sibling worktree's fetch or push wins the lock on the
      # shared refs/remotes/origin/master first; anything else it returns straight
      # through to the alert below.
      if ! push_race_retry attempt_push
      then
        # Say which files disagreed, and leave the worktree in a state the next
        # run can use: nightly_worktree.sh resets --hard, which does not clear a
        # rebase that is still in progress.
        stuck=$(git diff --name-only --diff-filter=U | tr '\n' ' ')
        git rebase --abort 2>/dev/null
        alert "the daily unit $1 committed but could not push, so the site does not show it yet. ${stuck:+The rebase onto origin/master conflicted in: $stuck}See the tail of .update.log."
      fi
    fi
  else
    echo "nothing to commit"
  fi
  return 0
}

if [ "${1:-}" = unit ]; then
  key="${2:-}"
  shift 2 || exit 2
  echo "=== cryptic-teacher $key $(date '+%Y-%m-%d %H:%M') ==="
  case "$key" in
    fetch:*) unit_fetch "${key#fetch:}" ;;
    blog:times) unit_blog_times ;;
    blog:telegraph) unit_blog_telegraph ;;
    bucket:telegraph) unit_bucket_telegraph ;;
    xval:globe) unit_xval_globe ;;
    ft) unit_ft ;;
    azed) unit_azed ;;
    blog-facts) unit_blog_facts ;;
    ratings) unit_ratings ;;
    checks) unit_checks ;;
    solutions) unit_solutions ;;
    minute) unit_minute ;;
    reports) unit_reports ;;
    miss:*) unit_miss "$@" ;;
    annotate:*) unit_annotate "${key#annotate:}" "$@" ;;
    *) echo "daily_update.sh: no unit $key" >&2; exit 2 ;;
  esac
  unit_rc=$?
  # A unit that never began (75) has nothing to commit.
  [ "$unit_rc" = 75 ] && exit 75
  unit_commit "$key" || unit_rc=1
  exit "$unit_rc"
fi

# --- the tick: choose the puzzles to annotate, then start what is due --------
echo "=== cryptic-teacher tick $(date '+%Y-%m-%d %H:%M') ==="

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
# pending. Number is only a tie-break, for
# the several series that publish on the same morning.
#
# A bulk import gets no special treatment: backfilled puzzles queue by date like
# everything else and are worked newest to oldest. The rate limit below is what
# stops a big import from being a big bill.
# Puzzles whose annotation already failed on the inputs they have now. Selection
# here is by date and nothing else, so without this a puzzle that fails is the
# newest un-annotated puzzle again tomorrow, bought from scratch each time (see
# tools/failed_inputs.py). Excluded before the queues are cut, not skipped inside
# the loop: the cut is the night's whole budget.
#
# Two queues. `fresh` is every new arrival, uncapped: a puzzle dated within the
# last two days, or one whose official key landed in that time (noted by the
# unit that refetched it: daily_units.py keyed). `pending` is everything older,
# newest first, and ANNOTATE_MAX a day bounds it together with the answerless
# puzzles, which join it below (tools/daily_units.py counts the day). Only the
# usage gates below limit `fresh`.
#
# puzzles/index.json is generated and untracked, so the copy on disk here was
# written by whatever code ran last, not by this checkout's. Both queues read
# fields off it and read a missing field as a puzzle with nothing wrong, so an
# index older than a field silently answers "fine" for every puzzle.
# A tick must return in seconds (the plugin kills it at 600), and a rebuild is
# minutes beside the corpus job, so the index is rebuilt detached, after the
# tick has read the last one (start_index_rebuild, at the end). This tick reads
# that index only when it was built by this checkout's indexer and no rebuild
# is writing it; otherwise it chooses no puzzle, and the next tick does.
index_lock="$(git rev-parse --path-format=absolute --git-common-dir)/daily-tick-index.lock"
index_stamp="$(git rev-parse --path-format=absolute --git-dir)/daily-tick-index.stamp"
index_ready() {
  [ -s puzzles/index.json ] && [ -s "$index_stamp" ] && flock -n "$index_lock" true &&
    git diff --quiet "$(cat "$index_stamp")" HEAD -- tools/fetch_puzzle.py tools/series.py 2>/dev/null
}
start_index_rebuild() {  # detached, holding none of this tick's descriptors (the tree lease, the scheduler's lock)
  python3 - "$index_lock" "$(git rev-parse --path-format=absolute --git-common-dir)/ct-generated.lock" "$index_stamp" <<'PY'
import subprocess, sys
index_lock, generated_lock, stamp = sys.argv[1:]
# One rebuild at a time for the tick (index_lock, which index_ready also
# tests), and one generated rebuild at a time across every tree.
# Detached, so no queue gates it: nice 19 on half the cores, beside the units.
script = ('flock -n "$1" flock "$2" env CT_JOBS=2 nice -n 19 python3 tools/fetch_puzzle.py --reindex >/dev/null 2>&1 '
          '&& git rev-parse HEAD >"$3.tmp" && mv "$3.tmp" "$3"')
subprocess.Popen(["bash", "-c", script, "rebuild", index_lock, generated_lock, stamp], stdin=subprocess.DEVNULL,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
PY
}
if ! index_ready; then
  echo "the annotation index is being rebuilt or is from other code; no puzzle is chosen this tick"
  start_index_rebuild
  exec python3 tools/unit_queue.py tick daily ${UNIT_QUEUE_DRY:+--dry-run}
fi
annotate_blocked=$(python3 tools/failed_inputs.py skipped annotate)
{ read -r fresh; read -r pending; } < <(python3 - "$ANNOTATE_MAX" "$annotate_blocked" "$(python3 tools/daily_units.py keyed --recent)" <<'EOF'
import json, sys
sys.path.insert(0, "tools")
import datetime
from series import puzzle_day, is_first_issue
idx = json.load(open("puzzles/index.json"))
blocked = set(sys.argv[2].split())
cutoff = datetime.date.today() - datetime.timedelta(days=2)

keyed_tonight = set(sys.argv[3].split())

# IDs, not numbers: an id is what every step below names and what
# tools/puzzle_paths.py finds a file by, so no consumer has to resolve a number
# two papers could share.
todo = sorted(((puzzle_day(p) or datetime.date.min, p["id"]) for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")
               and not p.get("awaitsPreamble") and p["id"] not in blocked), reverse=True)
fresh = [i for d, i in todo if d >= cutoff or i in keyed_tonight]
# A series' first puzzle leads the rest, then a partly annotated one, which
# costs only its missing clues.
partial = {p["id"]: p["unannotated"] for p in idx["puzzles"] if p.get("unannotated")}
older = sorted((i for _, i in todo if i not in fresh),
               key=lambda i: (not is_first_issue(i), i not in partial, partial.get(i, 0)))
print(" ".join(fresh))
print(" ".join(older[:int(sys.argv[1])]))
EOF
)

# Puzzles the paper hasn't published answers for — Saturday prize crosswords,
# which withhold them for about a week. No solutions means nothing for the
# annotator to explain, so unsolved, the newest and most-visited puzzle on the
# site would sit hintless for its whole first week.
#
# So solve it, as the first half of annotating it: it is placed in the
# annotation queue below, and one unit solves it and annotates it.
# Never as a separate pick: a grid solved and not hinted is spend the site
# never shows. A model solves the grid cold, and tools/apply_solution.py
# writes it only if every entry is answered, every length fits and all ~58
# crossings agree — which is not proof, but is a check no accidental fill
# passes. The answers go in marked as ours (solutions.model), the site says so,
# the fetcher keeps re-checking every night, and when the official key lands the
# guess is graded against it and any entry we got wrong loses its annotation and
# gets rewritten. Being wrong is therefore recoverable and visible; the failure
# mode we refuse is being wrong and silent, which is why a fill that fails the
# check writes nothing at all.
#
# SOLVE_MAX bounds how many answerless puzzles are offered to the queue, a
# ceiling and not a target; ANNOTATE_MAX then cuts them with the rest of the
# backlog. On a normal night there are none. They come in bursts — a Cyclops
# arrives answer-stripped and waits days for fifteensquared, a Saturday prize
# waits a week for its key, and with eight series those waits overlap.
SOLVE_MAX="${SOLVE_MAX:-5}"
# A cold solve that fails is not tried again until its inputs change: the
# clues, the solve prompt, or apply_solution.py (tools/failed_inputs.py).
# Selection is by date, so without that a failed puzzle is the newest unsolved
# one again tomorrow, with the same grid and the same rejection. The reason one
# fails is usually us — a crashing applier, a moved prompt file — and a fix to
# either changes the hash, so the puzzle comes back by itself.
solve_blocked=$(python3 tools/failed_inputs.py skipped solve)
unsolved=$(python3 - "$SOLVE_MAX" "$solve_blocked" <<'EOF'
import json, sys
sys.path.insert(0, "tools")
import datetime
from series import puzzle_day, is_first_issue
limit, tried = int(sys.argv[1]), set(sys.argv[2].split())
idx = json.load(open("puzzles/index.json"))
unsolved_ids = {p["id"] for p in idx["puzzles"] if not p.get("hasSolutions")}

# A grid a model cannot READ is not a solve it can fail; it is a puzzle we hold
# a picture of. Queued, a puzzle whose clues are printed blank would be the
# newest answerless puzzle every night, take a full cold solve, and raise "gave
# up after 1 attempt" — an alert naming the model for a hole in the data. They
# are not queued at all, which is
# why nothing here alerts: there is no failure, only a fetch that came back
# empty, and the thing that fixes it is re-fetching the clue text.
#
# The line is fetch_puzzle.cold_solvable, which the burn's queue shares.
from fetch_puzzle import cold_solvable
readable = {}  # id -> (present, total), only for puzzles the index flags
unreadable = set()
for p in idx["puzzles"]:
    if p["id"] in unsolved_ids and not cold_solvable(p):
        readable[p["id"]] = (p["clues"]["present"], p["clues"]["total"])
        unreadable.add(p["id"])
if unreadable:
    print("not queued for a cold solve, too little clue text to read: "
          + ", ".join(f"{i} ({readable[i][0]}/{readable[i][1]} clues)"
                      for i in sorted(unreadable)), file=sys.stderr)
# A series' first puzzle goes ahead of the newest-first order.
todo = sorted(((is_first_issue(p["id"]), puzzle_day(p) or datetime.date.min, p["id"])
               for p in idx["puzzles"]
               if p["id"] in unsolved_ids and p["id"] not in unreadable
               and not p.get("awaitsPreamble")
               and p["id"] not in tried), reverse=True)
# Puzzles held as their clues alone (tools/clues_only.py) are solved here too,
# those a builder can promote; the solve derives their grid. Read from the
# clues_only/ beside puzzles/index.json, the same tree as the index. Dateless book
# reprints, so they go last.
import clues_only
from pathlib import Path
todo += [(False, datetime.date.min, r["id"]) for r in clues_only.solvable(Path("clues_only"))
         if r["id"] not in tried]
print(" ".join(i for *_, i in todo[:limit]))
EOF
)
# How many of both queues are held out on a recorded failure, so the log says
# what the queues above left out and not only what they chose.
python3 tools/failed_inputs.py summary

# Annotation is the only thing here that spends inference, and a crossword
# backlog is never worth being rate-limited for real work. Skip it once the
# account's weekly window is more than ANNOTATE_MAX_WEEKLY_PCT spent; the other
# units still run, so the newest puzzle is still fetched and published, just
# without hints until the window resets.
#
# The gate fails CLOSED: if it cannot read the quota it skips, and a skipped
# night raises an alert into Discord, so a stalled backlog is as visible as
# overspending. Failing open does not even buy the puzzle it spends for: a read
# that fails every night leaves the gate wide open while the week's quota runs
# down, and the annotation dies on the limit anyway. One day of backlog is
# recoverable; a week of someone's quota spent by a gate that had stopped
# gating is not. A tick runs every ten minutes, so each alert's text names the
# cause and not a reading: alert.sh sends an identical text once in
# ALERT_REPEAT_HOURS.
#
# The verdict comes from weekly_usage.py rather than from arithmetic here,
# because "am I over the line" is answerable in cases where "what is the
# percentage" isn't: usage only rises within a window, so even a stale cached
# reading is a floor, and a floor above the limit is a decision: a 10-hour-old
# 75% against a 50% limit is a skip, not blindness.
if [ -n "$fresh$pending$unsolved" ] && ! python3 tools/weekly_usage.py --self-test >/dev/null 2>&1; then
  # The gate's own four cases, run offline before its verdict is believed. A
  # gate whose logic is broken says "spend" as confidently as a working one, so
  # a failing self-test is treated as the worst verdict rather than ignored.
  alert "the weekly usage gate is failing its own self-test, so annotation is skipped. The gate logic itself is wrong — see the SELF-TEST lines in .update.log."
  fresh=""
  pending=""
  unsolved=""
fi
if [ -n "$fresh$pending$unsolved" ]; then
  # The gate explains itself on stderr; keep it so the alert can carry the
  # reason instead of pointing at a log. "can't read the quota" alone is the
  # same sentence whether the API is down or the CLI is simply logged out — and
  # those need opposite responses, since a logged-out CLI means nothing would
  # have run tonight regardless of what the gate decided.
  gate_why=$(mktemp)
  gate_verdict=$(python3 tools/weekly_usage.py --gate "$ANNOTATE_MAX_WEEKLY_PCT" 2>"$gate_why")
  cat "$gate_why" >&2
  case "$gate_verdict" in
    spend)
      echo "weekly usage under ${ANNOTATE_MAX_WEEKLY_PCT}% — queued: ${fresh:-no new arrivals}; backlog ${pending:-none}${unsolved:+; answerless $unsolved}" ;;
    skip)
      echo "weekly usage over ${ANNOTATE_MAX_WEEKLY_PCT}% — skipping annotation of $fresh $pending${unsolved:+ and solving of $unsolved}"
      fresh=""
      pending=""
      unsolved="" ;;
    *)
      if grep -q "stale /login" "$gate_why"; then
        alert "Claude Code is logged out on this machine, so annotation is skipped — and every other model call would fail too, gate or no gate. Run \`claude\` in a terminal and \`/login\`; nothing else here can fix it. The site is fine, new puzzles just publish without hints."$'\n'"\`\`\`"$'\n'"$(grep -m1 "stale /login" "$gate_why" | cut -c1-300)"$'\n'"\`\`\`"
      else
        alert "the weekly usage gate can't read the quota, so annotation is skipped rather than run ungated. Nothing is broken on the site — new puzzles still publish, just without hints."$'\n'"\`\`\`"$'\n'"$(tail -1 "$gate_why" | cut -c1-300)"$'\n'"\`\`\`"
      fi
      fresh=""
      pending=""
      unsolved="" ;;
  esac
  rm -f "$gate_why"
fi

# The five-hour window is the one the annotation units spend, so it is read at
# every tick and again as each unit starts: a full window starts no model run,
# and the units wait for its reset rather than die on "you've hit your limit".
if [ -n "$fresh$pending$unsolved" ]; then
  session=$(python3 tools/weekly_usage.py --group session)
  if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
    echo "five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — no model run starts until it resets"
    fresh="" pending="" unsolved=""
  fi
fi
# Graded misses waiting for a diagnosis (unit_miss), under the same gates: the
# payload is the gate, so a quiet day costs nothing.
misses=$(python3 tools/solve_misses.py pending)
if [ -n "$misses" ]; then
  session=$(python3 tools/weekly_usage.py --group session)
  if [ "$(python3 tools/weekly_usage.py --gate "$ANNOTATE_MAX_WEEKLY_PCT" 2>/dev/null)" != spend ] ||
     { [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; }; then
    echo "graded misses wait for the usage gates: $(printf '%s' "$misses" | tr '\n' ' ')"
    misses=""
  fi
fi


# Place the unsolved in the annotation queue.
# An answerless puzzle is solved only as the first half of annotating it: the
# unit that annotates it solves it first, and nothing else in this script runs
# a solve. So a grid enters the queue here, where the queue would annotate it,
# and is cut with everything else; one the cut drops is not solved either,
# because a solve nobody hints is spend with nothing to show for it on the site.
#
# A day-dated one goes to the front of the capped backlog (`pending`, behind
# `fresh`): it is the newest puzzle there and the one people are looking at. A
# book reprint holds only its book's `year` (no volume prints the day a puzzle
# ran), so both queues above sort it behind every day-dated puzzle,
# deliberately, and putting one at the front would spend a place in tonight's
# ANNOTATE_MAX on a 1970s reprint while today's crossword waits. So a book or a
# dateless puzzle goes to the back, which is where the ordering puts it.
has_date() {   # id -> true when the puzzle file carries a publication DAY
  python3 - "$1" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "tools")
from fetch_puzzle import read_puzzle_file
from puzzle_paths import resolve_puzzle
try:
    puzzle = read_puzzle_file(resolve_puzzle(sys.argv[1]))
except Exception as err:  # noqa: BLE001 — an unreadable file is not a date
    print(f"cannot read {sys.argv[1]} to place it in the queue: {err}", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if "date" in puzzle else 1)
PY
}
dated_unsolved="" dateless_unsolved=""
for num in $unsolved; do
  if has_date "$num"; then
    dated_unsolved="$dated_unsolved $num"
  else
    dateless_unsolved="$dateless_unsolved $num"
  fi
done
# The backlog budget is ANNOTATE_MAX puzzles, cold solves included. `fresh` is
# not cut. Name the ones dropped: the queue line above has already promised
# them by id, and a promise withdrawn in silence reads in the log as a puzzle
# that failed rather than one that was never begun.
pending=$(echo $dated_unsolved $pending $dateless_unsolved)
kept=$(echo $pending | tr ' ' '\n' | grep -v '^$' | head -"$ANNOTATE_MAX" | tr '\n' ' ')
dropped=$(echo $pending | tr ' ' '\n' | grep -v '^$' | tail -n +"$((ANNOTATE_MAX + 1))" | tr '\n' ' ')
[ -n "$dropped" ] &&
  echo "over the ANNOTATE_MAX=$ANNOTATE_MAX backlog budget with the unsolved placed — not solving or annotating yet: $dropped"
pending=$(echo $kept)
# New arrivals first, then the capped backlog (tools/daily_units.py cuts it
# again to what is left of the day's ANNOTATE_MAX): newest-first either way.
pending="${fresh:+$fresh }$pending"

# The burn (tools/prereset_backfill.sh) works the same backlog, newest first,
# for as long as it runs. While it runs the backlog is left to it, so no puzzle
# is bought twice by the two jobs at once; new arrivals stay here. Its lock
# names its pid (see its own lock_is_dead).
burn_pid=$(cat "${CT_WORKTREE_ROOT:-$HOME/.cryptic-teacher}/prereset_backfill/.prereset.lock/pid" 2>/dev/null)
if [ -n "$kept" ] && [ -n "$burn_pid" ] && ps -o command= -p "$burn_pid" 2>/dev/null | grep prereset_backfill >/dev/null; then
  echo "the burn (pid $burn_pid) is draining the backlog; leaving it $kept"
  kept=""
fi
# The index the next tick reads, rebuilt now that this one has chosen.
start_index_rebuild
ANNOTATE_MAX="$ANNOTATE_MAX" ANNOTATE_MAX_MINUTES="$ANNOTATE_MAX_MINUTES" \
  DAILY_FRESH="$fresh" DAILY_PENDING="$kept" DAILY_UNSOLVED="$unsolved" DAILY_MISSES="$misses" \
  python3 tools/unit_queue.py tick daily ${UNIT_QUEUE_DRY:+--dry-run}
