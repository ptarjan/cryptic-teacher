#!/usr/bin/env bash
# The deploy's caches of files that live directly in puzzles/, carried as one
# tar file each instead of an actions/cache glob over puzzles/.
#
#   bash tools/cache_tar.sh pack pages|shims TAR   # before Save the ...
#   bash tools/cache_tar.sh unpack TAR             # after Restore the ...
#
# Why: @actions/glob lists a directory with stack.push(...entries), one
# argument per entry, and a listing past ~120k entries overflows V8's stack.
# puzzles/ holds a page directory, a .js shim and a .js.gz per puzzle (~140k
# entries since the gzipped shims, commit 7d1b0bb398), so both caches' saves
# failed with "Maximum call stack size exceeded" and the next run started
# cold: every puzzle page rendered again (runs 38498612588, 38499371632).
# find lists the directory instead; the cache's path is just TAR.
# tools/step_budgets.py lint refuses a cache path that globs puzzles/ again.
set -euo pipefail
cd "${CACHE_TAR_ROOT:-$(dirname "$0")/..}"  # CACHE_TAR_ROOT: tools/test_cache_tar.sh
case "${1:-}" in
  pack)
    [ $# -eq 3 ] || { echo "usage: $0 pack pages|shims TAR" >&2; exit 2; }
    case "$2" in
      pages)  # every page puzzles/<dir>/index.html and the page cache's keys
        list() {
          find puzzles -mindepth 2 -maxdepth 2 -name index.html -type f -print0
          [ -f .page-cache.pickle ] && printf '%s\0' .page-cache.pickle
          return 0
        } ;;
      shims)  # the puzzle shims, their gzipped copies and that manifest
        list() {
          find puzzles -maxdepth 1 -type f \( -name '*.js' -o -name '*.js.gz' \
            -o -name shims.gz.json \) -print0
        } ;;
      *) echo "$0: pack what? pages or shims, not '$2'" >&2; exit 2 ;;
    esac
    tmp="$3.$$.tmp"
    list | tar --null -cf "$tmp" -T -
    mv "$tmp" "$3"
    echo "cache_tar: $(tar -tf "$3" | wc -l) file(s) in $3, $(( $(stat -c %s "$3") / 1000000 ))MB"
    ;;
  unpack)
    [ $# -eq 2 ] || { echo "usage: $0 unpack TAR" >&2; exit 2; }
    if [ ! -f "$2" ]; then
      echo "cache_tar: no $2 (a cold cache)"; exit 0
    fi
    n=$(tar -xvf "$2" | wc -l)
    rm -f "$2"   # not shipped, and ~200MB of disk
    echo "cache_tar: $n file(s) from $2"
    ;;
  *) echo "usage: $0 pack pages|shims TAR | unpack TAR" >&2; exit 2 ;;
esac
