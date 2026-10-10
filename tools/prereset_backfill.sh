#!/bin/bash
# Spend the weekly usage window on backfills: the week to EXHAUSTED at its reset.
#
# Why this exists, separately from daily_update.sh: unspent quota does not roll
# over. daily_update.sh deliberately refuses to annotate above
# ANNOTATE_MAX_WEEKLY_PCT because a crossword backlog is never worth being
# rate-limited for real work; this job is the other half and runs with NO usage
# gate. It keeps as many runs in flight as spends the paced meter evenly up to
# its reset (tools/prereset_plan.py --width): the weekly one by default, each
# five-hour window after `tools/prereset_plan.py --five-hour`. That holds from
# the moment it starts until the week resets: a rolling pool, where a finished
# run's slot is refilled at once.
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
# Install: household-plugins/cryptic-prereset/plugin.toml, at :05 every hour,
# and that is the only schedule this job has; a fire that finds a run going is
# a no-op (the lock below). On a Mac it would have to be launchctl instead,
# never as well — see daily_update.sh's header.

set -uo pipefail
# The whole burn yields to the bridge: its checks and syncs as well as its runs.
renice -n 19 $$ >/dev/null
# The pool reaps whichever run finishes first with `wait -n -p`, which is bash 5.1.
if (( BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 501 )); then
  echo "ERROR: tools/prereset_backfill.sh needs bash 5.1+ for wait -n -p; this is $BASH_VERSION"
  exit 1
fi
# A checkout of its own, so days of unmetered annotation cannot collide with
# the nightly's units or with somebody editing the repo. See tools/nightly_worktree.sh.
# A commit a dropped run could not push yet is pushed by the next start.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_SALVAGE_PATHS=""
# It rebuilds the generated files itself (--reindex below, before anything
# reads them), so the worktree does not build them first.
# shellcheck disable=SC2034
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
# Set when this process is the burn re-execing itself onto new shell code
# (reexec_self): the file holding the pool's state, beside the run log.
REEXEC_STATE="${CT_PRERESET_STATE:-}"
unset CT_PRERESET_STATE
. "$REPO/tools/claude_path.sh"
# Without this the CLI reads the legacy un-suffixed keychain entry, which a
# file-based /login leaves empty, and every run dies on "Failed to
# authenticate: OAuth session expired and could not be refreshed". See the longer
# note in daily_update.sh.
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
# The runs' grid searches (tools/reconstruct_grid.py) go to the desktop, not this
# host's cores (tools/ocr_remote.py; OCR_REMOTE= keeps them here).
export OCR_REMOTE="${OCR_REMOTE-micro@192.168.1.198,micro@100.68.145.15}"

# claude-auth.sh is deliberately not sourced: the CLI finds its own stored
# login under CLAUDE_CONFIG_DIR, and that file's env token would override the
# stored one with a credential that cannot refresh.
. "$REPO/tools/alert.sh"

# session_id / session_exists — the resume mechanism run_claude below is built on.
. "$REPO/tools/claude_session.sh"
# worker_annotate / worker_apply / worker_finish — one puzzle's model work and
# what is done with it, the same code the nightly (tools/daily_update.sh)
# runs; this script only picks and paces the ids.
. "$REPO/tools/puzzle_worker.sh"
# Each run's sid file and fill, kept where a restart and the tree's reset leave
# them (worker_runs), so a run the restart stopped resumes.
RUNS="$(worker_runs prereset_backfill)" || exit 1

# This run's own output, so the exit trap can report any failure line nobody
# wrote an alert for. See alert_run_failures in alert.sh.
# Spelled out rather than `mktemp -t cryptic-prereset`: -t takes a bare prefix on macOS
# but a template that must contain X's on GNU, so the one spelling cannot mean
# the same thing on both. Every mktemp below is written this way.
# A re-exec keeps the log and the tee its output already goes to.
if [ -n "$REEXEC_STATE" ]; then
  RUN_LOG="${REEXEC_STATE%.state}"
else
  RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/cryptic-prereset.XXXXXX")"
  exec > >(tee -a "$RUN_LOG") 2>&1
fi

# Kept in step with daily_update.sh — Opus, benchmarked against Fable on 30078
# (APP.md). Matching quality at a third the cost matters more here than
# anywhere: a cheaper annotator is straightforwardly more puzzles per reset.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
MODEL="$ANNOTATE_MODEL"
ANNOTATE_EFFORT="${ANNOTATE_EFFORT:-medium}"  # see daily_update.sh
# Niced, with everything it runs: the pool shares this machine with the bridge.
WORKER_MODEL="$MODEL" WORKER_EFFORT="$ANNOTATE_EFFORT" WORKER_WRAP="nice -n 19"
WORKER_JOB="pre-reset backfill"
# Runs to keep in flight, asked at every pool checkpoint with the width now:
# what spends the paced meter (weekly, or five-hour) to EXHAUSTED by its reset,
# capped by free memory and CPU (tools/prereset_plan.py, which logs its inputs). If it prints no
# width the current one stands. At 0 (the bridge alone will spend what the
# week has left, or the machine has no room) nothing new starts, and once the
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
export EXHAUSTED="${EXHAUSTED:-99}"
# Below this on the five-hour meter a failed run was not locked out: the window
# had room, so waiting for it to turn over buys nothing.
LOCKOUT_PCT="${LOCKOUT_PCT:-90}"
# DRY_RUN=1 walks the whole job — queue order, the pool, deadline —
# without calling claude, touching git or rebuilding anything. This job spends
# ungated inference in parallel and cannot be rehearsed any other way.
DRY_RUN="${DRY_RUN:-0}"

if [ -n "$REEXEC_STATE" ]; then
  echo "=== pre-reset backfill re-execed onto $(git rev-parse --short HEAD) $(date '+%Y-%m-%d %H:%M') ==="
else
  echo "=== cryptic-teacher pre-reset backfill $(date '+%Y-%m-%d %H:%M') ==="
fi

# One at a time. This runs for days, so an hourly fire and a hand run overlap
# easily — and two copies would double the width and race each other's commits
# in the one git index. mkdir is the atomic part.
LOCK="$REPO/.prereset.lock"
# The holder writes its pid inside it, because the directory alone cannot say
# whether it belongs to a live run or to one the machine killed: the EXIT trap
# that removes it does not get to run when the container goes down. So a lock
# whose pid names no live backfill, or that carries no pid at all, is taken
# over rather than deferred to. The
# pid is matched against the command line and not merely tested for existence,
# because pids are reused and a restart hands them out again from the bottom.
lock_is_dead() {
  local pid
  pid=$(cat "$LOCK/pid" 2>/dev/null) || return 0
  [ -n "$pid" ] || return 0
  ps -o command= -p "$pid" 2>/dev/null | grep prereset_backfill >/dev/null || return 0
  return 1
}
# A re-exec is the same process, so the lock it took is its own already.
if [ -n "$REEXEC_STATE" ]; then
  [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] || {
    alert "the pre-reset backfill re-execed onto new code and found its lock no longer names it (pid $$) — stopping; the runs it had in flight resume at the next start."
    exit 1
  }
elif ! mkdir "$LOCK" 2>/dev/null; then
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
# A resume note is written for a retry in the same process, about the tree as it
# was then. A run this start finds still recorded in $RUNS was stopped by the
# restart, and its note is written afresh at its launch (worker_put_back), about
# the tree as it is now.
#
# Everything from here to the pool is the start's alone: a re-exec carries the
# deadline and the meters' reads in its state, and keeps its resume notes.
if [ -z "$REEXEC_STATE" ]; then
rm -f /tmp/ct-prereset-*.resume

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
fi

# What the week actually landed at, said once, after it is too late to change —
# because otherwise nobody ever finds out. A run that dies or stalls ends the
# same way as one that spent everything: a meter that reads 0% and no
# evidence it ever read anything else. LANDING_OK is the point below which the
# leftovers were worth having.
LANDING_FILE=".prereset_landing"
LANDING_OK="${LANDING_OK:-90}"
if [ -z "$REEXEC_STATE" ] && [ -f "$LANDING_FILE" ]; then
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
if [ -z "$REEXEC_STATE" ]; then
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
fi
past_deadline() {
  [ "$(date +%s)" -ge "$STOP_AT" ]
}
# One nap per five-hour window left in the week is the plan, not a failure, so
# the allowance is that count with slack. It only bounds runs failing fast for
# some reason other than a lockout; each nap is capped at the deadline anyway.
[ -n "$REEXEC_STATE" ] || MAX_NAPS=$(awk -v h="$resets_in" 'BEGIN{printf "%d", h / 5 + 3}')

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
  # queue[0..at) stays: the checkpoint's backlog re-read reads an index built
  # at start, which still lists what this run annotated, and appends any id
  # the queue no longer holds.
  queue=("${queue[@]:0:$at}" "${back[@]}" "${queue[@]:$at}")
}

# Put the queued ids whose runs a restart stopped (a record left in $RUNS) at
# the front of queue[at..], and keep them there through the re-plan: their
# conversations are already paid for.
resumed=" "
resumed_first() {
  local id first=() rest=()
  for id in "${queue[@]:$at}"; do
    if [ -s "$RUNS/$id.sid" ]; then first+=("$id"); resumed="$resumed$id "; else rest+=("$id"); fi
  done
  [ ${#first[@]} -eq 0 ] && return 0
  echo "resuming first, stopped by the restart: ${first[*]}"
  queue=("${queue[@]:0:$at}" "${first[@]}" ${rest[@]+"${rest[@]}"})
}

# Run one claude task against the repo. Returns non-zero if the run failed.
#
# Its output goes to a file named after the puzzle rather than to the log, because
# several of these run at once and interleaved transcripts belong to nobody.
# The caller prints the tail of each one as it reaps it, in order.
#
# Every run is given a session id up front so that a retry can RESUME it rather
# than start over. A run the limit cut off had already read the puzzle, worked
# out the wordplay and written half the answers down; a fresh -p throws that
# thinking away and buys it a second time. Resuming replays the transcript and
# carries on from the reasoning already paid for. The session lives in
# $RUNS/<id>.sid.
#
# With a third argument the puzzle has no key, and the run solves it cold first,
# writing its fill there (tools/puzzle_worker.sh); it writes the copy it
# annotates itself, once that fill is in.
run_claude() {
  local tag="$1" prompt="$2" fill="${3:-}" log resume_at note=""
  log="/tmp/ct-prereset-$1.txt"
  resume_at="/tmp/ct-prereset-$1.resume"
  if [ "$DRY_RUN" = 1 ]; then
    echo "would spend one $MODEL run on $tag" >"$log"
    sleep 1
    return 0
  fi
  [ -s "$resume_at" ] && note=$(cat "$resume_at")
  rm -f "$resume_at"
  # The annotate prompt names this copy, which leaves out the solutions detail:
  # that names the blog, which annotate_check.py discloses only once the run is stuck.
  [ -n "$fill" ] || python3 tools/annotate_check.py --view "$tag" >/dev/null
  worker_annotate "$tag" "$log" "$RUNS/$tag.sid" "$prompt" "$note" "$fill"
  local rc=$?
  # Running out of window is how this job is SUPPOSED to end, so a plain failure
  # stays quiet. A broken login is a different animal: it fails identically, at
  # the same point, every night, and looks like the normal ending, so it is
  # alerted on its own.
  if [ $rc -ne 0 ] && grep -qi "Failed to authenticate\|Not logged in" "$log"; then
    alert "pre-reset backfill cannot authenticate — the CLI needs a fresh /login. Nothing has been backfilled since this started."
  fi
  return $rc
}

# Whether pool_launch should have the run solve the puzzle before annotating it.
needs_solve() { python3 tools/prereset_plan.py --unsolved "$1"; }

# A finished solving run: tools/puzzle_worker.sh checks its fill again from the
# committed puzzle and puts the run's annotations back on it. A rejected one
# ships nothing and is recorded in the solve ledger, which keeps it out of the
# queue until its inputs change.
solve_applied() {
  local id="$1" fill="$RUNS/$1.fill" verdict="/tmp/ct-prereset-$1.verdict"
  if [ "$DRY_RUN" = 1 ]; then
    echo "  [$id] would apply the fill"
  elif ! worker_apply "$id" "$fill" "/tmp/ct-prereset-$id.txt" "$verdict" "$RUNS/$id.sid"; then
    echo "  [$id] solve rejected, nothing it wrote ships: $(grep -v '^[[:space:]]*$' "$verdict" | tail -1 | cut -c1-200)"
    rm -f "$verdict"
    worker_forget "$RUNS/$id.sid"
    return 1
  fi
  rm -f "$fill" "$verdict"
}

# The pool's validation-fix run holds a slot while it runs (pool_mark).
on_fix_run() { pool_mark; POOL_FIXING="$1"; }

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
  tail -5 "/tmp/ct-prereset-$1.txt" 2>/dev/null | sed "s/^/  [$1] failed: /"
  worker_failed "$1" "$2" "/tmp/ct-prereset-$1.resume" "$RUNS/$1.sid" || true
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
# This often the tree is synced with origin (sync_wave), runs still in flight.
POOL_SYNC_SECS="${POOL_SYNC_SECS:-3600}"
declare -A POOL_RUNS=()  # pid -> puzzle id, every run in flight
declare -A POOL_SOLVING=()  # pid -> 1 for each of those that solves its puzzle first
declare -A POOL_ADOPTED=()  # pid -> 1 for each of those the shell before a re-exec started
POOL_RUN_US=0            # run-microseconds in flight since the checkpoint
POOL_MARK_US=0           # when POOL_RUN_US was last brought up to date
POOL_STARTED_US=0        # when the interval since the last checkpoint began
POOL_SYNCED_US=${EPOCHREALTIME/[.,]/}
POOL_LAUNCHED_US=0
POOL_DONE=0              # runs finished since the checkpoint
POOL_FIXING=0            # 1 while commit_puzzle's fix run holds this shell
POOL_REPLANNED_US=0      # when the queue was last re-read and re-ordered
POOL_POLL_SECS=5         # how often pool_reap looks for an adopted run's end
POOL_RESUMING=0          # 1 when run_pool picks up a pool a re-exec carried over

# How many of POOL_RUNS are still running; the rest have finished and wait
# for pool_reap to commit them, holding their slots until it does.
pool_live() {
  local p n=0
  for p in "${!POOL_RUNS[@]}"; do kill -0 "$p" 2>/dev/null && n=$((n + 1)); done
  echo "$n"
}

# Bring POOL_RUN_US up to now. Called before every change to the runs going, so
# the average in flight a checkpoint logs is measured rather than the nominal
# width.
pool_mark() {
  local now=${EPOCHREALTIME/[.,]/}
  POOL_RUN_US=$(( POOL_RUN_US + (${#POOL_RUNS[@]} + POOL_FIXING) * (now - POOL_MARK_US) ))
  POOL_MARK_US=$now
}

pool_launch() {
  local id="$1" prompt wait_us fill=""
  wait_us=$(( POOL_LAUNCHED_US + POOL_LAUNCH_GAP_US - ${EPOCHREALTIME/[.,]/} ))
  [ "$wait_us" -gt 0 ] && sleep "$(printf '%d.%06d' $((wait_us / 1000000)) $((wait_us % 1000000)))"
  local again=""
  # A run the restart stopped: its files back, and the note to resume it with.
  [ -s "/tmp/ct-prereset-$id.resume" ] ||
    worker_put_back "$id" "$WAVE_WHAT" "/tmp/ct-prereset-$id.resume" "$RUNS/$id.sid" >/dev/null
  [ -s "/tmp/ct-prereset-$id.resume" ] && again=", picking up its cut-off conversation"
  pool_mark
  # A conversation that began with a cold solve keeps its fill, and has it
  # checked, however much of the grid its edits filled in.
  if [ "$WAVE_WHAT" = Annotate ] &&
     { [ "$(worker_kind "$RUNS/$id.sid")" = solve ] || needs_solve "$id"; }; then
    again="$again, solving it first"
    fill="$RUNS/$id.fill"
  fi
  prompt="${POOL_TMPL//@PATH@/$(python3 tools/puzzle_paths.py "$id")}"
  # The run leaves its status in a file too, for a shell that re-execed while
  # it ran and so cannot wait for it (pool_reap).
  rm -f "/tmp/ct-prereset-$id.rc"
  { run_claude "$id" "${prompt//@/$id}" "$fill"; rc=$?; echo "$rc" >"/tmp/ct-prereset-$id.rc"; exit "$rc"; } &
  [ -n "$fill" ] && POOL_SOLVING[$!]=1
  POOL_RUNS[$!]="$id"
  POOL_LAUNCHED_US=${EPOCHREALTIME/[.,]/}
  echo "  [$id] started$again (${#POOL_RUNS[@]} of $wide in flight)"
}

# Whether an adopted run has ended: its status file is written, or it is gone
# (or a zombie) without one, which pool_reap counts as a failure.
pool_adopted_done() {
  [ -s "/tmp/ct-prereset-${POOL_RUNS[$1]}.rc" ] && return 0
  kill -0 "$1" 2>/dev/null || return 0
  case "$(ps -o stat= -p "$1" 2>/dev/null)" in Z*) return 0 ;; esac
  return 1
}

# Wait for whichever run finishes first, and commit it or note it for a retry.
pool_reap() {
  local pid="" rc id p
  while :; do
    # A finished run bash has already cleaned out of its job table is invisible
    # to wait -n ("no such job"), though plain wait still returns its status. So
    # finished runs are looked for first, and wait -n only blocks on live ones.
    for p in "${!POOL_RUNS[@]}"; do
      if [ -n "${POOL_ADOPTED[$p]:-}" ]; then
        pool_adopted_done "$p" || continue
        pid=$p
        rc=$(cat "/tmp/ct-prereset-${POOL_RUNS[$p]}.rc" 2>/dev/null)
        case "$rc" in ''|*[!0-9]*) rc=1 ;; esac
        unset "POOL_ADOPTED[$p]"
        break
      fi
      kill -0 "$p" 2>/dev/null && continue
      pid=$p
      wait "$p"
      rc=$?
      break
    done
    [ -n "$pid" ] && break
    # wait -n sees only this shell's children, so while an adopted run is in
    # flight the pool polls instead.
    if [ ${#POOL_ADOPTED[@]} -gt 0 ]; then sleep "$POOL_POLL_SECS"; continue; fi
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
  rm -f "/tmp/ct-prereset-$id.rc"
  POOL_DONE=$((POOL_DONE + 1))
  if [ -n "${POOL_SOLVING[$pid]:-}" ]; then
    unset "POOL_SOLVING[$pid]"
    # Cut off, most likely by a lockout, before its fill went in: requeued to
    # resume that conversation, its fill as it left it.
    if [ "$rc" -ne 0 ] && [ -z "$(git status --porcelain -- "$(puzzle_spec "$id")")" ]; then
      handle_failed_run "$id" "$WAVE_WHAT"
      WAVE_FAILED_IDS+=("$id")
      return
    fi
    solve_applied "$id" || return
  fi
  if [ "$rc" -eq 0 ]; then
    tail -3 "/tmp/ct-prereset-$id.txt" | sed "s/^/  [$id] /"
    commit_puzzle "$id" "$WAVE_WHAT"
  else
    handle_failed_run "$id" "$WAVE_WHAT"
    WAVE_FAILED_IDS+=("$id")
  fi
}

# Let every run in flight finish, then sync.
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
  # The order is tools/prereset_plan.py --cover-first's (head_of_queue), which
  # re-sorts the whole of queue[at..], so what the re-read appends takes its
  # date's place. Cut-off puzzles stay first. Anything but a whole permutation
  # back leaves the order as it was. A dry run plans once. The re-plan takes
  # minutes on a loaded machine and nothing is reaped or launched meanwhile,
  # so it runs at most once per POOL_SYNC_SECS, not at every checkpoint.
  if [ "$POOL_REORDER" = 1 ] && [ "$at" -lt "${#queue[@]}" ] &&
     [ $(( ${EPOCHREALTIME/[.,]/} - POOL_REPLANNED_US )) -ge $(( POOL_SYNC_SECS * 1000000 )) ] &&
     { [ "$DRY_RUN" = 0 ] || [ "$POOL_PLANNED" = 0 ]; }; then
    POOL_REPLANNED_US=${EPOCHREALTIME/[.,]/}
    # A run lasts days: the backlog is read again, so a puzzle filed or made
    # eligible since the run started joins the queue. An id the queue already
    # holds, started or not, is not added again.
    if [ "$POOL_PLANNED" = 1 ]; then
      local -A held=()
      local id
      for id in "${queue[@]}"; do held[$id]=1; done
      for id in $(python3 tools/prereset_plan.py --backlog \
          "$(python3 tools/failed_inputs.py skipped annotate)" \
          "$(python3 tools/failed_inputs.py skipped solve)" 2>/dev/null); do
        [ -n "${held[$id]:-}" ] || queue+=("$id")
      done
    fi
    POOL_PLANNED=1
    local reordered
    reordered=($(printf '%s\n' "${queue[@]:$at}" \
      | python3 tools/prereset_plan.py --cover-first "$requeued$resumed" || true))
    [ "${#reordered[@]}" -eq $(( ${#queue[@]} - at )) ] \
      && queue=("${queue[@]:0:$at}" "${reordered[@]}")
  fi
  # Read after the re-plan, which can take longer than a five-hour window has
  # left on a loaded machine: the width launched is the one for now.
  POOL_BEFORE=$(python3 tools/weekly_usage.py 2>/dev/null || echo 0)
  POOL_BEFORE_S=$(python3 tools/weekly_usage.py --group session 2>/dev/null || echo 0)
  wide=$(wave_width)
  pool_mark
  POOL_RUN_US=0
  POOL_STARTED_US=$POOL_MARK_US
  echo "--- pool of $wide: ${#POOL_RUNS[@]} in flight ($(pool_live) running), $(( ${#queue[@]} - at )) queued${queue[$at]:+, next ${queue[*]:$at:3}} ---"
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
  local stop=0
  if [ "$POOL_RESUMING" = 1 ]; then
    # Re-execed mid-pool: the pool's state, its runs in flight among it, is the
    # shell's before the exec.
    POOL_RESUMING=0
  else
    WAVE_WHAT="$1" POOL_TMPL="$2" POOL_REORDER="${3:-0}" POOL_PLANNED=0
    resumed_first
    pool_interval_start
  fi
  while :; do
    if [ "$stop" = 0 ] && past_deadline; then echo "deadline reached — stopping"; stop=1; fi
    if [ "$stop" = 0 ] &&
       [ $(( ${EPOCHREALTIME/[.,]/} - POOL_SYNCED_US )) -ge $(( POOL_SYNC_SECS * 1000000 )) ]; then
      sync_wave
      POOL_SYNCED_US=${EPOCHREALTIME/[.,]/}
    fi
    # A sync that brought new shell code, here or in after_wave's drain.
    [ "$stop" = 0 ] && [ "$(shell_sum)" != "$SHELL_SUM" ] && reexec_self
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

# --- re-exec onto new shell code ----------------------------------------------
# Bash keeps the functions it parsed at the start, so a sync that moves this
# tree's shell code (this script and what it sources) reaches the burn only
# when it re-execs: at run_pool's loop top, between reaps. The exec keeps the
# pid, so the lock, the tree's lease (fd 9), the log's tee and the runs in
# flight all stay; the new shell adopts the runs (POOL_ADOPTED), reading each
# one's end off its status file since it cannot wait for them, and goes on
# with the queue where the old one stopped. Nothing in flight is stopped or
# run again.
SHELL_FILES=("$REPO/tools/prereset_backfill.sh" "$REPO/tools/puzzle_worker.sh"
  "$REPO/tools/claude_session.sh" "$REPO/tools/alert.sh" "$REPO/tools/claude_path.sh")
PRERESET_SELF="$REPO/tools/prereset_backfill.sh"
shell_sum() {
  cat "${SHELL_FILES[@]}" 2>/dev/null </dev/null | cksum
}
SHELL_SUM=$(shell_sum)
# The state the main sequence and run_pool carry across the exec.
REEXEC_VARS=(queue at requeued resumed naps NAPPED WAVE_FAILED_IDS WAVE_WHAT POOL_TMPL
  POOL_REORDER POOL_PLANNED POOL_RUNS POOL_SOLVING POOL_RUN_US POOL_MARK_US POOL_STARTED_US
  POOL_SYNCED_US POOL_LAUNCHED_US POOL_DONE POOL_REPLANNED_US POOL_BEFORE POOL_BEFORE_S wide
  resets_in RESET_AT STOP_AT MAX_NAPS POOL_PHASE fields field_i)
reexec_self() {
  local state="$RUN_LOG.state" err
  # New code that does not parse would kill the burn with its runs in flight.
  if ! err=$(bash -n "$PRERESET_SELF" 2>&1); then
    alert "the pre-reset backfill's tree has shell code that does not parse, so it keeps running the old: $err"
    SHELL_SUM=$(shell_sum)
    return 1
  fi
  declare -p "${REEXEC_VARS[@]}" | sed 's/^declare -/declare -g -/' >"$state" || return 1
  echo "=== shell code moved: re-execing onto $(git rev-parse --short HEAD), adopting ${#POOL_RUNS[@]} runs in flight ==="
  export CT_PRERESET_STATE="$state"
  shopt -s execfail
  exec "$BASH" -c '. "$0"' "$PRERESET_SELF"
  shopt -u execfail
  unset CT_PRERESET_STATE
  rm -f "$state"
  alert "the pre-reset backfill could not re-exec onto its new shell code, so it keeps running the old"
  SHELL_SUM=$(shell_sum)
}
# In the new shell: the old one's state, every run in flight adopted.
reexec_load() {
  local p
  eval "$(cat "$1")" || return 1
  rm -f "$1"
  for p in "${!POOL_RUNS[@]}"; do POOL_ADOPTED[$p]=1; done
  POOL_RESUMING=1
}

# One try at publishing every commit of this tree origin/master lacks, run
# through push_race_retry. Each goes by tools/push_puzzle_commit.sh, which
# replays it onto origin in memory, so the working tree is never touched and
# runs in flight cannot make it fail. A commit that will not replay is skipped
# when origin/master already holds its puzzle files byte for byte (published by
# another path: a hand rebuild, a sibling's merge); any other stops the attempt.
sync_attempt() {
  local c paths
  git fetch -q origin master || return
  for c in $(git cherry origin/master HEAD | sed -n 's/^+ //p'); do
    tools/push_puzzle_commit.sh "$c" && continue
    paths=$(git diff-tree --no-commit-id --name-only -r "$c" -- 'puzzles/*.json')
    if [ -n "$paths" ] && git diff --quiet origin/master "$c" -- $paths; then
      echo "sync: dropping $(git log -1 --format='%h %s' "$c") — origin/master already has its puzzle" >&2
      continue
    fi
    echo "sync: $(git log -1 --format='%h %s' "$c") does not apply to origin/master" >&2
    return 1
  done
}

# Move this tree to origin/master once sync_attempt has published everything
# HEAD holds. reset --keep updates only the files that differ between HEAD and
# origin/master, keeps every local edit to the rest, and refuses as a whole,
# touching nothing, when a file it would update has local edits or an untracked
# file sits in its way: a run in flight writing a puzzle origin also changed.
# Prints git's refusal and returns non-zero.
sync_tree() {
  git reset -q --keep origin/master
}

# Every shared data file the runs wrote, committed and pushed the way a puzzle
# is, so safe with runs in flight: the corroboration ledger extend_archive.py's
# fetches write, for one. The directory, not a list, so the next such file is
# covered too. Left uncommitted, a ledger origin also moved would make every
# sync_tree refuse. Committed, the keyed ones merge per key on the way to origin
# (.gitattributes, tools/json_merge.py). Published at every checkpoint rather than at the
# republish, so the puzzles already pushed validate on master, and a burn that
# is killed does not lose them to nightly_worktree.sh's reset --hard.
# The source-correction tables are left out (tools/own_rows.py paths): their
# rows ship only in their own puzzle's commit, beside the clue they correct, and
# a run still in flight has filed rows its puzzle file does not hold yet.
publish_shared_data() {
  [ "$DRY_RUN" = 1 ] && return 0
  # shellcheck disable=SC2046  # one path per line, none with a space
  set -- tools/data/ $(python3 tools/own_rows.py paths | sed 's/^/:(exclude)/')
  [ -n "$(git status --porcelain -- "$@")" ] || return 0
  index_lock
  if ! git add -A -- "$@"; then
    git reset -q -- "$@"
    index_unlock
    return 0
  fi
  worker_commit "Shared data from the pre-reset backfill" "$@" || true
}

# Publish what the per-puzzle pushes could not, and bring this tree up to
# origin/master, with runs in flight: nothing here touches a file a run writes.
# Planner and code changes reach the burn this way.
sync_wave() {
  [ "$DRY_RUN" = 1 ] && return 0
  publish_shared_data
  # Nothing generated is worth carrying: the republish step rewrites every one
  # of these files wholesale from the puzzle sources. A stale copy left modified
  # would make sync_tree refuse the first time origin rebuilt the same page.
  #
  # Exclusions, not a list of what to drop, for the reason the republish `add
  # -A` gives: a named list of generated paths is incomplete the day someone
  # adds a generated path. What is excluded is what a run authors, in flight or
  # kept after a cut-off: its puzzle, the clues-only file its solve removes, and
  # shared data under tools/, which publish_shared_data has just committed.
  git checkout -q -- . ':(exclude)puzzles/*.json' ':(exclude)clues_only/' ':(exclude)tools/'
  # checkout only restores files git is tracking HERE. A generated page for a
  # puzzle this worktree's HEAD predates is untracked, and the moment origin
  # commits that same path, sync_tree refuses to write over it.
  git clean -qfd -e 'puzzles/**/*.json' -e 'clues_only/' -e 'tools/'
  if ! push_race_retry sync_attempt; then
    alert "pre-reset backfill could not push what its worktree holds onto origin/master, so it stays where it is and runs old code — see .prereset.log."
    return 0
  fi
  local out
  if out=$(sync_tree 2>&1); then
    echo "sync: tree at $(git rev-parse --short HEAD), ${#POOL_RUNS[@]} runs in flight"
    return 0
  fi
  # With runs in flight a refusal names a puzzle one of them is writing, and the
  # next sync, after it is committed, gets through. With none, nothing will
  # clear it by itself.
  if [ ${#POOL_RUNS[@]} -gt 0 ]; then
    echo "sync: tree stays at $(git rev-parse --short HEAD) until the next sync, ${#POOL_RUNS[@]} runs in flight: $out"
  else
    alert "pre-reset backfill could not move its worktree to origin/master, so it runs old code: $out"
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
  # with runs going would leave them unreaped.
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
    rm -f "/tmp/ct-prereset-$id.resume"
    worker_forget "$RUNS/$id.sid"
    [ "$DRY_RUN" = 1 ] && continue
    discard_puzzle "$id"
    [ "$WAVE_WHAT" = Annotate ] || continue
    python3 tools/failed_inputs.py record annotate "$id" --reason \
      "$(grep -v '^[[:space:]]*$' "/tmp/ct-prereset-$id.txt" | tail -8 | tr '\n' ' ')" \
      | sed 's/^/  /'
  done
}

# Validate, commit and push what a finished run produced (tools/puzzle_worker.sh).
# A puzzle whose unparsed model answers were reopened is solved again next.
commit_puzzle() {
  local id="$1" what="$2"
  if [ "$DRY_RUN" = 1 ]; then echo "  would commit $what $id"; return 0; fi
  worker_finish "$id" "$what" "$RUNS/$id.sid" "/tmp/ct-prereset-$id.txt"
  case $? in
    0) return 0 ;;
    2) queue=("${queue[@]:0:$at}" "$id" "${queue[@]:$at}")
       echo "  [$id] solving it again next"
       return 1 ;;
    *) return 1 ;;
  esac
}

if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: claude CLI not on PATH ($PATH) — nothing to do."
  exit 1
fi

POOL_PHASE="" fields=() field_i=0
if [ -n "$REEXEC_STATE" ]; then
  reexec_load "$REEXEC_STATE" || { alert "the pre-reset backfill re-execed but could not read its state $REEXEC_STATE — stopping; the runs it had in flight resume at the next start."; exit 1; }
  echo "adopted ${#POOL_ADOPTED[@]} runs in flight: ${POOL_RUNS[*]}"
fi
# The start's alone: a re-exec has runs in flight reading the index, and its
# queue already.
if [ -z "$REEXEC_STATE" ]; then
python3 tools/fetch_puzzle.py --reindex >/dev/null

# Top the queue up from the archives before reading it. A window spent with
# nothing left to annotate wastes exactly as much as a window that stops early,
# and the papers publish four or five a day against a burn that clears far more,
# so the queue empties on its own. tools/extend_archive.py walks each paper
# backwards until the queue is deeper than the best week this job has had.
#
# Here rather than when the queue runs dry: fetching mid-pool would race the
# reindex the running annotators read through.
#
# Never fatal. A paper being down is a smaller problem than not annotating.
# Through publish_fetched.sh, which commits and pushes what was fetched before
# any annotator starts: an untracked fetched file blocks the sync (sync_tree) the
# moment origin commits the same path.
if [ "$DRY_RUN" = 1 ]; then
  python3 tools/extend_archive.py --dry-run || true
else
  tools/publish_fetched.sh python3 tools/extend_archive.py ||
    echo "archive extend failed or its puzzles could not be published — running on what is already on disk"
fi

# --- 1. un-annotated puzzles, and the answerless solved first ---------------
# The queue, its order and what it leaves out are tools/prereset_plan.py's
# backlog(). A puzzle without all its answers is solved cold by the run that
# annotates it (pool_launch): its clues are all a puzzle has to come with. A puzzle
# held as its clues alone is queued too; its solve files its grid.
echo "un-annotated backlog, newest first:"
annotate_blocked=$(python3 tools/failed_inputs.py skipped annotate)
solve_blocked=$(python3 tools/failed_inputs.py skipped solve)
todo=$(python3 tools/prereset_plan.py --backlog "$annotate_blocked" "$solve_blocked")
naps=0
queue=($todo)
at=0
fi

# Not "Guardian crossword": the queue spans every series. The puzzle file
# records its own series and publisher.
ANNOTATE_PROMPT="Annotate the crossword @ in this repo, whose clues and answers are in tools/_puzzle_@.json. Follow tools/annotate_prompt.md exactly (it is your system prompt's appendix; do not open the file), including running 'python3 tools/annotate_check.py @' until it reports clean. Do not commit — the calling script commits."

# The prompt's Reference section, restated from the code that enforces it. Same
# reason daily_update.sh does it: the run should not have to grep for a rule.
python3 "$REPO/tools/build_annotate_prompt.py"

# Reordered at every checkpoint (pool_interval_start). A stop here still runs
# the backfills below, which stop at once if it was the deadline.
if [ "$POOL_PHASE" = "" ] || [ "$POOL_PHASE" = annotate ]; then
  POOL_PHASE=annotate
  [ ${#queue[@]} -gt 0 ] && run_pool "Annotate" "$ANNOTATE_PROMPT" 1
  # Read here, so a re-exec in the field backfills keeps the list it was
  # draining.
  fields=($(python3 -c 'import json;print(" ".join(k for k in json.load(open("tools/annotation_backlog.json")) if not k.startswith("_")))'))
  field_i=0
fi

# --- 2. grandfathered-field backfill ------------------------------------------
# Additive only: these puzzles are already annotated and their hints are fine,
# they just predate a field. Anything that rewrites an existing hint here is a
# bug, not an improvement.
#
# The list of fields is read from tools/annotation_backlog.json, so a rule added
# next month is drained by this job without anyone editing it. Fields drain in
# the file's key order, which is BACKLOG_MARKERS order in
# tools/validate_annotations.py (write_backlog writes them so).
for ((; field_i < ${#fields[@]}; field_i++)); do
  field=${fields[$field_i]}
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
    messages) name="\`hiddenLetter\` on each clue the preamble's hidden-letter device touches, and the puzzle's \`messages\` (the _ann file's \"messages\" key),"
      what="the letter the clue's wordplay adds, omits or misprints, and the phrase those letters spell, as tools/annotate_prompt.md describes; an omitted letter gets a block with no clueFragment" ;;
    assembly.anagrams) name="\`assembly.anagrams\` entry"
      what="{fodder, gives} for the clue's shuffle: every letter that goes in, and what it becomes" ;;
    *) what="the field as tools/annotate_prompt.md describes it" ;;
  esac
  prompt="In this repo, add the missing $name to every annotated clue in @PATH@ that lacks one. It is $what. tools/annotate_prompt.md (appended to your system prompt) and STYLE.md set the voice, and read an existing puzzle that already has the field so yours match. This is ADDITIVE: change nothing else, do not rewrite existing hints, types, indicator texts or assembly. Run python3 tools/annotate_check.py @ until it reports clean. Do not commit — the calling script commits."
  # The field a re-exec came back into keeps its queue.
  if [ "$POOL_PHASE" != "$field" ]; then
    POOL_PHASE=$field
    queue=($nums)
    at=0
  fi
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
# that can never quietly lose the field again. Not suppressed: a failure here
# means drained puzzles go unrecorded, so it is alerted.
#
# A puzzle still uncommitted here is one a lockout cut off and the run never got
# back to. Keeping it was worth a retry; publishing it is not — the republish
# below stages the whole tree, and it would go out as a puzzle whose teaching
# ladder stops halfway down. The next run's queue picks it up whole.
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
# them; nothing else rebuilds them on every run (daily_update.sh does only when
# its rebase conflicts on a generated file), so without this line the counts
# stall at whatever the last rebuild saw. They are worth
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
if [ "$seo_ok" = 1 ] && command -v node >/dev/null 2>&1; then
  smoke_log="$(mktemp "${TMPDIR:-/tmp}/cryptic-prereset-smoke.XXXXXX")"
  node tools/smoke_test.js 2>&1 | tee "$smoke_log"
  smoke_rc=${PIPESTATUS[0]}
  # A WARNING in a log is not a warning to anyone, so a failure is alerted.
  # Exit 2 is "no hints yet".
  if [ "$smoke_rc" -ne 0 ] && [ "$smoke_rc" -ne 2 ]; then
    alert "the app's smoke test is failing on the tree the pre-reset backfill is about to commit: $(grep -m3 '^FAIL' "$smoke_log" | tr '\n' ' ')"
  fi
  rm -f "$smoke_log"
fi
# The annotation payloads apply_annotations.py consumed, swept for the same
# reason daily_update.sh sweeps them: ignored is not the same as cleaned up.
rm -f "$REPO/tools/_ann_"*.json "$REPO/tools/_puzzle_"*.json "$REPO/tools/_scan_"*.png

if [ -n "$(git status --porcelain)" ]; then
  # Everything, for the reason daily_update.sh gives at its own `add -A`: this
  # is a worktree of the job's own, and a named list is both incomplete and
  # fatal — git add aborts on a path that matches nothing, staging none of it.
  git add -A
  git commit -q -m "$(printf 'Republish after pre-reset backfill\n\n%s' "$(python3 tools/provenance.py trailer)")"
  left=$(git status --porcelain | cut -c4- | tr '\n' ' ')
  [ -n "$left" ] && alert "the pre-reset backfill committed, and left these behind in its own worktree: $left"
  push_race_retry sync_attempt ||
    alert "pre-reset backfill could not push its republish commit — the built pages are committed locally only. See .prereset.log."
fi

# Where the rollout got to. Nothing to flip by hand: the ratchet in
# tools/validate_annotations.py requires these fields of every puzzle
# annotated since they were added, and the numbers below are only the historical
# remainder.
python3 tools/validate_annotations.py 2>&1 | grep -i "backlog" || true

echo "=== done $(date '+%H:%M') ==="
