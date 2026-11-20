#!/bin/bash
# lists or restores what tools/puzzle_worker.sh salvaged from a discarded run
#
#     tools/salvaged.sh <id>                      # its salvages, newest last
#     tools/salvaged.sh <id> --restore [<time>]   # the newest, or that one
#
# --restore copies the salvage's _ann_<id>.json and _puzzle_<id>.json back into
# tools/ (refusing to overwrite a live run's) and prints the command that lands
# the hints as the run's own session, where apply_annotations reads their
# author. The puzzle file the run left (puzzle.json) and its fill (fill.json)
# are beside them, to read; a clue whose answer was reopened stays pending.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
SALVAGE_ROOT="${SALVAGE_ROOT:-$HOME/.cache/cryptic-teacher/salvage}"
id="${1:?usage: tools/salvaged.sh <id> [--restore [<time>]]}"
base="$SALVAGE_ROOT/$id"
if [ "${2:-}" != --restore ]; then
  [ -d "$base" ] || { echo "nothing salvaged for $id under $SALVAGE_ROOT"; exit 1; }
  for d in "$base"/*/; do
    echo "$(basename "$d")  $(cd "$d" && ls | tr '\n' ' ')"
  done
  exit 0
fi
if [ -n "${3:-}" ]; then
  dir="$base/$3"
else
  dir=$(find "$base" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1)
fi
[ -n "$dir" ] && [ -s "$dir/_ann_$id.json" ] ||
  { echo "no salvaged tools/_ann_$id.json for $id${3:+ at $3} under $SALVAGE_ROOT"; exit 1; }
for f in "_ann_$id.json" "_puzzle_$id.json"; do
  [ -e "tools/$f" ] && { echo "tools/$f exists (a run may be writing it); move it aside first"; exit 1; }
done
for f in "_ann_$id.json" "_puzzle_$id.json"; do
  [ -s "$dir/$f" ] && cp -p "$dir/$f" "tools/$f"
done
echo "restored tools/_ann_$id.json from $dir"
if [ -s "$dir/session" ]; then
  echo "land it: CLAUDE_CODE_SESSION_ID=$(cat "$dir/session") python3 tools/annotate_check.py $id"
else
  echo "land it: python3 tools/annotate_check.py $id --by <the exact model id that wrote it>"
fi
