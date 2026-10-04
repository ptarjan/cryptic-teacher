#!/bin/bash
# Do the keyed JSON data files merge per key in a real rebase?
#
# Two writers adding neighbouring rows to tools/data/corroboration_ledger.json
# conflicted line by line, and the pre-reset burn stopped on it (2a0dbdc). This
# rebases such a pair with the driver registered the way tools/nightly_worktree.sh
# registers it, through .gitattributes as committed, and through the
# merge-tree tools/push_puzzle_commit.sh pushes with.
#
#     bash tools/test_json_merge.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || exit 1
git init -q -b master repo && cd repo || exit 1
git config user.email nobody@example.com
git config user.name test
mkdir -p tools/data
cp "$ROOT/tools/json_merge.py" "$ROOT/.gitattributes" tools/ 2>/dev/null
mv tools/.gitattributes .
eval "$(grep -E "config (merge|filter)\.json-keys" "$ROOT/tools/nightly_worktree.sh" |
  sed 's/git -C "$(dirname "${BASH_SOURCE\[0\]}")"/git/')"
check "driver registered from nightly_worktree.sh" \
  "$(git config merge.json-keys.driver)" "python3 tools/json_merge.py %O %A %B"
check "clean filter registered from nightly_worktree.sh" \
  "$(git config filter.json-keys.clean)" "python3 tools/json_merge.py --clean"
canonical() { python3 -c 'import json,sys; sys.path.insert(0,"tools"); from json_merge import dump_lines; t=sys.stdin.read(); print(dump_lines(json.loads(t)) == t)'; }

ledger() { python3 - "$@" <<'PY'
import json, sys
sys.path.insert(0, "tools")
from json_merge import dump_lines
p = "tools/data/corroboration_ledger.json"
try: held = json.load(open(p))
except FileNotFoundError: held = {}
for kv in sys.argv[1:]:
    k, v = kv.split("=")
    held[k] = {"winner": v, "rule": "grid"}
open(p, "w").write(dump_lines(held))
PY
}
ledger "a 1=X" "c 1=Z"
git add -A && git commit -qm base
git checkout -qb burn
ledger "b 1=Y" "c 1=Z2"
git commit -qam burn
git checkout -q master
ledger "b 2=W"
git commit -qam upstream
# The commit push_puzzle_commit.sh would build: merge-tree, never a worktree.
if tree=$(git merge-tree --write-tree --merge-base master~1 master burn 2>&1); then mt=clean; else mt="conflict: $tree"; fi
check "merge-tree (push_puzzle_commit.sh) merges per key" "$mt" clean
git checkout -q burn
git rebase -q master >/dev/null 2>&1; check "rebase completes" "$(git ls-files -u | wc -l | tr -d ' ')" 0
check "ledger keeps every row, valid JSON" \
  "$(python3 -c 'import json; d=json.load(open("tools/data/corroboration_ledger.json")); print(sorted((k, v["winner"]) for k, v in d.items()))')" \
  "[('a 1', 'X'), ('b 1', 'Y'), ('b 2', 'W'), ('c 1', 'Z2')]"
check "ledger keeps its one-line-per-key layout" \
  "$(python3 -c 'import json,sys; sys.path.insert(0,"tools"); from json_merge import dump_lines; p="tools/data/corroboration_ledger.json"; print(dump_lines(json.load(open(p))) == open(p).read())')" True

# Both sides changing one row differently: the replayed side wins, no conflict.
git checkout -q master; ledger "a 1=UP"; git commit -qam up2
git checkout -q burn; ledger "a 1=MINE"; git commit -qam mine2
git rebase -q master >/dev/null 2>&1
check "same row changed both sides takes the replayed commit's" \
  "$(python3 -c 'import json; print(json.load(open("tools/data/corroboration_ledger.json"))["a 1"]["winner"])')" MINE

# Rows typed in by hand, without dump_lines' spacing, on both sides, by writers
# the clean filter did not cover (cat stands in for no filter). Both sides parse,
# so they merge, and the merge writes the canonical layout. The driver used to
# refuse a file neither side of which was canonical, and stranded the nightly
# (2a91fb9, 2026-10-04).
handrow() { python3 - "$1" <<'PY'
import sys
p = "tools/data/corroboration_ledger.json"
t = open(p).read()
open(p, "w").write(t[:t.rindex("}")].rstrip() + ',\n"%s":{"rule": "grid","winner":"%s"}\n}\n' % (sys.argv[1], sys.argv[1][0].upper()))
PY
}
nofilter() { git -c filter.json-keys.clean=cat "$@"; }
git checkout -q master; handrow "h 1"; nofilter commit -qam handwritten
check "the hand-written row is committed as written" \
  "$(git show HEAD:tools/data/corroboration_ledger.json | canonical)" False
nofilter checkout -qb burn2; handrow "d 1"; nofilter commit -qam d
nofilter checkout -q master; handrow "e 1"; nofilter commit -qam e
nofilter checkout -q burn2
nofilter rebase -q master >/dev/null 2>&1
check "rebase with both sides hand-written completes" "$(git ls-files -u | wc -l | tr -d ' ')" 0
check "the merge keeps every hand-written row" \
  "$(python3 -c 'import json; d=json.load(open("tools/data/corroboration_ledger.json")); print(d["h 1"]["winner"], d["d 1"]["winner"], d["e 1"]["winner"])')" "H D E"
check "the merge writes one line per key" "$(canonical < tools/data/corroboration_ledger.json)" True
nofilter checkout -q burn

# The clean filter: a hand edit is staged in the canonical layout.
sed -i 's/^}$/,"g 1":{"winner":"G","rule":"grid"}}/' tools/data/corroboration_ledger.json
git add tools/data/corroboration_ledger.json
check "git add stages a hand edit one line per key" \
  "$(git show :tools/data/corroboration_ledger.json | canonical)" True
git commit -qm g

# Not JSON on one side: an ordinary conflict, never a silently broken file.
git checkout -q master; echo '{ broken' > tools/data/corroboration_ledger.json; git commit -qam broken
git checkout -q burn; ledger "z 9=Q"; git commit -qam z
git rebase -q master >/dev/null 2>&1
check "unparseable side is left as a conflict" "$([ -n "$(git ls-files -u)" ] && echo conflict)" conflict
git rebase --abort 2>/dev/null

# What is committed: every json-keys file in its one-line-per-key layout, which
# is what lets the merge and the filter be no-ops on it.
for f in $(sed -n 's/^\([^#][^ ]*\) .*merge=json-keys.*/\1/p' "$ROOT/.gitattributes"); do
  check "$f is one line per key" "$(canonical < "$ROOT/$f")" True
done

[ "$fails" = 0 ] && echo "json_merge: all checks passed" || { echo "json_merge: $fails FAILED"; exit 1; }
