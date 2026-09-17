#!/usr/bin/env python3
"""Fetch The Globe and Mail's daily cryptic and convert it to this app's format.

Usage:
  python3 tools/fetch_globeandmail.py 20260917            # one date, YYYYMMDD
  python3 tools/fetch_globeandmail.py 20260910 20260917   # a date range, inclusive
  python3 tools/fetch_globeandmail.py --extend [N]        # N days OLDER than the
                                                           # oldest globeandmail-*
                                                           # puzzle already on disk
                                                           # (default 14)
  python3 tools/fetch_globeandmail.py --list              # print the dates the
                                                           # vendor's own picker
                                                           # currently advertises
  --dry-run     print what would be fetched/written, write nothing
  --out DIR     write .js files here instead of puzzles/ (also skips reindex(),
                since reindex() always scans the real puzzles/ dir)

Companion to fetch_puzzle.py (Guardian) and fetch_independent.py (Independent);
no code is shared with either beyond http_bytes/write_puzzle_file/reindex, because
nothing else is shared: this is a different vendor with a different payload shape.

WHERE THIS CAME FROM. The Globe and Mail's cryptic is hosted by Amuse Labs /
PuzzleMe, set "globeandmail-new-cryptic". Two endpoints matter:

  https://cdn-us.amuselabs.com/pmm/date-picker?set=globeandmail-new-cryptic
      HTML containing `"puzzleId":"globeandmail-new-cryptic_YYYYMMDD"` entries —
      about fourteen of them, roughly the last two weeks. That is the only
      listing endpoint found; depth beyond it is unknown, so --list only reports
      what the picker currently advertises and everything else (a single date, a
      range, --extend) just tries the URL directly regardless of whether --list
      would have mentioned it.

  https://cdn-us.amuselabs.com/pmm/crossword?id={puzzleId}&set=globeandmail-new-cryptic&embed=1
      HTML containing `"rawc":"<obfuscated>"`. Amuse never sends the grid in the
      clear; it ships a base64 blob whose bytes have been shuffled by a
      short repeating key, and the key itself is not sent — only the picker's
      own JS knows it, derived at runtime. DECODE below re-derives it by brute
      force (see its docstring) rather than executing that JS. This is the same
      scheme xword-dl's amuselabs source already reverse-engineered; the
      implementation here is a independent port kept local, not an xword-dl
      dependency, so this tool has no new import.

THE GRID IS COLUMN-MAJOR. The decoded JSON's `box` field is indexed box[x][y]
— outer index is the COLUMN, inner is the ROW — not the row-major [y][x] every
other shape in this repo uses. Confirmed against the sample: placedWords
"SEANCE" sits at x=0,y=1 going across (direction "E"), and box[0][1], box[1][1],
box[2][1]... spell S,E,A,N,C,E, while box[1] read as a whole row spells an
unrelated down word (REALLIFE, which sits at x=1). Get this backwards and every
solution comes out as some other entry's letters — it will look plausible
(real English strings) and be wrong. solution_letters() below is the one place
this is read; nothing else should index box directly.

ENUMERATIONS ARE DATA, NOT TEXT. Amuse gives `wordLens`, an int array, never a
rendered "(6)" or "(4,4)" in the clue text itself (checked: no clue in the
sample sample payload ends in anything parenthesised). This tool always
appends the rendered form, and only skips appending if the clue text already
ends in one — belt and braces, in case some other day's clue already carries
it. A multi-element wordLens (a "REAL LIFE"-style answer spanning contiguous
boxes) becomes a comma-separated enumeration and a comma separatorLocations
entry, exactly like a Guardian/Independent multi-word answer — Amuse gives no
signal that would ever justify a hyphen instead, so hyphens are never emitted.

NUMBERING. Amuse's `title` field is not a date artifact, it is the paper's own
sequence number: "No 3368" for 2026-09-17. That is exactly the kind of number
Guardian/Independent puzzles already use for `number`/`id`, so it is used
here too rather than deriving a number from the date — it is monotonic (the
paper prints six of these a week and counts up by one each time), and it is
the number a reader of the actual paper would recognise. `date` is taken from
the payload's own `publishTime` (epoch ms), not reconstructed from the YYYYMMDD
used to fetch — checked against the sample: 1789617600000 is exactly midnight
America/New_York on 2026-09-17, i.e. the vendor's own timestamp already agrees
with the URL date, so there is no reason to recompute it and every reason to
prefer the field the paper actually stamped.

If `title` is ever NOT "No <digits>" this raises rather than guessing a
number — matching fetch_independent.py's title parsing, and for the same
reason: a wrong number silently overwrites the wrong file or reorders the
archive, so an unrecognised format needs a human, not a fallback.

PACING. One request per second, max, with a browser-ish User-Agent (reusing
fetch_puzzle.UA) — this is somebody else's CDN and getting banned would take
the puzzle away from every future run, not just this one.

Writes puzzles/<series>-<number>.js (preserving any existing per-clue
annotations, same as the other two fetchers), then rebuilds the index via
fetch_puzzle.reindex() — unless --out points somewhere other than the real
puzzles/ dir, in which case reindex() is skipped, because it always rebuilds
the index from puzzles/ itself regardless of where files were just written.
"""

import base64
import json
import re
import sys
import time
import urllib.error
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, http_bytes, merge_annotations,  # noqa: E402
                          puzzle_files, read_puzzle_file, reindex,
                          write_puzzle_file)
import series as series_meta  # noqa: E402

SET = "globeandmail-new-cryptic"
DATE_PICKER_URL = f"https://cdn-us.amuselabs.com/pmm/date-picker?set={SET}"
PUZZLE_URL = f"https://cdn-us.amuselabs.com/pmm/crossword?id={{puzzle_id}}&set={SET}&embed=1"
PLAY_URL = "https://www.theglobeandmail.com/puzzles-and-crosswords/new-cryptic/?date={ymd}"
REQUEST_GAP = 1.0  # seconds between requests — see PACING above


# ---------- decode (ported from a working brute-force key search; see module
# docstring for where it came from) ----------

def is_valid_key_prefix(rawc, key_prefix, spacing):
    try:
        pos = 0
        chunk = []
        while pos < len(rawc):
            start_pos = pos
            key_index = 0
            while key_index < len(key_prefix) and pos < len(rawc):
                chunk_length = min(key_prefix[key_index], len(rawc) - pos)
                chunk.append(rawc[pos: pos + chunk_length][::-1])
                pos += chunk_length
                key_index += 1
            chunk_str = "".join(chunk)
            base64_start = ((start_pos + 3) // 4) * 4 - start_pos
            base64_end = (pos // 4) * 4 - start_pos
            if base64_start >= len(chunk_str) or base64_end <= base64_start:
                chunk.clear()
                pos += spacing
                continue
            b64_chunk = chunk_str[base64_start:base64_end]
            try:
                decoded = base64.b64decode(b64_chunk)
            except Exception:
                return False
            for byte in decoded:
                if (byte < 32 and byte not in (0x09, 0x0A, 0x0D)) or byte in (0xC0, 0xC1) or byte >= 0xF5:
                    return False
            pos += spacing
            chunk.clear()
        return True
    except Exception:
        return False


def deobfuscate_rawc_with_key(rawc, key):
    try:
        buffer = list(rawc)
        i = 0
        segment_count = 0
        while i < len(buffer) - 1:
            segment_length = min(key[segment_count % len(key)], len(buffer) - i)
            segment_count += 1
            left, right = i, i + segment_length - 1
            while left < right:
                buffer[left], buffer[right] = buffer[right], buffer[left]
                left += 1
                right -= 1
            i += segment_length
        decoded_bytes = base64.b64decode("".join(buffer))
        return decoded_bytes.decode("utf-8")
    except Exception:
        return ""


def deobfuscate_rawc(rawc):
    """Brute-force the 7-element chunk-length key by BFS, one digit (2-20) at a
    time, validating each prefix by reversing rawc in chunks of those lengths
    and checking every 4-byte-aligned base64 slice decodes to valid UTF-8.
    Runs in well under a second."""
    ye_pos = rawc.find("ye")
    we_pos = rawc.find("we")
    ye_pos = ye_pos if ye_pos != -1 else len(rawc)
    we_pos = we_pos if we_pos != -1 else len(rawc)
    first_key_digit = min(ye_pos, we_pos) + 2

    candidate_queue = deque([[first_key_digit]] if first_key_digit <= 20 else [[]])
    while candidate_queue:
        candidate_key_prefix = candidate_queue.popleft()
        if len(candidate_key_prefix) == 7:
            deobfuscated = deobfuscate_rawc_with_key(rawc, candidate_key_prefix)
            try:
                json.loads(deobfuscated)
                return deobfuscated
            except (json.JSONDecodeError, ValueError):
                continue
        for next_digit in range(2, 21):
            new_candidate = candidate_key_prefix + [next_digit]
            remaining_digits = 7 - len(new_candidate)
            min_spacing, max_spacing = 2 * remaining_digits, 20 * remaining_digits
            if any(is_valid_key_prefix(rawc, new_candidate, spacing)
                   for spacing in range(min_spacing, max_spacing + 1)):
                candidate_queue.append(new_candidate)
    raise ValueError("could not recover the rawc obfuscation key")


RAWC_RE = re.compile(r'rawc"\s*:\s*"(.*?)"')


def fetch_raw_json(puzzle_id):
    html = http_bytes(PUZZLE_URL.format(puzzle_id=puzzle_id)).decode("utf-8", errors="replace")
    m = RAWC_RE.search(html)
    if not m:
        raise ValueError(f"no rawc field found for {puzzle_id} — page shape changed?")
    rawc = json.loads('"' + m.group(1) + '"')  # unescape JSON string escapes (\/ etc)
    return json.loads(deobfuscate_rawc(rawc))


# ---------- mapping onto our puzzle shape ----------

TITLE_RE = re.compile(r"No\.?\s*([\d,]+)\s*$")
ENUM_TAIL_RE = re.compile(r"\([\d,\-.\s]+\)\s*$")


def solution_letters(box, cells):
    """box is indexed box[x][y] — see the COLUMN-MAJOR note in the module
    docstring — so this is the one place that ordering is allowed to matter."""
    return "".join(box[x][y] for x, y in cells).upper()


def setter_name(author):
    """The byline without the syndication notice.

    Amuse ships the author as "Hurley (©News Licensing/Times Media Limited)" —
    the puzzle is a Times syndication. The rights holder is not the setter, and
    a solver looking for another Hurley puzzle needs the name alone.
    """
    if not author:
        return "Unknown"
    name = re.sub(r"\s*\([^)]*(?:©|Licensing|Limited|Ltd)[^)]*\)", "", author).strip()
    return name or "Unknown"


def convert(data, ymd):
    m = TITLE_RE.search((data.get("title") or "").strip())
    if not m:
        raise ValueError(f"unrecognised title {data.get('title')!r} for {ymd}")
    number = int(m.group(1).replace(",", ""))

    box = data["box"]
    entries = []
    for pw in data["placedWords"]:
        across = bool(pw["acrossNotDown"])
        direction = "across" if across else "down"
        x0, y0, length = pw["x"], pw["y"], pw["nBoxes"]
        cells = [(x0 + i, y0) for i in range(length)] if across else [(x0, y0 + i) for i in range(length)]
        word_lens = pw["wordLens"]
        enum = "(" + ",".join(str(n) for n in word_lens) + ")"
        clue_text = pw["clue"]["clue"].strip()
        full_clue = clue_text if ENUM_TAIL_RE.search(clue_text) else f"{clue_text} {enum}"
        seps = {}
        if len(word_lens) > 1:
            cum, locs = 0, []
            for n in word_lens[:-1]:
                cum += n
                locs.append(cum)
            seps = {",": locs}
        num = int(pw["clueNum"])
        entries.append({
            "id": f"{num}-{direction}",
            "number": num,
            "direction": direction,
            "position": {"x": x0, "y": y0},
            "length": length,
            "clue": full_clue,
            "separatorLocations": seps,
            "solution": solution_letters(box, cells),
            "annotation": None,
        })
    entries.sort(key=lambda e: (e["position"]["y"], e["position"]["x"], e["direction"]))

    publish_time = data.get("publishTime")
    when_ms = int(publish_time) if publish_time else int(
        datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    return {
        "id": series_meta.puzzle_id("globeandmail", number),
        "number": number,
        "series": "globeandmail",
        "name": f"Globe and Mail cryptic crossword No {number:,}",
        "setter": setter_name(data.get("author")),
        "date": when_ms,
        "dimensions": {"cols": data["w"], "rows": data["h"]},
        "sourceUrl": PLAY_URL.format(ymd=ymd),
        "entries": entries,
    }


# ---------- fetch / list / write ----------

def list_available_dates():
    """The dates the vendor's own date-picker currently advertises, newest
    first. Not a hard boundary — --extend and explicit dates try dates this
    never mentions — just what's on offer right now (about two weeks)."""
    html = http_bytes(DATE_PICKER_URL).decode("utf-8", errors="replace")
    dates = sorted(set(re.findall(rf'"puzzleId"\s*:\s*"{re.escape(SET)}_(\d{{8}})"', html)), reverse=True)
    return dates


def fetch_date(ymd, out_dir, dry_run=False):
    puzzle_id = f"{SET}_{ymd}"
    data = fetch_raw_json(puzzle_id)
    puzzle = convert(data, ymd)
    path = out_dir / f"{puzzle['id']}.js"
    if dry_run:
        print(f"[dry-run] would write {path} ({puzzle['name']}, {len(puzzle['entries'])} entries)")
        return puzzle
    is_new = not path.exists()
    if not is_new:
        merge_annotations(puzzle, read_puzzle_file(path))
    write_puzzle_file(path, puzzle, generator="tools/fetch_globeandmail.py")
    print(("fetched " if is_new else "refreshed ") + f"{puzzle['id']} ({ymd})")
    return puzzle


def days_between(start, end):
    """Inclusive, newest first, in the "YYYYMMDD string" shape used everywhere
    else here."""
    lo, hi = min(start, end), max(start, end)
    n = (hi - lo).days
    return [(hi - timedelta(days=i)).strftime("%Y%m%d") for i in range(n + 1)]


def oldest_held():
    stamps = [p["date"] for p in (read_puzzle_file(f) for f in puzzle_files())
              if p["id"].startswith("globeandmail-")]
    if not stamps:
        return None
    return datetime.fromtimestamp(min(stamps) / 1000, timezone.utc).date()


def run_dates(ymds, out_dir, dry_run):
    fetched = missing = 0
    for i, ymd in enumerate(ymds):
        if i:
            time.sleep(REQUEST_GAP)
        try:
            fetch_date(ymd, out_dir, dry_run)
            fetched += 1
        except urllib.error.HTTPError as err:
            print(f"skip {ymd}: HTTP {err.code}")
            missing += 1
        except Exception as err:  # noqa: BLE001 — one bad day shouldn't stop the run
            print(f"skip {ymd}: {err}")
            missing += 1
    if not dry_run and out_dir == PUZZLE_DIR:
        reindex()
    print(f"done: {fetched} fetched, {missing} unavailable/failed")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    out_dir = PUZZLE_DIR
    if "--out" in argv:
        i = argv.index("--out")
        out_dir = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    out_dir.mkdir(parents=True, exist_ok=True)

    if argv[0] == "--list":
        for ymd in list_available_dates():
            print(ymd)
        return 0

    if argv[0] == "--extend":
        n = int(argv[1]) if len(argv) > 1 else 14
        held = oldest_held()
        end = (held - timedelta(days=1)) if held else date.today()
        ymds = [(end - timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]
        run_dates(ymds, out_dir, dry_run)
        return 0

    # 2026-09-17 and 20260917 both mean the same day. The vendor's ids are the
    # undashed form and everything downstream uses it, so normalise here rather
    # than making the caller know which one this particular tool wants.
    argv = [a.replace("-", "") for a in argv]
    for a in argv:
        if not re.fullmatch(r"\d{8}", a):
            raise SystemExit(f"Expected a YYYY-MM-DD date, got: {a}")
    if len(argv) == 1:
        ymds = [argv[0]]
    elif len(argv) == 2:
        ymds = days_between(datetime.strptime(argv[0], "%Y%m%d").date(),
                             datetime.strptime(argv[1], "%Y%m%d").date())
    else:
        raise SystemExit("Expected one date, two dates (a range), --extend, or --list")
    run_dates(ymds, out_dir, dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
