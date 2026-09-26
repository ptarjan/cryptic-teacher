#!/usr/bin/env python3
"""Cache fifteensquared blog posts and their comments, so we fetch each once.

fifteensquared.net blogs every puzzle in our five series, and its bloggers and
commenters name their favourite clues. That is the only per-clue quality signal
available to us, and it is what `tools/craft_report.py` needs to be tested
against — see that file for why testing is not the same as fitting.

Their robots.txt sets `Crawl-delay: 20` for everyone, so this is the expensive
half of the job and the cache is the point: nothing already on disk is ever
requested again, and a run killed halfway resumes for free. Parsing lives
elsewhere and can be rerun against the cache as often as it likes.

The WordPress REST API returns up to 100 records per request, and comments can
be asked for by a comma-separated list of post ids, so the whole archive slice
we care about is tens of requests rather than hundreds — minutes at the crawl
delay, not hours. Do not "optimise" that into one-request-per-post.

A run walks every page the API reports for each category, because a page cap
silently truncates the archive: Independent alone is 73 pages, and a run that
stopped at six looked exactly like a finished one. `--pages` is there to bound a
quick spot-check, never to bound a top-up.

  python3 tools/fetch_fifteensquared.py                       # top up the cache
  python3 tools/fetch_fifteensquared.py --status              # what is cached
  python3 tools/fetch_fifteensquared.py --category Everyman   # one series

Two things that cost a round trip to learn (2026-09-09): the `.com` domain
times out, only `.net` answers; and the API returns 403 to python-urllib's
default User-Agent, with nothing in the error naming the header.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path.home() / "cryptic-setter-data" / "fifteensquared"
POSTS = CACHE / "posts"
COMMENTS = CACHE / "comments"

BASE = "https://fifteensquared.net/wp-json/wp/v2"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Their own robots.txt. Not negotiable and not a tuning knob.
CRAWL_DELAY = 20
PER_PAGE = 100
# Posts per comments request. Small enough that a busy day's threads still fit
# in a page or two, large enough that the archive is tens of requests.
BATCH = 25

# The categories that overlap what we hold. Ids come from /categories; names are
# kept beside them so a renumbering is visible rather than silent.
#
# Private Eye/Cyclops earns its place twice over: it is the one series whose
# answers exist nowhere else, because Private Eye's own .puz ships a dummy
# solution grid, so this blog is the only source tools/fetch_privateeye.py can
# join against.
CATEGORIES = {
    "Guardian": None,
    "Independent": None,
    "Everyman": None,
    "Guardian Quiptic": None,
    "Private Eye/Cyclops": None,
    # The FT prints no grid we can read, so tools/ft_puzzles.py rebuilds each
    # one from the clue numbers these posts carry.
    "FT": None,
}

_last_request = [0.0]


def get(path, **params):
    """One polite GET. Blocks until the crawl delay since the last one is up."""
    wait = CRAWL_DELAY - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
            total = int(r.headers.get("X-WP-TotalPages") or 1)
    except urllib.error.HTTPError as e:
        # Put the failure in the message; a caller should never need the log.
        raise SystemExit(f"{url} -> HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}")
    finally:
        _last_request[0] = time.monotonic()
    return body, total


def resolve_categories():
    """Category name -> id, filled in once per run so ids are never hardcoded."""
    page, pages = 1, 1
    while page <= pages:
        rows, pages = get("categories", per_page=PER_PAGE, page=page)
        for row in rows:
            if row["name"] in CATEGORIES:
                CATEGORIES[row["name"]] = row["id"]
        page += 1
    missing = [k for k, v in CATEGORIES.items() if v is None]
    if missing:
        raise SystemExit(f"category not found on the site: {', '.join(missing)} "
                         f"— they renamed it; fix CATEGORIES")
    # Kept beside the posts, so a parser can pick its series out of the cache
    # without asking the site.
    store(CACHE, "categories", CATEGORIES)
    return CATEGORIES


def cached_categories():
    """Category name -> id as the last fetch resolved it."""
    return json.loads((CACHE / "categories.json").read_text(encoding="utf-8"))


def cached_post_ids():
    return {int(p.stem) for p in POSTS.glob("*.json")}


def cached_comment_ids():
    return {int(p.stem) for p in COMMENTS.glob("*.json")}


def store(directory, key, payload):
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{key}.tmp"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    # Rename last, so a killed run never leaves a half-written file that the
    # next run would treat as already fetched.
    tmp.rename(directory / f"{key}.json")


def fetch_posts(cat_id, name, pages_max=None):
    """Newest first, to the last page the API reports. Stops early at the first
    fully-cached page, but only once the cache holds every full page's worth of
    this category — the archive only grows at the head, so a cache that is
    complete below the head cannot have changed under us, while one with holes
    in it (a run that was killed, or bounded by --pages) must keep walking.
    pages_max is an explicit spot-check bound and is None for a real run: a
    default that caps pages truncates the archive without ever saying so."""
    have = cached_post_ids()
    held = sum(cat_id in json.loads(p.read_text(encoding="utf-8")).get("categories", ())
               for p in POSTS.glob("*.json"))
    new = 0
    page, pages = 1, 1
    while page <= pages and (pages_max is None or page <= pages_max):
        rows, pages = get("posts", categories=cat_id, per_page=PER_PAGE, page=page,
                          _fields="id,date,link,title,content,categories")
        fresh = [r for r in rows if r["id"] not in have]
        if not fresh and page > 1 and held + new >= PER_PAGE * (pages - 1):
            break
        for row in fresh:
            store(POSTS, row["id"], row)
            have.add(row["id"])
            new += 1
        print(f"  {name} page {page}/{pages}: +{len(fresh)} new", flush=True)
        page += 1
    if pages_max is not None and pages_max < pages:
        print(f"  {name}: STOPPED at --pages {pages_max} of {pages} pages", flush=True)
    return new


def fetch_comments(post_ids):
    """Comments for many posts per request. A post with none still gets a file,
    so 'no comments' is cached as an answer rather than retried forever.

    per_page caps the RESPONSE, not the batch: the posts in one batch share a
    single page of 100 comments, and everything past that is on page 2. So every
    page is walked before anything is stored — a batch stored from page 1 alone
    writes an empty file for most of its posts, and an empty file here is
    indistinguishable from a post that genuinely has no comments, so the cache
    never retries it and the error is permanent and silent.
    """
    todo = [i for i in sorted(post_ids) if i not in cached_comment_ids()]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        by_post = {p: [] for p in batch}
        page, pages = 1, 1
        while page <= pages:
            rows, pages = get("comments", post=",".join(map(str, batch)), page=page,
                              per_page=PER_PAGE, _fields="id,post,author_name,content,date")
            for row in rows:
                by_post.setdefault(row["post"], []).append(row)
            page += 1
        # Stored only once the batch is complete, for the same reason.
        for post_id, items in by_post.items():
            store(COMMENTS, post_id, items)
        got = sum(len(v) for v in by_post.values())
        print(f"  comments {i + len(batch)}/{len(todo)}  (+{got} in {pages} page(s))", flush=True)
    return len(todo)


def status():
    posts, comments = cached_post_ids(), cached_comment_ids()
    size = sum(p.stat().st_size for p in CACHE.rglob("*.json")) if CACHE.exists() else 0
    # The comment TOTAL is printed, not just the coverage: a truncated fetch
    # leaves every post covered and nearly all of them empty, which reads as a
    # finished job until you look at the number of comments in it.
    n = 0
    for c in COMMENTS.glob("*.json"):
        try:
            n += len(json.loads(c.read_text(encoding="utf-8")))
        except ValueError:
            continue
    print(f"cache: {CACHE}")
    print(f"  posts    {len(posts)}")
    print(f"  comments {n} on {len(comments)} posts covered")
    print(f"  on disk  {size / 1e6:.1f} MB")
    if posts:
        dates = []
        for p in POSTS.glob("*.json"):
            try:
                dates.append(json.loads(p.read_text(encoding="utf-8"))["date"])
            except (ValueError, KeyError):
                continue
        if dates:
            print(f"  covers   {min(dates)[:10]} .. {max(dates)[:10]}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="report the cache and exit")
    ap.add_argument("--pages", type=int, default=None,
                    help="stop after this many pages of 100 posts per category; "
                         "for a quick spot-check only (default: every page)")
    ap.add_argument("--category", action="append", metavar="NAME",
                    help=f"only this category, repeatable "
                         f"({', '.join(CATEGORIES)})")
    ap.add_argument("--posts-only", action="store_true", help="skip comments")
    args = ap.parse_args()

    if args.status:
        return status()

    print(f"cache {CACHE}  (crawl delay {CRAWL_DELAY}s, {PER_PAGE} records/request)",
          flush=True)
    wanted = args.category or list(CATEGORIES)
    unknown = [c for c in wanted if c not in CATEGORIES]
    if unknown:
        raise SystemExit(f"--category {', '.join(unknown)}: not one of "
                         f"{', '.join(CATEGORIES)}")

    cats = resolve_categories()
    total_new = 0
    for name in wanted:
        total_new += fetch_posts(cats[name], name, args.pages)
    print(f"posts: +{total_new} new, {len(cached_post_ids())} cached", flush=True)

    if not args.posts_only:
        # Comments for the whole cache, not just this run's posts: a previous
        # run killed during its comment pass leaves posts with no comment file,
        # and nothing else ever comes back for them.
        n = fetch_comments(cached_post_ids())
        print(f"comments: fetched for {n} posts", flush=True)

    status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
