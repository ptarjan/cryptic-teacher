#!/bin/bash
# Does tools/difficulty.py blend() move only the puzzles whose blog comments
# state enough solve times, re-rate a puzzle as its comments arrive, and leave
# a series' mean and spread where the clue index put them?
#
#     bash tools/test_comment_blend.sh
#
# Synthetic rows, so nothing here reads the corpus or the comment cache.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import random
import difficulty as D

rnd = random.Random(1)
idx, com = {}, {}
for i in range(60):
    pid = f"times-{i}"
    idx[pid] = rnd.gauss(0.2, 0.5)
    com[pid] = {"comments": 20, "dnf": rnd.randint(0, 6), "stated_times": 5,
                "median_minutes": rnd.uniform(15, 60)}
for i in range(10):  # a series under COMMENT_SERIES_MIN is never blended
    idx[f"timesjumbo-{i}"] = 0.0
    com[f"timesjumbo-{i}"] = {"comments": 9, "dnf": 1, "stated_times": 4, "median_minutes": 50}
cm = D.comment_moments(idx, com)
print("SERIES", sorted(cm))
b = {p: D.blend(p, x, com, cm) for p, x in idx.items() if p.startswith("times-")}
m = D.moments(list(b.values()))
o = D.moments([idx[p] for p in b])
print("MEAN", abs(m["mean"] - o["mean"]) < 1e-4, "SD", abs(m["sd"] - o["sd"]) < 1e-4)
few = dict(com["times-0"], stated_times=D.COMMENT_MIN_TIMES - 1)
print("FEW", D.blend("times-0", idx["times-0"], {"times-0": few}, cm))
print("NONE", D.blend("times-0", idx["times-0"], {}, cm))
slow = dict(com["times-0"], median_minutes=120)
print("SLOWER", D.blend("times-0", idx["times-0"], {"times-0": slow}, cm) > b["times-0"])
PY
)
fails=0
check() {  # check <what> <expected>
  if grep -qxF "$2" <<<"$out"; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2] in:"; echo "$out"; fails=$((fails + 1)); fi
}
check "a series needs COMMENT_SERIES_MIN puzzles" "SERIES ['times']"
check "the blend keeps the series' mean and spread" "MEAN True SD True"
check "too few stated times leaves the clue index" "FEW None"
check "no comments leaves the clue index" "NONE None"
check "slower stated times rate the puzzle harder" "SLOWER True"
[ "$fails" -eq 0 ]
