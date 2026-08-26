#!/usr/bin/env python3
"""Fetch a Guardian crossword and convert it to this app's puzzle format.

Usage:
  python3 tools/fetch_puzzle.py 30066            # fetch by number, any series
  python3 tools/fetch_puzzle.py --latest         # newest of EVERY series (see GUARDIAN_SERIES)
  python3 tools/fetch_puzzle.py --backfill [N] [series]
                                                 # fetch the last N puzzles (default 30)
                                                 # of one series (default cryptic) ending at
                                                 # the newest; skips ones already on disk and
                                                 # 404s; ~1s delay per request
  python3 tools/fetch_puzzle.py --reindex        # rebuild puzzles/index.json + index.js
                                                 # from the puzzle files already on disk
  python3 tools/fetch_puzzle.py --refresh-unsolved  # re-fetch puzzles still missing
                                                 # solutions (Saturday prize puzzles
                                                 # publish theirs about a week late)

Covers weekday cryptics, Saturday prize crosswords (one number sequence, two
URLs — six a week), the Monday Quiptic (the Guardian's beginner tier) and the
Sunday Everyman from the Observer. Each of the three runs its own number
sequence. See GUARDIAN_SERIES below.

Writes puzzles/<series>-<number>.js (preserving any existing per-clue
annotations), then rebuilds puzzles/index.json and puzzles/index.js. Commands
that take a puzzle still accept the bare number while it names only one.

Exit status for --latest: 0 and prints the puzzle number if a NEW puzzle was
downloaded, prints "up-to-date <n>" and exits 3 if nothing new was found.
"""

import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import series as series_meta  # noqa: E402 — what each series IS; see tools/series.py

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"
UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; personal educational use)"}
# The three series this fetcher can reach, each with its own number sequence and
# its own Guardian series page. What each series IS — publisher, display name,
# how gentle — lives in tools/series.py, because the SEO builder and the backfill
# need it too and the Independent (tools/fetch_independent.py) is not fetched
# from here at all.
#
# cryptic — the daily, Monday–Saturday (nothing on Sunday). Saturday's is the
#   PRIZE crossword: same number sequence, different URL. Looking only at
#   /cryptic/ silently loses one puzzle in six — 30044, 30050, 30056… were all
#   missing here until "prize" was added. Prize solutions are withheld for about
#   a week, so a freshly-fetched prize puzzle has hasSolutions=false until
#   --refresh-unsolved picks it up again later.
# quiptic — the Guardian's beginner tier, Mondays, "for beginners and those in a
#   hurry". Added 2026-08-01 (Paul: "are there any easier puzzles, I'm finding
#   the guardian ones pretty hard"). Same page shape, same converter, solutions
#   published same-day.
# everyman — the Observer's Sunday cryptic, syndicated onto the Guardian site and
#   free like the rest. Added 2026-08-05, when Paul asked whether we could scrape
#   the Times. We can't: the Times never sends the grid to a signed-out browser
#   at all, so there is nothing to parse without a Puzzles subscription (probed
#   with a headless browser — the page fires no puzzle request whatsoever, it
#   just renders the subscribe wall). Everyman is the closest free stand-in and
#   arguably the better one for this site: it is the gentlest broadsheet cryptic
#   in print, deliberately fair, and it fills Sunday — the one day the Guardian
#   cryptic doesn't publish, so it adds a puzzle rather than competing for a slot.
#
# Every series counts upward from its own 1, so the number alone names a puzzle
# only by luck of the ranges — and the luck runs out. Ids are namespaced by
# series (series.puzzle_id) for that reason, so nothing here has to reason about
# which sequences happen to be far apart today. Numbers are still what gets
# DISPLAYED, and a bare one is still accepted on the command line while it names
# only one puzzle (resolve_puzzle).
GUARDIAN_SERIES = {
    "cryptic": {
        "label": "Cryptic",
        "index": ["https://www.theguardian.com/crosswords/series/cryptic",
                  "https://www.theguardian.com/crosswords/series/prize"],
        "link_re": r"/crosswords/(?:cryptic|prize)/(\d+)",
    },
    "quiptic": {
        "label": "Quiptic",
        "index": ["https://www.theguardian.com/crosswords/series/quiptic"],
        "link_re": r"/crosswords/quiptic/(\d+)",
    },
    "everyman": {
        "label": "Everyman",
        "index": ["https://www.theguardian.com/crosswords/series/everyman"],
        "link_re": r"/crosswords/everyman/(\d+)",
        # The Guardian ships no creator for these; the fallback byline is in
        # tools/series.py, along with the reason there isn't one.
    },
}
# Tried in order for a bare number; the first that isn't a 404 wins.
PUZZLE_URLS = [
    "https://www.theguardian.com/crosswords/cryptic/{num}",
    "https://www.theguardian.com/crosswords/prize/{num}",
    "https://www.theguardian.com/crosswords/quiptic/{num}",
    "https://www.theguardian.com/crosswords/everyman/{num}",
]

JSON_START = "/*JSON-START*/"
JSON_END = "/*JSON-END*/"


def http_get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
ITALIC_TAGS = {"i", "em"}


def flatten_clue(s):
    """HTML clue text -> (plain text, italic ranges into that text).

    Both papers ship clues as HTML: an italicised title arrives as
    "<span>Case for </span><i>Turandot</i><span> lyrics…</span>". Storing that
    markup was tried and is wrong — the app escapes puzzle text, so the solver
    read the tags (Paul, on the Independent, 2026-08-15) — but so is throwing
    it away, because the italics are part of the clue: "<i>Times</i>
    desperately stifling question" is telling you the newspaper, not the plural
    of time.

    So the clue stays ONE plain string and the italics travel beside it as
    [start, length] ranges. The string has to stay plain because every
    annotation fragment is found in it with indexOf and highlighted by
    character offset; a tag in the middle would move every offset after it.
    Ranges are just a second list over the same offsets, so the two agree by
    construction, and app.js can cut the clue at the boundaries of both.

    The flatten runs character by character rather than as a regex sub so that
    unescaping entities and collapsing runs of whitespace — both of which
    change the length — carry the italic flags along with the characters they
    belong to.
    """
    # Nothing to flatten, so nothing is touched. Collapsing whitespace in a
    # clue that never had markup would edit the paper's own text — the
    # Independent really does print "Unsuitable pix?  I need ten developed" —
    # and worse, silently move every annotation offset in a file that had no
    # problem to fix.
    if "<" not in s and "&" not in s:
        return s, []

    chars, depth, pos = [], 0, 0
    for m in TAG_RE.finditer(s):
        chars.extend((c, depth > 0) for c in html.unescape(s[pos:m.start()]))
        if m.group(2).lower() in ITALIC_TAGS:
            depth = max(0, depth + (-1 if m.group(1) else 1))
        pos = m.end()
    chars.extend((c, depth > 0) for c in html.unescape(s[pos:]))

    out = []
    for c, italic in chars:
        if not c.isspace():
            out.append((c, italic))
        elif out and not out[-1][0].isspace():
            out.append((" ", italic))
    while out and out[-1][0].isspace():
        out.pop()

    ranges, start = [], None
    for i, (_, italic) in enumerate(out):
        if italic and start is None:
            start = i
        elif not italic and start is not None:
            ranges.append([start, i - start])
            start = None
    if start is not None:
        ranges.append([start, len(out) - start])
    return "".join(c for c, _ in out), ranges


def plain_text(s):
    """The text half of flatten_clue, for the strings that have no ranges to
    keep — annotation fragments, definitions, walkthroughs. Defined in terms of
    flatten_clue so the two can never disagree about where a character lands."""
    return flatten_clue(s)[0] if isinstance(s, str) else s


def extract_crossword_data(page_html):
    m = re.search(r'<gu-island name="CrosswordComponent"[^>]*props="([^"]*)"', page_html)
    if not m:
        raise SystemExit("Could not find CrosswordComponent data in page")
    return json.loads(html.unescape(m.group(1)))["data"]


def puzzle_path(series, number):
    """The one place a puzzle's file name is spelled. Every other module asks
    here, so the day the id format changes again it changes once."""
    return PUZZLE_DIR / f"{series_meta.puzzle_id(series, number)}.js"


def puzzle_files():
    """Every puzzle file and nothing else in puzzles/ — not index.js, not the
    static answer pages. Matched off the id shape, so adding a series needs no
    change here."""
    return sorted(PUZZLE_DIR.glob("*-[0-9]*.js"))


def resolve_puzzle(arg):
    """A puzzle file from either a namespaced id ("everyman-4165") or the bare
    number a person types ("4165").

    Bare numbers are what every URL, prompt and habit used before namespacing,
    so they keep working — but only while one names exactly one puzzle. An
    ambiguous number is an error naming both candidates, never a guess: guessing
    would annotate one paper's grid from another paper's clues.
    """
    # Everything puzzle-shaped, not just what the nightly sweep walks: an
    # authored draft (puzzles/A001.js) is deliberately outside puzzle_files(),
    # and naming one by hand is exactly how it gets validated.
    files = [p for p in sorted(PUZZLE_DIR.glob("*.js")) if p.stem != "index"]
    exact = [p for p in files if p.stem == str(arg)]
    if exact:
        return exact[0]
    hits = [p for p in files if p.stem.rpartition("-")[2] == str(arg)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"no puzzle {arg} in {PUZZLE_DIR}")
    raise SystemExit(f"{arg} names more than one puzzle — say which: "
                     + ", ".join(p.stem for p in hits))


def read_puzzle_file(path):
    """Parse the JSON payload out of a puzzles/<n>.js file."""
    text = path.read_text(encoding="utf-8")
    try:
        payload = text.split(JSON_START, 1)[1].rsplit(JSON_END, 1)[0]
    except IndexError:
        raise SystemExit(f"{path}: missing {JSON_START}/{JSON_END} markers")
    return json.loads(payload)


def write_puzzle_file(path, puzzle, generator="tools/fetch_puzzle.py"):
    # The file is named by the id, and the id carries the series, so two papers
    # that reach the same number cannot land on the same file — the collision is
    # impossible rather than guarded against. This assert is the one thing left
    # that could break that: a caller writing a puzzle to a path it did not get
    # from puzzle_path().
    assert path.name == f"{puzzle['id']}.js", (
        f"{path.name} does not match id {puzzle['id']} — use puzzle_path()")
    payload = json.dumps(puzzle, indent=1, ensure_ascii=False)
    text = (
        f"// Generated by {generator} — puzzle © its original publisher.\n"
        "// Annotations (type/definition/indicators/blocks/walkthrough) are original\n"
        "// to this project. Edit the annotation objects freely; keep the JSON markers.\n"
        'window.CRYPTIC_PUZZLES = window.CRYPTIC_PUZZLES || {};\n'
        f'window.CRYPTIC_PUZZLES["{puzzle["id"]}"] = {JSON_START} {payload} {JSON_END};\n'
    )
    path.write_text(text, encoding="utf-8")


def series_of(page_id):
    """Which GUARDIAN_SERIES a puzzle belongs to, read off the page's own id
    ("crosswords/quiptic/1393") rather than off whichever URL happened to answer,
    so a re-fetch through a different route can never relabel a puzzle.

    Unrecognised means cryptic, and that is a fact rather than a guess: the
    cryptic is the only series with two URLs, because Saturday's PRIZE crossword
    shares its number sequence and its page id says "crosswords/prize/30074".
    Everything else lives under its own name. Written as a scan over GUARDIAN_SERIES so
    that adding a series is one dict entry and no branch anywhere needs finding.
    """
    for name in GUARDIAN_SERIES:
        if f"/{name}/" in "/" + page_id:
            return name
    return "cryptic"


def convert(data):
    """Guardian data -> our puzzle object (annotation: null on every entry)."""
    entries = []
    for e in sorted(data["entries"], key=lambda e: (e["position"]["y"], e["position"]["x"], e["direction"])):
        clue, italics = flatten_clue(e["clue"])
        entries.append({
            "id": e["id"],
            "number": e["number"],
            "direction": e["direction"],
            "position": e["position"],
            "length": e["length"],
            "clue": clue,
            # Omitted rather than written empty: most clues have no italics and
            # a [] on every entry is 84 files of noise.
            **({"clueItalics": italics} if italics else {}),
            "group": e["group"],
            "separatorLocations": e.get("separatorLocations") or {},
            "solution": e.get("solution"),
            "annotation": None,
        })
    series = series_of(data["id"])
    return {
        "id": series_meta.puzzle_id(series, data["number"]),
        "number": data["number"],
        "series": series,
        "name": data["name"],
        "setter": ((data.get("creator") or {}).get("name")
                   or series_meta.default_setter(series)),
        "date": data.get("date"),
        "dimensions": data["dimensions"],
        "sourceUrl": "https://www.theguardian.com/" + data["id"],
        "entries": entries,
    }


def merge_annotations(new_puzzle, old_puzzle):
    """Carry our own work across a re-fetch: annotations always, and a model's
    solved grid until the paper publishes its own.

    A prize puzzle can be solved here before its answers are out (see
    tools/apply_solution.py), and refresh_unsolved re-fetches it every night
    until they are. Without the carryover each of those nightly re-fetches
    would wipe the fill and the annotations written off it; with it, the day
    the official key appears it simply replaces the model's, the unofficial
    marker comes off, and the differences get printed — which is the only
    grading of a blind solve that ever happens automatically."""
    old = {e["id"]: e.get("annotation") for e in old_puzzle.get("entries", [])}
    for e in new_puzzle["entries"]:
        if old.get(e["id"]) is not None:
            e["annotation"] = old[e["id"]]

    was_model = (old_puzzle.get("solutionSource") or {}).get("kind") == "model"
    if not was_model:
        return None
    official = all(e.get("solution") for e in new_puzzle["entries"])
    guessed = {e["id"]: e.get("solution") for e in old_puzzle.get("entries", [])}
    if not official:
        # Paper still silent — keep the fill and stay flagged.
        for e in new_puzzle["entries"]:
            if not e.get("solution") and guessed.get(e["id"]):
                e["solution"] = guessed[e["id"]]
        new_puzzle["solutionSource"] = old_puzzle["solutionSource"]
        return None
    wrong = [(e["id"], guessed.get(e["id"]), e["solution"])
             for e in new_puzzle["entries"] if guessed.get(e["id"]) != e["solution"]]
    # An annotation explains how the clue yields the answer, so an annotation
    # written off a wrong answer is wrong all the way through — definition,
    # blocks, walkthrough. Drop it and let the queue write it again against
    # the real answer, rather than leaving a confident explanation of a word
    # that was never the answer.
    missed = {eid for eid, _, _ in wrong}
    for e in new_puzzle["entries"]:
        if e["id"] in missed:
            e["annotation"] = None
    return wrong


def puzzle_is_annotated(puzzle):
    return all(e.get("annotation") is not None for e in puzzle["entries"])


def reindex():
    # Difficulty needs every puzzle at once (each rating is relative to the
    # others), so it is scored in one pass here rather than per-file. It is
    # optional on purpose: tools/difficulty.py leans on the gitignored lexicon,
    # and a clone that hasn't fetched it should still get a working index.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from difficulty import all_scores
        ratings = all_scores()
    except Exception as err:  # noqa: BLE001 — never let this break the index
        print(f"difficulty scoring skipped: {err}")
        ratings = {}

    puzzles = []
    for path in puzzle_files():
        p = read_puzzle_file(path)
        rating = ratings.get(p["id"])
        puzzles.append({
            "id": p["id"],
            "number": p["number"],
            # Absent on every file written before quiptics existed, and every one
            # of those is a cryptic — so default rather than forcing a re-fetch
            # of 36 puzzles to add one string.
            "series": p.get("series", "cryptic"),
            "name": p["name"],
            "setter": p["setter"],
            "date": p.get("date"),
            "file": path.name,
            # content hash → app.js appends it as ?v= so browsers never serve a
            # stale puzzle after a re-annotation (see APP.md, cache busting)
            "v": hashlib.md5(path.read_bytes()).hexdigest()[:8],
            "annotated": puzzle_is_annotated(p),
            "hasSolutions": all(e.get("solution") for e in p["entries"]),
            # True where the grid was solved here rather than published by the
            # paper. The site says so wherever it shows those answers: a learner
            # checking their grid is entitled to know whose answer they lost to.
            "solutionsUnofficial": bool(p.get("solutionSource")),
            # Absent for puzzles with too little to go on — an unrated puzzle
            # shows no badge rather than a made-up one.
            "difficulty": rating and {
                "band": rating["band"],
                "index": rating["index"],
                "percentile": rating["percentile"],
                "basis": rating["basis"],
            },
        })
    # Newest first BY DATE, not by number. With one series those agreed; with
    # three they don't — quiptic 1,393 and cryptic 30,073 came out the same week,
    # and sorting on the number would bury every quiptic below every cryptic
    # forever. Ties (a Monday publishes both) put the cryptic first, so the daily
    # cryptic stays the puzzle the site opens on.
    puzzles.sort(key=lambda p: (p.get("date") or 0, p["series"] == "cryptic", p["number"]),
                 reverse=True)
    index = {"latest": puzzles[0]["id"] if puzzles else None, "puzzles": puzzles}
    (PUZZLE_DIR / "index.json").write_text(
        json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (PUZZLE_DIR / "index.js").write_text(
        "// Generated by tools/fetch_puzzle.py from index.json — do not edit by hand.\n"
        f"window.CRYPTIC_INDEX = {JSON_START} "
        + json.dumps(index, indent=1, ensure_ascii=False)
        + f" {JSON_END};\n",
        encoding="utf-8")
    return index


def fetch_page(num):
    """Get a puzzle page by number, trying each series URL (cryptic, then prize)."""
    last = None
    for url in PUZZLE_URLS:
        try:
            return http_get(url.format(num=num))
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            last = err
    raise last


def fetch_number(num):
    data = extract_crossword_data(fetch_page(num))
    puzzle = convert(data)
    path = PUZZLE_DIR / f"{puzzle['id']}.js"
    is_new = not path.exists()
    graded = None
    if not is_new:
        graded = merge_annotations(puzzle, read_puzzle_file(path))
    write_puzzle_file(path, puzzle)
    reindex()
    print(("fetched " if is_new else "refreshed ") + puzzle["id"])
    if graded is not None:
        total = len(puzzle["entries"])
        print(f"BLIND SOLVE GRADED {puzzle['id']}: {total - len(graded)}/{total} correct "
              f"against the published answers")
        for eid, mine, theirs in graded:
            print(f"  miss {eid}: model said {mine}, answer is {theirs}")
    return puzzle, is_new


def backfill(count, series="cryptic"):
    """Fetch the last `count` puzzles of one series ending at the newest,
    skipping ones we already have. Guardian numbers are sequential within a
    series; some may be missing (404) — skip those gracefully. Polite ~1s delay
    between requests."""
    latest = find_latest_number(series)
    fetched, skipped, missing = 0, 0, 0
    for num in range(latest, latest - count, -1):
        path = puzzle_path(series, num)
        if path.exists():
            skipped += 1
            continue
        try:
            fetch_number(num)
            fetched += 1
        except urllib.error.HTTPError as err:
            print(f"skip {num}: HTTP {err.code}")
            missing += 1
        except Exception as err:  # malformed page etc. — keep going
            print(f"skip {num}: {err}")
            missing += 1
        time.sleep(1)
    reindex()
    print(f"backfill done: {fetched} fetched, {skipped} already present, {missing} unavailable")


def refresh_unsolved():
    """Re-fetch on-disk puzzles whose solutions weren't published yet.

    Saturday prize puzzles arrive without solutions and only get them about a
    week later; without this pass they would sit un-annotatable forever, since
    the daily job only annotates puzzles where hasSolutions is true.
    A puzzle we solved ourselves counts as unsolved here. It has a full grid of
    letters, so the "any entry missing a solution" test walks straight past it —
    and walking past it is exactly the failure worth avoiding, because it would
    mean the one puzzle whose answers are a guess is the one puzzle we stop
    checking. It stays on this list until the paper publishes and the merge can
    grade the guess.

    Annotations are preserved by fetch_number's merge."""
    pending = []
    for path in puzzle_files():
        p = read_puzzle_file(path)
        if not all(e.get("solution") for e in p["entries"]) or p.get("solutionSource"):
            pending.append(p["number"])
    filled = 0
    for num in pending:
        try:
            puzzle, _ = fetch_number(num)
            # A carried-over model fill fills every entry too, so "has letters
            # everywhere" is not the test — "the paper said so" is.
            if all(e.get("solution") for e in puzzle["entries"]) and not puzzle.get("solutionSource"):
                print(f"solutions now published for {num}")
                filled += 1
            elif puzzle.get("solutionSource"):
                print(f"{num}: solutions still withheld — keeping our own fill")
            else:
                print(f"{num}: solutions still withheld")
        except Exception as err:
            print(f"refresh {num} failed: {err}")
        time.sleep(1)
    if pending:
        reindex()
    print(f"refresh-unsolved: {filled}/{len(pending)} puzzle(s) gained solutions")


def find_latest_number(series="cryptic"):
    spec = GUARDIAN_SERIES[series]
    nums = []
    for url in spec["index"]:
        try:
            page = http_get(url)
        except Exception as err:
            print(f"series {url} unavailable: {err}")
            continue
        nums += [int(n) for n in re.findall(spec["link_re"], page)]
    if not nums:
        raise SystemExit(f"No {series} puzzle links found on series pages")
    return max(nums)


def main(argv):
    PUZZLE_DIR.mkdir(exist_ok=True)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--reindex":
        index = reindex()
        print(f"indexed {len(index['puzzles'])} puzzle(s); latest = {index['latest']}")
        return 0
    if argv[0] == "--refresh-unsolved":
        refresh_unsolved()
        return 0
    if argv[0] == "--backfill":
        count = int(argv[1]) if len(argv) > 1 else 30
        series = argv[2] if len(argv) > 2 else "cryptic"
        if series not in GUARDIAN_SERIES:
            raise SystemExit(f"Unknown series {series!r}; try {'/'.join(GUARDIAN_SERIES)}")
        backfill(count, series)
        return 0
    if argv[0] == "--latest":
        # Every series, not just the cryptic. A per-series loop rather than one
        # max() because the sequences are unrelated: 30,073 is not "newer" than
        # 1,393, and taking the larger would mean the quiptic never downloads.
        # One series being down doesn't stop the others.
        got, up_to_date = [], []
        for series in GUARDIAN_SERIES:
            try:
                num = find_latest_number(series)
            except SystemExit as err:
                print(err)
                continue
            if puzzle_path(series, num).exists():
                up_to_date.append(f"{series} {num}")
                continue
            try:
                fetch_number(num)
                got.append(str(num))
            except Exception as err:
                print(f"{series} {num} failed: {err}")
        if up_to_date and not got:
            print("up-to-date " + ", ".join(up_to_date))
            return 3
        if not got:
            return 1
        print(" ".join(got))
        return 0
    m = re.search(r"(\d{3,})", argv[0])
    if not m:
        raise SystemExit(f"Don't understand argument: {argv[0]}")
    fetch_number(int(m.group(1)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
