#!/bin/bash
# Spend the weekly usage window on backfills: every five-hour window to 100%.
#
# Why this exists, separately from daily_update.sh: unspent quota does not roll
# over. daily_update.sh deliberately refuses to annotate above
# ANNOTATE_MAX_WEEKLY_PCT because a crossword backlog is never worth being
# rate-limited for real work; this job is the other half and runs with NO usage
# gate. It keeps as many runs in flight as spends the five-hour window by its
# reset (tools/prereset_plan.py --width), from the moment it starts until the
# week resets: a rolling pool, where a finished run's slot is refilled at once.
#
# The only stops are the meters and the reset itself:
#   - the FIVE-hour limit: saturate it and nothing more can be bought until it
#     turns over, so a lockout is waited out and the pool picks up where it
#     stopped;
#   - the weekly meter at EXHAUSTED: the run stops (Paul resets it);
#   - the weekly reset: the run stops five minutes short of it rather than spend
#     the next week's quota, and the next hourly fire starts the new week.
#
# What it backfills, in priority order:
#   1. Un-annotated puzzles, NEWEST FIRST BY DATE, across every series at once.
#      A solver arriving today is looking at this week's puzzles, so this week's
#      puzzles are the ones worth spending on, whoever printed them.
#   2. Every field in tools/annotation_backlog.json, each named by its key
#      path — explanation.definitionFit, the one-sentence "why does the answer
#      mean the definition"; indicators.note, "why is THAT word the
#      indicator"; indicators.for, which of the clue's types each indicator
#      signals; features; explanation.surface. New puzzles are
#      required to carry these; the file is the list of puzzles annotated
#      before each rule existed, and draining one tightens the rule on it
#      forever. The fields are read from the file, so this job needs no edit
#      when the next rule lands.
#
# A failed run is read off the meters, never off the CLI's words: past
# EXHAUSTED weekly the job stops, past LOCKOUT_PCT five-hour it waits for the
# window to turn over, and below both the run failed for reasons of its own,
# so that puzzle is dropped and the queue carries on. See after_wave.
#
# Install: a line in the bridge container's tools/crontab (household repo), at
# :05 every hour, and that line is the only schedule this job has. `flock -n`
# on it is not decoration: cron has no idea that a copy is already running, and
# two of these overlapping would both spend the same window. On a Mac it would
# have to be launchctl instead, never as well — see daily_update.sh's header.

set -uo pipefail
# The pool reaps whichever run finishes first with `wait -n -p`, which is bash 5.1.
if (( BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 501 )); then
  echo "ERROR: tools/prereset_backfill.sh needs bash 5.1+ for wait -n -p; this is $BASH_VERSION"
  exit 1
fi
# A checkout of its own, so days of unmetered annotation cannot collide with
# the 04:45 job or with somebody editing the repo. See tools/nightly_worktree.sh.
. "$(dirname "$0")/nightly_worktree.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
. "$REPO/tools/claude_path.sh"
# Without this the CLI reads the legacy un-suffixed keychain entry, which a
# file-based /login emptied on 2026-07-31, and every run dies on "Failed to
# authenticate: OAuth session expired and could not be refreshed". See the longer
# note in daily_update.sh.
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# claude-auth.sh is deliberately not sourced: the CLI finds its own stored
# login under CLAUDE_CONFIG_DIR, and that file's env token would override the
# stored one with a credential that cannot refresh.
. "$REPO/tools/alert.sh"

# session_id / session_exists — the resume mechanism run_claude below is built on.
. "$REPO/tools/claude_session.sh"

# This run's own output, so the exit trap can report any failure line nobody
# wrote an alert for. See alert_run_failures in alert.sh.
# Spelled out rather than `mktemp -t cryptic-prereset`: -t takes a bare prefix on macOS
# but a template that must contain X's on GNU, so the one spelling cannot mean
# the same thing on both. Every mktemp below is written this way.
RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/cryptic-prereset.XXXXXX")"
exec > >(tee -a "$RUN_LOG") 2>&1

# Kept in step with daily_update.sh — Opus, benchmarked against Fable on 30078
# (STYLE.md). Matching quality at a third the cost matters more here than
# anywhere: a cheaper annotator is straightforwardly more puzzles per reset.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
MODEL="$ANNOTATE_MODEL"
ANNOTATE_EFFORT="${ANNOTATE_EFFORT:-medium}"  # see daily_update.sh
# Runs to keep in flight, asked at every pool checkpoint with the width now:
# what spends the five-hour window by its reset, capped by free memory and CPU
# pressure (tools/prereset_plan.py, which logs its inputs). If it prints no
# width the current one stands. At 0 (the bridge alone will spend what the
# window has left, or the machine has no room) nothing new starts, and once the
# runs in flight are done the pool naps a checkpoint interval and asks again.
wave_width() {
  local w
  w=$(python3 tools/prereset_plan.py --may-pause --width ${wide:-})
  case "$w" in ''|*[!0-9]*) echo "${wide:-14}" ;; *) echo "$w" ;; esac
}
# Above this the weekly window really is gone and a failing run means it. Below
# it, a failure is the FIVE-hour window instead, which clears by itself. The
# meter sits at 99 when the week is spent, which is also what the reset ping
# fires on, so the burn spends right up to it.
#
# The CLI's own words do not distinguish them. With pay-as-you-go set to $0 it
# says "You've hit your monthly spend limit" for BOTH — there is no dollar cap
# involved, only a plan limit with no paid overflow to fall through to. So which
# limit was hit is read off the seven-day number here, never off the message.
EXHAUSTED="${EXHAUSTED:-99}"
# Below this on the five-hour meter a failed run was not locked out: the window
# had room, so waiting for it to turn over buys nothing.
LOCKOUT_PCT="${LOCKOUT_PCT:-90}"
# DRY_RUN=1 walks the whole job — queue order, the pool, deadline —
# without calling claude, touching git or rebuilding anything. This job spends
# ungated inference in parallel and cannot be rehearsed any other way; the first
# version of it ran seven ungated nights a week and read as healthy in the log.
DRY_RUN="${DRY_RUN:-0}"

echo "=== cryptic-teacher pre-reset backfill $(date '+%Y-%m-%d %H:%M') ==="

# One at a time. This runs for days, so an hourly fire and a hand run overlap
# easily — and two copies would double the width and race each other's commits
# in the one git index. mkdir is the atomic part.
LOCK="$REPO/.prereset.lock"
# The holder writes its pid inside it, because the directory alone cannot say
# whether it belongs to a live run or to one the machine killed: the EXIT trap
# that removes it does not get to run when the container goes down. So a lock
# whose pid names no live backfill — or that carries no pid at all, as every
# lock taken before this line did — is taken over rather than deferred to. The
# pid is matched against the command line and not merely tested for existence,
# because pids are reused and a restart hands them out again from the bottom.
lock_is_dead() {
  local pid
  pid=$(cat "$LOCK/pid" 2>/dev/null) || return 0
  [ -n "$pid" ] || return 0
  ps -o command= -p "$pid" 2>/dev/null | grep prereset_backfill >/dev/null || return 0
  return 1
}
if ! mkdir "$LOCK" 2>/dev/null; then
  if lock_is_dead; then
    # A lock older than the container is the expected leftover of a restart
    # and needs nobody; one taken since means a run died here, which does.
    if [ ! -e /proc/1 ] || [ "$LOCK" -nt /proc/1 ]; then
      alert "a pre-reset backfill lock from $(date -r "$LOCK" '+%H:%M') has no live process behind it — the run that took it was killed rather than stopped, with no container restart since. Taking the lock over."
    else
      echo "taking over a lock from $(date -r "$LOCK" '+%H:%M'), left by the container restart"
    fi
    rm -f "$LOCK/pid"
    rmdir "$LOCK" 2>/dev/null
  fi
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "another pre-reset backfill is running (started $(date -r "$LOCK" '+%H:%M')) — leaving it alone"
    exit 0
  fi
fi
echo "$$" > "$LOCK/pid"
# bash skips the EXIT trap when a signal kills it, which strands the lock; so a
# signal is turned into an ordinary exit and the trap below runs for it too.
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null; sleep 1; alert_run_failures "$RUN_LOG"; rm -f "$RUN_LOG"' EXIT
# Session ids and resume notes belong to the run that wrote them. Left behind by
# a run that stopped before its retry, they would have tonight's first attempt
# resume a conversation about a worktree that has since been reset out from
# under it — and be told to carry on from edits that are no longer there.
rm -f /tmp/ct-prereset-*.sid /tmp/ct-prereset-*.resume

# The run is bounded by the weekly reset, which is a timestamp the usage API
# hands over on request — never a time of day guessed at. Exit 3 (a reset rolled
# forward from the last one seen, because the API has not re-stamped it yet) is
# still the right bound: the week is a fixed length.
resets_in=$(python3 tools/weekly_usage.py --resets-in)
if [ -z "$resets_in" ]; then
  alert "pre-reset backfill can't read when the weekly window resets, so it can't bound the run. Skipped — see .prereset.log. Nothing is being backfilled until this reads again."
  exit 1
fi
RESET_AT=$(awk -v n="$(date +%s)" -v h="$resets_in" 'BEGIN{printf "%d", n + h * 3600}')

# What the week actually landed at, said once, after it is too late to change —
# because otherwise nobody ever finds out. A run that dies or stalls ends the
# same way as one that spent everything: a meter that reads 0% and no
# evidence it ever read anything else. LANDING_OK is the point below which the
# leftovers were worth having.
LANDING_FILE=".prereset_landing"
LANDING_OK="${LANDING_OK:-90}"
if [ -f "$LANDING_FILE" ]; then
  read -r landed deadline < "$LANDING_FILE"
  if [ "$(date +%s)" -ge "${deadline:-0}" ]; then
    rm -f "$LANDING_FILE"
    echo "the weekly window turned over with the meter at ${landed}%"
    awk -v l="${landed:-100}" -v ok="$LANDING_OK" 'BEGIN{exit !(l < ok)}' &&
      alert "the weekly window turned over with the meter at ${landed}% — $(awk -v l="$landed" 'BEGIN{printf "%d", 100 - l}')% of the week expired unspent. The backfill stopped or stalled before the reset; .prereset.log has the meters at every pool checkpoint."
  fi
fi

# A spent week has nothing to buy, and everything below — the archive fetch,
# the republish, the smoke test — is not worth running hourly for nothing.
weekly_now=$(python3 tools/weekly_usage.py 2>/dev/null)
if [ -n "$weekly_now" ] && awk -v n="$weekly_now" -v e="$EXHAUSTED" 'BEGIN{exit !(n >= e)}'; then
  echo "weekly window is spent (${weekly_now}%) — nothing to do until it resets in ${resets_in}h"
  exit 0
fi
echo "weekly window at ${weekly_now:-?}%, resets in ${resets_in}h — spending until then"

# Stop five minutes short of the turnover: past it we would be spending the NEW
# week's quota on this run's queue. An epoch second, not an "HH:MM" string.
STOP_AT=$(( RESET_AT - 300 ))
# Formatted in python rather than with `date -r`: -r reads an epoch second on
# macOS and a FILE's mtime on GNU, so the one spelling means two different
# things and this argument is an epoch second. (The -r above it is a directory,
# which both agree on.)
echo "deadline $(python3 -c "import sys,time; print(time.strftime('%a %H:%M', time.localtime(int(sys.argv[1]))))" "$STOP_AT")"
past_deadline() {
  [ "$(date +%s)" -ge "$STOP_AT" ]
}
# One nap per five-hour window left in the week is the plan, not a failure, so
# the allowance is that count with slack. It only bounds runs failing fast for
# some reason other than a lockout; each nap is capped at the deadline anyway.
MAX_NAPS=$(awk -v h="$resets_in" 'BEGIN{printf "%d", h / 5 + 3}')

# Minutes until the five-hour window turns over. Empty when it cannot be read.
session_left_min() {
  python3 tools/weekly_usage.py --group session --resets-in 2>/dev/null \
    | awk 'NF{printf "%d", $1 * 60}'
}

# Put the puzzles a lockout cut off back at the front of what is left to do.
# Without this the queue index walks straight past them: the job served the whole
# nap, came back to a window that would have run them, and spent it on the NEXT
# puzzles instead while the ones it had already half-paid for sat out the night.
#
# Once each. A puzzle failing for its own reasons — a clue the model cannot solve
# — must not be able to hold the queue open, and MAX_NAPS bounds the rest.
# WAVE_FAILED_IDS is the runs that failed since the last pool checkpoint;
# WAVE_WHAT the commit message prefix of the pool running now.
WAVE_FAILED_IDS=()
WAVE_WHAT=""
NAPPED=0
requeued=" "
requeue_failed() {
  local id back=()
  [ "$NAPPED" = 1 ] || return 0
  for id in ${WAVE_FAILED_IDS[@]+"${WAVE_FAILED_IDS[@]}"}; do
    case "$requeued" in *" $id "*) continue ;; esac
    requeued="$requeued$id "
    back+=("$id")
  done
  [ ${#back[@]} -eq 0 ] && return 0
  echo "  requeuing ${back[*]} — the window that refused them has turned over"
  queue=("${back[@]}" "${queue[@]:$at}")
  at=0
}

# Run one claude task against the repo. Returns non-zero if the run failed.
#
# Its output goes to a file named after the puzzle rather than to the log, because
# several of these run at once now and interleaved transcripts belong to nobody.
# The caller prints the tail of each one as it reaps it, in order.
#
# Every run is given a session id up front so that a retry can RESUME it rather
# than start over. A run the limit cut off had already read the puzzle, worked
# out the wordplay and written half the answers down; a fresh -p throws that
# thinking away and buys it a second time. Resuming replays the transcript and
# carries on from the reasoning already paid for.
run_claude() {
  local tag="$1" prompt="$2" log sid sidfile resume_at sess=()
  log="/tmp/ct-prereset-$1.txt"
  sidfile="/tmp/ct-prereset-$1.sid"
  resume_at="/tmp/ct-prereset-$1.resume"
  if [ "$DRY_RUN" = 1 ]; then
    echo "would spend one $MODEL run on $tag" >"$log"
    sleep 1
    return 0
  fi
  # WebSearch/WebFetch are here for the last rung only: when a clue will not come
  # apart, a solvers' blog is the difference between an annotation and a `null`,
  # and a `null` ships a clue with no teaching ladder. tools/annotate_check.py
  # names the blog only once every clue but the last few is done, and says to
  # write the explanation from scratch, because the blog's prose teaches nobody
  # in rungs.
  if [ -s "$resume_at" ] && [ -s "$sidfile" ] && session_exists "$(cat "$sidfile")"; then
    sess=(--resume "$(cat "$sidfile")")
    prompt=$(cat "$resume_at")
  else
    sid=$(session_id) || sid=""
    echo "$sid" >"$sidfile"
    sess=(--session-id "$sid")
  fi
  rm -f "$resume_at"
  # The annotate prompt names this copy, which leaves out the solutions detail:
  # that names the blog, which annotate_check.py discloses only once the run is stuck.
  python3 tools/annotate_check.py --view "$tag" >/dev/null
  # Niced, with everything it runs: the pool shares this machine with the bridge.
  # The instructions ride in the system prompt, where every run of the pool shares
  # one cached prefix, instead of costing each run a turn to cat them. The git
  # status that differs run to run moves out of it into the first message, or
  # it would split that prefix.
  nice -n 19 claude -p "$prompt" "${sess[@]}" "${CLAUDE_HEADLESS[@]}" \
    --append-system-prompt-file tools/annotate_prompt.md \
    --exclude-dynamic-system-prompt-sections \
    --model "$MODEL" \
    --effort "$ANNOTATE_EFFORT" \
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *),WebSearch,WebFetch" \
    --max-turns 80 >"$log" 2>&1
  local rc=$?
  # Running out of window is how this job is SUPPOSED to end, so a plain failure
  # stays quiet. A broken login is a different animal: it fails identically, at
  # the same point, every night, and it hid there for seven days (2026-07-31 to
  # 2026-08-06) precisely because it looked like the normal ending.
  if [ $rc -ne 0 ] && grep -qi "Failed to authenticate\|Not logged in" "$log"; then
    alert "pre-reset backfill cannot authenticate — the CLI needs a fresh /login. Nothing has been backfilled since this started."
  fi
  return $rc
}

# One puzzle's file as a git pathspec: puzzles/<series>/<year>/<id>.json in
# whichever year folder, so a write that moved it to another year is staged or
# undone as both halves of the rename.
puzzle_spec() { printf 'puzzles/*/*/%s.json' "$1"; }
# Undo a run's edits to one puzzle, including a copy written to a new folder.
discard_puzzle() {
  git checkout -- "$(puzzle_spec "$1")" 2>/dev/null
  git clean -qf -- "$(puzzle_spec "$1")"
}

# A run that failed. One cut off by a lockout usually leaves real work behind:
# some clues annotated, the rest untouched, and that file still validates.
# Throwing it away means paying for those clues again. Only a half-written one —
# the run died mid-edit — is worth nothing and goes back.
#
# A kept file leaves a note for the retry, which resumes this same conversation
# (see run_claude), so the note only says what changed while it was stopped. A
# discarded one starts a fresh session: its conversation describes edits that
# are no longer on disk.
#   $1 the puzzle id  $2 the commit message prefix
handle_failed_run() {
  local id="$1" what="$2" seen
  tail -5 "/tmp/ct-prereset-$id.txt" 2>/dev/null | sed "s/^/  [$id] failed: /"
  # What the retry is told to look at: the annotate run's copy, never the
  # puzzle itself, which names the blog (see run_claude).
  seen=$(python3 tools/puzzle_paths.py "$id")
  [ "$what" = Annotate ] && seen="tools/_puzzle_$id.json"
  if [ -n "$(git status --porcelain -- "$(puzzle_spec "$id")")" ] &&
     python3 tools/validate_annotations.py "$id" >/dev/null 2>&1; then
    echo "  [$id] run failed — keeping what it finished, the file still validates"
    printf '%s\n' "You were cut off by a usage limit. The limit has since cleared and your edits to $seen are exactly as you left them. Pick up where you stopped, finish the task you were given, and run python3 tools/annotate_check.py $id until it reports clean. Do not commit." >"/tmp/ct-prereset-$id.resume"
  else
    echo "  [$id] run failed — discarding its changes"
    discard_puzzle "$id"
    rm -f "/tmp/ct-prereset-$id.sid"
  fi
}

# --- the rolling pool ----------------------------------------------------------
# Up to $wide claude runs in flight over queue[at..]. Whenever one finishes it is
# handled — committed, or noted for a retry — and the next queued id starts, so
# no slot waits on the slowest run. The claude runs are the only thing that
# happens in parallel: every git command runs in this shell, one at a time,
# because a second process staging its own file mid-commit swallows it into ours.
#
# Launches are POOL_LAUNCH_GAP seconds apart, so the runs' setup and validators
# do not all hit the CPU in the same second.
POOL_LAUNCH_GAP_US=$(awk -v s="${POOL_LAUNCH_GAP:-5}" 'BEGIN{printf "%d", s * 1000000}')
# A checkpoint (pool_checkpoint) logs the meters, judges failures, re-reads the
# width and re-plans the queue. It runs this often, and at once after any failed
# run, so a lockout stops the refilling within one run.
POOL_CHECK_SECS="${POOL_CHECK_SECS:-300}"
# The rebase that brings in origin's changes needs a tree no annotator is writing
# (sync_wave), so this often the pool stops refilling, drains and syncs.
POOL_SYNC_SECS="${POOL_SYNC_SECS:-3600}"
declare -A POOL_RUNS=()  # pid -> puzzle id, every run in flight
POOL_RUN_US=0            # run-microseconds in flight since the checkpoint
POOL_MARK_US=0           # when POOL_RUN_US was last brought up to date
POOL_STARTED_US=0        # when the interval since the last checkpoint began
POOL_SYNCED_US=${EPOCHREALTIME/[.,]/}
POOL_LAUNCHED_US=0
POOL_DONE=0              # runs finished since the checkpoint
POOL_FIXING=0            # 1 while commit_puzzle's fix run holds this shell

# Bring POOL_RUN_US up to now. Called before every change to the runs going, so
# the average in flight a checkpoint logs is measured rather than the nominal
# width.
pool_mark() {
  local now=${EPOCHREALTIME/[.,]/}
  POOL_RUN_US=$(( POOL_RUN_US + (${#POOL_RUNS[@]} + POOL_FIXING) * (now - POOL_MARK_US) ))
  POOL_MARK_US=$now
}

pool_launch() {
  local id="$1" prompt wait_us
  wait_us=$(( POOL_LAUNCHED_US + POOL_LAUNCH_GAP_US - ${EPOCHREALTIME/[.,]/} ))
  [ "$wait_us" -gt 0 ] && sleep "$(printf '%d.%06d' $((wait_us / 1000000)) $((wait_us % 1000000)))"
  local again=""
  [ -s "/tmp/ct-prereset-$id.resume" ] && again=", picking up its cut-off conversation"
  prompt="${POOL_TMPL//@PATH@/$(python3 tools/puzzle_paths.py "$id")}"
  pool_mark
  run_claude "$id" "${prompt//@/$id}" &
  POOL_RUNS[$!]="$id"
  POOL_LAUNCHED_US=${EPOCHREALTIME/[.,]/}
  echo "  [$id] started$again (${#POOL_RUNS[@]} of $wide in flight)"
}

# Wait for whichever run finishes first, and commit it or note it for a retry.
pool_reap() {
  local pid="" rc id p
  while :; do
    # A finished run bash has already cleaned out of its job table is invisible
    # to wait -n ("no such job"), though plain wait still returns its status. So
    # finished runs are looked for first, and wait -n only blocks on live ones.
    for p in "${!POOL_RUNS[@]}"; do
      kill -0 "$p" 2>/dev/null && continue
      pid=$p
      wait "$p"
      rc=$?
      break
    done
    [ -n "$pid" ] && break
    wait -n -p pid "${!POOL_RUNS[@]}" 2>/dev/null
    rc=$?
    pid=${pid:-}
    [ -n "$pid" ] && break
    # One finished between the scan and wait -n: the next scan finds it.
    sleep 1
  done
  if [ -z "${POOL_RUNS[$pid]:-}" ]; then
    alert "pre-reset backfill lost track of its runs: wait -n returned $rc for pid '${pid}' with ${!POOL_RUNS[*]} in flight. Forgetting them and carrying on."
    pool_mark
    POOL_RUNS=()
    return
  fi
  pool_mark
  id="${POOL_RUNS[$pid]}"
  unset "POOL_RUNS[$pid]"
  POOL_DONE=$((POOL_DONE + 1))
  if [ "$rc" -eq 0 ]; then
    tail -3 "/tmp/ct-prereset-$id.txt" | sed "s/^/  [$id] /"
    commit_puzzle "$id" "$WAVE_WHAT"
  else
    handle_failed_run "$id" "$WAVE_WHAT"
    WAVE_FAILED_IDS+=("$id")
  fi
}

# Let every run in flight finish, then sync the quiet tree.
pool_drain() {
  while [ ${#POOL_RUNS[@]} -gt 0 ]; do pool_reap; done
  sync_wave
  POOL_SYNCED_US=${EPOCHREALTIME/[.,]/}
}

# Start an interval: the meters it is measured from, the width to keep in
# flight, and (annotate pools) the queue re-planned so the indicator cover
# shrinks as annotations land.
pool_interval_start() {
  WAVE_FAILED_IDS=()
  POOL_DONE=0
  POOL_BEFORE=$(python3 tools/weekly_usage.py 2>/dev/null || echo 0)
  POOL_BEFORE_S=$(python3 tools/weekly_usage.py --group session 2>/dev/null || echo 0)
  wide=$(wave_width)
  # Ahead of the round-robin: Cracking the Cryptic's puzzles, then the puzzles
  # with a notable tag (tools/puzzle_tags.py), then the puzzles that give an
  # indicator on /indicators/ its first annotated clue (tools/indicator_cover.py). Cut-off puzzles stay first. Anything but a whole
  # permutation back leaves the order as it was. A dry run plans once.
  if [ "$POOL_REORDER" = 1 ] && [ "$at" -lt "${#queue[@]}" ] &&
     { [ "$DRY_RUN" = 0 ] || [ "$POOL_PLANNED" = 0 ]; }; then
    POOL_PLANNED=1
    local reordered
    reordered=($(printf '%s\n' "${queue[@]:$at}" \
      | python3 tools/prereset_plan.py --cover-first "$requeued" || true))
    [ "${#reordered[@]}" -eq $(( ${#queue[@]} - at )) ] \
      && queue=("${queue[@]:0:$at}" "${reordered[@]}")
  fi
  pool_mark
  POOL_RUN_US=0
  POOL_STARTED_US=$POOL_MARK_US
  echo "--- pool of $wide: ${#POOL_RUNS[@]} in flight, $(( ${#queue[@]} - at )) queued${queue[$at]:+, next ${queue[*]:$at:3}} ---"
}

# End the interval: after_wave logs the meters and decides on its failures,
# requeue_failed puts back what a lockout cut off, and the next interval starts.
# Returns non-zero when the caller should stop.
pool_checkpoint() {
  local elapsed hours avg
  pool_mark
  elapsed=$(( POOL_MARK_US - POOL_STARTED_US ))
  hours=$(awk -v e="$elapsed" 'BEGIN{printf "%.3f", e / 3.6e9}')
  avg=$(awk -v r="$POOL_RUN_US" -v e="$elapsed" 'BEGIN{printf "%.2f", (e > 0 ? r / e : 0)}')
  after_wave "$POOL_BEFORE" "$hours" "$avg" "${#WAVE_FAILED_IDS[@]}" "$POOL_BEFORE_S" "$wide" ||
    return 1
  requeue_failed
  pool_interval_start
}

# Run the pool over queue[at..] until it is spent.
#   $1   commit message prefix, e.g. "Annotate"
#   $2   the prompt, with every @ standing for the puzzle id and every
#        @PATH@ for its file (tools/puzzle_paths.py)
#   $3   1 to re-plan the queue's order at every checkpoint
# Returns non-zero when the run should stop: the deadline, or after_wave said so.
# Either way no new run starts and the ones in flight finish and are handled.
run_pool() {
  WAVE_WHAT="$1" POOL_TMPL="$2" POOL_REORDER="${3:-0}" POOL_PLANNED=0
  local stop=0
  pool_interval_start
  while :; do
    if [ "$stop" = 0 ] && past_deadline; then echo "deadline reached — stopping"; stop=1; fi
    if [ "$stop" = 0 ] &&
       [ $(( ${EPOCHREALTIME/[.,]/} - POOL_SYNCED_US )) -ge $(( POOL_SYNC_SECS * 1000000 )) ]; then
      pool_drain
      if [ "$POOL_DONE" -gt 0 ]; then pool_checkpoint || stop=1; fi
      continue
    fi
    while [ "$stop" = 0 ] && [ ${#POOL_RUNS[@]} -lt "$wide" ] && [ "$at" -lt "${#queue[@]}" ]; do
      pool_launch "${queue[$at]}"
      at=$((at + 1))
    done
    if [ ${#POOL_RUNS[@]} -gt 0 ]; then
      pool_reap
      [ "$stop" = 0 ] || continue
      [ ${#WAVE_FAILED_IDS[@]} -eq 0 ] &&
        [ $(( ${EPOCHREALTIME/[.,]/} - POOL_STARTED_US )) -lt $(( POOL_CHECK_SECS * 1000000 )) ] &&
        continue
    else
      # Width 0 with nothing left to checkpoint: nap, then ask for the width again.
      if [ "$stop" = 0 ] && [ "$wide" = 0 ] && [ "$POOL_DONE" = 0 ] &&
         [ "$at" -lt "${#queue[@]}" ]; then
        echo "--- pool of 0: napping ${POOL_CHECK_SECS}s ---"
        sleep "$POOL_CHECK_SECS"
        wide=$(wave_width)
        continue
      fi
      # Nothing in flight and nothing left to start: one last checkpoint for the
      # runs since the previous one, which may requeue what a lockout cut off.
      [ "$stop" = 0 ] && [ "$POOL_DONE" -gt 0 ] || break
    fi
    pool_checkpoint || stop=1
  done
  sync_wave
  POOL_SYNCED_US=${EPOCHREALTIME/[.,]/}
  return $stop
}

# One try at rebasing this tree onto origin/master and pushing whatever it then
# holds that origin does not, run through push_race_retry. Only on a quiet tree
# (see sync_wave). --autostash for what is left uncommitted. HEAD is detached in
# this worktree, so master is named on both sides of the push.
sync_attempt() {
  git fetch -q origin master && git rebase -q --autostash origin/master &&
    if [ -n "$(git rev-list origin/master..HEAD)" ]; then git push -q origin HEAD:master; fi
}

# Every shared data file the runs wrote, committed and pushed the way a puzzle
# is, so safe with runs in flight: the glossary rows (tools/add_abbreviation.py,
# whole, under a lock) and the corroboration ledger extend_archive.py's fetches
# write. The directory, not a list, so the next such file is covered too. None
# may ride the sync's --autostash: other writers append to these files all day,
# and a stash pop that conflicts leaves an unmerged index that stops the burn.
# Committed, the keyed ones merge per key in the rebase (.gitattributes,
# tools/json_merge.py). Published at every checkpoint rather than at the
# republish, so the puzzles already pushed validate on master, and a burn that
# is killed does not lose them to nightly_worktree.sh's reset --hard.
publish_shared_data() {
  [ "$DRY_RUN" = 1 ] && return 0
  [ -n "$(git status --porcelain -- tools/data/)" ] || return 0
  git add -A -- tools/data/
  git commit -q -m "$(printf 'Shared data from the pre-reset backfill\n\n%s' "$(python3 tools/provenance.py trailer)")"
  tools/push_puzzle_commit.sh ||
    alert "pre-reset backfill committed shared data ($(git show --name-only --format= HEAD | tr '\n' ' ')) but could not push it — the next sync retries. See .prereset.log."
}

# Bring this tree up to origin/master, and publish anything the per-puzzle
# pushes could not. Only with no run in flight (pool_drain): a rebase with an
# annotator still writing fails on its clean-tree check, and an autostash taken
# then holds that sibling's finished puzzle hostage. Planner and code changes
# reach the burn through this rebase, and the local copies of puzzles
# push_puzzle_commit.sh already published drop out as patch-identical.
sync_wave() {
  [ "$DRY_RUN" = 1 ] && return 0
  publish_shared_data
  # Nothing generated survives the rebase, because nothing generated is worth
  # carrying: the republish step rewrites every one of these files wholesale
  # from the puzzle sources, so the copy sitting in the tree right now is
  # already garbage. Carried across in the --autostash, it conflicts the first
  # time origin rebuilt the same pages, and an unmerged index fails every later
  # `git commit` and every later autostash in the run.
  #
  # Exclusions, not a list of what to drop, for the reason the republish `add
  # -A` gives: a named list of generated paths is incomplete the day someone
  # adds a generated path. What is excluded is what a run actually authors —
  # a puzzle kept after a cut-off run, and shared data under tools/, which
  # publish_shared_data has just committed.
  git checkout -q -- . ':(exclude)puzzles/*.json' ':(exclude)tools/'
  # checkout only restores files git is tracking HERE. A generated page for a
  # puzzle this worktree's HEAD predates is untracked, so it survives, and the
  # moment origin commits that same path, rebase refuses to check out over it
  # ("untracked working tree files would be overwritten").
  git clean -qfd -e 'puzzles/**/*.json' -e 'tools/'
  push_race_retry sync_attempt ||
    alert "pre-reset backfill could not bring its worktree up to origin/master or push what it holds — see .prereset.log."
  # An unmerged file is the rest of the night's problem: every commit and every
  # autostash from here on fails, so the job would keep buying annotations it
  # cannot save. Stop while the alert still names one cause.
  if [ -n "$(git ls-files -u)" ]; then
    alert "pre-reset backfill wedged its worktree — a rebase left these unmerged: $(git diff --name-only --diff-filter=U | tr '\n' ' '). Nothing more can commit, so the run stopped rather than spend on work it cannot save. Resolve in $PWD, then push."
    exit 1
  fi
}

# Record where a pool interval left the meters, and decide whether to go on.
#   $1 weekly percent at its start  $2 hours it took
#   $3 runs in flight on average over it, measured
#   $4 how many runs failed in it  $5 five-hour percent at its start
#   $6 the pool's width at its end
# Returns non-zero when the caller should stop.
#
# The meter line is what tools/prereset_plan.py per_run_rate reads: five-hour
# points over hours times the average in flight is points per run-hour.
after_wave() {
  local before="$1" hours="$2" avg="$3" failed="$4" before_s="$5" pool="$6" now now_s s_read=1
  NAPPED=0
  publish_shared_data
  now=$(python3 tools/weekly_usage.py 2>/dev/null || echo "$before")
  now_s=$(python3 tools/weekly_usage.py --group session 2>/dev/null) || { now_s="$before_s"; s_read=0; }
  echo "  weekly ${before}% -> ${now}%, five-hour ${before_s}% -> ${now_s}% in ${hours}h at width ${avg} (pool of ${pool})"
  # Where the weekly meter stood, and when it turns over. The meter reads 0% the
  # instant it does, so a week that landed at 100% and one that landed at 54%
  # look identical the morning after; the landing report above reads this back
  # on the first fire after the reset and says the number out loud.
  echo "$now $RESET_AT" > "$LANDING_FILE"
  [ "${failed:-1}" -eq 0 ] && return 0
  # A failed run with room still on the weekly clock is the FIVE-hour limit
  # only when that meter says so, and that clears by itself. Only the seven-day
  # number gets to end the run. awk -v, never string interpolation: an empty
  # reading spliced into the program is a syntax error, not a missing number.
  if awk -v n="$now" -v e="$EXHAUSTED" 'BEGIN{exit !(n >= e)}'; then
    echo "  weekly window is spent (${now}%) — stopping"
    return 1
  fi
  # With the five-hour meter read and below LOCKOUT_PCT the window had room, so
  # no nap clears whatever failed these runs. An unread meter counts as locked:
  # a nap wasted is an hour, a lockout read as a bad puzzle loses the puzzle.
  if [ "$s_read" = 1 ] && awk -v s="$now_s" -v l="$LOCKOUT_PCT" 'BEGIN{exit !(s < l)}'; then
    drop_failed "$now_s"
    return 0
  fi
  naps=$((naps + 1))
  if [ "$naps" -gt "$MAX_NAPS" ]; then
    echo "  $naps waits already and runs still fail — stopping rather than looping"
    return 1
  fi
  # Sleep until the five-hour window actually turns over, asked rather than
  # guessed: a nap shorter than the lockout spends a nap on runs that were
  # always going to fail. The runs still in flight finish first (into the
  # lockout, so they mostly fail and are requeued with the rest), because a nap
  # with runs going would leave them unreaped and the tree unsynced.
  pool_drain
  local nap room left_min
  left_min=$(session_left_min)
  nap=$(awk -v h="$left_min" 'BEGIN{printf "%d", (h == "" ? 1 : h / 60) * 3600 + 120}')
  room=$(( STOP_AT - $(date +%s) - 60 ))
  [ "$nap" -gt "$room" ] && nap="$room"
  if [ "$nap" -le 0 ]; then return 1; fi
  echo "  runs failed at ${now}% weekly — five-hour limit; waiting ${nap}s (nap $naps)"
  NAPPED=1
  sleep "$nap"
  return 0
}

# Drop the puzzles that failed for reasons of their own. Resuming their
# conversations only replays the failure, so the session, the resume note and
# the half-done edit all go; the queue has already walked past them and
# requeue_failed only runs after a nap, so this run does not come back to them.
# A new annotation is also entered in tools/failed_inputs.py, which keeps it
# out of later runs until its inputs change — and which refuses the entry
# itself when the run's last words were a limit or the network.
#   $1 the five-hour meter the failure was read at
drop_failed() {
  local id
  for id in ${WAVE_FAILED_IDS[@]+"${WAVE_FAILED_IDS[@]}"}; do
    echo "  [$id] failed with the five-hour window at ${1}% — not a lockout, dropped for this run"
    rm -f "/tmp/ct-prereset-$id.resume" "/tmp/ct-prereset-$id.sid"
    [ "$DRY_RUN" = 1 ] && continue
    discard_puzzle "$id"
    [ "$WAVE_WHAT" = Annotate ] || continue
    python3 tools/failed_inputs.py record annotate "$id" --reason \
      "$(grep -v '^[[:space:]]*$' "/tmp/ct-prereset-$id.txt" | tail -8 | tr '\n' ' ')" \
      | sed 's/^/  /'
  done
}

# Commit whatever a task produced, but only if the tree still validates. A run
# that ran out of room mid-file leaves a half-written annotation behind, and
# committing that would publish a broken puzzle page at 04:45.
commit_puzzle() {
  local num="$1" what="$2" attempt="${3:-first}"   # num is a puzzle ID, e.g. cryptic-30089
  if [ "$DRY_RUN" = 1 ]; then echo "  would commit $what $num"; return 0; fi
  # This puzzle only. A whole-tree run would fail for a sibling in the pool
  # that is still mid-write, and discard a good annotation to punish it.
  if ! python3 tools/validate_annotations.py "$num" >/tmp/ct-prereset-validate.txt 2>&1; then
    # A puzzle is twenty-odd clues of solving and a validation failure is
    # usually one of them, so the errors go back to the conversation that wrote
    # them before anything is thrown away. run_claude resumes that same session,
    # which still holds the solve — a fresh run would buy all of it again to fix
    # one clue. One attempt only: a second failure means the run cannot see what
    # is wrong with it, and repeating that is the waste this avoids.
    if [ "$attempt" = first ]; then
      local file
      file=$(python3 tools/puzzle_paths.py "$num")
      printf '%s\n\n%s\n\n%s\n' \
        "$file does not validate:" \
        "$(grep -E '^  ERROR' /tmp/ct-prereset-validate.txt)" \
        "Fix those clues in $file and nothing else, following tools/annotate_prompt.md, then run python3 tools/annotate_check.py $num until it reports clean. Do not commit." \
        >"/tmp/ct-prereset-$num.resume"
      echo "  [$num] did not validate — handing the errors back rather than discarding the puzzle"
      # Even a fix run the limit cuts off may have landed its edit, so the
      # second pass runs either way and decides on what is on disk.
      pool_mark; POOL_FIXING=1
      run_claude "$num" "$(cat "/tmp/ct-prereset-$num.resume")" || true
      pool_mark; POOL_FIXING=0
      commit_puzzle "$num" "$what" retry
      return $?
    fi
    # The work is thrown away and the puzzle stays unannotated, which is worth
    # saying out loud. Sent through alert so the line goes out explained
    # rather than as one more failure alert.sh found nobody had written an
    # alert for; quoting it verbatim is what marks it claimed.
    alert "$what $num was discarded — it did not validate, so that puzzle stays unannotated:"$'\n'"VALIDATION FAILED after $what $num — discarding that puzzle's changes"$'\n'"\`\`\`"$'\n'"$(grep -E '^  ERROR' /tmp/ct-prereset-validate.txt | head -5)"$'\n'"\`\`\`"
    tail -5 /tmp/ct-prereset-validate.txt
    # Recorded against the puzzle's inputs, not the window: this run finished
    # and was rejected, which is the one failure that says something about the
    # grid. It stays out of the queue until those inputs change.
    python3 tools/failed_inputs.py record annotate "$num" --judged \
      --reason "$(grep -E '^  ERROR' /tmp/ct-prereset-validate.txt | head -1)" || true
    discard_puzzle "$num"
    return 1
  fi
  # Solved-but-short is not a failure anywhere else in this pipeline: the nulled
  # clues just ship as "answers only". Say so, once, per puzzle.
  loss=$(python3 tools/check_annotation_loss.py "$num" 2>&1) || \
    alert "pre-reset backfill left clues blank — $loss. They ship with no teaching ladder, and validate_annotations.py fails the puzzle for it."
  echo "$loss"
  if [ -n "$(git status --porcelain -- "$(puzzle_spec "$num")")" ]; then
    # One puzzle, on purpose: this job runs for hours and publishes as it goes,
    # so each finished puzzle reaches the site without waiting for the rest.
    # Named because it was just written, not as an allow-list — the sweep at the
    # end takes everything. -A, so a file that changed year folders goes in as
    # a rename rather than as a new copy beside the old one. fetch_puzzle.py
    # goes with it: a clue the run corrected is only valid beside its
    # SOURCE_CLUE_WRONG row, so the puzzle must not land without it.
    git add -A -- "$(puzzle_spec "$num")" tools/fetch_puzzle.py
    if ! out=$(git commit -q -m "$(printf '%s %s\n\n%s' "$what" "$num" "$(python3 tools/provenance.py trailer)")" 2>&1); then
      # push_puzzle_commit.sh would find HEAD already on origin and exit 0, so
      # a refused commit has to stop here or the log says "committed".
      alert "pre-reset backfill could not commit $what $num, so nothing it annotates reaches the site until this is fixed: $(printf '%s' "$out" | tail -5)"
      return 1
    fi
    # Straight to origin/master without touching the tree: siblings in the
    # pool are still writing here. The tree catches up in sync_wave.
    tools/push_puzzle_commit.sh ||
      alert "pre-reset backfill committed $what $num but could not push it — the site will not show it until the pool's next sync retries. See .prereset.log."
    echo "committed $what $num"
  else
    echo "$what $num produced no change"
  fi
  return 0
}

if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: claude CLI not on PATH ($PATH) — nothing to do."
  exit 1
fi

python3 tools/fetch_puzzle.py --reindex >/dev/null

# Top the queue up from the archives before reading it. A window spent with
# nothing left to annotate wastes exactly as much as a window that stops early,
# and the papers publish four or five a day against a burn that clears far more,
# so the queue empties on its own. tools/extend_archive.py walks each paper
# backwards until the queue is deeper than the best week this job has had.
#
# Here rather than when the queue runs dry: the queue is read once below, and
# fetching mid-pool would race the reindex the running annotators read through.
#
# Never fatal. A paper being down is a smaller problem than not annotating.
# Through publish_fetched.sh, which commits and pushes what was fetched before
# any annotator starts: an untracked fetched file blocks the sync's rebase the
# moment origin commits the same path.
if [ "$DRY_RUN" = 1 ]; then
  python3 tools/extend_archive.py --dry-run || true
else
  tools/publish_fetched.sh python3 tools/extend_archive.py ||
    echo "archive extend failed or its puzzles could not be published — running on what is already on disk"
fi

# --- 1. un-annotated puzzles, quiptics first ---------------------------------
echo "un-annotated backlog, newest first:"
annotate_blocked=$(python3 tools/failed_inputs.py skipped annotate)
todo=$(python3 - "$annotate_blocked" <<'EOF'
import json, os, sys
from datetime import date
sys.path.insert(0, "tools")
from series import puzzle_day
idx = json.load(open("puzzles/index.json"))
# Selection here is by date and nothing else, so a puzzle that fails is the
# newest un-annotated puzzle again at the next checkpoint and on tomorrow's run, and
# is solved from scratch at a full puzzle's price each time — everyman-4110 was
# bought three times over one word its setter never wrote. The nightly job has
# skipped these since tools/failed_inputs.py; this is the same queue and
# reads the same ledger.
blocked = set(sys.argv[1].split())
todo = [p for p in idx["puzzles"] if not p["annotated"] and p.get("hasSolutions")
        and p["id"] not in blocked]
# $CT_SERIES, a space-separated list of series keys, narrows the burn to those
# papers. Unset or empty means every series.
only = set(os.environ.get("CT_SERIES", "").split())
if only:
    todo = [p for p in todo if p["series"] in only]
# Round-robin across the series, newest first inside each one.
#
# Newest first, and nothing else, inside a lane. Recency is the only property
# of a puzzle that predicts whether anyone will look for it: 79% of the site's
# search impressions land on the two most recent publication months. Any other
# key — number, series tier, measured demand — ranks something above a newer
# puzzle, and there is no evidence that anything beats being new.
#
# Measured demand in particular must NOT be a sort key here, however tempting a
# per-puzzle impression count looks. Impressions accumulate with age, so the
# only puzzles that can score high are the old ones; sorting by it walks the
# queue backwards, which is precisely the order this is supposed to avoid.
#
# Round-robin, not one flat date sort, because a flat sort by date runs the
# whole of the deepest paper's recent archive before the shallowest paper's
# newest gap, and the backlog is always deeper than one window of quota. This
# way no series can starve another and every series' newest gap is reached
# within the pool's first round.
#
# Not by number, either: each paper numbers from its own 1, so a number sort is
# a series sort wearing a disguise.
lanes = {}
for p in todo:
    lanes.setdefault(p["series"], []).append(p)
# A book puzzle holds a `year` rather than a `date`, and a cyclops puzzle not
# yet dated off its neighbours holds neither, so puzzle_day() makes the key a
# day. Undated sorts last
# inside its lane — "newest first" has nothing to say about a puzzle with no when — and
# never raises: this key crashed the whole listing, which is read with $(...),
# so one None emptied the queue and the pool spent itself on definitionFit
# instead of on the backlog it exists to clear.
for lane in lanes.values():
    lane.sort(key=lambda p: puzzle_day(p) or date.min, reverse=True)
# Series order within a round, so a window cut short by a lockout has spent
# itself on the papers people search for most. This ranks SERIES, never
# puzzles: every entry in a round is already its own lane's newest gap. A series
# missing from this list still runs; it just goes at the back of each cycle.
BY_DEMAND = ["everyman", "indysunday", "quiptic", "cryptic", "independent"]
cycle = sorted(lanes, key=lambda s: (BY_DEMAND.index(s) if s in BY_DEMAND
                                     else len(BY_DEMAND), s))
todo = [lanes[s][i]
        for i in range(max((len(l) for l in lanes.values()), default=0))
        for s in cycle if i < len(lanes[s])]
# The order this job spends a whole window in is worth one readable line in the
# log. It ran in the wrong order for weeks behind a single line listing 166 ids.
# stderr, because stdout is the queue itself.
for p in todo[:5]:
    when = (f"{p['year']:<10}" if "year" in p
            else f"{p['date']:<10}" if "date" in p else "  undated  ")
    print(f"  {when}  {p['id']}", file=sys.stderr)
if len(todo) > 5:
    print(f"  ... and {len(todo) - 5} older", file=sys.stderr)
# IDs, not numbers: an id is what tools/puzzle_paths.py finds a file by, so
# nothing downstream has to resolve a number that two papers could one day share.
print(" ".join(p["id"] for p in todo))
EOF
)

# Not "Guardian crossword": since 2026-08-05 some of these are the
# Independent's. The puzzle file records its own series and publisher.
ANNOTATE_PROMPT="Annotate the crossword @ in this repo, whose clues and answers are in tools/_puzzle_@.json. Follow tools/annotate_prompt.md exactly (it is your system prompt's appendix; do not open the file), including running 'python3 tools/annotate_check.py @' until it reports clean. Do not commit — the calling script commits."

# The prompt's Reference section, restated from the code that enforces it. Same
# reason daily_update.sh does it: the run should not have to grep for a rule.
python3 "$REPO/tools/build_annotate_prompt.py"

naps=0
queue=($todo)
at=0
# Reordered at every checkpoint (pool_interval_start). A stop here still runs
# the backfills below, which stop at once if it was the deadline.
[ ${#queue[@]} -gt 0 ] && run_pool "Annotate" "$ANNOTATE_PROMPT" 1

# --- 2. grandfathered-field backfill ------------------------------------------
# Additive only: these puzzles are already annotated and their hints are fine,
# they just predate a field. Anything that rewrites an existing hint here is a
# bug, not an improvement.
#
# The list of fields is read from tools/annotation_backlog.json, so a rule added
# next month is drained by this job without anyone editing it. Fields drain in
# the file's key order, which is BACKLOG_MARKERS order in
# tools/validate_annotations.py (write_backlog writes them so).
backlog_fields=$(python3 -c 'import json;print(" ".join(k for k in json.load(open("tools/annotation_backlog.json")) if not k.startswith("_")))')

for field in $backlog_fields; do
  # Smallest backlog first: with an unknown amount of quota left, finishing four
  # puzzles beats getting most of the way through one.
  nums=$(python3 -c 'import json,sys
d=json.load(open("tools/annotation_backlog.json")).get(sys.argv[1],{})
print(" ".join(n for n,_ in sorted(d.items(), key=lambda kv: kv[1])))' "$field")
  echo "$field backlog: ${nums:-none}"
  name="\`$field\`"
  case "$field" in
    explanation.definitionFit) what="ONE sentence saying why the answer means the definition; it renders last in the walkthrough" ;;
    indicators.note) name="\`note\` on each indicator object"
      what="ONE sentence saying why THOSE words carry THAT instruction — never the generic sentence about what the device does, and never a word of the answer" ;;
    explanation.surface) what="ONE sentence, 25 words max, of the picture the clue pretends to paint — never its mechanics" ;;
    indicators.for) name="\`for\` on each indicator object"
      what="the one name from the clue's own \`type\` whose operation those words signal" ;;
    *) what="the field as tools/annotate_prompt.md describes it" ;;
  esac
  prompt="In this repo, add the missing $name to every annotated clue in @PATH@ that lacks one. It is $what. tools/annotate_prompt.md (appended to your system prompt) and STYLE.md set the voice, and read an existing puzzle that already has the field so yours match. This is ADDITIVE: change nothing else, do not rewrite existing hints, types, indicator texts or assembly. Run python3 tools/annotate_check.py @ until it reports clean. Do not commit — the calling script commits."
  queue=($nums)
  at=0
  if [ ${#queue[@]} -gt 0 ]; then
    run_pool "Backfill $field for" "$prompt" || break
  fi
done

if [ "$DRY_RUN" = 1 ]; then
  echo "=== dry run — nothing spent, nothing built, nothing committed $(date '+%H:%M') ==="
  exit 0
fi

# Record what got drained. The allowance may only shrink — enforced in
# write_backlog, not merely intended — so every puzzle finished here is a puzzle
# that can never quietly lose the field again.
#
# NOT suppressed. This was `>/dev/null 2>&1 || true`, and under it the command
# had been raising TypeError on every run since puzzle ids stopped being bare
# numbers: the sort key was int(id). Months of drained puzzles were never
# recorded, and the one place that would have said so was pointed at /dev/null.
# A puzzle still uncommitted here is one a lockout cut off and the run never got
# back to. Keeping it was worth a retry; publishing it is not — the republish
# below stages the whole tree, and it would go out as a puzzle whose teaching
# ladder stops halfway down. Tomorrow's queue picks it up whole.
if [ -n "$(git status --porcelain -- puzzles/)" ]; then
  echo "dropping unfinished puzzles: $(git status --porcelain -- puzzles/ | awk '{print $2}' | tr '\n' ' ')"
  git checkout -- puzzles/
  git clean -qf -- 'puzzles/*/*/*.json'
fi

# Its per-puzzle report covers the whole corpus, a megabyte that would trim the
# run's own story out of the log; only the summary and a failure are kept.
tighten_summary() { grep -v -e " — OK$" -e " — skipped$" -e "^ *warn:" -e "^$" <<<"$tighten_out"; }
if tighten_out=$(python3 tools/validate_annotations.py --tighten 2>&1); then
  tighten_summary || true
else
  alert "the pre-reset backfill could not record what it drained (validate_annotations.py --tighten failed), so tonight's finished puzzles can still silently lose their notes:
\`\`\`
$(tighten_summary | tail -12)
\`\`\`"
fi

# --- 3. republish -------------------------------------------------------------
# Unconditionally, even if nothing was annotated: this is cheap, deterministic
# and idempotent, and running it always means a run that landed one puzzle and a
# run that landed none leave the tree in the same shape. The index, the static
# pages and the ?v= stamps have to move together, and the smoke test is the last
# word on whether the app still boots against what we just wrote.
python3 tools/fetch_puzzle.py --reindex
# The glossary is generated from the annotated corpus, so rebuild it before the
# final commit.
python3 tools/build_abbreviations.py
# The README's corpus counts are generated too, and annotating is what moves
# them. daily_update.sh rebuilds them before it commits so they are never more
# than one run behind; this job commits annotations as well, and without the
# same line the counts stall at whatever the last nightly saw. They are worth
# saying and not worth stopping for, so a refusal here names itself and the run
# carries on -- the puzzles are the point.
if ! readme_err=$(python3 tools/build_readme.py 2>&1); then
  printf '%s\n' "$readme_err"
  alert "the pre-reset backfill could not regenerate the README, so its corpus counts stay at their last good value:"$'\n'"\`\`\`"$'\n'"$(printf '%s' "$readme_err" | head -12)"$'\n'"\`\`\`"
fi
# A failed build leaves last week's pages on disk, and the smoke test below
# would grade those instead, so the refusal is the alert and the smoke test is
# skipped rather than run against output this tree did not make.
seo_ok=1
if ! seo_err=$(python3 tools/build_seo_pages.py 2>&1); then
  seo_ok=0
  printf '%s\n' "$seo_err"
  alert "the pre-reset backfill could not build the site pages, so its smoke test was skipped: $(printf '%s' "$seo_err" | tail -3)"
fi
python3 tools/stamp_assets.py
if [ "$seo_ok" = 1 ] && command -v node >/dev/null 2>&1; then
  smoke_log="$(mktemp "${TMPDIR:-/tmp}/cryptic-prereset-smoke.XXXXXX")"
  node tools/smoke_test.js 2>&1 | tee "$smoke_log"
  smoke_rc=${PIPESTATUS[0]}
  # A WARNING in a log is not a warning to anyone: this printed failures for weeks
  # while the job committed the tree that caused them. Exit 2 is "no hints yet".
  if [ "$smoke_rc" -ne 0 ] && [ "$smoke_rc" -ne 2 ]; then
    alert "the app's smoke test is failing on the tree the pre-reset backfill is about to commit: $(grep -m3 '^FAIL' "$smoke_log" | tr '\n' ' ')"
  fi
  rm -f "$smoke_log"
fi
# The annotation payloads apply_annotations.py consumed, swept for the same
# reason daily_update.sh sweeps them: ignored is not the same as cleaned up.
rm -f "$REPO/tools/_ann_"*.json "$REPO/tools/_puzzle_"*.json

# The stamps come back off before staging, for the reason daily_update.sh gives
# at its own --unstamp: a ?v= hash in a tracked file is churn, and the deploy
# workflow stamps its own checkout.
python3 tools/stamp_assets.py --unstamp

if [ -n "$(git status --porcelain)" ]; then
  # Everything, for the reason daily_update.sh gives at its own `add -A`: this
  # is a worktree of the job's own, and a named list is both incomplete and
  # fatal — git add aborts on a path that matches nothing, staging none of it.
  git add -A
  git commit -q -m "$(printf 'Republish after pre-reset backfill\n\n%s' "$(python3 tools/provenance.py trailer)")"
  left=$(git status --porcelain | cut -c4- | tr '\n' ' ')
  [ -n "$left" ] && alert "the pre-reset backfill committed, and left these behind in its own worktree: $left"
  # No annotator is running any more, so the rebase is safe here.
  push_race_retry sync_attempt ||
    alert "pre-reset backfill could not push its republish commit — the built pages are committed locally only. See .prereset.log."
fi

# Where the rollout got to. Nothing to flip by hand any more: the ratchet in
# tools/validate_annotations.py already requires these fields of every puzzle
# annotated since they were added, and the numbers below are only the historical
# remainder.
python3 tools/validate_annotations.py 2>&1 | grep -i "backlog" || true

echo "=== done $(date '+%H:%M') ==="
