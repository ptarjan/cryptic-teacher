#!/bin/bash
# Do two writers adding different rows to the source-correction tables merge
# without a conflict?
#
#     bash tools/test_source_tables_merge.sh
#
# tools/data/source_clue_wrong.json and source_answer_wrong.json are flat objects
# keyed "puzzle id/entry id", one row per line. In a scratch repo holding this
# repo's real tables, .gitattributes and tools/json_merge.py, two branches each
# add a different row at the same position (between the same two neighbours, and
# again at the very end of the file, where the trailing comma moves) and are
# merged by `git merge` and by a rebase. Neither may conflict, and the result
# must hold both rows and every original one, still one row per line.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <got> <want>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: got [$2], want [$3]"; fails=$((fails + 1)); fi
}

for t in source_clue_wrong source_answer_wrong; do
  check "$t.json is registered with the json-keys driver" \
    "$(git -C "$ROOT" check-attr merge -- "tools/data/$t.json" | awk '{print $NF}')" json-keys
done

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || exit 1
git init -q -b master repo && cd repo || exit 1
git config user.email nobody@example.com
git config user.name test
git config merge.json-keys.driver "python3 tools/json_merge.py %O %A %B"
mkdir -p tools/data
cp "$ROOT/tools/json_merge.py" tools/
cp "$ROOT/.gitattributes" .
cp "$ROOT/tools/data/source_clue_wrong.json" "$ROOT/tools/data/source_answer_wrong.json" tools/data/

# addrow <table> <key>: add one row, as a writer (or a model) would, by hand.
addrow() { python3 - "$@" <<'PY'
import json, sys
sys.path.insert(0, "tools")
from json_merge import dump_lines
p = f"tools/data/{sys.argv[1]}.json"
rows = json.load(open(p))
rows[sys.argv[2]] = ["served", "printed", "added by " + sys.argv[2]]
open(p, "w").write(dump_lines(rows))
PY
}
git add -A && git commit -qm base
before=$(python3 -c 'import json; print(json.dumps({t: json.load(open(f"tools/data/{t}.json")) for t in ("source_clue_wrong", "source_answer_wrong")}, sort_keys=True))')

for t in source_clue_wrong source_answer_wrong; do
  for where in "middle:cryptic-1/1-across:cryptic-1/2-across" "end:zzz-1/1-across:zzz-2/1-across"; do
    IFS=: read -r name ka kb <<<"$where"
    for how in merge rebase; do
      git checkout -q master
      git checkout -qb "a-$t-$name-$how"
      addrow "$t" "$ka"; git commit -qam "a adds $ka"
      git checkout -q master; git checkout -qb "b-$t-$name-$how"
      addrow "$t" "$kb"; git commit -qam "b adds $kb"
      if [ "$how" = merge ]; then
        git merge -q --no-edit "a-$t-$name-$how" >/dev/null 2>&1
      else
        git rebase -q "a-$t-$name-$how" >/dev/null 2>&1
      fi
      check "$t $name $how: no conflict" "$(git ls-files -u | wc -l | tr -d ' ')" 0
      check "$t $name $how: both rows present" \
        "$(python3 -c "import json; d=json.load(open('tools/data/$t.json')); print('$ka' in d and '$kb' in d)")" True
      check "$t $name $how: still sorted, one row per line" \
        "$(python3 -c 'import json,sys; sys.path.insert(0,"tools"); from json_merge import dump_lines; p="tools/data/'"$t"'.json"; print(dump_lines(json.load(open(p))) == open(p).read())')" True
      git merge --abort 2>/dev/null; git rebase --abort 2>/dev/null
      git checkout -q -f master; git reset -q --hard
    done
  done
done
check "every original row is unchanged on master" \
  "$(python3 -c 'import json; print(json.dumps({t: json.load(open(f"tools/data/{t}.json")) for t in ("source_clue_wrong", "source_answer_wrong")}, sort_keys=True))')" "$before"

[ "$fails" = 0 ] && echo "source_tables_merge: all checks passed" || { echo "source_tables_merge: $fails FAILED"; exit 1; }
