#!/usr/bin/env python3
"""Fetch an Observer Everyman crossword and convert it to this app's format.

Usage:
  python3 tools/fetch_observer.py --latest             # newest not already on disk
  python3 tools/fetch_observer.py --number N           # one puzzle by number
  python3 tools/fetch_observer.py --backfill [N]       # last N puzzles ending at the
                                                        # newest (default 30), skipping
                                                        # ones already on disk and 404s
  python3 tools/fetch_observer.py --extend [N]         # N puzzles OLDER than the oldest
                                                        # on disk, stopping at EARLIEST
  python3 tools/fetch_observer.py --refresh-unsolved   # fill in solutions for puzzles
                                                        # whose answers have since posted

Companion to fetch_puzzle.py (Guardian) and fetch_independent.py, run
independently in tools/daily_update.sh step 1 so the Observer being down never
costs the other two — same reasoning as the comment above that loop. Series is
"everyman" — the Guardian mirrored it under that name until no. 4096
(2025-04-20); the Observer was sold to Tortoise Media that month and
everything from 4097 on only exists at observer.co.uk.

A backfill gets no special treatment from the annotation queue: its puzzles
sort in by date with everything else and get worked newest to oldest, which
is the order somebody would want them in anyway (Paul, 2026-08-16). The
nightly job's own rate limit is what keeps a big import from being a big
bill.

WHERE THIS CAME FROM (2026-08-16). The Everyman article page
(observer.co.uk/puzzles/everyman/article/everyman-no-N) renders the grid
client-side and shows a "Subscribe" banner, which looks like a dead end. It
isn't one: the page's own hydration payload names the puzzle by a UUID
({"type":"puzzle","uuid":"..."}), and that UUID resolves at a completely
separate, unauthenticated host — content-api.slowdownwiseup.co.uk, the mobile
app's backend (CORS *, no cookies, no auth header, verified across puzzles
spanning May 2025 to the present day). The Piano paywall governs the article
text around the puzzle; it never touches this API.

That API serves a manifest (puzzle-data/<uuid>/) listing files, one of which
is data.json: a flat rows x cols `grid` (block/number/word-id per cell) plus
`copy.words` (word id -> 1-based x or y span, "2-7" or "7") and `copy.clues`
(one block titled "Across", one "Down", each clue keyed to a word id, with its
own `format` enumeration like Guardian/Independent's "5,2,3,5"). No number was
ever seen shared by two clues — every clue maps to exactly one word — so,
unlike the Guardian and the Independent, there is no "group" of more than one
entry to build here; every entry's group is itself.

SOLUTIONS LAG ABOUT A WEEK, behind the competition window (see `competition`
in data.json — a "closes" date near a week after publish, for the reader-
prize draw the article's small print describes). Until then, a puzzle's own
`copy.settings.solution_hashed` is a hash, not letters. Once the window
closes, the SAME field set on the SAME puzzle's data.json grows a sibling,
`copy.settings.solution` — a plain rows*cols-character row-major grid, spaces
for blocked cells, verified against the puzzle's own block layout cell for
cell. So refresh_unsolved() re-fetches puzzle N itself, not N+1: an earlier
version of this fetcher read a `previous_solution` field instead, on the
theory that a puzzle's answers only ever appeared on the FOLLOWING week's
page — which briefly seemed to hold, then broke on 4135 and 4140, where that
field was null despite `solution` sitting right there unhashed. See
fetch_puzzle.py's refresh_unsolved for the same SHAPE of problem even though
the mechanism differs (there it's the Saturday prize withholding a week; here
it's every single week).

Writes puzzles/<number>.js (preserving any existing per-clue annotations),
same file format and same fetch_puzzle.reindex() as every other fetcher here.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, UA, flatten_clue, merge_annotations,  # noqa: E402
                          puzzle_files, puzzle_path,
                          read_puzzle_file, reindex, write_puzzle_file)
from fetch_independent import span  # noqa: E402 — same 1-based "2-7"/"7" span format
                                     # for a different paper's crossword
import series as series_meta  # noqa: E402

ARTICLE_URL = "https://observer.co.uk/puzzles/everyman/article/everyman-no-{num}"
TOPICS_URL = "https://observer.co.uk/topics/everyman"
# The oldest everyman anyone still serves. 4096 and below were the Guardian's
# mirror, which 404s since the Observer moved to Tortoise Media, so the archive
# has a hard floor and walking below it only buys 404s. The handful we hold
# under this number were downloaded before the mirror went.
EARLIEST = 4097
API_BASE = "https://content-api.slowdownwiseup.co.uk"

# The article's own hydration payload double-escapes its embedded JSON (it's a
# JSON string sitting inside a JS string sitting inside the HTML), so the
# literal bytes on the wire have a backslash before every quote. Matched
# literally rather than unescaped-then-parsed because the payload around it is
# not valid JSON on its own — it's one clause of a much larger React Server
# Component tree — so there is nothing to hand json.loads() short of
# reimplementing Next.js's RSC framing for one field.
UUID_RE = re.compile(r'\\"type\\":\\"puzzle\\",\\"uuid\\":\\"([0-9a-f-]{36})\\"')
TOPIC_LINK_RE = re.compile(r"/puzzles/everyman/article/everyman-no-(\d+)")


def http_get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


def http_get_json(url):
    return json.loads(http_get(url))


def article_uuid(num):
    """The puzzle's UUID, scraped out of its (public, unauthenticated) article
    page. Raises urllib.error.HTTPError with code 404 for a number that has
    never been published, the same signal every other fetcher here uses."""
    page = http_get(ARTICLE_URL.format(num=num))
    m = UUID_RE.search(page)
    if not m:
        raise ValueError(f"everyman-no-{num}: no puzzle UUID found in the article page "
                          f"— the page layout may have changed")
    return m.group(1)


def puzzle_manifest(uuid):
    return http_get_json(f"{API_BASE}/api/mobile/v1/puzzle-data/{uuid}/")


def puzzle_data(manifest):
    """The data.json a manifest lists, fetched at the path the manifest itself
    gives rather than a guessed one — the manifest is what the API says its
    own layout is, and trusting it survives that layout changing under us.
    The listed paths are relative to /api/mobile/v1 (e.g.
    "/puzzle-data/<uuid>/file/data.json"), same as the manifest URL itself,
    even though they render as absolute-from-root paths inside a browser
    that's already sitting under that prefix; a bare API_BASE join 404s."""
    path = manifest["files"].get("data.json")
    if not path:
        raise ValueError(f"puzzle-data/{manifest.get('uuid')}: manifest lists no data.json")
    return http_get_json(f"{API_BASE}/api/mobile/v1{path}")


def entry_cells(entry):
    """The (x, y) cells an entry covers, recomputed from the fields already
    stored on it rather than carried separately — position + direction +
    length determine the run completely, so a second copy of the same fact
    would only be one more place for it to drift out of sync."""
    x, y = entry["position"]["x"], entry["position"]["y"]
    n = entry["length"]
    if entry["direction"] == "across":
        return [(x + i, y) for i in range(n)]
    return [(x, y + i) for i in range(n)]


SEPARATOR_RE = re.compile(r"([,\-'])")


def clue_separators(fmt, length):
    """Guardian-style separatorLocations from an Observer enumeration like
    "4,1'5" (WINE O'CLOCK) or "3-5,6": where the answer breaks for a space,
    hyphen or apostrophe, keyed by which mark it is. Not fetch_independent's
    separators() — that one exists to split a single enumeration ACROSS two
    linked grid entries, which Everyman never does (see the module docstring:
    every clue here maps to exactly one word), so it's simpler to total the
    boundaries within this one entry directly than to call that function
    through a one-entry list. It also doesn't know the apostrophe is a
    separator at all: fed "1'5" it tries to int() that whole piece and dies,
    which is what happened on 4126 and 4140 (G'DAY, WINE O'CLOCK) before this
    existed."""
    out = {}
    pos = 0
    for piece in SEPARATOR_RE.split(fmt or ""):
        if piece in (",", "-", "'"):
            if 0 < pos < length:
                out.setdefault(piece, []).append(pos)
        elif piece:
            pos += int(piece)
    return out


def convert(num, manifest, data):
    """Observer data.json -> our puzzle object (solution/annotation blank —
    solutions arrive a week later; see refresh_unsolved). Raises loudly on any
    mismatch between what the clue list claims and what the grid itself says,
    rather than writing a puzzle whose geometry might be transposed or off by
    one: a wrong grid looks exactly like a right one until a solver hits it."""
    if str(manifest.get("number")) != str(num):
        raise ValueError(f"everyman-no-{num}: manifest says number "
                          f"{manifest.get('number')!r}")
    if str(data.get("meta", {}).get("number")) != str(num):
        raise ValueError(f"everyman-no-{num}: data.json says number "
                          f"{data.get('meta', {}).get('number')!r}")

    grid = data["grid"]
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if any(len(row) != cols for row in grid):
        raise ValueError(f"everyman-no-{num}: grid rows are not all {cols} cells wide")

    words = {w["id"]: w for w in data["copy"]["words"]}
    entries = []
    for group in data["copy"]["clues"]:
        direction = {"Across": "across", "Down": "down"}.get(group.get("title"))
        if direction is None:
            raise ValueError(f"everyman-no-{num}: unrecognised clue group "
                              f"{group.get('title')!r}")
        for c in group["clues"]:
            word = words.get(c["word"])
            if word is None:
                raise ValueError(f"everyman-no-{num}: clue {c['number']} ({direction}) "
                                  f"references word {c['word']}, not in copy.words")
            length = c["length"]
            x1, x2 = span(word["x"])
            y1, y2 = span(word["y"])
            if direction == "across":
                if y1 != y2 or x2 - x1 + 1 != length:
                    raise ValueError(f"everyman-no-{num}: clue {c['number']} across, word "
                                      f"{word['id']} spans x={word['x']!r} y={word['y']!r}, "
                                      f"which is not a single {length}-cell row")
                pos = {"x": x1 - 1, "y": y1 - 1}
            else:
                if x1 != x2 or y2 - y1 + 1 != length:
                    raise ValueError(f"everyman-no-{num}: clue {c['number']} down, word "
                                      f"{word['id']} spans x={word['x']!r} y={word['y']!r}, "
                                      f"which is not a single {length}-cell column")
                pos = {"x": x1 - 1, "y": y1 - 1}

            eid = f"{c['number']}-{direction}"
            entry = {"position": pos, "length": length, "direction": direction}
            cells = entry_cells(entry)
            for (x, y) in cells:
                if not (0 <= x < cols and 0 <= y < rows):
                    raise ValueError(f"everyman-no-{num}: clue {c['number']} {direction} "
                                      f"reaches cell ({x},{y}), outside the {cols}x{rows} grid")
                if grid[y][x]["Blank"] == "blank":
                    raise ValueError(f"everyman-no-{num}: clue {c['number']} {direction} "
                                      f"claims cell ({x},{y}), which the grid marks blank")
            start = grid[cells[0][1]][cells[0][0]]
            if str(start["Number"]) != str(c["number"]):
                raise ValueError(f"everyman-no-{num}: clue {c['number']} {direction} starts "
                                  f"at grid cell numbered {start['Number']!r} instead — "
                                  f"the grid and the clue list disagree on where it begins")

            text, italics = flatten_clue(c["clue"])
            fmt = c.get("format") or str(length)
            entries.append({
                "id": eid,
                "number": c["number"],
                "direction": direction,
                "position": pos,
                "length": length,
                "clue": f"{text} ({fmt})",
                **({"clueItalics": italics} if italics else {}),
                "group": [eid],
                "separatorLocations": clue_separators(fmt, length),
                "solution": None,
                "annotation": None,
            })

    entries.sort(key=lambda e: (e["position"]["y"], e["position"]["x"], e["direction"]))
    when = datetime.fromisoformat(manifest["date"].replace("Z", "+00:00"))
    puzzle = {
        "id": series_meta.puzzle_id("everyman", num),
        "number": num,
        "series": "everyman",
        "name": f"Everyman crossword No {num:,}",
        "setter": data["copy"].get("setter") or series_meta.default_setter("everyman"),
        "date": int(when.timestamp() * 1000),
        "dimensions": {"cols": cols, "rows": rows},
        "sourceUrl": ARTICLE_URL.format(num=num),
        "entries": entries,
    }
    return puzzle


def fill_solutions(entries, solution, rows, cols, num):
    """Slice `entries`' solutions out of a flat row-major solution string —
    `copy.settings.solution` off this puzzle's own data.json (see
    refresh_unsolved). Raises loudly rather than writing a partial or
    contradictory grid: a length mismatch or a crossing disagreement means
    the slicing doesn't line up with the layout this puzzle's own entries
    were built from, and a silently-wrong fill is worse than staying unsolved
    another week."""
    if len(solution) != rows * cols:
        raise ValueError(f"everyman-no-{num}: solution is "
                          f"{len(solution)} chars, expected {rows}x{cols}="
                          f"{rows * cols}")
    cell_letters = {}
    for entry in entries:
        cells = entry_cells(entry)
        letters = "".join(solution[y * cols + x] for x, y in cells)
        if len(letters) != entry["length"]:
            raise ValueError(f"everyman-no-{num}: {entry['id']} sliced to "
                              f"{len(letters)} letters {letters!r}, wanted "
                              f"{entry['length']}")
        if not letters.isalpha():
            raise ValueError(f"everyman-no-{num}: {entry['id']} sliced to {letters!r} — "
                              f"a blocked or empty cell inside a live entry")
        for (x, y), ch in zip(cells, letters.upper()):
            prior = cell_letters.get((x, y))
            if prior is not None and prior != ch:
                raise ValueError(f"everyman-no-{num}: cell ({x},{y}) disagrees between "
                                  f"crossing entries — {prior!r} then {entry['id']} says "
                                  f"{ch!r}")
            cell_letters[(x, y)] = ch
        entry["solution"] = letters.upper()


def fetch_number(num):
    uuid = article_uuid(num)
    manifest = puzzle_manifest(uuid)
    data = puzzle_data(manifest)
    puzzle = convert(num, manifest, data)
    path = PUZZLE_DIR / f"{puzzle['id']}.js"
    is_new = not path.exists()
    if not is_new:
        old = read_puzzle_file(path)
        merge_annotations(puzzle, old)
    write_puzzle_file(path, puzzle, generator="tools/fetch_observer.py")
    print(("fetched " if is_new else "refreshed ") + puzzle["id"])
    return puzzle


def find_latest_number():
    page = http_get(TOPICS_URL)
    nums = [int(n) for n in TOPIC_LINK_RE.findall(page)]
    if not nums:
        raise SystemExit("No everyman puzzle links found on the topics page")
    return max(nums)


def latest():
    """The newest number the topics page lists, if we don't already have it.
    Returns the puzzle, or None for "nothing new" — exit 3, the same contract
    fetch_puzzle.py and fetch_independent.py both use so daily_update.sh can
    tell a quiet week from a broken feed without reading any output."""
    newest = find_latest_number()
    if puzzle_path("everyman", newest).exists():
        print(f"up-to-date {newest}")
        return None
    return fetch_number(newest)


def walk(numbers, what="backfill"):
    """Fetch each number in turn, skipping what's on disk and what 404s.
    Returns how many arrived."""
    fetched = skipped = missing = 0
    for num in numbers:
        path = puzzle_path("everyman", num)
        if path.exists():
            skipped += 1
            continue
        try:
            fetch_number(num)
            fetched += 1
        except urllib.error.HTTPError as err:
            print(f"skip {num}: HTTP {err.code}")
            missing += 1
        except Exception as err:  # noqa: BLE001 — one bad puzzle shouldn't stop the run
            print(f"skip {num}: {err}")
            missing += 1
        time.sleep(1)
    reindex()
    print(f"{what} done: {fetched} fetched, {skipped} already present, {missing} unavailable")
    return fetched


def backfill(count=30):
    """Fetch the last `count` puzzles ending at the newest, skipping ones
    already on disk."""
    newest = find_latest_number()
    return walk(range(newest, newest - count, -1))


def extend(count=30):
    """Fetch `count` puzzles OLDER than the oldest everyman on disk.

    Stops at EARLIEST rather than walking into the Guardian's dead mirror. Every
    number below it 404s at both publishers, and a walk that discovers that one
    polite second at a time would burn a minute of the run to learn nothing.
    """
    have = sorted(int(p.stem[len("everyman-"):]) for p in puzzle_files()
                  if p.stem.startswith("everyman-")
                  and p.stem[len("everyman-"):].isdigit())
    oldest = min(have) if have else find_latest_number() + 1
    if oldest <= EARLIEST:
        print(f"extend done: everyman starts at {EARLIEST}; nothing older exists")
        return 0
    return walk(range(oldest - 1, max(oldest - 1 - count, EARLIEST - 1), -1), "extend")


def refresh_unsolved():
    """Re-derive solutions for on-disk Everyman puzzles that don't have them
    yet, by re-fetching each one's OWN data.json (see module docstring — a
    puzzle's `copy.settings.solution` sits behind `solution_hashed` until its
    competition window closes, about a week after publish, then the plain
    letters appear right there). `previous_solution` — the field this used to
    read, on the theory that a puzzle's answers only ever showed up on the
    FOLLOWING week's page — turned out to be an unreliable secondary field,
    null on plenty of pages that already have their own `solution` filled in
    (4135, 4140, both discovered this way on the initial backfill). Reading
    the puzzle's own field instead needs no such theory: it just asks the one
    page that would know, and a puzzle stays pending here only as long as
    THAT field itself stays hashed."""
    pending = []
    for path in puzzle_files():
        p = read_puzzle_file(path)
        if p.get("series") == "everyman" and not all(e.get("solution") for e in p["entries"]):
            pending.append(p["number"])
    filled = 0
    for num in pending:
        uuid = article_uuid(num)
        manifest = puzzle_manifest(uuid)
        data = puzzle_data(manifest)
        solution = data["copy"]["settings"].get("solution")
        if not solution:
            print(f"{num}: still within its competition window — solutions still withheld")
            time.sleep(1)
            continue
        path = puzzle_path("everyman", num)
        puzzle = read_puzzle_file(path)
        fill_solutions(puzzle["entries"], solution,
                        puzzle["dimensions"]["rows"], puzzle["dimensions"]["cols"], num)
        write_puzzle_file(path, puzzle, generator="tools/fetch_observer.py")
        print(f"solutions now published for {num}")
        filled += 1
        time.sleep(1)
    if pending:
        reindex()
    print(f"refresh-unsolved: {filled}/{len(pending)} puzzle(s) gained solutions")


def main(argv):
    PUZZLE_DIR.mkdir(exist_ok=True)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--refresh-unsolved":
        refresh_unsolved()
        return 0
    if argv[0] == "--backfill":
        backfill(int(argv[1]) if len(argv) > 1 else 30)
        return 0
    if argv[0] == "--extend":
        extend(int(argv[1]) if len(argv) > 1 else 30)
        return 0
    if argv[0] == "--latest":
        puzzle = latest()
        if not puzzle:
            return 3
        reindex()
        print(puzzle["id"])
        return 0
    if argv[0] == "--number":
        if len(argv) < 2 or not argv[1].isdigit():
            raise SystemExit("--number needs a puzzle number, e.g. --number 4097")
        if fetch_number(int(argv[1])):
            reindex()
        return 0
    raise SystemExit(f"Don't understand argument: {argv[0]}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
