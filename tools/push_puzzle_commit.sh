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
# fresh fetch. Anything else, a conflict included, exits non-zero with git's
# own words on stderr.
set -uo pipefail

commit=$(git rev-parse --verify -q "${1:-HEAD}^{commit}") || {
  echo "push_puzzle_commit: no such commit: ${1:-HEAD}" >&2; exit 2; }
parent=$(git rev-parse --verify -q "$commit^") || {
  echo "push_puzzle_commit: $commit has no parent to diff against" >&2; exit 2; }

for attempt in 1 2 3 4 5 6; do
  if ! out=$(git fetch -q origin master 2>&1); then
    printf '%s\n' "$out" >&2
    printf '%s' "$out" | grep -q "cannot lock ref" || exit 1
    sleep "$attempt"; continue
  fi
  base=$(git rev-parse origin/master)
  if ! tree=$(git merge-tree --write-tree --merge-base "$parent" "$base" "$commit"); then
    echo "push_puzzle_commit: $(git log -1 --format=%s "$commit") conflicts with origin/master:" >&2
    printf '%s\n' "$tree" | tail -n +2 >&2
    exit 1
  fi
  if [ "$tree" = "$(git rev-parse "$base^{tree}")" ]; then
    echo "push_puzzle_commit: origin/master already has $(git log -1 --format=%s "$commit")" >&2
    exit 0
  fi
  sha=$(git log -1 --format=%B "$commit" |
    GIT_AUTHOR_NAME=$(git log -1 --format=%an "$commit") \
    GIT_AUTHOR_EMAIL=$(git log -1 --format=%ae "$commit") \
    GIT_AUTHOR_DATE=$(git log -1 --format=%aD "$commit") \
    git commit-tree "$tree" -p "$base") || exit 1
  out=$(git push -q origin "$sha:refs/heads/master" 2>&1) && exit 0
  printf '%s\n' "$out" >&2
  printf '%s' "$out" | grep -qE "rejected|fetch first|non-fast-forward|cannot lock ref" || exit 1
  echo "push_puzzle_commit: origin/master moved under us (attempt $attempt), rebuilding" >&2
  sleep "$attempt"
done
exit 1
