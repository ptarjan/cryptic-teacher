#!/bin/bash
# Grade every packet tools/favourite_grading.py --sample wrote, one claude -p per
# batch. Skips a batch whose score file already parses, so a killed run resumes
# instead of paying for the work twice.
set -u
cd "$(dirname "$0")/.." || exit 1
. tools/claude_path.sh
DIR=${1:-tools/data/favourite_grading}
MODEL=${GRADE_MODEL:-opus}

for pkt in "$DIR"/packets/*.json; do
  name=$(basename "$pkt" .json)
  out="$DIR/scores/$name.json"
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$out" 2>/dev/null; then
    echo "$name already graded"
    continue
  fi
  echo "grading $name"
  # mktemp, not /tmp/grade_$name.raw: two copies of this script running at once
  # (easy to do by accident) would otherwise share one raw file per batch, and
  # each would parse whichever answer landed last into its own score file.
  raw=$(mktemp)
  { cat tools/favourite_grading_prompt.md; echo; cat "$pkt"; } \
    | claude -p --model "$MODEL" > "$raw" 2>"$raw.err"
  # The model is asked for bare JSON but sometimes fences it; take the array.
  python3 - "$name" "$out" "$raw" <<'PY'
import json, re, sys
name, out, rawfile = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(rawfile, encoding="utf-8").read()
m = re.search(r"\[.*\]", raw, re.S)
if not m:
    sys.exit("no JSON array in %s output: %s" % (name, raw[:200].replace("\n", " ")))
rows = json.loads(m.group(0))
open(out, "w", encoding="utf-8").write(json.dumps(rows, indent=1) + "\n")
print("  %d clues scored" % len(rows))
PY
  rm -f "$raw" "$raw.err"
done
