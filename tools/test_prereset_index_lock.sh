#!/bin/bash
# Do the pool's concurrent runs commit only their own puzzle?
#
#     bash tools/test_prereset_index_lock.sh
#
# index_lock and index_unlock are read out of tools/prereset_backfill.sh. Eight
# runs in one scratch repo each stage and commit a file of their own at once,
# as the pool's runs do. Every commit must hold exactly its run's file, and
# nothing may be left uncommitted. The mirror runs the same eight without the
# lock and expects a run to lose its file, so the test is seen to bite.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO/tools/prereset_backfill.sh"
for fn in index_lock index_unlock; do
  block="$(sed -n "/^$fn() {/,/^}/p;/^$fn() {.*}$/p" "$SCRIPT")"
  if [ -z "$block" ]; then echo "FAIL tools/prereset_backfill.sh no longer defines $fn()"; exit 1; fi
  eval "$block"
done
fails=0

race() {  # race <lock|nolock>: prints how many runs' commits held only their own file
  local tree
  tree="$(mktemp -d)"
  # An identity of the scratch repo's own: CI has none, and a commit that cannot
  # be made reads as a lost race.
  git -C "$tree" init -q && git -C "$tree" config user.name "index lock test" &&
    git -C "$tree" config user.email "index-lock-test@example.invalid" &&
    git -C "$tree" commit -q --allow-empty -m base
  (
    cd "$tree" || exit 1
    for i in 1 2 3 4 5 6 7 8; do
      (
        echo "$i" >"p$i.json"
        [ "$1" = lock ] && index_lock
        git add -- "p$i.json" 2>/dev/null &&
          git commit -q -m "run $i" 2>/dev/null &&
          git show --name-only --format= HEAD >"msg$i"
        [ "$1" = lock ] && index_unlock
      ) &
    done
    wait
  )
  local own=0 i
  for i in 1 2 3 4 5 6 7 8; do
    [ "$(cat "$tree/msg$i" 2>/dev/null)" = "p$i.json" ] && own=$((own + 1))
  done
  [ -z "$(git -C "$tree" status --porcelain -- 'p*.json')" ] || own=$((own - 100))
  rm -rf "$tree"
  echo "$own"
}

got=$(race lock)
if [ "$got" = 8 ]; then echo "ok   locked: every run commits its own file and only it"
else echo "FAIL locked: $got of 8 runs committed only their own file"; fails=$((fails + 1)); fi

lost=0
for _ in 1 2 3 4 5; do [ "$(race nolock)" != 8 ] && lost=1 && break; done
if [ "$lost" = 1 ]; then echo "ok   unlocked, a run loses its file (the race is real)"
else echo "FAIL unlocked runs never collided in five tries, so this test proves nothing"; fails=$((fails + 1)); fi

[ "$fails" = 0 ] && echo "prereset index lock: all checks passed" || { echo "$fails failed"; exit 1; }
