#!/bin/bash
# Does apply_annotations find who wrote the hints when the model never ran it?
#
#     bash tools/test_session_model.sh
#
# tools/puzzle_worker.sh runs annotate_check itself after a cold solve, so a
# transcript may hold only the call that wrote tools/_ann_<id>.json. That call
# is the evidence of authorship, and only for the puzzle it names.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
check() { if [ "$1" = "$2" ]; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    wanted: $2"$'\n'"    got: $1"; fails=$((fails + 1)); fi; }

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
sid=00000000-beef-0000-0000-000000000000
mkdir -p "$work/projects/test"
printf '{"type":"assistant","timestamp":"2026-09-12T12:00:00Z","message":{"model":"claude-opus-5-5","content":[{"type":"tool_use","name":"Write","input":{"file_path":"/x/tools/_ann_nation-3441.json","content":"{}"}}]}}\n' \
  > "$work/projects/test/$sid.jsonl"
ask() { CLAUDE_CONFIG_DIR="$work" python3 -c "
import sys; sys.path.insert(0, 'tools')
import apply_annotations as a
print(a.session_model('$sid', '$1'))"; }

echo "a transcript that only wrote the annotations file"
check "$(ask nation-3441)" "claude-opus-5-5" "names the model for that puzzle"
check "$(ask nation-3442)" "None" "says nothing for another puzzle"

[ "$fails" = 0 ] || exit 1
