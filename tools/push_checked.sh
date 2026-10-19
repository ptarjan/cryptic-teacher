#!/bin/bash
# Push local commits to origin/master, each first checked by tools/clobber_guard.py.
#
#     tools/push_checked.sh            # commits in origin/master..HEAD
#
# For code and docs a session commits itself and pushes as is (puzzle commits go
# through tools/push_puzzle_commit.sh, which runs the same guard). Refuses, with
# the guard's exit 4, a stack holding a commit made from a stale tree. A stack that edits
# the validator's rules also gets a requeue commit, made after the push by a detached job
# (requeue_job below), so the deploy stays green without the push waiting on a corpus survey.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

# requeue_job: survey the corpus at origin/master, in a throwaway worktree, and push what a rule edit
# newly flags (tools/requeue_drift.py --write) as a commit of its own, as daily_update.sh does after a
# lexicon rebuild. One at a time: a push that finds one running leaves a marker and the running job
# goes round again, so the last rule edit is always surveyed.
requeue_job() {
  common=$(cd "$here" && git rev-parse --path-format=absolute --git-common-dir) || return 1
  exec 9>"$common/requeue_drift.lock"
  if ! flock -n 9; then : > "$common/requeue_drift.again"; echo "requeue job already running; it will go round again"; return 0; fi
  while :; do
    rm -f "$common/requeue_drift.again"
    git fetch -q origin master || return 1
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/requeue.XXXXXX") || return 1
    git worktree add -q --detach "$tmp" origin/master || { rmdir "$tmp"; return 1; }
    (
      cd "$tmp" || exit 1
      python3 tools/requeue_drift.py --write || exit 1
      git diff --quiet -- tools/data/shape_reannotate.json tools/annotation_backlog.json && exit 0
      git add tools/data/shape_reannotate.json tools/annotation_backlog.json &&
        git commit -q -m "Requeue puzzles newly flagged by a validator rule change

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" || exit 1
      PUSH_CHECKED_NO_REQUEUE=1 tools/push_checked.sh || exit 2   # beaten: survey the new tip
    )
    rc=$?
    git worktree remove --force "$tmp" 2>/dev/null
    echo "push_checked: requeue job finished (exit $rc)"
    [ $rc -eq 2 ] && : > "$common/requeue_drift.again"
    [ -e "$common/requeue_drift.again" ] || break
  done
}
if [ "${1:-}" = "--requeue-job" ]; then requeue_job; exit $?; fi

git fetch -q origin master || exit 1
for c in $(git rev-list --reverse origin/master..HEAD); do
  python3 "$here/clobber_guard.py" "$c" || exit $?
done
# A rule edit must never turn the deploy red: when the stack changes the validator's code or a data
# file it reads (validate_scope.py says the deploy would re-check every puzzle for that), the
# puzzles the edit newly flags are requeued by a detached, low-priority job once the push lands.
# The job's own push sets PUSH_CHECKED_NO_REQUEUE so it does not start another.
scope=
if [ -z "${PUSH_CHECKED_NO_REQUEUE:-}" ]; then
  scope=$(python3 "$here/validate_scope.py" origin/master 2>/dev/null | head -n 1)
fi
git push -q origin HEAD:master || exit $?
case "$scope" in
  "full the check's code changed"*|"full "*"a file the check reads"*)
    common=$(git rev-parse --path-format=absolute --git-common-dir)
    echo "push_checked: $scope; requeue of newly flagged puzzles running detached (log $common/requeue_drift.log)"
    setsid nohup "$here/push_checked.sh" --requeue-job >> "$common/requeue_drift.log" 2>&1 < /dev/null &
    [ -x /app/tools/deprioritize.sh ] && /app/tools/deprioritize.sh -q 19 $! || true ;;
esac
exit 0
