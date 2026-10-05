#!/usr/bin/env python3
"""Messages hidden in finished grids that the paper never announced, from the
blogs that point them out, each checked against our grid.

Most ninas go unannounced: the preamble says nothing and the blogger, or a
commenter, spots the perimeter or the unches spelling something. A post
saying so is the claim; the grid is the proof. A puzzle is listed only where
words the post quotes near "nina", "perimeter", "hidden message" and the like
are read off our grid along one of its lines (lines()), and the letters are
not just an answer the blogger was writing about (crosses()).

    python3 tools/ninas.py          # write tools/data/ninas.json
    python3 tools/ninas.py --show   # and print each find with its blog line

puzzle_tags reads tools/data/ninas.json, which is committed: the nightly
reindex runs where the blog caches are not.
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import parallel
import puzzle_tags

OUT = ROOT / "tools" / "data" / "ninas.json"

# Words a write-up uses when it points at a message in the grid.
POINTER = re.compile(
    r"\bninas?\b|hidden (?:message|theme)|perimeter|round the (?:edge|outside)"
    r"|\bunches\b|unchecked (?:letters|squares|cells)|(?:top|bottom) row"
    r"|(?:first|last|left|right)(?:-hand)? (?:column|col)\b|diagonal",
    re.IGNORECASE)

# How far either side of a pointer the quoted words may sit, in characters of
# the post's text.
WINDOW = 400

# The fewest letters a find may have: on a line read square by square, which a
# quoted run of answers can cross by chance, and on a line of every other
# square or of unchecked squares, which nothing but a planted message spells.
MIN_FULL = 8
MIN_SPACED = 6



def cell_entries(puzzle):
    """{cell: [answer index]}: the answers each square is part of, a linked
    answer's lights counted as one answer."""
    ents = puzzle["entries"]
    by_id = {puzzle_tags.entry_id(e): e for e in ents}
    cont = puzzle_tags.continuations(ents)
    out = {}
    for i, e in enumerate(ents):
        if puzzle_tags.entry_id(e) in cont:
            continue
        for gid in e.get("group") or [puzzle_tags.entry_id(e)]:
            for c in puzzle_tags.entry_cells(by_id.get(gid, e)):
                out.setdefault(c, []).append(i)
    return out


def lines(puzzle, grid):
    """(name, [cell]) for every line a message is hidden along: each row,
    column and long diagonal, the perimeter clockwise from the top left, each
    read square by square, every other square and unchecked squares only;
    then every unchecked square of the grid in reading order. Each forwards
    and backwards."""
    rows, cols = puzzle["dimensions"]["rows"], puzzle["dimensions"]["cols"]
    owners = cell_entries(puzzle)
    base = [(f"row {y + 1}", [(x, y) for x in range(cols)]) for y in range(rows)]
    base += [(f"column {x + 1}", [(x, y) for y in range(rows)]) for x in range(cols)]
    if rows == cols:
        base += [("diagonal", [(i, i) for i in range(rows)]),
                 ("diagonal", [(cols - 1 - i, i) for i in range(rows)])]
    ring = ([(x, 0) for x in range(cols)] + [(cols - 1, y) for y in range(1, rows)]
            + [(x, rows - 1) for x in range(cols - 2, -1, -1)]
            + [(0, y) for y in range(rows - 2, 0, -1)])
    base.append(("perimeter", ring))
    out = []
    for name, cells in base:
        white = [c for c in cells if c in grid]
        out += [(name, white, False),
                (f"{name}, every other square", white[0::2], True),
                (f"{name}, every other square", white[1::2], True),
                (f"{name}, unchecked squares", [c for c in white if len(owners.get(c, ())) == 1], True)]
        if name == "perimeter":  # the ring has no start: any square may begin it
            out += [(name, white + white, False)]
    out.append(("unchecked squares", [(x, y) for y in range(rows) for x in range(cols)
                                      if len(owners.get((x, y), ())) == 1], True))
    return [(n, cs[::d], spaced) for n, cs, spaced in out for d in (1, -1) if len(cs) > 1]


def crosses(cells, owners, starts):
    """A word the post quotes runs on from one answer into the next. A run
    whose every break between answers is a break between the post's words is
    the blogger writing answers out (ATTAIN IDIOLECT), not a message across
    them. `starts` are the offsets in the run where the post starts a word."""
    seams = {j for j in range(1, len(cells))
             if not set(owners.get(cells[j - 1], ())) & set(owners.get(cells[j], ()))}
    return bool(seams - starts)


def quoted(token):
    """The token as a word of a quoted message, or None. A blogger writes the
    message out in capitals, as whole words: prose in lower case and the
    letters a parsing splits off (outer letters of K ashmi R) are not one."""
    return token if token.isupper() and (len(token) > 1 or token in "AI") else None


def passages(text):
    """[(words, excerpt)]: the words near the pointers in a post, letters
    only, each stretch of the post once; a word that is not quoted() is None,
    which no run crosses. The pointer itself is not a word of the message (a
    row whose unches spell UNCHES)."""
    spans = []
    for m in POINTER.finditer(text):
        lo, hi = max(0, m.start() - WINDOW), m.end() + WINDOW
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = hi
        else:
            spans.append([lo, hi])
    masked = POINTER.sub(lambda m: "|" * len(m.group()), text)
    return [([quoted(t) for t in re.findall(r"[A-Za-z]+", masked[lo:hi])],
             " ".join(text[lo:hi].split()))
            for lo, hi in spans]


def find(puzzle, text):
    """(where, letters, blog excerpt) for the longest run of whole words near a
    pointer in the post that our grid spells along one of its lines, or None."""
    grid = puzzle_tags.grid_letters(puzzle) if puzzle_tags.trusted_answers(puzzle) else None
    if not grid:
        return None
    owners = cell_entries(puzzle)
    said = passages(text)
    if not said:
        return None
    best = None
    for name, cells, spaced in lines(puzzle, grid):
        letters = "".join(grid[c] for c in cells)
        floor = MIN_SPACED if spaced else MIN_FULL
        for words, excerpt in said:
            for k in range(len(words)):
                run, starts = "", set()
                for w in words[k:]:
                    if w is None:
                        break
                    starts.add(len(run))
                    run += w
                    if run not in letters:
                        break
                    if len(run) < floor or (best and len(run) <= len(best[1])):
                        continue
                    at = letters.find(run)
                    while at >= 0:
                        span = cells[at:at + len(run)]
                        if len(set(span)) == len(span) and (spaced or crosses(span, owners, starts)):
                            best = (name, run, excerpt)
                            break
                        at = letters.find(run, at + 1)
    return best


def _post_text(item):
    from blog_facts import rendered
    path, comments = item
    post = json.loads(Path(path).read_text(encoding="utf-8"))
    text = rendered(post.get("content"))
    if comments and Path(comments).exists():
        text += "\n" + "\n".join(rendered(c.get("content"))
                                 for c in json.loads(Path(comments).read_text(encoding="utf-8")))
    return post.get("link"), html.unescape(re.sub(r"<[^>]+>", " ", text))


def _check(item):
    from fetch_puzzle import read_puzzle_file, resolve_puzzle
    pid, url, text = item
    try:
        puz = read_puzzle_file(resolve_puzzle(pid))
    except (SystemExit, FileNotFoundError):
        return None
    got = find(puz, text)
    return got and (pid, url, *got)


def scan():
    from blog_facts import BLOGS
    from blog_facts import OUT as FACTS
    url_pids = {}
    for f in FACTS.glob("*.json"):
        for pid, rec in json.loads(f.read_text(encoding="utf-8")).items():
            url_pids.setdefault(rec["url"], []).append(pid)
    items = []
    for root, _ in BLOGS.values():
        items += [(str(p), str(root / "comments" / p.name)) for p in (root / "posts").glob("*.json")]
    texts = [t for t in parallel.pmap(_post_text, items) if t[0] in url_pids and POINTER.search(t[1])]
    jobs = [(pid, url, text) for url, text in texts for pid in url_pids[url]]
    return sorted((r for r in parallel.pmap(_check, jobs) if r), key=lambda r: r[0])


def main(argv):
    found = scan()
    data = {pid: {"where": where, "letters": letters, "blog": url}
            for pid, url, where, letters, _ in found}
    OUT.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if "--show" in argv:
        for pid, url, where, letters, chunk in found:
            print(f"{pid}\t{where}\t{letters}\n    {url}\n    {chunk[:300]}\n")
    print(f"{len(data)} puzzles", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
