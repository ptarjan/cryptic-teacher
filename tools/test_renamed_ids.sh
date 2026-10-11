#!/bin/bash
# Does a renamed puzzle's old id keep resolving? In a scratch repo:
# tools/renamed_ids.py pairs a rename even inside a commit that moves every
# file, refuses a staged rename the map lacks until --stage adds it, and
# --check agrees with history; current() follows a chain to its last id, leaves
# an old id a live puzzle holds now to that puzzle, and drops one whose puzzle
# was deleted. Then build_seo_pages.renamed_ids_pages() writes a redirect page
# (canonical + meta refresh, which indexnow.py never sends) for a real row,
# and none for a taken id.
#
#     bash tools/test_renamed_ids.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

R="$tmp/repo"
mkdir -p "$R/tools/data" "$R/puzzles/a/2020"
cp "$here/renamed_ids.py" "$R/tools/"
cd "$R"
git init -q
git config user.email t@example.com
git config user.name test
git config core.hooksPath /dev/null
puzzle() {  # puzzle <path> <id> <clue word>: a puzzle file with enough body to pair
  mkdir -p "$(dirname "$1")"
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
path, pid, word = sys.argv[1:]
entries = [{"number": n, "clue": {"text": f"{word} clue number {n} reads like this"},
            "solution": f"{word.upper()}{n}"} for n in range(1, 30)]
json.dump({"id": pid, "entries": entries}, open(path, "w"), indent=1)
PY
}
for n in 1 2 3 4 5 6; do puzzle "puzzles/a/2020/a-1$n.json" "a-1$n" "other$n"; done
puzzle puzzles/a/2020/a-1.json a-1 alpha
puzzle puzzles/a/2020/b-1.json b-1 beta
echo '{"README": "x"}' > tools/data/renamed_ids.json
git add -A && git commit -qm start

# Every file moves directory and a-1 is renamed a-2 in the same commit.
mkdir -p puzzles/a/2021
for f in puzzles/a/2020/*.json; do git mv "$f" puzzles/a/2021/; done
git mv puzzles/a/2021/a-1.json puzzles/a/2021/a-2.json
sed -i.bak 's/"a-1"/"a-2"/' puzzles/a/2021/a-2.json && rm puzzles/a/2021/a-2.json.bak
git add -A
check "a staged rename the map lacks is refused" 1 "$(python3 tools/renamed_ids.py --check-staged 2>/dev/null; echo $?)"
python3 tools/renamed_ids.py --stage
check "--stage adds it" 0 "$(python3 tools/renamed_ids.py --check-staged; echo $?)"
git commit -qm "move and rename"

git mv puzzles/a/2021/a-2.json puzzles/a/2021/a-3.json   # chain a-1 -> a-2 -> a-3
git mv puzzles/a/2021/b-1.json puzzles/a/2021/b-2.json   # b-1 -> b-2, deleted below
python3 tools/renamed_ids.py --stage
git commit -qm "rename again"
git rm -q puzzles/a/2021/b-2.json
puzzle puzzles/a/2021/a-1.json a-1 gamma                 # a new puzzle takes a-1
git add -A && git commit -qm "drop b-2, file a new a-1"

check "the map is what history says" 0 "$(python3 tools/renamed_ids.py --check; echo $?)"
check "one row per old id" "{'a-1': 'a-2', 'a-2': 'a-3', 'b-1': 'b-2'}" \
  "$(python3 -c 'import sys; sys.path.insert(0, "tools"); import renamed_ids as r; print(r.read())')"
live="$(cd puzzles && find . -name '*.json' | sed 's#.*/##; s#\.json$##' | sort | tr '\n' ' ')"
check "chains resolve; a live old id and a deleted target get nothing" "{'a-2': 'a-3'}" \
  "$(python3 -c 'import sys; sys.path.insert(0, "tools"); import renamed_ids as r; print(r.current(r.read(), set(sys.argv[1].split())))' "$live")"
echo '{"README": "x"}' > tools/data/renamed_ids.json
check "--check catches a missing row" 1 "$(python3 tools/renamed_ids.py --check 2>/dev/null; echo $?)"

# The real map and the page the build writes from it.
cd "$here"
got="$(python3 - <<'PY'
import build_seo_pages as B, indexnow, renamed_ids
rows = renamed_ids.read().items()
print("rows" if rows and all(renamed_ids.PUZZLE_FILE.match(f"puzzles/{a}.json")
                             and renamed_ids.PUZZLE_FILE.match(f"puzzles/{b}.json")
                             for a, b in rows) else "bad rows")
was, now = next((a, b) for a, b in rows if b.startswith("times-"))
stub = {"id": now, "series": "times", "number": int(now.split("-")[1]), "date": "1981-09-17"}
B.renamed_ids.read = lambda: {was: now}
pages = list(B.renamed_ids_pages([stub], set()))
path, text = pages[0]
print(path.parent.name == was, f'href="{B.BASE}/puzzles/{now}/"' in text,
      indexnow.REFRESH in text.encode())
print(len(list(B.renamed_ids_pages([stub], {was}))))
PY
)"
check "every real row is a pair of puzzle ids" rows "$(sed -n 1p <<<"$got")"
check "a page at the old id, canonical to the new, a refresh indexnow skips" "True True True" "$(sed -n 2p <<<"$got")"
check "a taken old id gets no page" 0 "$(sed -n 3p <<<"$got")"

[ "$fails" = 0 ] || { echo "FAILED: $fails"; exit 1; }
echo "all renamed-id checks passed"
