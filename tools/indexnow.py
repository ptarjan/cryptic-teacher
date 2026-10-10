#!/usr/bin/env python3
"""Tell IndexNow (Bing, Yandex, Seznam, Naver; Bing feeds DuckDuckGo, Ecosia
and ChatGPT search) which pages a deploy changed.

    python3 tools/indexnow.py changed _site MANIFEST URLS   # in the build
    python3 tools/indexnow.py ping URLS                     # after the deploy

`changed` hashes every staged page and writes the URLs whose hash differs from
MANIFEST (carried between runs by the Actions cache), then rewrites MANIFEST.
The ?v= asset stamps are stripped before hashing: they move on every app.js or
style.css edit and say nothing about the page. With no MANIFEST (a cold cache)
it writes sitemap-recent.xml's URLs instead of the whole site. A redirect page
is not content and is never sent.

`ping` posts them, at most BATCH per request (the protocol's limit is 10,000).
The key is public by design: it proves we own the host because it is served at
KEY_URL, from the KEY.txt at the repo root.
"""
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "cryptic.paultarjan.com"
BASE = f"https://{HOST}"
KEY = "f95c3e3037390dda228633f7d76588f2"
KEY_URL = f"{BASE}/{KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10000
STAMP = re.compile(rb"\?v=[0-9A-Za-z_-]+")
REFRESH = b'http-equiv="refresh"'


def page_url(site, page):
    rel = page.parent.relative_to(site).as_posix()
    return f"{BASE}/" if rel == "." else f"{BASE}/{rel}/"


def hashes(site):
    out = {}
    for page in sorted(site.rglob("index.html")):
        text = page.read_bytes()
        if REFRESH in text:
            continue
        out[page_url(site, page)] = hashlib.sha256(STAMP.sub(b"", text)).hexdigest()
    return out


def changed(site, manifest):
    """(urls to send, new manifest)."""
    now = hashes(site)
    if not manifest.exists():
        recent = (site / "sitemap-recent.xml").read_text(encoding="utf-8")
        return [u for u in re.findall(r"<loc>(.*?)</loc>", recent) if u in now], now
    before = json.loads(manifest.read_text(encoding="utf-8"))
    return [u for u, h in now.items() if before.get(u) != h], now


def ping(urls):
    for i in range(0, len(urls), BATCH):
        body = json.dumps({"host": HOST, "key": KEY, "keyLocation": KEY_URL,
                           "urlList": urls[i:i + BATCH]}).encode()
        req = urllib.request.Request(
            ENDPOINT, data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8",
                     "User-Agent": "cryptic-teacher-deploy"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"IndexNow: {r.status} for {len(urls[i:i + BATCH])} URL(s)")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"IndexNow refused {len(urls[i:i + BATCH])} URL(s): HTTP {e.code} "
                             f"{e.read().decode(errors='replace')[:500]}")


def main(argv):
    key_file = ROOT / f"{KEY}.txt"
    if not key_file.exists() or key_file.read_text().strip() != KEY:
        raise SystemExit(f"{key_file.name} must exist at the repo root holding {KEY}: "
                         "IndexNow fetches it from the site to check the key")
    if argv[:1] == ["changed"] and len(argv) == 4:
        site, manifest, out = map(Path, argv[1:])
        urls, now = changed(site, manifest)
        out.write_text("".join(u + "\n" for u in urls), encoding="utf-8")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(now, sort_keys=True), encoding="utf-8")
        print(f"{len(urls)} changed page(s) of {len(now)}")
        return 0
    if argv[:1] == ["ping"] and len(argv) == 2:
        urls = Path(argv[1]).read_text(encoding="utf-8").split()
        if urls:
            ping(urls)
        else:
            print("IndexNow: nothing changed")
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
