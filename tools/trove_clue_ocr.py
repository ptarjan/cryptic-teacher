#!/usr/bin/env python3
"""Repair the clues Trove's OCR loses by reading the page scan's clue columns.

    python3 tools/trove_clue_ocr.py --fetch ID [ID ...]   # cache the clue zones
    python3 tools/trove_clue_ocr.py --show ID             # the repair, one article
    python3 tools/trove_clue_ocr.py --fetch-pending N     # nightly: N pending articles

Trove's text OCR of a Canberra Times clue list loses about one clue a puzzle:
a clue number read as junk ("tfl" for 10) glues that clue onto the one
before, a broken bracket ("(6,\\n4> , ,") eats an enumeration, and "(S)"
reads as 5 or 8. Each blocks tools/reconstruct_grid.py. The page scan is
sharp, so tools/file_trove_puzzles.py hands its parsed lists to repair() with
RapidOCR's reading of the article's text zones (cached by fetch() in
~/.cache/trove-clues/<id>/zone<N>.png at ~half the scan's top resolution,
where the print is still ~17px tall).

--fetch-pending caches the zones of up to N articles tools/file_trove_puzzles.py
left pending (no grid fits the clues it read), oldest first, with
PENDING_DELAY seconds between Trove requests; the next filing run reads
them, since the zones are part of an article's input hash.

RapidOCR loses things too (it often drops brackets and the bold clue
numbers), so it never replaces a list. It is a second witness, and every
change it makes is anchored by text both readings share:

  1. A clue number missing from the list is split off the clue before it
     when RapidOCR reads that number in front of words that Trove's text of
     the clue before contains.
  2. A clue with no enumeration, or one read several ways, takes the counts
     RapidOCR reads right after the clue's last words, less the next clue's
     number. A reading Trove left ambiguous must be one of Trove's
     readings; digits Trove kept in a broken bracket must be the same
     digits in the same order. RapidOCR reads a hyphen as a period, so
     counts in parts ("4.5" for 4-5) give the rebuild the light's length
     but are not printed with the clue.
  3. A clue number read several ways takes the number RapidOCR reads
     right before the clue's first words, when it is one of those ways.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

CACHE = Path(os.path.expanduser("~/.cache/trove"))
ZONES = Path(os.path.expanduser("~/.cache/trove-clues"))
#: fetch()'s smallest zone width in pixels: Trove's level 6, half the top
#: resolution, which RapidOCR reads as well as the top one.
ZONE_WIDTH = 220
#: Seconds between Trove requests in the nightly --fetch-pending, twice the
#: full fetch's, since it shares the site with it.
PENDING_DELAY = 2.0
#: Letters a text anchor must share; fewer match by chance.
ANCHOR = 12
#: Letters at a span's edge the two readings may disagree on.
SLIDE = 8
#: Characters after a clue's last words searched for its enumeration.
TAIL = 30

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        import trove_solution_ocr
        from rapidocr_onnxruntime import RapidOCR
        extra = [m for m in trove_solution_ocr.EXTRA_MODELS if m.exists()]
        _ENGINE = RapidOCR(rec_model_path=str(extra[0])) if extra else RapidOCR()
    return _ENGINE


def zone_images(aid, zones=ZONES):
    return sorted((zones / str(aid)).glob("zone*.png"), key=lambda p: int(p.stem[4:]))


def fetch(aid, cache=CACHE, zones=ZONES, trove=None):
    """Cache article `aid`'s text zones (every zone but the grid)."""
    import fetch_trove
    meta = json.loads((cache / str(aid) / "meta.json").read_text())
    out = zones / str(aid)
    out.mkdir(parents=True, exist_ok=True)
    trove = trove or fetch_trove.Trove(str(zones), 1.0, ZONE_WIDTH)
    for i, z in enumerate(meta["zones"]):
        p = out / f"zone{i}.png"
        if z != meta.get("grid") and not p.exists():
            img, _ = trove.crop(z["page"], z, pad=4)
            img.save(p)
    return trove


def pending(cache=CACHE, zones=ZONES):
    """Article ids the filing ledger leaves pending whose zones are not cached."""
    ledger = cache / "filed.jsonl"
    if not ledger.exists():
        return []
    rows = (json.loads(line) for line in ledger.read_text().splitlines() if line.strip())
    return sorted(r["article"] for r in rows
                  if r.get("pending") and not zone_images(r["article"], zones)
                  and (cache / r["article"] / "meta.json").exists())


def fetch_pending(limit, cache=CACHE, zones=ZONES, delay=PENDING_DELAY, trove=None, out=sys.stdout):
    """fetch() the zones of up to `limit` pending articles; returns
    (fetched, failed, left). One article's failure is reported and the rest go
    on: it stays pending and is tried again the next night."""
    import fetch_trove
    todo = pending(cache, zones)
    trove = trove or fetch_trove.Trove(str(zones), delay, ZONE_WIDTH)
    fetched, failed = 0, 0
    for aid in todo[:limit]:
        try:
            fetch(aid, cache, zones, trove)
            fetched += 1
        except Exception as e:  # noqa: BLE001 -- one article's failure is reported, not fatal
            failed += 1
            print(f"  {aid}: {type(e).__name__}: {e}", file=out)
    left = len(todo) - fetched - failed
    print(f"clue zones fetched for {fetched} pending article(s), {failed} failed, "
          f"{left} left", file=out)
    return fetched, failed, left


def read_text(images):
    """RapidOCR's text of the zone images, one printed row a line."""
    import numpy as np
    from PIL import Image
    lines = []
    for p in images:
        res, _ = engine()(np.asarray(Image.open(p).convert("RGB")), use_cls=False)
        boxes = sorted(((b[0][1], b[0][0], b[2][1] - b[0][1], t) for b, t, _ in res or ()))
        row, top, height = [], None, 0
        for y, x, h, t in boxes:
            if row and y > top + height / 2:
                lines.append(" ".join(t for _, t in sorted(row)))
                row = []
            if not row:
                top, height = y, h
            row.append((x, t))
        if row:
            lines.append(" ".join(t for _, t in sorted(row)))
    return "\n".join(lines)


# ------------------------------------------------------------ the repair

def letters(text):
    """(lowercase letters of text, the index in text of each)."""
    idx = [i for i, ch in enumerate(text) if ch.isalpha()]
    return "".join(text[i].lower() for i in idx), idx


def slide(hay, near, least, backward=False):
    """Where `near` (letters from one reading, `near[0]` the edge of the
    span) begins in `hay` (the other reading), letting a few letters at the
    edge differ: the first ANCHOR-letter window of near found once in hay
    places it, shifted back by its offset, when that is at least `least`.
    backward: near runs leftward from the span's end, and the result is
    the end. None when no window places it."""
    for off in range(SLIDE + 1):
        w = near[off:off + ANCHOR]
        if len(w) < ANCHOR:
            return None
        if backward:
            at = find_once(hay, w[::-1])
            if at is not None:
                return at + ANCHOR + off
        else:
            at = find_once(hay, w)
            if at is not None and at - off >= least:
                return at - off
    return None


def find_once(hay, needle):
    """needle's one position in hay, or None when absent or repeated."""
    at = hay.find(needle)
    return at if at >= 0 and hay.find(needle, at + 1) < 0 else None


def numbers(parsed):
    return {next(iter(c["tokens"][0])) for v in parsed.values() for c in v
            if len(c["tokens"][0]) == 1}


ENUM_SEG = re.compile(r"[\s.?!;:'\"]*[(\[{]?\s*(\d{1,2}(?:(?:\s*[,.\-]\s*|\s+)\d{1,2})*)\s*[)\]}]?[\s.,;:]*")


def tail_enum(seg, nxt):
    """The enumeration printed in `seg` (the text between a clue's last word
    and the next clue's first), less the next clue's number `nxt` (its
    readings), or None."""
    m = re.search(r"(\d{1,2})\s*[.,]?\s*$", seg)
    if m and int(m.group(1)) in nxt and re.search(r"\d", seg[:m.start()]):
        seg = seg[:m.start()]
    m = ENUM_SEG.fullmatch(seg)
    if not m:
        return None
    enum = re.sub(r"\s*-\s*", "-", m.group(1))
    enum = re.sub(r"\s*[,.]\s*|\s+", ",", enum)
    parts = [int(n) for n in re.findall(r"\d+", enum)]
    return enum if all(parts) and sum(parts) <= 15 else None


def split_lost(direction, parsed, stream, s_letters, s_idx, notes):
    """Step 1: clues RapidOCR numbers that Trove's list lacks."""
    import file_trove_puzzles as ftp
    out = parsed[direction]
    top = max(numbers(parsed), default=0)
    for m in re.finditer(r"(?<![\w(,.\-])(\d{1,2})\s*[.,]?\s*(?=[A-Z])", stream):
        n = int(m.group(1))
        if n > top or any(c["tokens"][0] == {n} for c in out):
            continue
        k = next((i for i, c in enumerate(out) if len(c["tokens"][0]) == 1
                  and next(iter(c["tokens"][0])) < n
                  and (i + 1 == len(out) or min(out[i + 1]["tokens"][0] or {99}) > n)), None)
        if k is None or out[k]["see"] is not None:
            continue
        at = next((j for j, i in enumerate(s_idx) if i >= m.end()), None)
        if at is None:
            continue
        c = out[k]
        c_letters, c_idx = letters(c["text"])
        pos = slide(c_letters, s_letters[at:at + ANCHOR + SLIDE], 1)
        if not pos:
            continue
        cut = c_idx[pos]
        before = c["text"][:cut].rstrip()
        # The junk Trove read for the number ("tfl", "6."), then the bracket.
        before = re.sub(rf"\s*(?:{ftp.NUM}|{ftp.JUNK_NUM}|\S{{1,3}})[.,]?$", "", before)
        enums = set()
        b = re.search(r"\(([^()]{1,12})\)[\s.,]*$", before)
        if b:
            enums = ftp.enum_readings(b.group(1))
            before = before[:b.start()].rstrip()
        split(out, k, cut, before, enums, n)
        notes.append(f"{n} {direction}: split off {c_number(c)} {direction}")
    # Trove kept the number but a broken bracket before it hid the clue's
    # start: "sat (6, 4> , , 6. Rumour", "'1^7). 16 Eminent", the number one
    # the list lacks.
    k = 0
    while k < len(out):
        c = out[k]
        lo = min(c["tokens"][0] or {99})
        hi = min(out[k + 1]["tokens"][0] or {99}) if k + 1 < len(out) else 99
        for m in re.finditer(rf"(?:\([^()a-zA-Z]{{0,12}}|[\d)>\]}}][).,]*)\s({ftp.NUM})[.,]?\s+(?=[A-Z])", c["text"]):
            ns = {n for n in ftp.readings(m.group(1)) if lo < n < hi
                  and not any(n in o["tokens"][0] for o in out)}
            if len(ns) == 1 and c["see"] is None:
                n = ns.pop()
                split(out, k, m.end(), c["text"][:m.start(1)].rstrip(), set(), n)
                notes.append(f"{n} {direction}: split off {c_number(c)} {direction} at Trove's own number")
                break
        k += 1


def split(out, k, cut, before, enums, n):
    """Clue k becomes `before` (with `enums`) and clue n from `cut` on."""
    c = out[k]
    out[k:k + 1] = [dict(c, text=before, enums=enums),
                    {"tokens": [{n}], "text": c["text"][cut:].strip(),
                     "enums": c["enums"], "see": None}]


def c_number(c):
    return "/".join(map(str, sorted(c["tokens"][0]))) or "?"


def fix_enum(direction, parsed, stream, s_letters, s_idx, notes):
    """Step 2: an enumeration Trove lost or left ambiguous."""
    import file_trove_puzzles as ftp
    out = parsed[direction]
    for i, c in enumerate(out):
        if c["see"] is not None or len(c["enums"]) == 1:
            continue
        text = c["text"]
        broken = re.search(r"\s*[(\[{]([^()a-zA-Z]{0,12})$", text)
        loose = None
        kept = re.sub(r"\D", "", broken.group(1)) if broken else ""
        bare = text[:broken.start()] if broken else text
        # What is left of a bracket Trove broke: "warmth 0).", "nian'1^7).".
        junk = re.search(r"[^A-Za-z?!]*\d[^A-Za-z?!]*$", bare)
        if junk and not broken:
            loose = re.sub(r"\D", "", junk.group(0))
            bare = bare[:junk.start()]
        c_letters, _ = letters(bare)
        end = slide(s_letters, c_letters[::-1][:ANCHOR + SLIDE], 0, backward=True)
        if end is None or end > len(s_idx):
            continue
        start = s_idx[end - 1] + 1
        nxt_at = end if end < len(s_idx) else None
        end = min(s_idx[nxt_at] if nxt_at is not None else len(stream), start + TAIL)
        seg = stream[start:end]
        nxt = out[i + 1]["tokens"][0] if i + 1 < len(out) else {1}
        enum = tail_enum(seg, nxt)
        if enum is None:
            continue
        if c["enums"] and enum not in c["enums"]:
            continue
        if kept and re.sub(r"\D", "", enum) != kept:
            continue
        # Without its "(" a bracket's ")" reads as 1 and "(" as 0: the other
        # digits must be the count's.
        if loose and loose.strip("01") and re.sub(r"\D", "", enum) not in loose:
            continue
        if len(c["tokens"]) == 1 and ftp.count(enum) > 15:
            continue
        # RapidOCR reads a small hyphen as a period, so a count in parts
        # settles the light's length but is not printed with the clue.
        out[i] = dict(c, text=bare.rstrip(), enums={enum}, count_only=not enum.isdigit())
        notes.append(f"{c_number(c)} {direction}: enumeration ({enum}), Trove read "
                     f"{sorted(c['enums']) or repr(text[-12:])}")


def fix_number(direction, parsed, stream, s_letters, s_idx, notes):
    """Step 3: a clue number read several ways."""
    out = parsed[direction]
    for i, c in enumerate(out):
        if len(c["tokens"][0]) == 1:
            continue
        c_letters, _ = letters(c["text"])
        pos = find_once(s_letters, c_letters[:ANCHOR])
        if len(c_letters) < ANCHOR or pos is None:
            continue
        m = re.search(r"(?<!\d)(\d{1,2})\s*[.,]?\s*$", stream[max(0, s_idx[pos] - 8):s_idx[pos]])
        if m and int(m.group(1)) in c["tokens"][0]:
            out[i] = dict(c, tokens=[{int(m.group(1))}] + c["tokens"][1:])
            notes.append(f"{int(m.group(1))} {direction}: number, Trove read {sorted(c['tokens'][0])}")


def repair(parsed, stream):
    """(the parsed lists with what RapidOCR's `stream` settles, [what changed])."""
    parsed = {d: [dict(c) for c in v] for d, v in parsed.items()}
    s_letters, s_idx = letters(stream)
    notes = []
    for direction in parsed:
        fix_number(direction, parsed, stream, s_letters, s_idx, notes)
        split_lost(direction, parsed, stream, s_letters, s_idx, notes)
        fix_enum(direction, parsed, stream, s_letters, s_idx, notes)
    return parsed, notes


def complete(parsed):
    """Whether a clue list pins every number and count down: each clue one
    number and (unless a "See") one enumeration, each list increasing, and
    together the two lists number 1..N without a gap."""
    for v in parsed.values():
        prev = 0
        for c in v:
            if len(c["tokens"][0]) != 1 or (c["see"] is None and len(c["enums"]) != 1):
                return False
            n = next(iter(c["tokens"][0]))
            if n <= prev:
                return False
            prev = n
    nums = numbers(parsed)
    return bool(nums) and nums == set(range(1, max(nums) + 1))


def repaired(d, parsed, zones=ZONES):
    """repair() for article directory `d` when its zones are cached and the
    list is not already complete; else (parsed, [])."""
    if complete(parsed) or not (zone_images(d.name, zones) or (zones / d.name / "rapidocr.txt").exists()):
        return parsed, []
    return repair(parsed, stream(d.name, zones))


def stream(aid, zones=ZONES):
    """read_text() of article `aid`'s cached zones, itself cached beside them."""
    path = zones / str(aid) / "rapidocr.txt"
    if not path.exists():
        path.write_text(read_text(zone_images(aid, zones)), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def main(argv=None):
    import file_trove_puzzles as ftp
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", nargs="+", metavar="ID")
    ap.add_argument("--show", metavar="ID")
    ap.add_argument("--fetch-pending", type=int, metavar="N",
                    help="cache the zones of up to N articles the filer left pending")
    args = ap.parse_args(argv)
    if args.fetch_pending is not None:
        _, failed, _ = fetch_pending(args.fetch_pending)
        return 1 if failed else 0
    trove = None
    for aid in args.fetch or ():
        trove = fetch(aid, trove=trove)
        print(aid, len(zone_images(aid)), "zones")
    if args.show:
        d = CACHE / args.show
        secs = ftp.sections((d / "ocr.txt").read_text(encoding="utf-8", errors="replace"))
        parsed = {k: ftp.clues(v)[0] for k, v in secs.items()}
        text = stream(args.show)
        fixed, notes = repair(parsed, text)
        print(text)
        print("\n".join(notes) or "no change", "| complete:", complete(parsed), "->", complete(fixed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
