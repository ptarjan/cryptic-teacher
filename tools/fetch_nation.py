#!/usr/bin/env python3
"""The Nation's weekly cryptic, from the magazine's own article pages.

    python3 tools/fetch_nation.py urls         # list every puzzle page from the sitemaps
    python3 tools/fetch_nation.py download     # fetch the pages not yet held
    python3 tools/fetch_nation.py file [N...]  # file every held page (or these numbers)

thenation.com prints each puzzle as an HTML clue list, numbered and with
enumerations: Kosman and Picciotto's since 2011, and the Frank W. Lewis
puzzles (1947-2009) the site reprinted in 2009-11 under their original number,
each page saying which issue it "originally appeared in". The pages carry no
grid a script can read (the printable PDF is barred by robots.txt) and no
answers, so the grid is rebuilt from the clue numbers and enumerations
(tools/reconstruct_grid.py) and the puzzle is filed unsolved for the backfill.
A page whose grid will not rebuild to exactly one grid is counted by reason
and left held in downloads.NATION for a later builder.

The puzzle number is the one the page's title prints, and its date is the
issue it first appeared in.
"""
import datetime
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import boilerplate  # the paper's publishing notes in the preamble; tools/boilerplate.py
import downloads
import enumeration  # a clue's printed counts; tools/enumeration.py
import light_spec
import reconstruct_grid as rg
from clues_only import entries_from_grid
from fetch_puzzle import has_words, puzzle_path, write_puzzle_file
from file_penguin_puzzle import separators
from groups import entry_id, is_pointer
from normalise_linked_enumerations import normalise_record, resolve_groups
from series import puzzle_id

SERIES = "nation"
TOOL = "tools/fetch_nation.py"
SITE = "https://www.thenation.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
DIR = downloads.NATION
PAGES = DIR / "html"
URLS = DIR / "urls.json"
SLEEP_SECONDS = 1.5
# The Nation prints 15x15 and 13x13 blocked grids; the rebuild tries those.
SIZES = (15, 13)
MAX_NODES = 400_000
PUZZLE_URL = re.compile(r"/article/[a-z0-9-]+/(?:[a-z-]*puzzle-(?:no-)?\d+(?:-\d)?|crossword-classic-\d+)/?$")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def list_urls():
    """Every puzzle page the sitemaps name, written to URLS."""
    maps = re.findall(r"<loc>([^<]+)</loc>", get(f"{SITE}/sitemap_index.xml"))
    found = set()
    for m in maps:
        if "/article-sitemap" not in m:
            continue
        for _ in range(3):
            try:
                found.update(u for u in re.findall(r"<loc>([^<]+)</loc>", get(m))
                             if PUZZLE_URL.search(u))
                break
            except OSError as e:
                print(f"{m}: {e}", file=sys.stderr)
                time.sleep(10)
        time.sleep(0.3)
    DIR.mkdir(parents=True, exist_ok=True)
    URLS.write_text(json.dumps(sorted(found), indent=0) + "\n")
    print(f"{len(found)} puzzle pages in {len(maps)} sitemaps")


def page_path(url):
    return PAGES / (url.rstrip("/").rsplit("/", 1)[1] + ".html")


def download():
    PAGES.mkdir(parents=True, exist_ok=True)
    urls = json.loads(URLS.read_text())
    todo = [u for u in urls if not page_path(u).exists()]
    print(f"{len(todo)} of {len(urls)} pages to fetch", flush=True)
    for i, url in enumerate(todo, 1):
        try:
            text = get(url)
        except OSError as e:
            print(f"{url}: {e}", flush=True)
            time.sleep(30)
            continue
        page_path(url).write_text(text)
        if i % 50 == 0:
            print(f"{i}/{len(todo)}", flush=True)
        time.sleep(SLEEP_SECONDS)


# ------------------------------------------------------------------ parsing

BLOCK = re.compile(r"(?i)<br\s*/?>|</(?:div|p|li|h\d|tr)>")
NUMBERED = re.compile(r"^(\d{1,2})\b\s*(.*)$")
# "8 and 1 down", "12, 20 across", "3/14": the extra numbers of a linked clue.
LINKED = re.compile(r"^((?:\s*(?:,|and|&|/)\s*\d{1,2}(?:\s*(?:across|down))?)+)\s+(.*)$", re.I)
ENUM = re.compile(r"^(.*?)\s*\(\s*([\d][\d\s,.'’\-–]*)\s*\)\s*$")
SEE = re.compile(r"^see\s+(\d{1,2})(?:\s*-?\s*(?:across|down))?\s*\.?$", re.I)


def lines_of(page):
    """The article body as text lines, the clue list among them."""
    start = page.find("<article")
    end = page.find("Submit a correction", start)
    body = page[start:end if end > 0 else None]
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", body)
    body = BLOCK.sub("\n", body)
    text = html.unescape(re.sub(r"<[^>]+>", "", body))
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


def meta(page):
    title = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    title = html.unescape(title.group(1)) if title else ""
    number = re.search(r"\bPuzzle\s*(?:No\.?\s*)?(\d+)\b", title, re.I)
    flat = html.unescape(re.sub(r"<[^>]+>", "", page))
    original = re.search(r"originally appeared in the (\w+ \d{1,2}, \d{4}),? issue", flat)
    issue = (original or re.search(r"This article appears in the\s+(\w+ \d{1,2}, \d{4})\s+issue", flat))
    author = re.search(r'aria-label="author name ([^"]+)"', page)
    date = None
    if issue:
        date = datetime.datetime.strptime(issue.group(1), "%B %d, %Y").date().isoformat()
    else:
        # A page naming no issue is dated the day it went online.
        posted = re.search(r'<meta property="article:published_time" content="(\d{4}-\d\d-\d\d)', page)
        date = posted.group(1) if posted else None
    return {"title": title, "number": int(number.group(1)) if number else None,
            "date": date, "original": bool(original), "setter": html.unescape(author.group(1)) if author else None}


def clue_lists(lines):
    """({"across": [...], "down": [...]}, preamble lines): light_spec's entries
    ({"number", "clue", "enumeration"}) in printed order."""
    # The page's excerpt above the body can repeat the first clue under its
    # own ACROSS, so the list is the last ACROSS before the last DOWN.
    downs = [i for i, ln in enumerate(lines) if ln.upper() == "DOWN"]
    acrosses = [i for i, ln in enumerate(lines) if ln.upper() == "ACROSS"
                and downs and i < downs[-1]]
    if not acrosses:
        return None, []
    a, d = acrosses[-1], downs[-1]
    out = {}
    for direction, part in (("across", lines[a + 1:d]), ("down", lines[d + 1:])):
        entries, pending = [], None
        for ln in part:
            m = NUMBERED.match(ln)
            if m and (pending is None or not pending.get("open")):
                if pending:
                    entries.append(pending)
                pending = {"number": m.group(1), "text": m.group(2), "open": True}
            elif pending is not None and m is None and pending.get("open"):
                pending["text"] = (pending["text"] + " " + ln).strip()
            elif m and pending is not None:
                entries.append(pending)
                pending = {"number": m.group(1), "text": m.group(2), "open": True}
            else:
                break
            # A clue is closed by its enumeration or its "See N" — the pointer
            # and nothing else (groups.POINTER). "See 2 if confused about" is
            # the first line of a clue of its own (3257's 1-across) and runs on.
            t = pending["text"]
            if ENUM.match(t) or SEE.match(t) or is_pointer(t, counted=True):
                pending["open"] = False
        if pending and pending["text"]:
            entries.append(pending)
        rows = []
        for e in entries:
            number, text = e["number"], e["text"]
            link = LINKED.match(text)
            if link:
                extra = re.findall(r"\d{1,2}", link.group(1))
                number = ",".join([number] + extra)
                text = link.group(2)
            see = SEE.match(text)
            if see:
                rows.append({"number": number, "clue": f"See {see.group(1)}", "enumeration": None})
                continue
            m = ENUM.match(text)
            rows.append({"number": number, "clue": (m.group(1) if m else text).strip(),
                         "enumeration": re.sub(r"\s+", "", m.group(2)).replace("–", "-")
                         if m else None})
        out[direction] = rows
    return out, lines[:a]


def preamble_of(head):
    """The setters' note to solvers above the clue list, if any."""
    keep, on = [], False
    for ln in head:
        if "Word Salad" in ln or "printable PDF" in ln:
            on = True
            continue
        if on and not re.search(r"freestar|placementName|slotId|targeting|^Click$|^HERE$", ln):
            keep.append(ln)
    # The page's chrome sits in the same stretch on many pages: the share bar
    # with its byline and dates ("Joshua Kosman and Henri Picciotto Share Copy
    # Link Facebook ... This article appears in the November 5, 2012 issue."),
    # newsletter and subscription blurbs, the "Puzzled? ..." promo. None of it
    # is a note to solvers; tools/boilerplate.py names it, and the corpus audit
    # (puzzle_integrity.check_preamble) refuses a preamble still holding it.
    text = " ".join(keep).strip()
    return boilerplate.strip(text) or None


# Pages below this number are Lewis reprints of 2009-11; from it on (Lewis's
# last run, 2008-09, then Kosman and Picciotto) each is dated by its own issue.
REPRINTS_BELOW = 3100
# How far a reprint naming no original issue may be dated from the nearest
# number that names one, a week a number.
NEIGHBOUR_REACH = 6


def original_dates():
    """{number: original issue date} for every held Lewis reprint naming one."""
    out = {}
    for path in PAGES.glob("*.html"):
        m = meta(path.read_text())
        if m["number"] and m["number"] < REPRINTS_BELOW and m.get("original"):
            out[m["number"]] = m["date"]
    return out


def reprint_date(number, known):
    """A reprint's original issue from the nearest number naming one, or None."""
    near = sorted(known, key=lambda n: abs(n - number))
    if not near or abs(near[0] - number) > NEIGHBOUR_REACH:
        return None
    day = datetime.date.fromisoformat(known[near[0]])
    return (day + datetime.timedelta(weeks=number - near[0])).isoformat()


def linked_groups(lists, across, down):
    """reconstruct_grid's `groups` for the linked answers: ([(direction,
    index)], total) per leader. The leader's printed number field names its
    lights ("8,1" for "8 and 1 down"), its enumeration the total (the sum of
    its words: 28 for "5,6,3,5,1,3,5"). Each continuation is the linked light
    of that number printing no enumeration of its own ("See 8"), in either
    direction; a group whose lights cannot all be told apart is left out, so
    its lengths stay free as before."""
    lights = {"across": across, "down": down}
    groups, used = [], set()
    for direction in ("across", "down"):
        for row in lists[direction]:
            nums = [int(x) for x in re.findall(r"\d+", str(row.get("number") or ""))]
            total = sum(int(t) for t in re.findall(r"\d+", row.get("enumeration") or ""))
            if len(nums) < 2 or not total:
                continue
            lead = [(direction, i) for i, lg in enumerate(lights[direction])
                    if lg[0] == nums[0] and lg[2].startswith("linked")
                    and (lg[3] or {}).get("enumeration")]
            members = lead if len(lead) == 1 else None
            for n in nums[1:]:
                if members is None:
                    break
                hit = [(d, i) for d in ("across", "down")
                       for i, lg in enumerate(lights[d])
                       if lg[0] == n and lg[2].startswith("linked")
                       and not (lg[3] or {}).get("enumeration")
                       and (d, i) not in used]
                members = members + hit if len(hit) == 1 else None
            if members and not used & set(members):
                used.update(members)
                groups.append((members, total))
    return groups


def read_page(page, known=None):
    """((meta, head, across, down, groups), None) or (None, why not): the
    page's clue list as light_spec lights, before any grid search."""
    m = meta(page)
    if m["number"] and m["number"] < REPRINTS_BELOW and not m["original"]:
        m["date"] = reprint_date(m["number"], known or {})
        if m["date"] is None:
            return None, "a reprint naming no original issue, no dated neighbour"
    if m["number"] is None:
        return None, f"title {m['title']!r} prints no puzzle number"
    if m["date"] is None:
        return None, "no issue date"
    lists, head = clue_lists(lines_of(page))
    if not lists or not lists["across"] or not lists["down"]:
        return None, "no ACROSS/DOWN clue list"
    across, down, notes, damage = light_spec.build_spec(lists)
    if damage:
        return None, "clue list damaged: " + "; ".join(damage)
    # A linked answer's count is by words, not by lights ("1 and 5 (4,3,3,4)"
    # may be 7+7 or 4+10), so its lights' lengths are left to the grid.
    for lg in across + down:
        if lg[2].startswith("linked"):
            lg[1] = None
    # ...but the group's total is printed, and which lights make it up.
    groups = linked_groups(lists, across, down)
    if any(lg[0] is None for lg in across + down):
        return None, "a light with no number"
    return (m, head, across, down, groups), None


def search_grid(across, down, groups):
    """(grid, None) or (None, why not). A size whose search ran out of budget
    is the reason given, even if a smaller size then finished empty."""
    spec = [(lg[0], d, lg[1]) for d, lights in (("across", across), ("down", down))
            for lg in lights]
    longest = max((n for _, _, n in spec if n), default=0)
    grid, why, first = None, "no size tried", None
    for size in SIZES:
        if size < longest:
            continue
        grid, why = rg.unique_grid(spec, cols=size, rows=size, max_nodes=MAX_NODES,
                                   groups=groups)
        if grid is not None or "grids fit" in (why or ""):
            return grid, why
        if first is None or "budget" in why and "budget" not in first:
            first = why
    return None, first or why


def clues_record(page, url, known=None):
    """The clues_only/ record (tools/clues_only.py) for a page whose clue list
    reads but whose grid did not rebuild, or None: only the clues are
    mandatory, so the backfill's answers derive the grid (promote())."""
    read, _ = read_page(page, known)
    if read is None:
        return None
    m, _, across, down, _ = read
    import clues_only
    clues, problems = clues_only.lights_from_spec(across, down)
    if problems:
        return None
    n = m["number"]
    return {"id": puzzle_id(SERIES, n), "number": n, "series": SERIES,
            "name": f"The Nation cryptic crossword No {n}", "setter": m["setter"],
            "date": m["date"], "dimensions": {"cols": SIZES[0], "rows": SIZES[0]},
            "source": {"url": url, "acquiredBy": TOOL,
                       "acquiredOn": datetime.date.today().isoformat()},
            "clues": clues}


def promote(record, answers):
    """clues_only.BUILDERS' entry for this filer: (puzzle, problems) from the
    grid the backfill's answers cross in, built from the held page exactly as
    a page whose grid rebuilt at filing time."""
    import clues_only
    grid, why = None, "no size tried"
    for size in SIZES:
        grid, why = clues_only.derive_grid(
            {**record, "dimensions": {"cols": size, "rows": size}}, answers)
        if grid is not None:
            break
    if grid is None:
        return None, [f"no single grid holds these answers: {why}"]
    url = record["source"]["url"]
    path = page_path(url)
    if not path.is_file():
        return None, [f"the page {path} is no longer held"]
    puzzle, why = build(path.read_text(), url, original_dates(), grid=grid)
    return (puzzle, []) if puzzle else (None, [why])


def build(page, url, known=None, grid=None):
    """(puzzle, None) or (None, why not). `grid`, when given, is used instead
    of searching for one (promote())."""
    read, why = read_page(page, known)
    if read is None:
        return None, why
    m, head, across, down, groups = read
    if grid is None:
        grid, why = search_grid(across, down, groups)
    if grid is None:
        return None, f"grid did not rebuild: {why}"
    entries, problems = entries_from_grid(grid, across, down)
    if problems:
        return None, "; ".join(problems)
    for e in entries:
        e["clue"] = (e["clue"] or "").strip()
    normalise_record({"puzzle": {"entries": entries}, "fill": {}})
    groups = resolve_groups(entries)
    by_id = {entry_id(e): e for e in entries}
    seps = {}
    for e in entries:
        if not e.get("enumeration"):
            continue
        ids = groups.get(entry_id(e), [entry_id(e)])
        if ids[0] != entry_id(e):
            return None, f"{entry_id(e)} carries an enumeration but is a continuation"
        try:
            seps.update(separators(ids, by_id, e["enumeration"]))
        except SystemExit as err:
            return None, str(err)
    out = []
    for e in entries:
        printed = e.pop("enumeration", None)
        line = f"{e['clue']} ({printed})" if printed else e["clue"]
        e["clue"] = enumeration.clue(line, separators=seps.get(entry_id(e)),
                                     missing=not has_words(enumeration.split(line)[0]))
        if groups.get(entry_id(e), [None])[0] == entry_id(e):
            e["group"] = list(groups[entry_id(e)])
        e["solution"] = None
        out.append(e)
    n = m["number"]
    puzzle = {
        "id": puzzle_id(SERIES, n),
        "number": n,
        "series": SERIES,
        "name": f"The Nation cryptic crossword No {n}",
        "setter": m["setter"],
        "date": m["date"],
        "preamble": preamble_of(head),
        "dimensions": {"cols": len(grid[0]), "rows": len(grid)},
        "source": {"publisher": "The Nation", "url": url, "retrievedFrom": "publisher",
                   "acquiredBy": TOOL, "acquiredOn": datetime.date.today().isoformat(),
                   "gridOrigin": "reconstructed"},
        "entries": out,
    }
    if not puzzle["preamble"]:
        del puzzle["preamble"]
    return puzzle, None


def _build_one(path):
    """(number, puzzle, why not) for one held page; run in a worker."""
    urls = _build_one.urls
    page = path.read_text()
    url = urls.get(path.name) or f"{SITE}/article/archive/{path.stem}/"
    number = meta(page)["number"]
    try:
        puzzle, reason = build(page, url, _build_one.known)
    except Exception as e:  # one bad page never stops the rest
        puzzle, reason = None, f"{type(e).__name__}: {e}"
    held = None
    if puzzle is None and reason.startswith("grid did not rebuild"):
        held = clues_record(page, url, _build_one.known)
    return number or path.stem, puzzle, reason, held


def file_all(numbers=None, workers=None):
    """File every held page not yet in puzzles/ (or just `numbers`). A page
    whose grid does not rebuild is held in clues_only/ for the backfill."""
    import multiprocessing
    import os
    import clues_only
    import puzzle_paths
    workers = workers or int(os.environ.get("NATION_WORKERS", "4"))
    _build_one.urls = {page_path(u).name: u for u in json.loads(URLS.read_text())}
    _build_one.known = original_dates()
    paths = sorted(PAGES.glob("*.html"))
    # "puzzle-no-1588-0", "puzzle-no-3161-2": a later copy of a page held plain.
    names = {p.name for p in paths}
    paths = [p for p in paths
             if not (re.search(r"-\d+-\d\.html$", p.name)
                     and re.sub(r"-\d\.html$", ".html", p.name) in names)]
    if numbers:
        paths = [p for p in paths if meta(p.read_text())["number"] in numbers]
    else:
        paths = [p for p in paths if not (meta(p.read_text())["number"] and puzzle_paths.find(
            puzzle_id(SERIES, meta(p.read_text())["number"])))]
    filed, held, why, seen = 0, 0, {}, set()
    with multiprocessing.Pool(workers) as pool:
        for number, puzzle, reason, record in pool.imap_unordered(_build_one, paths):
            if puzzle is None:
                why.setdefault(re.sub(r"\d+", "N", reason)[:90], []).append(number)
                if record is not None and record["id"] not in seen:
                    seen.add(record["id"])
                    try:
                        clues_only.write(record)
                        held += 1
                    except Exception as e:
                        key = f"clues-only refused: {type(e).__name__}: {str(e)[:70]}"
                        why.setdefault(re.sub(r"\d+", "N", key), []).append(number)
                continue
            if puzzle["id"] in seen:  # a page printed twice ("puzzle-no-1588-0")
                continue
            seen.add(puzzle["id"])
            try:
                write_puzzle_file(puzzle_path(SERIES, number), puzzle, generator=TOOL)
                filed += 1
            except Exception as e:
                key = f"write refused: {type(e).__name__}: {str(e)[:70]}"
                why.setdefault(re.sub(r"\d+", "N", key), []).append(number)
    print(f"filed {filed} of {len(paths)} pages; {held} held clues-only")
    for key, ids in sorted(why.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(ids):4d}  {key}  e.g. {sorted(map(str, ids))[:6]}")


def main(argv):
    if argv[:1] == ["urls"]:
        list_urls()
    elif argv[:1] == ["download"]:
        download()
    elif argv[:1] == ["file"]:
        file_all({int(a) for a in argv[1:]} or None)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
