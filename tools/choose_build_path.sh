#!/usr/bin/env bash
# pages.yml's "Choose the build path": decide whether this build takes the puzzle fast
# path or the full one, and write `fast=true|false` to $GITHUB_OUTPUT.
#
#   EVENT=push FULL=false CACHED=true PAGEKEY=... bash tools/choose_build_path.sh
#
# EVENT is the triggering event, FULL whether a full run was asked for, CACHED whether
# both the row and page stores were restored, PAGEKEY the page store's key. What each
# answer of the background probe (tools/probe_path.sh, started by "Start the build path
# probe" and collected here through tools/bg_job.sh) means is in that script; the
# reasoning for the fast path is in pages.yml above the step.
set -uo pipefail
full() { echo "full build: $1"; echo "fast=false" >> "$GITHUB_OUTPUT"; exit 0; }
# A push (puzzle-only pushes included) or a dispatch. Only the daily
# tick (or full=true) and a cold cache take the full path by choice.
case "$EVENT" in
  push) ;;
  workflow_dispatch|schedule) [ "$FULL" != true ] || full "a full run was asked for" ;;
  *) full "a $EVENT run" ;;
esac
[ "$CACHED" = true ] || full "no restored row or page cache"
# The live site's commit, its blobless fetch and the diff against it
# were made while the caches downloaded (Start the build path probe,
# tools/probe_path.sh, which says what each answer means). One call
# to the deployments finds the commit, whatever event deployed it.
bash tools/bg_job.sh wait probe || full "the build path probe died"
verdict=$(cat "$RUNNER_TEMP/probe/verdict" 2>/dev/null) || full "the build path probe left no verdict"
base=$(cat "$RUNNER_TEMP/probe/base" 2>/dev/null || true)
# The probe's verdict only says what moved since the live commit.
# What makes the slices and shards worth running is a cold store,
# and the stores say that themselves (cache_warmth.py), whatever
# moved: a renumbered puzzle (a deleted file plus an added one) or a
# workflow edit does not send a build down the full path, whose nine
# shard steps each spend ~27s loading the stores to reuse nearly
# every page. Only the plain puzzle push skips
# the check, since nothing the stores are keyed on moved.
why=""
case "$verdict" in
  fast) ;;
  code\ *) why="tools/ modules moved since $base: ${verdict#code }" ;;
  full\ *) why="${verdict#full }" ;;
  *) why="$verdict" ;;
esac
if [ -n "$why" ]; then
  echo "not a plain puzzle push: $why"
  # seo-pages-<page fingerprint>-<sha>; an older key carries none.
  fp=$(printf '%s' "$PAGEKEY" | sed -nE 's/^seo-pages-([0-9a-f]{64})-[0-9a-f]{40}$/\1/p')
  warmth=$(python3 tools/cache_warmth.py "$fp")
  [ "$warmth" = warm ] || full "$why, and the stores are $warmth"
  echo "the row and page stores fit this code"
fi
echo "puzzle fast path: $(wc -l < "$RUNNER_TEMP/probe/puzzles.txt" 2>/dev/null || echo 0) puzzle file(s) since ${base:-?}"
echo "fast=true" >> "$GITHUB_OUTPUT"
