#!/bin/bash
# Ship local work to origin/master: optional commit, guard, push, rebase-retry.
#
#     tools/push_checked.sh [-m "<message>"] [--wait]
#
#     tools/push_checked.sh                 # push commits in origin/master..HEAD
#     tools/push_checked.sh -m "msg"        # commit what is staged first, then push
#     tools/push_checked.sh --wait          # then block on tools/ci_wait.sh (or CI_WAIT=1)
#
# -m commits only the staged changes (nothing is staged for you). With nothing staged
# and nothing unpushed it says so and fails. Each commit in origin/master..HEAD is
# first checked by tools/clobber_guard.py (exit 4 refuses a stack holding a commit
# made from a stale tree). On a non-fast-forward reject it runs
# `git pull --rebase origin master`, re-runs the guard and retries the push, up to
# PUSH_TRIES (default 3) pushes; a rebase conflict is aborted cleanly and reported.
#
# The last stdout line is always exactly `PUSHED <short-sha>` (exit 0) or
# `FAILED <reason>` (non-zero exit; the guard's own code when it refused).
#
# For code and docs a session commits itself (puzzle commits go through
# tools/push_puzzle_commit.sh, which runs the same guard).
#
# A rule edit that newly flags committed puzzles is not requeued here: the deploy's full
# check (pages.yml, "Requeue what the rules newly flag") raises their allowances and
# queues the clues as a commit of its own (tools/requeue_drift.py --publish). By hand:
# python3 tools/requeue_drift.py --write.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

fail() { # fail <code> <reason>
  echo "FAILED $2"
  exit "$1"
}

msg=""
have_msg=0
wait_ci=0
[ "${CI_WAIT:-}" = "1" ] && wait_ci=1
while [ $# -gt 0 ]; do
  case "$1" in
    -m) [ $# -ge 2 ] || fail 2 "-m needs a message"; msg="$2"; have_msg=1; shift 2 ;;
    --wait) wait_ci=1; shift ;;
    *) fail 2 "unknown argument: $1" ;;
  esac
done

git fetch -q origin master >&2 || fail 1 "git fetch failed"

if [ "$have_msg" = 1 ]; then
  if git diff --cached --quiet; then
    if [ -z "$(git rev-list origin/master..HEAD)" ]; then
      fail 1 "nothing staged and nothing unpushed"
    fi
    echo "nothing staged; pushing the unpushed commits" >&2
  else
    git commit -q -m "$msg" >&2 || fail 1 "git commit failed"
  fi
fi

check() {
  local c
  for c in $(git rev-list --reverse origin/master..HEAD); do
    python3 "$here/clobber_guard.py" "$c" >&2 || return $?
  done
  # A Python file that no longer parses stops every job that reloads onto
  # master (11-17: a misplaced colon in edition_queue.py killed the Guardian
  # re-file), so refuse it here rather than wait for CI.
  local f
  for f in $(git diff --name-only --diff-filter=AM origin/master..HEAD -- '*.py'); do
    git show "HEAD:$f" | python3 -c 'import ast, sys; ast.parse(sys.stdin.read(), sys.argv[1])' "$f" >&2 \
      || { echo "$f does not parse" >&2; return 4; }
  done
  # Duplicate assignments, conflict markers, unregistered reasons, new ruff findings and moved
  # keys (tools/prepush_check.py); the key snapshot is tools/data/keys.json (--write-keys).
  python3 "$here/prepush_check.py" >&2 || { echo "tools/prepush_check.py refused the push" >&2; return 5; }
  return 0
}

tries="${PUSH_TRIES:-3}"
n=0
while :; do
  check
  rc=$?
  [ "$rc" -eq 0 ] || fail "$rc" "pre-push check refused (exit $rc)"
  n=$((n + 1))
  if git push -q origin HEAD:master >&2; then
    break
  fi
  [ "$n" -lt "$tries" ] || fail 1 "push rejected after $n tries"
  echo "push rejected; rebasing onto origin/master (try $n of $tries)" >&2
  # fetch + rebase FETCH_HEAD, not pull: pull --rebase fails in a detached lease tree
  # ("no candidate for rebasing").
  if ! { git fetch -q origin master >&2 && git rebase -q FETCH_HEAD >&2; }; then
    git rebase --abort >&2 2>/dev/null
    fail 3 "rebase conflict, aborted"
  fi
done

# Opt-in only, so burn and other automated callers never block: --wait or CI_WAIT=1.
if [ "$wait_ci" = 1 ]; then
  "$here/ci_wait.sh" "$(git rev-parse HEAD)" >&2 || fail $? "ci_wait failed"
fi
echo "PUSHED $(git rev-parse --short HEAD)"
