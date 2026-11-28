#!/bin/bash
# Can a puzzle the burn fetched ever block its sync's rebase?
#
# extend_archive.py files new puzzles at burn start. Left untracked, the first
# time origin committed one of the same paths, `git rebase --autostash
# origin/master` refused to start and the burn stopped syncing. This runs
# tools/publish_fetched.sh against a real origin, with origin committing first
# and with it not, and rebases the way prereset_backfill.sh's sync_attempt does.
#
#     bash tests/test_publish_fetched.sh
set -uo pipefail
export PUSH_BATCH_SECS=0  # every push at once, not batched 5 min apart (tools/push_puzzle_commit.sh)
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
cp "$ROOT/tools/publish_fetched.sh" "$ROOT/tools/push_puzzle_commit.sh" "$ROOT/tools/yield_cpu.sh" "$ROOT/tools/same_history.sh" "$ROOT/tools/clobber_guard.py" "$ROOT/tools/drop_clues_only_twin.py" "$ROOT/tools/puzzle_schema.py" tools/
mkdir -p tools/data && cp "$ROOT/tools/data/puzzle.schema.json" tools/data/
echo '{"id":"cryptic-1"}' > puzzles/cryptic/2026/cryptic-1.json
printf "__pycache__/\n" > .gitignore
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

# A puzzle filed under puzzles/ takes its clues-only copy in the same commit.
mkdir -p clues_only/cryptic
echo '{"id":"cryptic-7","twin":true}' > clues_only/cryptic/cryptic-7.json
git add clues_only && git commit -qm "twin" && git push -q origin master
tools/publish_fetched.sh bash ../fetch.sh cryptic-7
check "the filed puzzle's clues-only twin is gone" "$(ls clues_only/cryptic | tr '\n' ' ')" ""
check "the twin went in the puzzle's commit" \
  "$(git show --name-status --format=%s HEAD | tr '\t\n' '  ')" "File cryptic-7  D clues_only/cryptic/cryptic-7.json A puzzles/cryptic/2026/cryptic-7.json "

# The twin's blog answers move into the puzzle first (read differently, so --force
# is what drops it); one that fits no entry keeps the twin.
cat > ../fetch_clues.sh <<'SH'
for id in "$@"; do
  echo "{\"id\":\"$id\",\"entries\":[{\"number\":1,\"direction\":\"down\",\"length\":3,\"position\":[0,0],\"clue\":{\"text\":\"Near WC1,for a start\"}}]}" > "puzzles/cryptic/2026/$id.json"
done
SH
mkdir -p clues_only/cryptic
twin_of() { echo "{\"id\":\"$1\",\"clues\":{\"down\":[{\"clue\":{\"text\":\"Near WC1, for a start +\"},\"length\":3,\"blogAnswer\":\"$2\"}]}}" > "clues_only/cryptic/$1.json"; }
twin_of cryptic-10 ABC; twin_of cryptic-11 ABCD
git add clues_only && git commit -qm "twins" && git push -q origin master
tools/publish_fetched.sh bash ../fetch_clues.sh cryptic-10 cryptic-11
check "a twin whose blog answer fits is dropped" "$(ls clues_only/cryptic | tr '\n' ' ')" "cryptic-11.json "
check "its blog answer is in the puzzle" \
  "$(python3 -c "import json;print(json.load(open('puzzles/cryptic/2026/cryptic-10.json'))['entries'][0]['blogAnswer'])")" "ABC"
check "the merge went in the puzzle's commit" \
  "$(git log --format=%s -1 -- puzzles/cryptic/2026/cryptic-10.json)" "File cryptic-10"
check "nothing is left uncommitted" "$(git status --porcelain -- clues_only | tr '\n' ' ')" ""

[ "$fails" = 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
