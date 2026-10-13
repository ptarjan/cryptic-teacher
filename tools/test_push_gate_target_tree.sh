#!/bin/bash
# Does tools/push_puzzle_commit.sh judge a commit with the checking code of the
# tree it publishes (origin/master plus the commit), not the pusher's own
# checkout? The burn (tools/prereset_backfill.sh) pushes from a checkout that is
# behind master until its push succeeds and it resets, so a gate judged from
# that checkout deadlocks it once master loosens the gate, and lets it past a
# gate master has tightened.
#
#     bash tools/test_push_gate_target_tree.sh
#
# The gate here is a stub tools/pre_push.py that refuses or passes every push,
# run by a copy of the repo's .githooks/pre-push, as on the real checkouts.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
push="$here/push_puzzle_commit.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

g() { git -c user.name=t -c user.email=t@t -c advice.detachedHead=false "$@"; }
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$tmp/hooks"
cp "$here/../.githooks/pre-push" "$tmp/hooks/pre-push"

strict='import sys; print("SETTER genius-18 no setter, but genius prints a byline", file=sys.stderr); sys.exit(1)'
loose='import sys; sys.exit(0)'
gate() {  # $1 clone, $2 strict|loose: put that gate on origin/master
  g -C "$1" pull -q --rebase origin master
  printf '%s\n' "${!2}" >"$1/tools/pre_push.py"
  g -C "$1" add tools/pre_push.py
  g -C "$1" diff --cached --quiet && return
  g -C "$1" commit -qm "gate $2" && g -C "$1" push -q --no-verify origin HEAD:master
}

git init -q --bare -b master "$tmp/origin.git"
g clone -q "$tmp/origin.git" "$tmp/master" 2>/dev/null
mkdir -p "$tmp/master/tools" "$tmp/master/puzzles/s/2026"
echo '{}' >"$tmp/master/puzzles/s/2026/seed.json"
g -C "$tmp/master" add -A && g -C "$tmp/master" commit -qm seed && g -C "$tmp/master" push -q origin HEAD:master

rc=0
# $1 gate the burn's checkout holds, $2 gate master moves to, $3 pass|refuse.
case_() {
  local stale="$1" target="$2" want="$3" burn="$tmp/burn-$1-$2" before
  gate "$tmp/master" "$stale"
  g clone -q "$tmp/origin.git" "$burn"
  g -C "$burn" config core.hooksPath "$tmp/hooks"
  gate "$tmp/master" "$target"
  echo '{"id": "x"}' >"$burn/puzzles/s/2026/$stale-$target.json"
  g -C "$burn" add puzzles && g -C "$burn" commit -qm "Annotate $stale-$target" -- puzzles
  before=$(git -C "$burn" rev-parse HEAD)
  if (cd "$burn" && "$push") >"$tmp/out" 2>&1; then got=pass; else got=refuse; fi
  git -C "$burn" fetch -q origin master
  if [ "$got" != "$want" ]; then
    echo "FAIL: burn with the $stale gate, master with the $target gate: push should $want, did $got:"
    sed 's/^/    /' "$tmp/out"; rc=1
  fi
  if git -C "$burn" cat-file -e "origin/master:puzzles/s/2026/$stale-$target.json" 2>/dev/null; then
    [ "$want" = pass ] || { echo "FAIL: master's $target gate was bypassed from a $stale checkout"; rc=1; }
  else
    [ "$want" = refuse ] || { echo "FAIL: $stale-$target.json never reached origin/master"; rc=1; }
  fi
  [ "$(git -C "$burn" rev-parse HEAD)" = "$before" ] || { echo "FAIL: the push moved the burn's HEAD"; rc=1; }
  [ "$(cat "$burn/tools/pre_push.py")" = "${!stale}" ] || { echo "FAIL: the push rewrote the burn's tools/"; rc=1; }
}

case_ strict loose pass     # master loosened the gate: the stale checkout must not deadlock
case_ loose strict refuse   # master tightened the gate: the stale checkout must not slip past
case_ strict strict refuse
case_ loose loose pass

[ "$rc" = 0 ] && echo "PASS"
exit "$rc"
