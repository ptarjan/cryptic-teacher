#!/usr/bin/env python3
"""The social card of every generated page that is not a puzzle.

A puzzle page unfurls as a clue out of that puzzle (make_og_card.py). Every
other page gets a card of its own title and description, drawn from
tools/og_page_card.html, so what a share previews is the page being shared.
build_seo_pages.head() gives one to any page that does not pass an image, so a
new page has a card without anyone remembering to make one.

The pages are generated before their cards can be drawn, since the cards are
drawn from what the pages say. So the ?v= stamp on a card's URL is a hash of
what it is drawn from — this file, the template, the title, the description,
the URL — rather than of the PNG, and head() can write it before the PNG
exists. build_seo_pages.py records every card it linked in og/page/cards.json;
make_og.sh --pages then draws the ones missing or out of date, and
stage_site.py fails the deploy if a page still links a card that is not there.

  python3 tools/page_card.py --stale            # slugs whose card needs drawing
  python3 tools/page_card.py --out F <slug>     # that card's HTML, to screenshot
  python3 tools/page_card.py --record <slug>    # note that card as drawn
  python3 tools/page_card.py --prune            # delete cards no page links
"""
import hashlib
import html
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = "https://cryptic.paultarjan.com"
TEMPLATE = REPO / "tools" / "og_page_card.html"
DIR = REPO / "og" / "page"
SPEC = DIR / "cards.json"
MANIFEST = DIR / ".manifest.json"
WIDTH, HEIGHT = 1200, 630


def slug(canonical):
    """og/page/<slug>.png for a page's canonical URL: its path, dashed."""
    path = canonical.removeprefix(BASE).strip("/")
    return path.replace("/", "-") or "home"


def spec(canonical, title, description):
    """Everything a card is drawn from, plus the version that names it."""
    s = {"url": canonical, "title": title, "description": description}
    h = hashlib.sha256(Path(__file__).resolve().read_bytes())
    h.update(TEMPLATE.read_bytes())
    h.update(json.dumps(s, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return {**s, "v": h.hexdigest()[:8]}


def rel(canonical):
    return f"og/page/{slug(canonical)}.png"


def alt(title, description):
    return f'A Cryptic Teacher card reading "{title}", above the line "{description}"'


def render(s):
    """The card's HTML. The title's size steps down with its length, so a long
    one takes a smaller face rather than a clamped fourth line."""
    n = len(s["title"])
    size = "" if n <= 40 else "long" if n <= 70 else "small"
    text = TEMPLATE.read_text(encoding="utf-8")
    for slot, value in (("SIZE", size), ("TITLE", html.escape(s["title"])),
                        ("DESCRIPTION", html.escape(s["description"])),
                        ("URL", html.escape(s["url"].removeprefix("https://")))):
        marker = f"<!--{slot}-->"
        if marker not in text:
            raise SystemExit(f"og_page_card.html is missing its {marker} slot")
        text = text.replace(marker, value)
    return text


def write_spec(cards):
    """cards: {slug: spec}, every page card the build just linked."""
    DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cards, indent=1, sort_keys=True, ensure_ascii=False)
    if not SPEC.exists() or SPEC.read_text(encoding="utf-8") != text:
        SPEC.write_text(text, encoding="utf-8")


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _cards():
    cards = _load(SPEC)
    if not cards:
        raise SystemExit(f"{SPEC.relative_to(REPO)} is missing or empty: run "
                         "python3 tools/build_seo_pages.py first, which writes it")
    return cards


def stale():
    have = _load(MANIFEST)
    return [k for k, s in sorted(_cards().items())
            if not (DIR / f"{k}.png").exists() or have.get(k) != s["v"]]


def record(k):
    have = _load(MANIFEST)
    have[k] = _cards()[k]["v"]
    MANIFEST.write_text(json.dumps(have, indent=1, sort_keys=True), encoding="utf-8")


def prune():
    cards, have = _cards(), _load(MANIFEST)
    for png in DIR.glob("*.png"):
        if png.stem not in cards:
            png.unlink()
            have.pop(png.stem, None)
            print(f"removed og/page/{png.name}")
    if MANIFEST.exists():
        MANIFEST.write_text(json.dumps(have, indent=1, sort_keys=True), encoding="utf-8")


def main():
    args = sys.argv[1:]
    if args == ["--stale"]:
        print("\n".join(stale()))
    elif args == ["--prune"]:
        prune()
    elif len(args) == 2 and args[0] == "--record":
        record(args[1])
    elif len(args) == 3 and args[0] == "--out":
        cards = _cards()
        if args[2] not in cards:
            raise SystemExit(f"no page links og/page/{args[2]}.png")
        Path(args[1]).write_text(render(cards[args[2]]), encoding="utf-8")
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
