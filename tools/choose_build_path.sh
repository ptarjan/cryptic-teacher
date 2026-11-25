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
# The probe's verdict only says what moved since the live commit. That
# is not what makes the build cheap: the stores are. They are saved
# only after a big re-render, so they can be older than the live commit
# and keyed on code that moved in between: the diff can be one puzzle
# while a template change sits between the stores and the live commit,
# and every page then renders in one step. So the stores are asked
# every time (cache_warmth.py: their rows and page fingerprint against
# this checkout's code), whatever moved, and only a cold one sends the
# build down the full path with its nine shards. A renumbered puzzle or
# a workflow edit does not, since the shards would spend ~27s each
# loading stores that fit.
why=""
case "$verdict" in
  fast) ;;
  code\ *) why="tools/ modules moved since $base: ${verdict#code }" ;;
  full\ *) why="${verdict#full }" ;;
  *) why="$verdict" ;;
esac
[ -z "$why" ] || echo "not a plain puzzle push: $why"
# seo-pages-<page fingerprint>-<sha>; an older key carries none.
fp=$(printf '%s' "$PAGEKEY" | sed -nE 's/^seo-pages-([0-9a-f]{64})-[0-9a-f]{40}$/\1/p')
warmth=$(python3 tools/cache_warmth.py "$fp")
[ "$warmth" = warm ] || full "${why:-only puzzle files moved}, and the stores are $warmth"
echo "the row and page stores fit this code"
echo "puzzle fast path: $(wc -l < "$RUNNER_TEMP/probe/puzzles.txt" 2>/dev/null || echo 0) puzzle file(s) since ${base:-?}"
echo "fast=true" >> "$GITHUB_OUTPUT"
