#!/usr/bin/env python3
"""Fetch Canberra Times crossword articles (OCR text + grid image) from Trove.

Usage:
  python3 tools/fetch_trove.py search 1975                  # list one year's hits
  python3 tools/fetch_trove.py search 1988 --query '"english cryptic"'
  python3 tools/fetch_trove.py fetch 102010719 [ID ...]     # OCR + grid for articles
  python3 tools/fetch_trove.py fetch --year 1975 [--limit N]  # every hit in a listing
  --out DIR     where everything lands (default ~/.cache/trove)
  --delay S     minimum seconds between requests (default 1.0)
  --title N     Trove newspaper title id (default 11, The Canberra Times)
  --grid-width PX  fetch the grid from the smallest pyramid level that is at
                least this wide (default 600, ~40px a cell on a 15x15)

Layout under --out:
  jar.txt                 cookies (the Anubis pass lasts ~7 days)
  index/<year>.jsonl      one search hit per line (id, date, page, title, snippet,
                          query), the union of every query run for that year
  <id>/meta.json          date, page id, article zones (page pixel boxes), grid box
  <id>/ocr.txt            Trove's OCR text, one printed line per line
  <id>/grid.jpg           the grid zone cut from the page scan (see --grid-width)

No account and no API key. Three anonymous mechanisms, all plain HTTP:

- Anubis proof of work. Every path first returns a "Making sure you're not a
  bot" page whose <script id="anubis_challenge"> holds randomData and a
  difficulty d; the answer is the first nonce n where
  sha256(randomData + str(n)) has d leading hex zeros, sent to
  /.within.website/x/cmd/anubis/api/pass-challenge. The cookie it sets is tied
  to the User-Agent and IP, so UA below must never change.
- Search. The SPA calls /api/search/137 with an `apikey` header it derives as
  md5("Wonder" + <x-ctx cookie>) with leading zeros stripped
  (installApikeyInterceptor in /static/js/app.*.js). x-ctx is set by any SPA
  page. Results page with startPos; at most 5000 per query.
- Articles. /newspaper/article/<id> is server-rendered: data-page-id and one
  div.zone per text block with page-pixel x/y/w/h. /newspaper/rendition/
  nla.news-article<id>.txt is the OCR. /newspaper/image/info/<page> gives the
  tile pyramid; tile (col,row) of level L is /imageservice/nla.news-page<page>/
  tile<L>-<col>-<row>, 256px, where page pixel p sits at p*scale + offset.
"""
import argparse
import hashlib
import html
import http.cookiejar
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://trove.nla.gov.au"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
TILE = 256
CHALLENGE_RE = re.compile(
    r'<script id="anubis_challenge"[^>]*>\s*(\{.*?\})\s*</script>', re.DOTALL)


class Trove:
    def __init__(self, out, delay, min_width):
        self.out, self.delay, self.last, self.min_width = out, delay, 0.0, min_width
        os.makedirs(out, exist_ok=True)
        self.jar = http.cookiejar.MozillaCookieJar(os.path.join(out, "jar.txt"))
        if os.path.exists(self.jar.filename):
            self.jar.load(ignore_discard=True, ignore_expires=True)
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [("User-Agent", UA), ("Referer", BASE + "/")]
        self.requests, self.seconds = 0, 0.0

    def _open(self, url, headers):
        wait = self.last + self.delay - time.time()
        if wait > 0:
            time.sleep(wait)
        t = time.time()
        try:
            r = self.op.open(urllib.request.Request(url, headers=headers), timeout=60)
            body, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
        self.last = time.time()
        self.requests += 1
        self.seconds += self.last - t
        return status, body

    def get(self, url, headers=None, ok=(200,)):
        if url.startswith("/"):
            url = BASE + url
        for _ in range(3):
            status, body = self._open(url, headers or {})
            m = CHALLENGE_RE.search(body[:20000].decode("utf-8", "replace"))
            if m:
                self._solve(json.loads(m.group(1)), url)
                continue
            if status not in ok:
                raise RuntimeError(f"HTTP {status} for {url}: {body[:200]!r}")
            return status, body
        raise RuntimeError(f"Anubis challenge kept coming back for {url}")

    def _solve(self, data, url):
        c = data["challenge"]
        prefix, rnd = "0" * c["difficulty"], c["randomData"]
        t, n = time.time(), 0
        while True:
            h = hashlib.sha256(f"{rnd}{n}".encode()).hexdigest()
            if h.startswith(prefix):
                break
            n += 1
        ms = int((time.time() - t) * 1000)
        q = urllib.parse.urlencode({"id": c["id"], "response": h, "nonce": n,
                                    "redir": url, "elapsedTime": ms})
        self._open(f"{BASE}/.within.website/x/cmd/anubis/api/pass-challenge?{q}", {})
        self.jar.save(ignore_discard=True, ignore_expires=True)
        print(f"anubis: solved difficulty {c['difficulty']} in {ms} ms", file=sys.stderr)

    def apikey(self):
        ctx = next((c.value for c in self.jar if c.name == "x-ctx"), None)
        if ctx is None:
            self.get("/search/category/newspapers")
            self.jar.save(ignore_discard=True, ignore_expires=True)
            ctx = next((c.value for c in self.jar if c.name == "x-ctx"), "")
        return hashlib.md5(f"Wonder{ctx}".encode()).hexdigest().lstrip("0")

    def search(self, query, title, year):
        hdr = {"apikey": self.apikey(), "Accept": "application/json"}
        limits = json.dumps({"title": [str(title)], "decade": [str(year)[:3]],
                             "year": [str(year)]})
        hits, start, total = [], 0, None
        while total is None or start < min(total, 5000):
            q = urllib.parse.urlencode({"terms": f"( {query} )", "limits": limits,
                                        "pageSize": 100, "startPos": start})
            _, body = self.get(f"/api/search/137?{q}", hdr)
            j = json.loads(body)
            total = j["totalRecords"]
            works = j.get("works") or []
            if not works:
                break
            for w in works:
                hits.append({"id": w["id"], "date": w.get("date"), "page": w.get("page"),
                             "title": w.get("title"),
                             "snippet": re.sub(r"<[^>]+>", "", " ".join(w.get("snippets") or []))})
            start += len(works)
        return total, hits

    def fetch_article(self, aid):
        d = os.path.join(self.out, str(aid))
        os.makedirs(d, exist_ok=True)
        _, page = self.get(f"/newspaper/article/{aid}")
        text = page.decode("utf-8", "replace")
        zones = [{"page": int(p), "x": int(x), "y": int(y), "w": int(w), "h": int(h)} for p, x, y, w, h in
                 re.findall(r'class="zone onPage[^"]*" data-page-id="(\d+)" data-x="(\d+)" '
                            r'data-y="(\d+)" data-w="(\d+)" data-h="(\d+)"', text)]
        if not zones:
            raise RuntimeError(f"article {aid}: no zones in the article page")
        t = re.search(r"<title>(.*?)</title>", text, re.DOTALL)
        meta = {"id": str(aid), "title": html.unescape(t.group(1).strip()) if t else "",
                "page_id": zones[0]["page"], "zones": zones}
        _, ocr = self.get(f"/newspaper/rendition/nla.news-article{aid}.txt")
        paras = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip()
                 for p in re.findall(r"<p>(.*?)</p>", ocr.decode("utf-8", "replace"), re.DOTALL)]
        with open(os.path.join(d, "ocr.txt"), "w") as f:
            f.write("\n".join(p for p in paras if p) + "\n")
        grid = grid_zone(zones)
        meta["grid"] = grid
        if grid:
            img, level = self.crop(grid["page"], grid)
            img.save(os.path.join(d, "grid.jpg"), quality=92)
            meta["grid_level"], meta["grid_px"] = level, list(img.size)
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump(meta, f, indent=1)
        return meta

    def crop(self, page_id, box, pad=10):
        from PIL import Image
        _, body = self.get(f"/newspaper/image/info/{page_id}")
        levels = ET.fromstring(body).find("levels")
        # The smallest level that still renders the box at least min_width px
        # wide; tiles are most of the requests, so this sets the pace.
        levels = sorted(levels, key=lambda e: float(e.findtext("scale")))
        lv = next((e for e in levels if box["w"] * float(e.findtext("scale")) >= self.min_width),
                  levels[-1])
        level, scale = int(lv.get("id")), float(lv.findtext("scale"))
        xo, yo = int(lv.findtext("xoffset")), int(lv.findtext("yoffset"))
        x1, y1 = (box["x"] - pad) * scale + xo, (box["y"] - pad) * scale + yo
        x2 = (box["x"] + box["w"] + pad) * scale + xo
        y2 = (box["y"] + box["h"] + pad) * scale + yo
        c1, r1, c2, r2 = int(x1) // TILE, int(y1) // TILE, int(x2) // TILE, int(y2) // TILE
        canvas = Image.new("L", ((c2 - c1 + 1) * TILE, (r2 - r1 + 1) * TILE), 255)
        for c in range(c1, c2 + 1):
            for r in range(r1, r2 + 1):
                _, tile = self.get(f"/imageservice/nla.news-page{page_id}/tile{level}-{c}-{r}")
                if tile:
                    canvas.paste(Image.open(io.BytesIO(tile)).convert("L"),
                                 ((c - c1) * TILE, (r - r1) * TILE))
        ox, oy = c1 * TILE, r1 * TILE
        return canvas.crop((int(x1) - ox, int(y1) - oy, int(x2) - ox, int(y2) - oy)), level


def grid_zone(zones):
    """The crossword grid: the largest roughly square zone at least 300px wide."""
    sq = [z for z in zones if z["w"] >= 300 and 0.75 <= z["w"] / z["h"] <= 1.33]
    return max(sq, key=lambda z: z["w"] * z["h"]) if sq else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["search", "fetch"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--query", default='"cryptic crossword"')
    ap.add_argument("--title", default="11")
    ap.add_argument("--year", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--grid-width", type=int, default=600)
    ap.add_argument("--out", default=os.path.expanduser("~/.cache/trove"))
    a = ap.parse_args()
    tv = Trove(a.out, a.delay, a.grid_width)
    t0 = time.time()
    if a.cmd == "search":
        year = a.year or int(a.args[0])
        total, hits = tv.search(a.query, a.title, year)
        os.makedirs(os.path.join(a.out, "index"), exist_ok=True)
        path = os.path.join(a.out, "index", f"{year}.jsonl")
        # A year's index is the union of every query run for it, keyed by id.
        known = {}
        if os.path.exists(path):
            with open(path) as f:
                known = {h["id"]: h for h in map(json.loads, f)}
        new = [h for h in hits if h["id"] not in known]
        for h in new:
            h["query"] = a.query
            known[h["id"]] = h
        with open(path, "w") as f:
            f.writelines(json.dumps(h) + "\n" for h in known.values())
        print(f"{year} {a.query}: {total} hits, {len(new)} new, {len(known)} in {path}")
    else:
        ids = list(a.args)
        if a.year:
            with open(os.path.join(a.out, "index", f"{a.year}.jsonl")) as f:
                ids += [json.loads(line)["id"] for line in f]
        for aid in ids[:a.limit]:
            if os.path.exists(os.path.join(a.out, str(aid), "meta.json")):
                continue
            t = time.time()
            m = tv.fetch_article(aid)
            g = f"grid {m['grid_px'][0]}x{m['grid_px'][1]}" if m.get("grid") else "NO GRID ZONE"
            print(f"{aid} {m['title']}: {len(m['zones'])} zones, {g}, {time.time() - t:.1f}s")
    tv.jar.save(ignore_discard=True, ignore_expires=True)
    print(f"{tv.requests} requests, {tv.seconds:.1f}s in HTTP, {time.time() - t0:.1f}s wall",
          file=sys.stderr)


if __name__ == "__main__":
    main()
