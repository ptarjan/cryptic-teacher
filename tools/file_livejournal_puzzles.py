#!/usr/bin/env python3
"""File the Club Monthly posts only times-for-the-times' old LiveJournal holds.

    python3 tools/file_livejournal_puzzles.py --scan 2016/06 2016/08   # list a month's club posts
    python3 tools/file_livejournal_puzzles.py --rebuild    # fetch POSTS, parse, backsolve the grids
    python3 tools/file_livejournal_puzzles.py --dry-run    # count what it would file
    python3 tools/file_livejournal_puzzles.py              # file them

The blog moved from times-xwd-times.livejournal.com to WordPress in 2017, and
the move dropped some posts: 13 Club Monthly write-ups (2011-2017) are on the
LiveJournal, which still serves them, and nowhere on timesforthetimes.co.uk.
POSTS lists them, found by --scan over the months the WordPress blog skips.
Each page is cached once in downloads.LIVEJOURNAL/html, turned into the
WordPress post shape (category 24, the club's) and read by
parse_timesforthetimes.parse_post like any blog post; the grid is backsolved
by tools/times_grids.py into this cache's own grids.jsonl, and
tools/file_times_puzzles.py files it, so nothing in the blog's cache, nor its
whole-blog parse, is touched.

Seven of the 13 give answers and wordplay with no clue text, as the blog's own
club posts did until mid-2014: they parse to no clues and stay unfiled
(ANSWERS_ONLY, for tools/coverage.py).
"""
import argparse
import datetime
import html
import json
import re
import sys
import time
import urllib.request
import downloads

TOOL = "tools/file_livejournal_puzzles.py"
CACHE = downloads.LIVEJOURNAL
HTML = CACHE / "html"
PARSED = CACHE / "parsed.jsonl"
GRIDS = CACHE / "grids.jsonl"
HOST = "https://times-xwd-times.livejournal.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
CLUB_CATEGORY = 24
POLITE = 0.5

#: Club number -> LiveJournal post id, for each Club Monthly write-up the
#: WordPress blog lacks (checked 2026-10-13 by its REST search and category 24).
POSTS = {20134: 774004, 20139: 830158, 20156: 1018642, 20159: 1051038,
         20163: 1102832, 20178: 1356989, 20179: 1374486, 20189: 1545668,
         20191: 1581698, 20192: 1603003, 20194: 1636879, 20199: 1729051,
         20205: 1835834}
#: Club numbers no source we know gives the clues of, for tools/coverage.py,
#: checked 2026-10-13. Before 20110 (November 2009) there is no write-up at all,
#: on WordPress or the LiveJournal; the Club Monthly was online-only for
#: Times Crossword Club members and never printed, and web.archive.org's
#: crosswordclub.co.uk captures are login redirects.
MEMBERS_ONLY = range(20000, 20110)
#: The write-ups (WordPress, or POSTS here) that give answers and wordplay with
#: no clue text: every one to 20164 (May 2014), then four.
ANSWERS_ONLY = set(range(20110, 20165)) | {20172, 20176, 20178, 20179}
LOST_CAUSES = {
    ("crosswordclub", "members-only"):
        "the Club Monthly before the blog's first write-up (20110, Nov 2009): online-only "
        "for Times Crossword Club members, never printed (no Gale, no scans); no write-up "
        "on timesforthetimes or its LiveJournal, and web.archive.org's crosswordclub.co.uk "
        "captures are login redirects. Only the Club's paid archive holds the clues",
}


def lost():
    """{club number: (source, cause)} for coverage.py's ledger."""
    out = {n: ("crosswordclub", "members-only") for n in MEMBERS_ONLY}
    out.update({n: ("timesforthetimes", "answers-only") for n in ANSWERS_ONLY})
    return out

LINK = re.compile(r'href="' + re.escape(HOST) + r'/(\d+)\.html">([^<]*)</a>')
CLUB_TITLE = re.compile(r"club|monthly", re.I)
TITLE = re.compile(r"<title>([^<]*?)(?::\s*times_xwd_times[^<]*)?</title>")
DATE = re.compile(r'aentry-head__date">\s*<time>\s*([A-Z][a-z]+ \d{1,2} \d{4}), (\d{2}:\d{2})')


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def scan(month):
    """[(post id, title)] of the club posts in a LiveJournal month, "2016/08"."""
    seen = {}
    for skip in range(0, 500, 50):
        page = get(f"{HOST}/{month}/" + (f"?skip={skip}" if skip else ""))
        new = [(int(i), html.unescape(t)) for i, t in LINK.findall(page) if int(i) not in seen]
        seen.update(new)
        if not new or "skip=" not in page:
            break
        time.sleep(POLITE)
    return [(i, t) for i, t in seen.items()
            if CLUB_TITLE.search(t) and not re.search(r"quick", t, re.I)]


def page(pid):
    """The post's page, fetched once."""
    path = HTML / f"{pid}.html"
    if not path.exists():
        HTML.mkdir(parents=True, exist_ok=True)
        path.write_text(get(f"{HOST}/{pid}.html"), encoding="utf-8")
        time.sleep(POLITE)
    return path.read_text(encoding="utf-8")


def as_post(pid, text):
    """A LiveJournal page in the WordPress REST shape parse_post reads."""
    title = html.unescape(TITLE.search(text).group(1)).strip()
    m = DATE.search(text)
    when = datetime.datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %d %Y %H:%M")
    start = text.index('aentry-post__text')
    start = text.index(">", start) + 1
    end = text.index('aentry-post__socials--bottom', start)
    body = text[start:text.rindex("<div", start, end)]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return {"id": pid, "date": when.isoformat(), "slug": slug,
            "link": f"{HOST}/{pid}.html", "title": {"rendered": html.escape(title)},
            "content": {"rendered": body}, "categories": [CLUB_CATEGORY]}


def write_records():
    """Fetch and parse every post in POSTS into PARSED; return the records."""
    import parse_timesforthetimes as tftt
    recs = []
    for number, pid in sorted(POSTS.items()):
        rec = tftt.parse_post(as_post(pid, page(pid)))
        if rec is None or rec["number"] != number:
            print(f"  {number} ({HOST}/{pid}.html): "
                  + ("no entries" if rec is None else f"reads as No {rec['number']}"))
            continue
        clued = sum(1 for e in rec["entries"] if e.get("clue"))
        print(f"  {number}: {len(rec['entries'])} entries, {clued} with clue text")
        recs.append(rec)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = PARSED.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                   encoding="utf-8")
    tmp.replace(PARSED)
    return recs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan", nargs="+", metavar="YYYY/MM",
                    help="list the club posts LiveJournal holds for these months")
    ap.add_argument("--rebuild", action="store_true",
                    help="fetch and parse POSTS, then backsolve their grids")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    a = ap.parse_args(argv)
    if a.scan:
        for month in a.scan:
            for pid, title in scan(month):
                print(f"{month} {HOST}/{pid}.html {title}")
        return 0
    if a.rebuild:
        write_records()
        import times_grids as tg
        import parse_timesforthetimes as tftt
        r = tg.run(where=CACHE, series=tftt.SERIES[CLUB_CATEGORY])
        if r:
            tg.report(r)
        return 0
    if not GRIDS.exists():
        raise SystemExit(f"no {GRIDS}: run with --rebuild first")
    file_all(write=not a.dry_run)
    return 0


def file_all(write=True):
    """File every grid in GRIDS the way tools/file_times_puzzles.py files the
    blog's, named as this tool's."""
    import file_blog_puzzles
    import file_times_puzzles as ftp
    source = file_blog_puzzles.Source(
        tool=TOOL, target=ftp.target,
        print_dates=lambda recs, renumbered: ftp.print_dates(recs, None, renumbered),
        setter=ftp.setter, run=ftp.numbering, tidy=ftp.tftt.tidy)
    return file_blog_puzzles.run(source, GRIDS, PARSED, write=write)


if __name__ == "__main__":
    sys.exit(main())
