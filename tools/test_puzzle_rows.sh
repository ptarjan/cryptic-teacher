#!/bin/bash
# Do a puzzle's table rows go where its file goes? In a scratch repo:
# tools/puzzle_rows.py retire discards a dropped id's rows and carries a
# renamed one's, leaving every other row and the file layout as they were; the
# pre-commit gate (--check-staged) refuses a staged deletion or rename that
# leaves rows and lets a directory move and a retired drop through;
# tools/durable.sh commits a drop with its rows gone, past that gate, and lands
# it on origin. Then every real table row names a puzzle file on disk.
#
#     bash tools/test_puzzle_rows.sh
set -uo pipefail
# json_merge (dump_lines) is imported in the scratch repo, which has no .gitignore.
export PYTHONDONTWRITEBYTECODE=1
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}
export HOME="$tmp/home" GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$HOME"
git config --global init.defaultBranch master
git init -q --bare "$tmp/origin.git"
git clone -q "$tmp/origin.git" "$tmp/r" 2>/dev/null
R="$tmp/r"
mkdir -p "$R/tools/data" "$R/puzzles/x/2017" "$R/hooks"
cp "$here"/{puzzle_rows.py,durable.sh,unstage_unparsable.sh,commit_puzzles.sh,push_puzzle_commit.sh,clobber_guard.py,commit_subject.py,renamed_ids.py,json_merge.py} "$R/tools/"
# SOURCE_LIGHT_WRONG, as fetch_puzzle.py spells it.
printf 'SOURCE_LIGHT_WRONG = {\n    ("x-9", "1-across"): (\n        {}, {}, ""),\n}\n' >"$R/tools/fetch_puzzle.py"
printf '#!/bin/sh\nexec python3 tools/puzzle_rows.py --check-staged\n' >"$R/hooks/pre-commit"
chmod +x "$R/hooks/pre-commit"
cd "$R" || exit 1
git config core.hooksPath "$R/hooks"
for n in 1 2 3 4 9; do
  python3 -c 'import json,sys; json.dump({"id": sys.argv[1], "entries": [{"n": i, "c": sys.argv[1] + " clue %d of many words" % i} for i in range(30)]}, open(sys.argv[2], "w"), indent=1)' "x-$n" "puzzles/x/2017/x-$n.json"
done
cat >tools/data/source_clue_wrong.json <<'EOF'
{
 "x-1/1-across": ["servd", "served", "a misread"],
 "x-2/3-down": ["a", "b", "c"],
 "x-3/5-across": ["d", "e", "f"]
}
EOF
printf '{\n "x-1": {\n  "letters": "ABC"\n },\n "x-2": {\n  "letters": "DEF"\n }\n}\n' >tools/data/ninas.json
echo '{"README": "x"}' >tools/data/renamed_ids.json
git add -A && git commit -qm start && git push -q origin master 2>/dev/null

# retire, without git.
cp tools/data/source_clue_wrong.json "$tmp/scw"
python3 tools/puzzle_rows.py retire x-1 >/dev/null
check "a drop discards its rows and no other" '["x-2/3-down", "x-3/5-across"]' \
  "$(python3 -c 'import json; print(json.dumps(list(json.load(open("tools/data/source_clue_wrong.json")))))')"
check "and keeps the table's layout" "$(grep -v x-1 "$tmp/scw")" "$(cat tools/data/source_clue_wrong.json)"
check "a puzzle-keyed table too" '["x-2"]' "$(python3 -c 'import json; print(json.dumps(list(json.load(open("tools/data/ninas.json")))))')"
git checkout -q -- tools/data
python3 tools/puzzle_rows.py retire x-2 x-4 >/dev/null
check "a rename carries its rows" '["x-1/1-across", "x-3/5-across", "x-4/3-down"]' \
  "$(python3 -c 'import json; print(json.dumps(sorted(json.load(open("tools/data/source_clue_wrong.json")))))')"
check "SOURCE_LIGHT_WRONG is named for hand editing" 1 \
  "$(python3 tools/puzzle_rows.py retire x-9 2>&1 >/dev/null | grep -c 'SOURCE_LIGHT_WRONG')"
git checkout -q -- tools/data

# The gate.
git rm -q puzzles/x/2017/x-1.json
check "a staged drop leaving rows is refused" 1 "$(python3 tools/puzzle_rows.py --check-staged 2>/dev/null; echo $?)"
check "and names the fix" 1 "$(python3 tools/puzzle_rows.py --check-staged 2>&1 | grep -c 'retire x-1')"
python3 tools/puzzle_rows.py retire x-1 >/dev/null && git add tools/data
check "retired and staged, it passes" 0 "$(python3 tools/puzzle_rows.py --check-staged; echo $?)"
git reset -q --hard
git rm -q puzzles/x/2017/x-9.json
check "a SOURCE_LIGHT_WRONG key counts" 1 "$(python3 tools/puzzle_rows.py --check-staged 2>/dev/null; echo $?)"
git reset -q --hard
git mv puzzles/x/2017/x-2.json puzzles/x/2017/x-5.json
check "a rename leaving rows is refused" 1 "$(python3 tools/puzzle_rows.py --check-staged 2>/dev/null; echo $?)"
check "and the fix names the new id" 1 "$(python3 tools/puzzle_rows.py --check-staged 2>&1 | grep -c 'retire x-2 x-5')"
git reset -q --hard
mkdir -p puzzles/x/2018 && git mv puzzles/x/2017/x-3.json puzzles/x/2018/x-3.json
check "a file that moves keeps its id and its rows" 0 "$(python3 tools/puzzle_rows.py --check-staged; echo $?)"
git reset -q --hard

# durable.sh: a deletion in the tree plus a filing.
rm puzzles/x/2017/x-1.json
python3 -c 'import json; json.dump({"id": "x-6", "entries": []}, open("puzzles/x/2017/x-6.json", "w"))'
(DURABLE_PATHS=(puzzles); . tools/durable.sh; durable_checkpoint "test pass") >"$tmp/durable.out" 2>&1
check "durable commits the drop past the gate" "Drop x-1" \
  "$(git --git-dir="$tmp/origin.git" log --format=%s master | grep -m1 'Drop')"
check "after the filing" "Drop x-1|File x-6" \
  "$(git --git-dir="$tmp/origin.git" log --format=%s -2 master | tr '\n' '|' | sed 's/|$//')"
check "and its rows go in that commit" 0 \
  "$(git --git-dir="$tmp/origin.git" show master:tools/data/source_clue_wrong.json | grep -c x-1)"
check "nothing left uncommitted" "" "$(git status --porcelain)"

cd "$here/.." || exit 1
check "every real table row names a puzzle on disk" 0 "$(python3 tools/puzzle_rows.py --check; echo $?)"

[ "$fails" = 0 ] && echo "puzzle_rows: all checks passed" || echo "puzzle_rows: $fails FAILED"
exit $((fails > 0))
