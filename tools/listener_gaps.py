"""A Gale Listener clue the vote left blank, read again from where it must be.

A joined puzzle that lacks only a few clue texts has, for each, a numbered
line in one of the page's OCR readings (the vote dropped it, the readers not
agreeing on it). That line and the lines run on under it, up to the next
numbered line, are the region the clue is printed in: the lines between the
neighbouring clues'. The VLM transcribes a crop of that region (vlm_reader.read)
and the clue is taken only when a page fact other than the transcription
checks it:

- the list prints counts: the transcription's own printed count equals the
  light's length, and its number is the light's;
- the list prints none (the 1930s magazine's): the transcription agrees with
  the OCR reader's text of those lines, AGREE of their letters (two readers).

A clue whose own line the OCR never read has no region to cut that way (44%
of the missing lines of a sample of refused pages have no "N." line in any
reading). The page's lists are still known: each list's lines bound its clue
columns, and one VLM ask a column crop (fill_columns: a few a page, not one a
clue) transcribes the whole column. The rule, whatever the number of gaps and
with no OCR line: the clue's number is an unclued light's of the list's
direction, its printed count equals that light's length in the joined grid,
it is the only clue of that number in the transcription (its numbers ascend), and its text is no
copy of a clue already read.

Only Gale Listener pages come here (file_gale_listener.run), never
archive_org_listener's TLS or Mephisto.
"""
import difflib
import re

import archive_org_listener as al
import gale_listener as gl
import ocr_clues

#: A joined puzzle lacking more clue texts than this has a list misread whole,
#: not a line lost: no ask is made.
MAX_GAPS = 3
#: Whether the column read (fill_columns) runs first, for any number of gaps.
COLUMNS = True
#: The share of letters a transcription and an OCR reading of the same lines
#: must agree on where no count checks the clue. Measured over the 1,763
#: uncounted clues of the refused pages whose `page` reading and voted text
#: both exist (the reading of one reader against the vote of three: median
#: and 75th percentile 1.0, 10th percentile 0.75, the low tail line joins and
#: heading lines): 0.9 is a letter in ten, the readings of a clue both right.
AGREE = 0.9
#: A count printed after a clue: "(5)", "(3,4)", "(4-4)".
#: The words a setter prints with it are no part of it: "(11, two words)", "(7, hyphen)", "(Two words. 7)".
COUNT = re.compile(r"\s*\((?:[A-Za-z]+(?: [A-Za-z]+)?[.,:]\s*)?(\d{1,2}(?:\s*[,\-]\s*\d{1,2})*)(?:,\s*[A-Za-z]+(?: [A-Za-z]+)?)?\)\W{0,2}$")


def letters(t):
    return re.sub(r"[^a-z]", "", t.lower())


def lines_of(words, lid):
    """(reader, [line]) of the first reading whose lists number `lid`: its
    numbered line and the lines run on under it up to the next numbered
    one, each (y0, y1, x0, x1, text)."""
    n, way = lid.split("-")
    for which in ["page", *ocr_clues.READERS]:
        cols = gl.page_columns(words.get(which) or [])
        lines = cols[way == "down"] if cols else []
        at = next((i for i, ln in enumerate(lines) if (m := al.LINE_CLUE.match(ln[4])) and m.group(1) == n), None)
        if at is None:
            continue
        end = next((j for j in range(at + 1, len(lines)) if al.LINE_CLUE.match(lines[j][4])), len(lines))
        return which, lines[at:end]
    return None, []


def columns_of(lines):
    """`lines` cut where the list runs into another column: a line that is
    not below the last (its top above that line's) or that starts left or
    right of it by more than its own height."""
    out = []
    for ln in lines:
        if out and ln[0] >= out[-1][-1][0] and abs(ln[2] - out[-1][-1][2]) <= ln[1] - ln[0]:
            out[-1].append(ln)
        else:
            out.append([ln])
    return out


def boxes_of(img, lines):
    """One padded crop box a column of the region's lines."""
    out = []
    for col in columns_of(lines):
        h = max(ln[1] - ln[0] for ln in col)
        out.append((max(0, min(ln[2] for ln in col) - h), max(0, min(ln[0] for ln in col) - h // 4),
                    min(img.width, max(ln[3] for ln in col) + h), min(img.height, max(ln[1] for ln in col) + h // 4)))
    return out


def parsed(reply, n):
    """(text, count or None) of the clue numbered `n` in the transcription
    `reply`, or None: its first line must open on the number; it runs to the
    next numbered line; a trailing count is split off."""
    text = " ".join(reply.split())
    m = al.LINE_CLUE.match(text)
    if not m or m.group(1) != n:
        return None
    body = m.group(2)
    nxt = re.search(r"\s(?=\d{1,2}[.,]\s+[A-Z\"'‘])", body)
    if nxt:
        body = body[:nxt.start()]
    c = COUNT.search(body)
    count = None
    if c:
        count = sum(int(x) for x in re.split(r"\s*[,\-]\s*", c.group(1)))
        body = body[:c.start()].rstrip()
    return (body, count, c.group(1) if c else None) if body else None


def counted(laid):
    """Whether the page's list prints counts: over half the clues read have one."""
    have = [v[1] for v in laid.values() if v[0]]
    return sum(1 for e in have if e) * 2 > len(have)


#: A list heading in a transcription: "ACROSS", "CLUES ACROSS", "DOWN".
HEADING = re.compile(r"^\W*(?:clues\W*)?(across|down)\b", re.IGNORECASE)
#: Pad above and below a column crop, in line heights: the list's first or
#: last clue may be a line the readings lost (the crop may take in the
#: heading above it, which sections() cuts away again).
PAD_LINES = 2
#: A clue text sharing this much of its letters with another clue's is a copy.
CLASH = 0.9


def merged(boxes):
    """`boxes` with those that share a column (widths overlapping over half
    the narrower's) taken as one: a column's lines cut by columns_of at an
    indent are one ask, not two."""
    out = []
    for b in sorted(boxes):
        for i, o in enumerate(out):
            if min(o[2], b[2]) - max(o[0], b[0]) > min(o[2] - o[0], b[2] - b[0]) / 2:
                out[i] = (min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3]))
                break
        else:
            out.append(b)
    return out


def column_boxes(img, lines):
    """The padded crop boxes of a list's `lines`, one a column."""
    out = []
    for col in columns_of(lines):
        h = max(ln[1] - ln[0] for ln in col)
        out.append((max(0, min(ln[2] for ln in col) - h), max(0, min(ln[0] for ln in col) - PAD_LINES * h),
                    min(img.width, max(ln[3] for ln in col) + h),
                    min(img.height, max(ln[1] for ln in col) + PAD_LINES * h)))
    return merged(out)


def sections(reply, way):
    """The lines of transcription `reply` that belong to list `way`: those
    under its heading up to the other's, those above a first heading that is
    the other's, or all of them when it prints no heading."""
    lines = [ln.strip() for ln in reply.splitlines() if ln.strip()]
    heads = [(i, m.group(1).lower()) for i, ln in enumerate(lines) if len(ln) <= 24 and (m := HEADING.match(ln))]
    if not heads:
        return lines
    out = lines[:heads[0][0]] if heads[0][1] != way else []
    for k, (i, w) in enumerate(heads):
        if w == way:
            out += lines[i + 1:heads[k + 1][0] if k + 1 < len(heads) else len(lines)]
    return out


#: Where a transcribed line holds another clue: after a closing count's bracket, its full stop, then
#: the next number, a full stop and a capital or quote.
INLINE_CLUE = re.compile(r"(?<=\))\.?\s+(?=\d{1,2}\.\s+[A-Z\"'‘“])")


def clues_in(lines):
    """{number: parsed()'s (text, count, printed count)} of the clues the
    transcribed `lines` number. A clue runs on over the lines up to the next
    numbered one; the numbers ascend, so each is the only clue of its number,
    and the first numbered line that does not (the other list's, a number
    read twice, a stray figure) ends the column."""
    out, last, rows = {}, 0, []
    # The model runs a column's lines on as it reads: "... Light Infantry from a knock-out (8). 10.
    # Sobriquet ..." has the clue 10 inside a line. A clue that ends on its printed count and is
    # followed by a number and a capital opens a new clue there (only after a count: the
    # figures a clue's own words hold do not split it).
    lines = [part for ln in lines for part in INLINE_CLUE.split(ln)]
    for ln in lines:
        m = al.LINE_CLUE.match(ln)
        if m and int(m.group(1)) > last:
            last = int(m.group(1))
            rows.append([m.group(1), m.group(2)])
        elif m and rows:
            break
        elif rows:
            rows[-1][1] += " " + ln
    for n, body in rows:
        if got := parsed(f"{n} {body}", n):
            out[n] = got
    return out


def suspect_text(e):
    """Whether light `e` has clue text that ocr_clues.suspect flags (a misread word), not a blank."""
    c = e["clue"]
    return bool((c.get("text") or "").strip() and ocr_clues.suspect(c["text"], printed=c.get("asPrinted") or ()))


def fill_columns(puzzle, pages, read_all=None):
    """{light id: "column"} of the unclued lights of `puzzle` read from the
    VLM's transcription of their list's column crops, written into its
    entries. One ask a column crop of a page (cached by crop), only for a
    list holding an unclued light, and none for a page once all are filled.
    A clue is taken only when its number is an unclued light's of the list's
    direction, its printed count equals the light's length, it is the only
    clue of that number in the transcription and its text is no copy of a
    clue the puzzle already has. A light whose clue text is there but suspect
    (ocr_clues.suspect: a misread word) is read the same way and its text
    replaced, only when the column read gives exactly one clue of its number
    on the page's list (not twice, over its columns) and that clue is not
    itself suspect."""
    import vlm_reader as vlm
    read_all = read_all or vlm.read_all
    out = {}

    def unclued():
        return {(str(e["number"]), e["direction"]): e for e in puzzle["entries"]
                if not (e["clue"].get("text") or "").strip() and e["clue"].get("missing") and "text" in e["clue"]}

    def unfit():
        return {(str(e["number"]), e["direction"]): e for e in puzzle["entries"] if suspect_text(e)}

    def numbered(cols):
        return sum(bool(al.LINE_CLUE.match(ln[4])) for c in cols for ln in c)

    for img, words, laid in pages:
        want = {**unfit(), **unclued()}
        if not want:
            break
        best = None
        for which in ["page", *ocr_clues.READERS]:
            cols = gl.page_columns(words.get(which) or [])
            if cols and (best is None or numbered(cols) > numbered(best)):
                best = cols
        for way, lines in zip(("across", "down"), best or ()):
            mine = {n: e for (n, d), e in want.items() if d == way}
            if not mine or not lines:
                continue
            try:
                replies = read_all([vlm.crop(img, b) for b in column_boxes(img, lines)])
            except RuntimeError:
                return out
            gots = [clues_in(sections(reply, way)) for reply in replies]
            for got in gots:
                for n, e in mine.items():
                    c = got.get(n)
                    if c is None or c[1] != e["length"] or not re.search(r"[A-Za-z]{2}", c[0]):
                        continue
                    # Text there but misread: only a column read that names its number once, in a text
                    # that checks out, takes its place.
                    if suspect_text(e) and (sum(n in g for g in gots) != 1 or ocr_clues.suspect(c[0])):
                        continue
                    others = [letters(o["clue"]["text"]) for o in puzzle["entries"]
                              if o is not e and (o["clue"].get("text") or "").strip()]
                    if any(difflib.SequenceMatcher(None, letters(c[0]), o).ratio() >= CLASH for o in others):
                        continue
                    e["clue"] = {"text": c[0], "enumeration": c[2]}
                    out[f"{n}-{way}"] = "column"
    return out


def accepted(got, n, length, ocr, counts):
    """The clue dict of transcription `got` (parsed) when a page fact checks it."""
    if got is None:
        return None
    text, count, printed = got
    if counts:
        if count != length:
            return None
        return {"text": text, "enumeration": printed}
    if count is not None and count != length:
        return None
    if difflib.SequenceMatcher(None, letters(text), letters(re.sub(r"^\W{0,2}\d{1,2}\W{0,2}\s+", "", ocr))).ratio() < AGREE:
        return None
    return {"text": text, **({"enumeration": printed} if count else {})}


def fill(puzzle, pages, read_all=None):
    """{light id: reason} of the clues of `puzzle` (join's) that lack their
    text and are read here, written into its entries. `pages`: [(img, words)]
    of the number's pages, words as gale_listener.read_page(keep=) gives.
    A transcription not answered (spooled, the VLM down) leaves the clue
    blank to be asked again."""
    def lacking():
        return [e for e in puzzle["entries"] if not (e["clue"].get("text") or "").strip() and e["clue"].get("missing")
                and "text" in e["clue"]]
    if not lacking() and not (COLUMNS and any(suspect_text(e) for e in puzzle["entries"])):
        return {}
    out = fill_columns(puzzle, pages, read_all) if COLUMNS else {}
    missing = lacking()
    if not missing or len(missing) > MAX_GAPS:
        return out
    import vlm_reader as vlm
    read_all = read_all or vlm.read_all
    for e in missing:
        lid = f"{e['number']}-{e['direction']}"
        for img, words, laid in pages:
            which, lines = lines_of(words, lid)
            if not lines:
                continue
            crops = [vlm.crop(img, b) for b in boxes_of(img, lines)]
            try:
                reply = "\n".join(read_all(crops))
            except RuntimeError:
                break
            ocr = " ".join(ln[4] for ln in lines)
            got = accepted(parsed(reply, str(e["number"])), str(e["number"]), e["length"], ocr, counted(laid))
            if got:
                e["clue"] = got
                out[lid] = "counted" if got.get("enumeration") and counted(laid) else "agreed"
                break
    return out
