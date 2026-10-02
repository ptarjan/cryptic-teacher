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
eval "$(grep "config merge.json-keys" "$ROOT/tools/nightly_worktree.sh" |
  sed 's/git -C "$(dirname "${BASH_SOURCE\[0\]}")"/git/')"
check "driver registered from nightly_worktree.sh" \
  "$(git config merge.json-keys.driver)" "python3 tools/json_merge.py %O %A %B"

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
abbrev() { python3 - "$@" <<'PY'
import json, sys
p = "tools/data/abbreviations.json"
try: d = json.load(open(p))
except FileNotFoundError: d = {"_comment": ["x"], "abbreviations": {}}
t = d["abbreviations"]
for kv in sys.argv[1:]:
    k, v = kv.split("=")
    t[k] = sorted(set(t.get(k, []) + [v]))
d["abbreviations"] = dict(sorted(t.items()))
open(p, "w").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
PY
}
ledger "a 1=X" "c 1=Z"; abbrev "A=about" "C=caught"
git add -A && git commit -qm base
git checkout -qb burn
ledger "b 1=Y" "c 1=Z2"; abbrev "A=ace" "B=bachelor"
git commit -qam burn
git checkout -q master
ledger "b 2=W"; abbrev "A=acre" "B=book"
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
check "abbreviation rows union, sorted, indent=2" \
  "$(python3 -c 'import json; p="tools/data/abbreviations.json"; t=open(p).read(); d=json.loads(t); print(d["abbreviations"], json.dumps(d, indent=2)+"\n"==t)')" \
  "{'A': ['about', 'ace', 'acre'], 'B': ['bachelor', 'book'], 'C': ['caught']} True"

# Both sides changing one row differently: the replayed side wins, no conflict.
git checkout -q master; ledger "a 1=UP"; git commit -qam up2
git checkout -q burn; ledger "a 1=MINE"; git commit -qam mine2
git rebase -q master >/dev/null 2>&1
check "same row changed both sides takes the replayed commit's" \
  "$(python3 -c 'import json; print(json.load(open("tools/data/corroboration_ledger.json"))["a 1"]["winner"])')" MINE

# Not JSON on one side: an ordinary conflict, never a silently broken file.
git checkout -q master; echo '{ broken' > tools/data/corroboration_ledger.json; git commit -qam broken
git checkout -q burn; ledger "z 9=Q"; git commit -qam z
git rebase -q master >/dev/null 2>&1
check "unparseable side is left as a conflict" "$([ -n "$(git ls-files -u)" ] && echo conflict)" conflict
git rebase --abort 2>/dev/null

[ "$fails" = 0 ] && echo "json_merge: all checks passed" || { echo "json_merge: $fails FAILED"; exit 1; }
