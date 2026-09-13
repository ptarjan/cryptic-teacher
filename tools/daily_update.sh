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
#      attempts — except when the wall-clock cap kills it, which says this grid
#      is lost and nothing about the next one, so the queue carries on.
#      A puzzle that fails, or whose annotation the validator throws
#      away, is written down (tools/annotate_attempts.py): the next night
#      resumes the session it died in rather than starting over, and after
#      ANNOTATE_MAX_ATTEMPTS of them it leaves the queue and a person is told,
#      because otherwise it is the newest un-annotated puzzle for ever and is
#      re-bought at full price every single night.
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

# Two limits, and the gap between them is the point. The thinking budget is what
# actually bounds spend: thinking bills as output, and a turn that reasons past
# the output ceiling emits no tool call, makes no progress, and is retried
# verbatim until the run dies — so an uncapped one can spend a whole puzzle's
# budget on nothing. The ceiling above it is a safety net that a healthy turn
# never touches; keeping it well clear means a long, productive turn finishes
# instead of being killed for overrunning.
# Measured over 10,823 turns (2026-08-23..09-06), grouped by the API's message
# id: 554 turns spent 8k-32k output tokens and every one of them ended in a tool
# call, and of the 101 above 32k, 91 did too. Big turns are working turns. The
# other 10 are the shape these two limits exist for — output_tokens exactly
# 64,000, stop_reason max_tokens, no text and no visible thinking: thinking ate
# the entire ceiling and the turn was truncated before it could act. A cap below
# the ceiling makes that unreachable. Count by message id, not by line: the CLI
# writes one line per content block and stamps each with the whole turn's usage.
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
#     A puzzle we solved ourselves is refreshed too, and the night the paper's
#     key lands our fill is marked against it: wrong answers lose the
#     annotations written off them, and the score is alerted rather than left in
#     .update.log. That grade is the whole measurement behind ANNOTATE_BLIND —
#     it happens once per puzzle, on a night nobody knows in advance, so it has
#     to come and find us.
refreshed=$( { python3 tools/fetch_puzzle.py --refresh-unsolved
               python3 tools/fetch_observer.py --refresh-unsolved; } 2>&1 | tee /dev/stderr)
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
# How many nights a puzzle may fail before it leaves the queue for a person to
# look at. Two, and a night already contains one in-run retry, so this is up to
# four tries. Exported rather than passed: tools/annotate_attempts.py reads it
# from the environment, and the default belongs in this file for the same reason
# every other one does — a value only the scheduler knows is a value this script
# cannot be run by hand with.
export ANNOTATE_MAX_ATTEMPTS="${ANNOTATE_MAX_ATTEMPTS:-2}"
# Puzzles whose annotation has already been bought and lost twice. Selection
# here is by date and nothing else, so without this a puzzle that fails is the
# newest un-annotated puzzle again tomorrow, and again the night after — the
# same grid, from scratch, at a full puzzle's price each time (see
# tools/annotate_attempts.py). Excluded before the slice below, not skipped
# inside the loop: that slice is the night's whole budget, and a blocked puzzle
# holding one of its three places would cost the backlog a real puzzle a night.
annotate_blocked=$(python3 tools/annotate_attempts.py blocked)
pending=$(python3 - "$ANNOTATE_MAX" "$annotate_blocked" <<'EOF'
import json, sys
idx = json.load(open("puzzles/index.json"))
blocked = set(sys.argv[2].split())
# IDs, not numbers: puzzles/<id>.js is what every step below names, so no
# consumer has to resolve a number two papers could share.
todo = sorted(((p.get("date") or 0, p["id"]) for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")
               and p["id"] not in blocked), reverse=True)
print(" ".join(i for _, i in todo[:int(sys.argv[1])]))
EOF
)

# Charge a lost night to the puzzle — but only when the puzzle is what lost it.
#
# A run stopped by a usage lockout or an expired login learned nothing about the
# grid: the CLI never got far enough to read it. Counting those against the
# puzzle would blacklist a perfectly good one for a fault that had nothing to do
# with it, and would do it on exactly the nights this job is already broken, so
# the whole head of the queue would go dark at once and stay there. The retry
# loop below draws the same line — it retries an output overrun and lets a
# lockout fall through to the next window rather than spending another attempt
# now — and this follows it.
record_annotate_failure() {   # id, reason, session id of that attempt (may be empty)
  local id="$1" reason="$2" sid="${3:-}" n
  case "$reason" in
    *"usage limit"*|*"limit reached"*|*"rate limit"*|*"five-hour window"*|\
    *"Not logged in"*|*authenticate*|*OAuth*|*"credit balance"*)
      echo "  not charging $id for that — it is our fault, not the puzzle's"
      return 0 ;;
  esac
  n=$(python3 tools/annotate_attempts.py record "$id" --reason "$reason" \
        ${sid:+--session "$sid"})
  echo "  $id has now failed ${n:-?} of $ANNOTATE_MAX_ATTEMPTS annotation attempts"
}

# A puzzle leaving the queue is worth waking someone for exactly once. Nightly
# it would be worth less than nothing: tools/alert.sh's header says why — the
# pre-reset job repeated one paragraph four times on 2026-08-07, and a channel
# that cries wolf on the hour teaches its one reader to scroll past everything
# in it, including the message that matters. So the set that has already been
# reported is remembered in the ledger and only a change to it speaks up.
alert_newly_blocked() {
  local ids
  ids=$(python3 tools/annotate_attempts.py blocked --if-changed | tr '\n' ' ')
  ids="${ids% }"
  [ -n "$ids" ] || return 0
  alert "these puzzles have failed $ANNOTATE_MAX_ATTEMPTS annotation runs each and are no longer being tried: $ids. They ship with no hints, and nothing will attempt them again until someone does — annotate one by hand, or clear it with \`python3 tools/annotate_attempts.py clear <id>\`. The reason each one gave up is in tools/data/annotate_attempts.json."
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
# One a night by default, because there is only ever one unsolved puzzle in the
# normal week. Not for cost: a cold solve is the CHEAP job here — around 10-15
# turns against an annotation's 40-90, and a third of the spend once cache reads
# are priced at their tenth. Raising SOLVE_MAX is not what will blow the budget.
SOLVE_MAX="${SOLVE_MAX:-1}"
# A puzzle gets SOLVE_ATTEMPTS_MAX cold solves in its life, then never again.
# Selection is by date, so before this cap a puzzle that failed was simply the
# newest unsolved puzzle again tomorrow, and again the night after — the same
# grid, the same model, the same rejection, until the paper published a key a
# week later. everyman-4166 was solved correctly on 26, 27 and 28 August and
# thrown away all three times, because apply_solution.py's `number` argument was
# type=int and "everyman-4166" is not an int. Three full solves bought nothing.
#
# One attempt, not several. A failed solve is rare enough to be worth a human
# look every time it happens (Paul, 2026-09-05), and the reason one fails is
# almost never the puzzle — it is us: a crashing applier, a moved prompt file, a
# CLI that can't authenticate. Retrying those just buys the same rejection at
# full price. So giving up is immediate, and it raises an alert carrying the
# rejection itself; the second attempt is a human deciding to make one.
SOLVE_ATTEMPTS_MAX="${SOLVE_ATTEMPTS_MAX:-1}"
# In the main checkout, not $REPO: this script re-execs into a throwaway
# worktree, and a count kept there is a count that resets whenever the worktree
# is rebuilt — which is exactly the night the cap needed to hold.
SOLVE_ATTEMPTS_FILE="${CT_MAIN_CHECKOUT:-$REPO}/.solve_attempts.json"
unsolved=$(python3 - "$SOLVE_MAX" "$SOLVE_ATTEMPTS_MAX" "$SOLVE_ATTEMPTS_FILE" <<'EOF'
import json, sys
limit, cap, path = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
idx = json.load(open("puzzles/index.json"))
try:
    tried = json.load(open(path))
except (FileNotFoundError, ValueError):
    tried = {}
# Forget puzzles that have answers now, so a key arriving late — or a re-fetch
# that genuinely changes the grid — is never blocked by a stale count.
unsolved_ids = {p["id"] for p in idx["puzzles"] if not p.get("hasSolutions")}
if any(k not in unsolved_ids for k in tried):
    tried = {k: v for k, v in tried.items() if k in unsolved_ids}
    json.dump(tried, open(path, "w"), indent=1, sort_keys=True)
todo = sorted(((p.get("date") or 0, p["id"]) for p in idx["puzzles"]
               if p["id"] in unsolved_ids and tried.get(p["id"], 0) < cap), reverse=True)
print(" ".join(i for _, i in todo[:limit]))
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
# Annotate without being shown the published answers, and grade what the model
# derives against them afterwards. See tools/blind_annotate.py for why this
# measures something the sighted path cannot. The cost of a blind night is that
# any clue the model gets wrong ships with no hints at all, so this is a trial
# with an end: run it for a stretch of nights, then compare the graded accuracy
# and the check_annotation_loss.py numbers against the sighted corpus and decide.
#
# The default is the trial's state, and it lives here because the repo is the
# only place that survives the machine. Set it anywhere else — a scheduler's
# environment, one host's dotfiles — and nothing in this checkout knows the
# trial exists, and a rewrite of that one file switches it off with no alert
# and no way to tell from the log that a sighted night was not the intended
# one. An environment variable still wins, so a one-off `ANNOTATE_BLIND= `
# still works.
ANNOTATE_BLIND="${ANNOTATE_BLIND:-1}"
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
      echo "weekly usage under ${ANNOTATE_MAX_WEEKLY_PCT}% — annotating $pending${unsolved:+, solving $unsolved}" ;;
    skip)
      echo "weekly usage over ${ANNOTATE_MAX_WEEKLY_PCT}% — skipping annotation of $pending${unsolved:+ and solving of $unsolved}"
      pending=""
      unsolved="" ;;
    *)
      if grep -q "stale /login" "$gate_why"; then
        alert "Claude Code is logged out on this machine, so tonight's annotation was skipped — and every other model call would have failed too, gate or no gate. Run \`claude\` in a terminal and \`/login\`; nothing else here can fix it. The site is fine, the newest puzzle just published without hints."$'\n'"\`\`\`"$'\n'"$(cut -c1-300 "$gate_why")"$'\n'"\`\`\`"
      else
        alert "the weekly usage gate can't read the quota, so tonight's annotation was skipped rather than run ungated. Nothing is broken on the site — the newest puzzle still published, just without hints."$'\n'"\`\`\`"$'\n'"$(cut -c1-300 "$gate_why")"$'\n'"\`\`\`"
      fi
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
# and it is charged to the puzzle like any other failure — its session id is
# kept, so tomorrow resumes the conversation rather than buying it again.
ANNOTATE_MAX_MINUTES="${ANNOTATE_MAX_MINUTES:-90}"
annotated_ok=0
annotated_nums=""
stop_reason=""
# Puzzles the wall-clock cap killed. Not a reason to stop the run — see the
# `ann_rc = 124` branch — but the night still has to say it happened.
lost_ids=""
# id:session for every annotate call this run makes, so a failure noticed after
# the loop — the validator throwing tonight's work away — can still say which
# conversation held it. A "$num:$ann_sid" list rather than an associative array:
# this script has to run under the bash 3.2 macOS ships as well as the
# container's, and only one of those has `declare -A`.
ann_sids=""
ann_session_of() { printf '%s\n' $ann_sids | sed -n "s/^$1://p" | tail -1; }

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
    solvelog="${TMPDIR:-/tmp}/cryptic-solve-$num.log"
    verdict="${TMPDIR:-/tmp}/cryptic-verdict-$num.log"
    rm -f "$fill"
    echo "solving puzzle $num cold with Claude Code... (session ${session:-unknown}%)"
    claude -p "Solve the cryptic crossword in puzzles/$num.js in this repo. Its answers have not been published, so there is no key: follow tools/solve_prompt.md exactly, write your fill to $fill, and iterate against 'python3 tools/apply_solution.py $num --fill $fill --check-only' until every crossing agrees. Do not write to puzzles/ — the calling script applies the fill." \
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
      pending="$num $pending"
      python3 - "$num" "$SOLVE_ATTEMPTS_FILE" <<'EOF'
import json, sys
num, path = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(path))
except (FileNotFoundError, ValueError):
    d = {}
if d.pop(num, None) is not None:
    json.dump(d, open(path, "w"), indent=1, sort_keys=True)
EOF
    else
      attempts=$(python3 - "$num" "$SOLVE_ATTEMPTS_FILE" <<'EOF'
import json, sys
num, path = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(path))
except (FileNotFoundError, ValueError):
    d = {}
d[num] = d.get(num, 0) + 1
json.dump(d, open(path, "w"), indent=1, sort_keys=True)
print(d[num])
EOF
)
      echo "solve of $num rejected — nothing written (attempt $attempts of $SOLVE_ATTEMPTS_MAX)"
      if [ "${attempts:-0}" -ge "$SOLVE_ATTEMPTS_MAX" ]; then
        # The lines travel in the alert. A repeated solve failure is a bug in
        # this repo far more often than a hard crossword, and the reader needs
        # the applier's complaint and the model's last words to tell which.
        alert "gave up solving $num after $attempts attempts — it will never be tried again, and the puzzle ships hintless until the paper publishes its key. Clear its entry in .solve_attempts.json to retry. The applier said:"$'\n'"\`\`\`"$'\n'"$(tail -8 "$verdict" | cut -c1-200)"$'\n'"\`\`\`"$'\n'"and the solver's last words were:"$'\n'"\`\`\`"$'\n'"$(tail -6 "$solvelog" | cut -c1-200)"$'\n'"\`\`\`"
      fi
    fi
    rm -f "$fill" "$solvelog" "$verdict"
  done
  # Whatever solving cost, the annotation budget is still ANNOTATE_MAX puzzles.
  # Solving prepends its puzzle, so a queue that was already at the cap loses its
  # last entry here. Name the ones being dropped: the queue line above has
  # already promised them by id, and a promise withdrawn in silence reads in the
  # log as a puzzle that failed rather than one that was never begun.
  kept=$(echo $pending | tr ' ' '\n' | grep -v '^$' | head -"$ANNOTATE_MAX" | tr '\n' ' ')
  dropped=$(echo $pending | tr ' ' '\n' | grep -v '^$' | tail -n +"$((ANNOTATE_MAX + 1))" | tr '\n' ' ')
  [ -n "$dropped" ] &&
    echo "over the ANNOTATE_MAX=$ANNOTATE_MAX budget once solving was prepended — not annotating tonight: $dropped"
  pending=$kept
fi

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
      # fetch as a last resort (bounded in tools/annotate_prompt.md). The cold
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
      ann_task="Annotate the cryptic crossword in puzzles/$num.js in this repo."
      if [ -n "$ANNOTATE_BLIND" ] && python3 tools/blind_annotate.py hide "$num"; then
        ann_tools="Read,Write,Edit,Bash(python3 *),Bash(node *)"
        ann_turns=120
        ann_task="Solve AND annotate the cryptic crossword in puzzles/$num.js in this repo. Its \"solution\" fields are deliberately empty: the answers are not published to you, so work each one out from the clue and the crossings, and write what you derive into that entry's \"solution\" field as you go. Do not look for the answers anywhere else in the repo, in git history, or on the web — a derived answer is the point. Where you cannot get an answer with confidence, leave its solution empty and its annotation null rather than guessing."
      fi
      # One session id per puzzle, fixed before the first attempt, because a run
      # that dies has already been paid for: it read the grid, worked out the
      # wordplay and wrote some of it down, and a fresh -p buys every bit of
      # that again. --resume replays the transcript and carries on from it.
      ann_sid=$(session_id) || ann_sid=""
      ann_sess=(--session-id "$ann_sid")
      ann_prompt="$ann_task Follow the instructions in tools/annotate_prompt.md exactly, including running 'python3 tools/annotate_check.py <ID>' until it reports clean. Every clue needs a definitionFit, and every indicator needs an indicatorNotes entry saying why THAT word carries THAT instruction. Do not commit — the calling script commits."
      # A conversation from a night that failed, if the ledger kept one and the
      # CLI still holds its transcript. This is the retry below, stretched over
      # a night instead of a turn, and it is worth the same: the dead run had
      # already read the grid, solved some of the clues and written part of the
      # annotation down, and a fresh -p pays for every bit of that a second time.
      # The prompt is the retry's, in its words, with one difference — a night
      # can also have ended in the validator throwing the file back to its old
      # contents, so it must be read as it NOW stands rather than assumed.
      ann_prior=$(python3 tools/annotate_attempts.py session "$num")
      if session_exists "$ann_prior"; then
        ann_sid="$ann_prior"
        ann_sess=(--resume "$ann_sid")
        ann_prompt="An earlier run of this task was cut off before it finished. Everything you did before that is intact in this conversation, but the files may have been rolled back since — read puzzles/$num.js to see how far you actually got, and carry on from there rather than starting again. Write in several smaller edits instead of one large one: an edit big enough to hit the output token limit will be cut off. Finish the task you were given and run 'python3 tools/annotate_check.py $num' until it reports clean. Do not commit."
        echo "  $num still has the session its last attempt died in — resuming that rather than buying it from scratch"
      fi
      ann_sids="$ann_sids $num:$ann_sid"
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
          record_annotate_failure "$num" "$ann_timeout" "$ann_sid"
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
        ann_prompt="Your last turn was cut off for going past the output token limit, so whatever it was writing was never saved. Everything you did BEFORE that turn is intact — read puzzles/$num.js to see how far you actually got, and carry on from there rather than starting again. Write in several smaller edits instead of one large one: an edit big enough to hit that limit will be cut off again. Finish the task you were given and run 'python3 tools/annotate_check.py $num' until it reports clean. Do not commit."
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
        record_annotate_failure "$num" "$stop_reason" "$ann_sid"
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
  if [ "$annotated_ok" -eq 0 ]; then
    alert "no puzzle got hints today — $stop_reason. If that mentions authentication the CLI needs a fresh /login; see the CLAUDE_CONFIG_DIR note in daily_update.sh. Full output: .update.log."
  else
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
        claude -p "Solvers of this crossword site reported these hints as wrong or unhelpful. Fix them.

$bad_hints

For each report: read that clue's annotation in its puzzles/<id>.js, decide whether the complaint is about this one clue or about a shape the site repeats, and fix it at the level it belongs to — the annotation, the rendering in app.js, or a rule in tools/validate_annotations.py. A complaint you disagree with is still evidence the page reads wrong; say what you concluded either way. Then run 'python3 tools/validate_annotations.py' and 'node tools/smoke_test.js' and leave both passing. Finally run 'python3 tools/reports.py --done <key>' for each report you actually fixed, using the r: key printed under it, and leave in the queue anything you could not fix. Do not commit — the calling script commits." \
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
    git checkout -- "puzzles/$num.js"
    # That puzzle is un-annotated again and back at the head of tomorrow's queue,
    # so the run just discarded gets bought again — and one that trips the
    # validator systematically would repeat that indefinitely. Charged to the
    # puzzle, because it IS the puzzle: the validator read tonight's annotation
    # of it and refused it.
    record_annotate_failure "$num" \
      "validation rejected tonight's annotation: $(grep -m1 ERROR "/tmp/ct-validate-$num.txt" | cut -c1-160)" \
      "$(ann_session_of "$num")"
  done
  # The index above was built over the files as they stood before that revert.
  python3 tools/fetch_puzzle.py --reindex
  # Tonight's annotation of those is gone and the inference that produced it is
  # spent. This branch used to exit 1 in silence, which is the same shape of
  # failure as the seven authentication days: the log knew, and nobody did.
  alert "annotation validation failed on$ann_failed, so those hints were thrown away: $(for n in $ann_failed; do grep -m1 ERROR "/tmp/ct-validate-$n.txt"; done | head -3 | tr '\n' ' ')${ann_passed:+ — the rest of the night ($ann_passed ) validated and still publishes}"
  alert_newly_blocked
fi
rm -f /tmp/ct-validate-*.txt
# Only what survived is tonight's work from here on: it is what gets committed,
# and what the loop below clears from the failure ledger.
annotated_nums="$ann_passed"
if [ -n "$ann_failed" ] && [ -z "$annotated_nums" ]; then
  exit 1
fi
# Tonight's puzzles passed, so their history is spent and is not worth keeping —
# except for one case that looks exactly like success from here. The `claude`
# call exiting 0 is not evidence the puzzle got hints: a run can finish its turns
# having written nothing, and the validator is happy with a file that has no
# annotations in it to be wrong. So the index, rebuilt above, is what decides,
# and a clean exit that annotated nothing is charged like any other lost night.
for num in $annotated_nums; do
  if python3 - "$num" <<'EOF'
import json, sys
idx = json.load(open("puzzles/index.json"))
sys.exit(0 if any(p["id"] == sys.argv[1] and p["annotated"]
                  for p in idx["puzzles"]) else 1)
EOF
  then
    python3 tools/annotate_attempts.py clear "$num"
  else
    echo "$num came back from a clean run still un-annotated"
    record_annotate_failure "$num" "the run exited cleanly but wrote no annotation" \
      "$(ann_session_of "$num")"
  fi
done
alert_newly_blocked
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
python3 tools/build_seo_pages.py

# The solver's abbreviation glossary, republished from the clue-writer's copy.
# Before the stamp, because a rebuild changes the bytes the stamp is of.
python3 tools/build_abbreviations.py

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
rm -f "$REPO/tools/_ann_"*.json

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
  git commit -m "$(printf 'Daily update: fetch latest cryptic / annotate backlog\n\n%s' "$ANNOTATE_TRAILER")"
  # Nothing may be left behind. With one writer this is no longer a judgement
  # call about whose file it was: anything still showing here after `add -A` and
  # a commit is a bug, and it is work that will never reach the site. Read with
  # cut, not awk $2 — a rename prints two paths and a filename may contain a
  # space, and both of those used to come out as the wrong filename.
  left=$(git status --porcelain | cut -c4- | tr '\n' ' ')
  [ -n "$left" ] && alert "the daily update committed, and left these behind in its own worktree: $left"
  # A rebase that stops here is rarely a disagreement. Every file this job writes
  # that an interactive session writes too is GENERATED — puzzles/index.json,
  # puzzles/index.js, README.md, sitemap.xml, the per-puzzle pages — so a
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
