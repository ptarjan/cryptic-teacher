#!/bin/bash
# Run a fetch, then commit and publish every puzzle file it wrote, at once.
#
#     tools/publish_fetched.sh <fetch command...>
#
# A fetched puzzle left uncommitted is untracked in this tree, and the moment
# origin commits the same path, `git rebase` refuses to check out over it and
# the burn's sync stalls. So nothing a fetch writes is left uncommitted: its
# paths go in one commit, published with tools/push_puzzle_commit.sh. If origin
# already holds a different copy of any of them the push is refused, and the
# commit is undone; the tree then holds origin's copy after the next rebase.
#
# Only the paths the command changed are taken, so a puzzle already dirty
# beforehand (a cut-off run's partial annotation) is never published by this.
# The command's own exit status is returned; a refused publish is reported on
# stderr and returns 3.
set -uo pipefail

dirty() { git ls-files -m -o -d --exclude-standard -- puzzles/ | sort -u; }

before=$(dirty)
"$@"
rc=$?
paths=$(comm -13 <(printf '%s\n' "$before") <(dirty) | grep -v '^$')
[ -n "$paths" ] || exit "$rc"

printf '%s\n' "$paths" | git add -A --pathspec-from-file=- &&
  git commit -q -m "archive: fetched $(printf '%s\n' "$paths" | wc -l | tr -d ' ') puzzles" \
    --pathspec-from-file=<(printf '%s\n' "$paths") || {
  echo "publish_fetched: could not commit the fetched puzzles" >&2; exit 3; }

"$(dirname "$0")/push_puzzle_commit.sh" && exit "$rc"
# --keep: undo only this commit's files; anything else dirty in the tree stays.
git reset -q --keep HEAD^
echo "publish_fetched: origin refused the fetched puzzles; dropped them here, origin's copies arrive with the next rebase" >&2
exit 3
