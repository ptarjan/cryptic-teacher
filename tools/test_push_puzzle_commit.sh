#!/bin/bash
# Does tools/push_puzzle_commit.sh publish a commit while another process keeps
# writing into the same working tree, where fetch + rebase --autostash + push
# fails? The burn (tools/prereset_backfill.sh) commits and pushes each puzzle
# while the rest of its wave is still writing into that tree.
#
#     bash tools/test_push_puzzle_commit.sh
#
# Each round moves origin from a second clone, commits one puzzle in the burn's
# clone and pushes it, with a sibling rewriting a tracked file in a tight loop.
# The old push must fail at least once (so the test can see the race at all);
# the new one must never fail, must publish every puzzle, must leave HEAD and
# the sibling's file alone, and must not revert what the other clone pushed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
push="$here/push_puzzle_commit.sh"
rounds="${ROUNDS:-25}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

g() { git -c user.name=t -c user.email=t@t -c advice.detachedHead=false "$@"; }
git init -q --bare -b master "$tmp/origin.git"
g clone -q "$tmp/origin.git" "$tmp/seed" 2>/dev/null
mkdir -p "$tmp/seed/puzzles/s/2026"
echo 0 >"$tmp/seed/puzzles/s/2026/sibling.json"
echo 0 >"$tmp/seed/other.txt"
g -C "$tmp/seed" add -A && g -C "$tmp/seed" commit -qm seed && g -C "$tmp/seed" push -q origin HEAD:master
g clone -q "$tmp/origin.git" "$tmp/other"
g clone -q "$tmp/origin.git" "$tmp/burn"
g -C "$tmp/burn" checkout -q --detach

old_push() {
  git fetch -q origin master && g rebase -q --autostash origin/master &&
    git push -q origin HEAD:master
}

# $1 old|new. Prints how many rounds failed.
run() {
  local how="$1" i fails=0 wedged=0
  cd "$tmp/burn" || exit 1
  ( while :; do echo "$RANDOM" >puzzles/s/2026/sibling.json; sleep 0.01; done ) >/dev/null 2>&1 &
  writer=$!
  for i in $(seq "$rounds"); do
    echo "$how $i" >>"$tmp/other/other.txt"
    g -C "$tmp/other" commit -qam "other $how $i"
    g -C "$tmp/other" pull -q --rebase origin master >/dev/null 2>&1
    g -C "$tmp/other" push -q origin HEAD:master 2>/dev/null
    echo "{}" >"puzzles/s/2026/$how-$i.json"
    g add -- "puzzles/s/2026/$how-$i.json"
    g commit -qm "Annotate $how-$i" -- "puzzles/s/2026/$how-$i.json"
    if [ "$how" = old ]; then
      old_push >>"$tmp/old.err" 2>&1 || fails=$((fails + 1))
      # Unwedge, with the writer paused, so the next round can try again; its
      # rebase carries this round's commit along.
      kill -STOP "$writer"
      if [ -d "$(git rev-parse --git-dir)/rebase-merge" ]; then
        wedged=$((wedged + 1))
        g rebase --abort >/dev/null 2>&1 || rm -rf "$(git rev-parse --git-dir)/rebase-merge"
      fi
      [ -n "$(git stash list)" ] && g stash pop -q >/dev/null 2>&1
      g checkout -q -- puzzles/s/2026/sibling.json
      kill -CONT "$writer"
    else
      "$push" >/dev/null 2>&1 || fails=$((fails + 1))
    fi
  done
  kill "$writer"; wait "$writer" 2>/dev/null
  [ "$wedged" = 0 ] || echo "  ($wedged of those left rebase-merge/ behind)" >&2
  echo "$fails"
}

rc=0
old_fails=$(run old)
echo "old push (fetch, rebase --autostash, push): $old_fails of $rounds rounds failed, e.g.:"
grep -E "^(error|fatal)" "$tmp/old.err" | sort | uniq -c | sort -rn | head -4 | sed 's/^/    /' 
[ "$old_fails" -gt 0 ] || { echo "FAIL: the old push never lost the race, so this test cannot see it"; rc=1; }

g -C "$tmp/burn" fetch -q origin master
g -C "$tmp/burn" reset -q --hard origin/master
g -C "$tmp/burn" stash clear
head_before=$(git -C "$tmp/burn" rev-parse HEAD)
new_fails=$(run new)
echo "new push (tools/push_puzzle_commit.sh):        $new_fails of $rounds rounds failed"
[ "$new_fails" = 0 ] || { echo "FAIL: push_puzzle_commit.sh failed with a sibling writing"; rc=1; }

cd "$tmp/burn" || exit 1
git fetch -q origin master
missing=0
for i in $(seq "$rounds"); do
  git cat-file -e "origin/master:puzzles/s/2026/new-$i.json" 2>/dev/null || missing=$((missing + 1))
  git cat-file -p origin/master:other.txt | grep -qx "new $i" || { echo "FAIL: other clone's line $i was reverted"; rc=1; }
done
[ "$missing" = 0 ] || { echo "FAIL: $missing puzzles never reached origin/master"; rc=1; }
[ "$(git rev-list --count "$head_before..HEAD")" = "$rounds" ] ||
  { echo "FAIL: HEAD moved: the push touched the local branch"; rc=1; }
git diff --quiet HEAD -- puzzles/s/2026/sibling.json &&
  { echo "FAIL: the sibling's uncommitted write was swept away"; rc=1; }
[ -d "$(git rev-parse --git-dir)/rebase-merge" ] && { echo "FAIL: a rebase was left behind"; rc=1; }
[ -z "$(git stash list)" ] || { echo "FAIL: something was stashed"; rc=1; }

# The quiet-tree catch-up the burn does after a wave: the local copies drop out.
g rebase -q --autostash origin/master >/dev/null 2>&1
[ "$(git rev-list --count origin/master..HEAD)" = 0 ] ||
  { echo "FAIL: after the rebase, local commits were not recognised as already pushed"; rc=1; }

# An upstream edit to the same file conflicts; it must be refused, not reverted.
echo "{}" >puzzles/s/2026/clash.json && g add -A -- puzzles && g commit -qm clash-base -- puzzles/s/2026/clash.json
git push -q origin HEAD:master
g -C "$tmp/other" pull -q --rebase origin master 2>/dev/null
echo '{"a":1}' >"$tmp/other/puzzles/s/2026/clash.json"
g -C "$tmp/other" commit -qam "other edits clash" && g -C "$tmp/other" push -q origin HEAD:master
echo '{"b":2}' >puzzles/s/2026/clash.json
g commit -qm "Annotate clash" -- puzzles/s/2026/clash.json
if "$push" 2>/dev/null; then
  echo "FAIL: a conflicting edit was pushed over the other clone's"; rc=1
fi
git fetch -q origin master
[ "$(git cat-file -p origin/master:puzzles/s/2026/clash.json)" = '{"a":1}' ] ||
  { echo "FAIL: origin's clash.json changed"; rc=1; }

[ "$rc" = 0 ] && echo "PASS"
exit "$rc"
