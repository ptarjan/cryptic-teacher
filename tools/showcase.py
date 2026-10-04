"""The puzzles /showcase/ picks out, and why: facts read off each file, never a guess.

build_seo_pages.puzzle_page_job() calls facts() on every listed, solved puzzle as
it renders that puzzle's page, so the showcase costs no second pass over the
corpus; sections() then picks each section's puzzles from all of them.

Only puzzles with our hints are shown: a reader who opens a pick to solve it
gets help. wanted() names the unhinted puzzles a section would show, and the
pre-reset burn (tools/prereset_plan.py) annotates those first.

Every section is a fact the file or the index states. A message hidden in the
grid counts only when the note above the clues says where to look: any edge
spells something if you hunt for words in it (see tools/puzzle_tags.py), so a
grid search would fill the section with accidents.
"""

import re

import parallel
import puzzle_tags
import series as series_meta

# A note above the clues that tells the solver words are hidden in the grid
# itself, and where. Every preamble in the corpus that matches was read and
# says so; the jigsaw one (cryptic-21963) puts the compass points on the edge.
MESSAGE = re.compile(
    r"(?:round|around) (?:the )?(?:perimeter|edge|shaded squares)"
    r"|perimeter[^.]{0,60}(?:clockwise|spell|reads?\b)|perimeter letters spell"
    r"|in the diagonals|displays [^.]* on the perimeter|\(see perimeter\)",
    re.IGNORECASE)

# A note that says the answers go wherever they fit: the clues carry no grid
# numbers. Every match in the corpus was read and says exactly that.
JIGSAW = re.compile(r"jigsaw-wise|wherever they will go", re.IGNORECASE)

# Grid words for the n of an n-fold pangram, from tools/puzzle_tags.py.
PANGRAM_TIMES = {f"{word}-pangram": i + 2
                 for i, (word, _) in enumerate(puzzle_tags.MULTIPLES)}
WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}

PER_SECTION = 6


def enumeration_letters(enum):
    return sum(int(n) for n in re.findall(r"\d+", enum or ""))


def longest_answer(puz):
    """(letters, lights) of the puzzle's longest answer, a linked one counted
    whole across every light it runs through, or None. Only an answer whose
    printed count adds up to the squares it fills: a count that disagrees
    is a filing slip, not a record."""
    ents = puz["entries"]
    by_id = {puzzle_tags.entry_id(e): e for e in ents}
    cont = puzzle_tags.continuations(ents)
    best = None
    for e in ents:
        eid = puzzle_tags.entry_id(e)
        if eid in cont:
            continue
        lights = [by_id[g] for g in e.get("group") or [eid] if g in by_id]
        letters = sum(x["length"] for x in lights)
        if enumeration_letters(e["clue"].get("enumeration")) != letters:
            continue
        if best is None or letters > best[0]:
            best = (letters, len(lights))
    return best


def facts(puz, meta):
    """What the showcase needs to know about one puzzle, small enough to
    send back from a worker. `meta` is its index row."""
    ents = puz["entries"]
    cont = puzzle_tags.continuations(ents)
    tags = puzzle_tags.tags(puz)
    preamble = puz.get("preamble", "")
    day = series_meta.puzzle_day(puz)
    series = puz.get("series") or "cryptic"
    diff = (meta or {}).get("difficulty") or {}
    return {
        "id": puz["id"], "series": series, "number": puz["number"],
        "day": day.toordinal() if day else None,
        # A book puzzle's year is the book's, not the day the paper printed it.
        "dated": "date" in puz,
        "answers": sum(1 for e in ents if puzzle_tags.entry_id(e) not in cont
                       and not e["clue"].get("missing")),
        "longest": longest_answer(puz),
        "tags": tags,
        "message": bool(MESSAGE.search(preamble)),
        "jigsaw": bool(JIGSAW.search(preamble)),
        "difficulty": diff.get("index") if diff.get("band") else None,
        "annotated": bool((meta or {}).get("annotated")),
        # A round issue number means something only where the number counts
        # issues: not a date (Metro), not a book's volume * 1000 + position.
        "counted": not (series_meta.is_book(series)
                        or series_meta.number_date(series, puz["number"])),
    }


def newest_first(f):
    return -(f["day"] or 0)


def pick(cands, key, used, per_series=None, n=PER_SECTION):
    """The first n of cands by key that no earlier section showed, at most
    per_series from any one series."""
    out, count = [], {}
    for f in sorted(cands, key=key):
        if f["id"] in used or count.get(f["series"], 0) >= (per_series or n):
            continue
        out.append(f)
        count[f["series"]] = count.get(f["series"], 0) + 1
        if len(out) == n:
            break
    used.update(f["id"] for f in out)
    return out


def pangram_times(f):
    return max((PANGRAM_TIMES[t] for t in f["tags"] if t in PANGRAM_TIMES), default=1)


def sections(all_facts, hinted=True):
    """[(slug, heading, blurb, [(fact dict, card note)])], in page order. A
    puzzle shows once, in the first section that wants it; with hinted, only
    the puzzles we have annotated are candidates."""
    used = set()
    fs = [f for f in all_facts if f["annotated"] or not hinted]
    out = []

    def add(slug, heading, blurb, picked, note):
        if picked:
            out.append((slug, heading, blurb, [(f, note(f)) for f in picked]))

    add("hidden-message", "A message hidden in the grid",
        "Words run round the edge of the finished grid, along a diagonal or through "
        "marked squares, and the note above the clues says where to look.",
        pick([f for f in fs if f["message"]], newest_first, used, per_series=3),
        lambda f: "hidden message")
    add("jigsaw", "Answers that go wherever they fit",
        "Some or all of the clues come without grid numbers. You solve them, then "
        "work out where each answer goes, like a jigsaw.",
        pick([f for f in fs if f["jigsaw"]], newest_first, used),
        lambda f: "jigsaw")
    add("alphabet", "One answer for every letter",
        "Twenty-six answers, and each starts with a different letter of the alphabet.",
        pick([f for f in fs if "alphabetical" in f["tags"] and f["answers"] == 26],
             newest_first, used),
        lambda f: "A to Z")
    add("pangrams", "Every letter, again and again",
        "Every letter of the alphabet, Q, X and Z included, appears at least three "
        "times in the finished grid.",
        pick([f for f in fs if pangram_times(f) >= 3],
             lambda f: (-pangram_times(f), newest_first(f)), used),
        lambda f: f"every letter {WORDS[pangram_times(f)]} times or more")
    add("asymmetric", "Grids that are not symmetrical",
        "Nearly every published grid looks the same turned upside down. These do not.",
        pick([f for f in fs if "asymmetric" in f["tags"]], newest_first, used,
             per_series=2),
        lambda f: "not symmetrical")
    add("barred", "Bars instead of black squares",
        "Thick lines between squares end the answers, so almost every letter is "
        "shared by two answers.",
        pick([f for f in fs if "barred" in f["tags"]], newest_first, used, per_series=3),
        lambda f: "barred grid")
    add("longest", "The longest answers",
        "A single answer, often a whole quotation, that snakes through several parts "
        "of the grid.",
        pick([f for f in fs if f["longest"] and f["longest"][1] > 1],
             lambda f: (-f["longest"][0], newest_first(f)), used),
        lambda f: f"{f['longest'][0]} letters in {f['longest'][1]} parts")
    add("most-clues", "The most clues",
        "The puzzles with the most clues, no two from the same series.",
        pick(fs, lambda f: (-f["answers"], newest_first(f)), used, per_series=1),
        lambda f: f"{f['answers']} clues")
    add("hardest", "The hardest",
        "The puzzles our difficulty rating puts at the top, no two from the same "
        "series.",
        pick([f for f in fs if f["difficulty"] is not None],
             lambda f: (-f["difficulty"], newest_first(f)), used, per_series=1),
        lambda f: "")
    add("round-numbers", "Round numbers",
        "Milestone issues, numbered in round thousands.",
        pick([f for f in fs if f["counted"] and f["number"] >= 1000
              and f["number"] % 1000 == 0], newest_first, used, per_series=1),
        lambda f: "")
    add("oldest", "The oldest",
        "The earliest puzzles in the archive.",
        pick([f for f in fs if f["dated"]], lambda f: f["day"], used, per_series=3),
        lambda f: "")
    return out


def wanted(all_facts):
    """Ids of the unannotated puzzles the showcase would pick if it took any
    puzzle: what annotating first would put on the page."""
    return [f["id"] for _, _, _, cards in sections(all_facts, hinted=False)
            for f, _ in cards if not f["annotated"]]


_META = {}


def _file_facts(path):
    from fetch_puzzle import read_puzzle_file
    puz = read_puzzle_file(path)
    row = _META.get(puz["id"])
    if row is None or not row.get("hasSolutions"):
        return None
    return facts(puz, row)


def corpus_facts(index):
    """facts() for every listed puzzle with all its answers (the index's
    hasSolutions), which build_seo_pages gathers as it renders their pages."""
    from puzzle_paths import puzzle_files
    global _META
    _META = {p["id"]: p for p in index["puzzles"]}
    try:
        return [f for f in parallel.pmap(_file_facts, puzzle_files()) if f]
    finally:
        _META = {}
