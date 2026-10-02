#!/bin/bash
# Does any series' page say the same word twice running ("Listener Listener")?
# The Listener is its own publisher and kind, so joining the two doubled it.
# Renders a crawlable page for every series in tools/series.py and refuses a
# repeated adjacent word in the title, heading, description or series name.
#
#     bash tools/test_no_doubled_paper.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHONPATH="$REPO/tools" python3 - <<'PY'
import re, sys
import series as S
import build_seo_pages as B

def doubled(text):
    m = re.search(r"\b([A-Za-z]+) \1\b", re.sub(r"<[^>]+>", " ", text), re.I)
    return m.group(0) if m else None

bad, n = [], 0
for key in S.SERIES:
    if S.is_book(key):
        continue
    puz = {"id": f"{key}-7", "series": key, "number": 7, "setter": None,
           "date": "2025-01-01", "name": "x", "entries": [], "dimensions": {"cols": 15, "rows": 15}}
    page = B.puzzle_page(puz, None, None, None)
    parts = re.findall(r"<title>(.*?)</title>|<h1>(.*?)</h1>|"
                       r'name="description" content="([^"]*)"', page)
    texts = [t for tup in parts for t in tup if t]
    texts += [B.named(puz), B.series_name(key)]
    n += 1
    for t in texts:
        if (d := doubled(t)):
            bad.append(f"{key}: {d!r} in {t!r}")
if n < 15:
    bad.append(f"only {n} series rendered")
if "Listener Listener" in B.named({"series": "listener", "number": 7}):
    bad.append("listener named twice")
print("\n".join(bad) or "ok")
sys.exit(1 if bad else 0)
PY
rc=$?
[ $rc -eq 0 ] && echo PASS || { echo "FAIL"; exit 1; }
