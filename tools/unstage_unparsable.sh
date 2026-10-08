#!/bin/bash
# Sourced by tools/durable.sh and tools/nightly_worktree.sh, the two that
# commit what a job filed.
#
# ct_unstage_unparsable <tree>: take out of the index each staged .json that
# does not parse (a write cut off by a kill), so no commit carries one.
ct_unstage_unparsable() {
  local bad
  bad=$(git -C "$1" diff --cached --name-only --diff-filter=AM -- '*.json' |
    (cd "$1" && python3 -c 'import json, sys
for p in sys.stdin.read().split("\n"):
    if p:
        try:
            json.load(open(p))
        except (OSError, ValueError):
            print(p)'))
  [ -n "$bad" ] || return 0
  printf '%s\n' "$bad" | (cd "$1" && xargs -d '\n' git reset -q --)
  echo "left out of the commit, not parsable: $(printf '%s\n' "$bad" | tr '\n' ' ')" >&2
}
