#!/usr/bin/env python3
"""File the Canberra Times crosswords fetched from Trove into puzzles/canberra/.

    python3 tools/file_trove_puzzles.py              # file what is new on disk
    python3 tools/file_trove_puzzles.py --dry-run    # count, write nothing
    python3 tools/file_trove_puzzles.py --cache DIR  # another fetch cache

Reads what tools/fetch_trove.py leaves in ~/.cache/trove/<article id>/
(meta.json, ocr.txt, grid.jpg) and files every cryptic whose clues parse.
Only the clues are mandatory:

  - The clues come from ocr.txt: the ACROSS and DOWN lists, wrapped lines
    rejoined (a word the paper hyphenated over a line end is rejoined when
    the joined word is in tools/data/cmudict.txt.gz and its halves are not).
  - A clue the OCR lost or garbled (a number read as junk, a bracket broken,
    "(S)") is repaired from RapidOCR's reading of the page's clue columns
    when tools/trove_clue_ocr.py has cached them beside the cache
    (~/.cache/trove-clues), anchored on text both readings share.
  - The grid comes from grid.jpg (tools/trove_grid.py), and is used only when
    it is 180-degree symmetric and every clue the OCR kept agrees with it:
    each clue number names one of its lights, and each enumeration counts that
    light (or the group a linked clue names). OCR slips in numbers (S for 5 or
    8, I or l for 1, O for 0) are repaired only where the grid's light decides
    the reading. A disagreement means the picture is not used, never that it
    is forced to fit: the grid is then rebuilt from the clue list by
    tools/reconstruct_grid.py, and filed only when that rebuild is unique.
  - Every clue's words are then put to our own readings of the page's clue
    zones (tools/ocr_clues.py's READERS, cached as read.<reader>.txt beside
    the zones), Trove's text one voter among them: each word takes the
    spelling the readings share, else the one lexicon spelling, as the
    archive.org scans' filer does; the desktop's VLM (tools/vlm_reader.py),
    when it answers, is one more reading and reads each clue the vote
    leaves blank. (Trove's text is its current one, with
    any correction its users made.) A puzzle files only when every light
    has a clue, every clue's vote is won and ocr_clues.suspect() finds no
    word OCR made up ("trom", "know7", "bacK"); else it waits.
  - The answers are read off the paper's printed solution grid by
    tools/trove_solution_ocr.py, a light only when every letter is read
    surely and no crossing disagrees; the rest stay None for the nightly
    cold solve (tools/daily_update.sh, step 3a). A puzzle filed before its
    solution was fetched gets its answers on a later run.

Series and numbers: one series, `canberra`, numbered by print date as YYMMDD
(No 720601 is Thursday 1 June 1972). The London Times number is printed once
in seventeen years of OCR and the Guardian reprints carry the Canberra
Times's own "English cryptic 715C", so neither paper's sequence can number
them; a date number is stable however much of the fetch has arrived, and it
never meets a times-* or cryptic-* id. The paper's own label ("English
cryptic 715C", a setter's byline) goes in the name and the setter. A Guardian
reprint whose clues match a held cryptic-* puzzle is not filed again.

Resumable and idempotent: ~/.cache/trove/filed.jsonl records each article's
verdict against its files' sizes and times and a hash of this code, so a
rerun reads only articles that are new or changed, the never-read first and
then the stale by when they were read (tools/scan_queue.py), the ledger saved
after each. --seconds N stops starting new reads once N seconds have passed
(a page-image read is 15-100 s); what is left keeps its old ledger row, so it
stays pending for the next run. --workers N reads N articles at once. A puzzle file on disk is never rewritten.
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import enumeration
import ocr_clues
import reconstruct_grid as rg
import scan_queue
import series as series_meta
import trove_clue_ocr
import trove_grid
import trove_solution_ocr
import vlm_reader as vlm
from fetch_puzzle import puzzle_path, write_puzzle_file
from file_penguin_puzzle import separators
from groups import entry_id
from ocr_clues import SEE_RE

SERIES = "canberra"
CACHE = Path(os.path.expanduser("~/.cache/trove"))
TOOL = "tools/file_trove_puzzles.py"
ARTICLE = "https://trove.nla.gov.au/newspaper/article/{}"
#: The code whose change makes every article worth reading again.
CODE = [Path(__file__), TOOLS / "trove_grid.py", TOOLS / "trove_solution_ocr.py",
        TOOLS / "trove_clue_ocr.py", TOOLS / "ocr_clues.py", TOOLS / "data" / "lexicon.tsv",
        TOOLS / "data" / "clue_lm.tsv.gz", TOOLS / "data" / "clue_compounds.tsv", TOOLS / "vlm_reader.py"]
#: Articles read at once: the desktop VLM serves one request at a time and
#: the host has four cores, so two keep both busy.
WORKERS = 2
#: How hard reconstruct_grid may try before a clue list counts as not pinning
#: its grid down: its own cap, ~10s on a 15x15.
REBUILD_NODES = rg.DEFAULT_MAX_NODES

# A character OCR reads for a digit, and the digits it can stand for.
SLIPS = {"S": "58", "s": "58", "I": "1", "l": "1", "i": "1", "J": "1", "j": "1",
         "!": "1", "|": "1", "X": "1", "O": "0", "o": "0", "B": "8", "Z": "2",
         "z": "2", "b": "6", "G": "6", "g": "9", "q": "9", "A": "4", "T": "7"}
DIGITISH = "0-9" + re.escape("".join(SLIPS))
NUM = rf"[{DIGITISH}]{{1,2}}"
#: A clue number OCR turned to junk ("f About to surround"): it is placed by
#: the grid alone, in the one slot its neighbours leave.
JUNK_NUM = r"(?:[a-zA-Z]|[a-zA-Z#?*%&$£!|'■\"`.,]{0,2}[#?*%&$£!|'■\"`.,][a-zA-Z#?*%&$£!|'■\"`.,]{0,2})"
BRACKET = re.compile(rf"\(([^()]{{1,12}})\)\s*\.?|\(([{DIGITISH},\-]{{1,5}}?)\.?(?=\s|$)"
                     r"|(?<=\s)[jJft\[{]\s?(\d{1,2}(?:[,\-]\d{1,2})*)\)\s*\.?")


# ------------------------------------------------------------ the article

def header(ocr):
    """(date, the article's head: its lines before ACROSS, lowercased)."""
    lines = ocr.splitlines()
    m = re.search(r"\w+day (\d{1,2} \w+ \d{4})", lines[0] if lines else "")
    day = datetime.datetime.strptime(m.group(1), "%d %B %Y").date() if m else None  # noqa: DTZ007 -- a print day, no time zone
    head = []
    for line in lines[1:]:
        if re.match(r"\s*(clues\s+)?across\b", line, re.IGNORECASE):
            break
        head.append(line)
    return day, " ".join(head)


def kind(ocr, title):
    """What the article is: "cryptic", or why it is skipped."""
    _, head = header(ocr)
    low = (title + " " + head).lower()
    has_lists = re.search(r"^\s*(clues\s+)?across\b", ocr, re.IGNORECASE | re.MULTILINE) and \
        re.search(r"^\s*(clues\s+)?down\b", ocr, re.IGNORECASE | re.MULTILINE)
    if "solution" in low.split("crossword")[0] and not has_lists:
        return "a solution grid"
    if not has_lists:
        return "not a crossword"
    if "quick" in low or "holiday crossword" in low:
        return "not a cryptic"
    if "australian" in low:
        return "an Australian cryptic"
    if "cryptic" in low or "times crossword" in low:
        return "cryptic"
    return "not a cryptic"


def label(ocr):
    """(the paper's own label, setter) off the article head: "English cryptic
    715C" and its byline, "The Times Crossword No 15,038", or ("", None)."""
    _, head = header(ocr)
    m = re.search(r"english cryptic\s*(\d+\s*\(?c\)?)?(?:\s*by\s+([A-Z][A-Za-z' ]+))?", head, re.IGNORECASE)
    if m:
        number = re.sub(r"\W", "", m.group(1) or "").upper()
        setter = (m.group(2) or "").strip().title() or None
        return (f"English cryptic {number}" if number else "English cryptic"), setter
    m = re.search(r"times crossword(?: puzzle)?\s+no\.?\s*([\d,]+)", head, re.IGNORECASE)
    if m:
        return f"The Times Crossword No {m.group(1)}", None
    return "", None


# ------------------------------------------------------------ the clues

_WORDS = None


def words():
    """(every spelling cmudict knows, WordNet's words): the first decides
    whether a rejoined word exists, the second whether a half is a word."""
    global _WORDS
    if _WORDS is None:
        with gzip.open(TOOLS / "data" / "cmudict.txt.gz", "rt", encoding="latin-1") as f:
            spellings = {line.split()[0].lower() for line in f
                         if line[:1].isalpha() and line.split()}
        with gzip.open(TOOLS / "data" / "wordnet.json.gz", "rt", encoding="utf-8") as f:
            wordnet = set(json.load(f)["words"])
        _WORDS = (spellings | wordnet, wordnet)
    return _WORDS


def rejoin(lines):
    """One string from wrapped lines. The paper hyphenates over a line end and
    the OCR drops the hyphen: "archi" + "tecture" is one word when the whole
    is a word and a half is not ("un" + "hinged" stays two)."""
    known, wordnet = words()
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out:
            a = re.search(r"([A-Za-z]+)-?$", out)
            b = re.match(r"([a-z]+)", line)
            if a and b and (a.group(1) + b.group(1)).lower() in known \
                    and not (a.group(1).lower() in wordnet and b.group(1) in wordnet):
                out = out.rstrip("-") + line
                continue
            out += " "
        out += line
    return out


def sections(ocr):
    """{"across": text, "down": text}, or None when either list is missing."""
    lines = ocr.splitlines()
    marks = {}
    for i, line in enumerate(lines):
        m = re.match(r"\s*(clues\s+)?(across|down)\b\W*", line, re.IGNORECASE)
        if m and m.group(2).lower() not in marks:
            marks[m.group(2).lower()] = (i, line[m.end():])
    if set(marks) != {"across", "down"} or marks["across"][0] > marks["down"][0]:
        return None
    (a, a_rest), (d, d_rest) = marks["across"], marks["down"]
    end = len(lines)
    for i in range(d + 1, len(lines)):
        if re.match(r"\s*[(.]*\s*(solution|yesterday|today's solution)", lines[i], re.IGNORECASE):
            end = i
            break
    # What follows the heading on its line is a clue only when it starts
    # with a digit: "ACROSS II" is a rule the OCR read, not clue 11.
    def rest(text):
        return text if re.match(r"\s*\d", text) else ""
    # The paper's "(Solution Monday)" after the last clue is not its text,
    # nor is what follows it on the page (the next puzzle's lists).
    down = re.sub(r"(?<=[).])\s*\(\s*solution\b[^()]{0,25}\)[\s\S]*$", "",
                  rejoin([rest(d_rest)] + lines[d + 1:end]), flags=re.IGNORECASE)
    down = re.sub(r"(?<=[).])\s*\(?\.?\s*solution\b[^()]{0,25}\)?[.*]?\s*$", "", down, flags=re.IGNORECASE)
    return {"across": rejoin([rest(a_rest)] + lines[a + 1:d]), "down": down}


def readings(token):
    """Every number an OCR'd clue-number token can be: "I5" -> {15}."""
    opts = [""]
    for ch in token:
        if ch.isdigit():
            opts = [o + ch for o in opts]
        elif ch in SLIPS:
            opts = [o + d for o in opts for d in SLIPS[ch]]
        else:
            return set()
    return {int(o) for o in opts if o and o[0] != "0"}


def enum_readings(raw):
    """Every enumeration an OCR'd bracket can be, as printed strings: "S, 4"
    -> {"5,4", "8,4"}. Periods read as commas; spaces between counts too."""
    raw = re.sub(r"\s*([,.\-'])\s*", r"\1", raw.strip()).replace(".", ",")
    raw = re.sub(r"\s+", ",", raw)
    opts = [""]
    for ch in raw:
        if ch.isdigit() or ch in ",-'":
            opts = [o + ch for o in opts]
        elif ch in SLIPS:
            opts = [o + d for o in opts for d in SLIPS[ch]]
        else:
            return set()
    return {o for o in opts if re.fullmatch(r"\d+(?:[,\-']\d+)*", o)
            and all(0 < int(n) <= 23 for n in re.findall(r"\d+", o))}


def clues(text):
    """The clues of one list in printed order: [{"tokens": [number readings
    of each light it names], "text", "enums": {readings}, "see": n}].

    A clue starts at a number token at the start of the list or after the
    previous clue's enumeration; its text runs to its own enumeration. A
    "See N" continuation carries no enumeration and ends where the next
    number starts."""
    start = re.compile(rf"\s*((?:{NUM}|{JUNK_NUM}(?-i:(?=\s+[A-Z])))(?:\s*(?:,|&|and)\s*\d{{1,2}}(?:\s*(?:across|down|ac|dn))?)*)[.,]?\s+(?=\S)",
                       re.IGNORECASE)
    # A speck the OCR read between two clues ("(3-6). _ 3 It's") is not text.
    text = re.sub(r"(\)\.?)\s+[_|*•~^#=+\-—.]{1,3}(?=\s)", r"\1", text)
    out, pos = [], 0
    while pos < len(text):
        m = start.match(text, pos)
        if not m:
            return None, f"cannot find a clue number at: {text[pos:pos + 40]!r}"
        body_from = m.end()
        # Only the lead number may be junk; the ones it links ("1,4",
        # "10,9dn") are numbers, and the commas and "dn" between are not.
        lead = re.match(rf"{NUM}|{JUNK_NUM}", m.group(1))
        links = re.sub(r"(?:across|down|and|ac|dn)\b", " ", m.group(1)[lead.end():], flags=re.IGNORECASE)
        tokens = [readings(lead.group(0))] + [readings(t) for t in re.findall(NUM, links)]
        rest = text[body_from:]
        see = SEE_RE.match(rest)
        if see:
            # "See 12" (and maybe "Across."), then the next clue's number.
            tail = re.match(r"see\s+\d+(?:\s*(?:across|down|ac|dn)\b)?\.?", rest, re.IGNORECASE)
            out.append({"tokens": tokens, "text": tail.group(0).rstrip("."),
                        "enums": set(), "see": int(see.group(1))})
            pos = body_from + tail.end()
            continue
        # The clue ends at the first bracket that is followed by the next
        # clue's number or the list's end. Its content is the count, read
        # with the slips; ")" itself is often read as "1", and "(?)" is a
        # count lost, which still ends the clue.
        end = None
        for e in BRACKET.finditer(rest):
            after = rest[e.end():]
            if not after.strip() or start.match(rest, e.end()):
                end = e
                break
        if end is None:
            out.append({"tokens": tokens, "text": rest.strip(), "enums": set(), "see": None})
            break
        raw = end.group(1) or end.group(2) or end.group(3)
        enums = enum_readings(raw)
        if end.group(2) and re.search(r"[1lI]$", raw):
            enums |= enum_readings(raw[:-1])
        out.append({"tokens": tokens, "text": rest[:end.start()].strip(),
                    "enums": enums, "see": None})
        pos = body_from + end.end()
    return out, None


# ------------------------------------------------------------ the cross-check

def count(enum):
    return sum(int(n) for n in re.findall(r"\d+", enum))


def seven_slips(enum):
    """The readings with one 1 read as 7 or one 7 as 1."""
    out = set()
    for k, ch in enumerate(enum):
        if ch in "17":
            out.add(enum[:k] + ("7" if ch == "1" else "1") + enum[k + 1:])
    return out


def match(parsed, grid):
    """Lay the parsed clues on the grid's lights. Returns ({light id:
    (clue text, enumeration or None, group or None)}, None) when every clue
    the OCR kept agrees with the grid, else (None, the first disagreement).
    A light the OCR lost is absent from the map."""
    lights = rg.light_cells(grid)
    length = {f"{n}-{d}": len(c) for (n, d), c in lights.items()}
    out = {}
    for direction in ("across", "down"):
        expected = [n for (n, d) in lights if d == direction]
        i = 0
        clues_here = parsed[direction]
        for ci, clue in enumerate(clues_here):
            # The first light still to come whose number the token can read as.
            first = clue["tokens"][0]
            j = next((k for k in range(i, len(expected)) if expected[k] in first), None)
            if j is None and i < len(expected):
                # A number misread past every slip ("11" for 21, "f" for 6) is
                # placed only when the next clue's number leaves it exactly
                # one light, and its count must still fit that light.
                nxt = clues_here[ci + 1]["tokens"][0] if ci + 1 < len(clues_here) else None
                if (nxt is None and i == len(expected) - 1) or \
                        (nxt and i + 1 < len(expected) and expected[i + 1] in nxt):
                    j = i
            if j is None:
                return None, (f"{direction} clue {sorted(first)} names no light the grid "
                              f"numbers after {expected[i - 1] if i else 'the start'}")
            n = expected[j]
            i = j + 1
            lid = f"{n}-{direction}"
            group = [lid]
            for t in clue["tokens"][1:]:
                if len(t) != 1:
                    return None, f"{lid}: unreadable linked number"
                m = next(iter(t))
                other = [f"{m}-{d}" for d in ("across", "down") if f"{m}-{d}" in length]
                if not other:
                    return None, f"{lid} links to {m}, which the grid does not number"
                group.append(other[0] if len(other) == 1 else
                             (f"{m}-{direction}" if f"{m}-{direction}" in other else other[0]))
            if clue["see"] is not None:
                if not any(f"{clue['see']}-{d}" in length for d in ("across", "down")):
                    return None, f"{lid} says see {clue['see']}, which the grid does not number"
                out[lid] = (clue["text"], None, None)
                continue
            total = sum(length[g] for g in group)
            fits = sorted(e for e in clue["enums"] if count(e) == total)
            if not fits:
                # A 7 printed thin reads as 1, and back: only the light decides.
                fits = sorted({s for e in clue["enums"] for s in seven_slips(e)
                               if count(s) == total})
            if clue["enums"] and len(fits) != 1:
                return None, (f"{lid}: the enumeration reads as {sorted(clue['enums'])}, "
                              f"the grid holds {total} letters")
            enum = fits[0] if fits and not clue.get("count_only") else None
            out[lid] = (clue["text"], enum, group if len(group) > 1 else None)
    return out, None


#: The Canberra Times grid's side, which a rebuild searches.
SIDE = 15
#: The most cells a scanned grid may misread and still pick one of several
#: grids the clue list allows: OCR's grid reader loses a square or two, not a
#: pattern.
IMAGE_SLACK = 6


def closest(image):
    """reconstruct_grid.unique_grid's `pick`: the one grid nearest the scan,
    when it is clearly nearest and near; None without a scan."""
    if not image:
        return None

    def pick(grids):
        def off(g):
            if len(g) != len(image) or len(g[0]) != len(image[0]):
                return len(g) * len(g[0])
            return sum(a != b for ra, rb in zip(g, image) for a, b in zip(ra, rb))
        ranked = sorted(grids, key=off)
        best = off(ranked[0])
        if best <= IMAGE_SLACK and (len(ranked) == 1 or off(ranked[1]) > best):
            return ranked[0]
        return None
    return pick


def rebuild(parsed, image=None):
    """The one grid the clue list's numbers and lengths allow, or (None, why).
    What the OCR leaves uncertain goes in unknown: a number read several
    ways, an enumeration read several ways, and each light of a linked clue,
    whose count is their sum. Several grids are settled by the scan
    (`image`, the grid read off it even where it disagrees with the clues)."""
    spec = []
    for direction in ("across", "down"):
        for clue in parsed[direction]:
            tokens = clue["tokens"][0]
            n = next(iter(tokens)) if len(tokens) == 1 else None
            length = None
            if len(clue["tokens"]) == 1 and clue["see"] is None and len(clue["enums"]) == 1:
                length = count(next(iter(clue["enums"])))
            spec.append((n, direction, length))
    return rg.unique_grid(spec, cols=SIDE, rows=SIDE, max_nodes=REBUILD_NODES,
                          pick=closest(image))


# ------------------------------------------------------------ the vote

def page_readings(d, zones=None):
    """{reader: its text of the article's clue zones} for every
    ocr_clues.READERS reader, each cached beside the zones as
    read.<reader>.txt (the cache alone serves, without the zones); {} when
    neither is there."""
    where = (zones or clue_zones(d)) / d.name
    cached = {which: where / f"read.{ocr_clues.reader_key(which)}.txt" for which in ocr_clues.READERS}
    images = trove_clue_ocr.zone_images(d.name, zones or clue_zones(d))
    if not images and not all(p.exists() for p in cached.values()):
        return {}
    from PIL import Image
    out = {}
    for which, cache in cached.items():
        if not cache.exists():
            text = "\n".join(ocr_clues.lines_of(ocr_clues.read_words(Image.open(p), which))
                             for p in images)
            cache.write_text(text, encoding="utf-8")
        out[which] = cache.read_text(encoding="utf-8")
    return out


def stacked(images):
    """The zone images one under another, as the article prints them."""
    from PIL import Image
    out = Image.new("RGB", (max(im.width for im in images), sum(im.height for im in images)), "white")
    y = 0
    for im in images:
        out.paste(im.convert("RGB"), (0, y))
        y += im.height
    return out


def parse_reading(text):
    """({"across": clues, "down": clues}, None) for one reading of the
    zones, or (None, why)."""
    secs = sections(text)
    if secs is None:
        return None, "no ACROSS and DOWN lists"
    parsed = {}
    for direction, t in secs.items():
        parsed[direction], why = clues(t)
        if why:
            return None, why
    return parsed, None


def vote(d, laid, grid, zones=None):
    """(laid, None) with every clue's words put to our own readings of the
    page (ocr_clues.reconcile, Trove's text one voter among them), or (None,
    why) when a light has no clue, a clue no spelling wins, or a word
    ocr_clues.suspect() refuses: only a puzzle whose every clue reads true
    is filed."""
    from PIL import Image
    texts = page_readings(d, zones)
    if not texts:
        return None, "no reading of the page's clues to vote with (trove_clue_ocr.py --fetch)"
    lengths = {f"{n}-{dr}": len(c) for (n, dr), c in rg.light_cells(grid).items()}
    lost = sorted(set(lengths) - set(laid), key=lambda k: (k.split("-")[1], int(k.split("-")[0])))
    if lost:
        return None, f"no clue for {', '.join(lost)}"
    images = [Image.open(p) for p in trove_clue_ocr.zone_images(d.name, zones or clue_zones(d))]
    # The desktop's VLM, when it answers, is one more reading, and reads
    # each clue the vote leaves blank shown every reading's text for it.
    if images and vlm.reachable():
        try:
            texts["vlm"] = "\n".join(vlm.read(vlm.crop(im, (0, 0, im.width, im.height))) for im in images)
        except RuntimeError:
            pass  # gone mid-run: read as without it
    before = dict(laid)
    laid, blank = ocr_clues.reconcile(laid, list(texts.values()), lengths, keep_known=True)
    if blank and "vlm" in texts and vlm.reachable():
        page = stacked(images)
        try:
            laid, blank = ocr_clues.vlm_pick(
                texts, laid, blank, parse_reading,
                lambda lid, cands: vlm.pick_in(vlm.crop(page, (0, 0, page.width, page.height)), lid, cands))
        except RuntimeError:
            pass
    # The vote settles words only: a count reconcile() took from the light
    # stands in for one Trove read in parts it could not print ("(6,4)").
    laid = {k: (t, before[k][1] if k in before else e, g) for k, (t, e, g) in laid.items()}
    if blank:
        return None, "clues unread: " + "; ".join(f"{k} {v}" for k, v in sorted(blank.items()))
    shared = None
    for t in texts.values():
        got = {w.lower() for w in ocr_clues.marked(ocr_clues.clean(t))}
        shared = got if shared is None else shared & got
    bad = {k: ocr_clues.suspect(t, shared) + [
        d for d in ocr_clues.doubled(t) if d not in ocr_clues.doubled(before[k][0])]
        for k, (t, _, _) in laid.items()}
    bad = {k: v for k, v in bad.items() if v}
    if bad:
        return None, "suspect words: " + "; ".join(
            f"{k} " + ", ".join(f"{w!r} ({why})" for w, why in v) for k, v in sorted(bad.items()))
    return laid, None


# ------------------------------------------------------------ the puzzle

def build(aid, meta, ocr, grid, how, laid, day):
    """The puzzle dict for a grid and the clues laid on it."""
    lights = rg.light_cells(grid)
    by_id = {}
    entries = []
    for (n, d), cells in lights.items():
        e = {"number": n, "direction": d, "position": {"x": cells[0][1], "y": cells[0][0]},
             "length": len(cells)}
        entries.append(e)
        by_id[entry_id(e)] = e
    seps, groups = {}, {}
    for lid, (text, enum, group) in laid.items():
        if enum:
            try:
                seps.update(separators(group or [lid], by_id, enum))
            except SystemExit:
                laid[lid] = (text, None, None)
                continue
            if group:
                groups[lid] = group
    for e in entries:
        lid = entry_id(e)
        text, enum, _ = laid.get(lid, ("", None, None))
        line = f"{text} ({enum})" if enum else text
        e["clue"] = enumeration.clue(line, separators=seps.get(lid),
                                     missing=not text.strip())
        if lid in groups:
            e["group"] = groups[lid]
        e["solution"] = None
    paper, setter = label(ocr)
    number = int(day.strftime("%y%m%d"))
    name = f"Canberra Times cryptic crossword, {day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"
    if paper:
        name += f" ({paper})"
    return {
        "id": series_meta.puzzle_id(SERIES, number),
        "number": number,
        "series": SERIES,
        "name": name,
        "setter": setter,
        "date": day.isoformat(),
        "dimensions": {"cols": len(grid[0]), "rows": len(grid)},
        "source": {"url": ARTICLE.format(aid),
                   "gridOrigin": "published" if how == "image" else "reconstructed"},
        "entries": entries,
    }


_HELD = None


def held_clues():
    """{normalised clue text: puzzle id} over the Guardian puzzles we hold
    from before 2000, the years a Trove reprint could repeat."""
    global _HELD
    if _HELD is None:
        _HELD = {}
        for path in sorted((ROOT / "puzzles" / "cryptic").glob("19*/*.json")):
            p = json.loads(path.read_text(encoding="utf-8"))
            for e in p.get("entries", ()):
                t = norm((e.get("clue") or {}).get("text", ""))
                if len(t) > 12:
                    _HELD[t] = p["id"]
    return _HELD


def norm(text):
    return re.sub(r"[^a-z]", "", text.lower())


def already_held(laid):
    """The held puzzle id at least half of these clues repeat, or None."""
    hits = {}
    texts = [norm(t) for t, _, _ in laid.values() if len(norm(t)) > 12]
    for t in texts:
        pid = held_clues().get(t)
        if pid:
            hits[pid] = hits.get(pid, 0) + 1
    best = max(hits, key=hits.get, default=None)
    return best if best and hits[best] * 2 >= len(texts) else None


# ------------------------------------------------------------ the run

def code_hash():
    h = hashlib.sha256()
    for p in CODE:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def clue_zones(d):
    """Where tools/trove_clue_ocr.py caches the clue columns of the articles
    in d's cache: ~/.cache/trove-clues beside ~/.cache/trove."""
    return d.parent.parent / f"{d.parent.name}-clues"


def input_hash(d, code):
    """The article's files by size and modification time, and the code: a
    rerun stats every article but reads only those whose hash moved."""
    h = hashlib.sha256(code.encode())
    for name in ("meta.json", "ocr.txt", "grid.jpg"):
        p = d / name
        st = p.stat() if p.exists() else None
        h.update((f"{name}:{st.st_size}:{st.st_mtime_ns}" if st else f"{name}:-").encode())
    h.update(" ".join(p.name for p in trove_clue_ocr.zone_images(d.name, clue_zones(d))).encode())
    h.update(" ".join(sorted(p.name for p in (clue_zones(d) / d.name).glob("read.*.txt"))).encode())
    return h.hexdigest()[:16]


def consider(d, taken):
    """(verdict, puzzle or None) for one article directory."""
    meta = json.loads((d / "meta.json").read_text())
    ocr = (d / "ocr.txt").read_text(encoding="utf-8", errors="replace")
    what = kind(ocr, meta.get("title", ""))
    if what != "cryptic":
        return {"skip": what}, None
    day, _ = header(ocr)
    if day is None:
        return {"refused": "no print date in the OCR's first line"}, None
    secs = sections(ocr)
    if secs is None:
        return {"refused": "no ACROSS and DOWN lists in the OCR"}, None
    parsed = {}
    for direction, text in secs.items():
        parsed[direction], why = clues(text)
        if why:
            return {"refused": f"{direction} clues do not parse: {why}"}, None
    parsed, repairs = trove_clue_ocr.repaired(d, parsed, clue_zones(d))
    verdict = {"clues": sum(len(v) for v in parsed.values())}
    if repairs:
        verdict["clueRepairs"] = repairs
    grid, laid, how, image = None, None, None, None
    if (d / "grid.jpg").exists():
        g, why = trove_grid.read_grid(d / "grid.jpg")
        image = g
        if g and not trove_grid.symmetric(g):
            g, why = None, "not 180-degree symmetric"
        if g:
            laid, why = match(parsed, g)
            if laid is not None:
                grid, how = g, "image"
            else:
                verdict["imageDisagrees"] = why
        else:
            verdict["imageUnread"] = why
    else:
        verdict["imageUnread"] = "no grid image"
    if grid is None:
        g, why = rebuild(parsed, image)
        if g is None:
            verdict["pending"] = f"no grid: {why}"
            return verdict, None
        laid, why = match(parsed, g)
        if laid is None:
            verdict["pending"] = f"rebuilt grid disagrees: {why}"
            return verdict, None
        grid, how = g, "rebuilt"
    verdict["grid"] = how
    verdict["laid"] = len(laid)
    verdict["lights"] = len(rg.light_cells(grid))
    laid, why = vote(d, laid, grid)
    if laid is None:
        verdict["pending"] = why
        return verdict, None
    held = already_held(laid)
    if held:
        verdict["skip"] = f"already held as {held}"
        return verdict, None
    puzzle = build(meta["id"], meta, ocr, grid, how, laid, day)
    answers, info = trove_solution_ocr.answers_for(d, grid, day, d.parent)
    verdict["answersRead"] = trove_solution_ocr.fill(puzzle, answers)
    verdict["answersFrom"] = info.get("ocr")
    if puzzle["id"] in taken and taken[puzzle["id"]] != meta["id"]:
        verdict["refused"] = f"{puzzle['id']} is article {taken[puzzle['id']]}'s"
        return verdict, None
    verdict["id"] = puzzle["id"]
    return verdict, puzzle


def run(cache=CACHE, write=True, ledger=None, out=sys.stdout, puzzles=None, seconds=None, workers=1,
        wait=False):
    """File what is new under `cache`; `puzzles` is a directory to write to
    instead of the corpus (tests). No article is started once `seconds` have
    passed; `workers` are read at once (scan_queue). Returns the tally it
    prints; None when another run holds the ledger and `wait` is not set."""
    deadline = None if seconds is None else time.monotonic() + seconds
    ledger = Path(ledger or cache / "filed.jsonl")
    with scan_queue.lock(ledger, wait) as mine:
        if not mine:
            print(f"another run holds {ledger.with_suffix('.lock')}: nothing read", file=out)
            return None
        return _run(cache, write, ledger, out, puzzles, deadline, workers)


def _run(cache, write, ledger, out, puzzles, deadline, workers):
    known = {}
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            row = json.loads(line)
            known[row["article"]] = row
    taken = {row["id"]: a for a, row in known.items() if row.get("id")}
    code = code_hash()
    # The VLM's readings are an input: an article read without it is read
    # again once it answers, and one read with it stands while it is down.
    seen_by = vlm.version() if vlm.reachable() else None
    dirs = sorted(p for p in cache.iterdir() if (p / "meta.json").exists()) if cache.exists() else []
    due = {}
    for d in dirs:
        h = input_hash(d, code + (f"+vlm-{seen_by}" if seen_by else ""))
        row = known.get(d.name)
        if not seen_by and row and row.get("vlm") and row.get("hash") == input_hash(d, f"{code}+vlm-{row['vlm']}"):
            h = row["hash"]
        if not (row and row.get("hash") == h):
            due[d] = h
    queue = scan_queue.order(list(due), {d: known[d.name] for d in due if d.name in known},
                             lambda row: row is None)
    for (d,), (verdict, puzzle, vlm_ok) in scan_queue.parallel(
            [(d,) for d in queue], consider_article, workers, deadline, init=set_taken, initargs=(taken,)):
        aid, h = d.name, due[d]
        if puzzle is not None and puzzle["id"] in taken and taken[puzzle["id"]] != aid:
            # Another worker filed this id while this one read.
            verdict, puzzle = {**verdict, "refused": f"{puzzle['id']} is article {taken[puzzle['id']]}'s"}, None
            verdict.pop("id", None)
        if puzzle is not None and write:
            path = (Path(puzzles) / f"{puzzle['id']}.json" if puzzles
                    else puzzle_path(SERIES, puzzle["number"]))
            if not path.exists():
                write_puzzle_file(path, puzzle, generator=TOOL)
                verdict["wrote"] = True
        if seen_by and not vlm_ok:
            h = input_hash(d, code)  # the VLM went down: read again when it answers
        row = {"article": aid, "hash": h, **verdict, "readAt": scan_queue.now()}
        if seen_by and vlm_ok:
            row["vlm"] = seen_by
        if puzzle is not None:
            taken[puzzle["id"]] = aid
        if write or not puzzle:
            known[aid] = row
        if write:
            save(ledger, known)
        del due[d]
    tally = {}
    for d in dirs:
        row = known.get(d.name)
        if d in due:
            tally["left for the next run"] = tally.get("left for the next run", 0) + 1
            continue
        key = ("filed" if row.get("id") else
               f"skipped: {row['skip']}" if row.get("skip") else
               f"pending: {row['pending'].split(':')[0]}" if row.get("pending") else
               f"refused: {row.get('refused', '?')[:60]}")
        tally[key] = tally.get(key, 0) + 1
        if row.get("id"):
            g = f"grid {row['grid']}"
            tally[g] = tally.get(g, 0) + 1
        if row.get("imageDisagrees"):
            tally["image read but disagrees"] = tally.get("image read but disagrees", 0) + 1
    if write:
        save(ledger, known)
    print(f"{len(dirs)} articles in {cache}", file=out)
    for k in sorted(tally):
        print(f"  {tally[k]:5d}  {k}", file=out)
    return tally


def save(ledger, known):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in known.values()))
    tmp.replace(ledger)


_TAKEN = {}


def set_taken(taken):
    """Each process's {puzzle id: article} (consider_article's)."""
    _TAKEN.clear()
    _TAKEN.update(taken)


def consider_article(d):
    """(verdict, puzzle or None, whether the VLM still answers after it)."""
    try:
        verdict, puzzle = consider(d, _TAKEN)
    except Exception as e:  # noqa: BLE001 -- one bad article is a verdict, not a crash
        verdict, puzzle = {"refused": f"crashed: {type(e).__name__}: {e}"}, None
    return verdict, puzzle, vlm.reachable()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--ledger", type=Path, help="default <cache>/filed.jsonl")
    ap.add_argument("--out", type=Path, help="write puzzles here, not into puzzles/")
    ap.add_argument("--seconds", type=float,
                    help="start no new article read after N seconds; the rest wait for the next run")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"articles read at once (default {WORKERS}): one's VLM wait overlaps another's OCR")
    ap.add_argument("--wait", action="store_true",
                    help="wait for another run's hold on the ledger instead of reading nothing")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--show", metavar="ID", help="print one article's verdict and grid")
    args = ap.parse_args(argv)
    if args.show:
        verdict, puzzle = consider(args.cache / args.show, {})
        print(json.dumps(verdict, indent=1))
        if puzzle:
            print(json.dumps(puzzle, indent=1)[:4000])
        return 0
    run(args.cache, write=not args.dry_run, ledger=args.ledger, puzzles=args.out,
        seconds=args.seconds, workers=args.workers, wait=args.wait)
    if not args.out:
        trove_solution_ocr.fill_corpus(args.cache, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
