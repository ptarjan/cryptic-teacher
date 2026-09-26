#!/usr/bin/env python3
"""Structural facts about our clues, read off the blogs that explain them.

timesforthetimes, fifteensquared and bigdave44 write up most of the puzzles we
hold. Their prose is theirs and is never copied. What this keeps is what the
blogger's markup states about the clue itself:

  * the definition: the words the blogger underlined, which are words of the
    clue, so a span is kept only where it is an exact run of whole words of
    OUR copy of the clue;
  * the clue type, only where the write-up names it in a form that means one
    thing (see TYPES);
  * the indicators, only where the blog's own convention marks them: a
    bracketed [word] on timesforthetimes, an italic (<em>word</em>) on
    bigdave44, and again only words that are in the clue.

The join never trusts a title. A post is a candidate for every puzzle whose
number its title carries, and it is that puzzle's post only if our clue texts
are found in it, in order: a clue is a long enough string that finding it is
the proof.

    python3 tools/blog_facts.py            # write tools/data/blog_facts/
    python3 tools/blog_facts.py --measure  # and print coverage per blog and series
    python3 tools/blog_facts.py --sample 30 --seed 1   # and print rows to check by hand
    python3 tools/blog_facts.py --if-changed  # the nightly: skip when no input moved

Reads the caches the fetchers write under ~/cryptic-setter-data; never the
network.
"""
import argparse
import ast
import collections
import hashlib
import html
import html.parser
import json
import os
import random
import re
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from fetch_puzzle import puzzle_files, read_puzzle_file

DATA = Path.home() / "cryptic-setter-data"
OUT = ROOT / "tools" / "data" / "blog_facts"
#: The digest of every input the files in OUT were written from; see inputs_digest.
STAMP = OUT / "inputs.sha256"

#: Blog key -> (cache directory, the name a reader is shown). The key is what
#: the sidecar stores; the name is what the site prints beside the link.
BLOGS = {
    "timesforthetimes": (DATA / "timesforthetimes", "Times for the Times"),
    "fifteensquared": (DATA / "fifteensquared", "Fifteensquared"),
    "bigdave44": (DATA / "bigdave44", "Big Dave's Crossword Blog"),
}

#: A post is a puzzle's write-up when at least this share of its clues is found
#: in it. Old Times posts blog only the interesting clues, so this is low; a
#: wrong puzzle scores zero, never a half.
MIN_ALIGNED = 0.3

U_ON, U_OFF, E_ON, E_OFF = "", "", "", ""
MARKS = U_ON + U_OFF + E_ON + E_OFF
BLOCK_TAGS = {"p", "br", "div", "tr", "td", "th", "li", "h1", "h2", "h3", "h4",
              "h5", "h6", "table", "tbody", "ul", "ol"}
UNDERLINE_STYLE = re.compile(r"text-decoration\s*:\s*underline", re.I)
SKIP_TAGS = {"s", "strike", "del", "script", "style"}


class _Flatten(html.parser.HTMLParser):
    """HTML to text, with underline and emphasis kept as sentinel characters."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.out.append("\n")
        if tag in ("br", "img", "hr"):
            return
        mark = ""
        if tag in SKIP_TAGS:
            self.skip += 1
            mark = "skip"
        elif tag in ("u", "ins") or UNDERLINE_STYLE.search(dict(attrs).get("style") or ""):
            mark = U_ON
        elif tag in ("em", "i"):
            mark = E_ON
        if mark and mark != "skip":
            self.out.append(mark)
        self.stack.append((tag, mark))

    def handle_endtag(self, tag):
        if tag in BLOCK_TAGS:
            self.out.append("\n")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _, mark in reversed(self.stack[i:]):
                    if mark == "skip":
                        self.skip -= 1
                    elif mark:
                        self.out.append(U_OFF if mark == U_ON else E_OFF)
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def flatten(rendered):
    p = _Flatten()
    p.feed(rendered)
    p.close()
    return "".join(p.out).replace("\xa0", " ")


def fold(ch):
    """A character as the letter it is compared by: accents off, lower case."""
    return unicodedata.normalize("NFKD", ch)[:1].lower()


def projection(text, marked=False):
    """(letters, positions, underline runs, emphasis flags) of a text.

    An underline run is numbered, 0 for none, so two underlines with only a
    space between them stay two spans: a double definition is two.

    Only letters are compared: punctuation, quotes, spacing and enumerations
    differ between a blog's copy of a clue and the paper's."""
    letters, pos, under, emph = [], [], [], []
    u = e = run = 0
    for i, ch in enumerate(text):
        if marked and ch in MARKS:
            if ch == U_ON and u == 0:
                run += 1
            u += {U_ON: 1, U_OFF: -1}.get(ch, 0)
            e += {E_ON: 1, E_OFF: -1}.get(ch, 0)
            continue
        f = fold(ch)
        if f.isalnum() and f.isascii():
            letters.append(f)
            pos.append(i)
            under.append(run if u > 0 else 0)
            emph.append(e > 0)
    return "".join(letters), pos, under, emph


ENUM_TAIL = re.compile(r"\s*\((?:[\d,\s\-–.]|words?)+\)\s*$")


def clue_body(clue):
    """The clue without its enumeration, which blogs print in varied forms."""
    return ENUM_TAIL.sub("", clue or "").strip()


def is_word_start(s, i):
    return i == 0 or not s[i - 1].isalnum()


def is_word_end(s, j):
    return j >= len(s) or not s[j].isalnum() or s[j] in "'’"


def spans_of(runs, pos, body):
    """Underline runs over the clue's letters, as whole-word substrings of
    `body`, or None when any run cuts into a word (a sloppy underline)."""
    out, i = [], 0
    while i < len(runs):
        if not runs[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(runs) and runs[j + 1] == runs[i]:
            j += 1
        a, b = pos[i], pos[j] + 1
        if not (is_word_start(body, a) and is_word_end(body, b)):
            return None
        out.append(body[a:b])
        i = j + 1
    return out


# --------------------------------------------------------------------- types

#: Where a sentence of a write-up begins: a clue type is named at the start
#: of one ("Hidden in ...", "BRUSSELS – hidden reversed ...").
OPENS = r"(?:^|(?<=[\n:–—;.(])|(?<=[\n:–—;.(] ))\s*(?:it's\s+|this\s+is\s+|an?\s+|just\s+an?\s+|simply\s+an?\s+)?"

#: The wordplay a write-up names in a form that means one thing, as the
#: TYPE_PARTS string app.js's familyOf reads. First match wins, in the same
#: dominance order as FAMILIES. &lit is not read: bloggers and annotators
#: split on &lit against cryptic definition too often for it to be a fact.
TYPES = (
    ("double definition", re.compile(
        r"\b(?:double|two|triple|three)[\s-]+def(?:inition)?s?\b|\bDD\b|\b2\s?defs?\b"
        r"|\b(?:two|three) meanings\b", re.I)),
    ("cryptic definition", re.compile(OPENS + r"(?:cryptic(?:ally)?\s+def(?:inition)?|CD)\b", re.I)),
    ("anagram", re.compile(r"\banagram\b|\banag\b|[A-Z)]\*|\*\s*\(|\banagrind", re.I)),
    ("spoonerism", re.compile(r"\bspooner(?:ism|'s)?\b", re.I)),
    ("homophone", re.compile(r"\bhomophone\b|\bsounds like\b", re.I)),
    ("hidden word", re.compile(
        OPENS + r"(?:reversed?\s+|reverse\s+)?hidden\b"
        r"|\bhidden\s+(?:reversed?\s+|backwards\s+)?(?:word\s+)?(?:in|within|inside)\b|\[hidden", re.I)),
)
#: A write-up that hedges ("almost a DD", "a dd cum cd", "sort of") or denies
#: ("not an anagram") has not named the type, so nothing is read off it.
HEDGED = re.compile(
    r"\bnot\s+(?:an?\s+|the\s+|quite\s+)?(?:anagram|homophone|hidden|double|cryptic|&\s*lit)"
    r"|\bnot quite\b|\balmost\b|\bsort of\b|\bkind of\b|\bnearly\b|\bish\b|\bcum\b"
    r"|\bI think\b|\bI suppose\b|\bdefinition\s*\?|\b[cd]d\s*\?"
    r"|\b[cd]d\s*/\s*[cd]d\b|\bsemi|\bor (?:an?|the) (?:anagram|homophone|double|cryptic|&\s*lit)",
    re.I)
REVERSED = re.compile(r"\brevers|\bbackwards?\b|\bup\b(?=.*\bhidden)", re.I)


def clue_type(expl):
    """The one clue type `expl` names unambiguously, or None."""
    if HEDGED.search(expl):
        return None
    for name, rx in TYPES:
        if rx.search(expl):
            if name == "hidden word" and REVERSED.search(expl):
                return "hidden word + reversal"
            return name
    return None


# ---------------------------------------------------------------- indicators

#: A timesforthetimes post puts indicators in [square brackets] only where its
#: blogger's key says so; other bloggers' brackets hold glosses or deletions.
BRACKETS_ARE_INDICATORS = re.compile(r"(?:indicators|directions) in square (?:ones|brackets)", re.I)
BRACKETED = re.compile(r"(?<![A-Za-z])\[([^\[\]]{2,60})\](?![A-Za-z])")
ITALIC_IN_PARENS = re.compile(r"\(" + E_ON + r"([^" + MARKS + r"()]{2,60})" + E_OFF + r"\)")
ELLIPSIS = re.compile(r"\s*(?:…|\.\.\.)\s*")


def in_clue(phrase, body):
    phrase = phrase.strip(" '‘’\"“”,.;:!?")
    if len(phrase) < 2:
        return None
    m = re.search(r"(?<![\w'’])" + re.escape(phrase) + r"(?![\w])", body, re.I)
    return body[m.start():m.end()] if m else None


def indicators(blog, expl_marked, body, brackets):
    """Indicator words the blog's own convention marks, as spelled in `body`.
    `brackets` says whether this post's key declares [bracketed] indicators."""
    if blog == "timesforthetimes" and brackets:
        raw = BRACKETED.findall(expl_marked.replace(E_ON, "").replace(E_OFF, ""))
    elif blog == "bigdave44":
        raw = ITALIC_IN_PARENS.findall(expl_marked.replace(U_ON, "").replace(U_OFF, ""))
    else:
        return []
    out = []
    for r in raw:
        parts = [p for p in ELLIPSIS.split(r) if p.strip()]
        found = [in_clue(p, body) for p in parts]
        if parts and all(found):
            out.extend(f for f in found if f not in out)
    return out


# ---------------------------------------------------------------- the posts

def rendered(field):
    """A WordPress `rendered` field, whichever of three shapes a fetcher stored."""
    if isinstance(field, dict):
        return field.get("rendered", "")
    if isinstance(field, str) and field.startswith("{'rendered'"):
        try:
            return ast.literal_eval(field)["rendered"]
        except (ValueError, SyntaxError):
            return field
    return field or ""


NUMBER = re.compile(r"(?<![\d,])(\d{1,2},\d{3}|\d{3,6})(?![\d,])")


def post_numbers(title):
    return {int(n.replace(",", "")) for n in NUMBER.findall(html.unescape(title))}


def load_post(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    return {"id": d["id"], "link": d.get("link"), "title": html.unescape(rendered(d.get("title"))),
            "content": rendered(d.get("content"))}


def puzzle_entries(p):
    """[(entry id, clue body, solution)] in the order blogs print them."""
    rows = [e for e in p["entries"] if clue_body(e.get("clue"))]
    rows.sort(key=lambda e: (e["direction"] != "across", e["number"]))
    return [(e["id"], clue_body(e["clue"]), e.get("solution") or "") for e in rows]


def align(entries, stream):
    """Per entry, the (start, end) of its clue's letters in `stream`'s projection.

    Clues are searched for in order from the last one found, which is the order
    blogs print them in; a clue not found after the cursor is looked for from
    the top once, and taken only if it occurs there exactly once."""
    letters = stream[0]
    hits, cursor = {}, 0
    for eid, body, _ in entries:
        key = projection(body)[0]
        if len(key) < 4:
            continue
        at = letters.find(key, cursor)
        if at < 0:
            first = letters.find(key)
            if first < 0 or letters.find(key, first + 1) >= 0:
                continue
            at = first
        hits[eid] = (at, at + len(key))
        cursor = at + len(key)
    return hits


#: Where a write-up moves on to the next clue: a line that is a clue number,
#: alone or with its direction, before anything but prose ("2 defs" is prose),
#: or an Across/Down heading. Bounds the explanation when the next clue itself
#: was not found.
NEXT_CLUE = re.compile(
    r"\n[ \t\ue000-\ue003]*(?:\d{1,2}(?:[ \t]*(?:a|d|ac|dn|across|down)\b)?[ \t.]*"
    r"(?=\n|[ \t]*[\"'‘“A-Z(\ue000-\ue003])|(?:across|down)\b)", re.I)


def facts_for_post(blog, entries, post):
    """{entry id: facts} for every clue of `entries` found in `post`."""
    text = flatten(post["content"])
    stream = projection(text, marked=True)
    letters, pos, under, _ = stream
    hits = align(entries, stream)
    brackets = bool(BRACKETS_ARE_INDICATORS.search(text))
    starts = sorted(a for a, _ in hits.values())
    out = {}
    for eid, body, solution in entries:
        if eid not in hits:
            continue
        a, b = hits[eid]
        nxt = next((s for s in starts if s >= b), len(letters))
        seg_start = pos[b - 1] + 1
        seg_end = pos[nxt] if nxt < len(letters) else len(text)
        expl_marked = text[seg_start:seg_end]
        cut = NEXT_CLUE.search(expl_marked, 1)
        expl_marked = expl_marked[:cut.start() if cut else 1200][:1200]
        expl = re.sub("[" + MARKS + "]", "", expl_marked)
        bpos = projection(body)[1]
        defs = spans_of(under[a:b], bpos, body)
        fact = {"found": True}
        if defs:
            fact["definition"] = defs
        elif defs is None:
            fact["badSpan"] = True
        t = clue_type(expl)
        if t:
            fact["type"] = t
        ind = indicators(blog, expl_marked, body, brackets)
        if ind:
            fact["indicators"] = ind
        out[eid] = fact
    return out


def _work(args):
    blog, path, candidates = args
    post = load_post(path)
    best = None
    for pid, entries in candidates:
        facts = facts_for_post(blog, entries, post)
        score = len(facts) / max(1, len(entries))
        if score >= MIN_ALIGNED and (best is None or score > best[1]):
            best = (pid, score, facts, len(entries))
    if best is None:
        return None
    return {"blog": blog, "post": post["id"], "url": post["link"], "id": best[0],
            "score": best[1], "facts": best[2], "clues": best[3]}


def load_puzzles(extra=()):
    """{number: [(id, entries)]} over our puzzles, plus any `extra` records."""
    by_number = collections.defaultdict(list)
    series = {}
    for path in puzzle_files():
        p = read_puzzle_file(path)
        ents = puzzle_entries(p)
        if ents:
            by_number[p["number"]].append((p["id"], ents))
            series[p["id"]] = p.get("series", "cryptic")
    for pid, number, ents, s in extra:
        by_number[number].append((pid, ents))
        series[pid] = s
    return by_number, series


def bigdave_records():
    """bigdave44's own parsed light lists, as stand-in puzzles to measure on
    until the Telegraph puzzles are filed. Ids are prefixed so nothing mistakes
    them for ours."""
    path = BLOGS["bigdave44"][0] / "parsed.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        ents = [(f"{e['number']}-{e['direction']}", clue_body(e.get("clue")),
                 e.get("answer") or "") for e in r["entries"] if clue_body(e.get("clue"))]
        if ents:
            out.append((f"bd:{r['series']}-{r['number']}", r["number"], ents, "bd:" + r["series"]))
    return out


def extract(blogs, with_bigdave_records=False, jobs=None):
    """Every post of `blogs` joined to the puzzle it writes up, with its facts.
    One record per puzzle: the post whose clues were found most completely."""
    extra = bigdave_records() if with_bigdave_records else ()
    by_number, series = load_puzzles(extra)
    work = []
    for blog in blogs:
        posts = BLOGS[blog][0] / "posts"
        for path in sorted(posts.glob("*.json")):
            try:
                title = rendered(json.loads(path.read_text(encoding="utf-8")).get("title"))
            except ValueError:
                continue
            cands = [c for n in post_numbers(title) for c in by_number.get(n, ())]
            if cands:
                work.append((blog, path, cands))
    best = {}
    with ProcessPoolExecutor(jobs) as ex:
        for r in ex.map(_work, work, chunksize=16):
            if r and (r["id"] not in best or r["score"] > best[r["id"]]["score"]):
                best[r["id"]] = r
    return best, series


def inputs_digest():
    """A digest of everything the output is a function of: this file, each
    blog's cached posts, bigdave44's parsed light lists, and the clues of every
    puzzle. Posts are cached once and never rewritten, so a post is its name and
    size; a puzzle is only what the join reads, so a new annotation moves nothing."""
    h = hashlib.sha256(Path(__file__).read_bytes())
    for blog in sorted(BLOGS):
        posts = BLOGS[blog][0] / "posts"
        names = sorted((e.name, e.stat().st_size) for e in os.scandir(posts)
                       if e.name.endswith(".json")) if posts.is_dir() else []
        h.update(json.dumps([blog, names]).encode())
    parsed = BLOGS["bigdave44"][0] / "parsed.jsonl"
    h.update(parsed.read_bytes() if parsed.exists() else b"")
    for path in puzzle_files():
        p = read_puzzle_file(path)
        h.update(json.dumps([p["id"], p["number"], p.get("series"), puzzle_entries(p)]).encode())
    return h.hexdigest()


# ------------------------------------------------------------------ outputs

def publishable(fact):
    """The facts of one clue that ship: what was found, minus the bookkeeping.

    More than one underlined span is a definition only as the two halves of a
    double definition; otherwise it is a split definition or a blogger's
    emphasis, and the site has no sentence that states it truthfully."""
    out = {k: fact[k] for k in ("definition", "type", "indicators") if k in fact}
    defs = out.get("definition", [])
    if len(defs) > 1 and not (len(defs) == 2 and out.get("type") == "double definition"):
        del out["definition"]
    return out


def write(best, series):
    OUT.mkdir(parents=True, exist_ok=True)
    by_series = collections.defaultdict(dict)
    for pid, r in best.items():
        if pid.startswith("bd:"):
            continue
        entries = {eid: publishable(f) for eid, f in sorted(r["facts"].items())}
        entries = {k: v for k, v in entries.items() if v}
        if entries:
            by_series[series[pid]][pid] = {"blog": r["blog"], "name": BLOGS[r["blog"]][1],
                                           "url": r["url"], "entries": entries}
    for old in OUT.glob("*.json"):
        if old.stem not in by_series:
            old.unlink()
    for s, rows in sorted(by_series.items()):
        (OUT / f"{s}.json").write_text(
            "{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False, sort_keys=True)
                               for k, v in sorted(rows.items())) + "\n}\n", encoding="utf-8")
    return sum(len(v) for v in by_series.values())


def measure(best, series):
    rows = collections.defaultdict(collections.Counter)
    for pid, r in best.items():
        c = rows[(r["blog"], series[pid])]
        c["puzzles"] += 1
        c["clues"] += r["clues"]
        for f in r["facts"].values():
            c["found"] += 1
            c["definition"] += "definition" in f
            c["badSpan"] += "badSpan" in f
            c["type"] += "type" in f
            c["indicators"] += "indicators" in f
    print("Percentages are of every clue in the joined puzzles.")
    print(f"{'blog':17} {'series':16} {'puzzles':>7} {'clues':>7} {'found%':>6} {'def%':>6} {'type%':>6} {'ind%':>6} {'bad%':>5}")
    for (blog, s), c in sorted(rows.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        n = max(1, c["clues"])
        print(f"{blog:17} {str(s):16} {c['puzzles']:7} {c['clues']:7} {100 * c['found'] / n:6.1f} {100 * c['definition'] / n:6.1f} "
              f"{100 * c['type'] / n:6.1f} {100 * c['indicators'] / n:6.1f} {100 * c['badSpan'] / n:5.1f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--blog", action="append", choices=sorted(BLOGS))
    ap.add_argument("--measure", action="store_true", help="print coverage per blog and series")
    ap.add_argument("--sample", type=int, help="print N random extractions to check by hand")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dump", help="also write every joined record, bookkeeping included, as JSON lines")
    ap.add_argument("--from-dump", help="read the joins from an earlier --dump instead of the caches")
    ap.add_argument("--if-changed", action="store_true",
                    help="exit without parsing when no input has changed since the last write")
    args = ap.parse_args()
    digest = inputs_digest()
    if args.if_changed and STAMP.exists() and STAMP.read_text().strip() == digest:
        print(f"blog facts are current: no post, clue or parser change since {STAMP.relative_to(ROOT)} was written")
        return
    if args.from_dump:
        lines = Path(args.from_dump).read_text(encoding="utf-8").splitlines()
        best = {r["id"]: r for r in map(json.loads, lines)}
        series = load_puzzles(bigdave_records())[1]
    else:
        best, series = extract(args.blog or sorted(BLOGS), with_bigdave_records=True)
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            for r in best.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if args.measure:
        measure(best, series)
    if args.sample:
        rng = random.Random(args.seed)
        pool = [(r, eid, publishable(f)) for r in best.values() for eid, f in r["facts"].items()]
        pool = [p for p in pool if p[2]]
        for r, eid, f in rng.sample(pool, min(args.sample, len(pool))):
            print(json.dumps({"id": r["id"], "entry": eid, "url": r["url"], **f}, ensure_ascii=False))
    print(f"wrote blog facts for {write(best, series)} puzzles to {OUT.relative_to(ROOT)}")
    if not (args.blog or args.from_dump):
        STAMP.write_text(digest + "\n")


if __name__ == "__main__":
    main()
