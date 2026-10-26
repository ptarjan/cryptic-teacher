#!/bin/bash
# Publish one local commit to origin/master without touching the working tree.
#
#     tools/push_puzzle_commit.sh [<commit>]     # default HEAD
#     PUSH_NOW=1 tools/push_puzzle_commit.sh     # skip the batch window, push now
#     tools/push_puzzle_commit.sh --flush        # push the waiting batch once its window opens
#     tools/push_puzzle_commit.sh --sync-target  # what a tree should reset onto: the batch or origin/master
#
# The commit's own change (its diff from its first parent) is replayed onto
# origin/master in memory with `git merge-tree`, committed there with the
# original message and author, and pushed. No stash, no rebase, no checkout, so
# annotators still writing into this tree can never make it fail, and nothing
# they have in flight is ever picked up or set aside. The local commit stays
# where it is; the next `git rebase origin/master`, run when the tree is quiet,
# drops it as patch-identical to the one pushed here.
#
# Batching: every push starts 9 CI jobs, and the burn pushing each puzzle alone
# (244 pushes an hour, 10-21) backed Actions up four hours. So pushes from this
# machine go out at most once per PUSH_BATCH_SECS (300). A commit that comes
# inside the window is replayed onto the batch, refs/push-batch/tip in the
# shared git dir (a chain of replayed commits on top of origin/master), instead
# of onto origin, and this exits 0 at once: the work is safe in the shared ref
# even if the caller then resets its tree. A detached flusher (--flush, one at
# a time) pushes the whole batch in one push when the window opens, so the
# last commit of a run is never stranded. If origin moved under the batch (a
# push from elsewhere), the flusher replays each batched commit onto it; one
# that no longer replays is kept as refs/push-batch/conflicts/<commit> and
# alerted. Conflicts with the batch itself are found at once, as with origin.
#
# A 3-way merge rather than copying this commit's blobs over origin/master, so
# an edit someone else pushed to the same file in the meantime is merged, or
# refused as a conflict, instead of silently reverted.
#
# A rejected push (origin moved) or a lost race on the shared
# refs/remotes/origin/master (a sibling worktree fetching) is retried against a
# fresh fetch. A conflict exits CONFLICT (3), read off merge-tree's
# own status (1: conflicts), so a caller can set the commit aside and go on to
# the next (tools/durable.sh). Anything else exits
# non-zero (1, 2) with git's own words on stderr. The one conflict settled instead of refused is a
# promotion racing a re-read of its clues-only file (modify/delete on
# clues_only/X.json): tools/resolve_promotion_conflict.py keeps the promoted
# puzzle, drops the clues-only copy, and carries the re-read's clue text in
# where the filed clue was never corrected.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/yield_cpu.sh"
CONFLICT=3
here="$(cd "$(dirname "$0")" && pwd)"
common=$(git rev-parse --path-format=absolute --git-common-dir) || exit 1
BATCH_REF=refs/push-batch/tip
BATCH_SECS=${PUSH_BATCH_SECS:-300}
stamp="$common/push_batch.last"

# Pushers on this machine (burn, daily units, re-date batches) take turns from
# fetch to push: unserialised, a 100-commit batch starved a daily unit through
# all ten attempts (10-13). flock(2) via python, since macOS ships no flock(1);
# the lock rides on fd 9 and drops when this script exits.
take_lock() {
  exec 9>>"$common/push_puzzle_commit.lock"
  python3 -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX)'
}

# window_left: seconds until the next push may go (<= 0: now).
window_left() {
  [ -n "${PUSH_NOW:-}" ] && { echo 0; return; }
  echo $(( $(cat "$stamp" 2>/dev/null || echo 0) + BATCH_SECS - $(date +%s) ))
}

# make_commit <tree> <parent> <commit>: <commit>'s message and author on <tree>.
# commit-tree ignores commit.gpgsign, so a republished commit signs only when asked.
make_commit() {
  local sign=()
  [ "$(git config --bool commit.gpgsign)" = true ] && sign=(-S)
  git log -1 --format=%B "$3" |
    GIT_AUTHOR_NAME=$(git log -1 --format=%an "$3") \
    GIT_AUTHOR_EMAIL=$(git log -1 --format=%ae "$3") \
    GIT_AUTHOR_DATE=$(git log -1 --format=%aD "$3") \
    git commit-tree "${sign[@]}" "$1" -p "$2"
}

# onto_for <base>: what to build on, the batch when one waits, else <base>
# (origin/master). A batch origin moved under is replayed onto <base> first.
onto_for() {
  local base="$1" tip c t prev
  tip=$(git rev-parse -q --verify "$BATCH_REF") || { echo "$base"; return 0; }
  if git merge-base --is-ancestor "$base" "$tip"; then echo "$tip"; return 0; fi
  prev=$base
  for c in $(git rev-list --reverse "$(git merge-base "$base" "$tip")..$tip"); do
    if t=$(git merge-tree --write-tree --merge-base "$c^" "$prev" "$c" 2>/dev/null); then
      [ "$t" = "$(git rev-parse "$prev^{tree}")" ] && continue
      prev=$(make_commit "$t" "$prev" "$c") || return 1
    else
      git update-ref "refs/push-batch/conflicts/$c" "$c"
      echo "push_puzzle_commit: batched $(git log -1 --format=%s "$c") no longer replays onto origin/master; kept as refs/push-batch/conflicts/$c" >&2
      ( . "$here/alert.sh" && alert "push_puzzle_commit: batched commit \"$(git log -1 --format=%s "$c")\" conflicts with a push made meanwhile and was not published; kept as refs/push-batch/conflicts/$c. Replay it by hand: tools/push_puzzle_commit.sh $c" ) 2>/dev/null || true
    fi
  done
  echo "$prev"
}

# schedule_flush: start the detached flusher (a no-op when one is waiting).
schedule_flush() {
  [ "${PUSH_BATCH_FLUSHER:-1}" = 0 ] && return 0
  local run=(nohup)
  command -v setsid >/dev/null && run=(setsid nohup)
  # Nothing between here and the flusher may keep fd 9 (the push lock) open,
  # or the flusher waits on it forever.
  ( exec 9>&- 8>&-
    cd "$common" || exit 1
    "${run[@]}" bash "$here/push_puzzle_commit.sh" --flush >>"$common/push_batch.log" 2>&1 </dev/null & )
}

# publish <sha> <base>: push <sha> if the window is open, else hold it as the
# batch. 0: pushed or held; 2: lost a race, fetch and rebuild; 1: failed.
publish() {
  local sha="$1" base="$2" out left
  if [ "$sha" = "$base" ]; then git update-ref -d "$BATCH_REF" 2>/dev/null; return 0; fi
  left=$(window_left)
  if [ "$left" -gt 0 ]; then
    git update-ref "$BATCH_REF" "$sha" || return 1
    echo "push_puzzle_commit: batched $(git rev-list --count "$base..$sha") commit(s); pushing in ${left}s" >&2
    schedule_flush
    return 0
  fi
  if out=$(net_git push -q --no-verify origin "$sha:refs/heads/master" 2>&1); then
    date +%s >"$stamp"
    git update-ref -d "$BATCH_REF" 2>/dev/null
    return 0
  fi
  printf '%s\n' "$out" >&2
  printf '%s' "$out" | grep -E "rejected|fetch first|non-fast-forward|cannot lock ref" >/dev/null || return 1
  echo "push_puzzle_commit: origin/master moved under us, rebuilding" >&2
  return 2
}

# net_git <args...>: git, cut off after CT_NET_TIMEOUT seconds (120): a stalled ssh to
# github.com (10-23) would hold the checkpoint, and the job's move to master, for good.
# Cut off is failed (124), and the commit goes with the next checkpoint.
net_git() {
  if command -v timeout >/dev/null 2>&1; then timeout "${CT_NET_TIMEOUT:-120}" git "$@"; else git "$@"; fi
}

# fetch_base: fetch origin/master into $base; 0 ok, 2 lost a ref race, 1 failed.
fetch_base() {
  local out
  if ! out=$(net_git fetch -q origin master 2>&1); then
    printf '%s\n' "$out" >&2
    printf '%s' "$out" | grep "cannot lock ref" >/dev/null && return 2
    return 1
  fi
  base=$(git rev-parse origin/master)
}

# flush_once: under the lock, push the batch (or hold it again if another
# push just went). 0 done, 1 failed.
flush_once() {
  local attempt rc onto
  take_lock
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    fetch_base; rc=$?
    [ $rc = 1 ] && break
    [ $rc = 2 ] && { sleep "$attempt"; continue; }
    onto=$(onto_for "$base") || break
    publish "$onto" "$base"; rc=$?
    [ $rc = 0 ] && { exec 9>&-; return 0; }
    [ $rc = 1 ] && break
    sleep "$((RANDOM % 3 + 1))"
  done
  exec 9>&-
  return 1
}

# The flusher: one at a time (fd 8). Sleeps until the window opens, pushes,
# and goes round while a batch waits. Re-checks after letting go of its lock,
# so a commit batched as it exits always finds a flusher.
flush() {
  local fails=0 left
  while :; do
    exec 8>>"$common/push_batch_flush.lock"
    python3 -c 'import fcntl; fcntl.flock(8, fcntl.LOCK_EX | fcntl.LOCK_NB)' 2>/dev/null || exit 0
    while git rev-parse -q --verify "$BATCH_REF" >/dev/null; do
      left=$(window_left)
      [ "$left" -gt 0 ] && { sleep "$left"; continue; }
      if flush_once; then fails=0; continue; fi
      fails=$((fails + 1))
      [ "$fails" = 10 ] && { ( . "$here/alert.sh" && alert "push_puzzle_commit --flush has failed 10 times in a row to push the batch at $BATCH_REF ($(git rev-list --count origin/master.."$BATCH_REF") commits wait); see $common/push_batch.log" ) || true; }
      sleep 60
    done
    exec 8>&-
    git rev-parse -q --verify "$BATCH_REF" >/dev/null || exit 0
  done
}

case "${1:-}" in
  --flush) flush; exit 0 ;;
  --sync-target)
    tip=$(git rev-parse -q --verify "$BATCH_REF") && git merge-base --is-ancestor origin/master "$tip" &&
      { echo "$tip"; exit 0; }
    git rev-parse origin/master; exit $? ;;
esac

take_lock

commit=$(git rev-parse --verify -q "${1:-HEAD}^{commit}") || {
  echo "push_puzzle_commit: no such commit: ${1:-HEAD}" >&2; exit 2; }
parent=$(git rev-parse --verify -q "$commit^") || {
  echo "push_puzzle_commit: $commit has no parent to diff against" >&2; exit 2; }

# A commit made from a stale tree is refused (exit 4), not replayed: see tools/clobber_guard.py.
python3 "$here/clobber_guard.py" "$commit" || exit $?

# partial_replay <conflicted tree> <onto> <path>...: <onto>'s tree with the
# clean merges of the conflicted tree and the conflicted paths left as <onto>
# has them. Only for a commit of two or more puzzle files whose conflicts are
# all puzzle files too; fails (nothing printed) otherwise.
partial_replay() {
  local ctree="$1" base="$2" p entry mode sha idx
  shift 2
  for p in "$@"; do
    case "$p" in puzzles/*.json) ;; *) return 1 ;; esac
  done
  [ "$(git diff-tree --no-commit-id --name-only -r "$parent" "$commit" -- 'puzzles/*.json' | wc -l)" -ge 2 ] || return 1
  idx="$(mktemp -d)/index"
  GIT_INDEX_FILE=$idx git read-tree "$ctree" || return 1
  for p in "$@"; do
    entry=$(git ls-tree "$base" -- "$p")
    if [ -n "$entry" ]; then
      read -r mode _ sha _ <<<"$entry"
      GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "$mode,$sha,$p" || return 1
    else
      GIT_INDEX_FILE=$idx git update-index --force-remove -- "$p" || return 1
    fi
  done
  GIT_INDEX_FILE=$idx git write-tree
}

final=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  final=0
  fetch_base; rc=$?
  [ $rc = 1 ] && exit 1
  [ $rc = 2 ] && { sleep "$attempt"; continue; }
  # The batch waiting to push, when there is one, else origin/master: the
  # commit replays onto that, so it conflicts now rather than at the flush.
  onto=$(onto_for "$base") || exit 1
  tree=$(git merge-tree --write-tree --merge-base "$parent" "$onto" "$commit")
  case $? in
    0) ;;
    1) # A promotion racing a re-read of the same clues-only file (one side
       # deletes clues_only/X.json, the other re-writes it) is settled by
       # keeping the promoted puzzle; anything else is refused as before.
       mapfile -t paths < <(printf '%s\n' "$tree" | sed -n '2,/^$/p' | grep $'\t' | cut -f2 | sort -u)
       if settled=$(python3 "$here/resolve_promotion_conflict.py" \
            "$parent" "$onto" "$commit" "$(printf '%s\n' "$tree" | head -1)" "${paths[@]}"); then
         tree=$settled
       # Origin changed other fields of the same puzzle (a re-date, a setter,
       # a re-read clue): the commit's annotation goes onto origin's file.
       elif settled=$(python3 "$here/reapply_annotation.py" \
            "$parent" "$onto" "$commit" "$(printf '%s\n' "$tree" | head -1)" "${paths[@]}"); then
         tree=$settled
       else
         echo "push_puzzle_commit: $(git log -1 --format=%s "$commit") conflicts with origin/master:" >&2
         printf '%s\n' "$tree" | tail -n +2 >&2
         # A batch commit (several puzzles, one "Annotate N puzzles: ..."): the
         # puzzles that do not conflict are published anyway, and the conflicted
         # ones keep the commit failing (CONFLICT) as a lone one would, so one
         # bad puzzle never holds the rest of its batch back.
         partial_tree=$(partial_replay "$(printf '%s\n' "$tree" | head -1)" "$onto" "${paths[@]}") || exit "$CONFLICT"
         if [ "$partial_tree" = "$(git rev-parse "$onto^{tree}")" ]; then exit "$CONFLICT"; fi
         echo "push_puzzle_commit: publishing the rest of the batch without: ${paths[*]}" >&2
         tree=$partial_tree
         final=$CONFLICT
       fi ;;
    *) exit 1 ;;
  esac
  if [ "$tree" = "$(git rev-parse "$onto^{tree}")" ]; then
    echo "push_puzzle_commit: origin/master already has $(git log -1 --format=%s "$commit")" >&2
    sha=$onto
  else
    sha=$(make_commit "$tree" "$onto" "$commit") || exit 1
  fi
  publish "$sha" "$base"; rc=$?
  [ $rc = 0 ] && exit "$final"
  [ $rc = 1 ] && exit 1
  echo "push_puzzle_commit: attempt $attempt lost the race" >&2
  sleep "$((RANDOM % 3 + 1))"
done
exit 1
