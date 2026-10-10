#!/bin/bash
# Does tools/trove_solution_ocr.py's _articles keep what it read in a file,
# reread only an article whose files changed, and return the same list warm?
#
#     bash tools/test_trove_articles_index.sh
#
# Runs in a temp HOME and a temp article folder; nothing real is read.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export PYTHONUSERBASE="$(python3 -m site --user-base)"
export HOME="$T/home"; mkdir -p "$HOME"
python3 - "$REPO/tools" "$T/trove" <<'PY'
import sys, json, os
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import trove_solution_ocr as t

cache = Path(sys.argv[2])
def make(name, title, ocr, grid=True):
    d = cache / name; d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"title": title}))
    (d / "ocr.txt").write_text(ocr)
    if grid: (d / "grid.jpg").write_bytes(b"x")
make("1", "Crossword - Trove", "Monday 5 June 1972\nclues")
make("2", "SOLUTION - Trove", "Tuesday 6 June 1972\nx")
make("3", "Crossword - Trove", "no day here")
make("4", "Crossword - Trove", "Monday 5 June 1972", grid=False)
def run():
    t._ARTICLES.clear()
    return [(str(d), n, s) for d, n, s in ((a, b.name, c) for a, b, c in t._articles(cache))]
cold = run()
assert [r[1:] for r in cold] == [("1", False), ("2", True)], cold
assert run() == cold
idx = json.loads(t._articles_index_path(cache).read_text())
assert sorted(idx) == ["1", "2", "3"], idx
reads = []
real = t._read_article
t._read_article = lambda d: (reads.append(d.name), real(d))[1]
run()
assert reads == [], reads
(cache / "3" / "ocr.txt").write_text("Friday 9 June 1972\n")
os.utime(cache / "3" / "ocr.txt", ns=(1, 1))
warm = run()
assert reads == ["3"] and [r[1] for r in warm] == ["1", "2", "3"], (reads, warm)
print("ok   articles index")
PY
