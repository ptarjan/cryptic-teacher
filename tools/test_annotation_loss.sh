#!/bin/bash
# Does the annotation loss check fail on a blank the model could not solve, and
# pass a blank that was reopened and solved twice with no parse?
#
#     bash tools/test_annotation_loss.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
fails=0
p=$(cd "$REPO" && python3 tools/puzzle_paths.py nation-3401)
python3 - "$REPO/$p" "$scratch" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
d["solutions"]["reopened"] = {"6-across": "CACTI"}
for e in d["entries"]:
    if f"{e['number']}-{e['direction']}" == "6-across":
        e["annotation"] = None
json.dump(d, open(f"{sys.argv[2]}/retried.json", "w"))
d["solutions"]["reopened"] = {}
json.dump(d, open(f"{sys.argv[2]}/blank.json", "w"))
PY
cd "$REPO" || exit 1
if python3 tools/check_annotation_loss.py "$scratch/retried.json" >/dev/null; then echo "ok   a reopened blank passes"
else echo "FAIL a blank solved twice with no parse fails the loss check"; fails=$((fails + 1)); fi
if python3 tools/check_annotation_loss.py "$scratch/blank.json" >/dev/null; then
  echo "FAIL a blank never reopened passes the loss check"; fails=$((fails + 1))
else echo "ok   a blank never reopened fails"; fi
exit $((fails > 0))
