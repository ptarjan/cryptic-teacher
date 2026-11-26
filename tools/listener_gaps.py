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
#: The share of letters a transcription and an OCR reading of the same lines
#: must agree on where no count checks the clue. Measured over the 1,763
#: uncounted clues of the refused pages whose `page` reading and voted text
#: both exist (the reading of one reader against the vote of three: median
#: and 75th percentile 1.0, 10th percentile 0.75, the low tail line joins and
#: heading lines): 0.9 is a letter in ten, the readings of a clue both right.
AGREE = 0.9
#: A count printed after a clue: "(5)", "(3,4)", "(4-4)".
COUNT = re.compile(r"\s*\((\d{1,2}(?:\s*[,\-]\s*\d{1,2})*)\)\W{0,2}$")


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
    missing = [e for e in puzzle["entries"] if not (e["clue"].get("text") or "").strip() and e["clue"].get("missing")
               and "text" in e["clue"]]
    if not missing or len(missing) > MAX_GAPS:
        return {}
    import vlm_reader as vlm
    read_all = read_all or vlm.read_all
    out = {}
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
