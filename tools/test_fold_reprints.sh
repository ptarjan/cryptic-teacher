#!/bin/bash
# Does fold_reprints.rekeyer rename a folded id both as a whole JSON string and
# as the lead of one ("globeandmail-3334 2-down MOSS"), and leave a longer
# number, a mid-string mention and other series alone?
#
#     bash tools/test_fold_reprints.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import fold_reprints as F

sub = F.rekeyer({"globeandmail-3334": "timesquick-3334"})
cases = (
    ("whole string", '["globeandmail-3334"]', '["timesquick-3334"]'),
    ("object key", '{"globeandmail-3334": 1}', '{"timesquick-3334": 1}'),
    ("leads a string", '"globeandmail-3334 2-down MOSS"', '"timesquick-3334 2-down MOSS"'),
    ("longer number", '"globeandmail-33345"', '"globeandmail-33345"'),
    ("longer number then space", '"globeandmail-33345 1-down X"', '"globeandmail-33345 1-down X"'),
    ("mid-string", '"see globeandmail-3334 2-down"', '"see globeandmail-3334 2-down"'),
    ("other id", '"globeandmail-3335 2-down MOSS"', '"globeandmail-3335 2-down MOSS"'),
)
fails = 0
for what, text, want in cases:
    got = sub(text)
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": expected {want!r}, got {got!r}"))
raise SystemExit(1 if fails else 0)
PY
