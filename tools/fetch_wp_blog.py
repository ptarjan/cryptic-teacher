#!/usr/bin/env python3
"""Cache a crossword blog's WordPress posts, so we fetch each one once.

Two papers withhold what we need and a blog prints it: The Times withholds
its grids, and timesforthetimes.co.uk has solved every Times puzzle in public
since 2007; the Telegraph's archive is paywalled, and bigdave44.com has
hinted every Telegraph back-page and Toughie since 2009. Each post carries the
clue NUMBER under an Across/Down heading, the clue TEXT with its enumeration,
and the ANSWER, whose letter count is the light's length. Number + direction +
length is the complete input to `tools/reconstruct_grid.py`, so the geometry
the paper withholds is derivable from what the blog prints, and the answers
narrow a shortlist by where they cross.

Both blogs run WordPress, whose REST API hands the whole archive over in tens
of requests. The cache is the point: nothing already on disk is requested
again and a killed run resumes for free. Parsing lives elsewhere and reruns
against the cache as often as it likes, because every blogger formats their
prose differently.

  python3 tools/fetch_wp_blog.py timesforthetimes            # top up the cache
  python3 tools/fetch_wp_blog.py bigdave44 --full            # walk every page again
  python3 tools/fetch_wp_blog.py bigdave44 --status          # what is cached
  python3 tools/fetch_wp_blog.py timesforthetimes --since 2020-01-01

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
from dataclasses import dataclass
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DATA = Path.home() / "cryptic-setter-data"


@dataclass(frozen=True)
class Blog:
    name: str
    api: str
    crawl_delay: int
    #: Puzzle categories only. Announcements, site updates and meetups blog no
    #: grid, and a post with no clue list is a post the parser would have to
    #: learn to reject — cheaper never to fetch it.
    categories: dict

    @property
    def cache(self):
        return DATA / self.name

    @property
    def posts(self):
        return self.cache / "posts"


#: No date floor by default. Before about 2017 timesforthetimes prints the
#: answer and the wordplay but not the clue, and those years still carry the
#: numbers and letter-counts a grid is rebuilt from, so they are worth the
#: bytes. `--since` bounds a spot-check.
BLOGS = {b.name: b for b in (
    Blog("timesforthetimes", "https://timesforthetimes.co.uk/wp-json/wp/v2/",
         10,  # their robots.txt, verified 2026-09-21
         {11: "Daily Cryptic", 12: "Quick Cryptic", 21: "Weekend Cryptic",
          14: "Jumbo Cryptic", 13: "Mephisto", 24: "Monthly Club Special",
          26: "Other Crosswords"}),
    # robots.txt sets no delay; 3s keeps a full walk to minutes. A prize
    # puzzle's hints go up on its print day under a Hints category, and their
    # post date is what dates it: its review follows entries closing.
    Blog("bigdave44", "https://bigdave44.com/wp-json/wp/v2/", 3,
         {43: "DT Cryptic Crosswords", 11: "Toughie Crosswords",
          71: "ST Cryptic Crosswords", 7625: "Sunday Toughie Crosswords",
          24: "Saturday Hints", 26: "Sunday Hints", 7734: "Sunday Toughie Hints"}),
)}

#: Only the fields a parser or a grid needs. The API will otherwise send
#: rendered excerpts, yoast metadata and a _links block per post, which is most
#: of the bytes and none of the information.
FIELDS = "id,date,slug,link,title,content,categories"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r), r.headers


def cached_ids(blog):
    return {int(p.stem) for p in blog.posts.glob("*.json")}


class FetchError(Exception):
    """The API refused a page, so the category's walk did not finish."""


def fetch_category(blog, cid, name, since=None, pages_cap=None, full=False):
    """Walk one category newest first, and stop at the first page that is
    already wholly cached: everything older than it was cached by an earlier
    walk. That makes a top-up one page per category rather than the whole
    archive, which at the crawl delay is twenty-odd minutes.

    `full` walks every page, for a cache an interrupted walk left with a hole
    below its newest page. `--pages` bounds a spot-check, never a top-up.
    """
    have = cached_ids(blog)
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
            posts, headers = get(blog.api + "posts?" + q)
        except urllib.error.HTTPError as e:
            if e.code == 400 and total_pages and page > total_pages:
                break  # walked off the end; the API 400s rather than emptying
            raise FetchError(f"{name} page {page}: HTTP {e.code} {e.reason}") from e
        if total_pages is None:
            total_pages = int(headers.get("X-WP-TotalPages") or 1)
            span = f" since {since}" if since else ""
            print(f"  {name}: {headers.get('X-WP-Total')} posts{span}, "
                  f"{total_pages} page(s)", flush=True)
        if not posts:
            break
        fresh = [p for p in posts if p["id"] not in have]
        for p in fresh:
            (blog.posts / f"{p['id']}.json").write_text(
                json.dumps(p, ensure_ascii=False), encoding="utf-8")
        new += len(fresh)
        if not fresh and not full:
            break
        page += 1
        if page > total_pages or (pages_cap and page > pages_cap):
            break
        time.sleep(blog.crawl_delay)
    return new


def fetch_categories(blog):
    """Cache the blog's category list as {id: name}. A post names its setter
    by category on bigdave44, and new setters arrive as new categories."""
    names, page = {}, 1
    while True:
        q = urllib.parse.urlencode({"per_page": 100, "page": page, "_fields": "id,name,parent"})
        cats, headers = get(blog.api + "categories?" + q)
        names.update({c["id"]: {"name": c["name"], "parent": c["parent"]} for c in cats})
        if page >= int(headers.get("X-WP-TotalPages") or 1):
            break
        page += 1
    (blog.cache / "categories.json").write_text(
        json.dumps(names, ensure_ascii=False), encoding="utf-8")


def status(blog):
    ids = cached_ids(blog)
    print(f"{len(ids)} post(s) cached in {blog.posts}")
    if not ids:
        return
    by_cat, years = {}, {}
    for p in blog.posts.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        for c in d.get("categories", []):
            by_cat[c] = by_cat.get(c, 0) + 1
        years[d["date"][:4]] = years.get(d["date"][:4], 0) + 1
    for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>6}  {blog.categories.get(c, 'category ' + str(c))}")
    print("  years: " + ", ".join(f"{y}:{n}" for y, n in sorted(years.items())))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("blog", choices=sorted(BLOGS))
    ap.add_argument("--since",
                    help="earliest post date to fetch (default: the whole archive)")
    ap.add_argument("--category", action="append",
                    help="one category name; repeatable, default all puzzle ones")
    ap.add_argument("--pages", type=int,
                    help="stop after N pages per category — a spot-check, not a top-up")
    ap.add_argument("--full", action="store_true",
                    help="walk every page, not just down to the first cached one")
    ap.add_argument("--status", action="store_true", help="what is cached, then exit")
    a = ap.parse_args()
    blog = BLOGS[a.blog]

    blog.posts.mkdir(parents=True, exist_ok=True)
    if a.status:
        status(blog)
        return 0

    wanted = blog.categories
    if a.category:
        names = {n.lower(): c for c, n in blog.categories.items()}
        try:
            wanted = {names[n.lower()]: n for n in a.category}
        except KeyError as e:
            print(f"unknown category {e}; known: {', '.join(blog.categories.values())}")
            return 2

    before = len(cached_ids(blog))
    failed = []
    for cid, name in wanted.items():
        try:
            fetch_category(blog, cid, name, a.since, a.pages, a.full)
        except (FetchError, urllib.error.URLError, TimeoutError) as e:
            failed.append(str(e))
        time.sleep(blog.crawl_delay)
    try:
        fetch_categories(blog)
    except (urllib.error.URLError, TimeoutError) as e:
        failed.append(f"categories: {e}")
    after = len(cached_ids(blog))
    print(f"cached {after} post(s), {after - before} new")
    for why in failed:
        print(f"ERROR: fetch_wp_blog {blog.name}: {why}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
