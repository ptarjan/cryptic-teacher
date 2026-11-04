#!/usr/bin/env python3
"""Fetch the blog post that explains a puzzle before its annotate run starts.

    python3 tools/blog_prefetch.py cryptic-28746

A run that is stuck used to WebSearch for the puzzle's post and WebFetch the
index pages on the way, which is inference spent on a lookup code can do. This
asks the blog's WordPress search for the puzzle's number (the same REST API
tools/fetch_wp_blog.py and tools/fetch_fifteensquared.py walk), keeps the post
whose title names the series and the number, and stores it with its comments
under ~/.cache/cryptic-blog-prefetch/ in the shape tools/blog_post.py prints.
blog_post.find falls back to it when the nightly cache has no post.

Polite and harmless: one search and at most one comments request per call, a
short timeout, a browser-ish User-Agent, no retries. Any failure (404, 403, a
timeout, nothing found) is recorded as a miss, so a retry of the same session
does not ask again for MISS_DAYS, and never fails the caller: exit is always 0.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import fetch_wp_blog
import series

DIR = Path(os.environ.get("CT_BLOG_PREFETCH") or Path.home() / ".cache" / "cryptic-blog-prefetch")
MISS_DAYS = 3
TIMEOUT = 15
UA = fetch_wp_blog.UA

#: Blog host -> (REST base, the name a reader is shown).
HOSTS = {
    "timesforthetimes.co.uk": (fetch_wp_blog.BLOGS["timesforthetimes"].api, "Times for the Times"),
    "bigdave44.com": (fetch_wp_blog.BLOGS["bigdave44"].api, "Big Dave's Crossword Blog"),
    "fifteensquared.net": ("https://fifteensquared.net/wp-json/wp/v2/", "Fifteensquared"),
}
#: Series fifteensquared blogs that tools/series.py gives no blog (annotate_check.FIFTEENSQUARED).
FIFTEENSQUARED = {"cryptic", "quiptic", "everyman", "independent", "indysunday", "cyclops"}

#: Series -> (title must match, title must not match): how each blog heads a post.
TITLES = {
    "times": (r"\btimes\b|\bdaily cryptic\b", r"sunday|quick|jumbo|literary|\bst\b|club"),
    "timesquick": (r"quick", None),
    "timesjumbo": (r"jumbo", None),
    "sundaytimes": (r"sunday times|\bst\b", r"mephisto|jumbo"),
    "timesclub": (r"club|special", None),
    "tls": (r"literary|tls", None),
    "mephisto": (r"mephisto", None),
    "azed": (r"azed", None),
    "ftcryptic": (r"\bft\b|financial", None),
    "telegraph": (r"\bdt\b|daily telegraph|telegraph", r"toughie|sunday|\bst\b"),
    "toughie": (r"toughie", r"sunday|\bst\b"),
    "sundaytel": (r"\bst\b|sunday telegraph|sunday cryptic", r"toughie"),
    "sundaytough": (r"sunday toughie|\bst toughie", None),
    "cryptic": (r"guardian|cryptic", r"quiptic|genius|prize"),
    "quiptic": (r"quiptic", None),
    "everyman": (r"everyman", None),
    "independent": (r"independent", r"sunday"),
    "indysunday": (r"sunday|\bios\b", None),
    "cyclops": (r"cyclops|private eye|\beye\b", None),
}
#: A post may be put up this long before or after the puzzle's date.
BEFORE, AFTER = timedelta(days=3), timedelta(days=21)


def host_of(puzzle):
    """The blog host that writes this puzzle up, or None."""
    s = series.of(puzzle)
    host = (series.meta(s) or {}).get("blog") if s in series.SERIES else None
    return host or ("fifteensquared.net" if s in FIFTEENSQUARED else None)


def _text(field):
    return re.sub(r"<[^>]+>", " ", (field or {}).get("rendered", "") if isinstance(field, dict) else field or "")


def titled(post, s, number):
    """Whether `post`'s title is this series' write-up of No `number`."""
    title = " ".join(_text(post.get("title")).replace("&#8211;", "-").replace("&nbsp;", " ").split()).lower()
    if number not in {n.replace(",", "") for n in re.findall(r"\d[\d,]*\d|\d", title)}:
        return False
    want, bar = TITLES.get(s, (None, None))
    return bool((not want or re.search(want, title)) and not (bar and re.search(bar, title)))


def in_window(post, when):
    try:
        posted = date.fromisoformat(post["date"][:10])
        return when - BEFORE <= posted <= when + AFTER
    except (KeyError, ValueError, TypeError):
        return True


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def find_post(puzzle, get=_get):
    """(host, post dict, comments list) for the puzzle's write-up, or None. Raises on a network error."""
    host = host_of(puzzle)
    number = str(puzzle.get("number") or "")
    if not host or not number.isdigit():
        return None
    api = HOSTS[host][0]
    s = series.of(puzzle)
    try:
        when = date.fromisoformat(str(puzzle.get("date"))[:10])
    except ValueError:
        when = None
    q = urllib.parse.urlencode({"search": number, "per_page": 20, "_fields": "id,date,link,title,content"})
    posts = [p for p in get(api + "posts?" + q) if titled(p, s, number) and (not when or in_window(p, when))]
    if not posts:
        return None
    post = min(posts, key=lambda p: p.get("date", ""))
    c = urllib.parse.urlencode({"post": post["id"], "per_page": 100, "order": "asc",
                                "_fields": "id,post,parent,date,content,author_name"})
    try:
        comments = get(api + "comments?" + c)
    except (urllib.error.URLError, TimeoutError, ValueError):
        comments = []  # the post alone is worth keeping
    return host, post, comments


def _path(pid):
    return DIR / f"{pid}.json"


def _misses():
    try:
        return json.loads((DIR / "misses.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load(pid):
    """(blog name, url, post, comments) fetched for `pid` earlier, or None."""
    try:
        rec = json.loads(_path(pid).read_text(encoding="utf-8"))
        return rec["name"], rec["url"], rec["post"], rec["comments"]
    except (OSError, ValueError, KeyError):
        return None


def _miss(pid, today):
    DIR.mkdir(parents=True, exist_ok=True)
    misses = _misses()
    misses[pid] = today.isoformat()
    (DIR / "misses.json").write_text(json.dumps(misses), encoding="utf-8")


def prefetch(puzzle, get=_get, today=None):
    """Cache the puzzle's blog post unless one is held or a recent lookup missed.
    Returns "have", "recent miss", "fetched" or "miss"; never raises."""
    today = today or date.today()
    pid = puzzle.get("id") or ""
    try:
        import blog_post  # the nightly cache wins; this is only its fallback
        if blog_post.find(pid) or load(pid):
            return "have"
        seen = _misses().get(pid)
        if seen and today - date.fromisoformat(seen) < timedelta(days=MISS_DAYS):
            return "recent miss"
        try:
            got = find_post(puzzle, get)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            got = None
        if not got:
            _miss(pid, today)
            return "miss"
        host, post, comments = got
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = _path(pid).with_suffix(".part")
        tmp.write_text(json.dumps({"name": HOSTS[host][1], "url": post["link"], "post": post,
                                   "comments": comments, "fetched": time.time()}, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(_path(pid))
        return "fetched"
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError) as e:  # a lookup never fails the session
        print(f"blog_prefetch {pid}: {type(e).__name__}: {e}", file=sys.stderr)
        return "miss"


def main(argv):
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__.strip())
        return 0
    try:
        import puzzle_paths
        path = puzzle_paths.find(argv[0])
        puzzle = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError, ImportError) as e:
        print(f"blog_prefetch {argv[0]}: no puzzle ({type(e).__name__})", file=sys.stderr)
        return 0
    print(f"blog_prefetch {argv[0]}: {prefetch(puzzle)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
