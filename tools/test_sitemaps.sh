#!/bin/bash
# Do new puzzles get found fast? /sitemap.xml must be a sitemap index (the URL
# Search Console holds) over a small sitemap-recent.xml, carrying the last
# RECENT_DAYS of puzzles and every page that changes daily, and the archive
# parts holding the rest, each puzzle in exactly one. The homepage and /puzzles/
# link each paper's newest puzzle, one per paper, leaving out a back archive;
# and a puzzle page pages Newer/Older within its own series and links the
# series' landing page.
#
#     bash tools/test_sitemaps.sh
#
# A synthetic index, so nothing here reads the corpus or writes to the tree.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>&1
import re
from datetime import date, timedelta
import build_seo_pages as B

top = date(2026, 9, 30)
ps = []
for i in range(120):          # a Guardian cryptic a day, newest first
    ps.append({"series": "cryptic", "number": 30200 - i, "id": f"cryptic-{30200 - i}",
               "date": (top - timedelta(days=i)).isoformat(), "hasSolutions": True,
               "setter": "Brummie"})
for i in range(5):            # a back archive: 1972
    ps.append({"series": "canberra", "number": 720630 - i, "id": f"canberra-{720630 - i}",
               "date": f"1972-06-{30 - i:02d}", "hasSolutions": True})
ps.append({"series": "everyman", "number": 4171, "id": "everyman-4171",
           "date": (top - timedelta(days=3)).isoformat(), "hasSolutions": True})
ps.sort(key=lambda p: p["date"], reverse=True)
idx = {"puzzles": ps}

files = {p.name: t for p, t in B.sitemaps(idx)}
index = files["sitemap.xml"]
print("INDEX", "<sitemapindex" in index and "<urlset" not in index
      and all(f"{B.BASE}/{n}</loc>" in index for n in files if n != "sitemap.xml"))
locs = {n: re.findall(r"<loc>(.*?)</loc>", t) for n, t in files.items() if n != "sitemap.xml"}
recent = locs.pop("sitemap-recent.xml")
archive = [u for us in locs.values() for u in us]
pages = [f"{B.BASE}/puzzles/{p['id']}/" for p in ps]
print("ONCE", sorted(u for u in recent + archive if "/puzzles/" in u and "/series/" not in u
                     and not u.endswith("/puzzles/")) == sorted(pages))
cut = top - timedelta(days=B.RECENT_DAYS)
print("SPLIT", all((f"{B.BASE}/puzzles/{p['id']}/" in recent) == (date.fromisoformat(p["date"]) >= cut)
                   for p in ps) and len(archive) > 0)
print("DAILY", f"{B.BASE}/puzzles/series/cryptic/" in recent and f"{B.BASE}/" in recent)

latest = B.latest_by_series(idx)
print("LATEST", [p["id"] for p in latest] == ["cryptic-30200", "everyman-4171"])
html = B.latest_list(idx)
print("LINKS", f'{B.BASE}/puzzles/cryptic-30200/' in html and "/series/everyman/" in html
      and "canberra" not in html)
print("HOME", html in B.homepage_nav(idx) and html in B.hub_page(idx))

stubs = ps
nb = dict(zip([p["id"] for p in stubs], B.series_neighbours(stubs)))
newer, older = nb["cryptic-30199"]
print("PAGER", newer["id"] == "cryptic-30200" and older["id"] == "cryptic-30198"
      and nb["everyman-4171"] == (None, None))
puz = {**ps[1], "name": "x", "entries": [], "dimensions": {"cols": 15, "rows": 15}}
page = B.puzzle_page(puz, ps[1], newer, older)
print("PAGERHTML", 'rel="prev"' in page and 'rel="next"' in page
      and f'{B.BASE}/puzzles/series/cryptic/">All Guardian Cryptic puzzles' in page)
PY
)
echo "$out"
for k in INDEX ONCE SPLIT DAILY LATEST LINKS HOME PAGER PAGERHTML; do
  echo "$out" | grep -qx "$k True" || { echo "FAIL: $k"; exit 1; }
done
echo "PASS"
