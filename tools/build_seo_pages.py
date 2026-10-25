#!/usr/bin/env python3
"""Generate the static, crawlable half of the site.

The app is one URL of JavaScript. That is fine for solving and useless for
being found: a crawler arriving at the homepage sees a headline, a tagline and
three buttons, and leaves, because the puzzle list, the clues and every word of
the annotations are built by app.js from data it never executes deeply enough
to index. Every word of original explanation — the only thing here nobody
else has written — would be invisible.

So this writes real HTML files alongside the app:

  puzzles/<id>/index.html  one page per puzzle: every clue, its answer, its
                           definition, its wordplay breakdown and its
                           walkthrough, as text in the document.
  puzzles/index.html       the archive hub: each series, its count, its years.
  puzzles/series/<series>/index.html
                           one landing page per series: its newest puzzle,
                           the twenty before it, and every year. The page a
                           search for "guardian cryptic crossword" wants.
  puzzles/series/<series>/<year>/index.html
                           one listing per series per year, linking every
                           puzzle; the hub reaches any puzzle in two clicks.
  learn/index.html         the lesson, from tools/tutorial.html — the only place
                           it is published.
  abbreviations/index.html the glossary, on its own URL. "cryptic crossword
                           abbreviations" is a question people type, and a
                           lookup table buried a third of the way down a
                           beginner's guide cannot answer it.
  indicators/index.html    every indicator in tools/data/lexicons/indicators.json,
                           by type and by how many clues use it. "cryptic
                           crossword indicators" is the other lookup people type.
  difficulty/index.html    how the difficulty badge is worked out and checked,
                           from tools/difficulty_page.html with every number
                           filled in from tools/difficulty.py and
                           tools/data/difficulty_check.json.
  progress/index.html      how many puzzles are known to exist, downloaded, filed, solved
                           and hinted, per series and over time, from
                           tools/data/progress.json (tools/progress.py) with
                           this build's index as today, so filed/solved/hinted
                           are current at every deploy; known and downloaded
                           are the newest recorded night's.
  showcase/index.html      puzzles with something unusual about them: a message
                           hidden in the grid, a jigsaw, a record. Picked by
                           tools/showcase.py from facts every puzzle page's
                           render reads off its file, so it costs no extra pass.
  showcase/<slug>/index.html  one showcase section's whole list, or the top 100
                           of a ranking, linked from its section.
  sitemap.xml              a sitemap index: sitemap-recent.xml (the pages that
                           change daily and the last 60 days of puzzles) and
                           sitemap-archive-<n>.xml (every older puzzle), all
                           with real lastmod dates.

These pages are not doorways: each carries the annotation work for one specific
puzzle and exists to be read. They also cross-link back into the app with
?p=<id>, so someone who lands on an explanation can go and solve it with hints
instead — which is the point of the site.

What is deliberately NOT generated: a page per clue. Thirty clues a puzzle of
near-identical shell around two sentences of content is the exact
thin-content pattern that gets a site's whole crawl budget written off, and it
would bury the puzzle pages that are actually worth ranking.

Usage:
  python3 tools/build_seo_pages.py            # write everything
  python3 tools/build_seo_pages.py --check    # exit 1 if anything is stale
"""

import collections
import functools
import hashlib
import html
import itertools
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import app_tables  # the app's own sentence about each series
import build_abbreviations  # one glossary, rendered into every page that shows it
import clue_types  # the one list of clue types, their labels and blurbs
import difficulty  # the weights, bands and constants /difficulty/ quotes
import difficulty_check  # the held-out scorecard /difficulty/ quotes
import progress  # the phase history /progress/ draws
import provenance  # solution_detail(), source_url()
import renamed_ids  # the ids commits renamed, for their redirect pages
import quotes  # curl(): clue text is stored straight, shown curled
import series as series_meta  # what each series IS; see tools/series.py
import showcase  # which puzzles /showcase/ picks, and why
from fetch_puzzle import (  # one glob, one reader for every tool
    blog_annotation, blog_fact_hashes, has_blog_hints, puzzle_files, read_puzzle_file, read_puzzle_view,
    with_blog_facts)
import puzzle_paths  # one puzzles/ for every tool
import page_cache  # last build's puzzle pages, reused when nothing moved
import annotation  # ABBR_ASKED: the abbreviation lookups a page re-checks
import parallel  # the corpus across the cores
import row_cache  # solved_stub's rows, read once per file version
from stamp_assets import asset_url  # content-hashed asset URLs
# Which clue a puzzle's card shows, and how to describe it. Imported rather than
# reimplemented: the alt text has to describe the picture that was actually
# drawn, and only the generator knows which clue that was.
from make_og_card import alt_text as card_alt
from make_og_card import DEFAULT_ENTRY, DEFAULT_PUZZLE  # the site card's clue
import page_card  # the card of every page that is not a puzzle
from groups import entry_id
# Which (type, key) pairs a clue's indicators give: shared with the burn's
# indicator cover (tools/indicator_cover.py).
from indicator_keys import clue_pairs

# Every page card head() linked this run, for make_og.sh --pages to draw.
PAGE_CARDS = {}

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://cryptic.paultarjan.com"
# The numbers /puzzles/<number>/ was ever a real page at; see legacy_redirects().
BARE_NUMBER_URLS = frozenset(json.loads(
    (ROOT / "tools/data/bare_number_urls.json").read_text(encoding="utf-8"))["numbers"])

# Marker pair in index.html. The homepage is hand-written and stays that way;
# only what is between these two comments is generated, so the crawl path out
# of the homepage can be regenerated nightly without touching anything else.
NAV_START = "<!-- SEO-NAV-START (generated by tools/build_seo_pages.py) -->"
NAV_END = "<!-- SEO-NAV-END -->"


def pct(n, d):
    """n of d as a whole percent, floored: 100% only when n == d, and "<1%"
    rather than 0% when n > 0 (escaped, it lands in markup), so 245 of 246 never reads as done."""
    if not d or n <= 0:
        return "0%"
    if n >= d:
        return "100%"
    return "&lt;1%" if 100 * n < d else f"{100 * n // d}%"


@functools.lru_cache(maxsize=1 << 16)
def _esc_str(s):
    return html.escape(s, quote=True)


def esc(s):
    # The same strings come round again and again (an answer in its heading,
    # its blocks and its walkthrough; a clue's words in its blocks and its
    # indicators), so each is escaped once.
    return _esc_str(s if type(s) is str else str(s or ""))


#: The assets a puzzle page's render asked asset() for, while one renders:
#: tools/page_cache.py checks their stamps again before it reuses the page.
_ASKED = None


def asset(rel):
    """An absolute, content-stamped URL for one of our own static files.

    Never write these out by hand. A bare URL stays identical when the image
    is redrawn, so every service that already unfurled the site keeps showing
    the old picture. The hash in the URL is what makes a corrected image reach
    someone who saw the wrong one.
    """
    if _ASKED is not None:
        _ASKED.add(rel)
    return _asset(rel)


@functools.cache       # the assets do not change while the pages are built
def _asset(rel):
    return esc(asset_url(rel, BASE + "/"))


# Setters italicise titles and foreign words. The clue text is plain and its
# italics are code-point ranges beside it (clue.italics [{at, length}]), so the
# page escapes the text and wraps exactly those ranges in <i>, the way app.js's
# markUp does.
@functools.lru_cache(maxsize=1 << 16)
def _cesc_str(s):
    return esc(quotes.curl(s))


def cesc(s):
    """esc() for words taken from a clue: stored straight, shown curled."""
    return _cesc_str(s) if type(s) is str else esc(quotes.curl(s or ""))


def clue_html_text(clue):
    text = quotes.curl(clue.get("text", ""))   # one for one, so italics offsets hold
    cuts = sorted({0, len(text)} | {p for r in clue.get("italics", ())
                                   for p in (r["at"], r["at"] + r["length"])
                                   if 0 <= p <= len(text)})
    out = []
    for a, b in itertools.pairwise(cuts):
        piece = esc(text[a:b])
        italic = any(r["at"] <= a < r["at"] + r["length"] for r in clue.get("italics", ()))
        out.append(f"<i>{piece}</i>" if italic else piece)
    if clue.get("enumeration"):
        out.append(f"{' ' if text else ''}({esc(clue['enumeration'])})")
    return "".join(out)


# The fields a puzzle is named, dated and addressed by: all a neighbour's pager
# link or a redirect page reads of it.
STUB_KEYS = ("id", "series", "number", "date", "year")


def solved_stub(path):
    """(path, stub) for a listed puzzle with every solution, else None: the
    rule fetch_puzzle.reindex() uses for hasSolutions, which decides whether
    the listing page a puzzle page links to exists.

    The raw file, not read_puzzle_view(): a stub needs only the series that
    view derives (from the id, as annotation.view_puzzle does) and the
    solutions, and viewing every annotation of ~50k files was most of the
    puzzle list's time whenever the annotation code changed."""
    p = read_puzzle_file(path)
    p = {**p, "series": series_meta.of(p)}
    if series_meta.unlisted(p["series"]) or not all(e.get("solution") for e in p["entries"]):
        return None
    return path, {k: p[k] for k in STUB_KEYS if k in p}


def solved_stub_row(path):
    """solved_stub()'s stub alone, the row tools/row_cache.py keeps for a file:
    not its path, which is another path in another tree."""
    t = solved_stub(path)
    return t and t[1]


def puzzles():
    """[(path, stub)] for every listed puzzle with a solution, newest first.

    Stubs, not puzzles: the corpus does not fit in memory at once. Each puzzle
    is read in full again when its own page is rendered, one at a time.
    """
    files = list(puzzle_files())
    rows = row_cache.cached_map("build_seo_pages", solved_stub_row, files, roots={"solved_stub"})
    out = [(path, stub) for path, stub in zip(files, rows) if stub]
    # Chronological, matching fetch_puzzle.reindex(). Sorting on the number
    # would not be: quiptics (~1,400) sit alongside cryptics (~30,000), and
    # every quiptic would file at the end of time.
    out.sort(key=lambda t: (series_meta.puzzle_day(t[1]) or date.min,
                            t[1].get("series", "cryptic") == "cryptic",
                            t[1]["number"]), reverse=True)
    return out


# Titles and headings are built from tools/series.py rather than from a
# hardcoded "Guardian Cryptic", so a Quiptic page doesn't claim to be a cryptic
# and an Everyman page doesn't credit the wrong paper — Everyman is the
# Observer's Sunday puzzle, only syndicated onto the Guardian's site.
def kind(p):
    return series_meta.kind(p.get("series"), p["number"])


def position(p):
    """The number printed BESIDE the kind, which already names the volume.

    A book puzzle's stored number carries its volume (tools/series.py,
    volume * 1000 + position), so "Penguin Book 5 Cryptic No 5,018" would both
    name a number no book prints and say the volume twice. A feed puzzle's
    number is its position, so this is the publisher's own number there.
    """
    return series_meta.position_of(p.get("series") or "cryptic", p["number"])


def number_day(p):
    """The day a date-keyed number names (series.number_date), else None."""
    return series_meta.number_date(p.get("series") or "cryptic", p["number"])


def named(p):
    """"Guardian Penguin Book 5 Cryptic No 18" — the puzzle in full prose.
    "Canberra Times Cryptic, Monday 6 January 1992" where the number is a date."""
    pk = series_meta.paper_kind(p.get('series'), p['number'])
    if (day := number_day(p)):
        return f"{pk}, {day:%A %-d %B %Y}"
    return f"{pk} No {position(p):,}"


def display_number(p):
    """The number as a reader is shown it — "No 30,089", "Penguin book 5 No 18".

    Used where the row's series badge already names the paper: the archive
    rows. See display_number() in tools/series.py; a
    book's stored number carries its volume, and "No 5,018" names a puzzle no
    book prints.
    """
    return series_meta.display_number(p.get("series") or "cryptic", p["number"])


def publisher(p):
    # The number as well as the series: a book's paper is the BOOK's, and one
    # shelf reprints a dozen of them.
    return series_meta.publisher(p.get("series"), p["number"])


def papers(idx):
    """The papers this collection actually holds, commonest first.

    Derived rather than written out: a sentence naming the collection cannot
    be true for long if a human has to remember to update it whenever a series
    is added.
    """
    counts = {}
    for p in idx["puzzles"]:
        if p.get("hasSolutions"):
            counts[publisher(p)] = counts.get(publisher(p), 0) + 1
    names = sorted(counts, key=lambda n: (-counts[n], n))
    if len(names) < 2:
        return names[0] if names else "broadsheet"
    return ", ".join(names[:-1]) + " and " + names[-1]


def assert_names_all_papers(where, text, idx):
    """No paper may be named in site-wide copy unless all of them are.

    The mechanical form of the rule above, for the pages a human still writes
    by hand. Naming one paper is fine on a puzzle page — that page IS one
    paper's puzzle — but in copy that describes the whole collection it is a
    claim about all of it, and a wrong one the moment a second paper lands.
    """
    present = {publisher(p) for p in idx["puzzles"] if p.get("hasSolutions")}
    named = {n for n in present if n in text}
    if named and named != present:
        raise SystemExit(
            f"{where}: names {sorted(named)} but the collection also holds "
            f"{sorted(present - named)}. Copy about the whole site names every "
            f"paper in it or none of them — see papers() in build_seo_pages.py.")


def index_json():
    return json.loads((puzzle_paths.PUZZLE_DIR / "index.json").read_text(encoding="utf-8"))


def row_date(puzzle):
    """The date on an archive row, "Sat 3 Oct 2026": the app list's form, and the
    only one a row is written in (series.ROW_DATE_FMT; "1995" for a book)."""
    return datestr(puzzle, series_meta.ROW_DATE_FMT)


def datestr(puzzle, fmt="%A %-d %B %Y"):
    # The weekday is in the DEFAULT because a Guardian week has a shape — Monday
    # gentle, Friday and the Saturday prize hard — so it is a difficulty cue, not
    # trim. Callers that want a machine date (datePublished,
    # sitemap lastmod) pass an explicit fmt and are unaffected.
    #
    # A book puzzle holds a `year`, and the year is all any format prints:
    # "1995" is valid ISO 8601 for datePublished and W3C for sitemap lastmod.
    if "year" in puzzle:
        return str(puzzle["year"])
    day = series_meta.puzzle_day(puzzle)
    return day.strftime(fmt) if day else ""


def app_name():
    """What an installed icon is called, from the one place that says so.

    iOS labels a Home Screen icon with apple-mobile-web-app-title if the page has
    one, then the manifest's short_name, then <title>, and a title here is a
    sentence — "Cryptic crossword answers and explanations — Independent,
    Observer and Guardian" under an icon. So every page states it, and states it from site.webmanifest so the two
    cannot answer the question differently.
    """
    return json.loads((ROOT / "site.webmanifest").read_text(encoding="utf-8"))["short_name"]


@functools.cache
def site_card_alt():
    return card_alt(DEFAULT_PUZZLE, DEFAULT_ENTRY)


def head(title, description, canonical, extra="", image=None, image_alt=None):
    """The shared <head>. Kept identical to index.html's, minus the app-only bits.

    `image` is the social card. Puzzle pages pass their own — a clue out of that
    very puzzle — or the site card; every other page gets a card of its own
    title and description (tools/page_card.py), so a page nobody made a card for
    still unfurls as itself, not as a picture of somebody else's crossword clue.
    """
    if image:
        card = asset(image)
    else:
        s = page_card.spec(canonical, title, description)
        PAGE_CARDS[page_card.slug(canonical)] = s
        card = esc(f"{BASE}/{page_card.rel(canonical)}?v={s['v']}")
        image_alt = page_card.alt(title, description)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">
<meta name="theme-color" content="#faf8f4" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#14171a" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{asset("favicon.ico")}" sizes="32x32">
<link rel="icon" href="{asset("favicon.svg")}" type="image/svg+xml">
<link rel="apple-touch-icon" href="{asset("apple-touch-icon.png")}">
<meta name="apple-mobile-web-app-title" content="{esc(app_name())}">
<link rel="manifest" href="{BASE}/site.webmanifest">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Cryptic Teacher">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:image" content="{card}">
<meta property="og:image:width" content="{page_card.WIDTH}">
<meta property="og:image:height" content="{page_card.HEIGHT}">
<meta property="og:image:alt" content="{esc(image_alt)}">
<meta name="twitter:card" content="summary_large_image">
{extra}<link rel="stylesheet" href="{asset("style.css")}">
<script src="{asset("analytics.js")}"></script>
<script src="{asset("appnav.js")}"></script>
</head>
<body class="static-page">
"""


FOOTER = f"""<footer>
  <p class="muted">Clues and grids &copy; their publishers, quoted for study and
  review. The explanations and hints are this site's own.
  <a href="{BASE}/">Solve a puzzle with hints</a> &middot;
  <a href="{BASE}/puzzles/">All puzzles</a> &middot;
  <a href="{BASE}/learn/">How cryptic clues work</a> &middot;
  <a href="{BASE}/abbreviations/">Crossword abbreviations</a> &middot;
  <a href="{BASE}/indicators/">Crossword indicators</a> &middot;
  <a href="{BASE}/difficulty/">How difficulty is rated</a> &middot;
  <a href="{BASE}/showcase/">Unusual puzzles</a> &middot;
  <a href="{BASE}/progress/">Progress</a> &middot;
  <a href="https://github.com/ptarjan/cryptic-teacher">Source code</a>.</p>
</footer>
</body>
</html>
"""


def site_url(path):
    """A crumb path made absolute. Both renderings of a crumb go through here.

    Every crumb href is absolute or page-relative, never root-relative. The
    structured data (breadcrumb_ld) and the link a crawler follows (masthead)
    both join here: one joiner, both callers, no room to disagree.
    """
    return BASE + path


def masthead(crumbs):
    """Site header plus a breadcrumb trail — the crawl path back up, and the
    thing that stops a visitor landing from search from feeling stranded."""
    parts = []
    for i, (label, href) in enumerate(crumbs):
        last = i == len(crumbs) - 1
        parts.append(f"<span aria-current=\"page\">{esc(label)}</span>" if last
                     else f"<a href=\"{esc(site_url(href))}\">{esc(label)}</a>")
    return f"""<header>
  <div class="brand">
    <a class="home-link" href="{BASE}/"><strong>Cryptic Teacher</strong></a>
    <p class="tagline">Real puzzles, real setters. Hints that teach, not spoil.</p>
  </div>
</header>
<nav class="crumbs" aria-label="Breadcrumb">{' &rsaquo; '.join(parts)}</nav>
"""


def breadcrumb_ld(crumbs):
    items = [{"@type": "ListItem", "position": i + 1, "name": label,
              **({"item": site_url(href)} if href else {})}
             for i, (label, href) in enumerate(crumbs)]
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": items}


def ld(obj):
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            + "</script>\n")


# ---------------------------------------------------------------- puzzle page

def listed(names):
    """Names as prose: "a", "a and b", "a, b and c"."""
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)


def clue_html(e, blog_note=True):
    """One clue: text, answer, and whatever explanation exists for it.

    blog_note=False when the page says once, above the clues, that every
    explanation on it is marked up from the blog, so each clue need not.

    Un-annotated puzzles fall through to clue-and-answer only. That is thinner
    than an annotated page but it is not filler — it is the specific thing
    somebody searching "guardian cryptic 30073 answers" wants, and it is
    honestly labelled rather than padded out.
    """
    ann = e.get("annotation") or blog_annotation(e) or {}
    answer = ann.get("answer") or e.get("solution") or ""
    num = f"{e['number']} {e['direction']}"
    # Bare elements, one line per clue: style.css styles them by position
    # under .s-list, because this runs once per clue on the site and a class on
    # each piece was the bulk of what the pages weighed.
    bits = [f'<article id="{esc(entry_id(e))}">',
            f'<h3><span>{esc(num)}</span> <b>{esc(answer)}</b></h3>',
            f'<p>{clue_html_text(e["clue"])}</p>']

    # A definition, type or indicators tools/letter_facts.py read off the letters are not the blogger's.
    inferred = (e.get("blog") or {}).get("inferred", ()) if ann.get("fromBlog") else ()
    if ann.get("definitions"):
        kind = clue_types.labels(ann.get("type"))
        # The type is a word from the lesson ("charade", "container"), so its
        # label is the way to the lesson that defines it.
        dfns = " and ".join(f'<dfn>{cesc(d["text"])}</dfn>' for d in ann["definitions"])
        bits.append(f'<p>Definition: {dfns}'
                    + (' <span class="s-note">worked out from the letters</span>' if "definitions" in inferred else "")
                    + (f' · <span class="s-type"><a href="{BASE}/learn/">Clue type</a>: '
                       f'{esc(kind)}</span>' if kind else "")
                    + "</p>")
    # One sentence on why the ANSWER means the DEFINITION — app.js's "Why
    # that's the answer" rung, minus the answer/definition repeated back at
    # the reader (both are already on the page a line up).
    prose = ann.get("explanation") or {}
    if prose.get("definitionFit"):
        bits.append(f'<p><em>Why it fits:</em> {esc(prose["definitionFit"])}</p>')
    blocks = ann.get("blocks") or []
    if blocks:
        rows = "".join(
            f"<li><mark>{cesc(b.get('clueFragment'))}</mark> "
            + (f"→ {esc(b['soundsLike'])} said aloud " if b.get("soundsLike") else "")
            + f"→ <strong>{esc(b.get('gives'))}</strong>"
            + (f" <span class=\"s-note\">{esc(b.get('note'))}</span>" if b.get("note") else "")
            # a piece tools/letter_facts.py split the answer into is not the blogger's
            + (' <span class="s-note">worked out from the letters</span>' if b.get("inferred") else "")
            + "</li>" for b in blocks)
        bits.append(f'<p><em>Wordplay, piece by piece:</em></p><ul>{rows}</ul>')
    # Skip any indicator without a written note rather than print an empty one.
    noted = [i for i in ann.get("indicators") or () if i.get("note")]
    if noted:
        rows = "".join(f'<li><mark>{cesc(i["text"])}</mark> — {esc(i["note"])}</li>' for i in noted)
        bits.append(f'<p><em>Indicators:</em></p><ul>{rows}</ul>')
    # A blog's marked indicators carry no note of their own; the app lists them
    # bare too.
    if ann.get("fromBlog") and ann.get("indicators"):
        bits.append('<p><em>Indicators:</em> '
                    + build_abbreviations.LIST_SEP.join(f'<mark>{cesc(i["text"])}</mark>' for i in ann["indicators"])
                    + (' <span class="s-note">worked out from the letters</span>' if "indicators" in inferred else "")
                    + "</p>")
    if ann.get("fromBlog"):
        read = listed([name for key, name in (("definitions", "definition"), ("type", "clue type"),
                                              ("indicators", "indicators")) if key in inferred]).capitalize()
        if blog_note:
            bits.append('<p class="muted">'
                        + (f"{read} worked out from the letters, the rest marked up from the blogger\'s write-up; "
                           if read else "Marked up from the blogger\'s write-up; ")
                        + 'our own explanation is not written yet.</p>')
        elif read:
            bits.append(f'<p class="muted">{read} worked out from the letters, '
                        'not the blogger\'s.</p>')
    # The surface first, the same order and for the same reason as the app's
    # walkthrough rung: what the clue pretends to be about, then what it is doing.
    if prose.get("surface"):
        bits.append(f'<p class="s-walk"><em>What it seems to say:</em> {esc(prose["surface"])}</p>')
    if prose.get("walkthrough"):
        bits.append(f'<p class="s-walk"><em>How it works:</em> {esc(prose["walkthrough"])}</p>')
    if not ann:
        # Two different silences, and telling them apart is the whole point —
        # the same split app.js makes off clue.missing. "No explanation yet"
        # promises a ladder that is coming; a clue the paper printed blank has
        # no ladder ever, because there is no clue. Say which, or the reader
        # hunts the grid for wordplay that was never printed.
        # A blank clue printed on purpose still yields its answer. Without the
        # reason the page shows an answer and no way to get to it, so the
        # hand-written clue.missingNote carries it; the annotation queue never
        # writes one, having no words to read.
        bits.append(
            '<p class="muted">The paper printed no clue here. '
            + (esc(e["clue"]["missingNote"]) if "missingNote" in e["clue"]
               else "With no clue, there is no wordplay to explain.")
            + '</p>'
            if e["clue"].get("missing") else
            '<p class="muted">No explanation yet.</p>')
    bits.append("</article>")
    return "".join(bits)


def solve_url(pid, eid=None):
    """The app with this puzzle open, on clue eid ("21-across") when given: where
    every puzzle link a reader follows goes. /puzzles/<id>/ shows every answer;
    it is for search engines, and a reader is sent there only from the archive
    listings, which are its crawl path (homepage_nav)."""
    url = f"{BASE}/?p={pid}"
    if eid:
        number, direction = eid.split("-")
        url += f"&amp;c={number}{direction[0].upper()}"
    return url


def app_return(pid):
    """Send a reload back into the app when this tab was solving the puzzle there.

    The app keeps /puzzles/<id>/ in the address bar, because that is what gets
    copied and what previews with this page's card, so a reload lands here. The
    app sets sessionStorage "ct:app:<id>" when it opens the puzzle; crawlers and
    fresh visitors carry no flag and get this page. Only a reload or back/forward
    returns: following a link (an "answers" link from a listing) is a request
    for the write-up, flag or not. `../../` is the site root from every
    /puzzles/<id>/ page, on any host.
    """
    key = json.dumps(f"ct:app:{pid}")
    app = json.dumps(f"../../?p={pid}")
    return ("<script>try{var n=performance.getEntriesByType(\"navigation\")[0];"
            "if(n&&(n.type==\"reload\"||n.type==\"back_forward\"))"
            "if(sessionStorage.getItem(" + key + ")){"
            "var c=new URLSearchParams(location.search).get(\"c\");"
            "location.replace(" + app + "+(c?\"&c=\"+encodeURIComponent(c):\"\"))}"
            "}catch(e){}</script>\n")


def landing_script(pid):
    """landing.js, which marks the clue a search visitor came for and offers the
    rest of the crossword with hints under it. Most visitors from Google typed a
    single clue; this is the one place on the page that knows which."""
    return f'<script src="{asset("landing.js")}" data-p="{esc(pid)}" defer></script>\n'


def page_row(meta):
    """The part of a puzzle's index row that its page prints, or None without
    a row. puzzle_page() sees nothing else of the row, and page_key() hashes
    exactly this, so a stored page is reused until something it shows moves.
    The rest of the row (the difficulty index and basis, tags, the file stamp)
    moves as puzzles arrive without changing a byte of the page."""
    if not meta:
        return None
    diff = meta.get("difficulty") or {}
    band = diff.get("band")
    return {"listing": listing_key(meta), "annotated": bool(meta.get("annotated")),
            "band": band, "percentile": diff.get("percentile") if band else None}


def puzzle_page(puz, meta, prev_p, next_p):
    row = page_row(meta)
    del meta  # every read of the index row goes through page_row()
    setter = puz.get("setter") or ""
    what = kind(puz)                  # "Cryptic", "Quiptic", "Everyman"
    paper = publisher(puz)            # "Guardian", "Observer"
    pretty = f"{position(puz):,}"
    pk = series_meta.paper_kind(puz.get("series"), puz["number"])
    when = datestr(puz)
    # A date-keyed number (the Canberra Times) is named by its day:
    # "No 920,106" is a date with thousands separators.
    day = number_day(puz)
    dw = f"{day:%A %-d %B %Y}" if day else ""
    annotated = row and row["annotated"]
    # The page lives at its ID, not its number: two papers can reach the same
    # number and would then want the same directory. The bare-number URL still
    # works — legacy_redirects() keeps one at every number that was ever a page.
    canonical = f"{BASE}/puzzles/{puz['id']}/"

    # "Everyman Crossword No 4,096 by Everyman" is the setter's pseudonym said
    # twice. Where the series name IS the byline — the Observer has kept Everyman
    # anonymous since 1945 — the attribution is already in the title, so drop it.
    # Also empty when the source shipped no byline at all — a null setter.
    by = "" if not setter or setter == what else f" by {setter}"

    # Paper and number first, then "answers": searches are "guardian 30111",
    # "times crossword 29653", "everyman 4170 answers", so the identifier is the
    # paper and its number as typed (no thousands comma), and the intent word
    # follows it rather than trailing behind "Crossword No". The setter stays
    # wherever there is one, because setter names get searched; that costs the
    # characters "clue by clue" spends where there is no setter.
    # "explained" is a claim about the page. An un-annotated page prints the
    # answers and no wordplay, so its title stops at "answers": a title that
    # promises a walkthrough the page has not got earns the click once and the
    # bounce every time after.
    lead = "answers explained" if annotated else "answers"
    num = str(position(puz))
    title = (f"{pk}, {dw} – {lead}" + (f" – crossword{by}" if by else "") if day
             else f"{pk} {num} {lead} – crossword{by}" if by
             else f"{pk} {num} {lead} – full crossword, clue by clue" if annotated
             else f"{pk} {num} {lead} – full crossword solution")
    # The snippet leads with the same promise for the same reason, and still says
    # which of the three pages this is: explained clue by clue, marked up from a
    # blog's write-up, or answers only.
    # The kind keeps its capitals ("Penguin Book 5 Cryptic"): it is a name.
    full = (f"{pk}, {dw}{by}" if day else
            f"{pk} {num}{by}" + (f" ({when})" if when else ""))
    blog = puz.get("blog") if has_blog_hints(puz) else None
    desc = (f"Every answer to {full}, with each clue's definition and wordplay explained."
            if annotated else
            f"Every answer to {full}, with the definitions and wordplay marked up "
            f"from the {blog['name']} write-up." if blog else
            f"Every answer to {full}. Answers only for now: the clue-by-clue "
            "explanations are not written yet.")

    if row:
        ls, ly = row["listing"]        # the listing page this puzzle is on
    crumbs = [("Cryptic Teacher", "/"), ("Puzzles", "/puzzles/"),
              *([(series_name(ls), series_path(ls)), (ly, listing_path(ls, ly))]
                if row else []),
              (dw or f"No {pretty}", "")]

    across = [e for e in puz["entries"] if e["direction"] == "across"]
    down = [e for e in puz["entries"] if e["direction"] == "down"]
    across.sort(key=lambda e: e["number"])
    down.sort(key=lambda e: e["number"])

    facts = [f"Set by: <strong>{esc(setter)}</strong>"] if setter else []
    if when:
        facts.append(f"Published: <strong>{esc(when)}</strong>")
    if row and row["band"]:
        pct = row["percentile"]
        extra = f" ({harder_than(pct)})" if pct is not None else ""
        # A band is a word this site made up the meaning of, and a puzzle page is
        # where most people meet it first — arrived at from a search, having
        # never seen the archive index that explains it. So the label is the
        # link to that explanation rather than leaving "Brutal" to read as a
        # fact about the crossword.
        facts.append(f'<a href="{BASE}/difficulty/">Difficulty</a>: '
                     f'{diff_badge(row["band"])}{esc(extra)}')
    facts.append(f'Grid: <strong>{puz["dimensions"]["cols"]}&times;'
                 f'{puz["dimensions"]["rows"]}</strong> squares')

    # The neighbours are this puzzle's own series (see series_neighbours); the
    # link names the paper all the same, since a book shelf spans volumes.
    nav = []
    if prev_p:
        nav.append(f'<a rel="prev" href="{BASE}/puzzles/{prev_p["id"]}/">'
                   f'&larr; Newer: {esc(named(prev_p))}</a>')
    if next_p:
        nav.append(f'<a rel="next" href="{BASE}/puzzles/{next_p["id"]}/">'
                   f'Older: {esc(named(next_p))} &rarr;</a>')
    if row and nav:
        nav.append(f'<a href="{site_url(series_path(ls))}">All {esc(series_name(ls))} puzzles</a>')

    article_ld = {
        "@context": "https://schema.org", "@type": "Article",
        # No "description": it would be the meta description a second time.
        "headline": title, "url": canonical,
        "author": {"@type": "Person", "name": "Paul Tarjan", "url": "https://paultarjan.com/"},
        "isAccessibleForFree": True,
        "about": {"@type": "Game", "name": f"{pk} Crossword" + (f", {dw}" if day else f" No {pretty}")},
    }
    if datestr(puz):
        article_ld["datePublished"] = datestr(puz, "%Y-%m-%d")

    body = [
        masthead(crumbs),
        "<main class=\"static-main\">",
        f"<h1>{pk} Crossword" + (f", {dw}" if day else f" No {pretty}") + "</h1>",
        f'<p class="s-facts">{build_abbreviations.LIST_SEP.join(facts)}</p>',
        *(f'<p class="s-reprint">Reprinted in the {esc(series_meta.publisher(r["series"], r["number"]))}'
          f' as No {r["number"]:,}' + (f', {date.fromisoformat(r["date"]):%A %-d %B %Y}' if r.get("date") else "")
          + '.</p>' for r in puz.get("source", {}).get("reprintedIn", ())),
        f'<p class="s-cta"><a class="cta" href="{solve_url(puz["id"])}">Solve it yourself, '
        f'with hints one step at a time &rarr;</a></p>',
    ]
    # A page that prints answers has to say where the answers came from. For a
    # prize puzzle solved here before the paper published its key, the answers
    # below are a machine's — right or wrong, and searchable either way, so the
    # claim gets qualified in the page itself rather than only in the data.
    detail = provenance.solution_detail(puz)
    if "model" in detail and detail.get("officialKey") == "never":
        # A reprint no job can fetch a key for. Promising official answers "as
        # soon as those appear" would be a promise nothing keeps: the book prints
        # its solutions only as answer-grid images, and it names no puzzle
        # number or date to look a key up by. Say that instead.
        body.append(
            '<p class="unofficial-note">These answers are our own solve. Every one fits the '
            "letters it shares with the answers crossing it, but none has been checked against "
            f"an official list of answers. The book that reprinted this {paper} crossword prints "
            "its solutions only as pictures of filled-in grids, with no puzzle number or date to "
            "match them by. Treat these answers as very likely right, not certain.</p>")
    elif "model" in detail:
        body.append(
            f'<p class="unofficial-note">This is a {paper} prize crossword: readers send in '
            "their solutions to win a prize, so the paper publishes the answers later. Until it "
            "does, these answers are our own solve. Every one fits the letters it shares with "
            "the answers crossing it, but the paper has not confirmed them. When the official "
            "answers come out, this page switches to them.</p>")
    if annotated:
        body.append(
            "<p>Every clue is below with its answer and how it works. A cryptic clue has two "
            "parts: a <strong>definition</strong>, an ordinary meaning of the answer at the "
            "start or end of the clue, and <strong>wordplay</strong>, a second route to the "
            "same letters. <em>Indicators</em> are the words that say what to do with the "
            "letters, such as rearrange them or turn them backwards. Each clue also says "
            "<em>what it seems to say</em>, the innocent sentence it pretends to be.</p>")
        types = type_key(puz)
        if types:
            body.append("<p>The clue types in this puzzle:</p><ul class=\"s-types\">"
                        + "".join(f"<li>{esc(t)}</li>" for t in types) + "</ul>")
        body.append(
            f'<p>Want to solve it first? <a href="{solve_url(puz["id"])}">Open it in the '
            "solver</a>: it gives the same explanation one hint at a time, so you see only "
            "as much as you need.</p>")
    else:
        body.append(
            "<p>Here is the answer to every clue. The explanations for this puzzle are not "
            f'written yet; we add them a few puzzles at a time. <a href="{BASE}/puzzles/">All '
            "puzzles</a> are listed by paper and year, and the ones marked <strong>full "
            "hints</strong> are explained clue by clue.</p>")
    source_url = provenance.source_url(puz)
    if source_url:
        # Link text is the host we actually fetched from, not a hardcoded
        # "theguardian.com" — the Independent's puzzles come from somewhere else
        # entirely, and crediting the wrong site is worse than not crediting one.
        host = re.sub(r"^www\.", "", urlparse(source_url).netloc)
        body.append(f'<p class="muted small-note">Original puzzle: '
                    f'<a href="{esc(source_url)}" rel="nofollow">{esc(host)}</a></p>')

    # A page with none of our own explanations says once that what it shows
    # is the blog's, rather than on each of its thirty clues.
    blog_only = (not any(e.get("annotation") for e in across + down)
                 and any(e.get("blog") for e in across + down))
    if blog_only:
        facts = [e.get("blog") or {} for e in across + down]
        read = listed([name for name, hit in (
            ("definitions", any("definitions" in f.get("inferred", ()) for f in facts)),
            ("pieces", any(b.get("inferred") for f in facts for b in f.get("blocks", ()))),
            ("indicators", any("indicators" in f.get("inferred", ()) for f in facts))) if hit])
        body.append('<p class="muted small-note">The definitions, pieces and indicators '
                    "below are marked up from the "
                    + (f"{esc(blog['name'])} write-up" if blog and blog.get("name")
                       else "blogger\'s write-up")
                    + (f", but for the {read} worked out from the letters" if read else "")
                    + "; our own explanations are not written yet.</p>")
    for label, entries in (("Across", across), ("Down", down)):
        body.append(f'<section class="s-list"><h2>{label}</h2>')
        body.extend(clue_html(e, blog_note=not blog_only) for e in entries)
        body.append("</section>")

    if nav:
        body.append(f'<nav class="s-pager">{" ".join(nav)}</nav>')
    body.append("</main>")

    # This puzzle's own social card, if one has been rendered. Existence on disk
    # is the condition rather than "is it annotated", because the page must not
    # advertise an image that isn't there — and asset() would fail on it anyway,
    # having nothing to hash.
    if (ROOT / f"og/{puz['id']}.png").exists():
        card, alt = f"og/{puz['id']}.png", card_alt(puz["id"])
    else:
        card, alt = "og.png", site_card_alt()

    return (head(title, desc, canonical,
                 app_return(puz["id"]) + landing_script(puz["id"]) + ld(article_ld) + ld(breadcrumb_ld(crumbs)),
                 card, alt)
            + "\n".join(body) + "\n" + FOOTER)


# ------------------------------------------------------------------ hub page

def diff_badge(band):
    """A difficulty band, the one way every page shows it: the lowercase pill
    the app's difficultyBadge() draws."""
    b = esc(band.lower())
    return f'<span class="badge diff diff-{b}">{b}</span>'


def harder_than(pct):
    """A difficulty percentile in words, the one way every page says it. The
    app's difficultyBadge() tooltip says it the same way."""
    return f"harder than {pct}% of rated puzzles here"


def series_badge(series):
    """A series' pill, as the app's seriesChip() draws it."""
    return f'<span class="badge series">{esc(series_meta.badge(series))}</span>'


def hub_row(p, note=None):
    """One archive row. Every listing page is made of these and nothing else.
    With `note` it is a showcase row: what is unusual about the puzzle takes
    the place of the hints badges, which say nothing about why it was picked.
    The row opens the puzzle in the app; an archive row adds a small link to
    its answer page, which is how a crawler reaches every one (homepage_nav)."""
    d = p.get("difficulty") or {}
    when = row_date(p)
    # The date column carries the date on every row. A date-keyed paper prints
    # no number, so its title slot names the publisher instead ("Canberra
    # Times", series.date_numbered()), as pickerRow in app.js does.
    title = (series_meta.date_numbered()[p.get("series")] if number_day(p)
             else display_number(p))
    badge = diff_badge(d["band"]) if d.get("band") else ""
    # The app's hintsBadge() in the same words: ours, a blog's (the index's
    # `blog`, see has_blog_hints), or none.
    hints = ('<span class="badge full">full hints</span>' if p.get("annotated")
             else f'<span class="badge auto blog">hints via {esc(p["blog"])}</span>' if p.get("blog")
             else '<span class="badge auto">answers only</span>')
    # Same coverage axis as the hints badge, same neutral colour — see
    # sourceBadge() in app.js.
    ours = ('<span class="badge auto">unverified answers</span>'
            if p.get("solutionsUnofficial") else "")
    if note is not None:
        hints, ours = (f'<span class="badge feature">{esc(note)}</span>' if note else ""), ""
    # Every row is badged, because the numbers alone ("No 1,393" among the
    # 30,000s) don't explain themselves and an unbadged row reads as one we
    # forgot rather than as the default. Mirrors seriesBadge() in app.js.
    series = series_badge(p.get("series") or "cryptic")
    answers = ("" if note is not None else
               f'<a class="p-answers" href="{BASE}/puzzles/{p["id"]}/">answers</a>')
    return (f'<li><a href="{solve_url(p["id"])}">'
            f'<span class="p-num">{esc(title)}</span>'
            f'<span class="p-setter">{esc(p.get("setter"))}</span>'
            f'<span class="p-meta">{esc(when)}</span>'
            f'<span class="p-tags">{series}{badge}{hints}{ours}</span></a>{answers}</li>')


# The archive is one page per series per year, under /puzzles/series/, and the
# hub only links to those: a single list of every puzzle would run to megabytes.
# A year of the busiest series is ~315 rows, about 100 KB.
# "series" is not a puzzle id, bare number or legacy id, so it cannot collide.
UNDATED = "undated"


def type_key(puz):
    """The clue types this puzzle uses, each with its clue_types blurb, in the
    order the types first appear. A clue's "Clue type: charade" is a word
    from the lesson, and a reader from a search has not had it."""
    seen = {}
    for e in puz["entries"]:
        for t in (e.get("annotation") or {}).get("type") or ():
            seen.setdefault(t, clue_types.TYPES[t]["blurb"])
    return list(seen.values())


@functools.cache
def series_blurbs():
    """{series: the app's sentence about it}, read from app.js once per run."""
    return app_tables.series_blurbs()


def series_blurb(series, ps, books_listed=True):
    """The app's sentence about a series, as HTML, for a page listing the puzzles ps.

    A books page lists which books its puzzles came out of, read off ps itself:
    the registry also holds books not acquired yet. The all-puzzles page,
    with books_listed False, gives only how many.
    """
    text = series_blurbs().get(series)
    para = f"<p>{esc(text)}</p>" if text else ""
    if not series_meta.is_book(series):
        return para
    rows = {}
    for p in ps:
        row = series_meta.book_row(series, p["number"])
        rows[row["book_index"]] = row["title"]
    titles = [rows[i] for i in sorted(rows)]
    if not books_listed:
        return para + f"<p>From {len(titles)} book{'s' if len(titles) != 1 else ''}.</p>"
    return para + '<ul class="s-books">' + "".join(f"<li>{esc(t)}</li>" for t in titles) + "</ul>"


def series_name(series):
    if series_meta.is_book(series):
        return "Crossword books"      # kind and publisher are each book's own
    return series_meta.paper_kind(series)


def listing_key(p):
    """(series, year) of the listing page a puzzle is on; year may be UNDATED."""
    return (p.get("series") or "cryptic",
            datestr(p, "%Y") or UNDATED)


def listing_path(series, year):
    return f"/puzzles/series/{series}/{year}/"


def series_path(series):
    return f"/puzzles/series/{series}/"


def reprint_rows(idx):
    """A row per reprint (the index's `reprints`) whose original has answers:
    the original's row under the reprinting paper's series, number, date (or
    a book's year) and name, so it lists under that paper and links to the
    original's pages."""
    by_id = {p["id"]: p for p in idx["puzzles"]}
    return [{**{k: v for k, v in by_id[r["reprintOf"]].items() if k not in ("date", "year")},
             **{k: r[k] for k in ("series", "number", "date", "year", "name") if k in r}}
            for r in idx.get("reprints", ())
            if by_id.get(r["reprintOf"], {}).get("hasSolutions")]


def listings(idx):
    """{series: {year: [rows' puzzles, newest first]}}, busiest series first,
    newest year first, undated last. A reprinting paper is listed by its
    reprint rows, each in its place by the index's order (newest day, then the
    cryptic, then highest number), so a book's reprint sits at its number."""
    out = {}
    rows = idx["puzzles"] + reprint_rows(idx)
    rows.sort(key=lambda p: (series_meta.puzzle_day(p) or date.min,
                             (p.get("series") or "cryptic") == "cryptic", p["number"]),
              reverse=True)
    for p in rows:
        if p.get("hasSolutions"):
            s, y = listing_key(p)
            out.setdefault(s, {}).setdefault(y, []).append(p)
    order = sorted(out, key=lambda s: (-sum(map(len, out[s].values())), s))
    return {s: dict(sorted(out[s].items(),
                           key=lambda kv: (kv[0] != UNDATED, kv[0]), reverse=True))
            for s in order}


# The badges and the difficulty scale, said once in words. Every listing page
# carries it: a reader arriving from a search lands there, not on the hub.
BADGE_KEY = ("<strong>full hints</strong>: every clue explained. "
             "<strong>hints via</strong> a blog: definitions and wordplay marked up from that "
             "blog's write-up, our own explanations not written yet. "
             "<strong>answers only</strong>: answers now, no explanations yet. "
             "<strong>unverified answers</strong>: our own solve, not yet confirmed by the "
             "paper. Difficulty runs <strong>gentle</strong>, <strong>moderate</strong>, "
             f'<strong>tough</strong>, <strong>brutal</strong> (<a href="{BASE}/difficulty/">'
             'how difficulty is rated</a>).')


STRIP_BINS, STRIP_MIN = 20, 10


def difficulty_strip(name, ps):
    """Where a series' rated puzzles fall on the site-wide difficulty
    percentile: one bar per twentieth, coloured by the band most of its puzzles
    in that bar carry, scaled to the series' own tallest bar so it shows shape
    and never size, with the median puzzle marked. Every series is drawn on the
    same 0-100 axis, so they compare down the page. Empty for a series with
    fewer than STRIP_MIN rated puzzles, too few for a shape."""
    rated = sorted((d["percentile"], d["band"]) for p in ps
                   if (d := p.get("difficulty") or {}).get("percentile") is not None
                   and d.get("band"))
    if len(rated) < STRIP_MIN:
        return ""
    bins = [{} for _ in range(STRIP_BINS)]
    for pct, band in rated:
        b = bins[min(int(pct * STRIP_BINS / 100), STRIP_BINS - 1)]
        b[band] = b.get(band, 0) + 1
    top = max(sum(b.values()) for b in bins)
    W, H, step = 300, 24, 300 / STRIP_BINS
    body = [f'<line class="axis" x1="0" y1="{H + .5}" x2="{W}" y2="{H + .5}"/>']
    for i, b in enumerate(bins):
        if b:
            h = H * sum(b.values()) / top
            band = max(b, key=b.get)
            body.append(f'<rect class="band diff-{esc(band.lower())}" x="{i * step + .5:.1f}" '
                        f'y="{H - h:.1f}" width="{step - 1:.1f}" height="{h:.1f}"/>')
    med_pct, med_band = rated[len(rated) // 2]
    x = W * med_pct / 100
    body.append(f'<line class="median" x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{H + 4}"/>'
                f'<text x="0" y="{H + 15}">easier</text>'
                f'<text x="{W}" y="{H + 15}" text-anchor="end">harder</text>')
    band = med_band.lower()
    label = f"{name}: its typical puzzle is {band}, {harder_than(med_pct)}."
    return (f'<figure class="chart strip"><svg viewBox="0 -2 {W} {H + 19}" role="img" '
            f'aria-label="{esc(label)}">{"".join(body)}</svg>'
            f'<figcaption>Typical puzzle {diff_badge(band)}, {harder_than(med_pct)}.'
            '</figcaption></figure>')


def hub_page(idx):
    who = papers(idx)                 # "Guardian, Independent and Observer"
    n_all = sum(1 for p in idx["puzzles"] if p.get("hasSolutions"))
    title = "Cryptic crossword answers and explanations, by paper and year"
    desc = (f"Answers to cryptic crosswords from the {who}, sorted by paper "
            "and year. Many are explained clue by clue: the definition, the wordplay and "
            "how they fit together.")
    canonical = f"{BASE}/puzzles/"
    crumbs = [("Cryptic Teacher", "/"), ("Puzzles", "")]

    sections = []
    for s, years in listings(idx).items():
        every = [p for ps in years.values() for p in ps]
        links = year_links(s, years)
        sections.append(
            f'<section class="s-series" id="{esc(s)}">'
            f'<h2><a href="{site_url(series_path(s))}">{esc(series_name(s))}</a> '
            f'{series_badge(s)}</h2>'
            + series_blurb(s, every, books_listed=False)
            + difficulty_strip(series_name(s), every)
            + '<p class="muted">Pick a year:</p>'
            f'<p class="s-years">{links}</p></section>')

    list_ld = {"@context": "https://schema.org", "@type": "CollectionPage",
               "name": title, "url": canonical, "description": desc}

    body = [
        masthead(crumbs),
        '<main class="static-main">',
        "<h1>Cryptic crossword answers and explanations</h1>",
        f"<p>All {n_all:,} puzzles on this site, sorted by paper and year. Pick a year to see "
        "its puzzles.</p>",
        f'<p class="muted small-note" id="difficulty">{BADGE_KEY} Difficulty compares each '
        "puzzle with the others on this site, from its grid, clues and answers. Under each "
        "paper, the bars show where its rated puzzles fall from easiest to hardest, coloured "
        "by band, and the line marks its middle puzzle. "
        f'New to cryptic crosswords? <a href="{BASE}/learn/">Start with how the clues work</a>.</p>',
        *sections,
        "</main>",
    ]
    return head(title, desc, canonical, ld(list_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


def hub_link():
    """The way back to /puzzles/ from a series' pages, in the footer's words."""
    return f'<a href="{BASE}/puzzles/">All puzzles</a>'


def year_links(series, years):
    """A series' years as links, each with its puzzle count: the one way the
    hub and the series page list them."""
    return build_abbreviations.LIST_SEP.join(
        f'<a href="{site_url(listing_path(series, y))}">{esc(y)}</a> ({len(ps):,})'
        for y, ps in years.items())


def listing_page(series, year, ps, prev_year, next_year):
    """One series' puzzles for one year, newest first."""
    name = series_name(series)
    label = f"{name}, {year}" if year != UNDATED else f"{name}, undated"
    title = (f"{name} {year} — crossword answers and explanations" if year != UNDATED
             else f"{name}, undated — crossword answers and explanations")
    explained = sum(1 for p in ps if p.get("annotated"))
    blogged = sum(1 for p in ps if p.get("blog"))
    # How many are explained is counted, not claimed: a year of answers-only
    # puzzles must not promise wordplay in its search snippet.
    # No counts either way: a search snippet never quotes the archive's size.
    ours = ("Every one is explained clue by clue." if explained == len(ps) else
            "Some are explained clue by clue." if explained else "")
    theirs = ("" if not blogged else
              "Every one has hints marked up from a solving blog's write-up."
              if blogged == len(ps) else
              "Some have hints marked up from a solving blog's write-up.")
    desc = (f"{name} crosswords"
            + (f" from {year}" if year != UNDATED else " with no publication date")
            + " on this site, with the answer to every clue. "
            + (" ".join(filter(None, (ours, theirs))) or "Explanations are not written yet."))
    path = listing_path(series, year)
    canonical = site_url(path)
    crumbs = [("Cryptic Teacher", "/"), ("Puzzles", "/puzzles/"),
              (name, series_path(series)), (year, "")]
    nav = []
    if prev_year:
        nav.append(f'<a rel="prev" href="{site_url(listing_path(series, prev_year))}">'
                   f'&larr; {esc(prev_year)}</a>')
    if next_year:
        nav.append(f'<a rel="next" href="{site_url(listing_path(series, next_year))}">'
                   f'{esc(next_year if next_year != UNDATED else "Undated")} &rarr;</a>')
    list_ld = {"@context": "https://schema.org", "@type": "CollectionPage",
               "name": title, "url": canonical, "description": desc}
    body = [
        masthead(crumbs),
        '<main class="static-main">',
        f"<h1>{esc(label)}</h1>",
        series_blurb(series, ps),
        difficulty_strip(label, ps),
        f'<p>{len(ps):,} puzzle{"s" if len(ps) != 1 else ""}, newest first. {hub_link()}.</p>',
        f'<p class="muted small-note">{BADGE_KEY}</p>',
        f'<ul class="s-index">{"".join(hub_row(p) for p in ps)}</ul>',
        *([f'<nav class="s-pager">{" ".join(nav)}</nav>'] if nav else []),
        "</main>",
    ]
    return head(title, desc, canonical, ld(list_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


RECENT = 20


def london_today():
    """Today where the papers print. "Today's" on a series page means the
    puzzle is dated the day the page was built, in the papers' own timezone."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/London")).date()


def series_page(series, years, today):
    """One series' landing page, /puzzles/series/<series>/: its newest puzzle
    first, then the ones before it, then every year.

    The searches it answers are "guardian cryptic crossword" and its kin, which
    want today's puzzle, so the title names it: "Guardian Cryptic crossword
    answers – today's No 30126 by Brummie". "Today's" only when the newest
    puzzle is dated today, else "latest"; "explained" only when it is. A book
    shelf has no newest puzzle, so its page is the blurb and the years.
    """
    name = series_name(series)
    every = [p for ps in years.values() for p in ps]
    canonical = site_url(series_path(series))
    crumbs = [("Cryptic Teacher", "/"), ("Puzzles", "/puzzles/"), (name, "")]
    latest = every[0] if not series_meta.is_book(series) and every[0].get("date") else None
    links = year_links(series, years)
    blurb = series_blurb(series, every)
    heading = name if series_meta.is_book(series) else f"{name} crossword answers"
    body = [masthead(crumbs), '<main class="static-main">', f"<h1>{esc(heading)}</h1>"]
    if latest:
        day = series_meta.puzzle_day(latest)
        which = "today's" if day == today else "latest"
        lead = "answers explained" if latest.get("annotated") else "answers"
        setter = latest.get("setter") or ""
        by = f" by {setter}" if setter and setter != kind(latest) else ""
        nd = number_day(latest)
        ident = f", {nd:%A %-d %B %Y}" if nd else f" No {position(latest)}"
        title = f"{name} crossword {lead} – {which}{ident}{by}"
        desc = (f"{which.capitalize()} {name} crossword{ident}{by}"
                + ("" if nd else f", {datestr(latest)}")
                + (", with every answer and each clue's definition and wordplay explained."
                   if latest.get("annotated") else ", with every answer.")
                + " Earlier puzzles are listed below, newest first, and by year.")
        body += [
            f"<h2>{'Today' if day == today else 'Latest'}: {esc(named(latest))}</h2>",
            f'<ul class="s-index">{hub_row(latest)}</ul>',
            f'<p class="s-cta"><a class="cta" href="{solve_url(latest["id"])}">Solve it yourself, '
            "with hints one step at a time &rarr;</a></p>",
            blurb,
            difficulty_strip(name, every),
            "<h2>Recent puzzles</h2>",
            f'<ul class="s-index">{"".join(hub_row(p) for p in every[1:RECENT + 1])}</ul>',
            f'<p class="muted small-note">{BADGE_KEY}</p>',
        ]
    else:
        title = f"{name}: cryptic crossword answers and explanations, by year"
        desc = ("Cryptic crosswords reprinted in books" if series_meta.is_book(series)
                else f"{name} crosswords") + ", by year, with the answer to every clue."
        body += [blurb, difficulty_strip(name, every)]
    body += ["<h2>Every year</h2>", f'<p class="s-years">{links}</p>',
             f'<p>{hub_link()}.</p>', "</main>"]
    list_ld = {"@context": "https://schema.org", "@type": "CollectionPage",
               "name": title, "url": canonical, "description": desc}
    return head(title, desc, canonical, ld(list_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


def series_pages(idx, today=None):
    today = today or london_today()
    for s, years in listings(idx).items():
        yield ROOT / series_path(s).strip("/") / "index.html", series_page(s, years, today)
    # /puzzles/series/ itself names nothing; it points at the hub, which lists them.
    target = f"{BASE}/puzzles/"
    yield ROOT / "puzzles" / "series" / "index.html", (
        bare_head("Crossword answers by paper", target,
                  f'<meta http-equiv="refresh" content="0; url={esc(target)}">\n')
        + f'<body>\n<p>Every paper is listed at <a href="{target}">all puzzles</a>.</p>\n'
        "</body>\n</html>\n")


def listing_pages(idx):
    for s, years in listings(idx).items():
        ys = list(years)          # newest first
        for i, y in enumerate(ys):
            # prev = the newer year, matching the puzzle pager's newest-first order
            yield ROOT / listing_path(s, y).strip("/") / "index.html", listing_page(
                s, y, years[y], ys[i - 1] if i > 0 else None,
                ys[i + 1] if i + 1 < len(ys) else None)


# ----------------------------------------------------------------- learn page

def learn_page():
    """Render tools/tutorial.html as the lesson, at /learn/.

    That fragment is the whole lesson and this is its only home.
    """
    inner = (ROOT / "tools" / "tutorial.html").read_text(encoding="utf-8")
    # The page leads with its own h1, so every heading in the fragment moves up
    # one: sections become h2, subsections h3. One pass, because two would run
    # the headings it had just rewritten through the next rule.
    inner = re.sub(r"<(/?)h([234])\b", lambda m: f"<{m.group(1)}h{int(m.group(2)) - 1}", inner)
    # The glossary has its own URL. Repeating it here would put
    # the same table on two indexable pages competing for the same query, so the
    # lesson points at it instead.
    inner = re.sub(
        re.escape(build_abbreviations.MARK_START) + ".*?" + re.escape(build_abbreviations.MARK_END),
        '<h2 id="abbreviations">Common abbreviations</h2>\n'
        "<p>Setters use short, fixed stand-ins for common words. <em>Street</em> gives "
        "<code>ST</code>. <em>Company</em> gives <code>CO</code>. You cannot work these out from "
        "the word. You just learn them, and they appear in charades all the time: "
        f'<a href="{BASE}/abbreviations/">see all '
        f'{len(build_abbreviations.by_word())} abbreviations used in these puzzles &rarr;</a></p>',
        inner, flags=re.S)

    # The indicator lists are the corpus's, ranked, not a hand-picked few.
    inner = re.sub(r"<!-- indicators: (\w+) -->", learn_indicators, inner)
    title = "How cryptic crossword clues work — a beginner's guide"
    desc = ("Every cryptic clue has two parts: a definition and wordplay. Learn to tell "
            "them apart, and learn the main clue types (anagram, charade, container, hidden "
            "word, homophone and more), each with a worked example.")
    canonical = f"{BASE}/learn/"
    crumbs = [("Cryptic Teacher", "/"), ("How cryptic clues work", "")]
    page_ld = {"@context": "https://schema.org", "@type": "Article",
               "headline": title, "url": canonical, "description": desc,
               "author": {"@type": "Person", "name": "Paul Tarjan",
                          "url": "https://paultarjan.com/"},
               "isAccessibleForFree": True}
    body = [
        masthead(crumbs),
        '<main class="static-main tutorial-static">',
        "<h1>How cryptic crossword clues work</h1>",
        inner,
        f'<p class="s-cta"><a class="cta" href="{BASE}/">Now try a real puzzle, '
        f'with hints &rarr;</a></p>',
        "</main>",
    ]
    return head(title, desc, canonical, ld(page_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


# ------------------------------------------------------------ difficulty page

DIFFICULTY_TEMPLATE = ROOT / "tools" / "difficulty_page.html"
COMPONENT = re.compile(r"<!-- component: (\w+) \| ([^>]*?) -->\n(.*?)(?=<!-- component:|\Z)", re.DOTALL)


def signed(x):
    """+0.50, &minus;0.25, and 0.00 for anything that rounds to zero."""
    x = round(x, 2)
    return "0.00" if x == 0 else f"{x:+.2f}".replace("-", "&minus;")


def difficulty_bands(idx):
    """The band table: where each band is cut, how many puzzles are in it now,
    and the NITCH range its Times badges quote. All of it read off
    difficulty.BANDS and the index."""
    counts = {}
    for p in idx["puzzles"]:
        b = (p.get("difficulty") or {}).get("band")
        if b:
            counts[b] = counts.get(b, 0) + 1
    total = sum(counts.values()) or 1
    ranges = idx.get("snitchRanges") or {}
    quoted = [s for s in difficulty.SNITCH_SERIES if ranges.get(s)]
    head = ("<tr><th>Band</th><th>Score</th><th>Puzzles here now</th>"
            + "".join(f"<th>{esc(series_name(s))} NITCH</th>" for s in quoted) + "</tr>")
    rows, lo = [], None
    for hi, band in difficulty.BANDS:
        cut = (f"below {signed(hi)}" if lo is None else
               f"above {signed(lo)}" if hi == float("inf") else f"{signed(lo)} to {signed(hi)}")
        n = counts.get(band, 0)
        nitch = "".join(
            f"<td>{r["q1"]}&ndash;{r["q3"]}</td>" if (r := ranges[s].get(band)) else "<td>&ndash;</td>"
            for s in quoted)
        rows.append(f'<tr><td>{diff_badge(band)}</td><td>{cut}</td>'
                    f"<td>{n:,} ({round(100 * n / total)}%)</td>{nitch}</tr>")
        lo = hi
    return f"<table>{head}{''.join(rows)}</table>"


def svg(w, h, body, label):
    """An inline chart. Colours come from style.css (.chart), so it follows
    the site's light and dark themes."""
    return (f'<figure class="chart"><svg viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{esc(label)}">{body}</svg><figcaption>{esc(label)}</figcaption></figure>')


def weights_chart(order, labels):
    """Horizontal bars, one per component, from difficulty.WEIGHTS."""
    total = sum(difficulty.WEIGHTS.values())
    top = max(difficulty.WEIGHTS.values())
    row, left, width = 22, 170, 300
    body = []
    for i, k in enumerate(order):
        w = difficulty.WEIGHTS[k]
        y = i * row
        body.append(f'<text x="{left - 8}" y="{y + 15}" text-anchor="end">{esc(labels[k])}</text>'
                    f'<rect class="bar" x="{left}" y="{y + 4}" width="{width * w / top:.1f}" height="14"/>'
                    f'<text x="{left + width * w / top + 6:.1f}" y="{y + 15}">'
                    f'{round(100 * w / total)}%</text>')
    return svg(left + width + 50, len(order) * row + 4, "".join(body),
               "Share of the rating each measure carries")


def bands_chart(idx):
    """One stacked bar: how the badged puzzles split across the bands now."""
    counts = {}
    for p in idx["puzzles"]:
        b = (p.get("difficulty") or {}).get("band")
        if b:
            counts[b] = counts.get(b, 0) + 1
    total = sum(counts.values())
    if not total:
        return ""
    width, x, body = 520, 0.0, []
    for _, band in difficulty.BANDS:
        n = counts.get(band, 0)
        w = width * n / total
        if w:
            body.append(f'<rect class="band diff-{esc(band.lower())}" x="{x:.1f}" y="0" '
                        f'width="{w:.1f}" height="26"/>'
                        f'<text x="{x + w / 2:.1f}" y="44" text-anchor="middle">'
                        f'{esc(band.lower())} {round(100 * n / total)}%</text>')
        x += w
    return svg(width, 52, "".join(body), f"How the {total:,} badged puzzles split across the bands")


def scatter(idx):
    """The badge rating of every rated Times daily against its NITCH minus
    the weekday mean of all rated Times dailies, with the rank correlation of
    exactly the points drawn."""
    sn = difficulty.load_snitch()
    by = {}
    for pid, v in sn.items():
        if pid.rpartition("-")[0] == "times":
            by.setdefault(datetime.fromisoformat(v["date"]).weekday(), []).append(v["nitch"])
    means = {d: sum(x) / len(x) for d, x in by.items()}
    pts = []
    for p in idx["puzzles"]:
        d, v = p.get("difficulty") or {}, sn.get(p.get("id"))
        if v and d.get("index") is not None and p.get("series") == "times":
            pts.append((d["index"], v["nitch"] - means[datetime.fromisoformat(v["date"]).weekday()]))
    if len(pts) < 30:
        return ""
    rho = difficulty._spearman([a for a, _ in pts], [b for _, b in pts])
    xs, ys = sorted(a for a, _ in pts), sorted(b for _, b in pts)
    # The middle 98% sets the axes, so a few outliers do not squash the rest.
    lo_x, hi_x = xs[len(xs) // 100], xs[-1 - len(xs) // 100]
    lo_y, hi_y = ys[len(ys) // 100], ys[-1 - len(ys) // 100]
    W, H, L, B = 520, 300, 40, 30
    def px(a):
        return L + (min(max(a, lo_x), hi_x) - lo_x) / (hi_x - lo_x) * (W - L - 10)
    def py(b):
        return (H - B) - (min(max(b, lo_y), hi_y) - lo_y) / (hi_y - lo_y) * (H - B - 10)
    body = [f'<line class="axis" x1="{L}" y1="{py(0):.1f}" x2="{W - 10}" y2="{py(0):.1f}"/>',
            f'<line class="axis" x1="{px(0):.1f}" y1="10" x2="{px(0):.1f}" y2="{H - B}"/>']
    body += [f'<circle class="dot" cx="{px(a):.1f}" cy="{py(b):.1f}" r="2.2"/>' for a, b in pts]
    body.append(f'<text x="{W - 10}" y="{H - 8}" text-anchor="end">our rating, easier &#8594; harder</text>'
                f'<text x="12" y="{H / 2}" transform="rotate(-90 12 {H / 2})" text-anchor="middle">'
                f"NITCH minus weekday mean</text>"
                f'<text class="big" x="{L + 8}" y="26">rho {signed(rho)}, {len(pts):,} Times puzzles</text>')
    return svg(W, H, "".join(body),
               "Each dot is a Times daily with full hints: the rating its badge shows, posted times "
               "included where there are enough, against how much "
               "slower than usual for its weekday the SNITCH solvers were. The rho is over every dot, "
               "not held out.")


def difficulty_page(idx):
    """Render tools/difficulty_page.html as /difficulty/.

    The prose is hand-written; every number and list is filled in here from
    the code that computes it, so the page cannot describe a rating other than
    the one the badges show. The held-out numbers come from
    tools/data/difficulty_check.json, which the nightly job rewrites, and are
    quoted only if that file was measured under today's weights and baseline.
    """
    text = DIFFICULTY_TEMPLATE.read_text(encoding="utf-8")
    text = re.sub(r"\A<!--.*?-->\n", "", text, flags=re.DOTALL)
    blocks = {m.group(1): (m.group(2).strip(), m.group(3).strip()) for m in COMPONENT.finditer(text)}
    text = text[:m.start()].rstrip() + "\n" if (m := COMPONENT.search(text)) else text
    if set(blocks) != set(difficulty.WEIGHTS):
        raise SystemExit(f"{DIFFICULTY_TEMPLATE.name} describes components "
                         f"{sorted(blocks)}, but difficulty.WEIGHTS has "
                         f"{sorted(difficulty.WEIGHTS)}: add or remove a block to match")

    check = json.loads(difficulty_check.OUT.read_text(encoding="utf-8")) \
        if difficulty_check.OUT.exists() else {}
    live = bool(check) and difficulty_check.current(check)
    order = sorted(difficulty.WEIGHTS, key=lambda k: -difficulty.WEIGHTS[k])
    total = sum(difficulty.WEIGHTS.values())
    comps = []
    for k in order:
        label, prose = blocks[k]
        w = difficulty.WEIGHTS[k]
        alone = (f" &middot; on its own {signed(check['components'][k]['mean'])}"
                 if live and k in check.get("components", {}) else "")
        comps.append(f'<h3 id="{esc(k)}">{esc(label)}</h3>\n'
                     f'<p class="muted">Weight {w:g}, {round(100 * w / total)}% of the rating{alone}</p>\n'
                     f"{prose}")

    base = difficulty.load_baseline()
    blend = base.get("comment_blend") or {}
    blended = listed([f"the {esc(series_name(s))} ({blend[s]['index']['n']:,} puzzles)"
                      for s in sorted(blend, key=lambda s: -blend[s]["index"]["n"])]) or "no series yet"
    labels = {k: blocks[k][0].lower() for k in difficulty.WEIGHTS}
    portable = listed([labels[k] for k in order if k in difficulty.PORTABLE])

    if live:
        h, b = check["heldout"], check["blended"]
        def row(name, key):
            c, cb = h[key], b[key]
            return (f"<tr><td>{name}</td><td>{c['n']:,}</td><td>{signed(c['mean'])}</td>"
                    f"<td>{signed(cb['mean'])}</td></tr>")
        checks = ("<table><tr><th>Puzzles tested</th><th>Number</th><th>Clue rating</th>"
                  "<th>With posted times</th></tr>"
                  + row("Times, with our hints", "annotated")
                  + row("Times, not yet explained (measures that need no hints)", "unannotated")
                  + row("Sunday Times, with our hints (plain NITCH)", "sunday")
                  + "</table>"
                  f'<p class="muted">Each figure is the average over the three periods. Measured '
                  f"on SNITCH ratings up to {esc(check['snitch_newest'])}.</p>")
        g = check["gentle_margin"]
        margin = (f"The rating puts them {g['margin']:.2f} standard deviations below the other "
                  f"series ({g['gentle_n']:,} gentle puzzles against {g['other_n']:,} others). "
                  f"A change that pushed this below {g['floor']:g} would be rejected.")
    else:
        checks = ("<p>These figures are being re-measured for the current version of the "
                  "rating and will be back after the next nightly run.</p>")
        margin = ("The rating has to put them clearly below the other series, by at least "
                  f"{difficulty.MARGIN_FLOOR:g} standard deviations.")

    fill = {"bands": difficulty_bands(idx), "bands_chart": bands_chart(idx),
            "weights_chart": weights_chart(order, {k: blocks[k][0] for k in order}),
            "scatter": scatter(idx), "component_count": str(len(order)),
            "components": "\n".join(comps), "comment_min_times": str(difficulty.COMMENT_MIN_TIMES),
            "comment_series_min": str(difficulty.COMMENT_SERIES_MIN), "blended_series": blended,
            "checks": checks, "margin": margin, "portable_measures": portable}
    text = re.sub(r"\{\{(\w+)\}\}", lambda m: fill.pop(m.group(1)), text)
    if fill:
        raise SystemExit(f"{DIFFICULTY_TEMPLATE.name} never uses "
                         + ", ".join("{{" + k + "}}" for k in fill))

    title = "How the difficulty rating works"
    desc = ("How Cryptic Teacher rates a cryptic crossword gentle, moderate, tough or brutal: "
            "what it measures, how each part is weighted, and how it is checked against real "
            "solve times.")
    canonical = f"{BASE}/difficulty/"
    crumbs = [("Cryptic Teacher", "/"), ("How difficulty is rated", "")]
    page_ld = {"@context": "https://schema.org", "@type": "Article",
               "headline": title, "url": canonical, "description": desc,
               "isAccessibleForFree": True}
    body = [masthead(crumbs), '<main class="static-main tutorial-static">',
            f"<h1>{title}</h1>", text,
            f'<p class="s-cta"><a class="cta" href="{BASE}/">Pick a puzzle &rarr;</a></p>',
            "</main>"]
    return head(title, desc, canonical, ld(page_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


# -------------------------------------------------------------- progress page

RATE_DAYS = 60   # days of per-day bars /progress/ draws
# The funnel's stages, in progress.nested()'s order: the bars and the table
# both draw these, with these labels and colour classes, and nothing else.
FUNNEL_LABEL = ("known to exist", "downloaded", "filed", "solved", "hinted")
FUNNEL_CLASS = ("known", "queued", "filed", "solved", "hinted")
S_KNOWN, S_DOWNLOADED, S_FILED, S_SOLVED, S_HINTED = range(5)
# The running-totals chart's own lines beyond the funnel's stages: the raw
# counts the history records, not nested(), whose downloaded is filed plus the
# unread and so follows filed by construction (Paul 10-17: "why does it track
# the download line so well").
L_SCANS, L_UNREAD = "scans", "backlog"
LINE_LABEL = {S_FILED: "filed", S_HINTED: "hinted", L_SCANS: "scans on disk", L_UNREAD: "scans not read"}
LINE_CLASS = {S_FILED: "filed", S_HINTED: "hinted", L_SCANS: "queued", L_UNREAD: "backlog"}
# Solved is not paced: answers are found in the session that hints the puzzle,
# so it moves with hinted and has no pace of its own.
PACED = (S_KNOWN, S_DOWNLOADED, S_FILED, S_HINTED)


def short_day(iso):
    return datetime.fromisoformat(iso).strftime("%-d %b")


def nice_step(top, ticks=4):
    """A 1, 2 or 5 times a power of ten that cuts 0..top into about `ticks`."""
    raw = max(top, 1) / ticks
    mag = 10 ** (len(str(int(raw))) - 1)
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)


def at_pace(remaining, per_day):
    """How long `remaining` takes at `per_day`, in words."""
    if remaining <= 0:
        return "done"
    if not per_day or per_day <= 0:
        return "not moving"
    days = remaining / per_day
    if days < 60:
        return f"{max(1, round(days))} days"
    if days < 730:
        return f"{round(days / 30.4)} months"
    return f"{days / 365.25:.0f} years"


def funnel_chart(stages):
    """One bar a stage of progress.nested_totals() (known, downloaded, filed,
    solved, hinted), each inside the one above it, as a share of the puzzles
    known to exist. Every bar has the same form; downloaded less filed is
    what is not read yet."""
    known = stages[S_KNOWN]
    rowh, left, width = 30, 110, 400
    body = []
    for i, n in enumerate(stages):
        y = i * rowh
        body.append(f'<text x="{left - 8}" y="{y + 18}" text-anchor="end">{FUNNEL_LABEL[i]}</text>'
                    f'<rect class="track" x="{left}" y="{y + 5}" width="{width}" height="18"/>'
                    f'<rect class="ph-{FUNNEL_CLASS[i]}" x="{left}" y="{y + 5}" '
                    f'width="{width * n / known:.1f}" height="18"/>'
                    f'<text x="{left + width + 6}" y="{y + 18}">{n:,} · {pct(n, known)}</text>')
    return svg(left + width + 190, 5 * rowh + 4, "".join(body),
               f"Each stage inside the one above, out of the {known:,} puzzles known to exist")


KEY_EM = .66      # a bold label's width a character, in ems: generous, so a serif fallback fits too
KEY_PX = 11       # .chart text's font-size in style.css
KEY_GAP = 13      # the least distance between two end labels' baselines
FLOOR = .02       # a line under this share of the y axis still reads as flat
MIN_SPAN = 14     # the trimmed axis never shows fewer days than this


def key_width(text):
    """How wide an end label may draw, in viewBox units (an over-estimate)."""
    return len(text) * KEY_PX * KEY_EM


def chart_start(lines, ymax, first, last):
    """Where the running-totals axis starts: a little before the first day any
    line rises visibly off the floor, so a long flat lead-in does not take
    the width (Paul 10-12: "it goes far back without much resolution"). Never
    later than MIN_SPAN days before the end, never before the first day held."""
    moving = [d for pts in lines.values() for d, n in pts if n > FLOOR * ymax]
    if not moving:
        return first
    m = datetime.fromisoformat(min(moving))
    pad = timedelta(days=max(2, round((last - m).days * .08)))
    return max(first, min(m - pad, last - timedelta(days=MIN_SPAN)))


def day_ticks(start, last, width):
    """Days to label on the x axis: counted back from the last day by a step
    of 1, 2, 3 days, a week, a fortnight ... chosen so about five fit."""
    span = max((last - start).days, 1)
    most = max(2, min(6, int(width // 70)))
    step = next((s for s in (1, 2, 3, 7, 14, 28, 56, 91, 182, 364, 728) if span / s < most), 1456)
    ticks, d = [], last
    while d >= start:
        ticks.append(d)
        d -= timedelta(days=step)
    return ticks[::-1]


def line_points(days, key, recorded=None):
    """[(day, total)] for one running-totals line: filed and hinted from
    progress.funnel_series, the scans on disk and the unread backlog as
    recorded (progress.series_of), so each has a slope of its own."""
    if key in (L_SCANS, L_UNREAD):
        phase = progress.DOWNLOADED if key == L_SCANS else progress.QUEUED
        pts = progress.series_of(days, phase)
        if recorded is not None:
            # with_today() carries the newest recorded count onto a day whose
            # row is not written yet; drawn, that is a flat last segment.
            counted = {d for d, v in progress.series_of(recorded, phase)}
            pts = [p for p in pts if p[0] in counted]
        return pts
    return progress.funnel_series(days, key)


def cumulative_chart(days, full=False, recorded=None):
    """Scans on disk, scans not read, filed and hinted's running totals, one
    line each over the days it was counted; a line counted on one day
    only has no line yet. The axis starts where the lines start to move
    (chart_start) unless `full`; returns (svg, trimmed). The end labels' margin
    is measured from their own text, so a longer number never runs off the side."""
    lines = {st: pts for st in (L_SCANS, L_UNREAD, S_FILED, S_HINTED)
             if len(pts := line_points(days, st, recorded)) > 1}
    if not lines:
        return "", False
    first = datetime.fromisoformat(next(iter(days)))
    last = datetime.fromisoformat(next(reversed(days)))
    top = max(n for pts in lines.values() for _, n in pts)
    step = nice_step(top)
    ymax = step * -(-top // step)
    start = first if full else chart_start(lines, ymax, first, last)
    if start > first:
        # A line enters at the axis with its last count before it.
        cut = start.date().isoformat()
        lines = {st: ([(cut, before[-1][1])] if (before := [p for p in pts if p[0] < cut]) else [])
                 + [p for p in pts if p[0] >= cut] for st, pts in lines.items()}
        lines = {st: pts for st, pts in lines.items() if len(pts) > 1}
    span = max((last - start).days, 1)
    keys = {st: f"{LINE_LABEL[st]} {pts[-1][1]:,}" for st, pts in lines.items()}
    W, H, L, T, B = 640, 260, 52, 10, 24
    R = 6 + max(map(key_width, keys.values())) + 4
    def px(d):
        return L + (datetime.fromisoformat(d) - start).days / span * (W - L - R)
    def py(n):
        return T + (1 - n / ymax) * (H - T - B)
    body = []
    for v in range(0, ymax + 1, step):
        body.append(f'<line class="grid" x1="{L}" y1="{py(v):.1f}" x2="{W - R:.1f}" y2="{py(v):.1f}"/>'
                    f'<text x="{L - 6}" y="{py(v) + 4:.1f}" text-anchor="end">{v:,}</text>')
    body += [f'<text class="tick" x="{px(d.date().isoformat()):.1f}" y="{H - 6}" text-anchor="middle">'
             f'{short_day(d.date().isoformat())}</text>' for d in day_ticks(start, last, W - L - R)]
    ends = []
    for st, pts in lines.items():
        xy = " ".join(f"{px(d):.1f},{py(n):.1f}" for d, n in pts)
        body.append(f'<polyline class="line ph-{LINE_CLASS[st]}" points="{xy}"/>')
        ends.append([py(pts[-1][1]), keys[st], LINE_CLASS[st]])
    # End labels pushed apart so two close lines do not print over each other,
    # then back up from the floor if the push ran them past it.
    ends.sort()
    for a, b in zip(ends, ends[1:]):
        b[0] = max(b[0], a[0] + KEY_GAP)
    ends[-1][0] = min(ends[-1][0], H - B)
    for a, b in zip(ends[-2::-1], ends[::-1]):
        a[0] = min(a[0], b[0] - KEY_GAP)
    body += [f'<text class="ph-{cls} key" x="{W - R + 6:.1f}" y="{y + 4:.1f}">{text}</text>'
             for y, text, cls in ends]
    since = f" since {short_day(start.date().isoformat())}" if start > first else ""
    return svg(W, H, "".join(body), f"Running totals by day{since}: filed and hinted as in the bars, scans as recorded, "
               "scans from the first night the read queue was counted"), start > first


def rate_chart(days, st):
    """The funnel stage's gain each day over the last RATE_DAYS, with its 7-day
    pace as a line. A day taller than the chart is cut off and its number printed."""
    name = FUNNEL_CLASS[st]
    pts = progress.funnel_series(days, st)
    gains = progress.daily(pts)[-RATE_DAYS:]
    if not gains:
        return ""
    per7 = progress.rate(pts, 7) or 0
    vals = sorted(max(g, 0) for _, g in gains)
    cap = max(vals[int(len(vals) * .9)] * 1.5, per7 * 1.5, 1)
    W, H, L, T, B = 640, 140, 52, 26, 20
    slot = (W - L) / RATE_DAYS
    def py(n):
        return T + (1 - min(n, cap) / cap) * (H - T - B)
    body = [f'<line class="axis" x1="{L}" y1="{H - B}" x2="{W}" y2="{H - B}"/>',
            f'<text x="{L - 6}" y="{py(cap) + 4:.1f}" text-anchor="end">{cap:,.0f}</text>',
            f'<text x="{L - 6}" y="{H - B + 4}" text-anchor="end">0</text>']
    x0 = L + (RATE_DAYS - len(gains)) * slot
    last_cut, y = -2, T - 3
    for i, (d, g) in enumerate(gains):
        x = x0 + i * slot
        g = max(g, 0)
        body.append(f'<rect class="ph-{name}" x="{x + 1:.1f}" y="{py(g):.1f}" '
                    f'width="{max(slot - 2, 1):.1f}" height="{H - B - py(g):.1f}"><title>'
                    f'{short_day(d)}: {g:,}</title></rect>')
        if g > cap:
            # Two cut days in a row print on two rows, so their numbers stay apart.
            y = T - 15 if i - last_cut == 1 and y == T - 3 else T - 3
            last_cut = i
            body.append(f'<text x="{x + slot / 2:.1f}" y="{y}" text-anchor="middle">'
                        f'{g / 1000:.1f}k</text>' if g >= 1000 else
                        f'<text x="{x + slot / 2:.1f}" y="{y}" text-anchor="middle">{g}</text>')
    for i, anchor in ((0, "start"), (len(gains) // 2, "middle"), (len(gains) - 1, "end")):
        x = x0 + {"start": 0, "middle": .5, "end": 1}[anchor] * slot + i * slot
        body.append(f'<text x="{x:.1f}" y="{H - 5}" text-anchor="{anchor}">'
                    f'{short_day(gains[i][0])}</text>')
    body.append(f'<line class="pace" x1="{L}" y1="{py(per7):.1f}" x2="{W}" y2="{py(per7):.1f}"/>')
    return svg(W, H, "".join(body), f"Puzzles {FUNNEL_LABEL[st]} a day, last {len(gains)} days"
               f" · dashed: {per7:,.0f} a day over the last week")


def series_chart(row, pages=()):
    """One bar a series, its known puzzles split by progress.nested() into
    hinted, solved, filed, downloaded but not read and the rest
    still to find. A series in `pages` (those with a series page) is one link,
    the whole row, to that page (Paul 10-12: "clicking By series should take
    you to that series")."""
    chain = {s: progress.nested(c) for s, c in row.items()}
    order = sorted((s for s in chain if chain[s][0]), key=lambda s: -chain[s][0])
    rowh, left, width = 24, 220, 330
    body = []
    for i, s in enumerate(order):
        known, downloaded, filed, solved, hinted = chain[s]
        y, x = i * rowh, float(left)
        if s in pages:
            body.append(f'<a class="row" href="{site_url(series_path(s))}"><title>All '
                        f'{esc(series_name(s))} puzzles</title><rect class="hit" x="0" y="{y}" '
                        f'width="{left + width + 190}" height="{rowh}"/>')
        body.append(f'<text x="{left - 8}" y="{y + 16}" text-anchor="end">{esc(series_name(s))}</text>'
                    f'<rect class="track" x="{left}" y="{y + 4}" width="{width}" height="16"/>')
        done = 0
        for n, cls in ((hinted, "hinted"), (solved, "solved"), (filed, "filed"),
                       (downloaded, "queued")):
            w = width * (n - done) / known
            if w > 0:
                body.append(f'<rect class="ph-{cls}" x="{x:.1f}" y="{y + 4}" width="{w:.1f}" height="16"/>')
            x += w
            done = n
        body.append(f'<text x="{left + width + 6}" y="{y + 16}">{filed:,} of {known:,} filed'
                    f' · {pct(hinted, known)} hinted</text>' + ("</a>" if s in pages else ""))
    return svg(left + width + 190, len(order) * rowh + 4, "".join(body),
               "Each series: hinted, then solved, then filed, then downloaded but not read, "
               "out of the puzzles known to exist (the grey is still to find)")


def queue_depths(c):
    """(to fetch, read failed, to read, to annotate) for one series' row c.
    To fetch is puzzles known to exist that we do not hold: known less the
    larger of downloaded and filed plus queued (a series filed from a blog
    or an API has far more filed than downloaded scans, so downloaded alone
    would overcount). Read failed is scans downloaded that were read and
    gave no puzzle (downloaded less filed less queued). To read is scans on
    disk not read (queued); to annotate is filed puzzles with a clue
    unexplained (filed less hinted). A queue the row has no count for is
    None; none is below 0."""
    known, _, filed, _, hinted, downloaded, queued = c
    if known is None or queued is None:
        fetch = failed = None
    else:
        fetch = max(known - max(downloaded or 0, filed + queued), 0)
        failed = max((downloaded or 0) - filed - queued, 0)
    return fetch, failed, queued, max(filed - hinted, 0)


def held_series(days):
    """[(day, filed + queued)] over the nights that record both."""
    pts = []
    for d, row in days.items():
        t = progress.totals(row)
        if t[progress.QUEUED] is not None:
            pts.append((d, t[progress.FILED] + t[progress.QUEUED]))
    return pts


def queue_flows(days, window):
    """((fetch in, out), (read in, out), (annotate in, out)) a day over the
    last `window` days of the recorded nights `days`, a part None where a
    phase has fewer than two nights. Into fetch is known's gain (negative
    when the known count falls), out is the gain in filed plus queued, all
    we hold; into read is the gain in queued plus read-out; out of read is
    filed's gain (a scan read for nothing, or a puzzle filed from another
    source, makes that only a proxy); into annotate is filed's gain, out is
    hinted's."""
    g = {ph: progress.rate(progress.series_of(days, ph), window)
         for ph in (progress.KNOWN, progress.FILED, progress.HINTED, progress.QUEUED)}
    held = progress.rate(held_series(days), window)
    read_in = None if g[progress.QUEUED] is None or g[progress.FILED] is None \
        else g[progress.QUEUED] + g[progress.FILED]
    return ((g[progress.KNOWN], held),
            (read_in, g[progress.FILED]),
            (g[progress.FILED], g[progress.HINTED]))


def flow_text(flow):
    i, o = flow
    if i is None and o is None:
        return "needs 2 nights"
    def signed(n, sign):
        n = round(n * sign)
        return "0" if n == 0 else f"+{n:,}" if n > 0 else f"&minus;{-n:,}"
    return f"{'?' if i is None else signed(i, 1)} / {'?' if o is None else signed(o, -1)}"


def queue_cell(depth, flow):
    return "&mdash;" if depth is None else f'{depth:,} <span class="muted">({flow_text(flow)})</span>'


def queue_table(row, recorded):
    """The queues by series: to fetch, read failed, to read, to annotate, each
    its depth in `row` and (but read failed) its 7-day flow a day over the
    `recorded` nights.
    Series with every queue empty are left out; the biggest queue ranks
    first; the last row is the total."""
    depths = {s: queue_depths(c) for s, c in row.items()}
    shown = sorted((s for s, d in depths.items() if any(d)),
                   key=lambda s: -max(n or 0 for n in depths[s]))

    def cells(d, flows, tag):
        # Read failed (second) has no flow: it is a leftover, not a pipe.
        fl = [flows[0], None, flows[1], flows[2]]
        return "".join(f"<{tag}>{queue_cell(n, f) if f else '&mdash;' if n is None else f'{n:,}'}</{tag}>"
                       for n, f in zip(d, fl))
    rows = []
    for s in shown:
        one = {d: {s: r[s]} for d, r in recorded.items() if s in r}
        rows.append(f"<tr><td>{esc(series_name(s))}</td>" + cells(depths[s], queue_flows(one, 7), "td") + "</tr>")
    tot = [sum(d[i] or 0 for d in depths.values()) for i in range(4)]
    rows.append("<tr><th>All series</th>" + cells(tot, queue_flows(recorded, 7), "th") + "</tr>")
    return ("<table><tr><th>Series</th><th>To fetch</th><th>Read failed</th><th>To read</th>"
            "<th>To annotate</th></tr>"
            + "".join(rows) + "</table>")


def fetching_note(cur):
    """The line under the queues table saying where the Gale downloader is, from
    the nightly record (progress.load_fetching()); "" when none."""
    if not cur or not cur.get("year"):
        return ""
    n = cur["left"]
    return (f'<p class="muted small-note">Fetching: Gale ({esc(cur["paper"])}), working '
            f'{"back through" if cur.get("back") else "forward through"} {cur["year"]} '
            f'({n:,} {"page" if n == 1 else "pages"} left in that bucket), as of the '
            f'{short_day(cur["at"])} night count.</p>')


def pace_cells(pts, today):
    """(7-day cell, 30-day cell, 7-day pace or None) for a funnel_series().
    A window longer than the history held shows its real span in days; the
    30-day cell is blank rather than repeat the 7-day one when under 7 days
    are held."""
    per7, per30 = progress.rate(pts, 7), progress.rate(pts, 30)
    if per7 is None:
        return "&mdash;", "&mdash;", None
    held = (datetime.fromisoformat(today) - datetime.fromisoformat(pts[0][0])).days
    c7 = f"{round(per7):,}" + ("" if held >= 7 else f" ({held} days)")
    c30 = ("&mdash;" if held < 7 or per30 is None else
           f"{round(per30):,}" + ("" if held >= 30 else f" ({held} days)"))
    return c7, c30, per7


def progress_page(idx, today=None, now=None):
    """/progress/: tools/progress.py's history with today's index as its last
    day, as totals, paces and charts. Filed, solved and hinted are this
    build's (every deploy); the rest are the newest recorded night's. now is
    the build's London time the page says it is as of."""
    if now is None and today is None:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/London"))
    today = (today or now.date()).isoformat()
    as_of = f"{now:%H:%M} on {short_day(today)}" if now else short_day(today)
    files = progress.index_counts(idx["puzzles"])
    recorded = progress.load()
    days = progress.with_today(recorded, files, today)
    # One source for every number on the page: the bars, the table and the
    # text all read progress.nested_totals() / funnel_series().
    stages = progress.nested_totals(days[today])
    known = stages[S_KNOWN]
    queued = progress.totals(days[today])[progress.QUEUED]
    rows = []
    for st, n in enumerate(stages):
        c7 = c30 = forecast = ""
        if st in PACED:
            c7, c30, per7 = pace_cells(progress.funnel_series(days, st), today)
            if st != S_KNOWN:
                forecast = at_pace(known - n, per7) if per7 is not None else "&mdash;"
        rows.append(f'<tr><td><span class="key-dot ph-{FUNNEL_CLASS[st]}"></span>{FUNNEL_LABEL[st]}</td>'
                    f"<td>{n:,}</td><td>{pct(n, known)}</td><td>{c7}</td>"
                    f'<td class="wide">{c30}</td><td>{forecast}</td></tr>')
    table = ('<table class="progress-table"><tr><th>Stage</th><th>Puzzles</th><th>Of known</th>'
             '<th>7-day pace</th><th class="wide">30-day pace</th><th>All known in</th></tr>'
             + "".join(rows) + "</table>")
    recent, trimmed = cumulative_chart(days, recorded=recorded)
    title = "Progress: every puzzle, downloaded, solved and hinted"
    desc = (f"How far Cryptic Teacher has got: {stages[S_DOWNLOADED]:,} of the {known:,} cryptic "
            f"crosswords known to exist downloaded, {stages[S_SOLVED]:,} solved and "
            f"{stages[S_HINTED]:,} with full hints, and how fast each is moving.")
    canonical = f"{BASE}/progress/"
    crumbs = [("Cryptic Teacher", "/"), ("Progress", "")]
    page_ld = {"@context": "https://schema.org", "@type": "Article", "headline": title,
               "url": canonical, "description": desc, "isAccessibleForFree": True}
    body = [masthead(crumbs), '<main class="static-main tutorial-static">', f"<h1>{title}</h1>",
            f'<p class="muted">As of {as_of}.'
            + (f" {queued:,} scans downloaded, not read yet." if queued is not None else "")
            + "</p>",
            funnel_chart(stages), table,
            '<p class="muted small-note">Each bar sits inside the one above. Downloaded is filed '
            "plus scans not read. Filed, solved and hinted are recounted every time the site "
            "updates; known and downloaded once a night.</p>",
            *(("<h2>The queues</h2>",
               '<p class="muted small-note">Depth now (flow a day over 7 days: in / out). '
               "Read failed is scans read that gave no puzzle.</p>",
               queue_table(days[today], recorded),
               fetching_note(progress.load_fetching())) if queued is not None else ()),
            "<h2>Running totals</h2>", recent,
            *((f"<details><summary>All time, from {short_day(next(iter(days)))}</summary>",
               cumulative_chart(days, full=True, recorded=recorded)[0], "</details>") if trimmed else ()),
            "<h2>A day at a time</h2>",
            *(rate_chart(days, st) for st in (S_FILED, S_HINTED)),
            "<h2>By series</h2>", series_chart(days[today], set(listings(idx))),
            f'<p class="s-cta"><a class="cta" href="{BASE}/">Pick a puzzle &rarr;</a></p>',
            "</main>"]
    return head(title, desc, canonical, ld(page_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


# -------------------------------------------------------------- showcase page

def showcase_page(secs, meta):
    """/showcase/: tools/showcase.py's sections, each a heading, one sentence
    on what makes its puzzles unusual, their archive rows, and a link to the
    whole ranked list where the section has more than it shows."""
    title = "Unusual cryptic crosswords: hidden messages, jigsaws and records"
    desc = ("Cryptic crosswords with something special about them: messages hidden in "
            "the grid, jigsaw grids, every letter of the alphabet, unusual grid shapes, the "
            "longest answers, the hardest and the oldest puzzles.")
    canonical = f"{BASE}/showcase/"
    crumbs = [("Cryptic Teacher", "/"), ("Unusual puzzles", "")]
    body = [masthead(crumbs), '<main class="static-main">',
            "<h1>Unusual puzzles</h1>",
            "<p>Most cryptic crosswords follow the same pattern. These break it, or set "
            "a record. Each one opens ready to solve, with hints one step at a time.</p>",
            '<p class="s-years">' + build_abbreviations.LIST_SEP.join(
                f'<a href="#{slug}">{esc(heading)}</a>' for slug, heading, *_ in secs)
            + "</p>"]
    for slug, heading, blurb, cards, full in secs:
        more = (f'<p class="s-more"><a href="{BASE}/showcase/{slug}/">'
                f"{esc(heading)}: {full[2]} &rarr;</a></p>" if full else "")
        body += [f'<section id="{slug}"><h2>{esc(heading)}</h2>', f"<p>{esc(blurb)}</p>",
                 '<ul class="s-index">'
                 + "".join(hub_row(meta[f["id"]], note) for f, note in cards)
                 + "</ul>" + more + "</section>"]
    body += [f'<p class="s-cta"><a class="cta" href="{BASE}/puzzles/">All puzzles, by paper '
             "and year &rarr;</a></p>", "</main>"]
    list_ld = {"@context": "https://schema.org", "@type": "CollectionPage",
               "name": title, "url": canonical, "description": desc}
    return head(title, desc, canonical, ld(list_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


def showcase_list_pages(secs, meta):
    """/showcase/<slug>/: one showcase section's whole ranked list, for every
    section with more than /showcase/ has room for."""
    for slug, heading, _, _, full in secs:
        if not full:
            continue
        blurb, cards, label = full
        title = f"{heading}: {label}, cryptic crosswords"
        canonical = f"{BASE}/showcase/{slug}/"
        crumbs = [("Cryptic Teacher", "/"), ("Unusual puzzles", "/showcase/"),
                  (heading, "")]
        body = [masthead(crumbs), '<main class="static-main">',
                f"<h1>{esc(heading)}</h1>", f"<p>{esc(blurb)}</p>",
                '<ul class="s-index">'
                + "".join(hub_row(meta[f["id"]], note) for f, note in cards) + "</ul>",
                f'<p class="s-cta"><a class="cta" href="{BASE}/showcase/">More unusual '
                "puzzles &rarr;</a></p>", "</main>"]
        list_ld = {"@context": "https://schema.org", "@type": "CollectionPage",
                   "name": title, "url": canonical, "description": blurb}
        yield (ROOT / "showcase" / slug / "index.html",
               head(title, blurb, canonical, ld(list_ld) + ld(breadcrumb_ld(crumbs)))
               + "\n".join(body) + "\n" + FOOTER)


# --------------------------------------------------------- abbreviations page

_NOT_AZ09 = re.compile(r"[^A-Z0-9]")


def letters_of(s):
    """A block's `gives` and a glossary key reduced to the same comparable form."""
    return _NOT_AZ09.sub("", (s or "").upper())


def fragment_re(word):
    """The word as it may appear in a clue fragment: whole, singular or plural.

    Nothing looser. A link from the glossary is a promise that the clue at the
    other end uses this convention, and a solver who follows "car" into a clue
    about care has been sent somewhere worse than nowhere.
    """
    tail = "(?:es)?" if re.search(r"(?:s|x|z|ch|sh)$", word) else "s?"
    return re.compile(r"\b" + re.escape(word) + tail + r"\b")


def clue_blocks(blocks, puz, page):
    """Add one puzzle's annotated wordplay to blocks, {letters: [candidate]},
    for clue_links() to choose from.

    Every candidate is verified against the puzzle page this same run writes,
    anchor included, so the glossary can never outlive the clue it cites. It is
    called with each page as it is rendered, because the pages are not kept.
    """
    for e in puz["entries"]:
        ann = e.get("annotation") or {}
        if f'id="{esc(entry_id(e))}"' not in page:
            continue
        prose = ann.get("explanation") or {}
        depth = len((prose.get("walkthrough") or "") + (prose.get("definitionFit") or ""))
        for b in ann.get("blocks") or []:
            frag = (b.get("clueFragment") or "").lower()
            key = letters_of(b.get("gives"))
            if key and frag:
                blocks.setdefault(key, []).append(
                    (frag, depth + len(b.get("note") or ""),
                     (series_meta.puzzle_day(puz) or date.min).toordinal(), puz["id"], entry_id(e)))


def clue_links(senses, blocks):
    """word -> the URL of one annotated clue whose wordplay uses that convention.

    A word matches a block when the block's letters are one of that word's
    senses and the block's clue fragment contains the word. Words no clue can be
    shown to use stay plain text; the glossary lists more conventions than the
    archive has yet demonstrated, and a link nobody can check is a false
    claim.

    Where several clues qualify: the one in the puzzle carrying the fewest
    glossary links so far, so the glossary's rows lead into the whole archive
    rather than all into one puzzle; then the fullest annotation; then the
    newest puzzle. Nothing is broken by chance — an unstable choice would make
    the nightly rebuild commit churn.
    """
    used, out = {}, {}
    for word in sorted(senses):
        pat = fragment_re(word)
        found = [c for k in senses[word] for c in blocks.get(letters_of(k), [])
                 if pat.search(c[0])]
        if not found:
            continue
        _, _, _, pid, eid = min(found, key=lambda c: (used.get(c[3], 0), -c[1], -c[2],
                                                      c[3], c[4]))
        used[pid] = used.get(pid, 0) + 1
        out[word] = solve_url(pid, eid)
    return out


# How many readings the "Most common" list shows: the head a new solver should
# learn first. The rest are in the A-to-Z list below it, each with its count.
COMMON_TOP = 40


def abbreviations_page(blocks):
    """The glossary as a document of its own.

    A lookup table is a destination, not a chapter: somebody who wants to know
    what CH means in a crossword is not reading a beginner's guide, and a query
    that specific deserves a URL that answers it in the first screen. Rendered
    from build_abbreviations.table() through the same function that writes the
    in-app table, so the page a search lands on and the row a hint jumps to
    cannot disagree.
    """
    senses = build_abbreviations.by_word()
    n = len(senses)
    links = clue_links(senses, blocks)
    title = f"Cryptic crossword abbreviations — {n:,} of them, A to Z"
    desc = (f"All {n:,} abbreviations cryptic crossword setters use in these puzzles, listed "
            "by word: street is ST, company is CO, right is R. Every one comes from a real "
            f"published puzzle, and {len(links):,} of them link to a clue that uses it, "
            "explained.")
    canonical = f"{BASE}/abbreviations/"
    crumbs = [("Cryptic Teacher", "/"), ("How cryptic clues work", "/learn/"),
              ("Abbreviations", "")]
    page_ld = {"@context": "https://schema.org", "@type": "DefinedTermSet",
               "name": "Cryptic crossword abbreviations", "url": canonical,
               "description": desc,
               "hasDefinedTerm": [
                   {"@type": "DefinedTerm", "name": w,
                    "description": f"stands for {', '.join(sorted(senses[w]))}",
                    "url": f"{canonical}#{build_abbreviations.anchor(w)}"}
                   for w in sorted(senses)]}
    body = [
        masthead(crumbs),
        '<main class="static-main tutorial-static">',
        "<h1>Cryptic crossword abbreviations</h1>",
        "<p>Setters often swap a word for a short, fixed set of letters. <em>Street</em> "
        "becomes <code>ST</code>. <em>Company</em> becomes <code>CO</code>. Each is the "
        "dictionary's abbreviation of its word, but which letters a setter picks you "
        "cannot work out from the word alone. You have to know them, so they are the quickest thing a new "
        "solver can learn.</p>",
        "<p>You will meet them most in charades, where the answer is built from small "
        "pieces: <em>company</em> + <em>street</em> gives CO + ST, which is COST. Some words "
        "stand for more than one set of letters. Try each one until the pieces build a word "
        "that matches the definition.</p>",
        "<p>Find the word from your clue; the letters it stands for are next to it, "
        "most used first, each with the number of clues in these puzzles that use it. "
        "Every one is an abbreviation Wiktionary or Wikipedia's list of crossword "
        "abbreviations gives and a clue "
        "here uses, plus the codes in the sets below.</p>",
        f"<p>{len(links):,} of the words are links to a real clue that uses that "
        "abbreviation, explained step by step.</p>",
        '<h2 id="most-common">Most common</h2>',
        f"<p>The {COMMON_TOP} abbreviations clues use most, with how many clues used "
        "each. Learn these first.</p>",
        build_abbreviations.common_html(senses, COMMON_TOP),
        '<h2 id="families">Families to learn whole</h2>',
        "<p>Some abbreviations come in sets. Learn the set once and you know every "
        "member. The sets, and the members of each, run most used first.</p>",
        build_abbreviations.families_html(),
        '<h2 id="a-to-z">A to Z</h2>',
        build_abbreviations.table_html(senses, links),
        f'<p class="s-cta"><a class="cta" href="{BASE}/learn/">New to cryptics? '
        f'Learn how the clues work &rarr;</a></p>',
        "</main>",
    ]
    return head(title, desc, canonical, ld(page_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


# ------------------------------------------------------------ indicators page

INDICATORS = ROOT / "tools" / "data" / "lexicons" / "indicators.json"
# Page order and the one-line lesson for each clue_types name indicators.json keys.
INDICATOR_TYPES = {
    "anagram": "Mix up the letters of the fodder next to it. <em>Out</em>, <em>new</em> "
               "and <em>drunk</em> all say the letters are in a mess.",
    "container": "Put one piece inside another. <em>About</em>, <em>holding</em> and "
                 "<em>wearing</em> say which piece goes round which.",
    "reversal": "Read a piece backwards. <em>Back</em> and <em>returned</em> are the "
                "usual words; in a down clue, <em>up</em> and <em>raised</em>.",
    "hidden_word": "The answer is written out in the clue, running across the words. "
                   "<em>Some</em> and <em>part of</em> tell you to look for it.",
    "homophone": "The answer sounds like another word. <em>We hear</em>, "
                 "<em>reportedly</em> and <em>on the radio</em> point at sound.",
    "deletion": "Take letters away. <em>Almost</em> and <em>endlessly</em> drop the last "
                "letter; <em>headless</em> drops the first.",
    "letter_selection": "Take only some letters. <em>Initially</em> gives first letters, "
                        "<em>finally</em> last ones, and <em>regularly</em> every other one.",
    "charade": "Put pieces side by side. These words tell you the order: "
               "<em>following</em> and <em>behind</em> put one piece after another.",
    "spoonerism": "Swap the first sounds of two words, as Dr Spooner was said to do: "
                  "<em>tons of soil</em> for <em>sons of toil</em>.",
}
assert set(INDICATOR_TYPES) <= set(clue_types.NAMES)

# Ops the blog-voted indicators.json never names but our annotations do, read
# from tools/data/indicator_roles.json (tools/build_indicator_roles.py): the
# annotated corpus's count of each indicator word per op. They follow the
# types above, after the lexicon's own.
ROLE_INDICATOR_TYPES = {
    "substitution": "Swap one piece for another. <em>For</em>, <em>replacing</em> and "
                    "<em>instead of</em> say which letters come out and which go in.",
    "cycling": "Move the end letters round to the other end. <em>Cycling</em>, "
               "<em>first to last</em> and <em>back to front</em> turn ROTA into OTAR.",
    "palindrome": "The answer reads the same both ways. <em>Either way</em> and "
                  "<em>whichever way you look at it</em> say so.",
}
ROLE_MIN_USES, ROLE_MIN_SHARE = 20, 0.5
INDICATOR_TYPES.update(ROLE_INDICATOR_TYPES)
assert set(INDICATOR_TYPES) <= set(clue_types.NAMES)

# The kinds of letter selection and deletion, from tools/data/indicator_kinds.json
# (tools/build_indicator_roles.py): {page section: (parent type, kind key, label,
# lesson)}. They are not clue types, so each has a label of its own and sits
# on the page after its parent; a clue links to one when its indicator is
# that parent's and the corpus files the word under that kind.
INDICATOR_KINDS = {
    "first_letters": ("letter_selection", "letter_selection:first", "first-letter",
                      "Take the first letter of each word. <em>Initially</em>, <em>at first</em> "
                      "and <em>leader of</em> point at the start."),
    "last_letters": ("letter_selection", "letter_selection:last", "last-letter",
                     "Take the last letter. <em>Finally</em>, <em>ultimately</em> and "
                     "<em>end of</em> point at the finish."),
    "middle_letters": ("letter_selection", "letter_selection:middle", "middle-letter",
                       "Take the letter or letters in the middle. <em>Heart of</em>, "
                       "<em>centre of</em> and <em>core of</em> point inside."),
    "outer_letters": ("letter_selection", "letter_selection:outer", "outer-letter",
                      "Take the first and last letters. <em>Extremely</em>, <em>case of</em> "
                      "and <em>on vacation</em> point at both ends."),
    "alternate_letters": ("letter_selection", "letter_selection:alternate", "alternate-letter",
                          "Take every other letter. <em>Regularly</em>, <em>oddly</em> and "
                          "<em>periodically</em> say to skip one, then take one."),
    "nth_letter": ("letter_selection", "letter_selection:nth", "numbered-letter",
                   "Take the letter at a stated place, such as the second or the fifth. "
                   "These words name where."),
    "head_deletion": ("deletion", "deletion:head", "head-deletion",
                      "Drop the first letter. <em>Headless</em>, <em>topless</em> and "
                      "<em>beheaded</em> take the start off."),
    "tail_deletion": ("deletion", "deletion:tail", "tail-deletion",
                      "Drop the last letter. <em>Mostly</em>, <em>almost</em> and "
                      "<em>short</em> take the end off."),
    "heart_deletion": ("deletion", "deletion:heart", "heart-deletion",
                       "Drop the middle letter or letters. <em>Heartless</em>, "
                       "<em>gutted</em> and <em>disheartened</em> take the centre out."),
    "outer_deletion": ("deletion", "deletion:outer", "outer-deletion",
                       "Drop the first and last letters, leaving the inside."),
    "named_deletion": ("deletion", "deletion:named", "named-letter deletion",
                       "Take out the piece the clue names, wherever it sits, as <em>loveless</em> "
                       "takes out LOVE. <em>Without</em>, <em>leaving</em> and <em>not</em> only say "
                       "to remove; the named piece decides where the letters come from."),
}
# The kinds of deletion that say where the cut is; a deletion word with none of
# them is a named-piece deletion.
POSITIONAL_DELETIONS = ("deletion:head", "deletion:tail", "deletion:heart", "deletion:outer")
# The h3 under a family's h2 for each kind.
KIND_TITLES = {
    "first_letters": "First letters", "last_letters": "Last letters",
    "middle_letters": "Middle letters", "outer_letters": "Outer letters",
    "alternate_letters": "Alternate letters", "nth_letter": "Nth letter",
    "head_deletion": "Head", "tail_deletion": "Tail", "heart_deletion": "Heart",
    "outer_deletion": "Outer", "named_deletion": "Named piece",
}
assert set(KIND_TITLES) == set(INDICATOR_KINDS)
# The page lists a kind after its parent, in the order above.
_ordered = {}
for _t, _blurb in INDICATOR_TYPES.items():
    _ordered[_t] = _blurb
    _ordered.update({k: v[3] for k, v in INDICATOR_KINDS.items() if v[0] == _t})
INDICATOR_TYPES = _ordered


def type_label(t):
    """A page section's name: a clue type's label, or a kind's."""
    return INDICATOR_KINDS[t][2] if t in INDICATOR_KINDS else clue_types.label(t)


@functools.cache
def role_lexicon():
    """{type: {KEY: clues}} for ROLE_INDICATOR_TYPES and INDICATOR_KINDS: each
    word goes under the one op the annotated corpus files it under most (one op
    per indicator), where that is at least ROLE_MIN_USES uses and ROLE_MIN_SHARE
    of its uses. A kind is the one the word is filed under most within its op,
    on the same bar (its uses, and ROLE_MIN_SHARE of the word's uses of that op).
    A deletion word with no positional kind (head, tail, heart, outer) at the
    share bar goes under named_deletion: it only says "remove".
    Keys are indicators.json's (capitals), so a clue's indicator matches."""
    data = ROOT / "tools" / "data"
    roles = json.loads((data / "indicator_roles.json").read_text(encoding="utf-8"))
    kinds = json.loads((data / "indicator_kinds.json").read_text(encoding="utf-8"))
    out = {t: {} for t in (*ROLE_INDICATOR_TYPES, *INDICATOR_KINDS)}
    kind_page = {v[1]: t for t, v in INDICATOR_KINDS.items()}
    for word, counts in roles.items():
        top = max(counts, key=counts.get)
        if not (counts[top] >= ROLE_MIN_USES and counts[top] >= ROLE_MIN_SHARE * sum(counts.values())):
            continue
        if top in ROLE_INDICATOR_TYPES:
            out[top][word] = counts[top]
        mine = {k: n for k, n in kinds.get(word, {}).items() if k.partition(":")[0] == top}
        if mine:
            best = max(mine, key=mine.get)
            total = sum(mine.values())
            if best in kind_page and mine[best] >= ROLE_MIN_USES and mine[best] >= ROLE_MIN_SHARE * total:
                out[kind_page[best]][word] = mine[best]
            elif (top == "deletion" and total >= ROLE_MIN_USES
                  and not any(k in mine and mine[k] >= ROLE_MIN_SHARE * total
                              for k in POSITIONAL_DELETIONS)):
                # NOT, LEAVING, WITHOUT: the word only says "remove", and the
                # clue's named piece decides where the letters come from.
                out["named_deletion"][word] = mine.get("deletion:named", 0) or total
    return out


@functools.cache
def indicator_lexicon():
    """tools/data/lexicons/indicators.json: {type: {key: clues}}."""
    return json.loads(INDICATORS.read_text(encoding="utf-8"))


def clue_indicators(found, puz, page):
    """Add one puzzle's indicators to found, {(type, key): candidate}, keeping
    for each a clue we annotated over one only a blog's facts explain, then a
    clue whose phrase is the key over one whose phrase only contains it, then
    the fullest annotation, then the newest puzzle.

    An indicator counts only under its own `for` (indicator_keys.clue_pairs),
    so "about" links to a container clue from the container list and not to
    an anagram that used it. Like clue_blocks(), every candidate is on a page this same run
    writes, and the page shows the indicator: a blog's facts are on it only
    for a clue we have not annotated (fetch_puzzle.with_blog_facts).
    """
    found.update(indicator_found(indicator_candidates(puz, page), found))


def indicator_candidates(puz, page):
    """clue_indicators()'s inputs from one page, before any lexicon: [(ours,
    depth, day, puzzle id, entry id, indicators)]. What the page cache stores,
    so a moved indicators.json re-matches a stored page without rendering it
    (tools/page_cache.py PER_ENTRY)."""
    out = []
    for e in puz["entries"]:
        ann = e.get("annotation") or e.get("blog") or {}
        if not ann.get("indicators") or f'id="{esc(entry_id(e))}"' not in page:
            continue
        prose = ann.get("explanation") or {}
        out.append((bool(e.get("annotation")),
                    len((prose.get("walkthrough") or "") + (prose.get("definitionFit") or "")),
                    series_meta.puzzle_day(puz) or date.min, puz["id"], entry_id(e),
                    [{k: i[k] for k in ("text", "for") if k in i} for i in ann["indicators"]]))
    return out


def indicator_found(cands, found=None, lexicon=None):
    """{(type, key): (rank, puzzle id, entry id)} for indicator_candidates()
    matched against indicators.json, best first into a copy of `found`."""
    found = dict(found or {})
    roles = role_lexicon() if lexicon is None else {}
    # The types only our own annotations name (substitution, cycling, palindrome)
    # match against the corpus's counts of their words.
    lex = {**indicator_lexicon(), **{t: roles[t] for t in ROLE_INDICATOR_TYPES}} if lexicon is None else lexicon
    for ours, depth, day, pid, eid, inds in cands:
        pairs = dict(clue_pairs(lex, inds))
        # A selection or deletion indicator also counts under its word's kind.
        for (t, key), exact in list(pairs.items()):
            for kind, (parent, _, _, _) in INDICATOR_KINDS.items():
                if parent == t and key in roles.get(kind, ()):
                    pairs[(kind, key)] = exact
        # A kind's words come from the annotated corpus's counts, which
        # indicators.json need not list under the parent (BEGINNING is a
        # first-letter word it has no letter_selection key for): match the
        # kind's own words under the parent's `for`.
        for kind, (parent, _, _, _) in INDICATOR_KINDS.items():
            if roles.get(kind):
                for (_, key), exact in clue_pairs({parent: roles[kind]}, inds).items():
                    pairs.setdefault((kind, key), exact)
        for (t, key), exact in pairs.items():
            rank = (ours, exact, depth, day)
            if (t, key) not in found or found[(t, key)][0] < rank:
                found[(t, key)] = (rank, pid, eid)
    return found


@functools.cache
def indicator_lexicon_hash():
    """What a stored page's indicator candidates were matched against: the
    lexicon and the corpus's counts of each word's role and kind."""
    data = ROOT / "tools" / "data"
    return "+".join(str(page_cache.file_hash(p)) for p in
                    (INDICATORS, data / "indicator_roles.json", data / "indicator_kinds.json"))


def ranked_indicators(t):
    """indicators.json's [(key, clues)] for type t, most used first."""
    return sorted({**indicator_lexicon(), **role_lexicon()}[t].items(), key=lambda kv: (-kv[1], kv[0]))


# How many of a type's indicators /learn/ shows: the head, where a beginner's
# time goes. The long tail is one link away on /indicators/.
LEARN_INLINE, LEARN_TABLE = 6, 10


def learn_indicators(m):
    """A /learn/ marker, <!-- indicators: TYPE --> or <!-- indicators: table -->,
    as the most used indicators with how many clues used each."""
    def run(t, n):
        return build_abbreviations.LIST_SEP.join(f'<em>{esc(indicator_label(k))}</em>{build_abbreviations.count_html(c)}'
                         for k, c in ranked_indicators(t)[:n])
    if m.group(1) != "table":
        return run(m.group(1), LEARN_INLINE)
    lex = indicator_lexicon()
    rows = [f'<tr><td>{clue_types.label(t).capitalize()}</td><td>{run(t, LEARN_TABLE)} '
            f'&middot; <a href="{BASE}/indicators/#{t}">all {len(lex[t]):,} &rarr;</a></td></tr>'
            for t in INDICATOR_TYPES if lex.get(t)]
    return ("<table>\n<tr><th>Clue type</th><th>Most used indicators, with how many clues "
            "used each</th></tr>\n" + "\n".join(rows) + "\n</table>")


def indicator_label(key):
    """indicators.json's key as a reader would write it."""
    return re.sub(r"\bspooner(s?)\b", lambda m: "Spooner" + ("’s" if m.group(1) else ""),
                  key.lower())


def indicators_page(found):
    """Every indicator the corpus has seen, by type, most used first.

    The counts are clues, off the solving blogs and this site's own annotations
    (tools/letter_facts.py --lexicons). An indicator links to one clue on a
    puzzle page that uses it (clue_indicators), explained by us where we can.
    """
    lex = indicator_lexicon()
    unknown = sorted(set(lex) - set(INDICATOR_TYPES))
    lex = {**lex, **role_lexicon()}
    types = [t for t in INDICATOR_TYPES if lex.get(t)]
    if unknown:
        raise SystemExit(f"{INDICATORS.relative_to(ROOT)} has indicator types the "
                         f"/indicators/ page does not explain: {', '.join(unknown)}. "
                         "Add each to INDICATOR_TYPES in tools/build_seo_pages.py.")
    # A kind's words are already in its parent's list: counted once.
    counted = [t for t in types if t not in INDICATOR_KINDS]
    families = counted
    kinds_of = {t: [k for k in types if k in INDICATOR_KINDS and INDICATOR_KINDS[k][0] == t]
                for t in families}
    # A list ranks; it does not pad: a word with no example clue on a page this
    # run writes is left off.
    def ranked_indicators(t):
        return [(k, n) for k, n in globals()["ranked_indicators"](t) if (t, k) in found]

    total = sum(len(ranked_indicators(t)) for t in counted)

    def item(t, k, n):
        _, pid, eid = found[(t, k)]
        return (f'<a href="{solve_url(pid, eid)}">{esc(indicator_label(k))}</a>'
                + build_abbreviations.count_html(n))

    title = f"Cryptic crossword indicators — {total:,} words, by type"
    desc = (f"{total:,} cryptic crossword indicators, grouped by what they tell you to do "
            "(anagram, container, reversal, hidden word, homophone and more) and ranked by "
            "how many real clues use them.")
    canonical = f"{BASE}/indicators/"
    crumbs = [("Cryptic Teacher", "/"), ("How cryptic clues work", "/learn/"),
              ("Indicators", "")]
    page_ld = {"@context": "https://schema.org", "@type": "DefinedTermSet",
               "name": "Cryptic crossword indicators", "url": canonical, "description": desc}
    body = [
        masthead(crumbs),
        '<main class="static-main tutorial-static">',
        "<h1>Cryptic crossword indicators</h1>",
        "<p>An indicator is the word in a clue that tells you what to do with the letters. "
        "In <em>Woman found in Oregon or Maine (5)</em>, the words <em>found in</em> say "
        "the answer is hidden in the words that follow: oregO<strong>N OR MA</strong>ine "
        "gives NORMA. Spot the indicator and you know what kind of clue you have.</p>",
        f"<p>These {total:,} indicators were counted in tens of thousands of solved clues, "
        "from solving blogs and from this site's own explanations. The number after each "
        "word is how many clues used it that way. The same word can do more than one job: "
        "<em>about</em> is a container, but it can also mean an anagram. "
        "Each word links to a real clue that uses it.</p>",
        "<p>Jump to: " + build_abbreviations.LIST_SEP.join(
            f'<a href="#{t}">{type_label(t)}</a>' + (
                " (" + ", ".join(f'<a href="#{k}">{KIND_TITLES[k].lower()}</a>' for k in kinds_of[t])
                + ")" if kinds_of[t] else "")
            for t in families) + "</p>",
    ]
    def words(t, ranked, lesson=None, heading=None):
        """An optional h3 and lesson, then the ranked Most used line and All N toggle."""
        top, rest = ranked[:15], ranked[15:]
        out = []
        if not ranked:
            return out
        if heading:
            out.append(f'<h3 id="{heading[0]}">{heading[1]}</h3>')
        if lesson:
            out.append(f"<p>{lesson}</p>")
        out.append("<p><strong>Most used:</strong> "
                   + build_abbreviations.LIST_SEP.join(item(t, k, n) for k, n in top) + "</p>")
        if rest:
            out += [f"<details><summary>All {len(ranked):,}</summary>",
                    "<p>" + build_abbreviations.LIST_SEP.join(item(t, k, n) for k, n in rest) + "</p>",
                    "</details>"]
        return out

    for t in families:
        body += [f'<h2 id="{t}">{type_label(t).capitalize()}</h2>',
                 f"<p>{INDICATOR_TYPES[t]}</p>"]
        subs = kinds_of[t]
        if not subs:
            body += words(t, ranked_indicators(t))
            continue
        used = set()
        for kind in subs:
            used |= set(lex[kind])
            body += words(kind, ranked_indicators(kind), INDICATOR_TYPES[kind],
                          (kind, KIND_TITLES[kind]))
        other = [(k, n) for k, n in ranked_indicators(t) if k not in used]
        if other:
            body += words(t, other, None, (f"{t}-other", "Other"))
    body +=[f'<p class="s-cta"><a class="cta" href="{BASE}/learn/">New to cryptics? '
             f'Learn how the clues work &rarr;</a></p>', "</main>"]
    return head(title, desc, canonical, ld(page_ld) + ld(breadcrumb_ld(crumbs))) \
        + "\n".join(body) + "\n" + FOOTER


# -------------------------------------------------------------------- sitemap

RECENT_DAYS = 60       # puzzle pages in the small, fast-changing sitemap
SITEMAP_MAX = 40000    # URLs per file; the protocol's limit is 50,000


def sitemap_urls(idx, pages=()):
    """(recent, archive): lists of (loc, changefreq, priority, lastmod).

    Recent is everything that changes daily (the site's own pages, the series
    landing pages and year listings) and the puzzles of the last RECENT_DAYS
    before the newest one; archive is every older puzzle. A small file Google
    re-reads often is what gets a new puzzle crawled the day it lands.
    """
    recent = [(f"{BASE}/", "daily", "1.0", None),
              (f"{BASE}/puzzles/", "daily", "0.9", None),
              (f"{BASE}/learn/", "monthly", "0.8", None),
              (f"{BASE}/abbreviations/", "weekly", "0.8", None),
              (f"{BASE}/indicators/", "weekly", "0.8", None),
              (f"{BASE}/difficulty/", "weekly", "0.6", None),
              (f"{BASE}/showcase/", "weekly", "0.7", None),
              (f"{BASE}/progress/", "daily", "0.5", None)]
    recent += [(u, "weekly", "0.6", None) for u in pages]
    for s, years in listings(idx).items():
        newest = next(iter(years.values()))[0]
        recent.append((site_url(series_path(s)), "daily", "0.9",
                       None if series_meta.is_book(s) else datestr(newest, "%Y-%m-%d") or None))
        for y in years:
            recent.append((site_url(listing_path(s, y)), "weekly", "0.6", None))
    solved = [p for p in idx["puzzles"] if p.get("hasSolutions")]
    days = [d for p in solved if "year" not in p and (d := series_meta.puzzle_day(p))]
    since = max(days) - timedelta(days=RECENT_DAYS) if days else None
    archive = []
    for p in solved:
        day = None if "year" in p else series_meta.puzzle_day(p)
        url = (f"{BASE}/puzzles/{p['id']}/", "monthly", "0.7", datestr(p, "%Y-%m-%d") or None)
        (recent if day and since and day >= since else archive).append(url)
    return recent, archive


def urlset(urls):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq, prio, lastmod in urls:
        out.append("  <url>")
        out.append(f"    <loc>{loc}</loc>")
        if lastmod:
            out.append(f"    <lastmod>{lastmod}</lastmod>")
        out.append(f"    <changefreq>{freq}</changefreq>")
        out.append(f"    <priority>{prio}</priority>")
        out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def sitemaps(idx, pages=()):
    """[(path, text)]: /sitemap.xml as a sitemap index (the URL Search Console
    holds), sitemap-recent.xml, and the archive in SITEMAP_MAX-URL parts.
    `pages` are generated pages' URLs that only the build knows of."""
    recent, archive = sitemap_urls(idx, pages)
    parts = [("sitemap-recent.xml", recent)] + [
        (f"sitemap-archive-{i // SITEMAP_MAX + 1}.xml", archive[i:i + SITEMAP_MAX])
        for i in range(0, len(archive), SITEMAP_MAX)]
    index = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for name, urls in parts:
        index.append("  <sitemap>")
        index.append(f"    <loc>{BASE}/{name}</loc>")
        if (last := max((u[3] for u in urls if u[3]), default=None)):
            index.append(f"    <lastmod>{last}</lastmod>")
        index.append("  </sitemap>")
    index.append("</sitemapindex>")
    return ([(ROOT / "sitemap.xml", "\n".join(index) + "\n")]
            + [(ROOT / name, urlset(urls)) for name, urls in parts])


# ------------------------------------------------------- homepage crawl links

def homepage_latest(idx, today):
    """Each paper's newest puzzle, for the homepage, and the papers with none.

    A paper still printing (newest puzzle within RECENT_DAYS) gets a line: its
    name links its series page, its number opens the solver, and a small
    "answers" link reaches the answer page, as an archive row does. The rest
    (books, finished archives) are one line of series links. Every series page
    and every newest answer page is then a link from the front door, which is
    how a crawler finds them; the sitemap alone is a weak signal.
    """
    lines, others = [], []
    cut = today - timedelta(days=RECENT_DAYS)
    for s, years in listings(idx).items():
        hub = f'<a href="{site_url(series_path(s))}">{esc(series_name(s))}</a>'
        p = next(iter(years.values()))[0]
        day = None if series_meta.is_book(s) else series_meta.puzzle_day(p)
        if not day or day < cut:
            others.append(hub)
            continue
        setter = p.get("setter") or ""
        by = f" by {esc(setter)}" if setter and setter != kind(p) else ""
        title, when = ((row_date(p), "") if number_day(p)
                       else (display_number(p), row_date(p)))
        parts = [hub, f'<a href="{solve_url(p["id"])}">{esc(title)}</a>{by}']
        if when:
            parts.append(esc(when))
        parts.append(f'<a class="p-answers" href="{BASE}/puzzles/{p["id"]}/">answers</a>')
        lines.append(f"<li>{build_abbreviations.LIST_SEP.join(parts)}</li>")
    return lines, others


def homepage_nav(idx, today=None):
    """The links that give a crawler somewhere to go from the homepage: the
    learn pages, the archive, every series page and each paper's newest puzzle
    (homepage_latest). No older puzzle is linked by name, since a handful
    picked out of the archive reads as random; those are reached through the
    series pages and the sitemaps.
    """
    solved = [p for p in idx["puzzles"] if p.get("hasSolutions")]
    lines, others = homepage_latest(idx, today or london_today())
    latest = ("" if not lines else
              '\n  <h2>Latest puzzles</h2>\n  <ul class="seo-latest">\n    '
              + "\n    ".join(lines) + "\n  </ul>")
    more = ("" if not others else
            f'\n  <p>More papers: {build_abbreviations.LIST_SEP.join(others)}.</p>')
    return f"""{NAV_START}
<section class="seo-nav">
  <h2>Answers and explanations</h2>
  <p>These are real crosswords from the {papers(idx)}, by the papers' own setters,
     not made-up practice clues. Every puzzle has a page with all its answers, and
     many explain every clue: its definition, its wordplay and how they fit.
     New to cryptics? Start with <a href="{BASE}/learn/">how cryptic clues work</a>,
     the <a href="{BASE}/abbreviations/">common abbreviations</a> and
     <a href="{BASE}/indicators/">indicators</a>, read
     <a href="{BASE}/difficulty/">how difficulty is rated</a>, see
     <a href="{BASE}/showcase/">puzzles with something unusual about them</a>, or browse
     <a href="{BASE}/puzzles/">all {len(solved):,} puzzles</a>.</p>{latest}{more}
</section>
{NAV_END}"""


def patch_homepage(idx):
    path = ROOT / "index.html"
    text = path.read_text(encoding="utf-8")
    # The <head> only: title, descriptions and the JSON-LD blurb are copy about
    # the site as a whole. The body below carries per-puzzle links, where naming
    # one paper is simply what that puzzle is.
    assert_names_all_papers("index.html <head>",
                            text.split("</head>", 1)[0], idx)
    want = f'<meta name="apple-mobile-web-app-title" content="{esc(app_name())}">'
    if want not in text:
        raise SystemExit(f'index.html must carry {want}. That string is the label '
                         'under the Home Screen icon; the generated pages take it '
                         "from site.webmanifest's short_name and this one is "
                         'hand-written, so it is checked rather than trusted.')
    nav = homepage_nav(idx)
    if NAV_START in text and NAV_END in text:
        new = re.sub(re.escape(NAV_START) + r".*?" + re.escape(NAV_END), lambda _: nav,
                     text, flags=re.S)
    else:
        new = text.replace("<footer>", nav + "\n\n<footer>", 1)
    return path, new


def moved_page(slug, target, title, body):
    """One "this puzzle is at <url>" page: canonical for a crawler, meta
    refresh for a reader. GitHub Pages cannot answer with a 301, so a URL that
    has moved is a page that says so in both of the ways that count.

    Nothing else: a reader is on it for the instant the refresh takes, and
    there are tens of thousands of them, so the site's full template on each
    would be a large share of the whole site's weight.
    """
    return puzzle_paths.PUZZLE_DIR / slug / "index.html", relative_links(
        bare_head(title, target,
                  f'<meta http-equiv="refresh" content="0; url={esc(target)}">\n')
        + f"<body>\n<p>{body}</p>\n</body>\n</html>\n", PUZZLE_ROOT)


def bare_head(title, canonical, extra=""):
    """The <head> of a page that only points somewhere else: a title, where
    the content really is, and analytics.js, because tools/ga_report.py is how
    anyone learns that an old address still gets visits. No social tags: the
    card a share of it should show is the target's."""
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{esc(title)}</title>\n"
            f'<link rel="canonical" href="{esc(canonical)}">\n'
            + extra
            + f'<script src="{asset("analytics.js")}"></script>\n</head>\n')


def legacy_ids(solved, ids):
    """A page at every id a puzzle has ever had, pointing at the one it has now.

    An id is in shared links, in indexed pages, and in the key every browser
    saved its progress under, so it has to keep resolving forever. One family
    so far, and it has moved twice: the scanned books were one series PER
    VOLUME ("penguin5-18"), then one series per BOOK with the volume in the
    number ("penguin-5018"), and are one series for the whole SHELF now, with
    a registered book index in the number. Both old spellings are pages here.

    Derived from each puzzle rather than listed, by series.legacy_ids(), so a
    book acquired after the collapse gets its pages without anyone remembering
    to add them. That writes a page for an id that was never published, which
    is harmless for the same reason the bare-number pages below say "is at"
    rather than "has moved": the page's job is to say which puzzle a name
    refers to. A derived id some puzzle holds today (Times book 21's No 24 is
    "times-21024", the paper's No 21,024) is that puzzle's, so it is skipped,
    as app.js's canonicalId checks a real id before an alias.
    """
    for p in solved:
        for was in series_meta.legacy_ids(p.get("series") or "cryptic", p["number"]):
            if was == p["id"] or was in ids:
                continue
            target = f"{BASE}/puzzles/{p['id']}/"
            label = named(p)
            yield moved_page(
                was, target, f"{label} has moved",
                f'This puzzle has a new address: <a href="{target}">{esc(label)}</a>.')


def renamed_ids_pages(solved, taken):
    """A page at every id a commit renamed, pointing at the id its puzzle has now.

    Read from tools/data/renamed_ids.json (tools/renamed_ids.py), which every
    renaming commit carries a row of. Kept forever, as the pages above are: an
    old id is in shared links, indexed pages and saved progress. An old id that
    a puzzle holds today, or that legacy_ids() already answers, is skipped
    (`taken`), and so is one whose puzzle was later deleted or has no page of
    its own to point at (renamed_ids.current).
    """
    paged = {p["id"]: p for p in solved}
    for was, now in sorted(renamed_ids.current(renamed_ids.read(), paged.keys()).items()):
        if was in taken:
            continue
        target = f"{BASE}/puzzles/{now}/"
        label = named(paged[now])
        yield moved_page(
            was, target, f"{label} has moved",
            f'This puzzle has a new address: <a href="{target}">{esc(label)}</a>.')


def legacy_redirects(solved):
    """A page at /puzzles/<bare number>/ for every puzzle, pointing at its id.

    Puzzle pages live at /puzzles/cryptic-30089/, not /puzzles/30089/, so two
    papers cannot claim one directory. The bare-number URLs are indexed and
    shared, and GitHub Pages cannot answer with a 301, so each becomes a page
    that says where its puzzle is in the two ways that count: rel=canonical for a crawler, a meta refresh for a
    reader. Kept forever, not for a grace period — a link somebody sent a friend
    has no expiry, and readers do still arrive on them. Nothing in this repo
    links here, so "nothing links to them" is the wrong test; the right one is
    the top-pages table in tools/ga_report.py.

    Built only at the numbers in BARE_NUMBER_URLS: the 222 puzzles that were
    pages at /puzzles/<number>/ before ids carried their series. Every other
    number was never published bare, and a stub for each of them was ~24k
    pages (~50 MB of the Pages artifact, headers included) that no crawler or
    reader had a URL for. The copy still says "is at" rather than "has moved":
    a number listed there may since have been reached by another paper too.

    A number claimed by more than one paper offers the choice rather than
    guessing, which is the same rule resolve_puzzle() applies on the command
    line: an ambiguous number is a question, never a coin toss.
    """
    by_number = {}
    for p in solved:
        if int(p["number"]) in BARE_NUMBER_URLS:
            by_number.setdefault(str(p["number"]), []).append(p)
    for num, ps in sorted(by_number.items()):
        pretty = f"{int(num):,}"
        if len(ps) == 1:
            target = f"{BASE}/puzzles/{ps[0]['id']}/"
            yield moved_page(num, target, named(ps[0]),
                             f'The page for this puzzle is at <a href="{target}">'
                             f'{esc(named(ps[0]))}</a>.')
            continue
        # A choice is a page somebody reads, so it keeps the site's template.
        title = f"Crossword No {pretty}: which paper?"
        body = (f"<p>More than one paper has a crossword No {pretty}. "
                "Pick the one you want:</p><ul>" + "".join(
            f'<li><a href="{BASE}/puzzles/{p["id"]}/">'
            f'{esc(named(p))}</a></li>' for p in ps)
            + "</ul>")
        yield puzzle_paths.PUZZLE_DIR / num / "index.html", relative_links(
            bare_head(title, f"{BASE}/puzzles/",
                      f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                      f'<link rel="stylesheet" href="{asset("style.css")}">\n'
                      f'<script src="{asset("appnav.js")}"></script>\n')
            + '<body class="static-page">\n'
            + masthead([("Cryptic Teacher", "/"), ("Puzzles", "/puzzles/"),
                        (f"No {pretty}", "")])
            + f'<main class="static-main"><h1>{esc(title)}</h1>{body}</main>\n'
            + FOOTER, PUZZLE_ROOT)   # FOOTER already closes body and html


# ------------------------------------------------------------------------ run

#: (solved, neighbours, meta, check, fingerprint, stored) for
#: puzzle_page_job(), set by outputs() before its workers fork.
_PAGES = None


def series_neighbours(stubs):
    """[(newer, older)] for each stub of the newest-first list: the adjacent
    puzzle of the same series, or None. A pager that steps to whatever another
    paper printed the same day is a link to a random puzzle."""
    out, last = [None] * len(stubs), {}
    for i, p in enumerate(stubs):
        s = p.get("series") or "cryptic"
        j = last.get(s)
        out[i] = [stubs[j] if j is not None else None, None]
        if j is not None:
            out[j][1] = p
        last[s] = i
    return [tuple(n) for n in out]


def page_key(i):
    """Puzzle page i's per-page inputs, under the build's fingerprint: what
    tools/page_cache.py reuses a stored page by. Its puzzle file, its blog
    facts, the part of its index row it prints (page_row), its pager
    neighbours and whether its card is drawn; everything else it reads is
    code or data, in the fingerprint."""
    solved, neighbours, meta, _, fp, _ = _PAGES
    path, stub = solved[i]
    pid = stub["id"]
    h = hashlib.sha256()
    for part in (fp, puzzle_paths.relative(path, ROOT) or str(path),
                 hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                 blog_fact_hashes().get(pid),
                 json.dumps(page_row(meta.get(pid)), sort_keys=True, default=str),
                 json.dumps(neighbours[i], sort_keys=True, default=str),
                 (ROOT / f"og/{pid}.png").exists()):
        h.update(f"{part}\0".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def reuse_page(i):
    """(result, key, why) for puzzle page i of the solved list: `result` is the
    stored page's puzzle_page_job() result when every check passes (its key,
    the stamped assets it asked for, the abbreviation pairs it looked up, the
    file on disk), else None and `why` names the check that failed. Shared by
    puzzle_page_job() and the parent-side first pass (reuse_first)."""
    solved, neighbours, meta, check, fp, stored = _PAGES
    path = puzzle_paths.PUZZLE_DIR / solved[i][1]["id"] / "index.html"
    key = page_key(i) if fp else None
    hit = stored.get(key) if key else None
    # Why a page is rendered, by series, for the log: its key moved, a stamped
    # asset it asked for did, or its file is not the one that was written.
    series = solved[i][1].get("series")
    why = f"key:{series}"
    # The store holds the showcase facts the file states; the index row's
    # (difficulty index, tags) move without the page, so they are added fresh.
    row = meta.get(solved[i][1]["id"])
    if hit:
        asked, digest, blocks, cands, lex, found, file_facts, abbrs = hit
        if not all(_asset(rel) == url for rel, url in asked):
            why = f"asset:{series}"
        elif not all((pair in annotation.abbreviation_pairs()) == known for pair, known in abbrs):
            why = f"abbr:{series}"
        elif page_cache.file_hash(path) == digest:
            if lex != indicator_lexicon_hash():  # the lexicon moved, not the page
                found = indicator_found(cands)
                hit = (asked, digest, blocks, cands, indicator_lexicon_hash(), found, file_facts,
                       abbrs)
            return ((path, False, blocks, found, showcase.with_meta(file_facts, row),
                     (key, hit, True, None)), key, why)
        else:
            why = f"file:{series}"
    return None, key, why


def reuse_first(n):
    """[(index, result)] for the pages of 0..n-1 that reuse_page() can reuse,
    and the indexes it cannot, checked here in the parent.

    A warm cache reuses nearly every page, and in puzzle_page_job that costs
    more in the pipe than in the check: each result carries the page's clue
    blocks and candidates back from a worker (a shard's reuse of 10.7k pages
    took 10s on four cores, run 39236355785). Checked here, serially, a page
    reused costs its key and its checks and nothing else; only the pages it
    cannot reuse go to the workers. The same checks decide, so the same files
    come out."""
    got, missed = {}, []
    for i in range(n):
        reused, _, _ = reuse_page(i)
        if reused:
            got[i] = reused
        else:
            missed.append(i)
    return got, missed


def puzzle_page_job(i):
    """Render, check and write puzzle page i of the solved list, in a worker,
    or reuse last build's (tools/page_cache.py).

    Returns (path, stale, blocks, found, facts, stored): whether the file on
    disk differed, this page's own clue_blocks() and clue_indicators()
    candidates, which outputs() merges in page order into exactly what one
    serial pass builds, what /showcase/ needs to know about the puzzle, and
    (key, entry, reused) for the store, or None with the store off.
    The text stays in the worker, so no page crosses a pipe.
    """
    global _ASKED
    solved, neighbours, meta, check, fp, stored = _PAGES
    path = puzzle_paths.PUZZLE_DIR / solved[i][1]["id"] / "index.html"
    reused, key, why = reuse_page(i)
    if reused:
        return reused
    row = meta.get(solved[i][1]["id"])
    # The list is newest-first, so "next" is the older neighbour.
    prev_p, next_p = neighbours[i]
    _ASKED = set()
    annotation.ABBR_ASKED = set()  # view() glosses leaves as the file is read
    try:
        puz = with_blog_facts(read_puzzle_view(solved[i][0]))
        page = puzzle_page(puz, row, prev_p, next_p)
        asked = tuple((rel, _asset(rel)) for rel in sorted(_ASKED))
        abbrs = tuple((pair, pair in annotation.abbreviation_pairs())
                      for pair in sorted(annotation.ABBR_ASKED))
    finally:
        _ASKED = None
        annotation.ABBR_ASKED = None
    blocks = {}
    clue_blocks(blocks, puz, page)
    cands = indicator_candidates(puz, page)
    found = indicator_found(cands)
    assert path == puzzle_paths.PUZZLE_DIR / puz["id"] / "index.html"
    text = relative_links(page, PUZZLE_ROOT)
    file_facts = showcase.file_facts(puz)
    entry = (asked, page_cache.text_hash(text), blocks, cands, indicator_lexicon_hash(), found,
             file_facts, abbrs)
    return (path, write_output(path, text, check), blocks, found,
            showcase.with_meta(file_facts, row),
            (key, entry, False, why) if key else None)


def write_output(p, text, check):
    """Check one generated file and write it if it changed; whether it did."""
    assert_no_root_relative(p, text)
    assert_no_answer_links(p, text)
    if p.exists() and p.read_text(encoding="utf-8") == text:
        return False
    if not check:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return True


#: Where `--shard i/n` leaves what the tail step needs from its pages.
SHARD_DIR = ROOT / ".page-shards"


def shard_of(pid, n):
    """Which of n shards renders puzzle page `pid`: a stable hash of the id,
    not Python's per-process hash(), so every step agrees on the split."""
    return int.from_bytes(hashlib.sha256(pid.encode("utf-8")).digest()[:8], "big") % n


def shard_file(i, n):
    return SHARD_DIR / f"{i}-of-{n}.pickle"


def read_shards(n, solved):
    """{page id: job result} from the n shard files, or exit unless every page
    of `solved` was rendered by exactly one shard (the one its id hashes to)."""
    import pickle
    got, errors = {}, []
    for i in range(n):
        try:
            with open(shard_file(i, n), "rb") as f:
                part = pickle.load(f)
        except (OSError, pickle.PickleError, EOFError) as err:
            errors.append(f"shard {i}/{n}: no usable {shard_file(i, n).name} ({err!r})")
            continue
        for pid, result in part.items():
            if shard_of(pid, n) != i:
                errors.append(f"shard {i}/{n} rendered {pid}, which belongs to shard {shard_of(pid, n)}")
            elif pid in got:
                errors.append(f"{pid} was rendered twice")
            got[pid] = result
    want = [stub["id"] for _, stub in solved]
    missing = [pid for pid in want if pid not in got]
    extra = sorted(got.keys() - set(want))
    if len(set(want)) != len(want):
        errors.append("the puzzle list repeats an id")
    if missing:
        errors.append(f"{len(missing)} page(s) were rendered by no shard, e.g. {missing[:5]}")
    if extra:
        errors.append(f"{len(extra)} rendered page(s) are not in the puzzle list, e.g. {extra[:5]}")
    if errors:
        raise SystemExit("the shards do not cover the pages exactly once:\n  " + "\n  ".join(errors))
    return got


def outputs(check=False, shard=None, shards=None, first=False):
    """Every generated file as (path, stale): the puzzle pages first, written
    across the cores by puzzle_page_job(), then the rest, one at a time.

    shard=(i, n) renders only the pages whose id hashes to i of n, leaves
    their results in SHARD_DIR and yields nothing; shards=n is the tail that
    reads all n shards' results in place of rendering, then runs as the
    unsharded build does. Byte for byte the same files either way.
    first=True (`--reuse-first`) checks the pages the store can reuse in this
    process and sends only the rest to the workers (reuse_first); it is the
    deploy's fast path for a push that only added puzzles, in place of the
    shards.

    Pages are written as they are made and only their paths kept, because the
    site does not fit in memory: tens of thousands of puzzle pages.
    """
    global _PAGES
    idx = index_json()
    meta = {p["id"]: p for p in idx["puzzles"]}
    # The whole-site copy checks go first, so a refusal writes nothing.
    home = patch_homepage(idx) if not shard else None
    # The manifest is hand-written and generates nothing, but it is copy about
    # the whole site — an installed icon's description — so it is held to the
    # same rule as the pages that are generated.
    if not shard:
        assert_names_all_papers("site.webmanifest",
                                (ROOT / "site.webmanifest").read_text(encoding="utf-8"), idx)
    started = time.monotonic()
    solved = puzzles()
    stubs = [stub for _, stub in solved]
    took("the puzzle list", started)

    claimed = set()

    def claim(p):
        # Before the write for every page but the puzzle pages, whose paths
        # are their ids and so cannot collide with each other.
        if p in claimed:
            raise SystemExit(f"{p.relative_to(ROOT)} is generated twice: two outputs "
                             "claim one URL, and only one of them could be served")
        claimed.add(p)

    blocks, found, facts = {}, {}, []
    fp = page_cache.fingerprint()
    stored = page_cache.load() if fp else {}
    blog_fact_hashes()  # once, before the workers fork
    _PAGES = solved, series_neighbours(stubs), meta, check, fp, stored
    keep, reused, why = {}, 0, collections.Counter()
    if shard:
        import pickle
        i, n = shard
        mine = [j for j, (_, stub) in enumerate(solved) if shard_of(stub["id"], n) == i]
        SHARD_DIR.mkdir(exist_ok=True)
        shard_file(i, n).unlink(missing_ok=True)
        part = {solved[j][1]["id"]: r for j, r in zip(mine, parallel.pmap(puzzle_page_job, mine))}
        _PAGES = None
        tmp = shard_file(i, n).with_suffix(f".{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            pickle.dump(part, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, shard_file(i, n))
        print(f"page shard {i}/{n}: {len(part)} of {len(solved)} puzzle page(s); "
              f"reused {sum(bool(r[5] and r[5][2]) for r in part.values())}", file=sys.stderr)
        took(f"the puzzle pages of shard {i}/{n}", started)
        return
    if shards:
        got = read_shards(shards, solved)
        results = [got[stub["id"]] for _, stub in solved]
    elif first:
        got, missed = reuse_first(len(solved))
        got.update(zip(missed, parallel.pmap(puzzle_page_job, missed)))
        results = [got[j] for j in range(len(solved))]
    else:
        results = parallel.pmap(puzzle_page_job, range(len(solved)))
    for path, stale, page_blocks, page_found, page_facts, kept in results:
        if kept:
            reused += kept[2]
            keep[kept[0]] = kept[1]
            if kept[3]:
                why[kept[3]] += 1
        facts.append(page_facts)
        for key, cands in page_blocks.items():
            blocks.setdefault(key, []).extend(cands)
        for key, cand in page_found.items():
            if key not in found or found[key][0] < cand[0]:
                found[key] = cand
        claim(path)
        yield path, stale
    _PAGES = None
    if fp:
        print(f"page cache: reused {reused} of {len(solved)} puzzle page(s)", file=sys.stderr)
        if why:
            print("page cache: rendered because " + ", ".join(
                f"{k} {n}" for k, n in why.most_common(12)), file=sys.stderr)
        if os.environ.get("GITHUB_OUTPUT"):  # the deploy saves the store after a big render
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
                out.write(f"rendered={len(solved) - reused}\n")
        if not check:
            page_cache.save(keep)
    took("the puzzle pages", started)

    def rest():
        yield from legacy_redirects(stubs)
        live = meta.keys() | {p["id"] for p in idx.get("unlisted", [])}
        derived = list(legacy_ids(stubs, live))
        yield from derived
        yield from renamed_ids_pages(stubs, live | {path.parent.name for path, _ in derived})
        yield puzzle_paths.PUZZLE_DIR / "index.html", hub_page(idx)
        yield from series_pages(idx)
        yield from listing_pages(idx)
        yield ROOT / "learn" / "index.html", learn_page()
        yield ROOT / "abbreviations" / "index.html", abbreviations_page(blocks)
        # Relative, like the puzzle pages: thousands of example links.
        yield ROOT / "indicators" / "index.html", relative_links(indicators_page(found), "../")
        yield ROOT / "difficulty" / "index.html", difficulty_page(idx)
        yield ROOT / "progress" / "index.html", progress_page(idx)
        secs = showcase.sections(f for f in facts if f["id"] in meta)
        yield ROOT / "showcase" / "index.html", showcase_page(secs, meta)
        yield from showcase_list_pages(secs, meta)
        yield from sitemaps(idx, [f"{BASE}/showcase/{slug}/"
                                  for slug, *_, full in secs if full])
        yield home
    for p, text in rest():
        claim(p)
        yield p, write_output(p, text, check)
    took("the other pages", started)


def took(what, since):
    """One phase's seconds on stderr, for the deploy log: which part of the
    step to look at when its budget is hit."""
    print(f"build_seo_pages: {what} by {time.monotonic() - since:.1f}s", file=sys.stderr)


# The site root as seen from /puzzles/<id>/, the directory every puzzle page and
# redirect lives in.
PUZZLE_ROOT = "../../"


def relative_links(page, root):
    """page with every href and src to this site made relative to root, bar
    rel=canonical.

    BASE is thirty bytes, and a puzzle page links home a dozen times; across the
    puzzle pages that would be tens of megabytes of one repeated string. The
    canonical keeps it, as do og:url, og:image and the JSON-LD, which are
    content= and JSON rather than href/src: all of them are read by machines
    that want an absolute URL.
    """
    # str.split rather than one regex: the pattern has no literal prefix for the
    # engine to skip ahead by, so it tried every position of a 100 KB page.
    needle, bare = f'="{BASE}/', f'="{root}'
    parts = page.split(needle)
    out = [parts[0]]
    for before, part in zip(parts, parts[1:]):
        for name in ("href", "src"):
            if before.endswith(name):
                head = before[:-len(name)]
                if (not head or not (head[-1].isalnum() or head[-1] == "_")) \
                        and not head.endswith('rel="canonical" '):
                    out.append(bare)
                    break
        else:
            out.append(needle)
        out.append(part)
    return "".join(out)


def assert_no_root_relative(path, text):
    """No generated link may start at /.

    Relative hrefs are what let the generated pages be opened straight off
    disk, and what make a move to another host or path a one-line change to
    BASE instead of a rewrite.

    Nothing in a browser catches a wrong link — the page renders fine and only a
    crawler notices — so it is checked here, where every generated href passes
    through. Links are absolute (BASE + path) or relative to the page.
    """
    if path.suffix != ".html":
        return
    bad = [m.group(1) for m in re.finditer(r'(?:href|src)="(/[^/][^"]*)"', text)]
    if bad:
        raise SystemExit(f"root-relative links in {path.relative_to(ROOT)} (the site lives "
                         f"at {BASE}/, so these 404):\n  " + "\n  ".join(bad[:20]))


# The pages a reader browses for puzzles to try. Their puzzle links open the
# app (solve_url); the answer pages are for search engines.
READER_PAGES = ("learn", "abbreviations", "indicators", "difficulty", "showcase")
ANSWER_LINK = re.compile(r'href="[^"]*\bpuzzles/(?!series/)[^/"?#]+/[^"]*"')
# A puzzle row in a list (hub_row). The chooser legacy_redirects() writes for an old
# /puzzles/<number>/ is not one: it was an answer page's URL, and its links
# are where that page went.
ROW_LIST = re.compile(r'<ul class="s-index">(.*?)</ul>', re.S)
ROW_LINK = re.compile(r'<li><a href="([^"]*)"')


def assert_no_answer_links(path, text):
    """No reader page links a puzzle's answer page, and every list row's own
    link, the one a reader clicks, opens the app: an archive row may add a
    small "answers" link beside it, and nothing more."""
    if path.suffix != ".html":
        return
    bad = [h for rows in ROW_LIST.findall(text) for h in ROW_LINK.findall(rows)
           if "?p=" not in h]
    if path.name == "index.html" and (
            path.parent.name in READER_PAGES and path.parent.parent == ROOT
            or path.parent.parent == ROOT / "showcase"):
        bad += ANSWER_LINK.findall(text)
    if bad:
        raise SystemExit(f"{path.relative_to(ROOT)} links puzzles to their answer pages; "
                         "a reader's puzzle link opens the app (solve_url):\n  "
                         + "\n  ".join(bad[:20]))


def orphans(files):
    """Per-puzzle output directories under puzzles/ that this run does not write.

    Output is decided by the index, so the set of directories that should exist
    is known exactly on every run; a directory outside that set is one no future
    run will ever rewrite. Left alone they accumulate silently — a renamed
    puzzle leaves its old page behind serving stale content at a live URL,
    with nothing on disk to say it is dead.

    The rule is narrow on purpose, because this walks the directory that also
    holds the site's real data:

      * only direct child DIRECTORIES of puzzles/, and the listing directories
        puzzles/series/<series>/<year>/, are candidates, so no flat
        puzzles/<series>-<number>.* file can be reached at all;
      * a source folder, puzzles/<series>/ (or authored/) holding
        <year>/<id>.json files, is never a candidate;
      * a directory qualifies only if its entire content is one index.html,
        which is the exact shape this generator creates;
      * and only if that index.html is not one this run is about to write.

    A bare-numeric directory legacy_redirects() still writes (one of
    BARE_NUMBER_URLS) is NOT an orphan; any other one is, and goes. The test for a dead page is "this run
    does not write it", never a guess from the name.

    Anything that does not fit the shape is returned as a leftover rather than
    removed — an unexpected file under puzzles/ is a question, not a target.
    """
    series_dir = puzzle_paths.PUZZLE_DIR / "series"
    sources = {p.parent.parent for p in puzzle_paths.PUZZLE_DIR.glob("*/*/*.json")}
    wanted = {p.parent for p in files} | {series_dir} | sources
    dead, unexpected = [], []
    # series/<series>/<year>/ is the one nested shape, so it gets the same test.
    for d in sorted([*puzzle_paths.PUZZLE_DIR.iterdir(), *series_dir.glob("*/*")]):
        if not d.is_dir() or d in wanted:
            continue
        if [x.name for x in d.iterdir()] == ["index.html"]:
            dead.append(d)
        else:
            unexpected.append(d)
    return dead, unexpected


def shard_arg(argv):
    """(i, n) from `--shard i/n`, or None."""
    if "--shard" not in argv:
        return None
    try:
        i, n = map(int, argv[argv.index("--shard") + 1].split("/"))
    except (IndexError, ValueError):
        raise SystemExit("--shard takes i/n, e.g. --shard 0/4")
    if not 0 <= i < n:
        raise SystemExit(f"--shard {i}/{n}: i must be from 0 to n-1")
    return i, n


def main():
    check = "--check" in sys.argv
    shard = shard_arg(sys.argv)
    shards = None
    if "--assemble" in sys.argv:       # the tail: --assemble N, after N --shard runs
        try:
            shards = int(sys.argv[sys.argv.index("--assemble") + 1])
        except (IndexError, ValueError):
            raise SystemExit("--assemble takes the number of shards, e.g. --assemble 4")
    if shard and (shards or check):
        raise SystemExit("--shard renders pages: it takes neither --assemble nor --check")
    if shard:
        for _ in outputs(shard=shard):
            pass
        return 0
    # Each file is compared, written and dropped as it is made; only the paths
    # are kept, for orphans().
    files, stale = set(), []
    for p, changed in outputs(check, shards=shards, first="--reuse-first" in sys.argv):
        files.add(p)
        if changed:
            stale.append(p)
    dead, unexpected = orphans(files)
    for d in unexpected:
        print(f"LEFTOVER: {d.relative_to(ROOT)} is not a generated page directory "
              "— left alone")
    if check:
        for d in sorted(dead):
            print(f"ORPHAN: {d.relative_to(ROOT)}")
        if stale or dead:
            for p in sorted(stale):
                print(f"STALE: {p.relative_to(ROOT)}")
            print("run python3 tools/build_seo_pages.py")
            return 1
        print(f"{len(files)} generated page(s) up to date")
        return 0
    for d in dead:
        (d / "index.html").unlink()
        d.rmdir()
        if d.parent.parent == puzzle_paths.PUZZLE_DIR / "series" and not any(d.parent.iterdir()):
            d.parent.rmdir()          # a series with no listing pages left
    page_card.write_spec(PAGE_CARDS)
    print(f"{len(files)} page(s); wrote {len(stale)} changed; "
          f"{len(dead)} orphan(s) removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
