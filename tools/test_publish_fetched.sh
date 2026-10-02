#!/bin/bash
# Can a puzzle the burn fetched ever block its sync's rebase?
#
# extend_archive.py files new puzzles at burn start. Left untracked, the first
# time origin committed one of the same paths, `git rebase --autostash
# origin/master` refused to start and the burn stopped syncing. This runs
# tools/publish_fetched.sh against a real origin, with origin committing first
# and with it not, and rebases the way prereset_backfill.sh's sync_attempt does.
#
#     bash tools/test_publish_fetched.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || exit 1
ident() { git config user.email nobody@example.com; git config user.name test; }
git init -q --bare -b master origin.git
git clone -q origin.git seed 2>/dev/null && cd seed && ident || exit 1
mkdir -p tools puzzles/cryptic/2026
cp "$ROOT/tools/publish_fetched.sh" "$ROOT/tools/push_puzzle_commit.sh" tools/
echo '{"id":"cryptic-1"}' > puzzles/cryptic/2026/cryptic-1.json
git add -A && git commit -qm base && git push -q origin master
cd .. && git clone -q origin.git burn && git clone -q origin.git upstream
(cd burn && ident) && (cd upstream && ident)

# Origin files a puzzle with this content.
upstream_files() { (cd "$tmp/upstream" && git pull -q --rebase origin master &&
  mkdir -p puzzles/cryptic/2026 && echo "$2" > "puzzles/cryptic/2026/$1.json" &&
  git add -A && git commit -qm "upstream $1" && git push -q origin master); }
# The fetch: files puzzles into the burn's tree.
cat > fetch.sh <<'SH'
for id in "$@"; do echo "{\"id\":\"$id\",\"from\":\"burn\"}" > "puzzles/cryptic/2026/$id.json"; done
SH
sync_attempt() { git fetch -q origin master && git rebase -q --autostash origin/master 2>/dev/null; }

cd burn || exit 1
# A cut-off run's partial annotation, dirty before the fetch.
echo '{"id":"cryptic-1","partial":true}' > puzzles/cryptic/2026/cryptic-1.json

# The stall itself, so the test is known to see it: untracked fetched file,
# origin commits the same path, the rebase will not start.
bash ../fetch.sh cryptic-9
upstream_files cryptic-9 '{"id":"cryptic-9","from":"upstream"}'
sync_attempt 2>/dev/null; check "untracked fetched file blocks the rebase (the bug)" "$?" "1"
rm puzzles/cryptic/2026/cryptic-9.json; sync_attempt

# Origin quiet: the fetched puzzles reach origin before anything else runs.
tools/publish_fetched.sh bash ../fetch.sh cryptic-2 cryptic-3
check "publish exits 0" "$?" "0"
check "origin holds the fetched puzzles" \
  "$(git ls-tree --name-only origin/master puzzles/cryptic/2026/ | tr '\n' ' ')" \
  "puzzles/cryptic/2026/cryptic-1.json puzzles/cryptic/2026/cryptic-2.json puzzles/cryptic/2026/cryptic-3.json puzzles/cryptic/2026/cryptic-9.json "
check "the partial annotation was not published" \
  "$(git show origin/master:puzzles/cryptic/2026/cryptic-1.json)" '{"id":"cryptic-1"}'
check "the partial annotation is still dirty here" \
  "$(git status --porcelain -- puzzles/ | tr '\n' ' ')" " M puzzles/cryptic/2026/cryptic-1.json "
upstream_files cryptic-3 '{"id":"cryptic-3","from":"upstream-edit"}'
sync_attempt; check "the rebase after publishing succeeds" "$?" "0"

# Origin files one of the same paths, differently, mid-fetch: ours is refused
# and dropped, and the rebase brings in origin's.
cat > ../racing_fetch.sh <<SH
bash "$tmp/fetch.sh" cryptic-4 cryptic-5
cd "$tmp/upstream" && git pull -q --rebase origin master &&
  echo '{"id":"cryptic-4","from":"upstream"}' > puzzles/cryptic/2026/cryptic-4.json &&
  git add -A && git commit -qm "upstream cryptic-4" && git push -q origin master
SH
tools/publish_fetched.sh bash ../racing_fetch.sh 2>/dev/null
check "a refused publish exits 3" "$?" "3"
check "nothing fetched is left uncommitted" \
  "$(git status --porcelain -- puzzles/ | tr '\n' ' ')" " M puzzles/cryptic/2026/cryptic-1.json "
sync_attempt; check "the rebase after a refused publish succeeds" "$?" "0"
check "origin's copy won" "$(cat puzzles/cryptic/2026/cryptic-4.json)" '{"id":"cryptic-4","from":"upstream"}'
check "the partial annotation survived both" \
  "$(cat puzzles/cryptic/2026/cryptic-1.json)" '{"id":"cryptic-1","partial":true}'

# A fetch that fails still publishes what it wrote, and its status comes back.
tools/publish_fetched.sh bash -c 'bash ../fetch.sh cryptic-6; exit 7'
check "the fetch's own failure is returned" "$?" "7"
check "what a failed fetch wrote reached origin" \
  "$(git cat-file -t origin/master:puzzles/cryptic/2026/cryptic-6.json)" "blob"

[ "$fails" = 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
