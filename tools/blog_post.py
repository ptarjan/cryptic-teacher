#!/usr/bin/env python3
"""Print the cached blog post that explains a puzzle, with its comments.

    python3 tools/blog_post.py cryptic-28746

For an annotation run stuck on a clue: the post is already on disk, found
by the join tools/blog_facts.py made, so there is nothing to search for or
fetch. Exits 1 when no cached post covers the puzzle.
"""
import html.parser
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blog_facts import BLOGS, OUT, rendered

BREAKS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "table", "blockquote"}


class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in BREAKS:
            self.out.append("\n")
        elif tag == "td":
            self.out.append("  ")

    def handle_endtag(self, tag):
        self.handle_starttag(tag, ())

    def handle_data(self, data):
        self.out.append(data)


def text(markup):
    p = _Text()
    p.feed(markup)
    p.close()
    lines = (" ".join(line.split()) for line in "".join(p.out).replace("\xa0", " ").splitlines())
    return "\n".join(line for line in lines if line)


def source(pid):
    """(blog key, url) blog_facts joined this puzzle to, or None."""
    own = OUT / f"{pid.rsplit('-', 1)[0]}.json"  # the series' file, where it is filed
    for f in [own, *(f for f in OUT.glob("*.json") if f != own)]:
        rec = json.loads(f.read_text(encoding="utf-8")).get(pid) if f.exists() else None
        if rec:
            return rec["blog"], rec["url"]
    return None


def cached(pid, blog, url):
    """(post, comments) for the cached post at `url`, which writes up `pid`, or None."""
    root = BLOGS[blog][0]
    index = root / "by_puzzle.json"  # fifteensquared's post ids per puzzle
    ids = json.loads(index.read_text(encoding="utf-8"))["ids"] if index.exists() else {}
    known = [root / "posts" / f"{i}.json" for i in ids.get(pid, ())]
    for path in [*known, *(root / "posts").glob("*.json")]:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        if url not in raw:
            continue
        post = json.loads(raw)
        if post.get("link") != url:
            continue
        c = root / "comments" / path.name
        return post, json.loads(c.read_text(encoding="utf-8")) if c.exists() else []
    return None


def find(pid):
    """(blog name, url, post, comments) for this puzzle, or None."""
    src = source(pid)
    got = src and cached(pid, *src)
    return got and (BLOGS[src[0]][1], src[1], *got)


def main(argv):
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__.strip())
        return 2
    got = find(argv[0])
    if not got:
        print(f"no cached blog post covers {argv[0]}")
        return 1
    name, url, post, comments = got
    print(f"{name}: {text(rendered(post.get('title')))}\n{url}\n\n{text(rendered(post.get('content')))}")
    for c in comments:
        print(f"\n--- {c.get('author_name', '?')}:\n{text(rendered(c.get('content')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
