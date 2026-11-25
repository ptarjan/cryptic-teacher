#!/bin/bash
# Ship local work to origin/master: optional commit, fetch, push, rebase-retry.
#
#     tools/push_checked.sh [-m "<message>"] [--wait]
#
#     tools/push_checked.sh                 # push commits in origin/master..HEAD
#     tools/push_checked.sh -m "msg"        # commit what is staged first, then push
#     tools/push_checked.sh --wait          # then block on tools/ci_wait.sh (or CI_WAIT=1)
#
# -m commits only the staged changes (nothing is staged for you). With nothing staged
# and nothing unpushed it says so and fails. The push is `git push origin HEAD:master`;
# nothing is checked first. On a non-fast-forward reject it fetches, runs
# `git rebase FETCH_HEAD` and retries, up to PUSH_TRIES (default 3) pushes, pausing
# 1..PUSH_BACKOFF_MAX seconds (default 5) before each retry so jobs that lost the
# same race do not collide again; a rebase conflict is aborted cleanly and reported.
# The scheduled workflows that commit fetched data call this with PUSH_TRIES=8 and
# nothing else: this script is the only place the rebase/retry policy lives. Run
# under GitHub Actions it also writes the failure as an ::error:: annotation.
#
# The last stdout line is always exactly `PUSHED <short-sha>` (exit 0) or
# `FAILED <reason>` (non-zero exit).
#
# Puzzle commits go through tools/push_puzzle_commit.sh instead.
#
# A rule edit that newly flags committed puzzles is not requeued here: the deploy's full
# check (pages.yml, "Requeue what the rules newly flag") raises their allowances and
# queues the clues as a commit of its own (tools/requeue_drift.py --publish). By hand:
# python3 tools/requeue_drift.py --write.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

fail() { # fail <code> <reason>
  [ -z "${GITHUB_ACTIONS:-}" ] || echo "::error::push_checked: $2" >&2
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

if [ -z "$(git rev-list origin/master..HEAD)" ]; then
  echo "nothing to push" >&2
else
  git log --format='%h %s' origin/master..HEAD >&2
fi

tries="${PUSH_TRIES:-3}"
n=0
while :; do
  n=$((n + 1))
  if git push -q origin HEAD:master >&2; then
    break
  fi
  [ "$n" -lt "$tries" ] || fail 1 "push rejected after $n tries"
  echo "push $n of $tries rejected; rebasing onto the new tip" >&2
  sleep $((RANDOM % ${PUSH_BACKOFF_MAX:-5} + 1))
  # fetch + rebase FETCH_HEAD, not pull: pull --rebase fails in a detached lease tree
  # ("no candidate for rebasing").
  git fetch -q origin master >&2 || { echo "fetch failed; trying again" >&2; continue; }
  if ! git rebase -q FETCH_HEAD >&2; then
    git rebase --abort >&2 2>/dev/null
    fail 3 "rebase conflict, aborted"
  fi
done

# Opt-in only, so burn and other automated callers never block: --wait or CI_WAIT=1.
if [ "$wait_ci" = 1 ]; then
  "$here/ci_wait.sh" "$(git rev-parse HEAD)" >&2 || fail $? "ci_wait failed"
fi
echo "PUSHED $(git rev-parse --short HEAD)"
