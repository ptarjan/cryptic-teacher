#!/usr/bin/env bash
# tools/cache_tar.sh round trip on a small tree: pack takes exactly the files
# each deploy cache carried as a glob (puzzles/*/index.html and the page
# store; puzzles/*.js, *.js.gz, shims.gz.json) with their mtimes, unpack puts
# them back and removes the tar, and a missing tar is a cold cache, not an error.
set -euo pipefail
cd "$(dirname "$0")/.."
tool=$PWD/tools/cache_tar.sh
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export CACHE_TAR_ROOT=$tmp/a
mkdir -p "$tmp/a/puzzles/times-1" "$tmp/a/puzzles/cryptic/2020" "$tmp/a/puzzles/times-2"
echo one > "$tmp/a/puzzles/times-1/index.html"
echo two > "$tmp/a/puzzles/times-2/index.html"
echo hub > "$tmp/a/puzzles/cryptic/index.html"
echo '{}' > "$tmp/a/puzzles/cryptic/2020/x.json"      # a puzzle file: in neither
echo deep > "$tmp/a/puzzles/cryptic/2020/index.html"  # too deep for */index.html
echo store > "$tmp/a/.page-cache.pickle"
echo shim > "$tmp/a/puzzles/times-1.js"
echo gz > "$tmp/a/puzzles/times-1.js.gz"
echo '{}' > "$tmp/a/puzzles/shims.gz.json"
echo '{}' > "$tmp/a/puzzles/index.json"               # not a shim
touch -d 2020-01-02 "$tmp/a/puzzles/times-1.js.gz"
fail() { echo "test_cache_tar: $*" >&2; exit 1; }
listed() { tar -tf "$1" | sort | tr '\n' ' '; }

bash "$tool" pack pages "$tmp/pages.tar" >/dev/null
[ "$(listed "$tmp/pages.tar")" = ".page-cache.pickle puzzles/cryptic/index.html puzzles/times-1/index.html puzzles/times-2/index.html " ] \
  || fail "pages packed: $(listed "$tmp/pages.tar")"
bash "$tool" pack shims "$tmp/shims.tar" >/dev/null
[ "$(listed "$tmp/shims.tar")" = "puzzles/shims.gz.json puzzles/times-1.js puzzles/times-1.js.gz " ] \
  || fail "shims packed: $(listed "$tmp/shims.tar")"

# Unpack into a fresh checkout: the files come back, mtimes kept, tar gone.
export CACHE_TAR_ROOT=$tmp/b
mkdir -p "$tmp/b/puzzles"
cp "$tmp/pages.tar" "$tmp/b/.page-cache.tar"
cp "$tmp/shims.tar" "$tmp/b/.shim-cache.tar"
bash "$tool" unpack .page-cache.tar | grep "4 file(s)" >/dev/null || fail "unpack pages count"
bash "$tool" unpack .shim-cache.tar | grep "3 file(s)" >/dev/null || fail "unpack shims count"
[ ! -e "$tmp/b/.page-cache.tar" ] && [ ! -e "$tmp/b/.shim-cache.tar" ] || fail "tar left behind"
cmp -s "$tmp/a/puzzles/times-2/index.html" "$tmp/b/puzzles/times-2/index.html" || fail "page differs"
cmp -s "$tmp/a/.page-cache.pickle" "$tmp/b/.page-cache.pickle" || fail "store differs"
[ "$(stat -c %Y "$tmp/b/puzzles/times-1.js.gz")" = "$(stat -c %Y "$tmp/a/puzzles/times-1.js.gz")" ] \
  || fail "mtime lost"

# A cold cache: nothing restored is not an error.
bash "$tool" unpack .page-cache.tar | grep cold >/dev/null || fail "missing tar"
# No page store yet (a first build) still packs the pages.
rm "$tmp/a/.page-cache.pickle"
CACHE_TAR_ROOT=$tmp/a bash "$tool" pack pages "$tmp/p2.tar" >/dev/null
[ "$(tar -tf "$tmp/p2.tar" | wc -l)" = 3 ] || fail "pack without a store"
echo "test_cache_tar: all passed"
