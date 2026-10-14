#!/usr/bin/env python3
"""Read a Cyclops crossword's clues off the page image of archive.org's Private Eye scan.

    python3 tools/privateeye_wayback.py read-scans 12 25 147

archive.org's own OCR text of an early issue (private-eye-magazine-<issue>
_djvu.txt) runs the crossword's clue columns into each other and into the
articles beside it, so tools/privateeye_wayback.py's read_capture finds no
whole clue list in it. This reads the page instead:

  - The crossword's leaf is the one whose hOCR text most often says
    "Cyclops", "crossword", "across" and "down" (LEAF_WORDS).
  - That leaf's image and its djvu words (with positions) are fetched one
    page at a time (BookReaderImages.php, BookReaderGetTextWrapper.php), to
    downloads.PRIVATE_EYE_WAYBACK/ia/pages/.
  - The clue columns are found from the djvu words' layout (columns): the
    lines that start with a clue number or end with a count, grouped by where
    they start, each column cut at the entry notice or the solution heading.
  - Each column is read by every ocr_clues.READERS reader (read_words, on the
    desktop when tools/ocr_remote.py can) and archive.org's words, and the
    readings voted on as the Listener's are (archive_org_listener.vote).
  - The voted clues are written as ia/<issue>_page.txt, "EYE CROSSWORD N
    ACROSS 1 clue (5) ... DOWN ...", which privateeye_wayback.index reads with
    read_capture like any capture: the filer rebuilds and checks the grid.

A clue the readings do not agree on is blank, and a list with a blank
clue is not written (the reason is returned): no puzzle is filed with a
clue missing.
"""
import gzip
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET

import downloads

DIR = downloads.PRIVATE_EYE_WAYBACK / "ia"
PAGES = DIR / "pages"
LEAF_WORDS = re.compile(r"cyclops|crossword|across|down", re.IGNORECASE)
#: A line that starts a clue ("7 TCP-like", "20/12 Paxman", "9ac. See") or
#: ends one with its count ("(6,4)", "(4-4)").
STARTS = re.compile(r"^\W{0,2}\d{1,2}(?:\s*/\s*\d{1,2}(?:\s*(?:ac|dn)\.?)?)*\W{0,2}\s+[A-Za-z(\"'‘“]")
COUNTED = re.compile(r"\(\s*\d{1,2}(?:\s*[,\-–]\s*\d{1,2})*\s*\)\W{0,2}$")
#: Where the clue columns stop: the prize and entry notice, the previous
#: puzzle's solution or winner, the next feature's heading.
END = re.compile(r"£\s?\d|\bprize\b|\bentries\b|solution\s+to|\bwinner\b|\bcrossword\b", re.IGNORECASE)
#: Clue starts within COLUMN_SLOP pixels of each other start one column;
#: a column holds MIN_STARTS clue starts and MIN_COUNTED counts at least.
COLUMN_SLOP = 45
MIN_STARTS, MIN_COUNTED = 3, 2
#: A gap between lines of one column taller than GAP_LINES lines ends it.
GAP_LINES = 3.5
#: A gap between two words of a line wider than SPLIT_GAP word heights
#: parts two columns.
SPLIT_GAP = 1.6


def item(issue):
    return f"private-eye-magazine-{issue}"


def find_leaf(issue, get):
    """The leaf of the issue's scan the crossword is on, or None."""
    base = f"https://archive.org/download/{item(issue)}/{issue}"
    index = json.loads(gzip.decompress(get(base + "_hocr_pageindex.json.gz")))
    text = gzip.decompress(get(base + "_hocr_searchtext.txt.gz")).decode("utf-8", "replace")
    best = None
    for leaf, (a, b, *_) in enumerate(index):
        page = text[a:b]
        if not re.search(r"cyclops|crossword", page, re.IGNORECASE):
            continue
        score = len(LEAF_WORDS.findall(page))
        if best is None or score > best[1]:
            best = (leaf, score)
    return best and best[0]


def fetch_page(issue, get):
    """(image path, words path) of the crossword's leaf, fetched once; None
    when no leaf names the crossword."""
    PAGES.mkdir(parents=True, exist_ok=True)
    held = sorted(PAGES.glob(f"{issue}_*.jpg"))
    if held:
        return held[0], held[0].with_suffix(".xml")
    leaf = find_leaf(issue, get)
    if leaf is None:
        return None
    meta = json.loads(get(f"https://archive.org/metadata/{item(issue)}"))
    host, name = f"https://{meta['server']}/BookReader/", str(issue)
    words = get(host + "BookReaderGetTextWrapper.php?" + urllib.parse.urlencode(
        {"path": f"{meta['dir']}/{name}_djvu.xml", "mode": "djvu_xml", "page": leaf}))
    image = get(host + "BookReaderImages.php?" + urllib.parse.urlencode(
        {"zip": f"{meta['dir']}/{name}_jp2.zip", "file": f"{name}_jp2/{name}_{leaf:04d}.jp2",
         "id": item(issue), "scale": 1, "rotate": 0}))
    if not image.startswith(b"\xff\xd8"):
        raise RuntimeError(f"issue {issue} leaf {leaf}: the image is not a JPEG ({image[:60]!r})")
    img_path = PAGES / f"{issue}_{leaf:04d}.jpg"
    img_path.with_suffix(".xml").write_bytes(words)
    img_path.write_bytes(image)
    return img_path, img_path.with_suffix(".xml")


def page_lines(xml):
    """[[(x0, y0, x1, y1, text)] per printed line] of one page's djvu xml,
    a line cut where a gap wider than SPLIT_GAP of its height parts its
    words: archive.org's OCR runs a row of two columns into one line."""
    start = xml.find(b"<OBJECT")
    if start < 0:
        return []
    el = ET.fromstring(xml[start:xml.rindex(b"</OBJECT>") + len(b"</OBJECT>")])
    out = []
    for line in el.iter("LINE"):
        ws = []
        for w in line.iter("WORD"):
            x0, y1, x1, y0 = (int(v) for v in w.get("coords").split(",")[:4])
            if (w.text or "").strip():
                ws.append((x0, y0, x1, y1, w.text.strip()))
        piece = []
        for w in ws:
            h = max(1, w[3] - w[1])
            if piece and w[0] - piece[-1][2] > SPLIT_GAP * h:
                out.append(piece)
                piece = []
            piece.append(w)
        if piece:
            out.append(piece)
    return out


def boxed(ws):
    return (min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws),
            max(w[3] for w in ws), " ".join(w[4] for w in ws))


def number_of(lines, issue):
    """The crossword's printed number ("EYE CROSSWORD 13 by Cyclops"): a
    number just after "crossword" within 2 of the one the issue implies
    (the entry address, "Crossword", Private Eye, 6 Carlisle Street, is
    not it), else None."""
    import privateeye_wayback
    want = issue - privateeye_wayback.ISSUE_OFFSET
    words = [w for ws in lines for w in ws]
    for k, w in enumerate(words):
        if re.fullmatch(r"\W*crossword\W*", w[4], re.IGNORECASE) and not (
                k and re.fullmatch(r"to", words[k - 1][4], re.IGNORECASE)):
            for nxt in words[k + 1:k + 4]:
                if re.fullmatch(r"\d{1,3}", nxt[4]) and abs(int(nxt[4]) - want) <= 2:
                    return int(nxt[4])
    # The heading lost: the solution printed below is the puzzle before's.
    for ws in lines:
        m = SOLVED.search(" ".join(w[4] for w in ws))
        if m and abs(int(m.group(1)) + 1 - want) <= 2:
            return int(m.group(1)) + 1
    return None


SOLVED = re.compile(r"solution\s+to\s+crossword\s+(?:no\.?\s*)?(\d{1,3})", re.IGNORECASE)


def columns(lines):
    """[(x0, y0, x1, y1)] of the clue columns in reading order (left to
    right), from the page's djvu lines: clue starts grouped by their left
    edge, each column running from its first clue line (or ACROSS/DOWN
    heading) down while lines follow within GAP_LINES lines, to an END line."""
    import file_archive_org_puzzles as fa
    rows = [boxed(ws) for ws in lines]
    starts = sorted((r for r in rows if STARTS.match(r[4])), key=lambda r: r[0])
    groups = []
    for r in starts:
        if groups and r[0] - groups[-1][-1][0] <= COLUMN_SLOP:
            groups[-1].append(r)
        else:
            groups.append([r])
    groups = [g for g in groups if len(g) >= MIN_STARTS]
    out = []
    lefts = [min(r[0] for r in g) for g in groups]
    for k, g in enumerate(groups):
        x0 = lefts[k]
        right = lefts[k + 1] - 8 if k + 1 < len(groups) else 10 ** 6
        mine = [r for r in rows if x0 - 15 <= r[0] <= x0 + 3 * COLUMN_SLOP and r[2] <= right + 15]
        mine.sort(key=lambda r: r[1])
        height = sorted(r[3] - r[1] for r in mine)[len(mine) // 2] if mine else 30
        best = []
        run = []
        for r in mine:
            heading = fa.heading_of(r[4])
            clueish = heading or STARTS.match(r[4]) or COUNTED.search(r[4])
            # A clue's own words ("20 This crossword is Cyclops's first") end nothing.
            ends = bool(END.search(r[4])) and not heading and not STARTS.match(r[4])
            if run and (r[1] - run[-1][3] > GAP_LINES * height or ends):
                best = max(best, run, key=score)
                run = []
            if ends:
                continue
            if run or clueish:
                run.append(r)
        best = max(best, run, key=score)
        if (sum(1 for r in best if STARTS.match(r[4])) >= MIN_STARTS
                and sum(1 for r in best if COUNTED.search(r[4])) >= MIN_COUNTED):
            out.append((x0 - 8, best[0][1] - 6, max(r[2] for r in best) + 8, best[-1][3] + 8))
    return out


def score(run):
    return sum(1 for r in run if COUNTED.search(r[4]))


SLASH = re.compile(r"^(\W{0,2}\d{1,2})\s*/\s*(?=\d)")


def column_cols(boxes):
    """archive_org_listener.vote's `cols`: each reading's words put in the
    column (of `boxes`) their middle falls in, merged into printed rows,
    the columns read in turn and cut at the ACROSS and DOWN headings. A
    linked head's "20/12" is written "20, 12", as the shared parser reads it."""
    import file_archive_org_puzzles as fa

    def cols(words):
        lines = []
        for b in boxes:
            col = [(w[1], w[3], w[0], w[2], w[4]) for w in words
                   if b[0] <= (w[0] + w[2]) / 2 <= b[2] and b[1] <= (w[1] + w[3]) / 2 <= b[3]]
            lines += fa.merge_rows(col)
        side, out = None, [[], []]
        for ln in lines:
            text = ln[4]
            while SLASH.match(text):
                text = SLASH.sub(r"\1, ", text, count=1)
            head = fa.heading_of(text.strip())
            if head:
                side = 0 if head == "ACROSS" else 1
                continue
            if side is None and re.match(r"\W{0,2}1\b", text):
                side = 0  # the ACROSS heading lost, the list starts at 1
            if side is not None:
                out[side].append(ln[:4] + (text,))
        return out
    return cols


def read(issue, get):
    """(number or None, page text or None, why not) for one issue's scan."""
    import ocr_clues
    from PIL import Image
    got = fetch_page(issue, get)
    if got is None:
        return None, None, "no leaf of the scan names the crossword"
    img_path, xml_path = got
    lines = page_lines(xml_path.read_bytes())
    number = number_of(lines, issue)
    if number is None:
        return None, None, "no crossword number near the issue's own on the page"
    boxes = columns(lines)
    if not boxes:
        return number, None, "no clue columns found in the page's layout"
    img = Image.open(img_path)
    words = {"djvu": [w for ws in lines for w in ws]}
    for which in ocr_clues.READERS:
        words[which] = []
        for b in boxes:
            words[which] += column_words(img, b, which, f"{img_path.stem}_{'-'.join(map(str, b))}")
    verdict, laid = voted(words, column_cols(boxes))
    if laid is None:
        return number, None, f"the readings do not parse: {verdict.get('refused')}"
    blank = verdict.get("blank") or {}
    if blank:
        return number, None, f"{len(blank)} clues the readings do not agree on: " + \
            "; ".join(f"{k}: {v}" for k, v in sorted(blank.items())[:4])
    return number, page_text(number, laid), None


def voted(words, cols):
    """(verdict, laid) of archive_org_listener.vote over every reading, or,
    when that leaves a clue blank, over every reading but one, whichever
    leaves the fewest blank: the fullest reading lays each clue, and one
    reading's misread count ("(©)" for "(6)") then blanks a clue the
    others all read."""
    import archive_org_listener as listener

    def one(ws):
        verdict, laid = listener.vote(ws, {}, cols=cols)
        if laid is not None:
            laid, verdict = see_filled(laid, verdict, ws, cols)
        return verdict, laid

    def blanks(got):
        return len(got[0].get("blank") or ()) if got[1] is not None else 10 ** 6
    best = one(words)
    for left in (list(words) if blanks(best) and len(words) > 3 else ()):
        got = one({k: w for k, w in words.items() if k != left})
        if blanks(got) < blanks(best):
            best = got
            best[0]["without"] = left
    return best


def column_words(img, box, which, key):
    """[(x0, y0, x1, y1, text)] reader `which` reads in `box`, in page
    pixels (ocr_clues.read_words), cached per crop box and reader."""
    import file_archive_org_puzzles as fa
    import ocr_clues
    path = fa.CROPS / "rapid" / f"privateeye_{key}.{ocr_clues.reader_key(which)}.json"
    if path.exists():
        return [tuple(w) for w in json.loads(path.read_text())]
    got = [(x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1], t)
           for x0, y0, x1, y1, t in ocr_clues.read_words(img.crop(box), which)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(got))
    return got


SEE = re.compile(r"^\W{0,2}(\d{1,2})\W{0,2}\s+\(?\s*see\s+(\d{1,2})\s*(across|down|ac|dn)?\b", re.IGNORECASE)


def see_filled(laid, verdict, words, cols):
    """A blank light two readings print as a cross-reference ("12 (See 20
    down)", which carries no count for the vote to lay it by) is that
    reference: "See 20"."""
    blank = dict(verdict.get("blank") or {})
    if not blank:
        return laid, verdict
    seen = {}
    for reading in words.values():
        for side, lines in zip(("across", "down"), cols(reading)):
            for ln in lines:
                m = SEE.match(ln[4])
                if m:
                    seen.setdefault(f"{int(m.group(1))}-{side}", []).append(m.group(2))
    laid = dict(laid)
    for lid in list(blank):
        refs = seen.get(lid, [])
        top = max(set(refs), key=refs.count) if refs else None
        if top and refs.count(top) >= 2:
            laid[lid] = (f"See {top}", None, None)
            blank.pop(lid)
    verdict = {k: v for k, v in verdict.items() if k != "blank"}
    if blank:
        verdict["blank"] = blank
    return laid, verdict


def page_text(number, laid):
    """The voted clues as a capture's text: "EYE CROSSWORD N ACROSS 7 clue
    (6,4) ... DOWN ...", a linked head "20/12", a continuation "12 See 20"."""
    parts = [f"EYE CROSSWORD {number}"]
    for side in ("across", "down"):
        parts.append(side.upper())
        lids = sorted((lid for lid in laid if lid.endswith("-" + side)), key=lambda l: int(l.split("-")[0]))
        for lid in lids:
            text, enum, group = laid[lid]
            head = "/".join(g.split("-")[0] for g in group) if group else lid.split("-")[0]
            if re.match(r"See \d", text or ""):
                parts.append(f"{head} {text}")
            else:
                parts.append(f"{head} {text} ({enum})" if enum else f"{head} {text}")
    return " ".join(parts)
