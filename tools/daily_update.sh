#!/bin/bash
# Daily updater for Cryptic Teacher — designed for a cron job on the Mac mini.
#
# What it does:
#   1. Fetches the newest puzzle of every series we follow — the Guardian daily
#      cryptic, the Monday Quiptic (their beginner tier), the Sunday Everyman
#      from the Observer, and the Independent's daily — if we don't have it yet.
#      The Times comes from the times-for-the-times blog, its grids rebuilt
#      from the posts' light lists (step 1b). The blog caches are then re-read
#      into the site's blog hints, tools/data/blog_facts/ (step 1d).
#   2. Re-fetches puzzles whose solutions weren't published yet (Saturday prize
#      crosswords publish theirs about a week late).
#   3. Asks Claude Code (headless) to annotate un-annotated puzzles, newest
#      first, following tools/annotate_prompt.md. Every new arrival is annotated
#      — dated within the last two days, or given its official key tonight —
#      however many there are. ANNOTATE_MAX (default 3) bounds only the rest:
#      answerless puzzles plus the older backlog, on top of the new arrivals.
#      An answerless one is solved cold immediately before its annotation, in
#      the conversation the annotation carries on (tools/puzzle_worker.sh), and
#      never otherwise; a rejected solve skips it.
#      All of it runs only while the account's weekly usage window is under
#      ANNOTATE_MAX_WEEKLY_PCT (default 90) and its five-hour window is under
#      ANNOTATE_MAX_SESSION_PCT (default 90), re-read between puzzles. Stops
#      early if a run fails rather than burning the rest of the quota on doomed
#      attempts — except when the wall-clock cap kills it, which says this grid
#      is lost and nothing about the next one, so the queue carries on.
#      A puzzle that fails, or whose annotation the validator throws away, is
#      recorded with a hash of its inputs (tools/failed_inputs.py) and left out
#      of the queue until those inputs change. Otherwise it would be the newest
#      un-annotated puzzle every night, bought again at full price each time.
#   3c. Reads the bad-hint queue solvers write to from the site, hands the
#      reports to the same headless model to fix, and alerts a person only
#      about the ones it could not close. Before the commit, so a fix reaches
#      the site the same night the report arrived.
#      Each puzzle is validated, committed and pushed on its own as it
#      finishes, by tools/puzzle_worker.sh, the same code the burn
#      (tools/prereset_backfill.sh) runs; the two differ only in scheduling.
#   4. Reindexes, commits whatever else the run wrote, and pushes. The
#      site is built, tested and deployed by .github/workflows/ on that push.
#
# Only work driven by new inputs runs here: tonight's puzzles, posts, keys,
# ratings and reports. A pass over the whole corpus that only a code change
# could alter (a better scan reader, a stricter validator) is run once by
# whoever changes the code, or by CI on the push that carries the change.
#
# Install: household-plugins/cryptic-daily/plugin.toml schedules it in the
# bridge container at 04:45 local, so a run of about two hours is done by 07:00,
# when Paul is up. That is the only schedule this job has, and a second one is
# not a fallback — two copies annotate the same backlog out of the same weekly
# quota. The container works because the credential is a file under
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
# A dropped run's commits (the fetched sources, committed before annotating)
# are pushed by the next start; its uncommitted annotations are not, since
# each is validated against that run's HEAD and may be one it was rejecting.
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

# worker_solve / worker_apply / worker_annotate — one puzzle's model work, the
# same code the burn (tools/prereset_backfill.sh) runs.
. "$REPO/tools/puzzle_worker.sh"

# Keep this run's output where the exit trap can read it back, and report any
# failure line nobody wrote an alert for. The scheduler's .update.log holds every run
# ever, so "grep the log" would re-report last week; this is tonight only.
# Spelled out rather than `mktemp -t cryptic-daily`: -t takes a bare prefix on macOS
# but a template that must contain X's on GNU, so the one spelling cannot mean
# the same thing on both. Every mktemp below is written this way.
RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/cryptic-daily.XXXXXX")"
exec > >(tee -a "$RUN_LOG") 2>&1
trap 'phase_report; sleep 1; alert_run_failures "$RUN_LOG"; rm -f "$RUN_LOG"' EXIT

# Where the night's wall clock went. Every step section opens with
# `phase <name> [minutes]`, and the exit trap prints each phase's duration, so a
# long run says which phase took the time. A phase given minutes is plain
# compute driven by tonight's inputs, and running past them means it is
# re-processing something it already did: that alerts, naming the phase. The
# phases that call claude are left unbudgeted; their calls are capped one by
# one and the weekly usage gate caps the total.
PHASES="" phase_name="" phase_start=$SECONDS phase_budget=""
phase() {
  [ -n "$phase_name" ] &&
    PHASES+="$phase_name $((SECONDS - phase_start)) ${phase_budget:-0}"$'\n'
  phase_name="$1" phase_budget="${2:-}" phase_start=$SECONDS
  [ -n "$phase_name" ] && echo "--- phase $phase_name ($((SECONDS / 60))m in) ---"
  return 0
}
phase_report() {
  phase ""
  local name secs budget over=""
  echo "=== phases, $((SECONDS / 60))m in all ==="
  while read -r name secs budget; do
    [ -n "$name" ] || continue
    printf '  %-14s %5dm %02ds\n' "$name" $((secs / 60)) $((secs % 60))
    [ "$budget" -gt 0 ] && [ "$secs" -gt $((budget * 60)) ] &&
      over+=" $name took $((secs / 60))m (budget ${budget}m);"
  done <<<"$PHASES"
  [ -n "$over" ] || return 0
  # The slowest timed steps travel in the message, so it says why as well as where.
  local slow
  slow=$(sed -nE 's/^(.*: rc=[0-9]+ in ([0-9]+)s)$/\2 \1/p' "$RUN_LOG" |
    sort -rn | head -4 | cut -d' ' -f2- | cut -c1-160)
  alert "the nightly ran $((SECONDS / 60))m, and these compute phases ran past their budget:$over${slow:+ Its slowest steps:}"$'\n'"$slow"
}

echo "=== cryptic-teacher update $(date '+%Y-%m-%d %H:%M') ==="

phase fetch 30
# --- 1. fetch the latest puzzle of every series (exit 3 = nothing new, fine) ---
# Run independently on purpose: one source going down should not cost us the
# others. None failing stops the run — there is usually a backlog worth
# annotating regardless. Cyclops is fortnightly, so fetch_privateeye normally
# returns 3 here; that is "nothing new", not a fault.
#
# Every fetcher with a --latest belongs in this list. A series backfilled but
# left out of it stops at the day it was backfilled and rots from there. Give a new fetcher --latest and add it here in
# the same pass; a backfill that isn't in this loop is already rotting.
FETCHERS="fetch_puzzle fetch_independent fetch_observer fetch_privateeye fetch_globeandmail fetch_metro"
fetch_broken=""
for fetcher in $FETCHERS; do
  python3 "tools/$fetcher.py" --latest
  fetch_rc=$?
  if [ $fetch_rc -ne 0 ] && [ $fetch_rc -ne 3 ]; then
    echo "$fetcher fetch failed (rc=$fetch_rc); continuing"
    fetch_broken="$fetch_broken $fetcher"
  fi
done
# One paper down is weather. Every one of them down at once is us: a changed
# user agent, no network, a python that no longer starts. Nothing new would arrive for as
# long as that lasted, and a site that quietly stops updating looks exactly like
# a site with nothing to update.
# Counted off FETCHERS rather than a literal, so adding a source can't quietly
# turn "all of them" into "all but the new one" and silence this alert.
if [ "$(printf %s "$fetch_broken" | wc -w)" -ge "$(printf %s "$FETCHERS" | wc -w)" ]; then
  alert "every fetcher failed tonight ($fetch_broken) — no new puzzle can arrive from any paper until this is fixed. The rc lines are in .update.log."
fi

phase blog-chains 30
# --- 1b. The Times and the Telegraph, rebuilt from the blogs that solve them ---
# Neither paper publishes its grids, so each puzzle is a chain rather than a
# fetch: cache the new blog posts, parse them, rebuild each grid from its
# light list, file what passes into puzzles/. Each step reads the one before
# it off ~/cryptic-setter-data/<blog>/, so a step that fails ends its chain --
# anything after it would read a half-written file -- except the fetches,
# whose failure only means the cache is as it was last night. The Times's
# second fetch is its own puzzle listing, as the Wayback Machine keeps it,
# which is what dates the prize puzzles the blog writes up a week late.
# Before the queue below reads puzzles/index.json, and the filers do not
# reindex, so it is done here: otherwise the day's puzzles would sit out
# tonight's annotation.
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
        alert "the $paper fetch \`$step\` failed (rc=$step_rc), so tonight's $paper puzzles are filed and dated from what is already cached:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$out" | cut -c1-200)"$'\n'"\`\`\`" ;;
      *)
        alert "the $paper chain stopped at \`$step\` (rc=$step_rc); the steps after it were skipped, so no new $paper puzzle is filed until it is fixed:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$out" | cut -c1-200)"$'\n'"\`\`\`"
        break ;;
    esac
  done
  rm -f "$out"
  return $step_rc
}
blog_filed=0
# Both rebuilds are bounded by wall clock, newest due first: times_grids
# starts no post once its budget is spent, and the rest stay due for the next
# night. A parser change that makes hundreds of old posts due again (a changed
# light list re-dues its failure) drains as fast as the budget allows, and
# can never stretch the nightly; a post already started runs to its node cap.
TIMES_GRID_SECONDS="${TIMES_GRID_SECONDS:-600}"
TELEGRAPH_GRID_SECONDS="${TELEGRAPH_GRID_SECONDS:-600}"
blog_chain Times "fetch_wp_blog.py timesforthetimes" fetch_times_listing.py \
  parse_timesforthetimes.py "times_grids.py --budget-seconds $TIMES_GRID_SECONDS" \
  file_times_puzzles.py && blog_filed=1
blog_chain Telegraph "fetch_wp_blog.py bigdave44" parse_bigdave44.py \
  "times_grids.py --blog bigdave44 --budget-seconds $TELEGRAPH_GRID_SECONDS" \
  file_telegraph_puzzles.py && blog_filed=1
# From 2015 the Telegraph's own bucket is the primary source: tonight's
# puzzles, and blog-rebuilt files of the numbers it serves, refiled as printed.
TELEGRAPH_BUCKET_PER_NIGHT="${TELEGRAPH_BUCKET_PER_NIGHT:-200}"
blog_chain Telegraph "fetch_telegraph.py --holes $TELEGRAPH_BUCKET_PER_NIGHT" && blog_filed=1
# The Globe and Mail prints the Times Quick Cryptic from No 3106: its copy
# witnesses the blog-rebuilt Quick the Times filer would file for the same
# number, which is how a defect of the converter behind every earlier Quick
# shows. Nothing is refiled from it; the filer files those numbers as
# globeandmail already.
GLOBE_XVAL_PER_NIGHT="${GLOBE_XVAL_PER_NIGHT:-60}"
blog_chain Globe "cross_validate.py globe --fetch --limit $GLOBE_XVAL_PER_NIGHT" "cross_validate.py globe"
[ $blog_filed -eq 1 ] && python3 tools/fetch_puzzle.py --reindex

phase ft 30
# --- 1c. The Financial Times, rebuilt from fifteensquared's write-ups ---
# The same chain in one tool: tools/ft_puzzles.py parses the cached posts,
# rebuilds the newest untried grids and files what passes. Bounded, because
# the untried are newest first: tonight's posts and a few of the backlog.
FT_PER_NIGHT="${FT_PER_NIGHT:-12}"
ft_out="$(mktemp "${TMPDIR:-/tmp}/cryptic-ft.XXXXXX")"
if ! python3 tools/fetch_fifteensquared.py --category FT --posts-only >"$ft_out" 2>&1; then
  cat "$ft_out"
  alert "the fifteensquared FT fetch failed, so tonight's FT puzzles are filed from the posts already cached:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$ft_out" | cut -c1-200)"$'\n'"\`\`\`"
fi
if python3 tools/ft_puzzles.py --limit "$FT_PER_NIGHT" >"$ft_out" 2>&1; then
  cat "$ft_out"
  python3 tools/fetch_puzzle.py --reindex
else
  cat "$ft_out"
  alert "tools/ft_puzzles.py failed, so no new FT puzzle is filed until it is fixed:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$ft_out" | cut -c1-200)"$'\n'"\`\`\`"
fi
rm -f "$ft_out"

phase azed 10
# --- 1c1. The Observer's Azed from the Guardian's printable copies ---
# tools/andlit_azed.py fetches the next copies andlit.org.uk's index links
# (2s apart, oldest unfiled first), then files every cached copy whose grid
# and clue list agree. Bounded per night so the archive drains politely.
AZED_PER_NIGHT="${AZED_PER_NIGHT:-40}"
azed_out="$(mktemp "${TMPDIR:-/tmp}/cryptic-azed.XXXXXX")"
if python3 tools/andlit_azed.py nightly --limit "$AZED_PER_NIGHT" >"$azed_out" 2>&1; then
  grep -v '^  No ' "$azed_out"
  grep -q '^filed [1-9]' "$azed_out" && python3 tools/fetch_puzzle.py --reindex
else
  cat "$azed_out"
  alert "tools/andlit_azed.py failed, so no Azed is filed from the Guardian's copies until it is fixed:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$azed_out" | cut -c1-200)"$'\n'"\`\`\`"
fi
rm -f "$azed_out"

phase cross-validate 30
# --- 1c3. Every copy of a puzzle at once (tools/cross_validate.py all) ---
# Each pair above compares ours with one other copy. This puts every copy we
# hold to a vote: the paper's own feed, app or page, fifteensquared,
# bigdave44, timesforthetimes, georgeho, the Globe, the FT's PDFs. A majority
# of three or more fixes our file, its votes in the corroboration ledger; two
# copies that disagree are a lead in cross-validate/all-leads.jsonl. Tonight's
# filings only; cached sources only, nothing is fetched.
blog_chain Corroboration "cross_validate.py all --new --apply" \
  && git status --porcelain -- puzzles | grep -q . && python3 tools/fetch_puzzle.py --reindex

phase blog-facts 30
# --- 1d. Blog hints, re-read off the caches the fetches above just topped up ---
# tools/blog_facts.py joins every cached write-up to the puzzle it explains and
# writes tools/data/blog_facts/, which the site's hints and the validator's
# definition check read. A full parse is ~5 minutes, so --if-changed skips it
# when no cached post, clue or the parser itself has moved since the files were
# written. Its letter_facts pass builds the corpus-wide lexicons here and
# reads the clues on the desktop (a local pool when it is busy or off).
# Before the annotation queue, so tonight's new puzzles are validated against
# their blog. The commit's `git add -A` below picks the files up.
facts_out="$(mktemp "${TMPDIR:-/tmp}/cryptic-facts.XXXXXX")"
step_start=$SECONDS
python3 tools/blog_facts.py --if-changed >"$facts_out" 2>&1
step_rc=$?
cat "$facts_out"
echo "blog_facts: rc=$step_rc in $((SECONDS - step_start))s"
[ $step_rc -eq 0 ] ||
  alert "tools/blog_facts.py failed (rc=$step_rc), so tonight's new puzzles get no blog hints:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$facts_out" | cut -c1-200)"$'\n'"\`\`\`"
rm -f "$facts_out"

phase snitch 30
# --- 1e. The SNITCH's ratings of the Times, which the difficulty index is
# checked against and the Times badges quote a range from. One page, so a
# failure only means last night's ratings stand; the commit's `git add -A`
# below picks up tools/data/snitch.json.
python3 tools/fetch_snitch.py || echo "fetch_snitch failed (rc=$?); continuing with the ratings already held"

# Times for the Times comments: the newest month on disk and any after it are
# refetched, and the comment table rebuilt from the whole cache.
# The table feeds the Times badges, which blend in the solve times commenters
# state (tools/difficulty.py blend()), so a puzzle re-rates as its post gains
# comments at the --reindex below. It leaves the committed table alone when the
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

phase solutions 30
# --- 2. pick up solutions that have since been published (prize puzzles, and
#     every Everyman — its competition window withholds answers for about a
#     week, same shape of problem as the Guardian prize below it) ---
#     A puzzle we solved ourselves is refreshed too, and the night the paper's
#     key lands our fill is marked against it: wrong answers lose the
#     annotations written off them, and the score is alerted rather than left in
#     .update.log. That grade is the only measurement of how often a derived answer is right —
#     it happens once per puzzle, on a night nobody knows in advance, so it has
#     to come and find us.
# A Cyclops its cover page misdates gets the fortnightly cadence's date.
python3 tools/fetch_privateeye.py --backfill-dates
refreshed=$( { python3 tools/fetch_puzzle.py --refresh-unsolved
               python3 tools/fetch_observer.py --refresh-unsolved
               python3 tools/fetch_privateeye.py --refresh-unsolved; } 2>&1 | tee /dev/stderr)
graded=$(printf %s "$refreshed" | grep -E "^BLIND SOLVE GRADED|^  miss ")
# A clean sweep and a bad night are not the same message. Both are worth
# sending — the grade is the only measurement of derived answers and it
# happens on a night nobody knows in advance — but the miss trailer is a lie
# when there are no misses.
if [ -n "$graded" ]; then
  if printf %s "$graded" | grep -q "^  miss "; then
    alert "a puzzle we solved ourselves has been graded against the
paper's published answers:

$graded

Every miss listed above has had its annotation dropped, so those clues are back
in tonight's queue and will be rewritten against the real answer."
  else
    ALERT_ICON="✅" alert "a puzzle we solved ourselves graded CLEAN against the
paper's published answers:

$graded

Nothing was dropped and nothing is queued — every annotation on it was written
off the right answer."
  fi
fi

phase minute 30
# --- 2b. refresh the Minute Cryptic reference corpus ---
# Their hint ladder is the same shape as ours and better written, so we keep a
# local copy of their 55 worked examples to write against; it also archives
# their daily clue, which is only ever available on the day. Costs two HTTP
# requests and no inference, and lands in gitignored tools/data/minutecryptic/,
# so it runs unconditionally and never blocks the puzzle work. Failures print
# and are ignored — a scrape of somebody else's bundle is expected to break the
# day they change it, and that is not a reason to hold back tonight's puzzle.
# The guard says so out loud. Their daily clue is only ever offered on the day,
# so a silent skip is not a deferral, it is a permanent hole in daily.jsonl.
if command -v node >/dev/null 2>&1; then
  node tools/fetch_minutecryptic.js --quiet || echo "WARNING: minutecryptic capture failed"
else
  echo "WARNING: no node on PATH ($PATH) — skipping the minutecryptic capture;" \
       "today's clue is only offered today and will not be recoverable"
fi

# The puzzle files the phases above wrote are the sources' clues, so they are
# committed before anything annotates over them. HEAD is the baseline the
# validator holds every annotated clue to (check_clue_unchanged), and a refile
# that rewords a clue is the source's change, not the annotator's. A rejected
# annotation is reverted to this commit, so the refile it sat on stands.
sources_committed=""
commit_sources() {
  git add -A -- puzzles || return 1
  git diff --cached --quiet -- puzzles && return 0
  git commit -q -m "$(printf 'Daily update: file the fetched puzzles\n\n%s' "$(python3 tools/provenance.py trailer)")" -- puzzles &&
    sources_committed=1
}
commit_sources || alert "the daily update could not commit tonight's fetched puzzles before annotating; a refiled clue will read as the annotator's rewrite"

phase annotate
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
# pending. Number is only a tie-break, for
# the several series that publish on the same morning.
#
# A bulk import gets no special treatment: backfilled puzzles queue by date like
# everything else and are worked newest to oldest. The rate limit below is what
# stops a big import from being a big bill.
ANNOTATE_MAX="${ANNOTATE_MAX:-3}"
# Puzzles whose annotation already failed on the inputs they have now. Selection
# here is by date and nothing else, so without this a puzzle that fails is the
# newest un-annotated puzzle again tomorrow, bought from scratch each time (see
# tools/failed_inputs.py). Excluded before the queues are cut, not skipped inside
# the loop: the cut is the night's whole budget.
#
# Two queues. `fresh` is every new arrival, uncapped: a puzzle dated within the
# last two days, or one whose official key landed tonight (a tracked file that
# had no complete published key at HEAD and has one now — the step 2 refetch).
# `pending` is everything older, newest first, and ANNOTATE_MAX bounds it
# together with tonight's answerless puzzles, which join it in step 3a. Only the usage
# gates below limit `fresh`.
#
# puzzles/index.json is generated and untracked, so the copy on disk here was
# written by whatever code ran last, not by this checkout's. Both queues read
# fields off it and read a missing field as a puzzle with nothing wrong, so an
# index older than a field silently answers "fine" for every puzzle.
# Nine seconds over the whole corpus; the rest of the script reindexes anyway.
python3 tools/fetch_puzzle.py --reindex
annotate_blocked=$(python3 tools/failed_inputs.py skipped annotate)
{ read -r fresh; read -r pending; } < <(python3 - "$ANNOTATE_MAX" "$annotate_blocked" <<'EOF'
import json, subprocess, sys
sys.path.insert(0, "tools")
import provenance
import datetime
from series import puzzle_day, is_first_issue
idx = json.load(open("puzzles/index.json"))
blocked = set(sys.argv[2].split())
cutoff = datetime.date.today() - datetime.timedelta(days=2)

def keyed(text):
    """True when a puzzle file's text carries the paper's complete key."""
    puzzle = json.loads(text)
    return (not provenance.solution_detail(puzzle)
            and all(e.get("solution") for e in puzzle.get("entries", [])))

def show(*args):
    """git's stdout, or "" outside a checkout; a missing git means no key news."""
    run = subprocess.run(["git", *args], capture_output=True, text=True)
    return run.stdout if run.returncode == 0 else ""

keyed_tonight = set()
for path in show("diff", "--name-only", "HEAD", "--", "puzzles/").split():
    try:
        if not keyed(show("show", f"HEAD:{path}") or "{}") and keyed(open(path).read()):
            keyed_tonight.add(path.rsplit("/", 1)[-1].removesuffix(".json"))
    except (OSError, ValueError):
        continue  # deleted or half-written; the validator reports those

# IDs, not numbers: an id is what every step below names and what
# tools/puzzle_paths.py finds a file by, so no consumer has to resolve a number
# two papers could share.
todo = sorted(((puzzle_day(p) or datetime.date.min, p["id"]) for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")
               and p["id"] not in blocked), reverse=True)
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

# Record a lost night against the puzzle's current inputs. failed_inputs.py
# refuses transient reasons (a usage lockout, an expired login, a network
# error), since those runs learned nothing about the grid. Extra arguments go
# straight through, which is how a validator's verdict says --judged.
record_annotate_failure() {   # id, reason, [--judged]
  echo "  $(python3 tools/failed_inputs.py record annotate "$1" --reason "$2" "${@:3}")"
}

# Puzzles the paper hasn't published answers for — Saturday prize crosswords,
# which withhold them for about a week. No solutions means nothing for the
# annotator to explain, so unsolved, the newest and most-visited puzzle on the
# site would sit hintless for its whole first week.
#
# So solve it, as the first half of annotating it: step 3a places it in the
# annotation queue and the loop there solves it immediately before its
# annotation, in the conversation the annotation then carries on. Never as a
# separate pick: a grid solved and not hinted is spend the site never shows. A
# model solves the grid cold, and tools/apply_solution.py
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
# account's weekly window is more than ANNOTATE_MAX_WEEKLY_PCT spent; steps 1,
# 2, 3c and 4 still run, so the newest puzzle is still fetched and published, just
# without hints until the window resets.
#
# The gate fails CLOSED: if it cannot read the quota it skips, and a skipped
# night raises an alert into Discord, so a stalled backlog is as visible as
# overspending. Failing open does not even buy the puzzle it spends for: a read
# that fails every night leaves the gate wide open while the week's quota runs
# down, and the annotation dies on the limit anyway. One day of backlog is
# recoverable; a week of someone's quota spent by a gate that had stopped
# gating is not.
#
# The verdict comes from weekly_usage.py rather than from arithmetic here,
# because "am I over the line" is answerable in cases where "what is the
# percentage" isn't: usage only rises within a window, so even a stale cached
# reading is a floor, and a floor above the limit is a decision: a 10-hour-old
# 75% against a 50% limit is a skip, not blindness.
ANNOTATE_MAX_WEEKLY_PCT="${ANNOTATE_MAX_WEEKLY_PCT:-90}"
# The annotating model. An alias, so it names whichever model it points at
# tonight; the exact id that ran is recorded in each puzzle's
# annotatedBy, and the commit trailer is read back from there.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
# Explicit, because the CLI default differs per model (medium on Opus 5.5,
# high elsewhere) and would change silently when the alias moves.
ANNOTATE_EFFORT="${ANNOTATE_EFFORT:-medium}"
if [ -n "$fresh$pending$unsolved" ] && ! python3 tools/weekly_usage.py --self-test; then
  # The gate's own four cases, run offline before its verdict is believed. A
  # gate whose logic is broken says "spend" as confidently as a working one, so
  # a failing self-test is treated as the worst verdict rather than ignored.
  alert "the weekly usage gate is failing its own self-test, so annotation was skipped. The gate logic itself is wrong — see the SELF-TEST lines in .update.log."
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
      echo "weekly usage under ${ANNOTATE_MAX_WEEKLY_PCT}% — annotating $fresh $pending${unsolved:+, solving first whichever of $unsolved the queue reaches}" ;;
    skip)
      echo "weekly usage over ${ANNOTATE_MAX_WEEKLY_PCT}% — skipping annotation of $fresh $pending${unsolved:+ and solving of $unsolved}"
      fresh=""
      pending=""
      unsolved="" ;;
    *)
      if grep -q "stale /login" "$gate_why"; then
        alert "Claude Code is logged out on this machine, so tonight's annotation was skipped — and every other model call would have failed too, gate or no gate. Run \`claude\` in a terminal and \`/login\`; nothing else here can fix it. The site is fine, the newest puzzle just published without hints."$'\n'"\`\`\`"$'\n'"$(cut -c1-300 "$gate_why")"$'\n'"\`\`\`"
      else
        alert "the weekly usage gate can't read the quota, so tonight's annotation was skipped rather than run ungated. Nothing is broken on the site — the newest puzzle still published, just without hints."$'\n'"\`\`\`"$'\n'"$(cut -c1-300 "$gate_why")"$'\n'"\`\`\`"
      fi
      fresh=""
      pending=""
      unsolved="" ;;
  esac
  rm -f "$gate_why"
fi

# The five-hour window is the one this loop actually spends, so it is re-read
# before every puzzle. Checking it once up front is worthless — it reads near
# zero at 04:45 by construction — and a run checked only then annotates two
# puzzles and dies on the third with "you've hit your limit", a quota
# discovered by crashing into it rather than budgeted.
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
annotated_ok=0
annotated_nums=""
stop_reason=""
# Set when the stop is the five-hour gate: a budget decision, never an alert.
stop_budget=""
# Set when a dead puzzle has already been reported WITH its post-mortem, so the
# run-level summary below does not say the same failure again as a headline.
stop_alerted=""

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
# Puzzles the wall-clock cap killed. Not a reason to stop the run — see the
# `ann_rc = 124` branch — but the night still has to say it happened.
lost_ids=""

phase misses
# --- 2c. learn from the misses step 2 graded ---
# A graded miss is a sample of a class: the reading, rule or check that let a
# wrong answer through will let the next one through too. Each miss gets one
# bounded run of tools/solve_miss_prompt.md, which fixes the class in
# tools/solve_prompt.md or tools/apply_solution.py, or records that nothing
# generalises. Here, ahead of 3a, so a fix already governs tonight's solves; the
# fix rides tonight's commit.
#
# The payload is the gate: tools/solve_misses.py pending lists only misses with
# no record in tools/data/diagnosed_misses.json, so a quiet night costs nothing
# and no miss is bought twice. A run that ends without recording a verdict is
# recorded as unfinished, alerted, and not retried: the same packet would buy
# the same failure.
SOLVE_MISS_MAX_MINUTES="${SOLVE_MISS_MAX_MINUTES:-30}"
misses=$(python3 tools/solve_misses.py pending)
if [ -n "$misses" ] && command -v claude >/dev/null 2>&1; then
  miss_cap="timeout ${SOLVE_MISS_MAX_MINUTES}m"
  command -v timeout >/dev/null 2>&1 || miss_cap=""
  misslog="$(mktemp "${TMPDIR:-/tmp}/cryptic-miss.XXXXXX")"
  while read -r miss_pid miss_eid; do
    [ -n "$miss_pid" ] || continue
    session=$(python3 tools/weekly_usage.py --group session)
    if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
      echo "miss diagnosis: five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — the rest wait for tomorrow"
      break
    fi
    if [ "$(python3 tools/weekly_usage.py --gate "$ANNOTATE_MAX_WEEKLY_PCT" 2>/dev/null)" != spend ]; then
      echo "miss diagnosis: weekly window not under ${ANNOTATE_MAX_WEEKLY_PCT}% — the rest wait for the reset"
      break
    fi
    echo "diagnosing the graded miss $miss_pid $miss_eid with Claude Code... (session ${session:-unknown}%)"
    # shellcheck disable=SC2086 # $miss_cap is a command and its argument, or nothing
    $miss_cap claude -p "Follow tools/solve_miss_prompt.md exactly (it is your system prompt's appendix; do not open the file). This is the miss it is about:

$(python3 tools/solve_misses.py packet "$miss_pid" "$miss_eid" 2>&1)" "${CLAUDE_HEADLESS[@]}" \
      --append-system-prompt-file tools/solve_miss_prompt.md \
      --exclude-dynamic-system-prompt-sections \
      --model "$ANNOTATE_MODEL" \
      --effort "$ANNOTATE_EFFORT" \
      --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(bash tools/test_*),Bash(grep *)" \
      </dev/null >"$misslog" 2>&1
    miss_rc=$?
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
  done <<MISSES
$misses
MISSES
  rm -f "$misslog"
fi

phase work
# --- 3a. place the unsolved in the annotation queue ---
# An answerless puzzle is solved only as the first half of annotating it: the
# loop below solves it immediately before its annotation, and nothing else in
# this script runs a solve. So a grid enters the queue here, where the queue
# would annotate it, and is cut with everything else; one the cut drops is not
# solved tonight either, because a solve nobody hints is spend with nothing to
# show for it on the site.
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
  echo "over the ANNOTATE_MAX=$ANNOTATE_MAX backlog budget with the unsolved placed — not solving or annotating tonight: $dropped"
pending=$(echo $kept)
# New arrivals first, then the capped backlog: newest-first either way.
pending="${fresh:+$fresh }$pending"

if [ -n "$pending" ]; then
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
      echo "  no timeout(1) here, so tonight's runs have no wall-clock cap"
    fi
    for num in $pending; do
      session=$(python3 tools/weekly_usage.py --group session)
      if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
        stop_reason="five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — $num waits for the reset"
        stop_budget=1
        break
      fi
      sidfile="$work_dir/$num.sid"
      # An answerless puzzle is solved here, immediately before the annotation
      # it feeds and nowhere else (see step 3a). A rejected fill skips the
      # puzzle: there is nothing to annotate.
      case " $unsolved " in *" $num "*)
        fill="$work_dir/$num.fill" solvelog="$work_dir/$num.solve.log" verdict="$work_dir/$num.verdict"
        echo "solving puzzle $num cold with Claude Code before annotating it... (session ${session:-unknown}%)"
        worker_solve "$num" "$fill" "$solvelog" "$sidfile"
        tail -40 "$solvelog"
        worker_apply "$num" "$fill" "$solvelog" "$verdict"
        applied=$?
        cat "$verdict"
        if [ "$applied" -ne 0 ]; then
          echo "solve of $num rejected — nothing written, nothing to annotate"
          # The lines travel in the alert. A solve failure is a bug in this
          # repo far more often than a hard crossword, and the reader needs the
          # applier's complaint and the model's last words to tell which.
          [ "$applied" -eq 1 ] &&
            alert "solving $num failed and will not be tried again until its clues, tools/solve_prompt.md or tools/apply_solution.py change — the puzzle ships hintless until then or until the paper publishes its key. The applier said:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$verdict" | cut -c1-200)"$'\n'"\`\`\`"$'\n'"and the solver's last words were:"$'\n'"\`\`\`"$'\n'"$(tail -6 "$solvelog" | cut -c1-200)"$'\n'"\`\`\`"
          continue
        fi ;;
      esac
      echo "annotating puzzle $num with Claude Code... (session ${session:-unknown}%)"
      # The run reads a copy of the puzzle without its solutions detail, which
      # names the blog the key came from (see annotate_check.py VIEW_KEYS).
      # A crashed view leaves the run nothing to read, and the crash is in the
      # tool, so every later puzzle would crash the same way: stop annotating
      # and alert with the traceback rather than pay for sessions that work
      # around a broken checker.
      view_err="$(mktemp "${TMPDIR:-/tmp}/cryptic-view.XXXXXX")"
      if ! ann_file=$(python3 tools/annotate_check.py --view "$num" 2>"$view_err") || [ -z "$ann_file" ]; then
        alert "tools/annotate_check.py --view $num failed, so no puzzle is annotated tonight:"$'\n'"\`\`\`"$'\n'"$(tail -n 20 "$view_err")"$'\n'"\`\`\`"
        rm -f "$view_err"
        stop_reason="annotate_check.py --view crashed on $num"
        break
      fi
      cat "$view_err" >&2
      rm -f "$view_err"
      ann_task="Annotate the cryptic crossword $num in this repo, whose clues and answers are in $ann_file."
      ann_prompt="$ann_task Follow tools/annotate_prompt.md exactly (it is your system prompt's appendix; do not open the file), including running 'python3 tools/annotate_check.py <ID>' until it reports clean. Do not commit — the calling script commits."
      # The conversation is fixed before the first attempt and named in
      # $sidfile (the cold solve's, when there was one), because a run that
      # dies has already been paid for: a retry resumes it.
      ann_note=""
      ann_ok=""
      ann_retried=0
      ann_timeout=""
      while :; do
        worker_annotate "$num" "$run_log" "$sidfile" "$ann_prompt" "$ann_note"
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
        ann_note="Your last turn was cut off for going past the output token limit, so whatever it was writing was never saved. Everything you did BEFORE that turn is intact — read $ann_file to see how far you actually got, and carry on from there rather than starting again. Write in several smaller edits instead of one large one: an edit big enough to hit that limit will be cut off again. Finish the task you were given and run 'python3 tools/annotate_check.py $num' until it reports clean. Do not commit."
        echo "  $num overran the output ceiling — resuming that same session, told to write in smaller edits, rather than paying for it twice"
      done
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
fi

# A run that could not solve some of the clues was already said, per puzzle, by
# tools/puzzle_worker.sh (check_annotation_loss.py).
if [ -n "$annotated_nums" ]; then
  # How many turns a session is taking, logged every night it annotates. A
  # number that only exists when somebody goes looking is a number that gets
  # quoted long after it stopped being true, so it is computed here from the
  # transcripts every run.
  python3 tools/turn_cost.py 2>&1 || true
fi

# Alert on the backlog not moving, not on a command exiting non-zero. A run that
# annotates two puzzles and then meets a rate limit has done its job; a run that
# annotates none has silently stalled, which is this repo's signature failure:
# the log knows and nobody does.
if [ -n "$lost_ids" ]; then
  echo "gave up on$lost_ids after ${ANNOTATE_MAX_MINUTES}m each and carried on with the rest of the queue"
  # A night where every attempt ran out the clock annotated nothing, and the
  # alert below only fires on a stop_reason. Give it one.
  if [ "$annotated_ok" -eq 0 ] && [ -z "$stop_reason" ]; then
    stop_reason="every puzzle tried ran past ${ANNOTATE_MAX_MINUTES}m:$lost_ids"
  fi
fi

if [ -n "$stop_reason" ]; then
  if [ -n "$stop_alerted" ]; then
    # Already sent, with the transcript's own post-mortem attached. Repeating it
    # here as a headline is the same failure twice in a channel with one reader.
    echo "annotated $annotated_ok puzzle(s); the failure above went out with its post-mortem"
  elif [ "$annotated_ok" -eq 0 ] && [ -z "$stop_budget" ]; then
    alert "no puzzle got hints today — $stop_reason. If that mentions authentication the CLI needs a fresh /login; see the CLAUDE_CONFIG_DIR note in daily_update.sh. Full output: .update.log."
  else
    # Reached when the run stopped on purpose rather than on a failure — the
    # five-hour window filling up is a budget decision, not something to wake
    # anybody for, even with nothing annotated; the backfill burn picks the
    # puzzle up after the reset.
    echo "annotated $annotated_ok puzzle(s), then stopped: $stop_reason"
  fi
fi

phase reports
# --- 3c. the bad-hint queue: fix what solvers reported, don't just relay it ---
# Ahead of the commit on purpose. An alert is a fix that has not happened yet:
# a solver reports a wrong hint, a human reads about it hours later, and the
# clue stays wrong until someone sits down with it. Run here, the fix rides
# tonight's commit, push and deploy, and the report is answered on the site by
# morning. A human is woken only for what this pass could not close.
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
if bad_hints=$(python3 tools/reports.py --since 14 2>&1); then
  case "$bad_hints" in
    "no bad-hint reports"*|"") ;;
    *)
      attempted=0
      session=$(python3 tools/weekly_usage.py --group session)
      if ! command -v claude >/dev/null 2>&1; then
        echo "bad-hint queue: no claude CLI, so tonight's reports only get an alert"
      elif [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
        echo "bad-hint queue: five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — the fix pass waits for the reset"
      else
        fixlog="${TMPDIR:-/tmp}/cryptic-reports.log"
        echo "fixing $(printf '%s' "$bad_hints" | grep -c '^  r:') reported hint(s) with Claude Code... (session ${session:-unknown}%)"
        claude -p "Follow tools/report_fix_prompt.md exactly (it is your system prompt's appendix; do not open the file). These are the reports it is about:

$bad_hints" "${CLAUDE_HEADLESS[@]}" \
          --append-system-prompt-file tools/report_fix_prompt.md \
          --exclude-dynamic-system-prompt-sections \
          --model "$ANNOTATE_MODEL" \
          --effort "$ANNOTATE_EFFORT" \
          --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
          --max-turns 120 >"$fixlog" 2>&1
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
        "no bad-hint reports"*|"") echo "bad-hint queue: cleared by tonight's fix pass" ;;
        *) alert "solvers reported bad hints that tonight's run did not close. Each one is a
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

phase commit 30
# --- 4. reindex, commit the rest ---
python3 tools/fetch_puzzle.py --reindex
# Tonight's puzzles were validated, committed and pushed one at a time by
# tools/puzzle_worker.sh as each finished; this commit sweeps up everything
# else the run wrote.
# The annotation payloads apply_annotations.py consumed. Gitignored (tools/_*),
# so this is housekeeping rather than safety — but nothing else clears them, and
# they pile up one per puzzle.
rm -f "$REPO/tools/_ann_"*.json "$REPO/tools/_puzzle_"*.json

if [ -n "$(git status --porcelain)" ] || [ -n "$sources_committed" ]; then
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
  git diff --cached --quiet ||
    git commit -m "$(printf 'Daily update: fetch latest cryptic / annotate backlog\n\n%s' "$(python3 tools/provenance.py trailer)")"
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
      alert "the daily update committed today's puzzle but could not push it, so the site is still showing yesterday's. ${stuck:+The rebase onto origin/master conflicted in: $stuck}See the tail of .update.log."
    fi
  fi
else
  echo "nothing to commit"
fi

echo "=== done ==="
