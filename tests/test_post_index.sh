#!/bin/bash
# Does a single-puzzle write find its fifteensquared posts without opening every
# cached post (tools/post_index.py), and do its readers (corroborate, blog_post,
# file_georgeho_puzzles.other_setters) find the same posts as a full read?
#
#     bash tests/test_post_index.sh
#
# The write gate (fetch_puzzle.write_puzzle_file -> corroborate) used to read
# all 20k+ posts off the media share whenever one had been added, which took a
# Genius write over twenty minutes. Everything here is a temp cache; nothing
# touches the network or the corpus.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

run() { CT_DOWNLOADS="$TMP/dl" CT_POST_INDEX="$TMP/index" PYTHONPATH="$REPO/tools" python3 -; }

run <<'PY'
import json
import corroborate as c, media_manifest
c.FIFTEENSQUARED_POSTS.mkdir(parents=True)
for i, title in ((1, "Guardian 501 / Tramp"), (2, "Genius 16 by Araucaria"),
                 (3, "Everyman 3348 28 November 2010")):
    post = {"id": i, "title": {"rendered": title}, "link": f"https://www.fifteensquared.net/p{i}/", "content": {"rendered": ""}}
    media_manifest.record_post(c.FIFTEENSQUARED_POSTS, post)
    (c.FIFTEENSQUARED_POSTS / f"{i}.json").write_text(json.dumps(
        {"id": i, "title": {"rendered": title}, "link": f"https://www.fifteensquared.net/p{i}/",
         "content": {"rendered": ""}}))
PY

# A spy on every file opened, then the reader under test.
spy='
import json, pathlib
opened = []
real = pathlib.Path.read_text
def read_text(self, *a, **k):
    opened.append(self.name)
    return real(self, *a, **k)
pathlib.Path.read_text = read_text
import corroborate as c, media_manifest
def ids():
    c._posts.clear()
    return dict(c._fifteensquared_index())
'

out=$(run <<PY
$spy
print("FIRST", ids(), sorted(n for n in opened if n.endswith(".json") and n[0].isdigit()))
PY
)
check "a first read indexes every post off the manifest, opening none" "{'cryptic-501': [1], 'everyman-3348': [3]} []" "$(printf '%s\n' "$out" | sed -n 's/^FIRST //p')"

out=$(run <<PY
$spy
got = ids()
print("SECOND", got, [n for n in opened if n[0].isdigit()])
opened.clear()
c.fifteensquared({"id": "genius-16", "series": "genius", "entries": []})
print("GENIUS", opened)
PY
)
check "a second process opens no post to index" "{'cryptic-501': [1], 'everyman-3348': [3]} []" "$(printf '%s\n' "$out" | sed -n 's/^SECOND //p')"
check "a Genius write reads no index and no post" "[]" "$(printf '%s\n' "$out" | sed -n 's/^GENIUS //p')"

out=$(run <<PY
import json, pathlib, media_manifest
p = pathlib.Path("$TMP/dl/fifteensquared/posts")
post = {"id": 4, "title": {"rendered": "Quiptic 1223 Hoskins"}, "link": "https://www.fifteensquared.net/p4/"}
(p / "4.json").write_text(json.dumps(post))
media_manifest.record_post(p, post)
$spy
import post_index
post_index.forget()
print("TOPPED", ids(), [n for n in opened if n[0].isdigit()])
PY
)
check "a new post joins the index off its manifest row, opening no post" "{'cryptic-501': [1], 'everyman-3348': [3], 'quiptic-1223': [4]} []" "$(printf '%s\n' "$out" | sed -n 's/^TOPPED //p')"

out=$(run <<PY
$spy
import blog_post
blog_post.BLOGS["fifteensquared"] = (c.FIFTEENSQUARED_POSTS.parent, "Fifteensquared")
got = blog_post.cached("quiptic-1223", "fifteensquared", "https://www.fifteensquared.net/p4/")
print("BLOGPOST", got[0]["id"], [n for n in opened if n[0].isdigit()])
PY
)
check "blog_post opens only the post at its url" "4 ['4.json']" "$(printf '%s\n' "$out" | sed -n 's/^BLOGPOST //p')"

out=$(run <<PY
$spy
import pathlib, file_georgeho_puzzles as G
bd = pathlib.Path("$TMP/bd"); bd.mkdir()
import media_manifest
media_manifest.write(media_manifest.posts_name(bd), [])
wanted = [{"series": "cryptic", "number": 501, "link": "https://fifteensquared.net/p1"}]
print("OTHER", G.other_setters(wanted, bd, c.FIFTEENSQUARED_POSTS), [n for n in opened if n[0].isdigit()])
PY
)
check "other_setters names the setter off the index, opening no post" "{('cryptic', 501): 'Tramp'} []" "$(printf '%s\n' "$out" | sed -n 's/^OTHER //p')"

[ "$fails" -eq 0 ] && echo "all ok" || { echo "$fails failed"; exit 1; }
