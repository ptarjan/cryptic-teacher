#!/usr/bin/env python3
"""Private Eye Cyclops crosswords the Eye no longer serves, from the Wayback Machine.

Usage:
  python3 tools/privateeye_wayback.py fetch        # list and download every capture
  python3 tools/privateeye_wayback.py index        # print number -> what the captures hold
  python3 tools/privateeye_wayback.py read-scans 13 25   # read scans' page images (privateeye_scans.py)

The Eye's own .puz downloads (tools/fetch_privateeye.py) start at No 300
(Nov 2005) and fifteensquared's posts at Dec 2006. Before that the Eye's site
printed the current crossword as HTML text, and the Wayback Machine kept it:

  1998-2005  private-eye.co.uk/xword.htm (and /noframe/xword.htm): "EYE
             CROSSWORD 105 by Cyclops" / "No. 249", the clues, then
             "Solution to Crossword No. 104" (or "Crossword 248 winner") and
             that puzzle's answers. From about 2003 it links
             download/cyclops<N>.puz and images/grid<issue>.gif.
  2005-2012  sections.php?section_link=crossword[&issue=<issue>]: "No. 307 by
             Cyclops", the clues, then "Previous Crossword Solution".

So each capture gives one puzzle's clues and the one before's answers. The
crossword number is the issue number - 845 throughout (No 105 = issue 950,
May 1998; No 249 = issue 1094; No 307 = issue 1152).

Captures go to downloads.PRIVATE_EYE_WAYBACK/<timestamp>.html (one per
distinct digest), the CDX listing to cdx.txt beside them. They are untrusted
downloads: this only reads them as text.
"""
import argparse
import datetime
import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import clue_repair
import clue_text
import downloads
import provenance

TOOL = "tools/privateeye_wayback.py"
DIR = downloads.PRIVATE_EYE_WAYBACK
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
ISSUE_OFFSET = 845
MAX_NODES = 4_000_000
# (url, matchType) of every page that printed the crossword, and the .puz/.gif
# files the 2003-2005 page linked.
# The CDX key sorts a query's arguments ("issue=1165&section_link=crossword"),
# so sections.php is listed whole and filtered on the original URL.
PAGES = [("private-eye.co.uk/xword.htm", "exact", None),
         ("private-eye.co.uk/noframe/xword.htm", "exact", None),
         ("private-eye.co.uk/frames/xword.htm", "exact", None),
         ("private-eye.co.uk/sections.php", "prefix", "original:.*section_link=crossword.*")]
FILES = [("private-eye.co.uk/download/", "prefix", "original:.*puz"),
         ("private-eye.co.uk/images/grid", "prefix", None)]


def get(url, tries=4):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=120).read()
        except Exception as e:  # Wayback drops connections under load
            err = e
            time.sleep(5 * (i + 1))
    raise err


def cdx(url, match, flt=None, to="2013"):
    # No collapse=digest: on these urlkeys it dropped most captures (sections.php:
    # 4 of 132); listing() dedupes by digest instead.
    q = urllib.parse.urlencode({"url": url, "matchType": match, "to": to, "filter": "statuscode:200",
                                "fl": "timestamp,original,digest"})
    if flt:
        q += "&" + urllib.parse.urlencode({"filter": flt})
    return [line.split() for line in get("http://web.archive.org/cdx/search/cdx?" + q).decode().splitlines()]


def listing():
    rows = []
    for url, match, flt in PAGES + FILES:
        rows += [r for r in cdx(url, match, flt) if len(r) == 3]
    seen, out = set(), []
    for ts, orig, digest in rows:
        if digest not in seen:
            seen.add(digest)
            out.append((ts, orig, digest))
    return out


def local_name(ts, orig):
    tail = orig.rsplit("/", 1)[-1]
    if tail.endswith((".puz", ".gif")):
        return f"files/{ts}_{tail}"
    return f"{ts}.html"


def fetch():
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "files").mkdir(exist_ok=True)
    rows = listing()
    (DIR / "cdx.txt").write_text("".join(" ".join(r) + "\n" for r in rows))
    got = 0
    for ts, orig, _digest in rows:
        path = DIR / local_name(ts, orig)
        if path.exists():
            continue
        try:
            path.write_bytes(get(f"http://web.archive.org/web/{ts}id_/{orig}"))
            got += 1
        except Exception as e:
            print(f"{ts} {orig}: {e}", file=sys.stderr)
        time.sleep(1)
    print(f"{len(rows)} captures listed, {got} downloaded to {DIR}")
    save_summary()


# ---------- reading a capture ----------

NUMBER = re.compile(r"EYE CROSSWORD\s+(\d{1,3})\b|\bNo\.\s*(\d{1,3})\s+(?=by Cyclops|'|ACROSS)", re.I)
SOLUTION = re.compile(r"Solution to Crossword No\.?\s*(\d{1,3})|Crossword\s+(\d{1,3})\s+winner"
                      r"|(Previous Crossword Solution)", re.I)
TAIL = re.compile(r"\bEntries to\b|Back to Private Eye|£\s?\d|\bThis site features\b"
                  r"|Arrived here unexpectedly|Send your entries", re.I)
#: A link's tail naming its direction: "23/4dn" (No 112), "4/16ac/22dn".
LINK_SIDE = r"\s*(?:across|down|ac|dn)\b\.?|[ad]\b\.?"
ENUM = clue_text.ENUM_OR_SEE
SEE_TAIL = r"See \d{1,2}\s*(?:ac|dn|across|down)?\.?"
CLUE = re.compile(r"(?:^|(?<=\s))(\d{1,2}(?:\s*/\s*\d{1,2}(?:" + LINK_SIDE + r")?)*)\s+(.*?)\s*(" + ENUM + "|"
                  + SEE_TAIL + r")(?=\s+\d{1,2}\s*[/\s(A-Za-z\"'£]|\s*$)", re.I)
ANSWER = re.compile(r"(\d{1,2}(?:/\d{1,2})*)\s+([^\d]+?)(?=\s+\d{1,2}[\s/]|\s*\.?\s*$)")


def text_of(raw, encoding="cp1252", plain=False):
    """One line of text. `plain` (an archive.org scan's OCR text) is not HTML:
    a stray "<" in the OCR would otherwise eat everything up to the next ">"
    as a tag, which lost the crossword from 6 in 10 scans."""
    t = raw.decode(encoding, "replace")
    if not plain:
        t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
        t = re.sub(r"<[^>]+>", " ", t)
        t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def split_dirs(part):
    """'ACROSS ... DOWN ...' -> (across text, down text) or None."""
    # Headings by case and a following number, so a clue's "going down on" isn't one
    # (or a scan's "|", "l", "I" misread for 1 before a capital: "DOWN | Picture").
    m = re.search(r"\b(?:ACROSS|Across)\b\s*:?(.*?)\b(?:DOWN|Down)\b\s*:?(?=\s*(?:\d|[|lIi]\s+(?:[A-Z]|\(see)))(.*)$", part, re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def clue_rows(part, scan=False):
    """light_spec rows ({"number", "clue", "enumeration"}) of one direction's
    text, or None if any text is left between or after the clues. A scan's
    OCR (`scan`) may leave punctuation specks between clues, and after the
    last across clue the grid's OCR junk: text with no enumeration in it,
    dropped (a real clue lost in it leaves a light the grid rebuild refuses)."""
    if scan:
        part = clue_text.mend_scan_text(" " + part)
        # Grid junk with no digit straight after the last clue's enumeration
        # ("... Dead mad-looking (4-4) eS ; i aes Ane", No 328) hid that clue.
        last = None
        for last in re.finditer(ENUM, part, re.I):
            pass
        if last and not re.search(r"\d", part[last.end():]):
            part = part[:last.end()]
    rows, pos = [], 0
    for m in CLUE.finditer(part):
        gap = part[pos:m.start()]
        if gap.strip() and not (scan and not re.search(r"[A-Za-z0-9]", gap)):
            return None
        pos = m.end()
        nums = re.findall(r"\d{1,2}", m.group(1))
        # "23/4dn": the tail's direction kept, for from_rows to link by.
        sides = {n: "across" if d.strip()[0].lower() == "a" else "down"
                 for n, d in re.findall(r"/\s*(\d{1,2})(" + LINK_SIDE + ")", m.group(1), re.I)}
        text, tail = m.group(2).strip(), m.group(3)
        see = re.match(r"\(?\s*see (\d{1,2})", tail, re.I)
        if see and not text:
            rows.append({"number": nums[0], "clue": f"See {see.group(1)}", "enumeration": None})
            continue
        if see:
            return None
        rows.append({"number": ",".join(nums), "clue": text,
                     "enumeration": re.sub(r"\s+", "", tail[1:-1]).replace("–", "-"),
                     **({"linkSides": sides} if sides else {})})
    left = part[pos:]
    if scan and not re.search(ENUM, left, re.I) and not re.search(r"\bSee \d", left):
        left = ""
    if left.strip() or not rows:
        return None
    return rows


def answer_rows(part, direction):
    """fetch_privateeye.solve_from_rows rows [(key, direction, LETTERS)]."""
    out = []
    # "DOWN: i Emma 2 Orgasm": the scan's 1 read as a letter (No 54).
    part = re.sub(r"^\s*[|lIi](?=\s+(?:[A-Z]|\(see))", "1", part)
    # The page's next item runs on after the last answer ("23 Blair. MONDAY,
    # MARCH 3, 44 BC ..."): it swallowed No 73's 23dn and added keys 0, 4, 94.
    part = re.split(r"\.\s+(?=[A-Z]{4,}\b)", part)[0]
    # A speck before a number ("2 Belgrano -3 Oppo", No 63) hid 2dn's end.
    part = re.sub(r"\s[-\u2013\u2014~]+(?=\d)", " ", part)
    # "12Ethelred", "28See.": the scan ran the number into its answer (No 27, 61).
    part = re.sub(r"(?:(?<=\s)|^)(\d{1,2})(?=[A-Za-z]{2,})", r"\1 ", part)
    seen = set()
    for key, words in ANSWER.findall(part):
        words = _unjunk(words)
        # "28 See. factor": the column broke inside the linked "12/14 Feel-good
        # factor"; the lowercase tail belongs to the last linked answer (No 27).
        wrap = re.match(r"([A-Z][a-z]+\.)\s+([a-z][a-z' \-]*)$", words)
        linked = [i for i, r in enumerate(out) if "/" in r[0]]
        if wrap and linked:
            k, d, lt = out[linked[-1]]
            out[linked[-1]] = (k, d, lt + re.sub(r"[^A-Z]", "", wrap.group(2).upper()))
            words = wrap.group(1)
        if re.match(r"\s*\(?see\b(?!\.)", words, re.I) or key in seen:
            continue
        letters = re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", words).upper())
        if letters and len(letters) <= 40 and 0 < int(key.split("/")[0]) <= 40:
            seen.add(key)
            out.append((key, direction, letters))
    return out


def _unjunk(words):
    """An answer's words without the speckle the scan read from the picture
    beside them ("Minors JA, : yy, ee", No 61): from the first token with a
    stray comma, colon or bar, if only short tokens follow it."""
    toks = words.split()
    for i, t in enumerate(toks[1:], 1):
        if re.search(r"[,:;|]", t) and not re.search(r"[A-Za-z]{4}", " ".join(toks[i:])):
            return " ".join(toks[:i])
    return words


def scan_number(t, issue):
    """(number, end of heading) of a scan whose "EYE CROSSWORD N" the OCR
    mangled ("EYE CROSSWORI by Cyclops D 157"): a number near "by Cyclops"
    within 2 of the one the issue implies (issue - ISSUE_OFFSET, which drifts
    by one in the early years), else the solution's number + 1 if that is."""
    want = issue - ISSUE_OFFSET
    for m in re.finditer(r"\bby Cyclops\b", t, re.I):
        near = t[max(0, m.start() - 60):m.end() + 40]
        for n in re.findall(r"(?<![\d£])(\d{1,3})(?![\d,)])", near):
            if abs(int(n) - want) <= 2:
                return int(n), m.end()
        sol = SOLUTION.search(t, m.end())
        if sol and sol.group(1) and abs(int(sol.group(1)) + 1 - want) <= 2:
            return int(sol.group(1)) + 1, m.end()
    return None


def read_capture(raw, encoding="cp1252", plain=False, issue=None):
    """{"number", "rows": {"across", "down"} | None, "prev", "answers": [...] | None}.
    `plain` and `issue`: an archive.org scan's OCR text, of that issue."""
    t = text_of(raw, encoding, plain)
    m = NUMBER.search(t)
    if m and issue and abs(int(m.group(1) or m.group(2)) - (issue - ISSUE_OFFSET)) > 2:
        m = None  # a misread heading ("EYE CROSSWORD 883" in issue 883)
    if m:
        num, end = int(m.group(1) or m.group(2)), m.end()
    elif issue and scan_number(t, issue):
        num, end = scan_number(t, issue)
    else:
        return None
    body = t[end:]
    sol = SOLUTION.search(body)
    clues = body[:sol.start()] if sol else body
    # The print issue (archive.org scans) sets "£100 prize" above ACROSS and
    # the entry notice under the last down clue: keep ACROSS up to that notice.
    # The heading in capitals first: an article's "across London" (No 245) is not it.
    across = re.search(r"\bACROSS\b", clues) or re.search(r"\bACROSS\b", clues, re.I)
    if across:
        clues = TAIL.split(clues[across.start():])[0]
    out = {"number": num, "rows": None, "prev": None, "answers": None}
    dirs = split_dirs(clues)
    if dirs:
        a, d = clue_rows(dirs[0], plain), clue_rows(dirs[1], plain)
        if a and d:
            a, d = clue_repair.repair_rows(a, d)
        # Square 1 starts a light: a list missing it lost its first clues
        # (a scan's column set above its heading), refused before the
        # minutes a grid search spends finding no grid.
        if a and d and "1" in (a[0]["number"].split(",")[0], d[0]["number"].split(",")[0]):
            out["rows"] = {"across": a, "down": d}
    if sol:
        out["prev"] = int(sol.group(1) or sol.group(2)) if not sol.group(3) else num - 1
        rest = body[sol.end():]
        rest = re.sub(r"^\s*Winner:?\s*[^A-Z]*[A-Z.\s'\-]+?(?=ACROSS)", "", rest)
        rest = TAIL.split(rest)[0]
        dirs = split_dirs(rest)
        if dirs:
            out["answers"] = answer_rows(dirs[0], "across") + answer_rows(dirs[1], "down")
    return out


def index():
    """{number: {"clues": [(ts, rows)], "answers": [(ts, rows)], "puz": path|None}}."""
    got = {}
    # Web captures, then the archive.org print scans (IA/<issue>_djvu.txt, UTF-8).
    # Last, a scan's clues read off its page image (privateeye_scans.py), so
    # build() takes them over the same scan's OCR text.
    for path in (sorted(DIR.glob("*.html")) + sorted((DIR / "ia").glob("*_djvu.txt"))
                 + sorted((DIR / "ia").glob("*_page.txt"))):
        try:
            scan = path.suffix == ".txt"
            cap = read_capture(path.read_bytes(), "utf-8" if scan else "cp1252", plain=scan,
                               issue=int(path.stem.split("_")[0]) if scan else None)
        except Exception as e:  # one odd capture never stops the rest
            print(f"{path.name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if not cap:
            continue
        ts = path.stem
        if cap["rows"]:
            got.setdefault(cap["number"], {}).setdefault("clues", []).append((ts, cap["rows"]))
        if cap["answers"]:
            got.setdefault(cap["prev"], {}).setdefault("answers", []).append((ts, cap["answers"]))
    for path in sorted((DIR / "files").glob("*_cyclops*.puz")):
        n = int(re.search(r"cyclops(\d+)\.puz", path.name).group(1))
        got.setdefault(n, {})["puz"] = str(path)
    return got


def fetch_ia(numbers=None):
    """Download the OCR text of the archive.org scan of each Cyclops number's
    issue (item private-eye-magazine-<issue>, file <issue>_djvu.txt), for the
    numbers not filed (or `numbers`). Issues 846 on are there (531 items in all,
    2026-10-13): No 1 is issue 846."""
    import puzzle_paths
    (DIR / "ia").mkdir(parents=True, exist_ok=True)
    nums = numbers or [n for n in range(LOST_FIRST, LOST_LAST + 1)
                       if not puzzle_paths.find(f"cyclops-{n}")]
    got = 0
    for n in nums:
        issue = n + ISSUE_OFFSET
        path = DIR / "ia" / f"{issue}_djvu.txt"
        if path.exists():
            continue
        try:
            path.write_bytes(get(IA_TEXT.format(issue=issue), tries=2))
            got += 1
        except Exception as e:
            print(f"cyclops-{n} (issue {issue}): {e}", file=sys.stderr)
        time.sleep(1)
    print(f"{got} scan texts downloaded to {DIR / 'ia'}")
    save_summary()


IA_TEXT = "https://archive.org/download/private-eye-magazine-{issue}/{issue}_djvu.txt"


def read_scans(numbers):
    """Read each number's clues off its archive.org scan's page image
    (privateeye_scans.read) into ia/<issue>_page.txt, for `file` to file.
    The number runs a step off issue - ISSUE_OFFSET in the early years
    (No 13 is in issue 857), so the issues either side are read too when
    the first holds another number. Returns {number: why not}."""
    import privateeye_scans
    why, done = {}, {}  # done: issue -> (number it prints, why not)
    for n in numbers:
        last = None
        for issue in (n + ISSUE_OFFSET, n + ISSUE_OFFSET - 1, n + ISSUE_OFFSET + 1):
            path = DIR / "ia" / f"{issue}_page.txt"
            if not (DIR / "ia" / f"{issue}_djvu.txt").exists():
                continue
            if issue in done:  # read for the number before: its outcome stands
                got, reason = done[issue]
                if got == n:
                    if reason:
                        why[n] = reason
                    break
                continue
            try:
                got, text, reason = privateeye_scans.read(issue, get)
            except Exception as e:  # one bad scan is a reason, not the end of the run
                got, text, reason = None, None, f"{type(e).__name__}: {e}"
            done[issue] = (got, reason)
            print(f"  issue {issue}: No {got}: {reason or 'read'}", flush=True)
            last = last or (got is None and reason)
            if text:
                path.write_text(text + "\n")
            else:  # an earlier reading this one refuses is no capture
                path.unlink(missing_ok=True)
            if got == n:
                if reason:
                    why[n] = reason
                break
        else:
            why.setdefault(n, last or "no scan of the issue or those either side prints it")
    return why


def capture_url(ts):
    """The Wayback (or archive.org) URL a capture was read from."""
    if ts.endswith(("_djvu", "_page")):
        return f"https://archive.org/details/private-eye-magazine-{ts[:-5]}"
    for line in (DIR / "cdx.txt").read_text().splitlines():
        t, orig, _ = line.split()
        if t == ts:
            return f"https://web.archive.org/web/{ts}/{orig}"
    return f"https://web.archive.org/web/{ts}/http://www.private-eye.co.uk/xword.htm"


# ---------- building a puzzle ----------

def build(num, held):
    """(puzzle, None) or (None, why not) for Cyclops `num` from its captures."""
    import fetch_privateeye as fp
    clues = held.get("clues") or []
    if held.get("puz") and clues:
        try:  # a truncated capture of the .puz (184) leaves the page's clues
            fp.parse_puz(Path(held["puz"]).read_bytes())
        except ValueError as e:
            print(f"  cyclops-{num}: the .puz does not read ({e}); using the page")
            held = {**held, "puz": None}
    if held.get("puz"):
        puz = fp.parse_puz(Path(held["puz"]).read_bytes())
        puzzle = fp.convert(num, puz)
        url = capture_url(Path(held["puz"]).name.split("_")[0])
        how = "the Eye's own .puz, from the Wayback Machine"
    elif clues:
        ts, rows = clues[-1]
        # Two issues' pages read as one number (a heading lost and the
        # solution's number misread) with different clues: neither is sure.
        pages = {json.dumps(r, sort_keys=True) for t, r in clues if t.endswith("_page")}
        if len(pages) > 1:
            return None, "two scans' page images print different clues under this number"
        puzzle, why = from_rows(num, rows, held.get("answers"), page_grid(ts))
        if puzzle is None:
            return None, why
        url = capture_url(ts)
        how = {"_djvu": "the issue's archive.org scan, its OCR text",
               "_page": "the issue's archive.org scan, its page image read by OCR"}.get(
                   ts[-5:], "the Eye's crossword page, from the Wayback Machine")
    else:
        return None, "no capture prints its clues"
    puzzle["source"] = {"publisher": "Private Eye", "url": url,
                        "retrievedFrom": "archive.org" if "/details/" in url else "web.archive.org",
                        "acquiredBy": TOOL, "acquiredOn": datetime.date.today().isoformat(),
                        **({} if held.get("puz") else
                           {"gridOrigin": "published" if puzzle.pop("gridFromScan", False)
                            else "reconstructed"})}
    if not puzzle.get("date"):
        day = fp.fetch_cover_date(num + ISSUE_OFFSET)
        puzzle["date"] = day.isoformat() if day else None
    for ts, rows in held.get("answers") or []:
        solutions, problem = fp.solve_from_rows(puzzle, rows)
        if solutions:
            for e in puzzle["entries"]:
                e["solution"] = solutions[f"{e['number']}-{e['direction']}"]
            # The Eye's own printed solution: the published origin, no detail.
            puzzle = provenance.drop_solution_detail(puzzle)
            print(f"  cyclops-{num}: answers from the solution printed in capture {ts}")
            break
        print(f"  cyclops-{num}: the answers in capture {ts} do not fit: {problem}")
    print(f"  cyclops-{num}: {how}")
    return puzzle, None


def page_grid(ts):
    """The grid trove_grid reads off capture `ts`'s scanned page
    (ia/pages/<issue>_<leaf>.jpg, an "<issue>_page" or "<issue>_djvu"
    capture), or None: no page image, or none reads as one 15x15 grid."""
    issue, _, kind = str(ts).partition("_")
    if kind not in ("page", "djvu") or not issue.isdigit():
        return None
    import trove_grid
    grids = []
    for path in sorted((DIR / "ia" / "pages").glob(f"{issue}_*.jpg")):
        try:
            grid, _why = trove_grid.read_grid(path)
        except Exception:  # an unreadable leaf is no evidence either way
            grid = None
        if grid and len(grid) == 15 and len(grid[0]) == 15:
            grids.append(grid)
    return grids[0] if len(grids) == 1 else None


def grid_misfits(grid, spec, groups=None):
    """What of the clue list `spec` ((number, direction, length) in printed
    order, None where unread) and its linked `groups` ([(direction, index),
    ...], total) the grid does not print: [] when it prints exactly these
    lights, the same count each way, numbered and as long as the list says."""
    import reconstruct_grid as rg
    lights = rg.lights_from_grid(grid)
    off, cells = [], {}
    for d in ("across", "down"):
        have = [(n, size) for n, dd, size in lights if dd == d]
        want = [(n, size) for n, dd, size in spec if dd == d]
        if len(have) != len(want):
            off.append(f"{len(want)} {d} clues, {len(have)} {d} lights")
            continue
        for i, ((gn, gsize), (n, size)) in enumerate(zip(have, want)):
            if n is not None and n != gn:
                off.append(f"{n} {d} is numbered {gn}")
            elif size is not None and size != gsize:
                off.append(f"{n} {d} counts {size}, {gsize} cells")
            cells[(d, i)] = gsize
    for members, total in groups or []:
        got = [cells.get(tuple(m)) for m in members]
        if None not in got and sum(got) != total:
            off.append(f"a linked answer counts {total}, its lights {sum(got)} cells")
    return off


def repair_grid(grid, spec, groups=None, max_misfits=3):
    """(grid, cells) where the scan's `grid` misreads a cell or two -- a
    black square read white or the reverse (No 44's 20ac read eight cells
    where the page shows seven) -- and exactly one way of flipping one cell,
    one cell and its 180-degree partner, or two such pairs makes it print
    the clue list exactly (grid_misfits empty); else (None, None). The clue
    list, which the printed counts and answers confirm, is the evidence;
    two repairs that fit settle nothing."""
    if len(grid_misfits(grid, spec, groups)) > max_misfits:
        return None, None
    size = len(grid)
    flips = []
    for y in range(size):
        for x in range(size):
            p = (size - 1 - y, size - 1 - x)
            flips.append(((y, x),))
            if p > (y, x):
                flips.append(((y, x), p))
    def flipped(cells):
        rows = [list(r) for r in grid]
        for y, x in cells:
            rows[y][x] = "." if rows[y][x] == "#" else "#"
        return ["".join(r) for r in rows]
    pairs = [f for f in flips if len(f) == 2]
    for tries in (flips, [a + b for i, a in enumerate(pairs) for b in pairs[i + 1:]]):
        fits = {}
        for cells in tries:
            g = flipped(cells)
            if not grid_misfits(g, spec, groups):
                fits.setdefault(tuple(g), cells)
        if len(fits) == 1:
            (g, cells), = fits.items()
            return list(g), cells
        if fits:
            return None, None
    return None, None


def correct_counts(num, rows, table=None):
    """`rows` with each count the OCR misread put right, by the rows of
    fetch_puzzle.SOURCE_LIGHT_WRONG (or `table`) keyed cyclops-`num`: served
    {"enumeration": <as read>} -> corrected {"enumeration": <as printed>}.
    The row holds the evidence (the page seen, the next issue's answer), so
    no count changes silently; a row whose count the reading no longer
    serves is warned about and left alone. A linked head ("11,24") is keyed
    by its first number."""
    import fetch_puzzle
    pid = f"cyclops-{num}"
    table = fetch_puzzle.SOURCE_LIGHT_WRONG if table is None else table
    rows = {d: [dict(r) for r in rows.get(d) or []] for d in ("across", "down")}
    for (row_pid, eid), (served, corrected, _why) in table.items():
        if row_pid != pid:
            continue
        n, _, d = eid.partition("-")
        hit = [r for r in rows.get(d, []) if re.split(r"\D+", str(r.get("number") or ""))[0] == n]
        if len(hit) != 1 or hit[0].get("enumeration") != served.get("enumeration"):
            print(f"WARNING: SOURCE_LIGHT_WRONG {pid} {eid} is STALE: the reading serves "
                  f"{[r.get('enumeration') for r in hit]}, not {served} -- left as read",
                  file=sys.stderr)
            continue
        hit[0]["enumeration"] = corrected["enumeration"]
        print(f"  {pid}: {eid} counts ({corrected['enumeration']}), the OCR read "
              f"({served['enumeration']}) (SOURCE_LIGHT_WRONG)")
    return rows


def count_hint(num, misfits):
    """The refusal's pointer when the scan's grid disagrees with the list only
    in single lights' counts: each may be a misread count, which a
    SOURCE_LIGHT_WRONG row puts right once the page or the printed answer
    confirms the scan's length -- never on the scan's word alone."""
    if not misfits or not all(re.fullmatch(r"\d+ (across|down) counts \d+, \d+ cells", m)
                              for m in misfits):
        return ""
    m = re.match(r"(\d+) (across|down) counts (\d+), (\d+) cells", misfits[0])
    return (f"; if the page prints the scan's length, add fetch_puzzle.SOURCE_LIGHT_WRONG"
            f"[('cyclops-{num}', '{m[1]}-{m[2]}')] = ({{'enumeration': <as read>}}, "
            f"{{'enumeration': <as printed, {m[4]} letters>}}, why)")


def named_tails(rows, entries):
    """{entry id: printed clue} of each "See N" tail a head's linkSides names
    (clue_rows), its clue made "See N <head's direction>" in `entries` so
    resolve_groups takes that head, not the same number in the tail's own
    direction."""
    from groups import entry_id
    by = {(str(e["number"]), e["direction"]): e for e in entries}
    printed = {}
    for side in ("across", "down"):
        for row in rows.get(side) or []:
            head = str(row.get("number") or "").split(",")[0]
            for n, d in (row.get("linkSides") or {}).items():
                e = by.get((n, d))
                if e and re.fullmatch(r"See " + head + r"\.?", e["clue"] or "", re.I):
                    printed[entry_id(e)] = e["clue"]
                    e["clue"] = f"See {head} {side}"
    return printed


def pin_word_lengths(groups, across, down):
    """Give a linked group's lights their lengths when its enumeration has one
    number per light ("6,7" over 11 across and 1 down): the words are the
    lights, so nothing is left to search. Mutates the lights, returns the
    groups still open. Cyclops 63 and 73 ran out of budget with the split
    free and prove empty in seconds with it pinned."""
    lights = {"across": across, "down": down}
    left = []
    for members, total in groups:
        lead = lights[members[0][0]][members[0][1]]
        sizes = [int(t) for t in re.findall(r"\d+", (lead[3] or {}).get("enumeration") or "")]
        if len(sizes) == len(members) and sum(sizes) == total and min(sizes) > 0:
            for (d, i), size in zip(members, sizes):
                lights[d][i][1] = size
        else:
            left.append((members, total))
    return left


def from_rows(num, rows, answers=None, image=None, fixes=None):
    """A puzzle with no answers from light_spec rows, its grid rebuilt from
    the clue numbers and enumerations (as tools/fetch_nation.py does).
    `answers`, [(ts, answer_rows)] from the solution the next issue printed:
    each single light's answer goes into the search, so the one grid they
    agree in is found where the clue list alone fits two (Nos 56, 59).
    `image`, the grid read off the issue's scanned page (page_grid): when it
    prints exactly the clue list's lights it is the grid, with no search --
    the evidence that settles a list two grids fit (No 269), or one the
    search runs out of budget on. One that disagrees is no evidence, and
    the refusal says where it disagrees (No 30's 22dn reads "(6)" over five
    cells)."""
    import light_spec
    from clues_only import entries_from_grid
    import reconstruct_grid as rg
    from fetch_nation import linked_groups
    from fetch_puzzle import has_words
    from file_penguin_puzzle import separators
    from groups import entry_id
    from normalise_linked_enumerations import normalise_record, resolve_groups
    import enumeration
    rows = correct_counts(num, rows, fixes)
    across, down, _notes, damage = light_spec.build_spec(rows)
    if damage:
        return None, "clue list damaged: " + "; ".join(damage)
    for lg in across + down:
        if lg[2].startswith("linked"):
            lg[1] = None
    groups = pin_word_lengths(linked_groups(rows, across, down), across, down)
    given = {}
    for _ts, arows in answers or []:
        given = {(k, d): w for k, d, w in arows if "/" not in k}
        if any(given.get((str(lg[0]), d)) for d, lights in (("across", across), ("down", down))
               for lg in lights):
            break
        given = {}
    from clue_repair import fill_missing_sizes
    fill_missing_sizes(across, down, given)
    spec = [(lg[0], d, lg[1]) for d, lights in (("across", across), ("down", down)) for lg in lights]
    words = [given.get((str(n), d)) if n and size and len(given.get((str(n), d)) or "") == size
             else None for n, d, size in spec]
    if not any(words):
        words = None
    # Every Cyclops is 15x15; the linked lights' free lengths need more search
    # than the Nation's budget.
    misfits = grid_misfits(image, spec, groups) if image else None
    if misfits:
        fixed, cells = repair_grid(image, spec, groups)
        if fixed:
            print(f"  cyclops-{num}: the scan's grid misread cell(s) {list(cells)} "
                  f"(row, col): flipped, it prints the clue list exactly ({', '.join(misfits)})")
            image, misfits = fixed, []
    if image and not misfits:
        grid = list(image)
    else:
        grid, why = rg.unique_grid(spec, cols=15, rows=15, max_nodes=MAX_NODES, groups=groups,
                                   words=words, min_light=3, no_square=True)
        if grid is None:
            seen = f"; the scan's grid: {', '.join(misfits[:4])}" if misfits else ""
            return None, f"grid did not rebuild: {why}{seen}{count_hint(num, misfits)}"
    entries, problems = entries_from_grid(grid, across, down)
    if problems:
        return None, "; ".join(problems)
    for e in entries:
        e["clue"] = (e["clue"] or "").strip()
    # A tail the head names the direction of ("23/4dn", where 4 across has
    # its own clue and 23 down too) points at the head by number alone,
    # "See 23": named for the grouping, "See 23 across", then put back.
    printed = named_tails(rows, entries)
    normalise_record({"puzzle": {"entries": entries}, "fill": {}})
    grouped = resolve_groups(entries)
    for e in entries:
        e["clue"] = printed.get(entry_id(e), e["clue"])
    by_id = {entry_id(e): e for e in entries}
    seps = {}
    for e in entries:
        if not e.get("enumeration"):
            continue
        ids = grouped.get(entry_id(e), [entry_id(e)])
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
        if grouped.get(entry_id(e), [None])[0] == entry_id(e):
            e["group"] = list(grouped[entry_id(e)])
        e["solution"] = None
        out.append(e)
    return {"id": f"cyclops-{num}", "number": num, "series": "cyclops",
            "name": f"Private Eye Cyclops crossword No {num}", "setter": "Cyclops",
            "date": None, "dimensions": {"cols": len(grid[0]), "rows": len(grid)},
            "entries": out, **({"gridFromScan": True} if image and not misfits else {})}, None


def file(numbers=None, dry_run=False, daily=False):
    """File what the captures print. `daily` (the daily job): only numbers
    nothing has tried yet (not in refused.json), newest first, stopping at the
    unit's soft deadline (tools/budget.py) with the rest due next run; a
    parser fix is carried in by a by-hand run over refused.json's numbers."""
    from fetch_puzzle import puzzle_path, write_puzzle_file
    import budget
    import puzzle_paths
    got = index()
    filed, why = [], {}
    tried = set(json.loads(REFUSED.read_text())) if daily and REFUSED.exists() else set()
    todo = sorted(numbers or got, reverse=daily)
    for i, num in enumerate(todo):
        if daily and str(num) in tried:
            continue
        if daily and budget.spent(300):
            print(f"  out of time: {len(todo) - i} numbers left for the next run")
            break
        if num not in got or (not numbers and puzzle_paths.find(f"cyclops-{num}")):
            continue
        try:
            puzzle, reason = build(num, got[num])
        # SystemExit too: the shared enumeration code exits on a linked count
        # that overruns its light ("the book counts (7,7,4) = 18 letters, the
        # light is 7 cells"), and one puzzle must never end the batch.
        except (Exception, SystemExit) as e:
            puzzle, reason = None, f"{type(e).__name__}: {e}"
        if puzzle is None:
            why[num] = reason
            print(f"  cyclops-{num}: refused: {reason}")
            continue
        if dry_run:
            print(json.dumps(puzzle)[:400])
        else:
            try:
                write_puzzle_file(puzzle_path("cyclops", num), puzzle, generator=TOOL)
            except Exception as e:
                why[num] = f"write refused: {type(e).__name__}: {e}"
                print(f"  cyclops-{num}: {why[num]}")
                continue
        filed.append(num)
    print(f"filed {len(filed)}: {filed}")
    if not dry_run:
        refused = json.loads(REFUSED.read_text()) if REFUSED.exists() else {}
        for n in filed:
            refused.pop(str(n), None)
        refused.update({str(n): r for n, r in why.items()})
        REFUSED.write_text(json.dumps(refused, indent=1, sort_keys=True) + "\n")
        save_summary(got)
    return filed, why


# ---------- coverage (tools/coverage.py) ----------

REFUSED = DIR / "refused.json"
# The numbers below the Eye's own .puz downloads (No 300) and the gaps after it,
# checked 2026-10-13 against every Wayback capture of xword.htm, noframe/ and
# frames/xword.htm, sections.php?section_link=crossword[&issue=N], download/*.puz
# and images/grid*.gif up to 2013, and against fifteensquared (Dec 2006 on).
LOST_CAUSES = {
    "no-capture": "the Wayback Machine holds no capture of the Eye's crossword page "
                  "or .puz while it was current, and no blog posted it: only a print "
                  "copy (or the Eye's paid archive) files it",
    "answers-only": "a capture holds only the solution printed in the next issue, "
                    "not the clues: only a print copy files it",
    "scan-not-read": "archive.org holds the issue's scan (private-eye-magazine-<issue>) "
                     "and its OCR text is not fetched or filed yet: "
                     "privateeye_wayback.py fetch-ia, then file",
    "scan-unparsed": "the issue's archive.org OCR text is fetched and read_capture finds "
                     "no whole clue list in it (2026-10-14, 133 of 276 scans: the early "
                     "issues' two clue columns run together, the first clues set above the "
                     "ACROSS heading, clues or headings lost in the grid's OCR junk): "
                     "the page through the shared OCR pipeline, with its layout, files it",
    "not-read": "a capture prints its clues and no filing run has tried it: "
                "privateeye_wayback.py file N",
    "refused": "a capture prints its clues and the filer refused it "
               "(privateeye_wayback/refused.json says why; for a scan, mostly a grid "
               "that does not rebuild from clues the OCR lost or merged: the page "
               "through the shared OCR pipeline files it)",
}
LOST_FIRST, LOST_LAST = 1, 459
# Numbers 1-459 unfiled on 2026-10-13 whose issue archive.org has no
# private-eye-magazine-<issue> item for (it has 846-1252 bar these, then 1258).
IA_ABSENT = {69, 108, 155, 187, 189, 195, 433, 459}


def summary_path():
    """What index() found, kept on the SSD (tools/media_manifest.py) so the
    daily coverage run (lost) neither lists DIR nor re-parses its captures:
    {"version", "numbers": {n: ["answers", "clues", "puz"] held}, "ia": [n],
    "refused": [n in refused.json]}."""
    import media_manifest
    return media_manifest.DIR / "privateeye-index.json"


def summary_version():
    import media_manifest
    return media_manifest.source_version("privateeye_wayback.py")


def save_summary(got=None):
    """Write summary_path() from index() (or `got`, its result) and the ia
    scans held. fetch, fetch-ia and file write it; lost reads it."""
    got = index() if got is None else got
    ia = sorted(int(p.name.split("_")[0]) - ISSUE_OFFSET for p in (DIR / "ia").glob("*_djvu.txt"))
    try:
        refused = sorted(json.loads(REFUSED.read_text()))
    except FileNotFoundError:
        refused = []
    s = {"version": summary_version(), "ia": ia, "refused": refused,
         "numbers": {str(n): sorted(k for k in ("answers", "clues", "puz") if h.get(k)) for n, h in got.items()}}
    p = summary_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(s, sort_keys=True))
    tmp.replace(p)
    return s


def summary():
    """summary_path()'s summary; written afresh (index() once) only when it is
    missing or this file changed since (a parser change reads every capture
    again once, not each run)."""
    try:
        s = json.loads(summary_path().read_text())
    except (OSError, ValueError):
        s = None
    if not s or s.get("version") != summary_version():
        s = _summary_indexed()
    return s


def _summary_indexed():
    """summary() taken off the disk: index() and the ia listing, saved."""
    return save_summary() if DIR.exists() else {"numbers": {}, "ia": [], "refused": []}


def lost():
    """{number: LOST_CAUSES key} for every Cyclops 1-459 this source could speak to.
    Filed numbers are the ledger's to skip. Off summary(): no listing of DIR."""
    s = summary()
    got = {int(n): dict.fromkeys(held, True) for n, held in s["numbers"].items()}
    ia, refused = set(s["ia"]), set(s.get("refused", ()))
    out = {}
    for n in range(LOST_FIRST, LOST_LAST + 1):
        h = got.get(n, {})
        if h.get("clues") or h.get("puz"):
            out[n] = "refused" if str(n) in refused else "not-read"
        elif n not in IA_ABSENT and n not in ia:
            out[n] = "scan-not-read"
        elif n in ia:
            out[n] = "scan-unparsed"
        elif h.get("answers"):
            out[n] = "answers-only"
        else:
            out[n] = "no-capture"
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["fetch", "fetch-ia", "index", "file", "read-scans"])
    ap.add_argument("numbers", nargs="*", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--daily", action="store_true", help="file: only numbers not yet tried, to the unit deadline")
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        fetch()
    elif args.cmd == "fetch-ia":
        fetch_ia(args.numbers)
    elif args.cmd == "read-scans":
        for n, reason in sorted(read_scans(args.numbers).items()):
            print(f"cyclops-{n}: not read: {reason}")
    elif args.cmd == "file":
        file(args.numbers, args.dry_run, args.daily)
    else:
        for n, h in sorted(index().items()):
            print(n, "clues" if h.get("clues") else "-", "answers" if h.get("answers") else "-",
                  "puz" if h.get("puz") else "-")


if __name__ == "__main__":
    main(sys.argv[1:])
