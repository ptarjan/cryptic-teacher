#!/bin/bash
# Run a fetch, then commit and publish every puzzle file it wrote, one commit each.
#
#     tools/publish_fetched.sh <fetch command...>
#
# A fetched puzzle left uncommitted is untracked in this tree, and the moment
# origin commits the same path, `git rebase` refuses to check out over it and
# the burn's sync stalls. So nothing a fetch writes is left uncommitted: each
# path goes in a commit of its own, subject "File <id>" like the filers' and
# annotators' (Paul 10-12: "The archive makes one commit instead of one per
# puzzle"), published with tools/push_puzzle_commit.sh. If origin already holds
# a different copy of one the push is refused, and that commit is undone; the
# tree then holds origin's copy after the next rebase.
#
# Only the paths the command changed are taken, so a puzzle already dirty
# beforehand (a cut-off run's partial annotation) is never published by this.
# The command's own exit status is returned; any refused publish is reported on
# stderr and returns 3.
set -uo pipefail

dirty() { git ls-files -m -o -d --exclude-standard -- puzzles/ | sort -u; }

before=$(dirty)
"$@"
rc=$?
paths=$(comm -13 <(printf '%s\n' "$before") <(dirty) | grep -v '^$')
[ -n "$paths" ] || exit "$rc"

refused=0
while IFS= read -r path; do
  verb=File; git cat-file -e "HEAD:$path" 2>/dev/null && verb=Update
  [ -e "$path" ] || verb=Drop
  id=$(basename "$path" .json)
  git add -A -- "$path" &&
    git commit -q -m "$verb $id" -- "$path" || {
    echo "publish_fetched: could not commit $path" >&2; refused=1; continue; }
  "$(dirname "$0")/push_puzzle_commit.sh" && continue
  # --keep: undo only this commit's file; anything else dirty in the tree stays.
  git reset -q --keep HEAD^
  echo "publish_fetched: origin refused $path; dropped it here, origin's copy arrives with the next rebase" >&2
  refused=1
done <<< "$paths"
[ "$refused" = 0 ] && exit "$rc"
exit 3
