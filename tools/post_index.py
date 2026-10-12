#!/usr/bin/env python3
"""A local index of a cached blog's posts: post id -> title, link and slug.

The post caches (fifteensquared, bigdave44, Times for the Times) sit on the
media share as one JSON file per post, 20k+ of them, where opening each is
milliseconds: reading them all to find one puzzle's posts took a single-puzzle
write over twenty minutes. This keeps the three fields a reader looks a post up
by in one file under ~/.cache, so a lookup opens only the posts it wants.

It is kept fresh incrementally. The fetchers (fetch_fifteensquared.py,
fetch_wp_blog.py) store only posts they do not hold, renamed in whole, and
never rewrite one, so an entry never goes stale: the index is topped up from a
listing of the directory (only when its mtime moved), reading just the posts
it lacks and dropping the ones gone. Titles, not puzzle ids, are held, so a
change to how a title names a puzzle (corroborate.BLOG_SERIES) needs no
rebuild.
"""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CACHE_DIR = Path(os.environ.get("CT_POST_INDEX") or Path.home() / ".cache" / "cryptic-teacher" / "post-index")
VERSION = 1
#: Readers in flight while topping up: the share answers many reads at once
#: about as fast as one.
THREADS = 16

_memo = {}


def cache_file(posts):
    key = hashlib.sha1(str(Path(posts).resolve()).encode()).hexdigest()[:12]
    return CACHE_DIR / f"v{VERSION}-{key}.json"


def _fields(path):
    """(title, link, slug) of one post file, or None when it cannot be read."""
    try:
        post = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    title = post.get("title")
    if isinstance(title, dict):
        title = title.get("rendered")
    return [title or "", post.get("link") or "", post.get("slug") or ""]


def _load(path):
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    return held.get("stamp"), held.get("posts") or {}


def _save(path, stamp, posts, directory):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"dir": str(directory), "stamp": stamp, "posts": posts}),
                   encoding="utf-8")
    tmp.replace(path)


def entries(posts):
    """{post id (the file's stem, a str): [title, link, slug]} for every post
    file in the directory `posts`; {} when it does not exist."""
    posts = Path(posts)
    if posts in _memo:
        return _memo[posts]
    try:
        stamp = posts.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    path = cache_file(posts)
    held_stamp, index = _load(path)
    if held_stamp != stamp:
        have = {n[:-5] for n in os.listdir(posts) if n.endswith(".json") and not n.startswith(".")}
        missing = sorted(have - index.keys())
        gone = index.keys() - have
        with ThreadPoolExecutor(THREADS) as ex:
            read = list(ex.map(lambda s: _fields(posts / f"{s}.json"), missing))
        unread = False
        for stem, got in zip(missing, read):
            if got is None:
                unread = True  # read again next time
            else:
                index[stem] = got
        for stem in gone:
            del index[stem]
        # An unreadable post leaves the stamp unset, so the next reader lists again.
        _save(path, None if unread else stamp, index, posts)
    _memo[posts] = index
    return index


def post_file(posts, stem):
    return Path(posts) / f"{stem}.json"


def by_link(posts, link, key=lambda u: u):
    """The post ids whose link is `link` (compared through `key`)."""
    want = key(link)
    return [s for s, (_t, l, _s) in entries(posts).items() if key(l) == want]


def forget():
    """Drop the in-process memo (tests, and a long run that fetched)."""
    _memo.clear()


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        print(d, len(entries(d)))
