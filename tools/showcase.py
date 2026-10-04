"""The puzzles /showcase/ picks out, and why: facts read off each file, never a guess.

build_seo_pages.puzzle_page_job() calls facts() on every listed, solved puzzle as
it renders that puzzle's page, so the showcase costs no second pass over the
corpus; sections() then picks each section's puzzles from all of them.

Only puzzles with our hints are shown: a reader who opens a pick to solve it
gets help. wanted() names the unhinted puzzles a section would show, and the
pre-reset burn (tools/prereset_plan.py) annotates those first.

Every section is a fact the file or the index states. A feature section is
one of tools/puzzle_tags.py's TAGS, with that tag's label for its heading, its
blurb, and the puzzles the tag is on, so /showcase/ and the app's feature
filter name and pick the same features. The rest are rankings, which no filter
offers.
"""

import re

import parallel
import puzzle_tags
import series as series_meta

# Top-level features (no `implies`) /showcase/ gives no section, each with why.
# A tag that implies another shows in that one's section, by its own label.
NOT_SHOWCASED = {}

# At most this many puzzles of one series in a feature's section on /showcase/.
FEATURE_PER_SERIES = {"hidden-message": 3, "asymmetric": 2, "barred": 3, "big-grid": 2,
                      "unclued": 3, "letters-given": 3, "special-rules": 3}

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
        # big-grid compares the puzzle with its series, so only the index has it.
        "tags": [k for k in puzzle_tags.TAGS if k in tags
                 or (k == "big-grid" and k in (meta or {}).get("tags", ()))],
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


def oldest_per_paper(fs):
    """The earliest dated puzzle of each publisher, oldest first."""
    best = {}
    for f in fs:
        if not f["dated"] or f["day"] is None:
            continue
        paper = series_meta.publisher(f["series"])
        if paper not in best or (f["day"], f["id"]) < (best[paper]["day"], best[paper]["id"]):
            best[paper] = f
    return sorted(best.values(), key=lambda f: (f["day"], f["id"]))


def features():
    """The top-level tags /showcase/ gives a section, in TAGS order."""
    return [t for t, info in puzzle_tags.TAGS.items()
            if "implies" not in info and t not in NOT_SHOWCASED]


def feature_spec(fs, tag):
    """A feature's section: the puzzles with the tag, a stronger one first
    (the most repeats of a pangram), each noting its own tag's label."""
    variants = [k for k, info in puzzle_tags.TAGS.items() if k == tag or info.get("implies") == tag]

    def own(f):
        return next(k for k in f["tags"] if k in variants)
    key = (lambda f: (variants.index(own(f)), newest_first(f))) if len(variants) > 1 else newest_first
    info = puzzle_tags.TAGS[tag]
    return (tag, info["label"][0].upper() + info["label"][1:], info["blurb"],
            [f for f in fs if puzzle_tags.has_tag(f["tags"], tag)], key,
            lambda f: puzzle_tags.TAGS[own(f)]["label"], FEATURE_PER_SERIES.get(tag))


# Each list as (slug, heading, blurb, which puzzles, ranking, card note,
# per_series): the rankings, every feature, then the round numbers.
# /showcase/ shows the first PER_SECTION of each, a puzzle once
# and at most per_series from one series; its own page /showcase/<slug>/
# lists every candidate in the same order: all of them, or the top FULL of a
# ranking (a key other than newest_first), which can run to thousands. A
# per_series of 1 lets a ranking that one series dominates show several papers.
def specs(fs):
    return [
        ("longest", "The longest answers",
         ("A single answer, often a whole quotation, that snakes through several parts "
          "of the grid."),
         [f for f in fs if f["longest"] and f["longest"][1] > 1],
         lambda f: (-f["longest"][0], newest_first(f)),
         lambda f: f"{f['longest'][0]} letters in {f['longest'][1]} parts", None),
        ("hardest", "The hardest",
         "The puzzles our difficulty rating puts at the top.",
         [f for f in fs if f["difficulty"] is not None],
         lambda f: (-f["difficulty"], newest_first(f)), lambda f: "", 1),
        ("easiest", "The easiest",
         "The puzzles our difficulty rating puts at the bottom: a good place to start.",
         [f for f in fs if f["difficulty"] is not None],
         lambda f: (f["difficulty"], newest_first(f)), lambda f: "", 1),
        ("most-clues", "The most clues", "The puzzles with the most clues.",
         fs, lambda f: (-f["answers"], newest_first(f)),
         lambda f: f"{f['answers']} clues", 1),
        *(feature_spec(fs, t) for t in features()),
        ("round-numbers", "Round numbers", "Milestone issues, numbered in round thousands.",
         [f for f in fs if f["counted"] and f["number"] >= 1000
          and f["number"] % 1000 == 0], newest_first, lambda f: "", 1),
    ]


FULL = 100

ONE_PER_SERIES = " Here, no two from the same series."


def sections(all_facts, hinted=True):
    """[(slug, heading, blurb, [(fact dict, card note)], full)] in page order,
    full being (blurb, cards, "all 21" or "top 100") for /showcase/<slug>/, or
    None where the section already shows everything it has. A puzzle
    shows once, in the first section that wants it; with hinted, only the
    puzzles we have annotated are candidates."""
    used = set()
    fs = [f for f in all_facts if f["annotated"] or not hinted]
    out = []
    # Picked first so no other section takes a paper's oldest puzzle and leaves
    # its second-oldest to stand in; shown last.
    oldest = oldest_per_paper(fs)
    used.update(f["id"] for f in oldest)
    for slug, heading, blurb, cands, key, note, per_series in specs(fs):
        picked = pick(cands, key, used, per_series)
        if not picked:
            continue
        ranked = sorted(cands, key=key)
        if key is not newest_first:
            ranked = ranked[:FULL]
        label = f"all {len(ranked)}" if len(ranked) == len(cands) else f"top {len(ranked)}"
        full = ((blurb, [(f, note(f)) for f in ranked], label)
                if [f["id"] for f in ranked] != [f["id"] for f in picked] else None)
        out.append((slug, heading, blurb + (ONE_PER_SERIES if per_series == 1 else ""),
                    [(f, note(f)) for f in picked], full))
    if oldest:
        out.append(("oldest", "The oldest",
                    "The earliest puzzle we have from each paper, oldest first.",
                    # No note: the series badge already names the paper.
                    [(f, "") for f in oldest], None))
    return out


def wanted(all_facts):
    """Ids of the unannotated puzzles the showcase would pick if it took any
    puzzle: what annotating first would put on the page."""
    return [f["id"] for _, _, _, cards, _ in sections(all_facts, hinted=False)
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
