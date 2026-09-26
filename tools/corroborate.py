#!/usr/bin/env python3
"""Corroborate a puzzle against every other source we hold for it.

    python3 tools/corroborate.py --sweep            # the whole corpus, offline, report only
    python3 tools/corroborate.py --sweep --apply    # ...and write what it resolves
    python3 tools/corroborate.py cryptic-23053      # one puzzle, report only

fetch_puzzle.write_puzzle_file calls corroborate() on every puzzle it writes,
so every fetcher gets this without asking for it. A source here only ever
reads a local cache, which keeps a write cheap and offline: a puzzle whose
series no cache covers simply has no second source, and that is not an error.
The caches are filled by the tools that own them — fetch_fifteensquared.py,
fetch_times_listing.py, and `--download` here for georgeho's database.

What happens to each field:

  setter, date   filled when the file has none; when sources disagree with
                 the file or each other, resolved by the rules below.
  clue text      filled only when the file's clue is blank. Blog transcriptions
                 differ from the paper in punctuation constantly, so a clue the
                 file already has is never compared.
  answers        compared, never filled: a file with no key stays keyless. A
                 disagreement is resolved by the rules below and the file is
                 written with the winner.

The rules, in order; the first that leaves one candidate decides, and is the
rule the ledger names:

  grid         answers: the letters must fill the light (the whole group, for
               a linked answer) and agree with every crossing light; disputed
               crossers are solved jointly, as a constraint problem over the
               candidates.
  sequence     dates: the date sits between the numbers either side on disk
               (fetch_puzzle.fits_sequence).
  enumeration  clues: the printed enumeration counts the light's cells.
  votes        the candidate backed by the most independent origins. Copies of
               one origin (fifteensquared's own cache and georgeho's scrape of
               it) are one vote.
  rank         RANK below, per field.

Nothing here raises on a disagreement. One no rule settles is printed as a
WARNING naming every candidate and left as the file had it. Every disagreement,
settled or not, and every fill, is recorded in LEDGER.

An answer fetch_puzzle.SOURCE_ANSWER_WRONG says the paper got wrong is the
file's corrected value; a source repeating the paper's wrong letters is
dropped, not counted.
"""

import argparse
import html
import itertools
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

DATA = Path.home() / "cryptic-setter-data"
GEORGEHO = DATA / "georgeho" / "data.db"
GEORGEHO_URL = "https://cryptics.georgeho.org/data.db"
# Our own rows out of GEORGEHO, keyed by puzzle id; rebuilt when data.db changes.
GEORGEHO_INDEX = DATA / "georgeho" / "ours.db"
FIFTEENSQUARED_POSTS = DATA / "fifteensquared" / "posts"
FIFTEENSQUARED_INDEX = DATA / "fifteensquared" / "by_puzzle.json"
LEDGER = TOOLS / "data" / "corroboration_ledger.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Best first; an origin not listed ranks below every listed one. The answer
# order is the measured one: `--sweep` prints, per origin, how many of the
# answer disputes the grid settled it lost. Over the corpus the paper lost
# none of 20, a model's solve none of 1, fifteensquared 22 of 23 and the Times
# blog 6 of 12 (misparsed rows, mostly, which is still an error rate).
RANK = {
    "answer": ("publisher", "model", "fifteensquared", "timesforthetimes"),
    "setter": ("publisher", "fifteensquared", "timesforthetimes"),
    "date": ("publisher", "times-listing", "fifteensquared", "timesforthetimes"),
    "clue": ("publisher", "fifteensquared", "timesforthetimes"),
}

# A candidate grid assignment is tried per combination of disputed lights;
# past this many combinations the grid rule steps aside for the votes.
MAX_COMBINATIONS = 4096


@dataclass
class Record:
    """What one source says about one puzzle. Keys of `answers` and `clues`
    are (number, direction) of the light the source prints it against."""
    source: str
    origin: str
    url: str = ""
    setter: str = None
    date: int = None              # epoch ms of the PRINT date, never a post date
    answers: dict = field(default_factory=dict)
    clues: dict = field(default_factory=dict)


# ---------------------------------------------------------------- normalising

def letters(text):
    """The letters a solver writes, accents folded: "Gets-ready" -> GETSREADY."""
    return re.sub(r"[^A-Z]", "", unicodedata.normalize(
        "NFKD", html.unescape(text or "")).upper())


def answer_letters(text):
    """letters(), or None for an answer that is not one plain answer: an
    alternative pair ("ANYONE/CERISE") or a bracketed spelling
    ("ANALYS(I)S")."""
    if not text or re.search(r"[/()\[\]?]", text):
        return None
    return letters(text) or None


def name_key(name):
    return letters(name).lower()


def clue_key(text):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize(
        "NFKD", html.unescape(text or "")).lower())


def day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def day_ms(text):
    return int(datetime.strptime(text, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp() * 1000)


MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
TITLE_DATE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)? (" + "|".join(MONTHS) + r"),? (\d{4})\b",
                        re.IGNORECASE)


def title_date(title):
    """The print date a blog title spells out ("Everyman 3348 28 November
    2010"), or None. The post's own date is when it was blogged, not printed."""
    m = TITLE_DATE.search(title or "")
    if not m:
        return None
    try:
        return int(datetime(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)),
                            tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


# ------------------------------------------------------------- naming a post

# fifteensquared's own titles, most specific first. Genius, Azed, the FT and the
# rest are other papers' number sequences and must not answer to ours.
BLOG_SERIES = (
    (re.compile(r"\bgenius\b|\bazed\b|financial|inquisitor|enigmatic|\bs b\b", re.IGNORECASE), None),
    (re.compile(r"\bquiptic\b", re.IGNORECASE), "quiptic"),
    (re.compile(r"\bin\w*dent on sunday\b|\bios\b", re.IGNORECASE), "indysunday"),
    (re.compile(r"\bindependent\b", re.IGNORECASE), "independent"),
    (re.compile(r"\beveryman\b", re.IGNORECASE), "everyman"),
    (re.compile(r"\bcyclops\b", re.IGNORECASE), "cyclops"),
    (re.compile(r"private eye", re.IGNORECASE), "cyclops"),
    (re.compile(r"\bgu?a\w*dian\b", re.IGNORECASE), "cryptic"),
)
# times-xwd-times, the Times for the Times blog's LiveJournal years.
TIMES_SERIES = (
    (re.compile(r"mephisto|club|\btls\b|extra|listener", re.IGNORECASE), None),
    (re.compile(r"quick|\bqcc?\s*\d", re.IGNORECASE), "timesquick"),
    (re.compile(r"jumbo", re.IGNORECASE), "timesjumbo"),
    (re.compile(r"sunday times", re.IGNORECASE), "sundaytimes"),
    (re.compile(r"\bt\w?mes\b", re.IGNORECASE), "times"),
)
NUMBER = re.compile(r"(\d{1,2},\d{3}|\d+)")


def blog_puzzle_id(title, table=BLOG_SERIES):
    """Our puzzle id for a blog post's title, or None when it is not one of our
    series. The number is the first one after the series name."""
    title = html.unescape(title or "")
    for pattern, series in table:
        m = pattern.search(title)
        if m:
            if series is None:
                return None
            n = NUMBER.search(title, m.end() if series != "timesquick" else m.start())
            return f"{series}-{int(n.group(1).replace(',', ''))}" if n else None
    return None


BYLINE = re.compile(r"\bby\s+([A-Z][\w'’.-]*(?: [A-Z][\w'’.-]*)?)\s*$")
TRAILING = re.compile(r"\d\s*([A-Z][a-z][\w'’-]*)$")


def blog_setter(title):
    """The setter a blog title names — "... by Tramp", or a lone capitalised
    word right after the number ("Guardian 25749 Brendan") — else None."""
    title = re.sub(r"\s+\d{1,2} \w+ \d{4}$", "", html.unescape(title or "").strip())
    m = BYLINE.search(title) or TRAILING.search(title)
    if not m or m.group(1).lower() in NOT_A_SETTER or len(m.group(1)) < 3:
        return None
    return m.group(1)


# Words a title puts where a setter's name would go.
NOT_A_SETTER = set(MONTHS) | {"guardian", "independent", "everyman", "quiptic", "cyclops",
                              "puzzle", "prize", "crossword", "cryptic", "anonymous",
                              "sunday", "saturday", "christmas", "special"}


CLUE_NUMBER = re.compile(r"^\D*(\d+)")


def light_key(clue_number, direction=None):
    """(number, direction) for a blog's clue-number cell: "18d", "13/15a",
    "12ac". None when the direction cannot be told."""
    text = (clue_number or "").strip().lower()
    m = CLUE_NUMBER.match(text)
    if not m:
        return None
    if re.search(r"(a|ac|across)\W*$", text):
        direction = "across"
    elif re.search(r"(d|dn|down)\W*$", text):
        direction = "down"
    return (int(m.group(1)), direction) if direction else None


# ------------------------------------------------------------------- sources

def download_georgeho():
    """Fetch georgeho's database into GEORGEHO. ~200 MB, once."""
    GEORGEHO.parent.mkdir(parents=True, exist_ok=True)
    part = GEORGEHO.with_suffix(".part")
    req = urllib.request.Request(GEORGEHO_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    part.rename(GEORGEHO)


def _georgeho_index():
    if not GEORGEHO.exists():
        return None
    if (not GEORGEHO_INDEX.exists()
            or GEORGEHO_INDEX.stat().st_mtime < GEORGEHO.stat().st_mtime):
        tmp = GEORGEHO_INDEX.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        out = sqlite3.connect(tmp)
        out.execute("create table clue (pid text, source text, url text, name text, "
                    "clue_number text, clue text, answer text)")
        src = sqlite3.connect(f"file:{GEORGEHO}?mode=ro", uri=True)
        tables = {"fifteensquared": BLOG_SERIES, "times_xwd_times": TIMES_SERIES}
        ids = {}
        rows = src.execute("select source, source_url, puzzle_name, clue_number, clue, answer "
                           "from clues where source in ('fifteensquared', 'times_xwd_times')")
        for source, url, name, number, clue, answer in rows:
            key = (source, url, name)
            if key not in ids:
                ids[key] = blog_puzzle_id(name, tables[source])
            if ids[key]:
                out.execute("insert into clue values (?,?,?,?,?,?,?)",
                            (ids[key], source, url, name, number, clue, answer))
        out.execute("create index by_pid on clue (pid)")
        out.commit()
        out.close()
        tmp.rename(GEORGEHO_INDEX)
    return sqlite3.connect(f"file:{GEORGEHO_INDEX}?mode=ro", uri=True)


_georgeho = []


def georgeho(puzzle):
    """georgeho.org's scrape of fifteensquared and times-xwd-times (ODbL)."""
    pid = puzzle["id"]
    if not _georgeho:
        _georgeho.append(_georgeho_index())
    db = _georgeho[0]
    if db is None:
        return []
    by_url = {}
    for source, url, name, number, clue, answer in db.execute(
            "select source, url, name, clue_number, clue, answer from clue where pid = ?",
            (pid,)):
        rec = by_url.get(url)
        if rec is None:
            origin = "fifteensquared" if source == "fifteensquared" else "timesforthetimes"
            rec = by_url[url] = Record(f"georgeho:{source}", origin, url,
                                       setter=blog_setter(name), date=title_date(name))
        key = light_key(number)
        if key is None:
            continue
        got = answer_letters(answer)
        if got:
            rec.answers.setdefault(key, got)
        if clue and clue.strip():
            rec.clues.setdefault(key, clue.strip())
    return list(by_url.values())


_posts = {}
CAPS_RUN = re.compile(r"^[^a-z]*[A-Z][^a-z]*$")


ROW_OR_HEADING = re.compile(r"(<tr\b.*?</tr>)|>\s*(Across|Down)\s*<", re.DOTALL | re.IGNORECASE)
TD = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
TAG = re.compile(r"<[^>]+>")
BOLD = re.compile(r"<(strong|b)\b[^>]*>(.*?)</\1>|<span[^>]*font-weight:\s*bold[^>]*>(.*?)</span>",
                  re.DOTALL)
STRUCK = re.compile(r"<del\b[^>]*>.*?</del>", re.DOTALL)


def _text(fragment):
    return html.unescape(TAG.sub("", fragment)).strip()


def _answers_in(fragment):
    """Every string a blog cell could be printing as its answer, likeliest
    first: its opening bold run (a two-word answer is often bolded a word at a
    time), each bold run in capitals and each run of up to four of them
    together (an answer coloured in its parts), and the whole cell when it is
    nothing but capitals. The caller keeps the first that fills the light."""
    import fetch_privateeye as pe
    fragment = STRUCK.sub("", fragment)
    out = []
    lead = pe._leading_answers(fragment)
    if lead:
        out.append(_text(lead))
    runs = [_text(m.group(2) or m.group(3) or "") for m in BOLD.finditer(fragment)]
    runs = [r for r in runs if letters(r) and CAPS_RUN.match(r)]
    for size in range(1, 5):
        out += [" ".join(runs[i:i + size]) for i in range(len(runs) - size + 1)]
    text = _text(fragment)
    if CAPS_RUN.match(text):
        out.append(text)
    return [a for a in map(answer_letters, out) if a]


def blog_rows(content):
    """[((number, direction), [candidate answers])] from a post's clue table.

    A row whose first cell is a clue number opens a light; its answer is the
    capitals _answers_in finds in the row's other cells, or in the rows
    after it whose first cell is empty (the template that prints the clue on
    one row and the answer under it). A clue's own words are never an answer:
    they are not in capitals.
    """
    direction, light, out = None, None, []
    for m in ROW_OR_HEADING.finditer(content):
        heading = m.group(2) or (re.search(r">\s*(Across|Down)\s*<", m.group(1), re.IGNORECASE)
                                 or [None, None])[1]
        if heading:
            direction, light = heading.lower(), None
            if m.group(2):
                continue
        cells_ = TD.findall(m.group(1))
        if len(cells_) < 2 or not direction:
            continue
        key = re.sub(r"\s+", "", _text(cells_[0])).lstrip("*").replace(".", "")
        if key:
            light = light_key(key, direction) if re.match(r"^\d+[a-z]*(/\d+[a-z]*)*$", key,
                                                          re.IGNORECASE) else None
        if light is None:
            continue
        found = [a for cell in cells_[1:] for a in _answers_in(cell)]
        if found:
            out.append((light, found))
            light = None
    return out


def _fifteensquared_index():
    """{puzzle id: [post id]} over the post cache, rebuilt when it grows."""
    if not FIFTEENSQUARED_POSTS.is_dir():
        return {}
    stamp = FIFTEENSQUARED_POSTS.stat().st_mtime
    if FIFTEENSQUARED_INDEX.exists():
        held = json.loads(FIFTEENSQUARED_INDEX.read_text())
        if held.get("stamp") == stamp:
            return held["ids"]
    ids = defaultdict(list)
    for path in FIFTEENSQUARED_POSTS.glob("*.json"):
        post = json.loads(path.read_text())
        pid = blog_puzzle_id(post["title"]["rendered"])
        if pid:
            ids[pid].append(int(path.stem))
    FIFTEENSQUARED_INDEX.write_text(json.dumps({"stamp": stamp, "ids": ids}))
    return ids


def fifteensquared(puzzle):
    """fifteensquared.net's posts, from tools/fetch_fifteensquared.py's cache."""
    if "ids" not in _posts:
        _posts["ids"] = _fifteensquared_index()
    sizes = light_sizes(puzzle)
    held = defaultdict(set)
    for members in units(puzzle).values():
        for m in members:
            held[(m["number"], m["direction"])].update(
                filter(None, (m.get("solution"), unit_value(members))))
    out = []
    for post_id in _posts["ids"].get(puzzle["id"], ()):
        post = json.loads((FIFTEENSQUARED_POSTS / f"{post_id}.json").read_text())
        title = html.unescape(post["title"]["rendered"])
        rec = Record("fifteensquared", "fifteensquared", post.get("link", ""),
                     setter=blog_setter(title), date=title_date(title))
        for light, found in blog_rows(post["content"]["rendered"]):
            # The file's own answer when the row prints it anywhere: a row
            # also prints its anagram fodder and its parts in capitals, and
            # only a row without the answer in it is a dissent.
            fits = [a for a in found if len(a) in sizes.get(light, ())]
            if fits and light not in rec.answers:
                rec.answers[light] = next((a for a in fits if a in held.get(light, ())), fits[0])
        out.append(rec)
    return out


_listing = {}


def times_listing(puzzle):
    """The Times's own puzzle listing, as Wayback captured it: print dates."""
    series, number = puzzle["series"], puzzle["number"]
    if not series.startswith(("times", "sundaytimes")):
        return []
    if "dates" not in _listing:
        import fetch_times_listing
        _listing["dates"] = (fetch_times_listing.paper_dates()
                             if fetch_times_listing.CACHE.is_dir() else {})
    when = _listing["dates"].get((series, number))
    if when is None:
        return []
    if not isinstance(when, int):
        when = day_ms(str(when)[:10])
    return [Record("times-listing", "times-listing", date=when)]


# Every source, cheapest first. The live Guardian, its Wayback copies and its
# printable PDFs are the publisher itself — a copy of the primary is no second
# vote — and the Times for the Times post cache is where every Times file's
# answers already come from, so none of those is listed.
SOURCES = (georgeho, fifteensquared, times_listing)


# ---------------------------------------------------------------- the grid

def cells(entry):
    x, y = entry["position"]["x"], entry["position"]["y"]
    dx, dy = (1, 0) if entry["direction"] == "across" else (0, 1)
    return [(x + dx * i, y + dy * i) for i in range(entry["length"])]


def units(puzzle):
    """{leader id: [member entries in answer order]}: each answer's lights."""
    by_id = {e["id"]: e for e in puzzle["entries"]}
    out, taken = {}, set()
    for e in puzzle["entries"]:
        group = [g for g in (e.get("group") or []) if g in by_id]
        if len(group) > 1 and group[0] == e["id"]:
            out[e["id"]] = [by_id[g] for g in group]
            taken.update(group)
    for e in puzzle["entries"]:
        if e["id"] not in taken:
            out[e["id"]] = [e]
    return out


def light_sizes(puzzle):
    """{(number, direction): letter counts an answer printed there may have}:
    the light's own, and the whole group's on a group's first light."""
    out = defaultdict(set)
    for members in units(puzzle).values():
        out[(members[0]["number"], members[0]["direction"])].add(len(unit_cells(members)))
        for m in members:
            out[(m["number"], m["direction"])].add(m["length"])
    return out


def unit_cells(members):
    return [c for m in members for c in cells(m)]


def unit_value(members):
    parts = [m.get("solution") or "" for m in members]
    return "".join(parts) if all(parts) else None


# ---------------------------------------------------------------- resolving

@dataclass
class Dispute:
    field: str
    entry: str                      # a leader id for answers/clues, "" otherwise
    primary: object                 # the file's value, None when it had none
    candidates: dict                # value -> {source name: origin}
    winner: object = None
    rule: str = None


def primary_origins(puzzle):
    """(answer origin, everything-else origin) of the file's own values."""
    kind = (puzzle.get("solutionSource") or {}).get("kind")
    answer = kind or "publisher"
    rest = kind if (puzzle.get("provenance") or {}).get("retrievedFrom") == "blog" else "publisher"
    return answer, rest or "publisher"


def _vote(candidates):
    counts = {v: len(set(src.values())) for v, src in candidates.items()}
    top = max(counts.values())
    best = [v for v, n in counts.items() if n == top]
    return best[0] if len(best) == 1 else None


def _rank(field_name, candidates):
    order = RANK[field_name]

    def best(src):
        return min((order.index(o) if o in order else len(order)) for o in src.values())
    scores = {v: best(src) for v, src in candidates.items()}
    top = min(scores.values())
    winners = [v for v, s in scores.items() if s == top]
    return winners[0] if len(winners) == 1 else None


def settle(d, tests=()):
    """Pick d.winner: each (rule, allowed values) test in turn narrows the
    candidates, then votes, then rank. The first rule to leave one is named."""
    pool = d.candidates
    for rule, allowed in tests:
        if allowed is None:
            continue
        kept = {v: s for v, s in pool.items() if v in allowed}
        if len(kept) == 1:
            d.winner, d.rule = next(iter(kept)), rule
            return d
        if kept:
            pool = kept
    for rule, pick in (("votes", _vote), ("rank", lambda p: _rank(d.field, p))):
        winner = pick(pool)
        if winner is not None:
            d.winner, d.rule = winner, rule
            return d
    d.winner, d.rule = d.primary, "unresolved"
    return d


def enumeration_parts(clue):
    """[4, 2, 3, 4] for a clue ending "(4,2,3,4)", else []."""
    m = re.search(r"\(([\d,\-\s.'’]+)\)\s*$", clue or "")
    return [int(n) for n in re.findall(r"\d+", m.group(1))] if m else []


def _add(candidates, value, source, origin):
    if value:
        candidates.setdefault(value, {})[source] = origin


def same_puzzle(puzzle, rec):
    """Whether `rec` is about this grid at all: most of the answers it shares
    with the file must agree. A post filed under the wrong number, or a scrape
    that joined two posts, disagrees on nearly every light and is no witness
    to anything in this puzzle. A record with no answers, or a file with no
    key, cannot be checked this way and is kept."""
    agree = differ = 0
    for members in units(puzzle).values():
        own = unit_value(members)
        got = rec.answers.get((members[0]["number"], members[0]["direction"]))
        if own and got and len(got) == len(own):
            agree += got == own
            differ += got != own
    if agree or differ:
        return agree > differ
    return not rec.answers or not any(e.get("solution") for e in puzzle["entries"])


def answer_disputes(puzzle, records):
    """Disputes over answers, with the grid rule already applied jointly."""
    import fetch_puzzle
    answer_origin, _ = primary_origins(puzzle)
    wrong = {eid: letters(served) for (tpid, eid), (served, _c, _w)
             in fetch_puzzle.SOURCE_ANSWER_WRONG.items() if tpid == puzzle["id"]}
    all_units = units(puzzle)
    disputes = {}
    for lead, members in all_units.items():
        own = unit_value(members)
        if own is None:
            continue
        size = len(unit_cells(members))
        cands = {}
        _add(cands, own, "primary", answer_origin)
        for rec in records:
            for m in members:
                got = rec.answers.get((m["number"], m["direction"]))
                if not got or got == wrong.get(m["id"]):
                    continue
                if m is members[0] and len(got) == size:
                    _add(cands, got, rec.source, rec.origin)
                elif got == (m.get("solution") or "") or got == own:
                    _add(cands, own, rec.source, rec.origin)
                elif len(members) == 1 and len(got) == size:
                    _add(cands, got, rec.source, rec.origin)
                break
        if len(cands) > 1:
            disputes[lead] = Dispute("answer", lead, own, cands)
    if not disputes:
        return []
    # Letters every undisputed light puts in its cells.
    fixed = {}
    for lead, members in all_units.items():
        if lead in disputes:
            continue
        for m in members:
            for c, ch in zip(cells(m), m.get("solution") or ""):
                fixed[c] = ch
    placed = {lead: unit_cells(all_units[lead]) for lead in disputes}
    # Disputed lights that share a cell are solved together.
    leads = list(disputes)
    comp = {lead: {lead} for lead in leads}
    for a, b in itertools.combinations(leads, 2):
        if set(placed[a]) & set(placed[b]) and comp[a] is not comp[b]:
            merged = comp[a] | comp[b]
            for x in merged:
                comp[x] = merged
    seen = set()
    for lead in leads:
        group = tuple(sorted(comp[lead]))
        if group in seen:
            continue
        seen.add(group)
        options = [list(disputes[g].candidates) for g in group]
        total = 1
        for o in options:
            total *= len(o)
        allowed = None
        if total <= MAX_COMBINATIONS:
            allowed = defaultdict(set)
            for combo in itertools.product(*options):
                grid, ok = dict(fixed), True
                for g, value in zip(group, combo):
                    for c, ch in zip(placed[g], value):
                        if grid.setdefault(c, ch) != ch:
                            ok = False
                            break
                    if not ok:
                        break
                if ok:
                    for g, value in zip(group, combo):
                        allowed[g].add(value)
        for g in group:
            settle(disputes[g], [("grid", allowed.get(g) if allowed is not None else None)])
    return list(disputes.values())


def field_disputes(puzzle, records):
    """Setter, date and blank-clue disputes and fills."""
    import fetch_puzzle
    _, origin = primary_origins(puzzle)
    out = []
    for name, key, own in (("setter", name_key, puzzle.get("setter")),
                           ("date", day, puzzle.get("date"))):
        cands, shown = {}, {}
        if own:
            _add(cands, key(own), "primary", origin)
            shown[key(own)] = own
        for rec in records:
            value = getattr(rec, name)
            if value:
                _add(cands, key(value), rec.source, rec.origin)
                shown.setdefault(key(value), value)
        if len(cands) > 1 or (cands and not own):
            d = Dispute(name, "", own, {shown[k]: s for k, s in cands.items()})
            tests = []
            if name == "date":
                series, number = puzzle["series"], puzzle["number"]
                tests = [("sequence", {v for v in d.candidates
                                       if fetch_puzzle.fits_sequence(series, number, v)})]
            if len(d.candidates) == 1:
                d.winner, d.rule = next(iter(d.candidates)), "filled"
            else:
                settle(d, tests)
            out.append(d)
    for members in units(puzzle).values():
        for m in members:
            if (m.get("clue") or "").strip():
                continue
            cands, shown = {}, {}
            for rec in records:
                text = rec.clues.get((m["number"], m["direction"]))
                if text:
                    _add(cands, clue_key(text), rec.source, rec.origin)
                    shown.setdefault(clue_key(text), text)
            if not cands:
                continue
            d = Dispute("clue", m["id"], None, {shown[k]: s for k, s in cands.items()})
            size = len(unit_cells(members)) if m is members[0] else m["length"]
            fits = {v for v in d.candidates
                    if sum(enumeration_parts(v)) in (size, 0)}
            if len(d.candidates) == 1:
                d.winner, d.rule = (next(iter(fits)), "filled") if fits else (None, "unresolved")
            else:
                settle(d, [("enumeration", fits)])
            out.append(d)
    return out


def resolve(puzzle, sources=None):
    """Every dispute and fill the sources raise over `puzzle`."""
    records = [r for source in (SOURCES if sources is None else sources) for r in source(puzzle)
               if same_puzzle(puzzle, r)]
    if not records:
        return []
    return answer_disputes(puzzle, records) + field_disputes(puzzle, records)


def apply(puzzle, disputes):
    """`puzzle` with every settled winner written in."""
    puzzle = {**puzzle, "entries": [dict(e) for e in puzzle["entries"]]}
    by_id = {e["id"]: e for e in puzzle["entries"]}
    all_units = units(puzzle)
    for d in disputes:
        if d.winner is None or d.winner == d.primary:
            continue
        if d.field == "answer":
            rest = d.winner
            for m in all_units[d.entry]:
                by_id[m["id"]]["solution"], rest = rest[:m["length"]], rest[m["length"]:]
        elif d.field == "clue":
            by_id[d.entry]["clue"] = d.winner
        else:
            puzzle[d.field] = d.winner
    return puzzle


def describe(pid, d):
    shown = day if d.field == "date" else str
    cands = "; ".join(f"{shown(v)} from {', '.join(sorted(s))}"
                      for v, s in d.candidates.items())
    where = f" {d.entry}" if d.entry else ""
    return f"{pid}{where} {d.field}: {cands}"


def record(pid, disputes, ledger=None):
    """Write each dispute to the ledger; warn on the ones no rule settled."""
    ledger = ledger or LEDGER
    held = json.loads(ledger.read_text()) if ledger.exists() else {}
    before = dict(held)
    for d in disputes:
        if d.rule == "unresolved":
            print(f"WARNING: corroborate: no rule settles {describe(pid, d)} — "
                  f"filed as the primary source had it", file=sys.stderr)
        key = " ".join(filter(None, (pid, d.field, d.entry)))
        shown = day if d.field == "date" else (lambda v: v)
        held[key] = {
            "candidates": [{"value": shown(v), "sources": sorted(s)}
                           for v, s in d.candidates.items()],
            "winner": shown(d.winner) if d.winner is not None else None,
            "rule": d.rule,
        }
    if held != before:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps(held, indent=1, sort_keys=True, ensure_ascii=False)
                          + "\n", encoding="utf-8")


def known_wrong(puzzle):
    """`puzzle` with fetch_puzzle.SOURCE_ANSWER_WRONG's corrections in, on
    every write and not only on the one fetcher that reads the Guardian: a
    correction any tool can write back over is no correction."""
    import fetch_puzzle
    fixes = {eid: (served, corrected) for (pid, eid), (served, corrected, _w)
             in fetch_puzzle.SOURCE_ANSWER_WRONG.items() if pid == puzzle["id"]}
    if not any(e["id"] in fixes and e.get("solution") == fixes[e["id"]][0]
               for e in puzzle["entries"]):
        return puzzle
    entries = [dict(e, solution=fixes[e["id"]][1])
               if e["id"] in fixes and e.get("solution") == fixes[e["id"]][0] else e
               for e in puzzle["entries"]]
    return {**puzzle, "entries": entries}


def corroborate(puzzle, sources=None, ledger=None):
    """`puzzle` corroborated: fills made, disputes settled, all of it ledgered.
    Never raises over what a source says."""
    if not puzzle.get("series") or not puzzle.get("entries"):
        return puzzle
    puzzle = known_wrong(puzzle)
    disputes = resolve(puzzle, sources)
    if not disputes:
        return puzzle
    record(puzzle["id"], disputes, ledger)
    return apply(puzzle, disputes)


# ------------------------------------------------------------------- the sweep

def sweep(write=False):
    import fetch_puzzle
    per_source = Counter()
    fields = Counter()
    lost = Counter()
    decided = Counter()
    shown, misfiled = [], []
    for path in fetch_puzzle.puzzle_files():
        puzzle = fetch_puzzle.read_puzzle_file(path)
        if not puzzle.get("series") or not puzzle.get("entries"):
            continue
        records = [r for s in SOURCES for r in s(puzzle)]
        dropped = [r for r in records if not same_puzzle(puzzle, r)]
        for r in dropped:
            misfiled.append(f"{puzzle['id']}: {r.source} {r.url}")
        records = [r for r in records if r not in dropped]
        for origin in {r.source.split(":")[0] if r.source != "times-listing" else r.source
                       for r in records}:
            per_source[(origin, puzzle["series"])] += 1
        if not records:
            continue
        disputes = answer_disputes(puzzle, records) + field_disputes(puzzle, records)
        for d in disputes:
            filled = d.primary in (None, "")
            fields[(d.field, "fill" if filled else "dispute", d.rule)] += 1
            if not filled:
                shown.append((d.rule, describe(puzzle["id"], d)
                              + f"  => {d.rule}: {d.winner if d.field != 'date' else day(d.winner)}"))
            if d.field == "answer" and d.rule == "grid":
                for value, src in d.candidates.items():
                    for origin in set(src.values()):
                        decided[origin] += 1
                        if value != d.winner:
                            lost[origin] += 1
        if write and disputes:
            record(puzzle["id"], disputes)
            fixed = apply(puzzle, disputes)
            if fixed != puzzle:
                fetch_puzzle.write_puzzle_file(path, fixed)
    print("coverage (puzzles with a record, by source and series):")
    for (origin, series), n in sorted(per_source.items()):
        print(f"  {origin:16} {series:14} {n}")
    print("outcomes:")
    for (f, kind, rule), n in sorted(fields.items(), key=str):
        print(f"  {f:7} {kind:8} {rule:11} {n}")
    print("answer disputes settled by the grid, lost / took part, by origin:")
    for origin, n in decided.most_common():
        print(f"  {origin:16} {lost[origin]}/{n}")
    print(f"records dropped as another puzzle's: {len(misfiled)}")
    for line in misfiled:
        print("  " + line)
    print("disputes:")
    for _rule, line in sorted(shown):
        print("  " + line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("puzzles", nargs="*", help="puzzle ids to report on")
    ap.add_argument("--sweep", action="store_true", help="every puzzle in the corpus")
    ap.add_argument("--apply", action="store_true", help="write what the sweep resolves")
    ap.add_argument("--download", action="store_true", help="fetch georgeho's database")
    args = ap.parse_args(argv)
    if args.download:
        download_georgeho()
    if args.sweep:
        return sweep(write=args.apply)
    import fetch_puzzle
    for pid in args.puzzles:
        puzzle = fetch_puzzle.read_puzzle_file(fetch_puzzle.resolve_puzzle(pid))
        for d in resolve(puzzle):
            print(describe(puzzle["id"], d), "=>", d.rule, d.winner)


if __name__ == "__main__":
    sys.exit(main())
