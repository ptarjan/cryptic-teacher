#!/bin/bash
# Sourced by a long job that files work into git, so a drop loses minutes,
# not the run.
#
#     . tools/nightly_worktree.sh          # first: the job's own tree
#     DURABLE_PATHS=(puzzles/times ...)    # what the job files (pathspecs)
#     . tools/durable.sh
#     durable_run "<what>" <command...>    # run it; commit every DURABLE_EVERY s
#     durable_checkpoint "<what>"          # commit and push what is filed now
#
# Three mechanisms, one per way a job ends early:
#
#   * While the command runs, every DURABLE_EVERY seconds (default 300) what
#     it has filed under DURABLE_PATHS is committed and pushed with
#     tools/push_puzzle_commit.sh, which replays the commit onto origin/master
#     without touching the working tree the command is still writing into.
#     A commit whose push fails stays local and goes with the next checkpoint.
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
_durable_child=""
_durable_what=""
_durable_pushed=""

durable_checkpoint() {  # durable_checkpoint <what>: commit what is filed, push every unpushed commit
  local what="$1" c p paths=()
  # git add refuses a pathspec that matches nothing: a folder made only once
  # something is filed into it is left out until it exists.
  for p in "${DURABLE_PATHS[@]}"; do
    [ -e "$p" ] && paths+=("$p")
  done
  if [ "${#paths[@]}" -gt 0 ]; then
    git add -- "${paths[@]}" || return 1
  fi
  ct_unstage_unparsable .
  if ! git diff --cached --quiet; then
    git commit -q -m "$(printf '%s\n\n%s' "$what" "$(python3 "$_durable_dir/provenance.py" trailer 2>/dev/null)")" ||
      return 1
  fi
  # Oldest first, from the last one pushed (or origin/master): a commit whose
  # push failed is tried again here, before the ones made after it.
  for c in $(git rev-list --reverse "${_durable_pushed:-origin/master}..HEAD" 2>/dev/null); do
    if bash "$_durable_dir/push_puzzle_commit.sh" "$c"; then
      _durable_pushed="$c"
    else
      echo "durable: push of $(git log -1 --format=%s "$c") failed; it stays committed here and is retried at the next checkpoint"
      return 1
    fi
  done
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
      durable_checkpoint "$what" || echo "durable: checkpoint failed for $what"
      last=$SECONDS
    fi
  done
  wait "$_durable_child"
  rc=$?
  [ -n "$tailer" ] && wait "$tailer"
  _durable_child=""
  durable_checkpoint "$what" || echo "durable: checkpoint failed for $what"
  return "$rc"
}

durable_resync() {  # move the tree to origin/master once the job is quiet; nothing is lost if it cannot
  git fetch -q origin master 2>/dev/null
  git rebase -q origin/master 2>/dev/null || { git rebase --abort 2>/dev/null; echo "durable: tree left where it is (rebase failed); its commits are pushed"; }
  _durable_pushed=""
}
