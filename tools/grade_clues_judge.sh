#!/bin/bash
# Run the blind judges over one round of tools/grade_clues.py packets.
#
#   tools/grade_clues_judge.sh <round-dir> [judges]      e.g. tools/data/grading/runs/<runid>
#
# Each judge is a fresh `claude -p` that sees tools/grade_clues_judge.md, the
# rubric and every packet in the round, and nothing else: no key, no repo. The
# scores land in <round-dir>/scores/judgeN.json, next to the key they belong
# to, with the model and effort recorded in <round-dir>/scores/judges.txt.
# Rounds before September 2026 recorded neither, so their judge model is lost.
# Skips a judge whose score file already parses, so a killed run resumes.
set -u
cd "$(dirname "$0")/.." || exit 1
. tools/claude_path.sh
ROUND=${1:?usage: grade_clues_judge.sh <round-dir> [judges]}
JUDGES=${2:-3}
MODEL=${GRADE_MODEL:-claude-opus-5-5}
EFFORT=${GRADE_EFFORT:-medium}  # explicit: the CLI default differs per model
mkdir -p "$ROUND/scores"
echo "model=$MODEL effort=$EFFORT judges=$JUDGES" > "$ROUND/scores/judges.txt"

judge() {
  local n=$1 out="$ROUND/scores/judge$1.json" raw
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$out" 2>/dev/null; then
    echo "judge$n already scored"; return
  fi
  raw=$(mktemp)
  { cat tools/grade_clues_judge.md tools/data/grading_rubric.md; echo; echo "The packets:"
    for p in "$ROUND"/packets/*.json; do cat "$p"; echo; done; } \
    | claude -p --model "$MODEL" --effort "$EFFORT" > "$raw" 2>"$raw.err"
  # The model is asked for bare JSON but sometimes fences it; take the array.
  if python3 - "$out" "$raw" <<'PY'
import json, re, sys
out, rawfile = sys.argv[1], sys.argv[2]
raw = open(rawfile, encoding="utf-8").read()
m = re.search(r"\[.*\]", raw, re.S)
if not m:
    sys.exit("no JSON array in judge output: " + raw[:300].replace("\n", " "))
rows = json.loads(m.group(0))
open(out, "w", encoding="utf-8").write(json.dumps(rows, indent=1) + "\n")
print("  %s: %d packets scored" % (out, len(rows)))
PY
  then rm -f "$raw" "$raw.err"
  else echo "judge$n failed; raw output kept at $raw, stderr at $raw.err" >&2
  fi
}

for n in $(seq 1 "$JUDGES"); do judge "$n" & done
wait
