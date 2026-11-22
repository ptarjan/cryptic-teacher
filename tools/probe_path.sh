#!/usr/bin/env bash
# The git half of pages.yml's "Choose the build path", run in the background
# while the cache restores that precede that step download.
#
#   GH_TOKEN=... REPO=owner/name bash tools/probe_path.sh OUT_DIR
#
# Finds the commit the live site came from, fetches its trees, asks
# tools/ci_scope.py whether only puzzle files moved since, and lists them. All
# of that is the network and the git diff, none of it depends on a cache, and it
# was 23s of the build's critical path (run 44984839816). It writes OUT_DIR/verdict,
# one line, last (so a reader that sees it sees every file):
#
#   fast             only puzzle files moved; OUT_DIR/puzzles.txt lists them
#   code <paths>     tools/ modules or static files moved too (ci_scope --code-ok);
#                    the step then asks the stores whether they fit that code
#   full <why>       anything else: the step takes the full path and says why
#
# The step still decides from the cheap facts only it has (the event, a full
# run asked for, whether both caches were restored) before it reads this, so a
# probe that was not needed is simply not read. Never fails: a probe that could
# not tell says "full".
set -uo pipefail
out=${1:?usage: probe_path.sh OUT_DIR}
mkdir -p "$out"
rm -f "$out/verdict"
say() { echo "$1" > "$out/verdict.tmp"; mv "$out/verdict.tmp" "$out/verdict"; exit 0; }

base=$(python3 tools/last_deploy.py "$REPO") || say "full no successful deploy to diff against"
echo "$base" > "$out/base"
auth=$(printf 'x-access-token:%s' "${GH_TOKEN:-}" | base64 -w0)
GIT_TERMINAL_PROMPT=0 git -c protocol.version=2 -c "http.extraheader=AUTHORIZATION: basic $auth" \
  fetch --no-tags --no-recurse-submodules --depth=1 --filter=blob:none origin "$base" \
  || say "full could not fetch $base"
verdict=$(GIT_TERMINAL_PROMPT=0 python3 tools/ci_scope.py decide --site --code-ok "$base") \
  || say "full could not diff against $base"
case "$verdict" in
  fast | code\ *) ;;
  *) say "full $verdict" ;;
esac
GIT_TERMINAL_PROMPT=0 python3 tools/ci_scope.py files "$base" > "$out/puzzles.txt" \
  || say "full too many puzzles changed since $base"
say "$verdict"
