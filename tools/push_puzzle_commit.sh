#!/bin/bash
# Publish one local commit to origin/master without touching the working tree.
#
#     tools/push_puzzle_commit.sh [<commit>]     # default HEAD
#
# The commit's own change (its diff from its first parent) is replayed onto
# origin/master in memory with `git merge-tree`, committed there with the
# original message and author, and pushed. No stash, no rebase, no checkout, so
# annotators still writing into this tree can never make it fail, and nothing
# they have in flight is ever picked up or set aside. The local commit stays
# where it is; the next `git rebase origin/master`, run when the tree is quiet,
# drops it as patch-identical to the one pushed here.
#
# A 3-way merge rather than copying this commit's blobs over origin/master, so
# an edit someone else pushed to the same file in the meantime is merged, or
# refused as a conflict, instead of silently reverted.
#
# A rejected push (origin moved) or a lost race on the shared
# refs/remotes/origin/master (a sibling worktree fetching) is retried against a
# fresh fetch. Only the first push runs the pre-push check: a retry pushes the
# same change onto a newer origin, and the check's seconds are the window
# another pusher wins in. A conflict exits CONFLICT (3), read off merge-tree's
# own status (1: conflicts), so a caller can set the commit aside and go on to
# the next (tools/durable.sh); anything else exits non-zero (1, 2) with git's
# own words on stderr. The one conflict settled instead of refused is a
# promotion racing a re-read of its clues-only file (modify/delete on
# clues_only/X.json): tools/resolve_promotion_conflict.py keeps the promoted
# puzzle, drops the clues-only copy, and carries the re-read's clue text in
# where the filed clue was never corrected.
set -uo pipefail
CONFLICT=3

# Pushers on this machine (burn, daily units, re-date batches) take turns from
# fetch to push: unserialised, a 100-commit batch starved a daily unit through
# all ten attempts (10-13). flock(2) via python, since macOS ships no flock(1);
# the lock rides on fd 9 and drops when this script exits.
exec 9>>"$(git rev-parse --git-common-dir)/push_puzzle_commit.lock"
python3 -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX)'

commit=$(git rev-parse --verify -q "${1:-HEAD}^{commit}") || {
  echo "push_puzzle_commit: no such commit: ${1:-HEAD}" >&2; exit 2; }
parent=$(git rev-parse --verify -q "$commit^") || {
  echo "push_puzzle_commit: $commit has no parent to diff against" >&2; exit 2; }

verify=()
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if ! out=$(git fetch -q origin master 2>&1); then
    printf '%s\n' "$out" >&2
    printf '%s' "$out" | grep "cannot lock ref" >/dev/null || exit 1
    sleep "$attempt"; continue
  fi
  base=$(git rev-parse origin/master)
  tree=$(git merge-tree --write-tree --merge-base "$parent" "$base" "$commit")
  case $? in
    0) ;;
    1) # A promotion racing a re-read of the same clues-only file (one side
       # deletes clues_only/X.json, the other re-writes it) is settled by
       # keeping the promoted puzzle; anything else is refused as before.
       mapfile -t paths < <(printf '%s\n' "$tree" | sed -n '2,/^$/p' | grep $'\t' | cut -f2 | sort -u)
       if settled=$(python3 "$(dirname "$0")/resolve_promotion_conflict.py" \
            "$parent" "$base" "$commit" "$(printf '%s\n' "$tree" | head -1)" "${paths[@]}"); then
         tree=$settled
       else
         echo "push_puzzle_commit: $(git log -1 --format=%s "$commit") conflicts with origin/master:" >&2
         printf '%s\n' "$tree" | tail -n +2 >&2
         exit "$CONFLICT"
       fi ;;
    *) exit 1 ;;
  esac
  if [ "$tree" = "$(git rev-parse "$base^{tree}")" ]; then
    echo "push_puzzle_commit: origin/master already has $(git log -1 --format=%s "$commit")" >&2
    exit 0
  fi
  # commit-tree ignores commit.gpgsign, so a republished commit signs only when asked.
  sign=()
  [ "$(git config --bool commit.gpgsign)" = true ] && sign=(-S)
  sha=$(git log -1 --format=%B "$commit" |
    GIT_AUTHOR_NAME=$(git log -1 --format=%an "$commit") \
    GIT_AUTHOR_EMAIL=$(git log -1 --format=%ae "$commit") \
    GIT_AUTHOR_DATE=$(git log -1 --format=%aD "$commit") \
    git commit-tree "${sign[@]}" "$tree" -p "$base") || exit 1
  out=$(git push -q "${verify[@]}" origin "$sha:refs/heads/master" 2>&1) && exit 0
  printf '%s\n' "$out" >&2
  printf '%s' "$out" | grep -E "rejected|fetch first|non-fast-forward|cannot lock ref" >/dev/null || exit 1
  echo "push_puzzle_commit: origin/master moved under us (attempt $attempt), rebuilding" >&2
  verify=(--no-verify)
  sleep "$((RANDOM % 3 + 1))"
done
exit 1
