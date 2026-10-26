#!/usr/bin/env python3
# Does a deploy tell IndexNow only what changed? A page whose only difference
# is its ?v= stamps is unchanged, a redirect page is never sent, a cold cache
# sends the recent sitemap rather than the site, and the key file the
# protocol fetches is at the repo root (stage_site ships root *.txt).
#
#     python3 tests/test_indexnow.py
import fnmatch
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import indexnow as I
import stage_site

results = {}
with tempfile.TemporaryDirectory() as tmp:
    site, man = pathlib.Path(tmp, "s"), pathlib.Path(tmp, "m.json")

    def page(rel, text):
        p = site / rel / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    page(".", '<link href="style.css?v=aaa">home')
    page("puzzles/x-1", "one")
    page("puzzles/1", '<meta http-equiv="refresh" content="0; url=/puzzles/x-1/">')
    (site / "sitemap-recent.xml").write_text(f"<loc>{I.BASE}/</loc><loc>{I.BASE}/nope/</loc>")
    cold, now = I.changed(site, man)
    results["COLD"] = cold == [f"{I.BASE}/"]
    results["NOREDIRECT"] = f"{I.BASE}/puzzles/1/" not in now and f"{I.BASE}/puzzles/x-1/" in now
    man.write_text(I.json.dumps(now))
    page(".", '<link href="style.css?v=bbb">home')
    page("puzzles/x-1", "two")
    results["CHANGED"] = I.changed(site, man)[0] == [f"{I.BASE}/puzzles/x-1/"]
key = pathlib.Path(I.ROOT, f"{I.KEY}.txt")
results["KEY"] = (key.read_text().strip() == I.KEY
                  and any(fnmatch.fnmatch(key.name, g) for g in stage_site.PUBLISH))
results["UNVERIFIED"] = (I.error_code('{"errorCode":"SiteVerificationNotCompleted"}')
                         == "SiteVerificationNotCompleted" and I.error_code("<html>") is None)

for k, v in results.items():
    print(k, v)
for k in ("COLD", "NOREDIRECT", "CHANGED", "KEY", "UNVERIFIED"):
    if results[k] is not True:
        print(f"FAIL: {k}")
        sys.exit(1)
print("PASS")
