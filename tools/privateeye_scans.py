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

import clue_text
import downloads

DIR = downloads.PRIVATE_EYE_WAYBACK / "ia"
PAGES = DIR / "pages"
LEAF_WORDS = re.compile(r"cyclops|crossword|across|down", re.IGNORECASE)
#: A line that starts a clue ("7 TCP-like", "20/12 Paxman", "9ac. See") or
#: ends one with its count ("(6,4)", "(4-4)").
STARTS = re.compile(r"^\W{0,2}\d{1,2}(?:\s*[/+]\s*\d{1,2}(?:\s*(?:ac|dn)\.?)?)*\W{0,2}\s+[A-Za-z(.…\"'‘“]")
COUNTED = clue_text.PRINTED_COUNT
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
            # Rules read as "|" between the heading and its number skipped
            # (issue 1125: "CROSSWORD | | |_ 280"); "Crossword 279 winner"
            # names the puzzle before.
            after = [w for w in words[k + 1:k + 12] if re.search(r"[^\W_]", w[4])][:4]
            for i, nxt in enumerate(after[:3]):
                if re.fullmatch(r"\d{1,3}", nxt[4]) and abs(int(nxt[4]) - want) <= 2 and not (
                        i + 1 < len(after) and re.match(r"winner", after[i + 1][4], re.IGNORECASE)):
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
            heading = clue_text.heading_of(r[4])
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
            # A line the djvu layer breaks mid-row ("— it's crap ... Paisley (8)"
            # after "11 The sex act") starts inside the column and runs past
            # its clue lines' right edge: the box takes it in, or the words
            # past the edge are lost (No 43's clue 11 and 12/14).
            top, bottom = best[0][1], best[-1][3]
            reach = max([r[2] for r in best] + [r[2] for r in rows
                        if x0 <= r[0] <= right and r[2] <= right + 15 and top <= r[1] and r[3] <= bottom])
            out.append((x0 - 8, top - 6, reach + 8, bottom + 8))
    return out


def score(run):
    return sum(1 for r in run if COUNTED.search(r[4]))


#: A linked head's slash, after its first number ("20/12") or after a
#: comma ("7, 17/23", three lights): the shared parser reads commas, and
#: a slash left in "17/23 Truss" puts the numbers in the clue's words,
#: which then are no clue and the light is filed blank (Nos 4, 29, 150).
#: A "+" joins them as a slash does ("14+16 Cops ...", No 152): left in,
#: the line is no clue start and its words ran into the clue above.
SLASH = re.compile(r"^(\W{0,2}\d{1,2}(?:\s*,\s*\d{1,2})*)\s*[/+]\s*(?=\d)")


#: A linked head's tail marked with its own direction, "6, 15a Hurley's"
#: (No 49's "6/15a": 6 and 15 across, the answer's 7,5,8 over both).
TAIL_MARKED = re.compile(r"^(\W{0,2}\d{1,2}(?:\s*,\s*\d{1,2})*\s*,\s*\d{1,2})(a|d)(?:c|n)?\b\.?(?=\s)")


def same_side_tail(text, side):
    """`text` with a tail's direction mark dropped when it names the side the
    clue is printed in (an "a" in the across list): the head links two lights
    of its own list, and the mark only keeps the shared parser from reading
    "15a" as no number. A mark naming the other side is left to DIRECTED."""
    m = TAIL_MARKED.match(text)
    if m and m.group(2).lower() == ("a", "d")[side]:
        return m.group(1) + text[m.end():]
    return text


def column_cols(boxes):
    """archive_org_listener.vote's `cols`: each reading's words put in the
    column (of `boxes`) their middle falls in, merged into printed rows,
    the columns read in turn and cut at the ACROSS and DOWN headings. A
    linked head's "20/12" is written "20, 12" and "7, 17/23" "7, 17, 23",
    as the shared parser reads them."""
    import file_archive_org_puzzles as fa
    named = {}

    def cols(words):
        lines = []
        for b in boxes:
            col = [(w[1], w[3], w[0], w[2], w[4]) for w in words
                   if b[0] <= (w[0] + w[2]) / 2 <= b[2] and b[1] <= (w[1] + w[3]) / 2 <= b[3]]
            lines += fa.merge_rows(col)
        side, out = None, [[], []]
        for ln in lines:
            text = clue_text.tidy_ocr_clues(ln[4], scope="line")
            while SLASH.match(text):
                text = SLASH.sub(r"\1, ", text, count=1)
            if side is not None:
                text = same_side_tail(text, side)
            text = DIRECTED.sub(r"\1", text)
            head = clue_text.heading_in(text.strip(), running_head=side is None)
            if head:
                side = 0 if head == "ACROSS" else 1
                continue
            if side is None and re.match(r"\W{0,2}1\b", text):
                side = 0  # the ACROSS heading lost, the list starts at 1
            if side is not None:
                m = NAMED.match(text)
                if m:
                    mine = ("across", "down")[side]
                    tails = tuple((int(n), {"a": "across", "d": "down"}[d[0].lower()] if d else mine)
                                  for n, d in NAMED_TAIL.findall(m.group(2)))
                    lead = int(re.search(r"\d+", m.group(1)).group(0))
                    got = named.setdefault((mine, lead), {})
                    got[tails] = got.get(tails, 0) + 1
                    text = m.group(1) + text[m.end():]
                out[side].append(ln[:4] + (text,))
        return [closed_clues(relinked(side)) for side in out]
    cols.named = named
    return cols


#: A clue's number at the start of a printed line, and how far above the
#: clue before it a real next clue's number can be.
CLUE_NUMBER = re.compile(r"^\W{0,2}(\d{1,2})\W{0,2}\s+[A-Za-z(\"'\u2018\u201c]")
NEXT_CLUE_WITHIN = 12
SEE_CLUE = re.compile(r"^\W{0,2}\d{1,2}(?:\W{0,2}[,/]\s*\d{1,2}\W*)*\s+\(?\s*see\b", re.IGNORECASE)


def relinked(lines):
    """`lines` with a linked head's misread tail put right
    (clue_text.mend_link_tails: "11/14" for "11/4", No 80)."""
    mended = clue_text.tidy_ocr_clues([ln[4] for ln in lines], scope="lines")
    return [ln[:4] + (t,) for ln, t in zip(lines, mended)]


def closed_clues(lines):
    """`lines` (one side's printed lines) with each clue a reader left with
    no count closed by "(?)": the next clue's number, just above this one's,
    starts a line, and a count lost at the end of its last line (No 215's
    "18 State if Tone's broken promises to voters", the "(9)" unread by two
    readers) would otherwise run the next clue ("20 Enjoy sport ...") into
    it, and that clue is lost from the list. "(?)" is how the shared parser reads a
    count it could not read: the vote takes the count the other readings
    print. A "See 10" clue prints none and is left."""
    out = list(lines)
    starts = []  # (index, number) of each clue's first line
    for i, ln in enumerate(out):
        m = CLUE_NUMBER.match(ln[4])
        if not m:
            continue
        n = int(m.group(1))
        if starts and not starts[-1][1] < n <= starts[-1][1] + NEXT_CLUE_WITHIN:
            continue  # a wrapped line that happens to start with a number
        if starts:
            j = starts[-1][0]
            text = " ".join(l[4] for l in out[j:i])
            if not (clue_text.PRINTED_COUNT.search(text) or re.search(r"\(\s*\??\s*\)\W*$", text)
                    or SEE_CLUE.match(out[j][4])):
                out[i - 1] = out[i - 1][:4] + (out[i - 1][4].rstrip() + " (?)",)
        starts.append((i, n))
    return out


#: A link head naming a tail's direction, "4, 16ac./22dn." (No 294) or
#: "23, 4dn." (No 112): the shared parser reads no direction, and the vote
#: lost the clue's words to it. column_cols leaves the head's own number
#: for the vote and keeps the tails, in printed order, for named_links.
NAMED = re.compile(r"^(\W{0,2}\d{1,2})((?:\s*[,/]\s*\d{1,2}\s*(?:(?:across|down|ac|dn)\b\.?)?)*?"
                   r"\s*[,/]\s*\d{1,2}\s*(?:across|down|ac|dn)\b\.?"
                   r"(?:\s*[,/]\s*\d{1,2}\s*(?:(?:across|down|ac|dn)\b\.?)?)*)(?=\s)", re.IGNORECASE)
NAMED_TAIL = re.compile(r"(\d{1,2})\s*(across|down|ac|dn)?\b", re.IGNORECASE)


def named_links(laid, named):
    """`laid` with each head column_cols found naming its tails' directions
    (cols.named, {(side, head): {tails: readings}}) given its group as
    printed, and each tail light "See <head>". A tail holding words of its
    own is no continuation: that head is left as the vote laid it."""
    out = dict(laid)
    for (side, head), seen in named.items():
        lid = f"{head}-{side}"
        text, enum, _ = out.get(lid) or ("", None, None)
        if not (text or "").strip():
            continue
        tails = [f"{n}-{d}" for n, d in max(seen, key=seen.get)]
        if any((out.get(t) or ("",))[0].strip() and not SEE_SIDE.fullmatch(out[t][0].strip())
               for t in tails):
            continue
        out[lid] = (text, enum, [lid] + tails)
        for t in tails:
            out[t] = (f"See {head}", None, None)
    return out


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
    cols = column_cols(boxes)
    verdict, laid = voted(words, cols)
    if laid is None:
        return number, None, f"the readings do not parse: {verdict.get('refused')}"
    blank = verdict.get("blank") or {}
    deferred = ""
    if blank:
        laid, blank, deferred = vlm_filled(img, boxes, words, cols, laid, blank)
    if blank:
        return number, None, f"{len(blank)} clues the readings do not agree on{deferred}: " + \
            "; ".join(f"{k}: {v}" for k, v in sorted(blank.items())[:4])
    laid = linked_across(directed_links(named_links(laid, cols.named)))
    empty =sorted(lid for lid, (t, _, _) in laid.items() if not (t or "").strip())
    if empty:
        return number, None, f"clues with no words: {', '.join(empty)}"
    return number, page_text(number, laid), None


def linked_across(laid):
    """`laid` with a link that crosses directions put right. The Eye prints
    "14/22" for 14 across and 22 down, and the vote lays both on the head's
    direction, writing "See 14" on 22 across. When the other direction's 22
    prints the reference ("See 14", or a bare "(14)", the reference's
    number read as its count), that light is the continuation and the
    one the vote made goes."""
    out = dict(laid)
    for lid, (_, _, group) in laid.items():
        head = lid.split("-")[0]
        see = "See " + head
        for tail in (group or [])[1:]:
            n, side = tail.split("-")
            other = n + "-" + ("down" if side == "across" else "across")
            text, enum, _ = out.get(other, ("", None, None))
            text = (text or "").strip()
            # "25 (see 5dn)": the reference names the head's direction, which
            # is the head's own side here (No 266's 5/25 down, 25 across).
            ref = SEE_SIDE.fullmatch(text)
            if ref and str(clue_text.see_number(ref.group(1))) == head and ref.group(2) and \
                    ("across" if ref.group(2).lower().startswith("a") else "down") == lid.split("-")[1]:
                text = see
            # "(see 16)" read "see (6)": the reference lost its first digit and
            # became the count, a suffix of the head's number.
            lost = text.lower() == "see" and bool(enum) and head.endswith(str(enum)) and str(enum) != head
            if other in out and (text == see or (not text and enum == head) or lost):
                out[other] = (see, None, None)
                if (out.get(tail) or ("",))[0] == see:
                    del out[tail]
    return out


LEAD = re.compile(r"^(\W{0,2})(\d{1,3})(?=\W{0,2}\s)")


def renumbered(words, cols):
    """`cols` with each reading's clue number that no other reading prints
    put right before the vote, when it is one digit too many (No 279's "61"
    for 6 down): dropping a digit gives a number most other readings print (two at least)
    and this one lacks, between this reading's neighbours. Anything less
    sure is left for the vote."""
    per = {id(w): cols(w) for w in words.values()}
    if len(per) < 3:
        return cols

    def nums(lines):
        return [int(m.group(2)) for ln in lines if (m := LEAD.match(ln[4]))]

    def fixed(ws):
        out = cols(ws)
        mine = id(ws)
        if mine not in per:
            return out
        for side in (0, 1):
            others = [set(nums(p[side])) for k, p in per.items() if k != mine]
            seq = nums(out[side])
            for i, ln in enumerate(out[side]):
                m = LEAD.match(ln[4])
                if not m or any(int(m.group(2)) in o for o in others):
                    continue
                n = m.group(2)
                pos = seq.index(int(n))
                prev, nxt = (seq[pos - 1] if pos else 0), (seq[pos + 1] if pos + 1 < len(seq) else 99)
                cands = {int(c) for c in (n[:-1], n[1:]) if c and c[0] != "0"}
                cands = [c for c in cands if 2 <= sum(c in o for o in others) > len(others) / 2 and c not in seq
                         and prev < c < nxt]
                if len(cands) == 1:
                    text = ln[4][:m.start(2)] + str(cands[0]) + ln[4][m.end(2):]
                    out[side][i] = ln[:4] + (text,)
                    seq[pos] = cands[0]
        return out
    return fixed


#: A link to the other direction's light set with its direction letter,
#: "1, 1D Fellow feeling ..." (No 281): the parser keeps "1D" in the words.
#: column_cols drops that tail ("1, 1D" read "1, 1" lays the tail on the
#: head itself); directed_links puts the link back from the tail's own
#: "See 1 Across" in the other list.
DIRECTED = re.compile(r"^(\W{0,2}\d{1,2}(?:\s*,\s*\d{1,2})*)\s*,\s*\d{1,2}(?:\s*[AD]|[ad])\b\.?(?=\s)")
SEE_SIDE = re.compile(r"\(?\s*" + clue_text.SEE_DIRECTED + r"\W*", re.IGNORECASE)


def directed_links(laid):
    """`laid` with a light whose clue is "See 1 Across", naming the other
    direction (No 281's 1 down, the head printed "1, 1D"), the tail of that
    head's link: the head's group gets it, as the Eye's "1/1", and the
    light reads "See 1". Only a head with words and no group of its own."""
    out = dict(laid)
    for lid, (text, _, _) in laid.items():
        m = SEE_SIDE.fullmatch((text or "").strip())
        n, side = lid.split("-")
        if not m:
            continue
        if m.group(2):
            named = "across" if m.group(2).lower().startswith("a") else "down"
        elif str(clue_text.see_number(m.group(1))) == n:  # "1 See 1": a light never refers to itself
            named = "down" if side == "across" else "across"
        else:
            continue
        head = f"{m.group(1)}-{named}"
        htext, henum, hgroup = out.get(head) or ("", None, None)
        if named == side or hgroup or not (htext or "").strip() or not henum:
            continue
        out[head] = (htext, henum, [head, f"{n}-{named}"])
        out[lid] = ("See " + m.group(1), None, None)
    return out


def vlm_filled(img, boxes, words, cols, laid, blank, vlm=None):
    """(laid, blank, note): each blank clue read by the desktop VLM through
    ocr_clues.vlm_pick, as the other scan filers do (shown the clue columns
    and every reader's text for the clue). With the VLM down the clues stay
    blank and `note` says the page is deferred: it is read again when the
    VLM answers, never filed on a worse reading."""
    import archive_org_listener as listener
    import file_archive_org_puzzles as fa
    import ocr_clues
    if vlm is None:
        import vlm_reader as vlm
    try:
        if not vlm.wanted():
            return laid, blank, (" (deferred: the VLM is down)" if vlm.URL else "")
        texts = {k: fa.tidy(listener.text_of(cols(w))) for k, w in words.items()}
        crop = vlm.crop(img, (min(b[0] for b in boxes), min(b[1] for b in boxes),
                              max(b[2] for b in boxes), max(b[3] for b in boxes)))
        laid, left = ocr_clues.vlm_pick(texts, laid, blank, listener.parse,
                                        lambda lid, cands: vlm.pick_in(crop, lid, cands))
    except vlm.Down:
        return laid, blank, " (deferred: the VLM is down)"
    except RuntimeError:
        return laid, blank, " (deferred: the VLM went away)"
    return laid, left, ""


def voted(words, cols):
    """(verdict, laid) of archive_org_listener.vote over every reading, or,
    when that leaves a clue blank, over every reading but one, whichever
    leaves the fewest blank: the fullest reading lays each clue, and one
    reading's misread count ("(©)" for "(6)") then blanks a clue the
    others all read."""
    import archive_org_listener as listener
    cols = renumbered(words, cols)

    def one(ws):
        verdict, laid = listener.vote(ws, {}, cols=cols)
        if laid is not None:
            # The vote can lay a light with no words and name no blank (a
            # clue wrapped past the column's edge, one reading's cut copy
            # outvoting the whole one): left so it won the fewest-blank
            # choice and then refused "clues with no words". It is blank.
            bare = {lid: "no words laid" for lid, (t, _, _) in laid.items()
                    if not (t or "").strip() and lid not in (verdict.get("blank") or {})}
            if bare:
                verdict = dict(verdict, blank=dict(verdict.get("blank") or {}, **bare))
            # A light the page prints as a reference, "24 (see 8)", has no
            # words and is blank to the vote: it is that reference.
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


SEE = re.compile(r"^\W{0,2}(\d{1,2})\W{0,2}\s+\(?\s*" + clue_text.SEE_DIRECTED, re.IGNORECASE)


def see_filled(laid, verdict, words, cols):
    """A blank light two readings print as a cross-reference ("12 (See 20
    down)", which carries no count for the vote to lay it by) is that
    reference: "See 20". A reference number every reader misread as a letter
    ("26 (see lac)", No 103) is read as the one it is, 1."""
    blank = dict(verdict.get("blank") or {})
    if not blank:
        return laid, verdict
    seen = {}
    for reading in words.values():
        for side, lines in zip(("across", "down"), cols(reading)):
            for ln in lines:
                m = SEE.match(clue_text.tidy_ocr_clues(ln[4], scope="piece"))
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


def side_mark(lid):
    return "ac" if lid.endswith("-across") else "dn"


def page_text(number, laid):
    """The voted clues as a capture's text: "EYE CROSSWORD N ACROSS 7 clue
    (6,4) ... DOWN ...", a linked head "20/12", a continuation "12 See 20"."""
    parts = [f"EYE CROSSWORD {number}"]
    for side in ("across", "down"):
        parts.append(side.upper())
        lids = sorted((lid for lid in laid if lid.endswith("-" + side)), key=lambda l: int(l.split("-")[0]))
        for lid in lids:
            text, enum, group = laid[lid]
            # A light of the other direction is named so: "23/4dn".
            head = "/".join(g.split("-")[0] + ("" if g.endswith("-" + side) else side_mark(g))
                            for g in group) if group else lid.split("-")[0]
            if re.match(r"See \d", text or ""):
                parts.append(f"{head} {text}")
            else:
                parts.append(f"{head} {text} ({enum})" if enum else f"{head} {text}")
    return " ".join(parts)
