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
#      tonight's cold solves plus the older backlog, on top of the new arrivals.
#      All of it runs only while the account's weekly usage window is under
#      ANNOTATE_MAX_WEEKLY_PCT (default 90) and its five-hour window is under
#      ANNOTATE_MAX_SESSION_PCT (default 70), re-read between puzzles. Stops
#      early if a run fails rather than burning the rest of the quota on doomed
#      attempts — except when the wall-clock cap kills it, which says this grid
#      is lost and nothing about the next one, so the queue carries on.
#      A puzzle that fails, or whose annotation the validator throws away, is
#      recorded with a hash of its inputs (tools/failed_inputs.py) and left out
#      of the queue until those inputs change. Otherwise it would be the newest
#      un-annotated puzzle every night, bought again at full price each time.
#   4. Reads the bad-hint queue solvers write to from the site, hands the
#      reports to the same headless model to fix, and alerts a person only
#      about the ones it could not close. Before the commit, so a fix reaches
#      the site the same night the report arrived.
#   5. Validates, reindexes, rebuilds the static crawlable pages
#      (tools/build_seo_pages.py — one per puzzle, plus the hub, the tutorial
#      and the sitemap) so the checks have something to read, and commits (and
#      pushes, if a remote is set up). The pages themselves are not committed:
#      .github/workflows/pages.yml rebuilds and deploys them on every push.
#
# Install: a line in the bridge container's tools/crontab (household repo),
# 06:15 local. That is the only schedule this job has, and a second one is not
# a fallback — two copies annotate the same backlog out of the same weekly
# quota. Cron works here because the credential is a file under
# CLAUDE_CONFIG_DIR. On a Mac it does not: there the `claude` CLI reads the
# *login* keychain, which cron cannot unlock, and every run dies with "Not
# logged in" — so scheduling this on a Mac means launchctl, and means deleting
# the crontab line rather than adding to it.
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
# A scheduler runs with a bare PATH (/usr/bin:/bin), so the `claude` CLI is
# invisible and every run silently skips annotation.
. "$REPO/tools/claude_path.sh"
# The CLI keys its keychain item by CLAUDE_CONFIG_DIR: the entry is named
# "Claude Code-credentials-<first 8 of sha256(configdir)>", and with the variable
# unset it reads the legacy un-suffixed "Claude Code-credentials" instead. A
# file-based /login on 2026-07-31 wrote the suffixed entry and emptied the legacy
# one, so from then until 2026-08-06 every run of this script died on "Failed to
# authenticate: OAuth session expired and could not be refreshed" and annotated
# nothing for seven days — while interactive sessions and the Discord bridge
# (which sets this variable) kept working, so nothing looked broken. Set it
# here rather than only in the scheduler's environment: the failure is silent
# and non-obvious, and this way it survives being run by hand too.
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
# for why: the seven silent days above are what a log-only failure looks like.
. "$REPO/tools/alert.sh"

# session_id / session_exists — what lets a failed annotation resume instead of
# being bought a second time.
. "$REPO/tools/claude_session.sh"

# Keep this run's output where the exit trap can read it back, and report any
# failure line nobody wrote an alert for. launchd's .update.log holds every run
# ever, so "grep the log" would re-report last week; this is tonight only.
# Spelled out rather than `mktemp -t cryptic-daily`: -t takes a bare prefix on macOS
# but a template that must contain X's on GNU, so the one spelling cannot mean
# the same thing on both. Every mktemp below is written this way.
RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/cryptic-daily.XXXXXX")"
exec > >(tee -a "$RUN_LOG") 2>&1
trap 'sleep 1; alert_run_failures "$RUN_LOG"; rm -f "$RUN_LOG"' EXIT

echo "=== cryptic-teacher update $(date '+%Y-%m-%d %H:%M') ==="

# A published key that last night's blind annotation hid and never put back.
# First thing, before the fetchers: they rewrite puzzle files, and one that
# merged into a blanked grid would make the loss permanent. No-op on any normal
# night — see tools/blind_annotate.py.
python3 tools/blind_annotate.py restore

# --- 1. fetch the latest puzzle of every series (exit 3 = nothing new, fine) ---
# Run independently on purpose: one source going down should not cost us the
# others. None failing stops the run — there is usually a backlog worth
# annotating regardless. Cyclops is fortnightly, so fetch_privateeye normally
# returns 3 here; that is "nothing new", not a fault.
#
# Every fetcher with a --latest belongs in this list. A series backfilled but
# left out of it stops at the day it was backfilled and rots from there, which
# is what happened to Cyclops. Give a new fetcher --latest and add it here in
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
blog_chain Times "fetch_wp_blog.py timesforthetimes" fetch_times_listing.py \
  parse_timesforthetimes.py times_grids.py file_times_puzzles.py && blog_filed=1
# The Telegraph's rebuild is bounded, newest untried first: tonight's posts
# and a slice of the ~10,000-puzzle archive behind them.
TELEGRAPH_PER_NIGHT="${TELEGRAPH_PER_NIGHT:-40}"
blog_chain Telegraph "fetch_wp_blog.py bigdave44" parse_bigdave44.py \
  "times_grids.py --blog bigdave44 --limit $TELEGRAPH_PER_NIGHT" \
  file_telegraph_puzzles.py && blog_filed=1
[ $blog_filed -eq 1 ] && python3 tools/fetch_puzzle.py --reindex

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

# --- 1d. Blog hints, re-read off the caches the fetches above just topped up ---
# tools/blog_facts.py joins every cached write-up to the puzzle it explains and
# writes tools/data/blog_facts/, which the site's hints and the validator's
# definition check read. A full parse is ~5 minutes, so --if-changed skips it
# when no cached post, clue or the parser itself has moved since the files were
# written. Before the annotation queue, so tonight's new puzzles are validated
# against their blog. The commit's `git add -A` below picks the files up.
facts_out="$(mktemp "${TMPDIR:-/tmp}/cryptic-facts.XXXXXX")"
step_start=$SECONDS
python3 tools/blog_facts.py --if-changed >"$facts_out" 2>&1
step_rc=$?
cat "$facts_out"
echo "blog_facts: rc=$step_rc in $((SECONDS - step_start))s"
[ $step_rc -eq 0 ] ||
  alert "tools/blog_facts.py failed (rc=$step_rc), so tonight's new puzzles get no blog hints:"$'\n'"\`\`\`"$'\n'"$(tail -12 "$facts_out" | cut -c1-200)"$'\n'"\`\`\`"
rm -f "$facts_out"

# --- 1e. The SNITCH's ratings of the Times, which the difficulty index is
# checked against and the Times badges quote a range from. One page, so a
# failure only means last night's ratings stand; the commit's `git add -A`
# below picks up tools/data/snitch.json.
python3 tools/fetch_snitch.py || echo "fetch_snitch failed (rc=$?); continuing with the ratings already held"

# What we hold of every series, printed every night whether or not anything is
# wrong, because the two ways a series dies are both silent: a fetcher that can
# only ever get "today" leaves its series one puzzle deep forever, and a feed
# that stops answering leaves it frozen at the day it broke. The nightly run
# cannot tell either case from a quiet night — it fetched, nothing failed —
# so until 2026-09-17 the only thing that ever noticed was Paul looking at the
# site and counting. The full table goes to the log; only a series that has gone
# QUIET raises an alert, because an unfinished backfill would fire the same
# alert every night until the walk ends, and an alert that always fires is not
# read.
python3 tools/coverage_report.py || true
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

# --- 2. pick up solutions that have since been published (prize puzzles, and
#     every Everyman — its competition window withholds answers for about a
#     week, same shape of problem as the Guardian prize below it) ---
#     A puzzle we solved ourselves is refreshed too, and the night the paper's
#     key lands our fill is marked against it: wrong answers lose the
#     annotations written off them, and the score is alerted rather than left in
#     .update.log. That grade is the whole measurement behind ANNOTATE_BLIND —
#     it happens once per puzzle, on a night nobody knows in advance, so it has
#     to come and find us.
# A Cyclops its cover page misdates gets the fortnightly cadence's date.
python3 tools/fetch_privateeye.py --backfill-dates
refreshed=$( { python3 tools/fetch_puzzle.py --refresh-unsolved
               python3 tools/fetch_observer.py --refresh-unsolved
               python3 tools/fetch_privateeye.py --refresh-unsolved; } 2>&1 | tee /dev/stderr)
graded=$(printf %s "$refreshed" | grep -E "^BLIND SOLVE GRADED|^  miss ")
# A clean sweep and a bad night are not the same message. Both are worth
# sending — the grade is the whole measurement behind ANNOTATE_BLIND and it
# happens on a night nobody knows in advance — but the miss trailer is a lie
# when there are no misses, and 28/28 went out under a ⚠️ saying every miss
# above had had its annotation dropped.
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

# --- 2b. refresh the Minute Cryptic reference corpus ---
# Their hint ladder is the same shape as ours and better written, so we keep a
# local copy of their 55 worked examples to write against; it also archives
# their daily clue, which is only ever available on the day. Costs two HTTP
# requests and no inference, and lands in gitignored tools/data/minutecryptic/,
# so it runs unconditionally and never blocks the puzzle work. Failures print
# and are ignored — a scrape of somebody else's bundle is expected to break the
# day they change it, and that is not a reason to hold back tonight's puzzle.
# The guard says so out loud. Their daily clue is only ever offered on the day,
# so a silent skip is not a deferral, it is a permanent hole in daily.jsonl --
# eleven days of them, when node went missing between 2026-08-28 and the
# container cutover and this printed nothing either way.
if command -v node >/dev/null 2>&1; then
  node tools/fetch_minutecryptic.js --quiet || echo "WARNING: minutecryptic capture failed"
else
  echo "WARNING: no node on PATH ($PATH) — skipping the minutecryptic capture;" \
       "today's clue is only offered today and will not be recoverable"
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
# together with tonight's cold solves, which join it in step 3a. Only the usage
# gates below limit `fresh`.
#
# puzzles/index.json is generated and untracked, so the copy on disk here was
# written by whatever code ran last, not by this checkout's. Both queues read
# fields off it and read a missing field as a puzzle with nothing wrong, so an
# index older than a field silently answers "fine" for every puzzle — which is
# how cryptic-24577 was handed to a model the night clue counts were added.
# Nine seconds over the whole corpus; the rest of the script reindexes anyway.
python3 tools/fetch_puzzle.py --reindex
annotate_blocked=$(python3 tools/failed_inputs.py skipped annotate)
{ read -r fresh; read -r pending; } < <(python3 - "$ANNOTATE_MAX" "$annotate_blocked" <<'EOF'
import json, subprocess, sys, time
sys.path.insert(0, "tools")
from series import date_ms
idx = json.load(open("puzzles/index.json"))
blocked = set(sys.argv[2].split())
FRESH_MS = 2 * 86400 * 1000
cutoff = time.time() * 1000 - FRESH_MS

def keyed(text):
    """True when a puzzle file's text carries the paper's complete key."""
    puzzle = json.loads(text)
    return (not puzzle.get("solutionSource")
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

# IDs, not numbers: puzzles/<id>.json is what every step below names, so no
# consumer has to resolve a number two papers could share.
todo = sorted(((date_ms(p.get("date")) or 0, p["id"]) for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")
               and p["id"] not in blocked), reverse=True)
fresh = [i for d, i in todo if d >= cutoff or i in keyed_tonight]
older = [i for _, i in todo if i not in fresh]
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
# Five a night, which is a ceiling and not a target: the queue is every puzzle we
# hold with no answers in it, and on a normal night that queue is empty. It fills
# in bursts, not one at a time — a Cyclops arrives answer-stripped and waits days
# for fifteensquared, a Saturday prize waits a week for its key, and with eight
# series those waits overlap. A limit of one made the burst take a working week
# to clear, and the puzzles came out of it newest-first, so the oldest answerless
# grid was the last one ever looked at.
#
# The ceiling is not a cost decision: a cold solve is the CHEAP job here — around
# 10-15 turns against an annotation's 40-90, and a third of the spend once cache
# reads are priced at their tenth. Raising SOLVE_MAX is not what will blow the
# budget. The weekly and five-hour usage gates below are what bounds it.
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
from series import date_ms
limit, tried = int(sys.argv[1]), set(sys.argv[2].split())
idx = json.load(open("puzzles/index.json"))
unsolved_ids = {p["id"] for p in idx["puzzles"] if not p.get("hasSolutions")}

# A grid a model cannot READ is not a solve it can fail; it is a puzzle we hold
# a picture of. cryptic-24577 has all 28 clues printed blank and no answers, so
# it was the newest answerless puzzle every night, took a full cold solve, and
# raised "gave up after 1 attempt" — an alert naming the model for a hole in the
# data. 18 puzzles are in that state today. They are not queued at all, which is
# why nothing here alerts: there is no failure, only a fetch that came back
# empty, and the thing that fixes it is re-fetching the clue text.
#
# The line is a majority, not "any clue at all". Unclued entries have to come
# out of the crossings, and the crossing check in apply_solution.py is the only
# thing between a guess and the published site — it cannot tell an invented fill
# that happens to interlock from a solved one. A gap or two the rest of the grid
# pins down is fine; a minority of readable clues means the model is writing the
# puzzle, so those wait for the clue text like the blank ones do.
readable = {}  # id -> (present, total), only for puzzles the index flags
for p in idx["puzzles"]:
    cov = p.get("clues")  # absent means every entry carries a clue
    if cov and p["id"] in unsolved_ids:
        readable[p["id"]] = (cov["present"], cov["total"])
unreadable = {i for i, (present, total) in readable.items() if present * 2 <= total}
if unreadable:
    print("not queued for a cold solve, too little clue text to read: "
          + ", ".join(f"{i} ({readable[i][0]}/{readable[i][1]} clues)"
                      for i in sorted(unreadable)), file=sys.stderr)
todo = sorted(((date_ms(p.get("date")) or 0, p["id"]) for p in idx["puzzles"]
               if p["id"] in unsolved_ids and p["id"] not in unreadable
               and p["id"] not in tried), reverse=True)
print(" ".join(i for _, i in todo[:limit]))
EOF
)
# How many of both queues are held out on a recorded failure, so the log says
# what the queues above left out and not only what they chose.
python3 tools/failed_inputs.py summary

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
ANNOTATE_MAX_WEEKLY_PCT="${ANNOTATE_MAX_WEEKLY_PCT:-90}"
# The annotating model. An alias, so it names whichever model it points at
# tonight; the exact id that ran is recorded in each puzzle's
# provenance.annotatedBy, and the commit trailer is read back from there.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
# Annotate without being shown the published answers, and grade what the model
# derives against them afterwards. See tools/blind_annotate.py for what this
# measures that the sighted path cannot.
#
# Off by default: the trial ran 2026-09-06 to 09-17 and the numbers are in the
# commit that turned it off. Set ANNOTATE_BLIND=1 to run a blind night; the
# machinery, the grading and blind_misses.json all still work. The default
# lives here rather than in a scheduler's environment because the repo is the
# only thing that survives the machine, and a night whose mode was set
# somewhere else cannot be read back out of the log.
ANNOTATE_BLIND="${ANNOTATE_BLIND:-}"
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
  # reason instead of pointing at a log. "can't read the quota" was the same
  # sentence whether the API was down or the CLI was simply logged out — and
  # those need opposite responses, since a logged-out CLI means nothing would
  # have run tonight regardless of what the gate decided.
  gate_why=$(mktemp)
  gate_verdict=$(python3 tools/weekly_usage.py --gate "$ANNOTATE_MAX_WEEKLY_PCT" 2>"$gate_why")
  cat "$gate_why" >&2
  case "$gate_verdict" in
    spend)
      echo "weekly usage under ${ANNOTATE_MAX_WEEKLY_PCT}% — annotating $fresh $pending${unsolved:+, solving $unsolved}" ;;
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
# zero at 06:15 by construction — and that is why runs kept annotating two
# puzzles and then dying on the third with "you've hit your limit", which is a
# quota being discovered by crashing into it rather than being budgeted.
ANNOTATE_MAX_SESSION_PCT="${ANNOTATE_MAX_SESSION_PCT:-70}"
# Turns are the wrong unit to bound a run by, because one turn is not one price.
# A turn cut off for overrunning the output ceiling emits no tool call, so the
# CLI keeps its --max-turns budget intact and simply tries again; the ceiling is
# 128k output tokens and takes ~25 minutes to reach. independent-12456 did that
# six times inside one run on 2026-09-11 — 36 turns, 1.16M output tokens, four
# hours, and not one byte written to the puzzle. Nothing in this script could see
# it: the retry below only fires when the CLI EXITS saying "output token
# maximum", and a run that absorbs the overrun never exits at all.
# So bound the wall clock as well. A puzzle that is going to be annotated is
# annotated in well under an hour (23 and 68 minutes, the two that finished that
# same night); one still going at ANNOTATE_MAX_MINUTES is not slow, it is lost,
# and it is recorded against the puzzle like any other failure.
ANNOTATE_MAX_MINUTES="${ANNOTATE_MAX_MINUTES:-90}"
annotated_ok=0
annotated_nums=""
stop_reason=""
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

# Both meters before any of tonight's spend, so the run can price a five-hour
# window on its way out. What a window is worth is the number the pre-reset burn
# starts on, and until now it was only ever measured DURING a burn — once a
# week, on the night it was already too late to move the start. It moved by a
# factor of 1.7 between two of those on 2026-09-08 and nothing here noticed for
# six days. An empty reading just makes the pair unusable below.
spend_weekly_before=$(python3 tools/weekly_usage.py --group weekly 2>/dev/null)
spend_session_before=$(python3 tools/weekly_usage.py --group session 2>/dev/null)

# --- 3a. solve the unsolved, so step 3b has something to annotate ---
# Runs before the annotation loop and feeds it: a grid solved tonight joins the
# front of the capped backlog queue (`pending`, behind `fresh`), because it is
# by definition the newest puzzle there and the one people are actually looking
# at. Same session gate as annotation, and
# the same trailer, since it is the same model spending the same quota.
#
# "By definition the newest" stopped being true when the book reprints arrived.
# A book reprint is dated only by its book's year ("1995": no volume prints
# the day a puzzle ran), so both queues above sort it behind every day-dated
# puzzle, deliberately: the backfill does
# today's crosswords first and gets to a 1970s reprint eventually. Prepending
# one here would undo that at the last moment and spend a place in tonight's
# ANNOTATE_MAX on a reprint, dropping a puzzle somebody is solving today off the
# end of the queue. So a day-dated solve goes to the front and a year-only or
# dateless one to the back, which is where the ordering had it all along.
has_date() {   # id -> true when the puzzle file carries a publication DAY
  python3 - "$1" <<'EOF'
import sys
from pathlib import Path
sys.path.insert(0, "tools")
from fetch_puzzle import PUZZLE_DIR, read_puzzle_file
from series import is_year
try:
    puzzle = read_puzzle_file(PUZZLE_DIR / f"{sys.argv[1]}.json")
except Exception as err:  # noqa: BLE001 — an unreadable file is not a date
    print(f"cannot read {sys.argv[1]} to place it in the queue: {err}", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if puzzle.get("date") and not is_year(puzzle["date"]) else 1)
EOF
}
solved_ok=0
# id:session for every grid solved tonight, so the annotation below can carry on
# in the conversation that worked it out. A "$num:$sid" list rather than an
# associative array, because bash 3.2 has no `declare -A`.
solve_sids=""
solve_session_of() { printf '%s\n' $solve_sids | sed -n "s/^$1://p" | tail -1; }
if [ -n "$unsolved" ] && command -v claude >/dev/null 2>&1; then
  for num in $unsolved; do
    session=$(python3 tools/weekly_usage.py --group session)
    if [ -n "$session" ] && [ "$session" -gt "$ANNOTATE_MAX_SESSION_PCT" ]; then
      stop_reason="five-hour window ${session}% spent (limit ${ANNOTATE_MAX_SESSION_PCT}%) — solving $num waits for the reset"
      break
    fi
    fill="${TMPDIR:-/tmp}/cryptic-fill-$num.json"
    solvelog="${TMPDIR:-/tmp}/cryptic-solve-$num.log"
    verdict="${TMPDIR:-/tmp}/cryptic-verdict-$num.log"
    rm -f "$fill"
    echo "solving puzzle $num cold with Claude Code... (session ${session:-unknown}%)"
    # Named, so the annotation can resume it. Working an answer out and
    # explaining how it was worked out are the same reasoning, and this is the
    # only place the second half is still bought twice.
    solve_sid=$(session_id) || solve_sid=""
    solve_sess=()
    [ -n "$solve_sid" ] && solve_sess=(--session-id "$solve_sid")
    claude -p "Solve the cryptic crossword in puzzles/$num.json in this repo. Its answers have not been published, so there is no key: follow tools/solve_prompt.md exactly, write your fill to $fill, and iterate against 'python3 tools/apply_solution.py $num --fill $fill --check-only' until every crossing agrees. Do not write to puzzles/ — the calling script applies the fill." \
      "${solve_sess[@]}" \
      --model "$ANNOTATE_MODEL" \
      --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
      --max-turns 120 >"$solvelog" 2>&1
    tail -40 "$solvelog"
    # The verdict comes from the checker, not from the model's own report. A
    # run can exit 0 having given up, and did — the check is what decides. It is
    # captured rather than only printed, because the reason a fill was rejected
    # is the entire content of the give-up alert below.
    if [ -s "$fill" ]; then
      python3 tools/apply_solution.py "$num" --fill "$fill" --model "$ANNOTATE_MODEL" >"$verdict" 2>&1
      applied=$?
    else
      echo "the solver finished without writing a fill to $fill at all" >"$verdict"
      applied=1
    fi
    cat "$verdict"
    if [ "$applied" -eq 0 ]; then
      solved_ok=$((solved_ok + 1))
      if has_date "$num"; then
        pending="$num $pending"
      else
        echo "  $num has no date — annotating it after tonight's dated puzzles, not before"
        pending="$pending $num"
      fi
      solve_sids="$solve_sids $num:$solve_sid"
    else
      echo "solve of $num rejected — nothing written"
      # A fill the applier refused is its verdict on the puzzle. No fill at all
      # means the CLI stopped, and its last line says whether that was transient.
      judged="" said="$solvelog"
      [ -s "$fill" ] && judged=--judged said="$verdict"
      # shellcheck disable=SC2086 # $judged is one flag or nothing
      if python3 tools/failed_inputs.py record solve "$num" $judged \
           --reason "$(grep -v '^[[:space:]]*$' "$said" | tail -1 | cut -c1-200)"; then
        # The lines travel in the alert. A solve failure is a bug in this repo
        # far more often than a hard crossword, and the reader needs the
        # applier's complaint and the model's last words to tell which.
        alert "solving $num failed and will not be tried again until its clues, tools/solve_prompt.md or tools/apply_solution.py change — the puzzle ships hintless until then or until the paper publishes its key. The applier said:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$verdict" | cut -c1-200)"$'\n'"\`\`\`"$'\n'"and the solver's last words were:"$'\n'"\`\`\`"$'\n'"$(tail -6 "$solvelog" | cut -c1-200)"$'\n'"\`\`\`"
      fi
    fi
    rm -f "$fill" "$solvelog" "$verdict"
  done
  # The backlog budget is still ANNOTATE_MAX puzzles, cold solves included.
  # Solving adds its puzzle, so a backlog already at the cap loses its last
  # entry here — the dateless reprint itself when that is what was solved, and
  # the oldest backlog puzzle when it is not. `fresh` is not cut. Name the ones
  # being dropped: the queue line above has already promised them by id, and a
  # promise withdrawn in silence reads in the log as a puzzle that failed rather
  # than one that was never begun.
  kept=$(echo $pending | tr ' ' '\n' | grep -v '^$' | head -"$ANNOTATE_MAX" | tr '\n' ' ')
  dropped=$(echo $pending | tr ' ' '\n' | grep -v '^$' | tail -n +"$((ANNOTATE_MAX + 1))" | tr '\n' ' ')
  [ -n "$dropped" ] &&
    echo "over the ANNOTATE_MAX=$ANNOTATE_MAX backlog budget once solving was prepended — not annotating tonight: $dropped"
  pending=$kept
fi
# New arrivals first, then the capped backlog: newest-first either way.
pending="${fresh:+$fresh }$pending"

if [ -n "$pending" ]; then
  # Restate the controlled vocabulary and the validator's limits in the prompt
  # from the code that enforces them, BEFORE the run reads it. A rule the run has
  # to go and grep for is a rule the prompt did not state, and it was opening
  # app.js and the validator several times a puzzle to find these.
  python3 tools/build_annotate_prompt.py
  if command -v claude >/dev/null 2>&1; then
    run_log="$(mktemp "${TMPDIR:-/tmp}/cryptic-annotate.XXXXXX")"
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
      # Web lookup belongs to the annotate call and to no other: a clue nobody
      # can parse ships with no teaching ladder, so a solvers' blog is worth a
      # fetch as a last resort (disclosed by tools/annotate_check.py only once
      # every clue but the last few is done, never up front). The cold
      # solve above gets none on purpose — the paper's answers are unpublished
      # but the blogs are not, and a solve that reads the answers measures
      # nothing.
      # Blind mode hides the published key for the duration of this one call,
      # then restores it and grades what the model derived. Same puzzle, same
      # single pass, same bill — the comparison is against the sighted runs
      # already in the corpus, so nothing is ever annotated twice. Web tools
      # come off for the same reason the cold solve never had them: a solvers'
      # blog carries the answers, and a blind run that reads one measures
      # nothing. A puzzle with no key to hide (a prize grid we solved
      # ourselves) is annotated sighted as usual.
      ann_tools="Read,Write,Edit,Bash(python3 *),Bash(node *),WebSearch,WebFetch"
      ann_turns=80
      # The run reads a copy of the puzzle without solutionSource, which names
      # the blog the key came from (see annotate_check.py VIEW_KEYS). Blind runs
      # have no web and write their answers into the puzzle itself.
      ann_file=$(python3 tools/annotate_check.py --view "$num")
      ann_task="Annotate the cryptic crossword $num in this repo, whose clues and answers are in $ann_file."
      if [ -n "$ANNOTATE_BLIND" ] && python3 tools/blind_annotate.py hide "$num"; then
        ann_file="puzzles/$num.json"
        ann_tools="Read,Write,Edit,Bash(python3 *),Bash(node *)"
        ann_turns=120
        ann_task="Solve AND annotate the cryptic crossword in puzzles/$num.json in this repo. Its \"solution\" fields are deliberately empty: the answers are not published to you, so work each one out from the clue and the crossings, and write what you derive into that entry's \"solution\" field as you go. Do not look for the answers anywhere else in the repo, in git history, or on the web — a derived answer is the point. Where you cannot get an answer with confidence, leave its solution empty and its annotation null rather than guessing."
      fi
      # One session id per puzzle, fixed before the first attempt, because a run
      # that dies has already been paid for: it read the grid, worked out the
      # wordplay and wrote some of it down, and a fresh -p buys every bit of
      # that again. --resume replays the transcript and carries on from it.
      ann_sid=$(session_id) || ann_sid=""
      ann_sess=(--session-id "$ann_sid")
      ann_prompt="$ann_task Follow the instructions in tools/annotate_prompt.md exactly, including running 'python3 tools/annotate_check.py <ID>' until it reports clean. Do not commit — the calling script commits."
      # This grid may have been solved cold half an hour ago in a conversation
      # that is still on disk. That run derived every answer and the wordplay
      # that reached it, which is exactly what an annotation has to say;
      # starting fresh hands the model a key and makes it work backwards to
      # reasoning it already did. It cannot work from memory alone -- the
      # transcript ends before apply_solution.py wrote the fill in -- so the
      # prompt sends it back to the file.
      solve_prior=$(solve_session_of "$num")
      if session_exists "$solve_prior"; then
        ann_sid="$solve_prior"
        ann_sess=(--resume "$ann_sid")
        ann_prompt="You solved this crossword earlier in this conversation, and your fill has since been written into $ann_file. Read the file as it now stands rather than working from memory, then annotate it from the wordplay you used to derive each answer. $ann_prompt"
        echo "  $num was solved cold tonight — annotating in that same conversation rather than from a cold start"
      fi
      ann_ok=""
      ann_retried=0
      ann_timeout=""
      # Unquoted on purpose: empty means no cap, and neither field can contain a
      # space. `timeout` is GNU and the nightly runs in the Linux container; a
      # by-hand run on the Mac says so rather than silently going uncapped.
      ann_cap="timeout ${ANNOTATE_MAX_MINUTES}m"
      if ! command -v timeout >/dev/null 2>&1; then
        ann_cap=""
        echo "  no timeout(1) here, so $num runs with no wall-clock cap"
      fi
      while :; do
        # shellcheck disable=SC2086
        $ann_cap claude -p "$ann_prompt" "${ann_sess[@]}" \
            --model "$ANNOTATE_MODEL" \
            --allowedTools "$ann_tools" \
            --max-turns "$ann_turns" 2>&1 | tee "$run_log"
        ann_rc=$?
        [ "$ann_rc" = 0 ] && ann_ok=1
        [ -n "$ann_ok" ] && break
        # The cap fired. Say so here rather than below, because below reads the
        # reason off the CLI's last line and a killed CLI never printed one —
        # that is how this failure reached the ledger as "independent-12456
        # failed:" with nothing after the colon.
        # This puzzle is lost; the night is not. The cap firing says the model
        # is stuck on THIS grid — it says nothing about the next one, and the
        # loop re-reads the five-hour window at the top of every iteration, so
        # carrying on cannot outspend the gate. It used to `break 2` here, and
        # that is why 2026-09-12 published one puzzle instead of three:
        # independent-12459 ran out the clock and took cryptic-30109, which
        # nothing had tried yet, down with it.
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
        ann_sess=(--resume "$ann_sid")
        ann_prompt="Your last turn was cut off for going past the output token limit, so whatever it was writing was never saved. Everything you did BEFORE that turn is intact — read $ann_file to see how far you actually got, and carry on from there rather than starting again. Write in several smaller edits instead of one large one: an edit big enough to hit that limit will be cut off again. Finish the task you were given and run 'python3 tools/annotate_check.py $num' until it reports clean. Do not commit."
        echo "  $num overran the output ceiling — resuming that same session, told to write in smaller edits, rather than paying for it twice"
      done
      if [ -n "$ann_ok" ]; then
        annotated_ok=$((annotated_ok + 1))
        annotated_nums="$annotated_nums $num"
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
        # bought again from an empty context. That is what happened to
        # indysunday-1906 after 2026-09-06, and it escaped a second full run only
        # because a person annotated it by hand.
        record_annotate_failure "$num" "$stop_reason"
        # Every dead puzzle is reported, not only a night that annotated none.
        # A run that got two and lost one used to say so with `echo` and wake
        # nobody, so 2026-09-10 and 09-12 each lost a puzzle in silence and the
        # first anyone knew was the site being a day short.
        annotate_alert "$num" "$stop_reason" "$ann_sid"
        break
      fi
    done
    # After the loop, not inside it: the failure branch above breaks out, and a
    # key left stashed is a key only git still has. Runs before the validator
    # and the commit, both of which would otherwise see the blanked grid.
    python3 tools/blind_annotate.py restore
    rm -f "$run_log"
  else
    stop_reason="claude CLI not on PATH ($PATH)"
  fi
fi

# A run that could not solve some of the clues still exits 0, still commits, and
# still looks like a good night — see tools/check_annotation_loss.py. Ask.
if [ -n "$annotated_nums" ]; then
  loss=$(python3 tools/check_annotation_loss.py $annotated_nums 2>&1) || \
    alert "tonight's annotation came back short — $loss. Those clues ship with \"auto hints\" and no teaching ladder."
  echo "$loss"

  # How many turns a session is taking, logged every night it annotates. This
  # was measured by hand twice and the two measurements disagreed; the second
  # could not reproduce the first at all. A number that only exists when
  # somebody goes looking is a number that gets quoted long after it stopped
  # being true, so it is computed here from the transcripts every run.
  python3 tools/turn_cost.py 2>&1 || true
fi

# Alert on the backlog not moving, not on a command exiting non-zero. A run that
# annotates two puzzles and then meets a rate limit has done its job; a run that
# annotates none has silently stalled, which is this repo's signature failure —
# it shipped that three times (no PATH to claude, oldest-first ordering, a gate
# reading a blanked keychain entry) and each time the log knew and nobody did.
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
  elif [ "$annotated_ok" -eq 0 ]; then
    alert "no puzzle got hints today — $stop_reason. If that mentions authentication the CLI needs a fresh /login; see the CLAUDE_CONFIG_DIR note in daily_update.sh. Full output: .update.log."
  else
    # Reached when the run stopped on purpose rather than on a failure — the
    # five-hour window filling up is a budget decision, not something to wake
    # anybody for.
    echo "annotated $annotated_ok puzzle(s), then stopped: $stop_reason"
  fi
fi

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
        claude -p "Read tools/report_fix_prompt.md and follow it exactly. These are the reports it is about:

$bad_hints" \
          --model "$ANNOTATE_MODEL" \
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

# Price the window off everything claude spent above. The planner refuses the
# pair unless both meters really moved, so a quiet night, a five-hour turnover
# mid-run (session falls) and a weekly reset (weekly falls) all read as no
# measurement rather than as a wrong one.
if [ -n "$spend_weekly_before" ] && [ -n "$spend_session_before" ]; then
  spend_weekly_after=$(python3 tools/weekly_usage.py --group weekly 2>/dev/null)
  spend_session_after=$(python3 tools/weekly_usage.py --group session 2>/dev/null)
  if [ -n "$spend_weekly_after" ] && [ -n "$spend_session_after" ]; then
    priced=$(python3 tools/prereset_plan.py --observe-yield \
      "$((spend_weekly_after - spend_weekly_before))" \
      "$((spend_session_after - spend_session_before))" 2>/dev/null)
    echo "five-hour window now priced at ${priced:-unknown} weekly points" \
      "(planning on $(python3 tools/prereset_plan.py --planning-yield 2>/dev/null))"
  fi
fi

# --- 4. validate, reindex, commit ---
python3 tools/fetch_puzzle.py --reindex
# Tonight's work is judged on tonight's work. This used to validate the whole
# corpus and revert on any failure anywhere, so a type part in a puzzle from
# months ago discarded three clean puzzles and published nothing (2026-09-02).
# A puzzle that is already live cannot be made good by throwing away a puzzle
# that isn't.
# And one puzzle at a time, because the night is not the unit either. Validated
# as a lump, one blank clue in cryptic-30109 threw away independent-12458 too on
# 2026-09-11, which had just passed 29 of 29. A puzzle that is good is good on
# its own, and nothing about the bad one makes it less so.
ann_passed=""
ann_failed=""
for num in $annotated_nums; do
  if python3 tools/validate_annotations.py "$num" >"/tmp/ct-validate-$num.txt" 2>&1; then
    ann_passed="$ann_passed $num"
  else
    cat "/tmp/ct-validate-$num.txt"
    ann_failed="$ann_failed $num"
  fi
done
if [ -n "$ann_failed" ]; then
  echo "VALIDATION FAILED on$ann_failed — reverting those puzzle files"
  for num in $ann_failed; do
    git checkout -- "puzzles/$num.json"
    # That puzzle is un-annotated again and back at the head of tomorrow's
    # queue. Recorded against its inputs, because it IS the puzzle: the
    # validator read tonight's annotation of it and refused it.
    record_annotate_failure "$num" \
      "validation rejected tonight's annotation: $(grep -m1 ERROR "/tmp/ct-validate-$num.txt" | cut -c1-160)" \
      --judged
  done
  # The index above was built over the files as they stood before that revert.
  python3 tools/fetch_puzzle.py --reindex
  # Tonight's annotation of those is gone and the inference that produced it is
  # spent. This branch used to exit 1 in silence, which is the same shape of
  # failure as the seven authentication days: the log knew, and nobody did.
  alert "annotation validation failed on$ann_failed, so those hints were thrown away and those puzzles are skipped until their clues, answers, tools/annotate_prompt.md or tools/validate_annotations.py change: $(for n in $ann_failed; do grep -m1 ERROR "/tmp/ct-validate-$n.txt"; done | head -3 | tr '\n' ' ')${ann_passed:+ — the rest of the night ($ann_passed ) validated and still publishes}"
fi
rm -f /tmp/ct-validate-*.txt
# Only what survived is tonight's work from here on: it is what gets committed,
# and what the loop below clears from the failure ledger.
annotated_nums="$ann_passed"
if [ -n "$ann_failed" ] && [ -z "$annotated_nums" ]; then
  exit 1
fi
# Tonight's puzzles passed, so their failure records are cleared — except for
# one case that looks exactly like success from here. The `claude`
# call exiting 0 is not evidence the puzzle got hints: a run can finish its turns
# having written nothing, and the validator is happy with a file that has no
# annotations in it to be wrong. So the index, rebuilt above, is what decides,
# and a clean exit that annotated nothing is recorded like any other lost night.
for num in $annotated_nums; do
  if python3 - "$num" <<'EOF'
import json, sys
idx = json.load(open("puzzles/index.json"))
sys.exit(0 if any(p["id"] == sys.argv[1] and p["annotated"]
                  for p in idx["puzzles"]) else 1)
EOF
  then
    python3 tools/failed_inputs.py clear annotate "$num"
  else
    echo "$num came back from a clean run still un-annotated"
    record_annotate_failure "$num" "the run exited cleanly but wrote no annotation" --judged
  fi
done
# The corpus still gets checked every night, because a live page can be made
# wrong by a change to the validator or the glossary and nobody would look. It
# shouts and publishes anyway: the clues it names are already in front of
# readers, so holding tonight's puzzle back fixes nothing and costs a day.
if ! python3 tools/validate_annotations.py >/tmp/ct-corpus-validate.txt 2>&1; then
  alert "$(grep -c ERROR /tmp/ct-corpus-validate.txt) validation error(s) in already-published puzzles — tonight's puzzle published anyway: $(grep ERROR /tmp/ct-corpus-validate.txt | head -3 | tr '\n' ' ')"
fi

# The social cards are NOT drawn here. They are drawn by
# .github/workflows/pages.yml, on the same clean checkout that builds the pages
# that link them, because only the built tree is published — see tools/make_og.sh.
# That also takes headless Chrome off the list of things this machine has to have.

# Rebuild the crawlable pages: one per puzzle, the archive hub, the tutorial and
# the sitemap. After validation, deliberately — these pages publish the
# annotations as plain text, so a run that produced a bad annotation should have
# already bailed out above rather than putting it in front of a search engine.
#
# None of it is committed any more (.gitignore, and .github/workflows/pages.yml
# builds and deploys the same files from a clean checkout on every push). It is
# built here because the checks below read the pages — the stamp sweep and the
# glossary test have nothing to look at otherwise — and because a generator that
# has stopped working is worth finding out about tonight rather than at deploy.
# The solver's abbreviation glossary, republished from the clue-writer's copy.
# It leads, because it is gitignored generated output that every generated page
# names by content hash: a tree that has not built it has the pages before it
# has the file, and the builder below stops dead rather than stamp a hash of
# something missing. Before the stamp for the same reason — a rebuild changes
# the bytes the stamp is of.
python3 tools/build_abbreviations.py

python3 tools/build_seo_pages.py

# The README's generated regions, so the corpus counts in it are never more than
# one run behind. This can also fail, on purpose: a tool added without a line
# describing it, or a knob renamed out from under the paragraph quoting it. Worth
# shouting about, but not worth withholding tonight's puzzle over — and the
# refusal names exactly what is undescribed, so it travels in the alert rather
# than waiting in a log for someone to go and look.
if ! readme_err=$(python3 tools/build_readme.py 2>&1); then
  printf '%s\n' "$readme_err"
  alert "the README could not be regenerated, so its corpus counts are frozen at their last good value:"$'\n'"\`\`\`"$'\n'"$(printf '%s' "$readme_err" | head -12)"$'\n'"\`\`\`"
fi

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
  smoke_log="$(mktemp "${TMPDIR:-/tmp}/cryptic-smoke.XXXXXX")"
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

# The annotation payloads apply_annotations.py consumed. Gitignored (tools/_*),
# so this is housekeeping rather than safety — but the throwaway scripts these
# replaced were gitignored too, and they piled up one per puzzle for months.
rm -f "$REPO/tools/_ann_"*.json "$REPO/tools/_puzzle_"*.json

# Stamping is a build step, so the stamps come back off before anything is
# staged. A ?v= hash committed into index.html changes on every asset edit and
# on every reindex (index.html carries puzzles/index.js's hash too), which is
# churn in a tracked file and the thing this job's rebase collides in night
# after night.
# The deploy workflow stamps its own checkout, so what ships is stamped anyway.
python3 tools/stamp_assets.py --unstamp

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
  git commit -m "$(printf 'Daily update: fetch latest cryptic / annotate backlog\n\n%s' "$(python3 tools/provenance.py trailer)")"
  # Nothing may be left behind. With one writer this is no longer a judgement
  # call about whose file it was: anything still showing here after `add -A` and
  # a commit is a bug, and it is work that will never reach the site. Read with
  # cut, not awk $2 — a rename prints two paths and a filename may contain a
  # space, and both of those used to come out as the wrong filename.
  left=$(git status --porcelain | cut -c4- | tr '\n' ' ')
  [ -n "$left" ] && alert "the daily update committed, and left these behind in its own worktree: $left"
  # A rebase that stops here is rarely a disagreement. Every file this job writes
  # that an interactive session writes too is GENERATED — README.md, the asset
  # stamps, and what is still tracked of the built pages — so a
  # conflict in one is two rebuilds of the same inputs, not two opinions, and
  # resolving it by hand is what stranded the 2026-09-06 and 09-07 runs. Rebuild
  # from the merged sources instead.
  #
  # What makes that safe is not a list of generated filenames, which would drift
  # the moment a builder learns a new output: a path is only accepted once a
  # builder has actually rewritten it, and rewriting it is exactly what leaves no
  # conflict markers behind. A path still carrying markers is owned by no builder
  # — a real conflict — and the whole rebase is abandoned to the alert above
  # rather than half-resolved.
  rebuild_generated_conflicts() {
    # Nothing to continue unless the rebase stopped mid-pick; a rebase that
    # refused to start is not a conflict and must not be papered over. The state
    # directory is the only honest test of that: REBASE_HEAD is left behind
    # after a rebase finishes, so it says "in progress" for the rest of the day.
    [ -d "$(git rev-parse --git-path rebase-merge)" ] ||
      [ -d "$(git rev-parse --git-path rebase-apply)" ] || return 1
    # stamp_assets.py last, and not optional: index.html's ?v= is the content
    # hash of the very files this rebuild rewrites, so skipping it pushes a page
    # that points every cache at bytes that no longer exist.
    # The glossary leads, because --reindex restamps index.html on its way
    # past and a stamp is a hash of the file it names. It is gitignored
    # generated output, so a checkout that has never built it has the page
    # before it has the file.
    python3 tools/build_abbreviations.py >/dev/null &&
      python3 tools/fetch_puzzle.py --reindex >/dev/null &&
      python3 tools/build_seo_pages.py >/dev/null &&
      python3 tools/build_readme.py >/dev/null &&
      python3 tools/stamp_assets.py >/dev/null || return 1
    # Collect the list before staging any of it. Fed in through a process
    # substitution, `git diff` is still running while the loop stages, and it
    # takes .git/index.lock to refresh the index — every add after the first
    # then dies on "Another git process seems to be running".
    local conflicted path
    conflicted=$(git diff --name-only --diff-filter=U) || return 1
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      [ -f "$path" ] && ! grep -q '^<<<<<<< ' "$path" || return 1
      git add -- "$path" || return 1
    done <<CONFLICTED
$conflicted
CONFLICTED
    # The builders also rewrite files the rebase never conflicted in — index.html
    # carries the ?v= hash of an index.js that just changed. A rebase refuses to
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
  # (interactive sessions push to it all day), and this used to be a bare push
  # swallowed by `|| true`, so a rejected push looked exactly like a successful
  # one and the day's puzzle quietly never reached the site.
  if git remote get-url origin >/dev/null 2>&1; then
    # HEAD is detached in this worktree, so master is named explicitly on both
    # sides. --autostash still earns its place: a rebase refuses outright with
    # anything unstaged, and the leftover check above reports that case rather
    # than preventing it.
    if git fetch -q origin master &&
       { git rebase -q --autostash origin/master || rebuild_generated_conflicts; } &&
       git push -q origin HEAD:master
    then
      # Pushed is not published. GitHub Pages builds afterwards, and a build that
      # fails leaves the site serving yesterday with a green git log in front of
      # it — "can you always hold off on telling me to reload until it is
      # deployed" applies to the machine saying it too.
      python3 tools/wait_for_deploy.py ||
        alert "tonight's update pushed, but the site never came back with it — GitHub Pages has not published the new build. Check https://github.com/ptarjan/cryptic-teacher/actions."
    else
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

# The bad-hint reports solvers sent. Nothing read this queue until 2026-09-06 —
# the endpoint stored them correctly and they sat in KV until somebody thought
# to run the tool, which is a report button that works and a report nobody
# answers. Last, because it is the only step that asks a person for something.
#
echo "=== done ==="
