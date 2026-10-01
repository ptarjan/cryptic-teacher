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
  - The grid comes from grid.jpg (tools/trove_grid.py), and is used only when
    it is 180-degree symmetric and every clue the OCR kept agrees with it:
    each clue number names one of its lights, and each enumeration counts that
    light (or the group a linked clue names). OCR slips in numbers (S for 5 or
    8, I or l for 1, O for 0) are repaired only where the grid's light decides
    the reading. A disagreement means the picture is not used, never that it
    is forced to fit: the grid is then rebuilt from the clue list by
    tools/reconstruct_grid.py, and filed only when that rebuild is unique.
  - The answers are left out: the SOLUTION articles' letters are too small to
    read reliably, so the nightly cold solve (tools/daily_update.sh, step 3a)
    fills them in.

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
rerun reads only articles that are new or changed (--limit N caps those per
run). A puzzle file on disk is never rewritten.
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import enumeration
import reconstruct_grid as rg
import series as series_meta
import trove_grid
from fetch_puzzle import puzzle_path, write_puzzle_file
from file_penguin_puzzle import separators
from groups import entry_id

SERIES = "canberra"
CACHE = Path(os.path.expanduser("~/.cache/trove"))
TOOL = "tools/file_trove_puzzles.py"
ARTICLE = "https://trove.nla.gov.au/newspaper/article/{}"
#: The code whose change makes every article worth reading again.
CODE = [Path(__file__), TOOLS / "trove_grid.py"]
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
SEE_RE = re.compile(r"^see\s+(\d+)", re.IGNORECASE)


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
        if re.match(r"\s*(solution|yesterday|today's solution)", lines[i], re.IGNORECASE):
            end = i
            break
    # What follows the heading on its line is a clue only when it starts
    # with a digit: "ACROSS II" is a rule the OCR read, not clue 11.
    def rest(text):
        return text if re.match(r"\s*\d", text) else ""
    return {"across": rejoin([rest(a_rest)] + lines[a + 1:d]),
            "down": rejoin([rest(d_rest)] + lines[d + 1:end])}


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
        tokens = [readings(t) for t in re.findall(rf"{NUM}|{JUNK_NUM}", m.group(1))] or [set()]
        rest = text[body_from:]
        see = SEE_RE.match(rest)
        if see:
            # "See 12" (and maybe "Across."), then the next clue's number.
            tail = re.match(r"see\s+\d+(?:\s*(?:across|down))?\.?", rest, re.IGNORECASE)
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
            out[lid] = (clue["text"], fits[0] if fits else None, group if len(group) > 1 else None)
    return out, None


def rebuild(parsed):
    """The one grid the clue list's numbers and lengths allow, or (None, why).
    Needs every clue's number and count to be unambiguous."""
    spec = []
    for direction in ("across", "down"):
        for clue in parsed[direction]:
            if len(clue["tokens"]) > 1 or clue["see"] is not None:
                return None, "a linked clue: its lights' lengths are not known apart"
            if len(clue["tokens"][0]) != 1:
                return None, f"clue number {sorted(clue['tokens'][0])} is ambiguous without a grid"
            if len(clue["enums"]) > 1:
                return None, f"enumeration {sorted(clue['enums'])} is ambiguous without a grid"
            n = next(iter(clue["tokens"][0]))
            length = count(next(iter(clue["enums"]))) if clue["enums"] else None
            spec.append((n, direction, length))
    try:
        found, info = rg.reconstruct(spec, limit=2, max_nodes=REBUILD_NODES)
    except ValueError as e:
        return None, f"clue list unusable: {e}"
    if info.get("gaps"):
        return None, f"numbers {info['gaps']} lost from the clue list"
    if len(found) == 1:
        return list(found[0]), None
    if found:
        return None, "more than one grid fits the clue list"
    return None, "the search " + ("ran out of budget" if info["truncated"] else "found no grid")


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


def input_hash(d, code):
    """The article's files by size and modification time, and the code: a
    rerun stats every article but reads only those whose hash moved."""
    h = hashlib.sha256(code.encode())
    for name in ("meta.json", "ocr.txt", "grid.jpg"):
        p = d / name
        st = p.stat() if p.exists() else None
        h.update((f"{name}:{st.st_size}:{st.st_mtime_ns}" if st else f"{name}:-").encode())
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
    verdict = {"clues": sum(len(v) for v in parsed.values())}
    grid, laid, how = None, None, None
    if (d / "grid.jpg").exists():
        g, why = trove_grid.read_grid(d / "grid.jpg")
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
        g, why = rebuild(parsed)
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
    held = already_held(laid)
    if held:
        verdict["skip"] = f"already held as {held}"
        return verdict, None
    puzzle = build(meta["id"], meta, ocr, grid, how, laid, day)
    if puzzle["id"] in taken and taken[puzzle["id"]] != meta["id"]:
        verdict["refused"] = f"{puzzle['id']} is article {taken[puzzle['id']]}'s"
        return verdict, None
    verdict["id"] = puzzle["id"]
    return verdict, puzzle


def run(cache=CACHE, write=True, ledger=None, out=sys.stdout, puzzles=None, limit=None):
    """File what is new under `cache`; `puzzles` is a directory to write to
    instead of the corpus (tests). Returns the tally it prints."""
    ledger = Path(ledger or cache / "filed.jsonl")
    known = {}
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            row = json.loads(line)
            known[row["article"]] = row
    taken = {row["id"]: a for a, row in known.items() if row.get("id")}
    code = code_hash()
    tally, fresh = {}, 0
    dirs = sorted(p for p in cache.iterdir() if (p / "meta.json").exists()) if cache.exists() else []
    for d in dirs:
        aid = d.name
        h = input_hash(d, code)
        row = known.get(aid)
        if not (row and row.get("hash") == h):
            if limit is not None and fresh >= limit:
                tally["left for the next run"] = tally.get("left for the next run", 0) + 1
                continue
            fresh += 1
            try:
                verdict, puzzle = consider(d, taken)
            except Exception as e:  # noqa: BLE001 -- one bad article is a verdict, not a crash
                verdict, puzzle = {"refused": f"crashed: {type(e).__name__}: {e}"}, None
            if puzzle is not None and write:
                path = (Path(puzzles) / f"{puzzle['id']}.json" if puzzles
                        else puzzle_path(SERIES, puzzle["number"]))
                if not path.exists():
                    write_puzzle_file(path, puzzle, generator=TOOL)
                    verdict["wrote"] = True
            row = {"article": aid, "hash": h, **verdict}
            if puzzle is not None:
                taken[puzzle["id"]] = aid
            if write or not puzzle:
                known[aid] = row
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
        ledger.parent.mkdir(parents=True, exist_ok=True)
        tmp = ledger.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in known.values()))
        tmp.replace(ledger)
    print(f"{len(dirs)} articles in {cache}", file=out)
    for k in sorted(tally):
        print(f"  {tally[k]:5d}  {k}", file=out)
    return tally


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--ledger", type=Path, help="default <cache>/filed.jsonl")
    ap.add_argument("--out", type=Path, help="write puzzles here, not into puzzles/")
    ap.add_argument("--limit", type=int, help="read at most N new or changed articles")
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
        limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
