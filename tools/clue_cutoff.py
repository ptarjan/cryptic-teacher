#!/usr/bin/env python3
"""Spot a puzzle whose held clue text is cut short or garbled, before a model is bought on it.

An annotate session reads every clue, finds one that ends mid-sentence
(times-25739's 24-down "So (5)", toughie-571's 15-down "Stood before (9)",
OCR'd "demar", "Ea", "trans-") and withdraws: the whole session is lost,
and the puzzle comes back next night unless failed_inputs holds it. This is
the same finding made in code, for nothing, from the puzzle file alone.

    suspects(puzzle) -> {entry id: why}      the lights whose clue looks cut short
    gate(puzzles)    -> ({id: {entry: why}})  of those that are, for the burn's queue
    python3 tools/clue_cutoff.py ID...        say what each puzzle's file shows

Positive evidence only. A clue that is short, empty, a "See 9" pointer or a
cross-reference is legitimate (a linked entry's blank half, a one-word cryptic
definition, genius-108 published with no clue text), so shortness alone never
counts. The signals:
  mid-word     the text ends on a hyphen after letters ("depriving trans-")
  garble       (OCR channels only) two or more words not in the lexicon, or
               scraps like "tr", "ta", "mai"
  repeated     two lights hold the same clue words (fetch_puzzle.duplicated_clues):
               the source served one light's clue on another (sundaytel-2540's
               25-across); "See N" pointers never count
  blog         the puzzle's .blog file quotes a clue fragment ("clueFragment")
               with a word the held clue does not contain: the blog saw words
               the file lost (toughie-144's "cad")

A puzzle with a row in tools/data/reread_unfixable.json (a reread left its clue text
unmended: unfixable from the scan until the OCR reader changes) is held out of the burn
whatever its file shows, and no reread is asked for it (scan_queue.request_reread
refuses it too). Deleting the row lifts both.

A light with a row in SOURCE_CLUE_WRONG or SETTER_ERROR is exempt: its text was
already read against a source. The gate acts on the file as it is, so a repair
that changes the clue text lifts the hold by itself, and nothing is stored.
"""
import functools
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: Words a clue cannot stop on: it was cut before their object.
DANGLING = frozenset(["a", "an", "the", "of", "to", "for", "in", "with", "from", "by", "and", "or", "on", "at", "as", "into", "onto", "about", "after", "before", "around", "over", "under", "that", "which", "when", "if", "but", "not", "is", "are", "be", "being", "has", "have", "had", "was", "were", "this", "these", "those", "its", "his", "her", "their", "my", "our", "your", "some", "any", "each", "every", "than", "then", "so", "while", "where", "whose", "who", "whom"])
#: ...except a handful that do end clues: "...so", "...for", a one-word reply.
ENDS_OK = frozenset(["so"])
#: Two-letter and one-letter words a clue can hold whole.
SHORT_OK = frozenset(["a", "i", "o", "am", "an", "as", "at", "be", "by", "do", "go", "ha", "he", "hi", "if", "in", "is", "it", "me", "my", "no", "of", "oh", "ok", "on", "or", "ox", "so", "to", "up", "us", "we", "ye", "yo", "ah", "ay", "eh", "er", "em", "en", "ex", "id", "la", "lo", "ma", "pa", "pi", "re", "ta", "uh", "um"])


@functools.lru_cache(maxsize=1)
def lexicon():
    words = set()
    with open(HERE / "data" / "lexicon.tsv", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("#"):
                words.add(line.split("\t", 1)[0].lower())
    return words


@functools.lru_cache(maxsize=1)
def unfixable():
    """{puzzle id: why} of the puzzles a reread could not mend (tools/data/reread_unfixable.json)."""
    import json
    with open(HERE / "data" / "reread_unfixable.json", encoding="utf-8") as f:
        return {k: v[0] for k, v in json.load(f).items()}


@functools.lru_cache(maxsize=1)
def exempt():
    import fetch_puzzle
    import validate_annotations
    return set(fetch_puzzle.SOURCE_CLUE_WRONG) | set(validate_annotations.SETTER_ERROR)


def _letters(enum):
    return sum(int(n) for n in re.findall(r"\d+", enum or ""))


def clue_why(text, enum, ocr=False):
    """Why this clue looks cut short or garbled, or None. Never for an empty,
    short or "See N" clue: those are legitimate."""
    text = (text or "").strip()
    if not text or re.match(r"see\b", text, re.IGNORECASE) or re.search(r"\bsee\s+\d", text, re.IGNORECASE):
        return None
    tokens = re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", text)
    if len(tokens) < 2:
        return None
    if re.search(r"[^\W\d_]-\s*$", text):
        return f"ends mid-word ({text[-12:]!r})"
    if ocr:
        lex = lexicon()
        tokens = [t for t in tokens if "'" not in t and "’" not in t]
        scraps = [t for t in tokens if len(t) <= 2 and t.lower() not in SHORT_OK and not t.isupper()]
        unknown = [t for t in tokens if len(t) >= 3 and t.islower()
                   and t.lower() not in lex and t.lower().rstrip("s") not in lex and "-" not in t]
        if len(scraps) + len(unknown) >= 2:
            return f"garbled words {(scraps + unknown)[:3]}"
    return None


def blog_missing(text, fragments):
    """The words of a blog-quoted clue fragment the held clue lacks, or []."""
    have = {w.lower() for w in re.findall(r"[^\W\d_]+", text or "")}
    miss = []
    for frag in fragments:
        if "[" in frag or "…" in frag:
            continue
        words = [w.lower() for w in re.findall(r"[^\W\d_]+", frag)]
        miss += [w for w in words if w not in have]
    return miss


def blog_fragments(puzzle):
    """{entry id: [clueFragment]} from the .blog file beside the puzzle, if any."""
    import json

    import puzzle_paths
    try:
        path = puzzle_paths.find_listed(puzzle["id"])
        blog = json.loads(Path(path).with_suffix(".blog").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    out = {}
    for eid, v in (blog.get("entries") or {}).items():
        out[eid] = [b["clueFragment"] for b in v.get("blocks") or ()
                    if isinstance(b, dict) and isinstance(b.get("clueFragment"), str)]
    return out


def raw_suspects(puzzle):
    """{entry id: why} for the lights of `puzzle` whose clue looks cut short,
    exempt lights included: suspects() drops those after, so a change to the
    exempt rules needs no new reading of the file (the row cache holds this)."""
    import provenance
    from groups import entry_id
    ocr = (puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS
    frags = blog_fragments(puzzle)
    out = {}
    for e in puzzle.get("entries", ()):
        clue = e.get("clue") if isinstance(e.get("clue"), dict) else {}
        eid = entry_id(e)
        why = clue_why(clue.get("text"), clue.get("enumeration"), ocr)
        if not why and eid in frags and (clue.get("text") or "").strip():
            miss = blog_missing(clue["text"], frags[eid])
            if miss:
                why = f"the blog quotes {miss[:3]} which the held clue lacks"
        if why:
            out[eid] = why
    import fetch_puzzle
    for ids in fetch_puzzle.duplicated_clues(puzzle.get("entries", ())):
        for eid in ids:
            out.setdefault(eid, f"its clue repeats {', '.join(i for i in ids if i != eid)}'s")
    return out


def suspects(puzzle):
    """{entry id: why} for the lights of `puzzle` whose clue looks cut short."""
    skip = exempt()
    return {eid: why for eid, why in raw_suspects(puzzle).items() if (puzzle["id"], eid) not in skip}


def puzzle_row(path):
    """What gate keeps per puzzle file: its id, the raw suspects, whether its
    source is OCR'd, and the held text of each suspect light."""
    import json

    import provenance
    puzzle = json.loads(path.read_text(encoding="utf-8"))
    found = raw_suspects(puzzle)
    texts = {f"{e['number']}-{e['direction']}": e["clue"].get("text") for e in puzzle.get("entries", ())
             if isinstance(e.get("clue"), dict) and f"{e.get('number')}-{e.get('direction')}" in found}
    return {"id": puzzle["id"], "found": found, "texts": texts,
            "ocr": (puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS}


def _blog_stamp(path, row):
    """The .blog beside a puzzle is read by raw_suspects but is not the file
    the row is keyed on: its size and mtime stand in for it."""
    try:
        st = path.with_suffix(".blog").stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def held_only(pids):
    """{puzzle id: {"*": why}} of the `pids` a reread could not mend: gate()'s
    answer without a look at any file."""
    unfix = unfixable()
    return {pid: {"*": unfix[pid]} for pid in pids if pid in unfix}


def gate(pids, read=None, log=None):
    """{puzzle id: {entry id: why}} for the ids in `pids` whose file shows a cut-short clue.

    `read(pid)` returns the puzzle dict (default: its file in the checkout, with
    the raw suspects of each file held in the row cache). An OCR'd
    puzzle's source is asked for a re-read (scan_queue.request_reread, the desktop's
    lane), once per reading; any other is appended to `log` (a path) as a row for
    the source-fix path. Neither is annotated until its clue text changes.

    One listed_once() scope covers the loop: a find per id was a stat of every
    year folder of its series, twice (the puzzle and its .blog), and 11-05
    that was two thirds of a 31k-id --backlog."""
    import json

    import provenance
    import puzzle_paths
    import scan_queue
    pids = list(pids)
    flagged = {}
    held = unfixable()
    skip = exempt()
    with puzzle_paths.listed_once():
        if read is None:
            import row_cache
            paths = {pid: puzzle_paths.find_listed(pid) for pid in pids if pid not in held}
            have = sorted({p for p in paths.values() if p is not None})
            rows = dict(zip(have, row_cache.cached_map("clue_cutoff", puzzle_row, have, deps=_blog_stamp)))
        for pid in pids:
            if pid in held:
                flagged[pid] = {"*": held[pid]}
                continue
            if read is None:
                row = rows.get(paths[pid])
                if row is None:  # queued, then renamed or removed: skip it
                    continue
                found = {k: v for k, v in row["found"].items() if (pid, k) not in skip}
                ocr, shown = row["ocr"], [(eid, row["texts"].get(eid, "")) for eid in found]
                puzzle = {"id": pid, "entries": ()}
            else:
                try:
                    puzzle = read(pid)
                except (OSError, ValueError, KeyError):
                    continue
                found = suspects(puzzle)
                ocr = (puzzle.get("source") or {}).get("retrievedFrom") in provenance.OCR_CHANNELS
                shown = [(eid, next((e["clue"].get("text") for e in puzzle["entries"]
                                     if f"{e['number']}-{e['direction']}" == eid), "")) for eid in found]
            if not found:
                continue
            flagged[pid] = found
            if ocr:
                scan_queue.request_reread(puzzle if read else _reload(paths[pid]), shown, ["clueCutShort"])
            elif log:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"id": pid, "lights": found}) + "\n")
    return flagged


def _reload(path):
    """The puzzle dict at `path`, for the few flagged OCR'd ones that need a re-read asked."""
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv):
    import json

    import puzzle_paths
    for pid in argv[1:]:
        puzzle = json.loads(puzzle_paths.find(pid).read_text(encoding="utf-8"))
        print(pid, suspects(puzzle) or "clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
