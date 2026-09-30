#!/usr/bin/env python3
"""What Cracking the Cryptic's solvers praise and complain about, clue by clue.

Reads YouTube subtitle files (.vtt) of the channel's crossword solves, finds
the moments a solver reacts to a clue, and ties each moment to the clue in our
corpus so its annotated device type can be counted against the puzzle's base
rate.

  1. Dedupe. Auto captions roll: each cue repeats the previous line and adds
     a few words. A line is kept only when it differs from the last one kept.
  2. Match the video to a puzzle by what is said, not by the title: every
     corpus answer of 4+ letters that is spoken counts for its puzzle, and the
     puzzle with the largest share of its answers spoken wins (at least
     MIN_SHARE of them, so a sudoku or a chat video matches nothing).
  3. Moments. PRAISE and DISLIKE regexes over the deduped lines; hits within
     MERGE_S seconds of each other are one moment, with WINDOW_S seconds of
     text either side kept as context.
  4. Clue. The moment's clue is the matched puzzle's answer spoken closest
     before the reaction (solvers praise a clue just after solving it), else
     the closest one just after.

  python3 tools/ctc_transcripts.py extract SUBS_DIR TITLES.tsv   # -> tools/data/ctc_moments.json
  python3 tools/ctc_transcripts.py packets N                     # unjudged reacted-to clues, N batches, for tools/ctc_reasons_prompt.md
  python3 tools/ctc_transcripts.py merge                         # judge answers in the cache -> tools/data/ctc_reasons.json
  python3 tools/ctc_transcripts.py report                        # counts, needs tools/data/ctc_reasons.json
  python3 tools/ctc_transcripts.py solves SUBS_DIR              # -> tools/data/ctc_solve_times.json
  python3 tools/ctc_transcripts.py solvecheck                    # our per-clue difficulty vs those solves

Solve times. A clue is read when its number and direction ("ten across") or
three consecutive words of its text are first said; it is solved at the first
mention of its answer from READ_SLACK_S before that on, so an incidental
earlier use of the word does not count. A clue whose reading is never heard
is solved at the first mention another follows within CLUSTER_S. Its seconds
are the gap since the previous solve, its wait the time from reading to
solving; the last STUCK_TAIL of a video's solves, or a solve beside "last
one" / "stuck" in its second half, is stuck. solvecheck ranks everything
within each video, so a puzzle's pace cancels.

TITLES.tsv is `id<TAB>title` per video, from `yt-dlp --flat-playlist`.
The reasons file maps a moment id to {"reasons": [...], "quote": "..."}.
"""
import collections
import glob
import html
import itertools
import json
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "ctc_moments.json"
REASONS = ROOT / "tools" / "data" / "ctc_reasons.json"
PACKETS = Path("/data/home/cache/ctc/packets")

MIN_SHARE = 0.45
DATED_SHARE = 0.15
WINDOW_S = 30
MERGE_S = 20
BEFORE_S = 60   # how far back a reaction can reach for its clue
AFTER_S = 15

PRAISE = re.compile(
    r"what a (?:lovely |great |brilliant |beautiful |wonderful |fantastic )?clue|"
    r"\blovely\b|\bbrilliant\b|\bbeautiful\b|\bbeautifully\b|clue of the (?:day|puzzle|week|year)|"
    r"i (?:really )?love (?:that|this|it)\b|\bgorgeous\b|\bclever\b|penny (?:drop|has dropped|dropped)|"
    r"\bdelightful\b|\bmagnificent\b|\bwonderful\b|\bgenius\b|\bsuperb\b|\[laughter\]|\bha ha\b",
    re.IGNORECASE)
DISLIKE = re.compile(
    r"\bunfair\b|\bobscure\b|(?:do not|don't|didn't) (?:really )?like (?:that|this|it)\b|"
    r"\bnot keen\b|\bdubious\b|\bnever heard of\b|\bgeneral knowledge\b|\bweak\b|\bclunky\b|"
    r"\bharsh\b|bit of a stretch|not (?:a )?(?:big )?fan|not (?:entirely )?convinced|\bquibble\b|\bnaughty\b",
    re.IGNORECASE)

TS = re.compile(r"(\d+):(\d\d):(\d\d)\.(\d+)\s+-->")
TAG = re.compile(r"<[^>]+>")


def parse_vtt(path):
    """[(seconds, line)] with the rolling-caption repeats removed."""
    out, last, t = [], None, 0.0
    for raw in Path(path).read_text(errors="replace").splitlines():
        m = TS.match(raw)
        if m:
            h, mi, s, ms = m.groups()
            t = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000
            continue
        line = html.unescape(TAG.sub("", raw)).strip()
        if not line or line in ("WEBVTT",) or line.startswith(("Kind:", "Language:")):
            continue
        if line == last:
            continue
        out.append((t, line))
        last = line
    return out


def norm(text):
    return re.sub(r"[^A-Z ]+", " ", text.upper().replace("'", "").replace("’", ""))


def words_of(solution, enumeration):
    """Split a solution into its spoken words using the enumeration."""
    lens = [int(n) for n in re.findall(r"\d+", enumeration or "")]
    if sum(lens) != len(solution) or not lens:
        return [solution]
    out, i = [], 0
    for n in lens:
        out.append(solution[i:i + n])
        i += n
    return out


def load_corpus():
    """{puzzle_id: puzzle} for every dated puzzle file, and the answer index."""
    puzzles, index = {}, collections.defaultdict(set)
    for f in glob.glob(str(ROOT / "puzzles" / "*" / "[12][0-9][0-9][0-9]" / "*.json")):
        try:
            p = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        ents = [e for e in p.get("entries", []) if e.get("solution")]
        if len(ents) < 8:
            continue
        p["_phrases"] = []
        for e in ents:
            phrase = " ".join(words_of(e["solution"].upper(), e.get("clue", {}).get("enumeration")))
            e["_phrase"] = phrase
            if len(e["solution"]) >= 4:
                p["_phrases"].append(phrase)
                index[phrase.split()[0]].add(p["id"])
        puzzles[p["id"]] = p
    return puzzles, index


MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
TITLE_SERIES = [("sunday times", "sundaytimes"), ("times", "times"), ("guardian", "cryptic"),
                ("telegraph", "telegraph"), ("toughie", "toughie"), ("independent", "independent"),
                ("financial times", "ftcryptic"), ("everyman", "everyman")]


def title_facts(title):
    """(series or None, ISO date or None) named in a video title."""
    low = title.lower()
    series = next((s for k, s in TITLE_SERIES if k in low), None)
    m = (re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*,?\s+(20\d\d)", low)
         or re.search(r"([a-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)", low))
    date = None
    if m:
        a, b, y = m.groups()
        day, mon = (a, b) if a.isdigit() else (b, a)
        if mon in MONTHS:
            date = f"{y}-{MONTHS[mon]:02d}-{int(day):02d}"
    return series, date


def match_puzzle(text, puzzles, index, title=""):
    """(share of answers spoken, puzzle id or None).

    The best share wins; within 0.1 of it, the series the title names wins,
    then the title's date (the Globe and Mail reprints the Times, so the same
    answers can sit in two files). A puzzle carrying the title's date and
    series needs only DATED_SHARE: short vlogs talk through a few clues."""
    t_series, t_date = title_facts(title)
    padded = " " + text + " "
    wordset = set(text.split())
    cands = collections.Counter()
    for w in wordset:
        for pid in index.get(w, ()):
            cands[pid] += 1
    scored = []
    for pid, _ in cands.most_common(400):
        ph = puzzles[pid]["_phrases"]
        if ph:
            scored.append((sum(1 for x in ph if " " + x + " " in padded) / len(ph), pid))
    if not scored:
        return 0.0, None
    top = max(s for s, _ in scored)
    dated = [(s, pid) for s, pid in scored if t_date and puzzles[pid].get("date") == t_date
             and (not t_series or puzzles[pid].get("series") == t_series)]
    if dated and max(dated)[0] >= DATED_SHARE:
        return max(dated)
    if top < MIN_SHARE:
        return top, None
    near = [(s, pid) for s, pid in scored if s >= top - 0.1]
    near.sort(key=lambda x: (puzzles[x[1]].get("series") == t_series, x[0]), reverse=True)
    return near[0]


def moments_of(lines, pat):
    hits = [(t, m.group(0).lower()) for t, line in lines for m in pat.finditer(line)]
    groups = []
    for t, w in hits:
        if groups and t - groups[-1]["t_end"] <= MERGE_S:
            groups[-1]["t_end"] = t
            groups[-1]["triggers"].append(w)
        else:
            groups.append({"t": t, "t_end": t, "triggers": [w]})
    return groups


def window(lines, t0, t1):
    return " ".join(l for t, l in lines if t0 - WINDOW_S <= t <= t1 + WINDOW_S)


def locate_clue(lines, puzzle, t):
    """The entry whose answer was spoken closest before t (else just after)."""
    best = None
    for e in puzzle["entries"]:
        if len(e.get("solution", "")) < 3:
            continue
        ph = " " + e["_phrase"] + " "
        for lt, l in lines:
            if not (t - BEFORE_S <= lt <= t + AFTER_S):
                continue
            if ph in " " + norm(l) + " ":
                # before the reaction beats after it; nearer beats further
                d = (t - lt) if lt <= t else (lt - t) * 3
                if best is None or d < best[0]:
                    best = (d, e)
    return best[1] if best else None


def entry_record(e):
    a = e.get("annotation") or {}
    return {
        "clue": e["clue"]["text"], "enumeration": e["clue"].get("enumeration"),
        "answer": e["solution"], "number": e["number"], "direction": e["direction"],
        "types": a.get("type") or [], "features": a.get("features") or {},
    }


def extract(subs_dir, titles_tsv):
    titles = {}
    for row in Path(titles_tsv).read_text().splitlines():
        parts = row.rstrip("\n").replace("\\t", "\t").split("\t")
        if len(parts) >= 2:
            titles[parts[0]] = parts[1]
    puzzles, index = load_corpus()
    videos, moments = [], []
    for f in sorted(glob.glob(str(Path(subs_dir) / "*.vtt"))):
        vid = Path(f).name.split(".")[0]
        lines = parse_vtt(f)
        text = norm(" ".join(l for _, l in lines))
        share, pid = match_puzzle(text, puzzles, index, titles.get(vid, ""))
        videos.append({"video": vid, "title": titles.get(vid, ""), "puzzle": pid,
                       "answers_spoken": round(share, 2), "lines": len(lines)})
        for kind, pat in (("praise", PRAISE), ("dislike", DISLIKE)):
            for g in moments_of(lines, pat):
                rec = {"id": f"{vid}@{int(g['t'])}", "video": vid, "kind": kind,
                       "t": int(g["t"]), "triggers": g["triggers"], "puzzle": pid,
                       "window": window(lines, g["t"], g["t_end"])}
                e = locate_clue(lines, puzzles[pid], g["t"]) if pid else None
                rec["entry"] = entry_record(e) if e else None
                if not e:
                    rec.pop("window")  # nothing downstream reads an untied window
                moments.append(rec)
    base = collections.Counter()
    for pid in {v["puzzle"] for v in videos if v["puzzle"]}:
        for e in puzzles[pid]["entries"]:
            for ty in (e.get("annotation") or {}).get("type") or ["unannotated"]:
                base[ty] += 1
    OUT.write_text(json.dumps({"videos": videos, "base_types": dict(base),
                               "moments": moments}, indent=1, ensure_ascii=False) + "\n")
    matched = sum(1 for v in videos if v["puzzle"])
    tied = sum(1 for m in moments if m["entry"])
    print(f"{len(videos)} videos, {matched} matched to a puzzle; "
          f"{len(moments)} moments, {tied} tied to a clue -> {OUT}")


def clue_moments(data):
    """One row per (video, clue): a clue praised twice in a video is one clue."""
    rows = {}
    for m in data["moments"]:
        if not m["entry"]:
            continue
        key = (m["video"], m["entry"]["number"], m["entry"]["direction"])
        r = rows.setdefault(key, {"id": m["id"], "kind": set(), "triggers": [],
                                  "entry": m["entry"], "puzzle": m["puzzle"],
                                  "windows": []})
        r["kind"].add(m["kind"])
        r["triggers"] += m["triggers"]
        r["windows"].append(m["window"])
    return list(rows.values())


def packets(n):
    data = json.loads(OUT.read_text())
    done = json.loads(REASONS.read_text()) if REASONS.exists() else {}
    rows = [r for r in clue_moments(data) if r["id"] not in done]
    PACKETS.mkdir(parents=True, exist_ok=True)
    for old in PACKETS.glob("*.jsonl"):
        old.unlink()
    size = -(-len(rows) // n)
    for i in range(n):
        chunk = rows[i * size:(i + 1) * size]
        with open(PACKETS / f"batch{i:02d}.jsonl", "w") as fh:
            fh.writelines(json.dumps({
                    "id": r["id"], "clue": r["entry"]["clue"], "enumeration": r["entry"]["enumeration"],
                    "answer": r["entry"]["answer"], "triggers": r["triggers"],
                    "transcript": " ... ".join(r["windows"])[:2500]}, ensure_ascii=False) + "\n" for r in chunk)
    print(f"{len(rows)} unjudged clues in {n} packets under {PACKETS}")


def merge():
    """Fold the judge's per-packet answers into REASONS."""
    done = json.loads(REASONS.read_text()) if REASONS.exists() else {}
    for f in sorted((PACKETS.parent / "reasons").glob("*.json")):
        done.update(json.loads(f.read_text()))
    REASONS.write_text(json.dumps(done, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{len(done)} judged clues in {REASONS}")


def feature_keys(e):
    """The annotation features that are set, as countable labels."""
    out = []
    for k, v in (e.get("features") or {}).items():
        if v and k != "misdirectedWord":
            out.append(f"{k}={v}" if isinstance(v, str) else k)
        elif v:
            out.append("misdirectedWord")
    return out


def binom_p(k, n, p):
    """Two-sided exact binomial p-value: k of n where the base rate is p."""
    if n == 0 or p <= 0 or p >= 1:
        return 1.0
    probs = [math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(n + 1)]
    return min(1.0, sum(q for q in probs if q <= probs[k] * (1 + 1e-9)))


def report(top=25):
    """Device and feature lift of reacted-to clues over their own puzzles.

    With a reasons file, a clue counts under the judge's verdict and a `none`
    verdict (the trigger word was about something else) drops it; without one,
    under the regex kind."""
    data = json.loads(OUT.read_text())
    reasons = json.loads(REASONS.read_text()) if REASONS.exists() else {}
    rows = clue_moments(data)
    puzzles, _ = load_corpus()
    # Unannotated clues have no type to count, so they leave both sides.
    rows = [r for r in rows if r["entry"]["types"]]
    base_t, base_f, nbase, base_w = collections.Counter(), collections.Counter(), 0, []
    for pid in {r["puzzle"] for r in rows}:
        for e in puzzles[pid]["entries"]:
            rec = entry_record(e)
            if not rec["types"]:
                continue
            nbase += 1
            base_w.append(len(rec["clue"].split()))
            base_t.update(set(rec["types"]))
            base_f.update(set(feature_keys(rec)))
    for r in rows:
        v = reasons.get(r["id"], {}).get("verdict")
        r["verdict"] = v if reasons else ("dislike" if "dislike" in r["kind"] else "praise")
    for kind in ("praise", "dislike"):
        sel = [r for r in rows if r["verdict"] == kind]
        n = len(sel) or 1
        print(f"\n{kind}: {len(sel)} clues (of {nbase} in the same puzzles). "
              "share of clues with the label, vs share in the same puzzles")
        if sel:
            w = [len(r["entry"]["clue"].split()) for r in sel]
            print(f"  clue words: mean {sum(w) / len(w):.2f} vs {sum(base_w) / len(base_w):.2f} in the same puzzles")
        for label, counter, basec in (("type", collections.Counter(t for r in sel for t in set(r["entry"]["types"])), base_t),
                                      ("feature", collections.Counter(f for r in sel for f in set(feature_keys(r["entry"]))), base_f)):
            for t, c in counter.most_common(14):
                b = basec[t] / nbase
                print(f"  {label:7s} {t:28s} {c:4d} {c / n:6.1%}  base {b:6.1%}  "
                      f"lift {c / n / b if b else 0:4.2f}  p {binom_p(c, len(sel), b):.3f}")
        rc = collections.Counter(x for r in sel for x in reasons.get(r["id"], {}).get("reasons", []))
        print("  reasons:", ", ".join(f"{x} {c}" for x, c in rc.most_common()))
    print(f"\ntop {top} praised (most trigger hits first):")
    sel = sorted((r for r in rows if r["verdict"] == "praise"), key=lambda r: -len(r["triggers"]))
    for r in sel[:top]:
        e, why = r["entry"], reasons.get(r["id"], {})
        print(f"  {e['clue']} ({e['enumeration']}) {e['answer']} [{'/'.join(e['types'])}] "
              f"{','.join(why.get('reasons', []))}: \"{why.get('quote', '')}\"  <{r['id']}>")

SOLVES = ROOT / "tools" / "data" / "ctc_solve_times.json"
#: An answer said this long before its clue is first read still counts as the
#: solve: a solver often names the answer mid-reading.
READ_SLACK_S = 5
#: A clue whose reading is never heard is timed from the first mention of its
#: answer that another mention follows within this: an incidental use of the
#: word stands alone, a solve is explained.
CLUSTER_S = 90
#: A video is timed only when this many of its puzzle's clues are, and this share.
MIN_TIMED, MIN_TIMED_SHARE = 8, 0.4
#: The solved-last share of a video's clues flagged stuck.
STUCK_TAIL = 0.9
#: A solve within LAST_ONE_S of one of these, in the second half of the solve, is stuck too.
LAST_ONE = re.compile(r"\b(?:last (?:one|clue|answer)|final (?:one|clue|answer)|"
                      r"stuck|loi|haven.?t got|can.?t (?:get|see|do))\b", re.IGNORECASE)
LAST_ONE_S = 45
STOP = {"A", "AN", "THE", "OF", "IN", "ON", "TO", "FOR", "AND", "OR", "BY", "WITH", "AT", "IS", "IT",
        "AS", "FROM", "THAT", "THIS", "BE", "ARE", "WAS", "S", "ITS"}
_UNITS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
NUMBER_WORDS = {w: i + 1 for i, w in enumerate(
    _UNITS + ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
              "seventeen", "eighteen", "nineteen"])}
for _tens, _v in (("twenty", 20), ("thirty", 30)):
    NUMBER_WORDS[_tens] = _v
    NUMBER_WORDS.update({f"{_tens} {u}": _v + i + 1 for i, u in enumerate(_UNITS)})
CLUE_REF = re.compile(r"\b(\d{1,2}|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
                      + r")[\s-]*(across|a?cross|down)\b", re.IGNORECASE)


def token_stream(lines):
    """(tokens, their line times, {token: [positions]}) over norm()'d lines."""
    toks, times, where = [], [], collections.defaultdict(list)
    for t, line in lines:
        for w in norm(line).split():
            where[w].append(len(toks))
            toks.append(w)
            times.append(t)
    return toks, times, where


def phrase_times(words, toks, times, where):
    """The times of every occurrence of the word sequence, in order."""
    n = len(words)
    return [times[i] for i in where.get(words[0], ()) if toks[i:i + n] == words]


def clue_read_time(e, stream, refs):
    """When the clue is first read: its number and direction said, or any
    three consecutive words of its text with a content word among them."""
    toks, times, where = stream
    cw = norm(re.sub(r"<[^>]+>", " ", e["clue"].get("text", ""))).split()
    ts = [refs[(e["number"], e["direction"])]] if (e["number"], e["direction"]) in refs else []
    for i in range(len(cw) - 2):
        g = cw[i:i + 3]
        if any(len(w) >= 4 and w not in STOP for w in g):
            ts += phrase_times(g, toks, times, where)[:1]
    return min(ts) if ts else None


def solve_time(mentions, read):
    """(the solve moment, whether the clue's reading anchored it) or None."""
    if read is not None:
        after = [m for m in mentions if m >= read - READ_SLACK_S]
        return (after[0], True) if after else None
    for a, b in itertools.pairwise(mentions):
        if b - a <= CLUSTER_S:
            return a, False
    return (mentions[0], False) if mentions else None


def _spearman(a, b):
    ra, rb = (_ranks(x) for x in (a, b))
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return cov / va if va else 0.0


def _ranks(xs):
    """Mid-ranks, ties shared, scaled 0-1."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 / max(1, len(xs) - 1)
        i = j + 1
    return out


def time_video(lines, puz):
    """(per-clue solve rows in solve order, video facts) for one matched video."""
    stream = token_stream(lines)
    refs = {}
    for t, line in lines:
        for m in CLUE_REF.finditer(line):
            num = m.group(1).lower()
            n = int(num) if num.isdigit() else NUMBER_WORDS[re.sub(r"[\s-]+", " ", num)]
            refs.setdefault((n, "down" if m.group(2).lower() == "down" else "across"), t)
    last_one = [t for t, line in lines if LAST_ONE.search(line)]
    rows = []
    for e in puz["entries"]:
        if len(e.get("solution", "")) < 3 or re.match(r"(?i)see\b", e["clue"].get("text", "").strip()):
            continue
        read = clue_read_time(e, stream, refs)
        st = solve_time(phrase_times(e["_phrase"].split(), *stream), read)
        if st:
            rows.append({"entry": f"{e['number']}-{e['direction']}", "answer": e["solution"],
                         "t": round(st[0], 1), "read": None if read is None else round(read, 1),
                         "anchored": st[1]})
    graded = [e for e in puz["entries"] if len(e.get("solution", "")) >= 3]
    facts = {"entries": len(graded), "timed": len(rows)}
    if len(rows) < MIN_TIMED or len(rows) < MIN_TIMED_SHARE * len(graded):
        return [], facts
    rows.sort(key=lambda r: r["t"])
    start = min([r["read"] for r in rows if r["read"] is not None] + [rows[0]["t"]])
    prev = start
    for i, r in enumerate(rows):
        r["order"] = i + 1
        r["seconds"] = round(r["t"] - prev, 1)
        r["read_to_solve"] = None if r["read"] is None else round(r["t"] - r["read"], 1)
        r["rank"] = round(i / (len(rows) - 1), 3)
        r["stuck"] = r["rank"] >= STUCK_TAIL or (
            r["rank"] >= 0.5 and any(abs(t - r["t"]) <= LAST_ONE_S for t in last_one))
        prev = r["t"]
    grid = sorted(rows, key=lambda r: (r["entry"].split("-")[1], int(r["entry"].split("-")[0])))
    pos = {r["entry"]: i for i, r in enumerate(grid)}
    facts.update(start=round(start, 1), end=rows[-1]["t"],
                 anchored=sum(r["anchored"] for r in rows),
                 order_vs_grid=round(_spearman([r["order"] for r in rows], [pos[r["entry"]] for r in rows]), 3))
    return rows, facts


def solves(subs_dir):
    """Per-clue solve moments for every matched video -> SOLVES."""
    data = json.loads(OUT.read_text())
    puzzles, _ = load_corpus()
    videos, clues = [], []
    for v in data["videos"]:
        if not v["puzzle"] or v["puzzle"] not in puzzles:
            continue
        f = Path(subs_dir) / f"{v['video']}.en.vtt"
        if not f.exists():
            continue
        rows, facts = time_video(parse_vtt(f), puzzles[v["puzzle"]])
        videos.append({"video": v["video"], "puzzle": v["puzzle"], **facts})
        clues += [{"video": v["video"], "puzzle": v["puzzle"], **r} for r in rows]
    row = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    SOLVES.write_text('{"videos":[\n' + ",\n".join(map(row, videos)) + '\n],\n"clues":[\n'
                      + ",\n".join(map(row, clues)) + "\n]}\n")
    used = sum(1 for v in videos if "start" in v)
    print(f"{len(videos)} matched videos, {used} timed; {len(clues)} clues timed, "
          f"{sum(c['anchored'] for c in clues)} anchored to their reading, "
          f"{sum(c['stuck'] for c in clues)} stuck -> {SOLVES}")


#: Per-clue ingredients of tools/difficulty.py's index, each with the weight
#: of the puzzle component it is the per-clue form of (higher = harder).
CLUE_WEIGHTS = {"unchecked": "checking", "rarity": "rarity", "cost": "device",
                "machinery": "machinery", "question_mark": "question_marks",
                "unrelated": "definition_unrelated"}


def clue_features(puz, rank, blog_defs):
    """{entry id: {feature: value or None}} for one puzzle, from what the
    difficulty index reads per clue before it averages over the grid."""
    import difficulty as D
    used = collections.Counter()
    cells = {}
    for e in puz["entries"]:
        dx, dy = (1, 0) if e["direction"] == "across" else (0, 1)
        cells[D.entry_id(e)] = [(e["position"]["x"] + dx * i, e["position"]["y"] + dy * i)
                                for i in range(e["length"])]
        used.update(cells[D.entry_id(e)])
    bd = blog_defs.get(puz["id"], {})
    out = {}
    for e in puz["entries"]:
        eid = D.entry_id(e)
        sol, ws = D.answer_words(e)
        if not sol:
            continue
        r = rank[sol] if sol in rank else max(rank.get(w, D.MISSING_RANK) for w in ws)
        d = bd.get(eid) or D.definition_key(D.definitions.texts(e.get("annotation")))
        rel = D.definition_related("_".join(w.lower() for w in ws), d) if d else None
        clue = e["clue"].get("text", "").strip().rstrip("\"'”’)")
        out[eid] = {"unchecked": sum(used[c] < 2 for c in cells[eid]) / len(cells[eid]),
                    "rarity": math.log10(max(r, 10)),
                    "cost": D.clue_cost(e), "machinery": D.clue_machinery(e),
                    "question_mark": float(clue.endswith("?") and not D.acrostic(sol, clue)),
                    "unrelated": None if rel is None else float(not rel),
                    "length": len(sol)}
    return out


#: CtC's per-clue measures, higher = harder: solve rank, gap since the last
#: solve, stuck, rank minus the clue's place in grid order (solvers read the
#: clues in order, so an early clue is solved early whatever it is like), and
#: the wait from first reading the clue to solving it.
CTC_MEASURES = ("ctc_rank", "ctc_seconds", "ctc_stuck", "ctc_delay", "ctc_wait")


def grid_rank(rows):
    """Each row's place in reading order, acrosses then downs, scaled 0-1."""
    return _ranks([(r["entry"].split("-")[1], int(r["entry"].split("-")[0])) for r in rows])


def _rho_p(a, b):
    """Spearman rho and its two-sided normal-approximation p."""
    r = _spearman(a, b)
    return r, len(a), math.erfc(abs(r) * math.sqrt(max(1, len(a) - 1)) / math.sqrt(2))


def solve_table():
    """Our per-clue difficulty ingredients against CtC's solve order, within
    each video so a puzzle's overall difficulty and pace cancel; and CtC
    against the Times for the Times comments' hard/LOI flags on the same
    clues. The tables solvecheck() prints: within-video percentiles, pooled."""
    import puzzle_paths
    from fetch_puzzle import puzzle_is_annotated, read_puzzle_file

    import difficulty as D
    data = json.loads(SOLVES.read_text())
    tftt = json.loads((ROOT / "tools/data/blog_comment_difficulty.json").read_text())
    rank, blog_defs = D.ranks(), D.blog_definitions()
    by_video = collections.defaultdict(list)
    for c in data["clues"]:
        by_video[c["video"]].append(c)
    cols = {k: collections.defaultdict(list) for k in ("all", "annotated")}
    per_video = collections.defaultdict(list)
    human = collections.defaultdict(list)
    held = []
    for rows in by_video.values():
        puz = read_puzzle_file(puzzle_paths.find(rows[0]["puzzle"]))
        feats = clue_features(puz, rank, blog_defs)
        rows = [r for r in rows if r["entry"] in feats]
        if len(rows) < MIN_TIMED:
            continue
        ann = puzzle_is_annotated(puz)
        pct = {"ctc_rank": _ranks([r["rank"] for r in rows]),
               "ctc_seconds": _ranks([r["seconds"] for r in rows]),
               "ctc_stuck": [float(r["stuck"]) for r in rows],
               "ctc_delay": _ranks([r["rank"] - g for r, g in zip(rows, grid_rank(rows))]),
               "ctc_wait": _ranks([r["read_to_solve"] if r["read_to_solve"] is not None else r["seconds"]
                                   for r in rows])}
        names = list(CLUE_WEIGHTS) + ["length"]
        for f in names:
            vals = [feats[r["entry"]][f] for r in rows]
            known = [i for i, x in enumerate(vals) if x is not None]
            p = _ranks([vals[i] for i in known]) if len(known) >= MIN_TIMED else []
            pct[f] = [None] * len(rows)
            for i, x in zip(known, p):
                pct[f][i] = x
        comp = []
        for i in range(len(rows)):
            parts = [(D.WEIGHTS[w], pct[f][i]) for f, w in CLUE_WEIGHTS.items() if pct[f][i] is not None]
            comp.append(sum(w * x for w, x in parts) / sum(w for w, _ in parts) if parts else None)
        pct["composite"] = comp
        for f in names + ["composite"]:
            pairs = [(pct[f][i],) + tuple(pct[m][i] for m in CTC_MEASURES)
                     for i in range(len(rows)) if pct[f][i] is not None]
            for key in ("all",) + (("annotated",) if ann else ()):
                cols[key][f] += pairs
            if f == "composite" and len(pairs) >= MIN_TIMED:
                wait = 1 + CTC_MEASURES.index("ctc_wait")
                per_video["annotated" if ann else "unannotated"].append(
                    _spearman([p[0] for p in pairs], [p[wait] for p in pairs]))
                held += [(comp[i], pct["ctc_wait"][i], pct["length"][i])
                         for i in range(len(rows)) if comp[i] is not None]
        t = tftt.get(rows[0]["puzzle"])
        if t and t["comments"] >= 10:
            n = [t["clues"].get(r["entry"], [0, 0, 0]) for r in rows]
            for m in CTC_MEASURES:
                human[(m, "hard")] += list(zip(pct[m], _ranks([x[1] for x in n])))
                human[(m, "loi")] += list(zip(pct[m], _ranks([x[2] for x in n])))
    return SimpleNamespace(videos=len(by_video), clues=len(data["clues"]), cols=cols,
                           per_video=per_video, held=held, human=human)


def partial_rho(held):
    """Spearman of the first column with the second, the third held."""
    x, y, z = zip(*held)
    rxy, rxz, ryz = _spearman(x, y), _spearman(x, z), _spearman(y, z)
    part = (rxy - rxz * ryz) / math.sqrt((1 - rxz ** 2) * (1 - ryz ** 2))
    return part, len(held), math.erfc(abs(part) * math.sqrt(len(held) - 2) / math.sqrt(2))


def solvecheck():
    t = solve_table()
    cols, per_video, held, human = t.cols, t.per_video, t.held, t.human
    print(f"{t.videos} timed videos, {t.clues} timed clues. Within-video percentiles, pooled; "
          "rho of each feature against each of CTC_MEASURES")
    for key, table in cols.items():
        print(f"\n{key}:")
        for f, pairs in table.items():
            outs = [_rho_p([p[0] for p in pairs], [p[j + 1] for p in pairs]) for j in range(len(CTC_MEASURES))]
            print(f"  {f:13s} n={outs[0][1]:5d}  " + "  ".join(
                f"{lab[4:]} {r:+.3f} (p={p:.2g})" for lab, (r, _, p) in zip(CTC_MEASURES, outs)))
    print("\ncomposite vs wait with answer length held: partial rho {:+.3f} (n={}, p={:.2g})".format(
        *partial_rho(held)))
    for key, rs in per_video.items():
        print(f"composite vs wait per {key} video: median rho {sorted(rs)[len(rs) // 2]:+.3f}, "
              f"{sum(r > 0 for r in rs)}/{len(rs)} positive")
    print("\nCtC vs Times for the Times comments (puzzles with 10+ comments), within puzzle:")
    for k, pairs in human.items():
        r, n, p = _rho_p([a for a, _ in pairs], [b for _, b in pairs])
        print(f"  {k[0]:11s} vs {k[1]:4s} rho {r:+.3f} (n={n}, p={p:.2g})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "solves":
        solves(sys.argv[2])
        sys.exit()
    if cmd == "solvecheck":
        sys.path.insert(0, str(ROOT / "tools"))
        solvecheck()
        sys.exit()
    if cmd == "extract":
        extract(sys.argv[2], sys.argv[3])
    elif cmd == "packets":
        packets(int(sys.argv[2]))
    elif cmd == "merge":
        merge()
    elif cmd == "report":
        report()
    else:
        sys.exit(__doc__)
