#!/usr/bin/env python3
"""The Nation's answers, from the setters' own solution printed a week later.

    python3 tools/nation_key.py report [N...]  # what each key gives, nothing written
    python3 tools/nation_key.py file [N...]    # file the puzzles the keys place
    python3 tools/nation_key.py braze          # fetch Braze's solution posts

From about No 3243 every page of The Nation's cryptic (tools/fetch_nation.py)
prints "SOLUTION TO PUZZLE NO. <n>", Kosman and Picciotto's wordplay for the
week before: "1 ABSO(LUTE)LY (LA boys anag.) 6 hidden 10 DOG + MA". Most
entries spell the answer in capitals; "anag.", "hidden", "2 defs." and the
like give no letters. The capitals are read as the answer (key_letters), the
rest stay unanswered with the setter's note.

A key is checked against the puzzle before anything is written: an answer
must be its light's length, and the grid is rebuilt from the clue numbers
with the answers written in (reconstruct_grid with `words`), so an answer that
crosses wrongly finds no grid. One that does is dropped, and the rest tried
again (place). A light whose every cell the key's crossing answers fill is
answered from them, and a "hidden" one from the one run of its clue's letters
that fits its crossings (derive).

Braze's blog, the Nation Cryptic Crossword Forum (thenationcryptic.blogspot.com),
posted a full solution for most puzzles of 2012-07..2015-08, every answer
spelt out under its number ("1a / BOUND ARIES / BOUND ("certain") + ARIES"),
its notation marking the pieces ("PU}L{SE", "_UTTER", "M(<NEM ON<)ICS"). It
fills the lights the setters' key gives no letters for; where both spell one,
the setters' stands (the paper before a blog), and the grid judges both.

The puzzle is filed in puzzles/ with the key's answers as a partial key, the
shape a scan that kept part of its answer grid gets: tools/solve_packet.py
prints them as the paper's own and the backfill solves the rest around them.
"""
import itertools
import re
import sys
import time

import fetch_nation as fn

# "SOLUTION TO PUZZLE NO. 3272", and the pages that link the number.
SOLUTION = re.compile(r"SOLUTION TO\D{0,80}?(\d{3,4})")
# A line that carries on the solution: its headings and its numbered entries.
CARRIES_ON = re.compile(r"^>?\s*(?:ACROSS\b|DOWN\b|\d)")
MAX_LINES = 40
# What a key entry may print besides the answer's capitals: its pieces' joins.
ANSWER_ONLY = re.compile(r"^[A-Z\s+()\-.'’,&]+$")
# "S + ODA (rev.)" spells SODA but "[pl]ATTE (rev.)" means ETTA: a reversal's
# capitals may be either way round.
REVERSED = re.compile(r"\brev\b")
# How long the search for the one wrong answer may take, per puzzle.
LEAVE_ONE_OUT_SECONDS = 45


def solution_text(lines):
    """(number, text) of the solution a page's lines print, or None."""
    for i, line in enumerate(lines):
        m = SOLUTION.search(line)
        if not m:
            continue
        rest = [line[m.end():]]
        for more in lines[i + 1:i + 1 + MAX_LINES]:
            if not CARRIES_ON.match(more):
                break
            rest.append(more)
        return int(m.group(1)), " ".join(rest)
    return None


def solutions():
    """({puzzle number: (key text, page number)}, {number: page path}) over
    every held page. A key printed twice is the one on the page after the
    puzzle's; a puzzle printed twice is its plain page ("puzzle-no-1588",
    not "-0")."""
    out, pages = {}, {}
    for path in sorted(fn.PAGES.glob("*.html")):
        page = path.read_text()
        own = fn.meta(page)["number"]
        if own and (own not in pages or not re.search(r"-\d+-\d\.html$", path.name)):
            pages[own] = path
        found = solution_text(fn.lines_of(page))
        if not found:
            continue
        number, text = found
        if number not in out or own == number + 1:
            out[number] = (text, own)
    return out, pages


BRAZE = fn.downloads.NATION / "braze"
BRAZE_FEED = "https://thenationcryptic.blogspot.com/feeds/posts/default?alt=json&max-results=150&start-index={}"
BRAZE_TITLE = re.compile(r"solution\s*no[.,]?\s*(\d),?(\d{3})\b", re.IGNORECASE)


def braze_download():
    """Braze's post list (the blog's JSON feed, which carries summaries only)
    and every Nation solution post it names, into BRAZE."""
    (BRAZE / "posts").mkdir(parents=True, exist_ok=True)
    start, entries = 1, []
    while True:
        data = fn.get(BRAZE_FEED.format(start))
        (BRAZE / f"feed-{start}.json").write_text(data)
        got = fn.json.loads(data)["feed"].get("entry", [])
        entries += got
        if len(got) < 150:
            break
        start += 150
    for e in entries:
        m = BRAZE_TITLE.search(e["title"]["$t"])
        if not m:
            continue
        out = BRAZE / "posts" / f"{m.group(1)}{m.group(2)}.html"
        if out.exists():
            continue
        url = next(link["href"] for link in e["link"] if link["rel"] == "alternate")
        out.write_text(fn.get(url))
        time.sleep(fn.SLEEP_SECONDS)


def braze_answers(post):
    """{(direction, number): letters} of one Braze solution post: each "1a"
    or "14d" line and the answer line under it, its capitals the answer (the
    lowercase and "_" are letters taken away, the rest notation)."""
    start = post.find("post-body entry-content")
    body = post[start:post.find("post-footer", start)]
    body = re.sub(r"(?i)<br\s*/?>|</(?:p|div|td|tr|li)>", "\n", body)
    lines = [ln.strip() for ln in fn.html.unescape(re.sub(r"<[^>]+>", "", body)).split("\n")]
    lines = [ln for ln in lines if ln]
    out = {}
    for ln, nxt in itertools.pairwise(lines):
        m = re.fullmatch(r"(\d{1,2})\s*([ad])", ln)
        if not m:
            continue
        letters = re.sub(r"[^A-Z]", "", nxt)
        if letters and not re.search(r"[a-z]{3}", nxt.replace("_", " ")):
            out[("across" if m.group(2) == "a" else "down", int(m.group(1)))] = letters
    return out


def braze_keys():
    """{puzzle number: braze_answers} over every held post."""
    return {int(p.stem): braze_answers(p.read_text())
            for p in sorted((BRAZE / "posts").glob("*.html"))}


def sections(text):
    """{"across": text, "down": text} of a key, either missing when absent."""
    m = re.search(r"\bACROSS\b(.*?)(?:\bDOWN\b(.*))?$", text, re.DOTALL)
    if not m:
        return {}
    out = {"across": m.group(1)}
    if m.group(2) is not None:
        out["down"] = m.group(2)
    return out


def items(section, numbers):
    """{number: entry text} of one direction's key, read in the order of
    `numbers`, the puzzle's own clue numbers for it. Each must start past the
    one before it, so "14 2 defs." is 14's "2 defs.", and a number the key
    skips (a linked light's continuation) is passed over."""
    out, pos, found = {}, 0, []
    for n in numbers:
        m = re.compile(rf"(?<![\w(+/\[]){n}(?!\d)(?:\s*&\s*\d+\s*[AD]?)?\s").search(section, pos)
        if not m:
            continue
        found.append((n, m.start(), m.end()))
        pos = m.end() + 1
    for k, (n, _, end) in enumerate(found):
        stop = found[k + 1][1] if k + 1 < len(found) else len(section)
        out[n] = section[end:stop].strip()
    return out


def key_letters(entry):
    """The answer a key entry spells, or None where it gives no letters.
    Bracketed lowercase notes go ("(LA boys anag.)"), a deletion goes
    ("[s]TIFFIN[g]"), a substitution keeps its new letters ("[s/N]-EEDLESS");
    what is left must be capitals and joins alone."""
    text = re.sub(r"\[[^\]/]*/([^\]]*)\]", r"\1", entry)
    text = re.sub(r"\[[^\]]*\]", "", text)
    while True:
        cut = re.sub(r"\([^()]*[a-z][^()]*\)", "", text)
        if cut == text:
            break
        text = cut
    text = text.strip()
    if not text or not ANSWER_ONLY.match(text):
        return None
    letters = re.sub(r"[^A-Z]", "", text)
    return letters or None


def key_for(read, text, braze=None):
    """{(direction, light index): (letters or None, entry text)} of a key
    against the puzzle's lights (fetch_nation.read_page's across, down).
    `braze` (braze_answers) fills what the setters' key spells no letters
    for, its text then ""."""
    _, _, across, down, _ = read
    parts = sections(text or "")
    braze = braze or {}
    out = {}
    for direction, lights in (("across", across), ("down", down)):
        got = items(parts.get(direction, ""), [lg[0] for lg in lights])
        for i, lg in enumerate(lights):
            letters, note = None, got.get(lg[0])
            if note is not None:
                letters = key_letters(note)
                if letters and REVERSED.search(note) and braze.get((direction, lg[0])) in (
                        letters, letters[::-1]):
                    letters, note = braze[(direction, lg[0])], ""
            if not letters and (direction, lg[0]) in braze:
                letters, note = braze[(direction, lg[0])], note or ""
            if note is not None:
                out[(direction, i)] = (letters, note)
    return out


def spec_of(across, down):
    return [(lg[0], d, lg[1]) for d, lights in (("across", across), ("down", down))
            for lg in lights]


def search(spec, words, groups):
    """(grid, why) for these lights with these answers written in: the
    filer's own search (fetch_nation.search_grid), so a 15x15 search that ran
    out of budget is the reason given, not the 13x13 one that then found
    nothing (3325, 3499, 3505 and 3507 were refused as "no grid" so)."""
    across = [[n, length] for n, d, length in spec if d == "across"]
    down = [[n, length] for n, d, length in spec if d == "down"]
    return fn.search_grid(across, down, groups, words=words)


def place(read, key):
    """(grid, words, dropped, why): the one grid the clue list and the key's
    answers make, the answers kept (one per light, None where unknown), and
    the indices of answers dropped for not fitting. An answer not its light's
    length is dropped first; then, with no grid, each answer in turn, keeping
    the one drop that leaves a grid."""
    _, _, across, down, groups = read
    spec = spec_of(across, down)
    index = [(d, i) for d, lights in (("across", across), ("down", down))
             for i in range(len(lights))]
    words, dropped = [], []
    for k, (d, i) in enumerate(index):
        letters = (key.get((d, i)) or (None, ""))[0]
        if letters and spec[k][2] is not None and len(letters) != spec[k][2]:
            dropped.append(k)
            letters = None
        if letters and spec[k][2] is None:
            letters = None   # a linked light's share of its answer is not printed
        note = (key.get((d, i)) or (None, ""))[1]
        if letters and REVERSED.search(note) and key_letters(note) == letters:
            letters = None   # which way round the capitals are, place_reversed says
        words.append(letters)
    if not any(words):
        return None, words, dropped, "the key gives no answers"
    grid, why = search(spec, words, groups)
    if grid is not None:
        return grid, words, dropped, None
    if "grids fit" not in (search(spec, [None] * len(spec), groups)[1] or ""):
        return None, words, dropped, f"{why}, and the clue list alone gives no grid"
    deadline = time.monotonic() + LEAVE_ONE_OUT_SECONDS
    for k in [k for k, w in enumerate(words) if w]:
        if time.monotonic() > deadline:
            break
        trial = words[:k] + [None] + words[k + 1:]
        g, _ = search(spec, trial, groups)
        if g is not None:
            return g, trial, dropped + [k], None
    return None, words, dropped, why


def cells_of(entry):
    x, y = entry["position"]["x"], entry["position"]["y"]
    return [(x + i, y) if entry["direction"] == "across" else (x, y + i)
            for i in range(entry["length"])]


def clue_letters(entry):
    return re.sub(r"[^A-Z]", "", (entry["clue"].get("text") or "").upper())


def derive(entries, notes):
    """Answer the unanswered entries the grid fixes, in place: every cell
    filled by a crossing answer, or a "hidden" one (by the setter's `notes`,
    entry id -> key text) the one run of its clue's letters, forwards or for
    "rev." backwards, that agrees with every filled cell. Repeats until
    nothing changes; returns the ids answered."""
    from groups import entry_id
    done = []
    while True:
        known = {}
        for e in entries:
            if e.get("solution"):
                for c, ch in zip(cells_of(e), e["solution"]):
                    known[c] = ch
        changed = False
        for e in entries:
            if e.get("solution"):
                continue
            cells = cells_of(e)
            word = None
            if all(c in known for c in cells):
                word = "".join(known[c] for c in cells)
            note = notes.get(entry_id(e)) or ""
            if word is None and re.fullmatch(r"(?:rev\.\s*)?hidden\.?(?:\s*rev\.)?", note.strip()):
                text = clue_letters(e)
                if "rev" in note:
                    text = text[::-1]
                n = len(cells)
                fits = {text[i:i + n] for i in range(len(text) - n + 1)
                        if all(known.get(c, ch) == ch for c, ch in zip(cells, text[i:i + n]))}
                if len(fits) == 1:
                    word = fits.pop()
            if word is None and note and REVERSED.search(note):
                spelt = key_letters(note)
                if spelt and len(spelt) == len(cells):
                    fits = {w for w in (spelt, spelt[::-1])
                            if all(known.get(c, ch) == ch for c, ch in zip(cells, w))}
                    crossed = sum(c in known for c in cells)
                    if len(fits) == 1 and crossed:
                        word = fits.pop()
            if word:
                e["solution"] = word
                done.append(entry_id(e))
                changed = True
        if not changed:
            return done


def merge_filed(held, keyed):
    """`held`, a filed puzzle, with the answers of `keyed` (the same puzzle
    rebuilt on the key's grid) where it has none; None when the two grids
    differ, light for light."""
    from groups import entry_id
    shape = lambda p: sorted((entry_id(e), e["position"]["x"], e["position"]["y"], e["length"])
                             for e in p["entries"])
    if shape(held) != shape(keyed):
        return None
    got = {entry_id(e): e.get("solution") for e in keyed["entries"]}
    for e in held["entries"]:
        if not e.get("solution") and got.get(entry_id(e)):
            e["solution"] = got[entry_id(e)]
    return held


def settle_spellings(entries):
    """An annotation written before the key spells its answer. Once the
    answer is filed that spelling is derived (annotation.view) and goes; an
    answer other than the one spelt is a reading the key contradicts, so the
    light is left open for a look. Returns the ids left open."""
    from groups import entry_id
    contradicted = []
    for e in entries:
        spelt = (e.get("annotation") or {}).get("spelling")
        if not spelt or not e.get("solution"):
            continue
        if re.sub(r"[^A-Z]", "", spelt.upper()) == e["solution"]:
            del e["annotation"]["spelling"]
        else:
            e["solution"] = None
            contradicted.append(entry_id(e))
    return contradicted


def by_order(number, read, key):
    """(puzzle, report) for a held clues-only record whose clue numbers place
    no grid but whose key spells every light: its answers in printed order,
    the grid they cross in (clues_only.promote, the backfill's own route), or
    None."""
    from groups import entry_id

    import clues_only
    record = clues_only.read(fn.puzzle_id(fn.SERIES, number))
    _, _, across, down, _ = read
    if record is None:
        return None
    answers = {}
    for direction, lights in (("across", across), ("down", down)):
        got = [(key.get((direction, i)) or (None,))[0] for i in range(len(lights))]
        if not all(got) or len(got) != len(record["clues"][direction]):
            return None
        answers[direction] = got
    puzzle, _ = clues_only.promote(record, answers)
    if puzzle is None:
        return None
    for direction in ("across", "down"):
        entries = sorted((e for e in puzzle["entries"] if e["direction"] == direction),
                         key=lambda e: e["number"])
        if [e["length"] for e in entries] != [len(w) for w in answers[direction]]:
            return None
        for e, w in zip(entries, answers[direction]):
            e["solution"] = w
    return puzzle, {"keyed": sum(map(len, answers.values())), "dropped": [], "derived": [],
                    "open": [entry_id(e) for e in puzzle["entries"] if not e.get("solution")],
                    "filed": False, "gained": len(puzzle["entries"]), "notes": {}}


def keyed_puzzle(number, keys=None, known=None, braze=None):
    """(puzzle, report) for Nation `number` answered from its key, or (None,
    why not). report: {"keyed", "dropped", "derived", "open", "notes"}."""
    import puzzle_paths
    from groups import entry_id
    keys, pages = keys if keys is not None else solutions()
    braze = braze_keys().get(number) if braze is None else braze.get(number)
    if number not in keys and not braze:
        return None, "no held page prints its solution, and Braze posted none"
    path = pages.get(number)
    if path is None:
        return None, "its own page is not held"
    page = path.read_text()
    known = known if known is not None else fn.original_dates()
    read, why = fn.read_page(page, known)
    if read is None:
        return None, why
    key = key_for(read, (keys.get(number) or ("",))[0], braze)
    if not key:
        return None, "the key's entries did not read"
    import clues_only
    held = clues_only.read(fn.puzzle_id(fn.SERIES, number))
    broken = held and clues_only.implausible(held)
    if broken:
        # No grid holds the clue list as numbered: only every answer, in
        # order, can place it.
        grid, words, dropped, why = None, [], [], broken
    else:
        grid, words, dropped, why = place(read, key)
    if grid is None:
        whole = by_order(number, read, key)
        if whole is not None:
            return whole
        return None, f"no single grid holds the key's answers: {why}"
    url = next((u for u in fn.json.loads(fn.URLS.read_text())
                if fn.page_path(u).name == path.name), f"{fn.SITE}/article/archive/{path.stem}/")
    filed = puzzle_paths.find(fn.puzzle_id(fn.SERIES, number))
    puzzle, why = fn.build(page, url, known, grid=grid)
    if puzzle is None:
        return None, why
    _, _, across, down, _ = read
    lights = [(d, lg[0]) for d, ls in (("across", across), ("down", down)) for lg in ls]
    answers, notes = {}, {}
    for (d, n), w, k in zip(lights, words, [(d, i) for d, ls in (("across", across), ("down", down))
                                             for i in range(len(ls))]):
        eid = f"{n}-{d}"
        if w:
            answers[eid] = w
        if k in key:
            notes[eid] = key[k][1]
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    for eid, w in answers.items():
        if eid in by_id and len(w) == by_id[eid]["length"]:
            by_id[eid]["solution"] = w
    if filed:
        from fetch_puzzle import read_puzzle_file
        before = sum(bool(e.get('solution')) for e in read_puzzle_file(filed)['entries'])
        puzzle = merge_filed(read_puzzle_file(filed), puzzle)
        if puzzle is None:
            return None, "the filed grid is not the one the key places"
    derived = derive(puzzle["entries"], notes)
    contradicted = settle_spellings(puzzle["entries"])
    derived = [eid for eid in derived if eid not in contradicted]
    open_ = [entry_id(e) for e in puzzle["entries"] if not e.get("solution")]
    gained = len(puzzle["entries"]) - len(open_) - (before if filed else 0)
    return puzzle, {"keyed": len(answers), "dropped": [lights[k] for k in dropped],
                    "derived": derived, "open": open_, "filed": bool(filed), "gained": gained,
                    "notes": {eid: notes[eid] for eid in open_ if eid in notes}}


def notes_for(puzzle):
    """{entry id: the setters' note} for a filed Nation puzzle's unanswered
    lights, off the page printing its solution (the next number's, held as
    "puzzle-no-<n+1>.html"); {} when none is held. tools/solve_packet.py
    shows each beside its clue: "anag.", "hidden", "2 defs." say what kind
    of clue it is."""
    from groups import entry_id
    if puzzle.get("series") != fn.SERIES or not isinstance(puzzle.get("number"), int):
        return {}
    path = fn.PAGES / f"puzzle-no-{puzzle['number'] + 1}.html"
    found = solution_text(fn.lines_of(path.read_text())) if path.is_file() else None
    if not found or found[0] != puzzle["number"]:
        return {}
    parts, out = sections(found[1]), {}
    for direction in ("across", "down"):
        entries = sorted((e for e in puzzle["entries"] if e["direction"] == direction),
                         key=lambda e: e["number"])
        got = items(parts.get(direction, ""), [e["number"] for e in entries])
        for e in entries:
            if not e.get("solution") and got.get(e["number"]):
                out[entry_id(e)] = got[e["number"]]
    return out


def main(argv):
    if not argv or argv[0] not in ("report", "file", "braze"):
        raise SystemExit(__doc__)
    if argv[0] == "braze":
        return braze_download()
    keys, known, braze = solutions(), fn.original_dates(), braze_keys()
    numbers = [int(a) for a in argv[1:]] or sorted(set(keys[0]) | set(braze))
    for n in numbers:
        try:
            puzzle, report = keyed_puzzle(n, keys, known, braze)
        except (Exception, SystemExit) as e:  # one bad page never stops the rest
            puzzle, report = None, f"{type(e).__name__}: {e}"
        if puzzle is None:
            print(f"nation-{n}: {report}", flush=True)
            continue
        if argv[0] == "file" and report["gained"]:
            try:
                fn.write_puzzle_file(fn.puzzle_path(fn.SERIES, n), puzzle, generator=fn.TOOL)
            except Exception as e:  # one refused write never stops the rest
                print(f"nation-{n}: write refused: {type(e).__name__}: {str(e)[:300]}", flush=True)
                continue
        print(f"nation-{n}: {report['keyed']} keyed, {len(report['derived'])} derived, "
              f"{len(report['open'])} open, dropped {report['dropped']}"
              + (" (already filed)" if report["filed"] else ""), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
