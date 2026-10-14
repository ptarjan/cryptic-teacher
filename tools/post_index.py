#!/usr/bin/env python3
"""A local index of a cached blog's posts: post id -> title, link and slug.

The post caches (fifteensquared, bigdave44, Times for the Times) sit on the
media share as one JSON file per post, 20k+ of them, where opening each is
milliseconds: reading them all to find one puzzle's posts took a single-puzzle
write over twenty minutes. This answers from the three fields a reader looks a
post up by, so a lookup opens only the posts it wants.

It reads tools/media_manifest.py's posts-<blog> manifest on the SSD, which the
fetchers (fetch_fifteensquared.py, fetch_wp_blog.py) append a row to as they
store each post, title, link and slug included; they never rewrite one, so an
entry never goes stale. Nothing here lists, stats or opens the posts on the
media disk (Paul 2026-10-14: "I don't want anything regularly scanning the
spinning disk"). Titles, not puzzle ids, are held, so a change to how a title
names a puzzle (corroborate.BLOG_SERIES) needs no rebuild.
"""

from pathlib import Path

import media_manifest

_memo = {}


def entries(posts):
    """{post id (the file's stem, a str): [title, link, slug]} for every post
    the cache `posts` holds, off its manifest (media_manifest.posts)."""
    posts = Path(posts)
    if posts not in _memo:
        _memo[posts] = {str(i): [r["title"], r["link"], r["slug"]]
                        for i, r in media_manifest.posts(posts).items()}
    return _memo[posts]


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
