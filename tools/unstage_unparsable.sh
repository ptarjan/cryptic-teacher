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

# ct_unstage_refused <tree>: take out of the index each staged puzzle file the
# pre-push would refuse (puzzle_integrity.py --refused: its own checks and the
# corpus-wide DATE, DUPLICATE, NEARDUP), a rename's old path with it, so one
# refused puzzle is held in the tree and named here while the rest commit and
# push, instead of stranding the whole commit. A crash of the check is
# reported and the commit goes ahead: the pre-push still judges it.
ct_unstage_refused() {
  local staged out
  staged=$(git -C "$1" diff --cached --name-status -M --diff-filter=AMR -- 'puzzles/*.json')
  [ -n "$staged" ] || return 0
  if ! out=$(cut -f2- <<<"$staged" | awk -F'\t' '{print $NF}' |
      (cd "$1" && xargs -d '\n' python3 tools/puzzle_integrity.py --refused) 2>&1); then
    echo "puzzle_integrity --refused failed, committing unchecked: $out" >&2
    return 0
  fi
  [ -n "$out" ] || return 0
  cut -f1 <<<"$out" | while IFS= read -r p; do
    awk -F'\t' -v p="$p" '$NF == p { for (i = 2; i <= NF; i++) print $i }' <<<"$staged"
  done | (cd "$1" && xargs -d '\n' git reset -q --)
  echo "held out of the commit, the pre-push would refuse it:" >&2
  printf '  %s\n' "$out" >&2
  # A DATE pair of new files, one placed by a count the other's filed
  # neighbours now contradict: delete that one from the tree and have its
  # edition read again (tools/replace_held_pair.py); never fails the commit.
  if [ -f "$1/tools/replace_held_pair.py" ] && grep -q $'\tDATE \|; DATE ' <<<"$out"; then
    (cd "$1" && python3 tools/replace_held_pair.py . <<<"$out" >/dev/null) || true
  fi
}
