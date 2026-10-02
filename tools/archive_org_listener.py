#!/usr/bin/env python3
"""Read the Listener crosswords in archive.org's scans of The Times' Saturday editions.

    python3 tools/archive_org_listener.py --out ~/.cache/archive_org_crops/unfiled
    python3 tools/archive_org_listener.py --show NewsUK1998UKEnglish/1998-07-25_66263

From the late 1990s the Times' Saturday "games" page prints the Listener: a
barred grid at the left under "No. 3472: Marital Progression by Gnivri",
"LISTENER CROSSWORD No 3472" under the grid, the preamble and the two clue
columns (ACROSS, DOWN) to its right, and in a box below, "Solution and notes
for No. 3469", the filled grid and notes of the puzzle three weeks before.

The clue columns are read as tools/file_archive_org_puzzles.py reads the
daily's: archive.org's words (often none for this block), RapidOCR's two
recognisers and the fine-tuned Tesseract, parsed one list per reading, the
fullest list taken and every clue put to the other readings (reconcile).

A page laid out otherwise (1997's grid at the right of the clues) or with
lists that are not ACROSS and DOWN ("Brick clues", "Row clues") reads no
list and is refused.

No reading goes into puzzles/listener. A Listener's answers are entered as
its preamble's device makes them (a letter dropped, a state abbreviated,
lights left unclued), and its clues carry deliberate misprints and extra
letters, which the reconcile vote's spelling mends turn back into words. The
solution grid gives the entries, not the answers, so a filed puzzle would
need each entry's `alteration`, which only reading the preamble gives
(tools/listener_puzzles.py's TIMES rows). Each reading goes to --out as
listener-N.json, with its blanks and the scan's page, for that step.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import file_archive_org_puzzles as fa
import file_trove_puzzles as ftp
import ocr_clues

NUMBER = r"(\d[,.]?\d{3})"
HEAD = re.compile(r"^\W*listener\s+crossword\s+no\.?\s*" + NUMBER, re.IGNORECASE)
TITLE = re.compile(r"^\W*no\.?\s*" + NUMBER + r"\s*[:;]\s*(.+?)\s+by\s+(.+?)\s*$", re.IGNORECASE)
SOLUTION = re.compile(r"^\W*solution\s+(?:and\s+notes\s+)?(?:for|to)\s+no\.?\s*" + NUMBER, re.IGNORECASE)
#: Where the clue columns end: the solution box's heading or the line
#: saying when the solution will be printed.
END = re.compile(r"^\W*(?:the\s+)?solution\b", re.IGNORECASE)
#: Listener numbers the Times printed (Oct 1991 - Apr 1999), padded.
NUMBERS = range(3000, 3600)
#: "(6, two words)": the count of words is the print's, not an enumeration.
WORDS = re.compile(r"\(\s*(\d{1,2}(?:\s*[,\-]\s*\d{1,2})*)\s*[,.]\s*\(?\s*[a-z]{2,5}\s+w[a-z]{3,4}\s*\)",
                   re.IGNORECASE)


def line_text(ws):
    return " ".join(w[4] for w in ws)


def scan(d):
    """{"date", "item", "puzzles": [{number, leaf, head, title}], "solutions": [...]}"""
    pages = json.loads((d / "pages.json").read_text())
    leaves = {p["leaf"] for p in pages.get("crossword_pages", ())
              if (d / f"leaf_{p['leaf']:04d}.jpg").exists()}
    found = {"date": pages["date"], "item": pages["item"], "puzzles": [], "solutions": []}
    if not leaves or not (d / "djvu.xml.gz").exists():
        return found
    for leaf, lines in fa.leaf_lines(d / "djvu.xml.gz", leaves).items():
        heads, titles = {}, {}
        for ws in lines:
            text = line_text(ws)
            box = (min(w[0] for w in ws), min(w[1] for w in ws),
                   max(w[2] for w in ws), max(w[3] for w in ws))
            for pat, into in ((HEAD, heads), (TITLE, titles)):
                m = pat.match(text)
                if m and fa.number_of(m.group(1)) in NUMBERS:
                    n = fa.number_of(m.group(1))
                    # The topmost: the coupon's "Listener Crossword No N,
                    # 63 Green Lane" is under the grid's own line.
                    if n not in into or box[1] < into[n][0][1]:
                        into[n] = (box, m)
            m = SOLUTION.match(text)
            if m and fa.number_of(m.group(1)) in NUMBERS:
                found["solutions"].append({"number": fa.number_of(m.group(1)), "leaf": leaf,
                                           "box": box})
        for n, (box, _) in heads.items():
            hit = {"number": n, "leaf": leaf, "head": box}
            if n in titles:
                tbox, m = titles[n]
                hit.update(title=m.group(2).strip(), setter=m.group(3).strip(), titleBox=tbox)
            found["puzzles"].append(hit)
    return found


def grid_of(img, hit):
    """The grid's box: the largest ink above the "LISTENER CROSSWORD No N" line."""
    x0, y0, x1, _ = hit["head"]
    top = hit["titleBox"][3] if "titleBox" in hit else y0 - 1100
    crop = (max(0, x0 - 600), max(0, top), min(img.width, x1 + 700), y0 - 4)
    box = fa.ink_box(img.crop(crop))
    if box is None:
        return None
    return (crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3])


def clue_box(img, grid, solutions=()):
    """Right of the grid, down to the "Solution and notes" box when it is
    below the grid's top (its grid lies under the clue columns)."""
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    bottom = min([int(gy1 + 1.4 * gw)] + [s[1] - 10 for s in solutions if s[1] > gy0 + 100])
    return (gx1 + 15, max(0, gy0 - 150), min(img.width, int(gx1 + 2.3 * gw)),
            min(img.height, bottom))


def heading_word(words, name, below=None):
    """The (x0, y0, x1, y1, text) of the ACROSS or DOWN heading among the
    words: the topmost, at or below `below`'s line when given (the title
    "No. 3444: 8 DOWN 12 DOWN" is above the lists)."""
    for w in sorted(words, key=lambda w: w[1]):
        if fa.heading_of(w[4]) == name and (below is None or w[1] >= below[1] - 20):
            return w
    return None


def columns(words):
    """[across lines, down lines], each [(y0, y1, x0, x1, text)] cut at a gap.
    The lists run in two columns: ACROSS heads the first, and DOWN stands in
    the second, level with ACROSS or under the across clues that ran on into
    the second column's top."""
    across = heading_word(words, "ACROSS")
    down = across and heading_word(words, "DOWN", below=across)
    if not across or not down or down[0] <= across[2]:
        return None
    split = down[0] - 30
    # The column to DOWN's right (the bridge hands) starts a column's width
    # on; a down clue's words start within 0.8 of it.
    right = down[0] + 0.8 * (down[0] - across[0])
    cols = [[], [], []]
    for w in words:
        # By the word's middle: a reader's box for the first clue line can
        # reach up into the heading's.
        mid = (w[1] + w[3]) / 2
        if w is across or w is down or mid < across[3]:
            continue
        if across[0] - 40 <= w[0] < split:
            side = 0
        elif split <= w[0] < right:
            side = 2 if mid >= down[3] else 1
        else:
            continue
        cols[side].append((w[1], w[3], w[0], w[2], w[4]))
    out = []
    for col in cols:
        kept, last = [], None
        for line in fa.merge_rows(col):
            if kept and (line[0] - last > fa.GAP or END.match(line[4])):
                break
            kept.append(line)
            last = line[1]
        out.append(kept)
    # The second column's top is across clues only when they follow on.
    head = out[1] if out[1] and re.match(r"\W*\d", out[1][0][4]) else []
    return [out[0] + head, out[2]]


def text_of(cols):
    if not cols:
        return ""
    return ("ACROSS\n" + "\n".join(l[4] for l in cols[0]) + "\nDOWN\n"
            + "\n".join(l[4] for l in cols[1]))


def clues(text):
    """ftp.clues, going on past a stretch it cannot read: the clues before it
    are kept, and reading starts again at the next clue number."""
    out = []
    while text.strip():
        got, why = ftp.clues(text)
        if got is not None:
            return out + got
        m = re.search(r"at: '(.{1,20})", why or "")
        at = text.find(m.group(1)) if m else -1
        if at < 0:
            break
        if at:
            head, _ = ftp.clues(text[:at])
            out += head or []
        nxt = re.compile(r"\s(?=\d{1,2}\s+[A-Z\"'.])").search(text, at + 1)
        if not nxt:
            break
        text = text[nxt.end():]
    return out


def parse(text):
    """fa.parse, with each list read past a stretch that does not parse."""
    secs = ftp.sections(fa.tidy(text))
    if secs is None:
        return None, "no ACROSS and DOWN lists"
    parsed = {k: clues(t) for k, t in secs.items()}
    if not all(parsed.values()):
        return None, "a list has no clue that parses"
    return parsed, None


def tidy(text):
    """Listener counts into the daily's shape: "(6, two words)" is "(6)";
    a clue number read as two digits ("1 9 Nurse") is one, and specks
    before it go."""
    # A two-digit count set wide, "(1 1)", is one number: a count's parts
    # are printed with a comma or hyphen between them.
    text = re.sub(r"\((\d) (\d)\)", r"(\1\2)", text)
    # A speck read as a middle dot ("study·money") is a space.
    text = text.replace("\u00b7", " ")
    # Specks the scan left before a clue number (". 11", ":. 11").
    text = re.sub(r"^[.:;,'`\u2018\u2019 ]+(?=[\dIl])", "", text, flags=re.MULTILINE)
    text = re.sub(r"^(\d) (\d) (?=\S)", r"\1\2 ", text, flags=re.MULTILINE)
    text = re.sub(r"^(\d{1,2})(?=[A-Z]{2})", r"\1 ", text, flags=re.MULTILINE)
    return WORDS.sub(r"(\1)", text)


#: A count inside a clue's text: the next clue ran on after it.
RUN_ON = re.compile(r"\(\s*[\dSIl,.\- ]*\)\s*\S")


def lay(parsed):
    """{light: (text, enumeration or None, None)} by each clue's own number:
    the reading above the last number laid, else the smallest."""
    out = {}
    for direction in ("across", "down"):
        last = 0
        for clue in parsed[direction]:
            nums = sorted(n for n in clue["tokens"][0] if n > last) or sorted(clue["tokens"][0])
            if not nums or clue["see"] is not None:
                continue
            last = nums[0]
            enums = sorted(clue["enums"])
            out[f"{last}-{direction}"] = (clue["text"], enums[0] if len(enums) == 1 else None, None)
    return out


#: The next clue's number (">0" for a misread 10) and first word inside a
#: clue's text.
NEXT_NUMBER = re.compile(r"\s\S?\d{1,2}\s+[A-Z]")
#: How alike two readings' texts for a light must be to corroborate it.
CORROBORATE = 0.7


def sound(text):
    """A clue text that is one clue: words, starting as a clue starts (a
    lone "1" is the I ocr_clues.clean makes of it), with no count or clue number
    inside it."""
    return bool(text and re.match(r"[A-Z\"'.\u2018\u201c]|1\s", text)
                and not RUN_ON.search(text) and not NEXT_NUMBER.search(text))


def pick(lays):
    """Every light any reading laid, each from the first reading (fullest
    first) whose text for it is sound and which another reading laid on the
    same light alike; a light no two readings agree on is filed blank."""
    out = {}
    order = sorted({lid for laid in lays for lid in laid},
                   key=lambda lid: (lid.split("-")[1] != "across", int(lid.split("-")[0])))
    for lid in order:
        have = [laid[lid] for laid in lays if lid in laid]
        texts = [v[0].lower() for v in have]
        good = [v for k, v in enumerate(have) if sound(v[0]) and any(
            j != k and ocr_clues.similar(texts[k], t) >= CORROBORATE for j, t in enumerate(texts))]
        enum = next((v[1] for v in have if v[1]), None)
        out[lid] = good[0] if good else ("", enum, None)
    return out


def ocr_words(img, box, which, cache_path):
    """[(x0, y0, x1, y1, text)] one reader (ocr_clues.READERS) finds in `box`, read at
    ocr_clues.UPSCALE as the daily's columns are, in page coordinates; cached."""
    if cache_path.exists():
        return [tuple(w) for w in json.loads(cache_path.read_text())]
    import numpy as np
    crop = img.crop(box).convert("RGB")
    crop = crop.resize((crop.width * ocr_clues.UPSCALE, crop.height * ocr_clues.UPSCALE))
    if which in ocr_clues.TESS_MODELS:
        res = [(((x0, y0), (x1, y1)), t, None)
               for x0, y0, x1, y1, t in ocr_clues.tesseract_words(crop, ocr_clues.TESS_MODELS[which])]
    else:
        res, _ = ocr_clues.engine(which)(np.asarray(crop), use_cls=False)
    words = []
    for b, t, _ in res or ():
        xs, ys = [p[0] / ocr_clues.UPSCALE for p in b], [p[1] / ocr_clues.UPSCALE for p in b]
        words.append((int(min(xs)) + box[0], int(min(ys)) + box[1],
                      int(max(xs)) + box[0], int(max(ys)) + box[1], t))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(words))
    return words


def read(d, hit, solutions=()):
    """(verdict, {light: (text, enumeration, None)} or None) for one Listener."""
    n, leaf = hit["number"], hit["leaf"]
    verdict = {"number": n, "leaf": leaf}
    img = fa.page(d, leaf)
    grid = grid_of(img, hit)
    if grid is None:
        verdict["refused"] = "no ink above the heading"
        return verdict, None
    gw, gh = grid[2] - grid[0], grid[3] - grid[1]
    if not (450 <= gw <= 1100 and 0.7 <= gw / max(gh, 1) <= 1.4):
        verdict["refused"] = f"the ink above the heading is {gw}x{gh}, not a grid"
        return verdict, None
    box = clue_box(img, grid, [s["box"] for s in solutions if s["leaf"] == leaf])
    # The crop is in the cache's name: a reading of another box is not this one.
    return read_box(d, leaf, img, box, f"{d.name}_listener{n}_{'-'.join(map(str, box))}", verdict)


def read_box(d, leaf, img, box, key, verdict, split=None):
    """(verdict, {light: (text, enumeration, None)} or None) for the ACROSS
    and DOWN columns inside `box` on one leaf: archive.org's words and every
    ocr_clues.READERS reading (cached under `key`), parsed, laid by number (pick)
    and voted on (ocr_clues.reconcile). With `split` (the x between the columns),
    Tesseract reads each column alone: over two columns its line finder
    runs lines of both together."""
    words = {"djvu": [w for ws in fa.leaf_lines(d / "djvu.xml.gz", {leaf})[leaf] for w in ws
                      if box[0] <= w[0] and w[2] <= box[2] and box[1] <= w[1] <= box[3]]}
    for which in ocr_clues.READERS:
        path = fa.CROPS / "rapid" / f"{key}.{ocr_clues.reader_key(which)}.json"
        if split and which in ocr_clues.TESS_MODELS:
            halves = ((box[0], box[1], split, box[3]), (split, box[1], box[2], box[3]))
            words[which] = [w for k, half in enumerate(halves) for w in ocr_words(
                img, half, which, path.with_name(f"{key}.col{k}.{ocr_clues.reader_key(which)}.json"))]
        else:
            words[which] = ocr_words(img, box, which, path)
    texts = {k: tidy(fa.tidy(text_of(columns(w)))) for k, w in words.items()}
    tried = []
    for k, t in texts.items():
        parsed, why = parse(t) if t.strip() else (None, "no words")
        if parsed is None:
            verdict.setdefault("unparsed", {})[k] = why
            continue
        tried.append((sum(len(v) for v in parsed.values()), -len(tried), k, parsed))
    if not tried:
        verdict["refused"] = "no reading parses"
        return verdict, None
    tried.sort(reverse=True)
    best = tried[0][2]
    verdict["reading"] = best
    laid = pick([lay(t[3]) for t in tried])
    lengths = {lid: ftp.count(e) for lid, (_, e, _) in laid.items() if e}
    stream = [t for k, t in texts.items() if k != best and t.strip()]
    laid, blank = ocr_clues.reconcile(laid, stream, lengths)
    for lid, (t, e, g) in laid.items():
        if t and not sound(t):
            # The vote put back words that run on into the next clue.
            laid[lid] = ("", e, g)
            blank[lid] = "runs on into the next clue"
    verdict["clues"] = len(laid)
    verdict["agreed"] = sum(1 for t, _, _ in laid.values() if t)
    if blank:
        verdict["blank"] = blank
    return verdict, laid


def reading(d, found, hit, laid, verdict):
    """The unfiled reading written to --out."""
    return {
        "id": f"listener-{hit['number']}",
        "number": hit["number"],
        "series": "listener",
        "name": f"Listener crossword No {hit['number']:,}" + (f": {hit['title']}" if hit.get("title") else ""),
        "setter": hit.get("setter"),
        "date": found["date"],
        "source": {"url": fa.PAGE_URL.format(item=found["item"], leaf=hit["leaf"])},
        "unfiled": "a Listener's entries are its preamble's alterations of the answers; "
                   "filing needs them read off the preamble",
        "verdict": verdict,
        "clues": {lid: {"text": t, "enumeration": e} for lid, (t, e, _) in laid.items()},
    }


def run(cache=fa.CACHE, out_dir=None, out=sys.stdout):
    counts = {"puzzles": 0, "read": 0, "complete": 0}
    for d in fa.edition_dirs(cache):
        if datetime.date.fromisoformat(d.name[:10]).weekday() != 5:
            continue
        found = scan(d)
        for hit in found["puzzles"]:
            counts["puzzles"] += 1
            verdict, laid = read(d, hit, found["solutions"])
            if laid is None:
                print(f"{d.name} listener-{hit['number']}: {verdict['refused']}", file=out)
                continue
            counts["read"] += 1
            whole = not verdict.get("blank")
            counts["complete"] += whole
            print(f"{d.name} listener-{hit['number']}: {verdict['agreed']}/{verdict['clues']} clues",
                  file=out)
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"listener-{hit['number']}.json"
                path.write_text(json.dumps(reading(d, found, hit, laid, verdict), indent=1,
                                           ensure_ascii=False) + "\n")
    print(f"{counts['puzzles']} Listeners found, {counts['read']} read, "
          f"{counts['complete']} with every clue; none filed", file=out)
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="write each reading here as listener-N.json")
    ap.add_argument("--show", help="<item>/<edition dir>: print its readings")
    args = ap.parse_args(argv)
    if args.show:
        d = fa.CACHE / args.show
        found = scan(d)
        for hit in found["puzzles"]:
            verdict, laid = read(d, hit, found["solutions"])
            print(json.dumps(verdict, indent=1))
            for lid, (t, e, _) in (laid or {}).items():
                print(f"{lid:10s} {t} ({e})")
        return 0
    run(out_dir=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
