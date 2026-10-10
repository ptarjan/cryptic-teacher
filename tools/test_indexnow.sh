#!/bin/bash
# Does a deploy tell IndexNow only what changed? A page whose only difference
# is its ?v= stamps is unchanged, a redirect page is never sent, a cold cache
# sends the recent sitemap rather than the site, and the key file the
# protocol fetches is at the repo root (stage_site ships root *.txt).
#
#     bash tools/test_indexnow.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>&1
import tempfile, pathlib, fnmatch
import indexnow as I, stage_site
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
    print("COLD", cold == [f"{I.BASE}/"])
    print("NOREDIRECT", f"{I.BASE}/puzzles/1/" not in now and f"{I.BASE}/puzzles/x-1/" in now)
    man.write_text(I.json.dumps(now))
    page(".", '<link href="style.css?v=bbb">home')
    page("puzzles/x-1", "two")
    print("CHANGED", I.changed(site, man)[0] == [f"{I.BASE}/puzzles/x-1/"])
key = pathlib.Path(I.ROOT, f"{I.KEY}.txt")
print("KEY", key.read_text().strip() == I.KEY
      and any(fnmatch.fnmatch(key.name, g) for g in stage_site.PUBLISH))
print("UNVERIFIED", I.error_code('{"errorCode":"SiteVerificationNotCompleted"}')
      == "SiteVerificationNotCompleted" and I.error_code("<html>") is None)
PY
)
echo "$out"
for k in COLD NOREDIRECT CHANGED KEY UNVERIFIED; do
  grep -qx "$k True" <<<"$out" || { echo "FAIL: $k"; exit 1; }
done
echo "PASS"
