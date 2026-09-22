#!/usr/bin/env python3
"""Cache timesforthetimes.co.uk blog posts, so we fetch each one once.

The Times publishes no puzzle archive we can read, but this blog has solved
every one of them in public since 2007 and its WordPress REST API hands the
whole archive over in tens of requests. What a post carries is the reason to
want it:

  * the clue NUMBER, under an Across/Down heading, in every era of the blog;
  * the ANSWER, whose letter count is the light's length;
  * from about 2017 on, the clue TEXT and its enumeration;
  * from 2025 on, all of that inside a `<table class="clues">` skeleton with
    `num`/`clue`/`ans` cells and the definition underlined.

Number + direction + length is the complete input to
`tools/reconstruct_grid.py`, so the geometry The Times withholds is derivable
from what the blog prints. The answers do double duty: a reconstruction that
comes back as a shortlist can be narrowed by throwing out the candidates whose
crossing squares disagree with the letters we already know.

Their robots.txt sets `Crawl-delay: 10`, so the cache is the point: nothing
already on disk is requested again and a killed run resumes for free. Parsing
lives elsewhere and reruns against the cache as often as it likes — which
matters more here than it did for fifteensquared, because the pre-2025 posts
are prose and every blogger formats their prose differently.

  python3 tools/fetch_timesforthetimes.py               # top up the cache
  python3 tools/fetch_timesforthetimes.py --status      # what is cached
  python3 tools/fetch_timesforthetimes.py --since 2020-01-01

The API returns 403 to python-urllib's default User-Agent with nothing in the
error naming the header — the same trap fifteensquared sets.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path.home() / "cryptic-setter-data" / "timesforthetimes"
POSTS = CACHE / "posts"

API = "https://timesforthetimes.co.uk/wp-json/wp/v2/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CRAWL_DELAY = 10  # their robots.txt, verified 2026-09-21

#: Puzzle categories only. Announcements, site updates and meetups blog no
#: grid, and a post with no clue list is a post the parser would have to learn
#: to reject — cheaper never to fetch it.
CATEGORIES = {
    11: "Daily Cryptic",
    12: "Quick Cryptic",
    21: "Weekend Cryptic",
    14: "Jumbo Cryptic",
    13: "Mephisto",
    24: "Monthly Club Special",
    26: "Other Crosswords",
}

#: No date floor by default. Before about 2017 the blog prints the answer and
#: the wordplay but not the clue, and those years still carry the numbers and
#: letter-counts a grid is rebuilt from, so they are worth the bytes. `--since`
#: bounds a spot-check.

#: Only the fields a parser or a grid needs. The API will otherwise send
#: rendered excerpts, yoast metadata and a _links block per post, which is most
#: of the bytes and none of the information.
FIELDS = "id,date,slug,link,title,content,categories"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r), r.headers


def cached_ids():
    return {int(p.stem) for p in POSTS.glob("*.json")}


def fetch_category(cid, name, since=None, pages_cap=None):
    """Walk every page the API reports for one category.

    Walk them all: a page cap silently truncates an archive, and a run that
    stopped early looks exactly like a finished one. `--pages` bounds a
    spot-check, never a top-up.
    """
    have = cached_ids()
    page, total_pages, new = 1, None, 0
    while True:
        args = {
            "categories": cid, "per_page": 100, "page": page,
            "orderby": "date", "order": "desc", "_fields": FIELDS,
        }
        if since:
            args["after"] = since + "T00:00:00"
        q = urllib.parse.urlencode(args)
        try:
            posts, headers = get(API + "posts?" + q)
        except urllib.error.HTTPError as e:
            if e.code == 400 and total_pages and page > total_pages:
                break  # walked off the end; the API 400s rather than emptying
            print(f"  {name} page {page}: HTTP {e.code} {e.reason}", flush=True)
            break
        if total_pages is None:
            total_pages = int(headers.get("X-WP-TotalPages") or 1)
            span = f" since {since}" if since else ""
            print(f"  {name}: {headers.get('X-WP-Total')} posts{span}, "
                  f"{total_pages} page(s)", flush=True)
        if not posts:
            break
        for p in posts:
            if p["id"] not in have:
                (POSTS / f"{p['id']}.json").write_text(
                    json.dumps(p, ensure_ascii=False), encoding="utf-8")
                new += 1
        page += 1
        if page > total_pages or (pages_cap and page > pages_cap):
            break
        time.sleep(CRAWL_DELAY)
    return new


def status():
    ids = cached_ids()
    print(f"{len(ids)} post(s) cached in {POSTS}")
    if not ids:
        return
    by_cat, years = {}, {}
    for p in POSTS.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        for c in d.get("categories", []):
            by_cat[c] = by_cat.get(c, 0) + 1
        years[d["date"][:4]] = years.get(d["date"][:4], 0) + 1
    for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>6}  {CATEGORIES.get(c, 'category ' + str(c))}")
    print("  years: " + ", ".join(f"{y}:{n}" for y, n in sorted(years.items())))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since",
                    help="earliest post date to fetch (default: the whole archive)")
    ap.add_argument("--category", action="append",
                    help="one category name; repeatable, default all puzzle ones")
    ap.add_argument("--pages", type=int,
                    help="stop after N pages per category — a spot-check, not a top-up")
    ap.add_argument("--status", action="store_true", help="what is cached, then exit")
    a = ap.parse_args()

    POSTS.mkdir(parents=True, exist_ok=True)
    if a.status:
        status()
        return 0

    wanted = CATEGORIES
    if a.category:
        names = {n.lower(): c for c, n in CATEGORIES.items()}
        try:
            wanted = {names[n.lower()]: n for n in a.category}
        except KeyError as e:
            print(f"unknown category {e}; known: {', '.join(CATEGORIES.values())}")
            return 2

    before = len(cached_ids())
    for cid, name in wanted.items():
        fetch_category(cid, name, a.since, a.pages)
        time.sleep(CRAWL_DELAY)
    after = len(cached_ids())
    print(f"cached {after} post(s), {after - before} new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
