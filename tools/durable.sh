#!/bin/bash
# Sourced by a long job that files work into git, so a drop loses minutes,
# not the run.
#
#     . tools/nightly_worktree.sh          # first: the job's own tree
#     DURABLE_PATHS=(puzzles/times ...)    # what the job files (pathspecs)
#     . tools/durable.sh
#     durable_run "<what>" <command...>    # run it; commit every DURABLE_EVERY s
#     durable_checkpoint "<what>"          # commit and push what is filed now
#     DURABLE_RESYNC=1                     # and move the tree to origin/master after each
#     DURABLE_END=later durable_run ...    # no checkpoint as it ends: the caller's
#     durable_background <function...>     # publish runs beside the next command;
#                                          # every checkpoint, move and stop waits for it
#
# Three mechanisms, one per way a job ends early:
#
#   * While the command runs, every DURABLE_EVERY seconds (default 300) what
#     it has filed under DURABLE_PATHS is committed and pushed with
#     tools/push_puzzle_commit.sh, which replays the commit onto origin/master
#     without touching the working tree the command is still writing into.
#     A commit whose push fails stays local and goes with the next checkpoint;
#     DURABLE_ALERT_AFTER (default 6) failed checkpoints in a row alert the room.
#     One that conflicts (push_puzzle_commit.sh's CONFLICT: another job filed
#     the same puzzle meanwhile) never will, so it is set aside and the ones
#     after it still go: origin's version stands, and each puzzle it filed
#     asks for its source to be read again (scan_queue.py conflicted), which
#     files over origin's; a commit nothing re-reads is kept under
#     refs/durable/conflicts/ and the room is told.
#   * SIGTERM, SIGINT or SIGHUP (tools/corpus_queue.py stop, a container
#     stop) TERMs the command, waits up to DURABLE_STOP_GRACE seconds (default
#     60) for it to end, KILLs it if not, checkpoints, and exits 143.
#   * SIGKILL, an OOM or a reboot runs no trap: the job's worktree keeps what
#     was filed, and tools/nightly_worktree.sh commits and pushes it (and any
#     local commit a failed push left) before its reset, when the job's script
#     sets CT_SALVAGE_PATHS before sourcing it.
#
# tools/test_durable.sh kills a fake job each of these ways and checks that
# what it filed reaches origin; it also fails when a scheduled entry point
# neither sources this file nor is listed there as short.

DURABLE_EVERY="${DURABLE_EVERY:-300}"
DURABLE_STOP_GRACE="${DURABLE_STOP_GRACE:-60}"
_durable_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_durable_dir/unstage_unparsable.sh"
. "$_durable_dir/commit_puzzles.sh"
_durable_child=""
_durable_what=""
_durable_pushed=""
_durable_bg=""
_durable_bg_state=""

durable_checkpoint() {  # durable_checkpoint <what>: commit what is filed, push every unpushed commit
  local what="$1" c p paths=()
  durable_wait
  # git add refuses a pathspec that matches nothing: a folder made only once
  # something is filed into it is left out until it exists.
  for p in "${DURABLE_PATHS[@]}"; do
    [ -e "$p" ] && paths+=("$p")
  done
  if [ "${#paths[@]}" -gt 0 ]; then
    git add -- "${paths[@]}" || return 1
  fi
  ct_unstage_unparsable .
  ct_unstage_refused .
  if ! git diff --cached --quiet; then
    # One commit per puzzle or clues-only file (a rename's two paths
    # together), then one for whatever else is staged (ledgers, series files).
    ct_commit_puzzles "$what" || return 1
    if ! git diff --cached --quiet; then
      git commit -q -m "$(printf '%s\n\n%s' "$what" "$(python3 "$_durable_dir/provenance.py" trailer 2>/dev/null)")" || return 1
    fi
  fi
  # Oldest first, from the last one settled (pushed or set aside; else
  # origin/master): a commit whose push failed is tried again here, before
  # the ones made after it.
  local rc
  for c in $(git rev-list --reverse "${_durable_pushed:-origin/master}..HEAD" 2>/dev/null); do
    bash "$_durable_dir/push_puzzle_commit.sh" "$c"
    rc=$?
    if [ "$rc" = 3 ]; then
      durable_set_aside "$c"
    elif [ "$rc" != 0 ]; then
      echo "durable: push of $(git log -1 --format=%s "$c") failed; it stays committed here and is retried at the next checkpoint"
      durable_push_failed "$c"
      return 1
    fi
    _durable_pushed="$c"
  done
  rm -f "$(git rev-parse --git-path durable-push-failures)"
}

# A push that fails the same way every time (the pre-push refusing a shape
# the job's old code still writes: 10-13, 5 hours and 777 commits) leaves
# every checkpoint failing, and a failed checkpoint never resyncs, so the job
# never reaches the code that would fix it. The streak is counted in the git
# dir (a durable_background publish runs in a subshell) and the room is told
# once it reaches DURABLE_ALERT_AFTER checkpoints in a row; a checkpoint that
# pushes everything ends the streak.
DURABLE_ALERT_AFTER="${DURABLE_ALERT_AFTER:-6}"
durable_push_failed() {  # durable_push_failed <commit>: count the failed checkpoint, alert at the threshold
  local f n
  f="$(git rev-parse --git-path durable-push-failures)"
  n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 ))
  echo "$n" >"$f"
  [ "$n" = "$DURABLE_ALERT_AFTER" ] || return 0
  . "$_durable_dir/alert.sh" 2>/dev/null &&
    alert "durable: ${_durable_what:-a job} in $PWD has failed $n checkpoints in a row: \"$(git log -1 --format=%s "$1")\" will not push, so $(git rev-list --count "${_durable_pushed:-origin/master}..HEAD" 2>/dev/null) commit(s) wait unpushed and the tree cannot move to origin/master's code. Push them by hand (tools/push_puzzle_commit.sh) or fix what the pre-push refuses."
}

durable_set_aside() {  # durable_set_aside <commit>: a commit that conflicts with origin/master
  local c="$1" subj out
  subj="$(git log -1 --format=%s "$c")"
  if out="$(python3 "$_durable_dir/scan_queue.py" conflicted "$c" 2>&1)"; then
    echo "durable: $subj conflicts with origin/master; origin's version stands and the source is read again:"
  else
    git update-ref "refs/durable/conflicts/$c" "$c"
    echo "durable: $subj conflicts with origin/master and not all of it is read again; kept as refs/durable/conflicts/$c:"
    . "$_durable_dir/alert.sh" 2>/dev/null &&
      alert "durable: \"$subj\" conflicts with origin/master and is not all re-readable, so origin's version stands and the commit is kept as refs/durable/conflicts/$c; merge it from a worktree. $out"
  fi
  printf '%s\n' "$out"
}

# A publish (commit, push, move) run beside the next command, so a job
# that works in slices (tools/ocr_full_pass.sh) starts its next one at once
# instead of leaving its workers idle for the minutes a pre-push takes. It
# shares the tree with the command, as durable_run's own checkpoints do; one
# at a time: every checkpoint, move and stop waits for it first, and takes
# on what it pushed. It ignores TERM, so a stop lets it finish, then commits.
durable_background() {  # durable_background <command...>: run it in the background (a shell function: durable_checkpoint, ...)
  durable_wait
  _durable_bg_state="$(mktemp)"
  (
    trap '' TERM INT HUP
    "$@"
    rc=$?
    printf 'pushed=%s\n' "$_durable_pushed" >"$_durable_bg_state"
    exit "$rc"
  ) &
  _durable_bg=$!
}

durable_wait() {  # wait for durable_background's publish; its status (0 when none runs)
  local rc=0 line
  [ -n "$_durable_bg" ] || return 0
  # A trap (a stop) can end the wait early: wait again until it has ended.
  while :; do
    wait "$_durable_bg"
    rc=$?
    kill -0 "$_durable_bg" 2>/dev/null || break
  done
  line="$(cat "$_durable_bg_state" 2>/dev/null)"
  # The last commit it settled, "" once it moved the tree: the next
  # checkpoint pushes from there, not again from before the move.
  [ "${line#pushed=}" != "$line" ] && _durable_pushed="${line#pushed=}"
  rm -f "$_durable_bg_state"
  _durable_bg=""
  _durable_bg_state=""
  return "$rc"
}

_durable_stop() {
  trap '' TERM INT HUP
  echo "=== ${_durable_what:-job}: stop asked at $(date '+%F %T'); committing what it filed ==="
  if [ -n "$_durable_child" ] && kill -0 "$_durable_child" 2>/dev/null; then
    kill -TERM "$_durable_child" 2>/dev/null
    local waited=0
    while kill -0 "$_durable_child" 2>/dev/null && [ "$waited" -lt "$DURABLE_STOP_GRACE" ]; do
      sleep 1
      waited=$((waited + 1))
    done
    kill -KILL "$_durable_child" 2>/dev/null
  fi
  durable_checkpoint "${_durable_what:-job} (stopped)" || echo "durable: the stop's checkpoint failed; the next start salvages the tree"
  exit 143
}
trap _durable_stop TERM INT HUP

durable_run() {  # durable_run <what> <command...>: its exit status; DURABLE_TEE=<file> also copies its output there
  local what="$1" last rc tailer=""
  shift
  _durable_what="$what"
  if [ -n "${DURABLE_TEE:-}" ]; then
    "$@" >"$DURABLE_TEE" 2>&1 &
    _durable_child=$!
    tail -n +1 -f --pid="$_durable_child" "$DURABLE_TEE" &
    tailer=$!
  else
    "$@" &
    _durable_child=$!
  fi
  last=$SECONDS
  while kill -0 "$_durable_child" 2>/dev/null; do
    sleep 2 &
    wait $!
    if [ $((SECONDS - last)) -ge "$DURABLE_EVERY" ]; then
      if durable_checkpoint "$what"; then
        # A job that starts its work as fresh processes (tools/edition_queue.py)
        # runs master's code from the next one on, without a restart.
        [ -n "${DURABLE_RESYNC:-}" ] && durable_resync
      else
        echo "durable: checkpoint failed for $what"
      fi
      last=$SECONDS
    fi
  done
  wait "$_durable_child"
  rc=$?
  [ -n "$tailer" ] && wait "$tailer"
  _durable_child=""
  # DURABLE_END=later: the caller publishes (durable_background).
  [ "${DURABLE_END:-}" = later ] || durable_checkpoint "$what" || echo "durable: checkpoint failed for $what"
  return "$rc"
}

durable_resync() {  # move the tree to origin/master; nothing is lost if it cannot (status 1)
  local lock move pending
  durable_wait
  git fetch -q origin master 2>/dev/null
  # A process starting off this tree (tools/edition_queue.py) loads its code
  # under a shared lock on code.lock; the move takes it alone, so none loads
  # half of each version.
  lock="$(git rev-parse --path-format=absolute --git-path code.lock)"
  # Every commit settled (pushed, or set aside for a re-read): origin/master
  # holds what stands, so the tree moves straight there (reset --keep, which
  # refuses a file the job has changed). A rebase would replay a set-aside
  # commit onto origin's version and stop on the same conflict.
  move='git rebase -q origin/master 2>/dev/null || { git rebase --abort 2>/dev/null; exit 1; }'
  pending="$(git rev-list "${_durable_pushed:-origin/master}..HEAD")" && [ -z "$pending" ] &&
    move='git reset -q --keep origin/master 2>/dev/null'
  if ! flock -w 60 "$lock" sh -c "$move"; then
    echo "durable: tree left where it is (rebase failed, or code.lock busy 60s); its commits are pushed"
    return 1
  fi
  _durable_pushed=""
}
