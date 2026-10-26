#!/usr/bin/env python3
# Do new puzzles get found fast? /sitemap.xml must be a sitemap index (the URL
# Search Console holds) over a small sitemap-recent.xml, carrying the last
# RECENT_DAYS of puzzles and every page that changes daily, and the archive
# parts holding the rest, each puzzle in exactly one. The homepage links every
# series page and each printing paper's newest puzzle; /puzzles/ links no puzzle;
# and a puzzle page pages Newer/Older within its own series and links the
# series' landing page.
#
#     python3 tests/test_sitemaps.py
#
# A synthetic index, so nothing here reads the corpus or writes to the tree.
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_seo_pages as B

results = {}
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
results["INDEX"] = ("<sitemapindex" in index and "<urlset" not in index
                    and all(f"{B.BASE}/{n}</loc>" in index for n in files if n != "sitemap.xml"))
locs = {n: re.findall(r"<loc>(.*?)</loc>", t) for n, t in files.items() if n != "sitemap.xml"}
recent = locs.pop("sitemap-recent.xml")
archive = [u for us in locs.values() for u in us]
pages = [f"{B.BASE}/puzzles/{p['id']}/" for p in ps]
results["ONCE"] = (sorted(u for u in recent + archive if "/puzzles/" in u and "/series/" not in u
                          and not u.endswith("/puzzles/")) == sorted(pages))
cut = top - timedelta(days=B.RECENT_DAYS)
results["SPLIT"] = (all((f"{B.BASE}/puzzles/{p['id']}/" in recent) == (date.fromisoformat(p["date"]) >= cut)
                        for p in ps) and len(archive) > 0)
results["DAILY"] = f"{B.BASE}/puzzles/series/cryptic/" in recent and f"{B.BASE}/" in recent

home, hub = B.homepage_nav(idx, top), B.hub_page(idx)
answers = lambda page: {p["id"] for p in ps if f"{B.BASE}/puzzles/{p['id']}/" in page}
results["NOPICKS"] = answers(hub) == set()
# The homepage links each printing paper's newest puzzle (solver first, then
# its answer page) and every series page; a back archive is a series link only.
results["LATEST"] = (answers(home) == {"cryptic-30200", "everyman-4171"}
                     and f'{B.BASE}/?p=cryptic-30200">' in home
                     and all(f'{B.BASE}/puzzles/series/{s}/"' in home for s in ("cryptic", "everyman", "canberra"))
                     and "canberra-720630" not in home)

stubs = ps
nb = dict(zip([p["id"] for p in stubs], B.series_neighbours(stubs)))
newer, older = nb["cryptic-30199"]
results["PAGER"] = (newer["id"] == "cryptic-30200" and older["id"] == "cryptic-30198"
                    and nb["everyman-4171"] == (None, None))
puz = {**ps[1], "name": "x", "entries": [], "dimensions": {"cols": 15, "rows": 15}}
page = B.puzzle_page(puz, ps[1], newer, older)
results["PAGERHTML"] = ('rel="prev"' in page and 'rel="next"' in page
                        and f'{B.BASE}/puzzles/series/cryptic/">All Guardian Cryptic puzzles' in page)

for k, v in results.items():
    print(k, v)
for k in ("INDEX", "ONCE", "SPLIT", "DAILY", "NOPICKS", "LATEST", "PAGER", "PAGERHTML"):
    if results[k] is not True:
        print(f"FAIL: {k}")
        sys.exit(1)
print("PASS")
