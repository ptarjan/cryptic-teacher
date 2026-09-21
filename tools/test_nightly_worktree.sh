#!/bin/bash
# Which tree does a scheduled job end up running in? Checked by running one.
#
# The three outcomes tools/nightly_worktree.sh can produce — its own worktree,
# the main checkout, or nothing at all — differ only in what the job then reads
# out of the tree, so none of them announces itself as wrong. A job that plans
# from a checkout behind origin/master hands out work that is already pushed.
#
# Run standalone or from tools/smoke_test.js.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git config --global --get init.defaultBranch >/dev/null 2>&1 || true

# A repo with an origin, and a job that reports nothing but the tree it woke up
# in. fetch_puzzle.py stands in for the reindex the helper runs after a reset.
git init -q --bare "$tmp/origin.git"
git init -q "$tmp/main"
mkdir -p "$tmp/main/tools"
cp "$ROOT/tools/nightly_worktree.sh" "$ROOT/tools/alert.sh" "$tmp/main/tools/"
printf '#!/usr/bin/env python3\n' > "$tmp/main/tools/fetch_puzzle.py"
cat > "$tmp/main/tools/faketask.sh" <<'JOB'
#!/bin/bash
. "$(dirname "$0")/nightly_worktree.sh"
echo "RAN IN $(cd "$(dirname "$0")/.." && pwd)"
JOB
chmod +x "$tmp/main/tools/faketask.sh"
git -C "$tmp/main" add -A
git -C "$tmp/main" -c user.email=t@t -c user.name=t commit -qm init
git -C "$tmp/main" remote add origin "$tmp/origin.git"
git -C "$tmp/main" push -q origin HEAD:master
git -C "$tmp/main" branch -q -M master
git -C "$tmp/main" fetch -q origin master

run() { # run() <worktree-root> -> the job's output, stderr folded in
  ALERT_ENV_FILE=/nonexistent CT_WORKTREE_ROOT="$1" \
    bash "$tmp/main/tools/faketask.sh" 2>&1
}

# 1. The happy path, and the baseline the next two are read against.
got="$(run "$tmp/trees" | grep '^RAN IN ')"
check "a job gets its own worktree" "$got" "RAN IN $tmp/trees/faketask"

# 2. An index.lock outlives the process that took it — nothing in git ever
#    clears one — so a single crashed command otherwise fails every future run
#    of the job in the same way, forever.
lock="$(git -C "$tmp/trees/faketask" rev-parse --git-dir)/index.lock"
: > "$lock"
touch -t 200001010000 "$lock"
out="$(run "$tmp/trees")"
check "a stale index.lock is cleared, not waited on" \
  "$(echo "$out" | grep -c 'clearing an index.lock')" "1"
check "and the job still gets its worktree" \
  "$(echo "$out" | grep '^RAN IN ')" "RAN IN $tmp/trees/faketask"

# 3. With no worktree to be had, the main checkout is the only tree left. Behind
#    origin/master it holds a stale view of the corpus, and a job that plans
#    from one hands out work that is already pushed, so the run must not happen.
: > "$tmp/blocked"   # a file where the worktree root wants a directory
git -C "$tmp/main" -c user.email=t@t -c user.name=t commit -q --allow-empty -m ahead
git -C "$tmp/main" push -q origin master
git -C "$tmp/main" reset -q --hard HEAD~1
out="$(run "$tmp/blocked/trees")"
check "a checkout behind origin/master is refused" \
  "$(echo "$out" | grep -c 'stopping without running')" "1"
check "and nothing runs there" "$(echo "$out" | grep -c '^RAN IN ')" "0"

# 4. Dirty is refused for the same reason from the other side: the job would
#    sweep somebody's unstaged work into its own commit.
git -C "$tmp/main" merge -q --ff-only origin/master
echo dirt >> "$tmp/main/tools/faketask.sh"
out="$(run "$tmp/blocked/trees")"
check "a dirty checkout is refused" \
  "$(echo "$out" | grep -c 'stopping without running')" "1"
git -C "$tmp/main" checkout -q -- tools/faketask.sh

# 5. Clean and current, it is the same tree the worktree would have been.
out="$(run "$tmp/blocked/trees")"
check "a clean checkout at origin/master runs in place" \
  "$(echo "$out" | grep '^RAN IN ')" "RAN IN $tmp/main"

[ "$fails" = 0 ] && echo "NIGHTLY WORKTREE PASSED" || echo "$fails check(s) failed"
exit $((fails > 0))
