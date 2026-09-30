#!/usr/bin/env python3
"""What YouTube solvers praise, wait on, explain and get unstuck by, clue by clue.

Cracking the Cryptic first, then every channel in CHANNELS, each tagged with
its solver's skill.

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
  python3 tools/ctc_transcripts.py parsecheck SUBS_DIR          # our parses vs the solvers' explanations -> tools/data/ctc_parse_check.json
  python3 tools/ctc_transcripts.py unstick SUBS_DIR             # what unlocked each hard solve, against the hint ladder -> tools/data/ctc_unstick.json
  python3 tools/ctc_transcripts.py --channel SLUG[,SLUG] CMD      # any of the above for other channels; SUBS_DIR defaults to theirs
  python3 tools/ctc_transcripts.py --channel all solvecheck     # our difficulty vs every channel's waits, by skill -> tools/data/yt_solvers/skill_check.json
  python3 tools/ctc_transcripts.py --channel all unstick        # unstick per channel, then by skill -> tools/data/yt_solvers/unstick_by_skill.json

Solve times. A clue is read when its number and direction ("ten across") or
three consecutive words of its text are first said; it is solved at the first
mention of its answer from READ_SLACK_S before that on, so an incidental
earlier use of the word does not count. A clue whose reading is never heard
is solved at the first mention another follows within CLUSTER_S. Its seconds
are the gap since the previous solve, its wait the time from reading to
solving; the last STUCK_TAIL of a video's solves, or a solve beside "last
one" / "stuck" in its second half, is stuck. solvecheck ranks everything
within each video, so a puzzle's pace cancels.

Parse check. A clue's explanation is what is said from just before its solve
to EXPLAIN_TAIL_S after, cut where the solver turns to another clue (says its
number or reads three words of it). Each annotated clue gets agree, disagree
or unknown per field: definition (clue words the solver calls the
definition), type (a device named that we lack, or one of ours named),
fodder (the clue words said after "anagram of") and pieces (a short block's
letters heard beside its clue words). Silence is unknown, never agreement.

Unstick. A hard solve (stuck, or waited LONG_WAIT_S from reading) is
unlocked by what is said in the UNLOCK_LEAD_S before it, with the clue read
aloud dropped: the definition, an indicator, a device named, a short piece,
letters already in the grid, or a word read in its other sense. Each unlock
credits the rung of app.js's ladder that shows it, and every order of the
rungs is scored by the mean rungs a solver takes to reach one that would have
unstuck them.

TITLES.tsv is `id<TAB>title` per video, from `yt-dlp --flat-playlist`; without
it the titles come from the videos.json playlist dump beside SUBS_DIR. A title's
series with its date or puzzle number lets a short talk-through match.
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

#: Every solve channel: its subtitle cache and its solver's skill, from the
#: channel's own description and pace (SKILLS lists the levels, best first).
#: --channel picks one; the default is Cracking the Cryptic, whose files keep
#: the ctc_ names; the others write tools/data/yt_solvers/<slug>_<kind>.json.
SKILLS = ("expert", "intermediate", "beginner")
#: Explainers talk through a finished puzzle with no solve to time, so they
#: are kept out of solvecheck and unstick and serve parsecheck alone (their
#: solve_times file only holds the clue timestamps parsecheck reads).
EXPLAINER = "explainer"
CHANNELS = {
    "ctc": ("Cracking the Cryptic", "expert", "/data/home/cache/ctc/subs"),
    "pat_cousins": ("Pat Cousins", "expert", "/data/home/cache/yt_solvers/pat_cousins/subs"),
    "cryptics_uncovered": ("Cryptics Uncovered", "intermediate", "/data/home/cache/yt_solvers/cryptics_uncovered/subs"),
    "lucyverbalist": ("Lucyverbalist", "intermediate", "/data/home/cache/yt_solvers/lucyverbalist/subs"),
    "dhansak": ("Dhansak Crosswords", "intermediate", "/data/home/cache/yt_solvers/dhansak/subs"),
    "solving_telegraph_cryptic": ("Solving The Telegraph Cryptic", "beginner",
                                  "/data/home/cache/yt_solvers/solving_telegraph_cryptic/subs"),
    "cryptic_mystic": ("The Cryptic Mystic", "beginner", "/data/home/cache/yt_solvers/cryptic_mystic/subs"),
    "cafe_cryptic": ("Cafe Cryptic", EXPLAINER, "/data/home/cache/yt_solvers/cafe_cryptic/subs"),
    "henderson": ("Henderson Cryptic", EXPLAINER, "/data/home/cache/yt_solvers/henderson/subs"),
    "justcordelia": ("justcordelia", EXPLAINER, "/data/home/cache/yt_solvers/justcordelia/subs"),
    "minute_cryptic": ("Minute Cryptic", EXPLAINER, "/data/home/cache/yt_solvers/minute_cryptic/subs"),
    "morning_cryptic": ("Morning Cryptic", EXPLAINER, "/data/home/cache/yt_solvers/morning_cryptic/subs"),
}
CHANNEL = "ctc"


def data_file(kind, channel=None):
    """The channel's output file of one kind (moments, solve_times, ...)."""
    channel = channel or CHANNEL
    if channel == "ctc":
        return ROOT / "tools" / "data" / f"ctc_{kind}.json"
    return ROOT / "tools" / "data" / "yt_solvers" / f"{channel}_{kind}.json"


def use_channel(channel):
    """Point every subcommand's files at one channel."""
    global CHANNEL, OUT, SOLVES, PARSECHECK, UNSTICK
    if channel not in CHANNELS:
        sys.exit(f"unknown channel {channel!r}; one of {', '.join(CHANNELS)}")
    CHANNEL = channel
    OUT, SOLVES = data_file("moments"), data_file("solve_times")
    PARSECHECK, UNSTICK = data_file("parse_check"), data_file("unstick")
    OUT.parent.mkdir(parents=True, exist_ok=True)


def sub_files(subs_dir):
    """{video id: its .vtt}: the uploaded or translated en track, else the
    auto-caption original."""
    out = {}
    for f in sorted(Path(subs_dir).glob("*.vtt")):
        vid, track = f.name.split(".")[0], f.name.split(".")[1]
        if track == "en" or vid not in out:
            out[vid] = f
    return out


def read_titles(subs_dir, titles_tsv=None):
    """{video id: title} from TITLES.tsv, else the videos.json playlist dump
    beside the subs directory."""
    if titles_tsv:
        titles = {}
        for row in Path(titles_tsv).read_text().splitlines():
            parts = row.rstrip("\n").replace("\\t", "\t").split("\t")
            if len(parts) >= 2:
                titles[parts[0]] = parts[1]
        return titles
    meta = Path(subs_dir).parent / "videos.json"
    if not meta.exists():
        return {}
    return {v["id"]: v.get("title") or "" for v in json.loads(meta.read_text()).get("entries", [])}

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


_CORPUS = []


def load_corpus():
    """{puzzle_id: puzzle} for every dated puzzle file, and the answer index;
    read once per run, so a loop over channels pays for it once."""
    if not _CORPUS:
        _CORPUS.append(_read_corpus())
    return _CORPUS[0]


def _read_corpus():
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
#: (title words, corpus series) in the order tried: a longer name before the
#: one it contains. A series we hold none of maps to a name with no puzzles.
TITLE_SERIES = [("sunday times", "sundaytimes"), ("financial times", "ftcryptic"),
                ("times quick", "timesquick"), ("guardian quick", "guardianquick"),
                ("guardian qc", "guardianquick"), ("quiptic", "quiptic"), ("everyman", "everyman"),
                ("times", "times"), ("guardian", "cryptic"), ("sunday telegraph", "sundaytel"),
                ("toughie", "toughie"), ("telegraph", "telegraph"), ("independent", "independent")]
TITLE_DATE = (re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*,?\s+(20\d\d)"),
              re.compile(r"([a-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)"),
              re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b"))
TITLE_NUMBER = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{3,6})\b")


def title_facts(title):
    """(series or None, ISO date or None, puzzle number or None) named in a
    video title. A slashed date is day first (UK channels)."""
    low = title.lower()
    series = next((s for k, s in TITLE_SERIES if k in low), None)
    date = None
    for pat in TITLE_DATE:
        m = pat.search(low)
        if not m:
            continue
        a, b, y = m.groups()
        day, mon = (a, b) if a.isdigit() else (b, a)
        mon = int(mon) if mon.isdigit() else MONTHS.get(mon)
        if mon and 1 <= mon <= 12:
            date = f"{y}-{mon:02d}-{int(day):02d}"
            low = low[:m.start()] + " " + low[m.end():]
            break
    n = TITLE_NUMBER.search(low)
    return series, date, int(n.group(1).replace(",", "")) if n else None


def match_puzzle(text, puzzles, index, title=""):
    """(share of answers spoken, puzzle id or None).

    The best share wins; within 0.1 of it, the series the title names wins,
    then the title's date (the Globe and Mail reprints the Times, so the same
    answers can sit in two files). A puzzle carrying the title's date and
    series, or the title's series and number, needs only DATED_SHARE: short
    vlogs talk through a few clues."""
    t_series, t_date, t_num = title_facts(title)
    padded = " " + text + " "
    share = lambda pid: sum(1 for x in puzzles[pid]["_phrases"] if " " + x + " " in padded) / max(1, len(puzzles[pid]["_phrases"]))
    if t_series and t_num and f"{t_series}-{t_num}" in puzzles:
        s = share(f"{t_series}-{t_num}")
        if s >= DATED_SHARE:
            return s, f"{t_series}-{t_num}"
    wordset = set(text.split())
    cands = collections.Counter()
    for w in wordset:
        for pid in index.get(w, ()):
            cands[pid] += 1
    scored = []
    for pid, _ in cands.most_common(400):
        if puzzles[pid]["_phrases"]:
            scored.append((share(pid), pid))
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


def extract(subs_dir, titles_tsv=None):
    titles = read_titles(subs_dir, titles_tsv)
    puzzles, index = load_corpus()
    videos, moments = [], []
    for vid, f in sub_files(subs_dir).items():
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
    subs = sub_files(subs_dir)
    videos, clues = [], []
    for v in data["videos"]:
        if not v["puzzle"] or v["puzzle"] not in puzzles:
            continue
        f = subs.get(v["video"])
        if not f:
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
    import difficulty as D
    import puzzle_paths
    from fetch_puzzle import puzzle_is_annotated, read_puzzle_file
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


PARSECHECK = ROOT / "tools" / "data" / "ctc_parse_check.json"
#: A clue's explanation runs from EXPLAIN_LEAD_S before its solve to
#: EXPLAIN_TAIL_S after, cut at the next clue read after the solve.
EXPLAIN_LEAD_S, EXPLAIN_TAIL_S = 5, 30
#: Words a solver names a device by, per clue type. A device named while
#: explaining that our annotation lacks is a disagreement only for the types
#: in NAMED_STRONG; the rest are said too loosely ("around", "without").
TYPE_CUES = {
    "anagram": r"ANAGRAM\w*|REARRANG\w*",
    "hidden_word": r"HIDDEN|LURKING|SPELT OUT|SPELLED OUT",
    "homophone": r"HOMOPHONE\w*|SOUNDS LIKE",
    "double_definition": r"DOUBLE DEF\w*|TWO DEFINITIONS",
    "cryptic_definition": r"CRYPTIC DEF\w*",
    "spoonerism": r"SPOONER\w*",
    "reversal": r"BACKWARDS|REVERS\w*",
    "and_lit": r"AND ?LIT|ALL IN ONE",
    "container": r"INSIDE|AROUND|CONTAIN\w*|SURROUND\w*|OUTSIDE|WITHIN",
    "deletion": r"WITHOUT|LOS[EI]\w*|REMOV\w*|TAKE AWAY|DROP\w*|MINUS|DELET\w*",
    "letter_selection": r"FIRST LETTERS?|LAST LETTERS?|INITIAL\w*|ALTERNATE|ODD LETTERS|EVEN LETTERS",
}
NAMED_STRONG = {"anagram": r"ANAGRAM\w*", "hidden_word": r"HIDDEN WORD|A HIDDEN|HIDDEN IN",
                "homophone": r"HOMOPHONE\w*", "double_definition": r"DOUBLE DEF\w*",
                "cryptic_definition": r"CRYPTIC DEF\w*", "spoonerism": r"SPOONER\w*",
                "reversal": r"BACKWARDS|REVERS\w*"}
HEDGES = {"IF", "MIGHT", "COULD", "MAYBE", "WONDERING", "THOUGHT", "PERHAPS", "SOMETIMES", "WHETHER"}
NEGATORS = {"NOT", "ISNT", "DONT", "NO", "CANT", "WASNT", "DOESNT", "ARENT"}
DEF_SAID = re.compile(
    r"\bDEFINITION (?:HERE |THERE )?(?:IS|BEING|WOULD BE|MUST BE) (?P<after>(?:[A-Z]+ ?){1,4})|"
    r"\bMY DEFINITION (?P<after2>(?:[A-Z]+ ?){1,3})|"
    r"(?P<before>(?:[A-Z]+ ){1,4})(?:IS|BEING|WAS|WOULD BE|AS) (?:THE|MY|OUR) DEFINITION\b")
SPELT = re.compile(r"\b(?:[A-Z] ){1,}[A-Z]\b")
PIECE_SAYS = r"\b(?:IS|FOR|GIVES|GIVING|GIVE|AS|MEANS|BECOMES)\b"


def _named(tokens_str, cue, clue_words):
    """Cue matches in the string not negated and not merely the clue read aloud."""
    hits = []
    for m in re.finditer(r"\b(?:" + cue + r")\b", tokens_str):
        if set(m.group(0).split()) & clue_words:
            continue
        before = tokens_str[:m.start()].split()[-4:]
        if (NEGATORS | HEDGES) & set(before):
            continue
        hits.append(m)
    return hits


def _content(text):
    return {w for w in norm(re.sub(r"<[^>]+>", " ", text)).split() if len(w) >= 3 and w not in STOP}


def _letters(s):
    return re.sub(r"[^A-Z]", "", s.upper())


def check_clue(e, talk):
    """{field: (verdict, evidence)} for one annotated clue against what the
    solver said explaining it; a verdict is agree, disagree or unknown."""
    a = e["annotation"]
    clue = e["clue"].get("text", "")
    cw = _content(clue)
    ans = set(e["_phrase"].split())
    out = {}
    # definition: the clue words a solver names as the definition ("the
    # definition is X", "X being the definition") fall in ours or elsewhere.
    ours = set().union(*(_content(d["text"]) for d in a.get("definitions") or [])) - ans
    rest = cw - ours - ans
    toks = talk.split()
    in_def = in_rest = 0
    ev = []
    for m in DEF_SAID.finditer(talk):
        if NEGATORS & set(talk[:m.start()].split()[-2:]):
            continue
        near = set((m.group("after") or m.group("after2") or m.group("before") or "").split())
        in_def += len(near & ours)
        in_rest += len(near & rest)
        if near & (ours | rest):
            ev.append(m.group(0))
    if not ours or in_def == in_rest:
        out["definition"] = ("unknown", ev[:1])
    else:
        out["definition"] = ("agree" if in_def > in_rest else "disagree", ev[:2])
    # type: each of our types the solver names agrees; a strong type named
    # that we lack disagrees.
    types = set(a.get("type") or [])
    said = {t for t, c in TYPE_CUES.items() if _named(talk, c, cw | ans)}
    strong = {t: h for t, c in NAMED_STRONG.items() if t not in types and (h := _named(talk, c, cw | ans))}
    if strong:
        ev = []
        for t, h in strong.items():
            i = len(talk[:h[0].start()].split())
            ev.append(f"{t}: " + " ".join(toks[max(0, i - 6):i + 8]))
        out["type"] = ("disagree", ev[:2])
    elif types & said:
        out["type"] = ("agree", sorted(types & said))
    else:
        out["type"] = ("unknown", [])
    # fodder: the clue words the solver calls anagram fodder, against ours.
    fod = set()
    for b in a.get("blocks") or []:
        f, g = b.get("clueFragment", ""), b.get("gives") or ""
        if g and sorted(_letters(f)) == sorted(_letters(g)) and _letters(f) != _letters(g):
            fod |= _content(f)
    for an in (a.get("assembly") or {}).get("anagrams") or []:
        fod |= _content(an.get("fodder", "")) & cw
    said_fod = set()
    fod_ev = []
    for m in re.finditer(r"\bANAGRAM(?:MING)?(?: OF)(?: THE LETTERS OF| THE)?((?: [A-Z]+){1,4})", talk):
        said_fod |= set(m.group(1).split()) & (cw - ans)
        fod_ev.append(m.group(0))
    if not said_fod:
        out["fodder"] = ("unknown", [])
    elif not fod:
        out["fodder"] = ("disagree" if "anagram" not in types else "unknown", fod_ev[:2])
    else:
        out["fodder"] = ("agree" if said_fod & fod else "disagree", fod_ev[:2])
    # pieces: each short block that turns clue words into other letters (an
    # abbreviation or short synonym) is heard, or a fragment is said to give
    # other spelt letters.
    agree, dis = [], []
    for b in a.get("blocks") or []:
        f, g = b.get("clueFragment", ""), _letters(b.get("gives") or "")
        fw = _content(f) - ans
        if not g or not fw or len(g) > 4 or sorted(_letters(f)) == sorted(g) or g in _letters(f):
            continue
        heard = re.search(r"\b" + " ?".join(g) + r"\b", talk) or re.search(r"\b" + g + r"\b", talk)
        if heard and any(w in toks for w in fw):
            agree.append(f"{f}={g}")
            continue
        for w in fw:
            for m in re.finditer(r"\b" + w + r" " + PIECE_SAYS + r" ((?:[A-Z] )*[A-Z])\b", talk):
                got = m.group(1).replace(" ", "")
                if set(got) - {"A", "I"} and got not in _letters(e["solution"]):
                    dis.append(f"{f}={g}, said: {m.group(0)}")
    out["pieces"] = (("disagree", dis[:2]) if dis else ("agree", agree) if agree else ("unknown", []))
    return out


_ENTRIES = {}


def entries_of(pid):
    """{entry id: entry} of a corpus puzzle, each with its spoken `_phrase`."""
    if pid not in _ENTRIES:
        sys.path.insert(0, str(ROOT / "tools"))
        import puzzle_paths
        p = json.loads(Path(puzzle_paths.find(pid)).read_text())
        for e in p["entries"]:
            e["_phrase"] = " ".join(words_of(e.get("solution", "").upper(), e["clue"].get("enumeration")))
        _ENTRIES[pid] = {f"{e['number']}-{e['direction']}": e for e in p["entries"]}
    return _ENTRIES[pid]


def own_talk(lines, eid, puz):
    """The window's words up to where the solver turns to another clue: says
    its number and direction, or reads three words of its text."""
    grams = set()
    for other, e in puz.items():
        if other == eid:
            continue
        cw = norm(re.sub(r"<[^>]+>", " ", e["clue"].get("text", ""))).split()
        grams |= {tuple(cw[i:i + 3]) for i in range(len(cw) - 2)
                  if any(len(w) >= 4 and w not in STOP for w in cw[i:i + 3])}
    out = []
    for _, line in lines:
        m = CLUE_REF.search(line)
        if m:
            num = m.group(1).lower()
            n = int(num) if num.isdigit() else NUMBER_WORDS[re.sub(r"[\s-]+", " ", num)]
            if f"{n}-{'down' if m.group(2).lower() == 'down' else 'across'}" != eid:
                break
        out += norm(line).split()
        if any(tuple(out[i:i + 3]) in grams for i in range(max(0, len(out) - len(norm(line).split()) - 2), len(out) - 2)):
            break
    return " ".join(out)


def parsecheck(subs_dir, top=15):
    """Our annotations' parses against the solvers' spoken explanations -> PARSECHECK."""
    data = json.loads(SOLVES.read_text())
    by_video = collections.defaultdict(list)
    for c in data["clues"]:
        by_video[c["video"]].append(c)
    talks = collections.defaultdict(list)   # (puzzle, entry) -> explanation windows
    subs = sub_files(subs_dir)
    for vid, rows in by_video.items():
        f = subs.get(vid)
        if not f:
            continue
        lines = parse_vtt(f)
        reads = sorted(r["read"] for r in rows if r["read"] is not None)
        puz = entries_of(rows[0]["puzzle"])
        for r in rows:
            t0 = r["t"] - EXPLAIN_LEAD_S
            t1 = min([r["t"] + EXPLAIN_TAIL_S] + [x for x in reads if x > r["t"] + 2])
            talks[(r["puzzle"], r["entry"])].append(
                own_talk([(t, l) for t, l in lines if t0 <= t <= t1], r["entry"], puz))
    rows = []
    for (pid, eid), ws in talks.items():
        e = entries_of(pid).get(eid)
        if not e or not e.get("annotation"):
            continue
        talk = " ".join(re.sub(r"\s+", " ", w).strip() for w in ws)
        res = check_clue(e, talk)
        rows.append({"puzzle": pid, "entry": eid, "clue": e["clue"].get("text", ""), "answer": e["solution"],
                     "types": e["annotation"].get("type") or [],
                     "definitions": [d["text"] for d in e["annotation"].get("definitions") or []],
                     **{k: v[0] for k, v in res.items()},
                     "evidence": {k: v[1] for k, v in res.items() if v[0] == "disagree"}})
    fields = ("definition", "type", "fodder", "pieces")
    summ = {"clues": len(rows), "by_field": {}, "by_type": {}}
    for f in fields:
        c = collections.Counter(r[f] for r in rows)
        judged = c["agree"] + c["disagree"]
        summ["by_field"][f] = {**c, "disagree_rate": round(c["disagree"] / judged, 3) if judged else None}
    for ty in sorted({t for r in rows for t in r["types"][:1]}):
        sel = [r for r in rows if r["types"][:1] == [ty]]
        d = sum(any(r[f] == "disagree" for f in fields) for r in sel)
        j = sum(any(r[f] != "unknown" for f in fields) for r in sel)
        summ["by_type"][ty] = {"clues": len(sel), "judged": j, "any_disagree": d,
                               "rate": round(d / j, 3) if j else None}
    summ["top"] = {f: [f"{r['puzzle']} {r['entry']} {r['answer']}" for r in rows if r[f] == "disagree"][:top]
                   for f in fields}
    row = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    PARSECHECK.write_text('{"summary":' + json.dumps(summ, ensure_ascii=False, indent=1)
                          + ',\n"clues":[\n' + ",\n".join(map(row, rows)) + "\n]}\n")
    print(f"{len(rows)} annotated clues with a spoken explanation -> {PARSECHECK}")
    for f, s in summ["by_field"].items():
        print(f"  {f:10s} agree {s.get('agree', 0):5d}  disagree {s.get('disagree', 0):4d}  "
              f"unknown {s.get('unknown', 0):5d}  disagree rate {s['disagree_rate']}")
    for ty, s in sorted(summ["by_type"].items(), key=lambda x: -x[1]["clues"]):
        print(f"  {ty:20s} {s['clues']:5d} clues, {s['judged']:5d} judged, {s['any_disagree']:4d} disagree ({s['rate']})")


UNSTICK = ROOT / "tools" / "data" / "ctc_unstick.json"
#: A clue is a hard one when it is flagged stuck or waited this long from its
#: reading to its solve (about the top quarter of waits).
LONG_WAIT_S = 180
#: The baseline: solves read and solved within QUICK_WAIT_S, not stuck. What a
#: solver says at every solve (the definition beside the answer) is not what
#: unstuck anyone, so each unlock's share is read against its share here.
QUICK_WAIT_S = 60
#: What unlocked it is said in the UNLOCK_LEAD_S before the solve and the
#: first UNLOCK_TAIL_S after (the answer is said mid-sentence).
UNLOCK_LEAD_S, UNLOCK_TAIL_S = 20, 5
#: The rungs of app.js's ladderSteps, in the order its LABELS map lists them.
LADDER = ("indicators", "definition", "type", "blocks")
#: Which rung carries each unlock. Crossing letters are the grid's reveal-a-letter
#: button, not a rung; a word's other sense goes to the rung whose words hold
#: the misdirected word (unstick_rungs).
UNLOCK_RUNG = {"definition": "definition", "indicator": "indicators", "device": "type",
               "block": "blocks", "crossing": "letter"}
DEF_CUE = re.compile(r"\bDEFINITION\b|\bDEFINED\b|\bDEFINES\b")
INDICATOR_CUE = re.compile(r"\bINDICAT\w*")
BLOCK_CUE = re.compile(r"\bABBREVIAT\w*|\bSHORT FOR\b|\bSTANDS? FOR\b|\b(?:[B-HJ-Z] ){0,2}[B-HJ-Z] FOR [A-Z]{3,}")
CROSSING_CUE = re.compile(
    r"\bWITH (?:THE |AN? )?[B-HJ-Z]\b|\b(?:BEGIN\w*|START\w*|END\w*) (?:WITH|IN) (?:AN? )?[B-HJ-Z]\b|"
    r"\bCHECK(?:ER|ING LETTER|ED LETTER)S?\b|\bCROSS(?:ER|ING LETTER)S?\b|\bBLANK\b|"
    r"\bSOMETHING [A-Z] SOMETHING\b|\b[A-Z] SOMETHING [A-Z]\b|\b(?:THE )?LETTERS? (?:I|WE) (?:HAVE|VE GOT)\b")
SENSE_CUE = re.compile(
    r"\bSENSE\b|\b(?:OTHER|DIFFERENT|ANOTHER|SECOND|OTHER KIND OF) MEANING\b|\bMISLE[AD]\w*|\bMISDIRECT\w*|"
    r"\bAS AN? (?:VERB|NOUN|ADJECTIVE)\b|\bRATHER THAN\b|\bI WAS THINKING OF\b|\bDISGUISE\w*|"
    r"\bCAPITAL LETTER\b|\bNOT (?:THE|AN?) [A-Z]+ (?:BUT|KIND)\b")


def unread(toks, clue):
    """The tokens with every run of three or more of the clue's words read in
    order dropped: a clue read aloud names every word in it and unlocks nothing."""
    cw = norm(re.sub(r"<[^>]+>", " ", clue)).split()
    grams = {tuple(cw[i:i + 3]) for i in range(len(cw) - 2)}
    drop = set()
    for i in range(len(toks) - 2):
        if tuple(toks[i:i + 3]) in grams:
            drop.update((i, i + 1, i + 2))
    return [w for i, w in enumerate(toks) if i not in drop]


def near_answer(toks, answer, words, reach=5):
    """Whether any of the words sits within reach tokens of the answer."""
    aw = answer.split()
    at = [i for i in range(len(toks)) if toks[i:i + len(aw)] == aw]
    return any(toks[j] in words for i in at
               for j in range(max(0, i - reach), min(len(toks), i + len(aw) + reach)))


def classify_unlock(e, talk):
    """{unlock: evidence} for what the solver said around one hard solve.

    definition: our definition's words said next to the answer, or the word
    "definition"; indicator: an indicator's own words said, or "indicator",
    with the type it signals; device: a device named ("anagram of", "hidden")
    without its indicator; block: a short piece's letters heard with its clue
    words, or an abbreviation called one; crossing: letters already in the
    grid ("with the W", "beginning with"); sense: a word read another way
    ("in the sense of", "misled")."""
    a = e.get("annotation") or {}
    clue = e["clue"].get("text", "")
    ans = e["_phrase"]
    answ = set(ans.split())
    toks = unread(talk.split(), clue)
    s = " ".join(toks)
    tokset = set(toks)
    cw = _content(clue)
    out = {}
    defs = set().union(*(_content(d["text"]) for d in a.get("definitions") or [])) - answ
    if not defs:   # unannotated: the clue's first and last content words
        words = [w for w in norm(re.sub(r"<[^>]+>", " ", clue)).split() if len(w) >= 3 and w not in STOP]
        defs = set(words[:1] + words[-1:]) - answ
    def said(pat):
        """The first match of pat that is not merely clue words."""
        return next((m.group(0) for m in pat.finditer(s) if not set(m.group(0).split()) <= cw | STOP), None)

    if m := said(DEF_CUE):
        out["definition"] = m
    elif near_answer(toks, ans, defs):
        out["definition"] = " ".join(sorted(defs & tokset))
    heard = [i for i in a.get("indicators") or [] if _content(i["text"]) & tokset - answ]
    if heard:
        out["indicator"] = heard[0].get("for") or "unknown"
    elif said(INDICATOR_CUE):
        ty = [i.get("for") for i in a.get("indicators") or []]
        out["indicator"] = (ty[0] if ty else None) or "unknown"
    named = [t for t, c in NAMED_STRONG.items() if _named(s, c, cw | answ)]
    if named and "indicator" not in out:
        out["device"] = named[0]
    for b in a.get("blocks") or []:
        f, g = b.get("clueFragment", ""), _letters(b.get("gives") or "")
        fw = _content(f) - answ
        if not g or not fw or len(g) > 4 or sorted(_letters(f)) == sorted(g) or g in _letters(f):
            continue
        if (re.search(r"\b" + " ?".join(g) + r"\b", s)) and fw & tokset:
            out["block"] = f"{f}={g}"
            break
    if "block" not in out and (m := said(BLOCK_CUE)):
        out["block"] = m
    if m := said(CROSSING_CUE):
        out["crossing"] = m
    if m := said(SENSE_CUE):
        out["sense"] = m
    return out


def available_rungs(a):
    """The LADDER rungs ladderSteps builds for this annotation."""
    have = {"indicators": bool(a.get("indicators")), "definition": bool(a.get("definitions")),
            "type": bool(a.get("type")), "blocks": bool(a.get("blocks"))}
    return [r for r in LADDER if have[r]]


def unstick_rungs(a, unlocks):
    """The rungs whose content carries one of the unlocks. A word's other
    sense is on the rung that shows the misdirected word: the definition, an
    indicator, else a block."""
    out = {UNLOCK_RUNG[u] for u in unlocks if u in UNLOCK_RUNG}
    if "sense" in unlocks:
        mw = _content((a.get("features") or {}).get("misdirectedWord") or "")
        if mw & set().union(*(_content(d["text"]) for d in a.get("definitions") or [])):
            out.add("definition")
        elif mw & set().union(*(_content(i["text"]) for i in a.get("indicators") or [])):
            out.add("indicators")
        elif mw:
            out.add("blocks")
        else:
            out.add("sense")
    return out


def rungs_to_unlock(rows, order):
    """Mean rungs taken, walking order over each clue's available rungs, until
    one that carries its unlock; over clues some available rung unlocks."""
    n = tot = 0
    for r in rows:
        avail = [x for x in order if x in r["available"]]
        hits = [i for i, x in enumerate(avail) if x in r["rungs"]]
        if hits:
            n += 1
            tot += hits[0] + 1
    return round(tot / n, 3) if n else None, n


def two_prop_p(k1, n1, k2, n2):
    """Two-sided normal-approximation p that k1/n1 and k2/n2 share a rate."""
    if not n1 or not n2:
        return 1.0
    q = (k1 + k2) / (n1 + n2)
    se = math.sqrt(q * (1 - q) * (1 / n1 + 1 / n2))
    return math.erfc(abs(k1 / n1 - k2 / n2) / se / math.sqrt(2)) if se else 1.0


def summarise(sel, base):
    """Unlock shares against the quick solves, rung hit rates and rung orders
    scored, for one set of hard solves."""
    orders = list(itertools.permutations(LADDER))
    n, nb = len(sel), len(base) or 1
    bc = collections.Counter(k for r in base for k in r["unlocks"])
    uc = collections.Counter(k for r in sel for k in r["unlocks"])
    ind = collections.Counter(r["unlocks"]["indicator"] for r in sel if "indicator" in r["unlocks"])
    dev = collections.Counter(r["unlocks"]["device"] for r in sel if "device" in r["unlocks"])
    rc = collections.Counter(x for r in sel for x in r["rungs"])
    avail = collections.Counter(x for r in sel for x in r["available"])
    # A rung's hit rate is over the clues that have it.
    hit = {x: round(sum(x in r["rungs"] for r in sel if x in r["available"]) / avail[x], 3)
           for x in LADDER if avail[x]}
    cur, k = rungs_to_unlock(sel, LADDER)
    best = min(orders, key=lambda o: (rungs_to_unlock(sel, o)[0] or 99, o != LADDER))
    return {"clues": n, "classified": sum(bool(r["unlocks"]) for r in sel),
            "unlocks": {x: {"clues": c, "share": round(c / n, 3), "quick_share": round(bc[x] / nb, 3),
                            "lift": round(c / n / (bc[x] / nb), 2) if bc[x] else None,
                            "p": round(two_prop_p(c, n, bc[x], len(base)), 4)}
                        for x, c in uc.most_common()} if n else {},
            "quick_clues": len(base),
            "indicator_types": dict(ind.most_common()), "devices_named": dict(dev.most_common()),
            "rungs": dict(rc.most_common()), "rung_hit_rate": hit,
            "best_first_rung": max(hit, key=hit.get) if hit else None,
            "current_order": {"order": list(LADDER), "mean_rungs": cur, "clues": k},
            "best_order": {"order": list(best), "mean_rungs": rungs_to_unlock(sel, best)[0]}}



def unstick(subs_dir):
    """What unlocked each hard CtC solve, by clue type, against the ladder -> UNSTICK."""
    data = json.loads(SOLVES.read_text())
    by_video = collections.defaultdict(list)
    for c in data["clues"]:
        by_video[c["video"]].append(c)
    rows, quick = [], []
    subs = sub_files(subs_dir)
    for vid, clues in by_video.items():
        f = subs.get(vid)
        if not f:
            continue
        lines = parse_vtt(f)
        puz = entries_of(clues[0]["puzzle"])
        for c in clues:
            is_hard = c["stuck"] or (c["read_to_solve"] or 0) >= LONG_WAIT_S
            if not is_hard and (c["read_to_solve"] is None or c["read_to_solve"] >= QUICK_WAIT_S):
                continue
            e = puz.get(c["entry"])
            if not e:
                continue
            talk = norm(" ".join(l for t, l in lines if c["t"] - UNLOCK_LEAD_S <= t <= c["t"] + UNLOCK_TAIL_S))
            a = e.get("annotation") or {}
            u = classify_unlock(e, talk)
            (rows if is_hard else quick).append({"video": vid, "puzzle": c["puzzle"], "entry": c["entry"], "answer": e["solution"],
                         "clue": e["clue"].get("text", ""), "type": (a.get("type") or [None])[0],
                         "stuck": c["stuck"], "wait": c["read_to_solve"], "unlocks": u,
                         "available": available_rungs(a), "rungs": sorted(unstick_rungs(a, u))})
    ann = [r for r in rows if r["type"]]
    types = collections.Counter(r["type"] for r in ann)
    summ = {"hard_clues": len(rows), "videos": len({r["video"] for r in rows}),
            "all": summarise(rows, quick), "annotated": summarise(ann, [r for r in quick if r["type"]]),
            "by_type": {t: summarise([r for r in ann if r["type"] == t], [r for r in quick if r["type"] == t])
                        for t, c in types.most_common() if c >= 10}}
    row = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    UNSTICK.write_text('{"summary":' + json.dumps(summ, ensure_ascii=False, indent=1)
                       + ',\n"clues":[\n' + ",\n".join(map(row, rows)) + "\n]}\n")
    print(f"{len(rows)} hard solves in {summ['videos']} videos ({len(ann)} annotated) -> {UNSTICK}")
    for key in ("all", "annotated"):
        s = summ[key]
        print(f"  {key}: {s['classified']}/{s['clues']} classified; share, vs {s['quick_clues']} quick solves: "
              + ", ".join(f"{x} {u['share']:.0%} vs {u['quick_share']:.0%}" for x, u in s["unlocks"].items()))
    print("  hard vs quick at p < 0.05: " + "; ".join(
        f"{t} {x} {u['share']:.0%} vs {u['quick_share']:.0%}"
        for t, sm in [("annotated", summ["annotated"])] + list(summ["by_type"].items())
        for x, u in sm["unlocks"].items() if u["p"] < 0.05))
    print("  rung hit rate on hard solves (share of clues with the rung whose unlock it shows):")
    print(f"  {'type':20s} {'n':>4s}  " + "  ".join(f"{x[:5]:>5s}" for x in LADDER) + "  best-first  now->best mean rungs")
    for t, s in [("annotated", summ["annotated"])] + list(summ["by_type"].items()):
        h = s["rung_hit_rate"]
        print(f"  {t:20s} {s['clues']:4d}  " + "  ".join(
            f"{h[x]:5.0%}" if x in h else "    -" for x in LADDER)
            + f"  {s['best_first_rung'] or '-':10s}  {s['current_order']['mean_rungs']} -> "
              f"{s['best_order']['mean_rungs']} {'/'.join(x[:3] for x in s['best_order']['order'])}")
    return rows, quick


def unstick_by_skill():
    """unstick() for every channel with solve times, then what unlocked the
    hard solves by solver skill; each level's shares are read against its own
    quick solves, so a talkative tutor's baseline cancels. Unannotated clues
    count: every unlock but the rungs is read off the transcript alone."""
    by = {k: ([], []) for k in SKILLS}
    for ch, (_, skill, subs) in CHANNELS.items():
        if skill == EXPLAINER or not data_file("solve_times", ch).exists():
            continue
        use_channel(ch)
        print(f"== {ch} ({skill})")
        rows, quick = unstick(subs)
        by[skill][0].extend(rows)
        by[skill][1].extend(quick)
    summ = {k: summarise(*v) for k, v in by.items() if v[0]}
    print("\nhard solves by solver skill: unlock share (vs own quick solves)")
    kinds = sorted({x for s in summ.values() for x in s["unlocks"]})
    print(f"  {'skill':12s} {'hard':>5s} {'quick':>5s}  " + "  ".join(f"{x:>17s}" for x in kinds))
    for k, sm in summ.items():
        print(f"  {k:12s} {sm['clues']:5d} {sm['quick_clues']:5d}  " + "  ".join(
            f"{sm['unlocks'][x]['share']:6.0%} vs {sm['unlocks'][x]['quick_share']:4.0%} "
            f"{'*' if sm['unlocks'][x]['p'] < 0.05 else ' '}" if x in sm["unlocks"] else f"{'-':>17s}" for x in kinds))
    print("  rung hit rate: " + "; ".join(
        f"{k} " + " ".join(f"{x[:5]} {sm['rung_hit_rate'].get(x, 0):.0%}" for x in LADDER) for k, sm in summ.items()))
    lo, hi = SKILLS[-1], SKILLS[0]
    if lo in summ and hi in summ:
        a, b = summ[lo], summ[hi]
        print(f"  {lo} vs {hi}, hard-solve unlock share at p < 0.05: " + ", ".join(
            f"{x} {a['unlocks'].get(x, {}).get('share', 0):.0%} vs {b['unlocks'].get(x, {}).get('share', 0):.0%}"
            for x in kinds if two_prop_p(a["unlocks"].get(x, {}).get("clues", 0), a["clues"],
                                        b["unlocks"].get(x, {}).get("clues", 0), b["clues"]) < 0.05) or "none")
        for x in LADDER:
            ka = sum(x in r["rungs"] for r in by[lo][0] if x in r["available"])
            na = sum(x in r["available"] for r in by[lo][0])
            kb = sum(x in r["rungs"] for r in by[hi][0] if x in r["available"])
            nb = sum(x in r["available"] for r in by[hi][0])
            print(f"  rung {x:10s} {lo} {ka}/{na}  {hi} {kb}/{nb}  p {two_prop_p(ka, na, kb, nb):.3g}")
    UNSTICK_SKILL.write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n")
    print(f"-> {UNSTICK_SKILL}")


SKILLCHECK = ROOT / "tools" / "data" / "yt_solvers" / "skill_check.json"
UNSTICK_SKILL = ROOT / "tools" / "data" / "yt_solvers" / "unstick_by_skill.json"


def wait_percentiles(channel):
    """{(puzzle, entry): wait percentile within its video} for one channel,
    a puzzle solved twice averaged."""
    data = json.loads(data_file("solve_times", channel).read_text())
    by_video = collections.defaultdict(list)
    for c in data["clues"]:
        by_video[c["video"]].append(c)
    got = collections.defaultdict(list)
    for rows in by_video.values():
        w = _ranks([r["read_to_solve"] if r["read_to_solve"] is not None else r["seconds"] for r in rows])
        for r, x in zip(rows, w):
            got[(r["puzzle"], r["entry"])].append(x)
    return {k: sum(v) / len(v) for k, v in got.items()}


def fisher_p(r1, n1, r2, n2):
    """Two-sided p that two correlations are equal (Fisher z)."""
    z = lambda r: math.atanh(max(-0.999, min(0.999, r)))
    if n1 < 4 or n2 < 4:
        return 1.0
    return math.erfc(abs(z(r1) - z(r2)) / math.sqrt(1 / (n1 - 3) + 1 / (n2 - 3)) / math.sqrt(2))


def skillcheck():
    """Our per-clue difficulty against each channel's waits, per channel, by
    skill and pooled. Every value is a percentile within its own video, so
    each solver's pace and each puzzle's hardness cancel before pooling."""
    out, pooled = {"channels": {}, "skills": {}}, collections.defaultdict(list)
    for ch, (name, skill, _) in CHANNELS.items():
        if skill == EXPLAINER or not data_file("solve_times", ch).exists():
            continue
        use_channel(ch)
        t = solve_table()
        if len(t.held) < 30:
            out["channels"][ch] = {"skill": skill, "clues": len(t.held)}
            continue
        comp, wait, length = zip(*t.held)
        r, n, p = _rho_p(comp, wait)
        pv = sorted(x for rs in t.per_video.values() for x in rs)
        hard = t.human.get(("ctc_wait", "hard"), [])
        out["channels"][ch] = {
            "name": name, "skill": skill, "videos": len(pv), "clues": n,
            "composite_vs_wait": round(r, 3), "p": float(f"{p:.2g}"),
            "length_vs_wait": round(_spearman(length, wait), 3),
            "partial_length_held": round(partial_rho(t.held)[0], 3),
            "per_video_median": round(pv[len(pv) // 2], 3) if pv else None,
            "per_video_positive": f"{sum(x > 0 for x in pv)}/{len(pv)}",
            "times_blog_hard_vs_wait": round(_spearman(*zip(*hard)), 3) if len(hard) >= 30 else None}
        pooled[skill] += t.held
        pooled["all"] += t.held
    for k, held in pooled.items():
        r, n, p = _rho_p([h[0] for h in held], [h[1] for h in held])
        out["skills"][k] = {"clues": n, "composite_vs_wait": round(r, 3), "p": float(f"{p:.2g}"),
                            "length_vs_wait": round(_spearman([h[2] for h in held], [h[1] for h in held]), 3)}
    lo, hi = SKILLS[-1], SKILLS[0]
    if lo in out["skills"] and hi in out["skills"]:
        a, b = out["skills"][lo], out["skills"][hi]
        out["beginner_vs_expert_p"] = float(f"{fisher_p(a['composite_vs_wait'], a['clues'], b['composite_vs_wait'], b['clues']):.2g}")
    # solvers against each other on the clues both timed
    waits = {ch: wait_percentiles(ch) for ch in out["channels"]}
    out["agreement"] = {}
    for a, b in itertools.combinations(waits, 2):
        both = sorted(set(waits[a]) & set(waits[b]))
        if len(both) >= 30:
            r, n, p = _rho_p([waits[a][k] for k in both], [waits[b][k] for k in both])
            out["agreement"][f"{a}~{b}"] = {"clues": n, "rho": round(r, 3), "p": float(f"{p:.2g}")}
    SKILLCHECK.parent.mkdir(parents=True, exist_ok=True)
    SKILLCHECK.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{'channel':26s} {'skill':12s} {'vids':>4s} {'clues':>5s}  ours~wait  (p)      len~wait  partial  median/video  blog-hard~wait")
    for ch, c in out["channels"].items():
        if "composite_vs_wait" not in c:
            print(f"{ch:26s} {c['skill']:12s} {'':4s} {c['clues']:5d}  too few timed clues")
            continue
        print(f"{ch:26s} {c['skill']:12s} {c['videos']:4d} {c['clues']:5d}  {c['composite_vs_wait']:+.3f}  ({c['p']:.2g})  "
              f"{c['length_vs_wait']:+.3f}   {c['partial_length_held']:+.3f}   {c['per_video_median']:+.3f} {c['per_video_positive']:>7s}  "
              f"{c['times_blog_hard_vs_wait'] if c['times_blog_hard_vs_wait'] is not None else '-'}")
    for k, c in out["skills"].items():
        print(f"pooled {k:12s} clues {c['clues']:5d}  ours~wait {c['composite_vs_wait']:+.3f} (p={c['p']:.2g})  len~wait {c['length_vs_wait']:+.3f}")
    if "beginner_vs_expert_p" in out:
        print(f"beginner vs expert rho differ: p={out['beginner_vs_expert_p']}")
    for k, c in out["agreement"].items():
        print(f"solver agreement {k}: wait rho {c['rho']:+.3f} over {c['clues']} shared clues (p={c['p']:.2g})")
    print(f"-> {SKILLCHECK}")


if __name__ == "__main__":
    args = sys.argv[1:]
    channel = "ctc"
    if "--channel" in args:
        k = args.index("--channel")
        channel = args[k + 1]
        del args[k:k + 2]
    cmd = args[0] if args else ""
    if channel == "all" and cmd in ("solvecheck", "unstick"):
        sys.path.insert(0, str(ROOT / "tools"))
        (skillcheck if cmd == "solvecheck" else unstick_by_skill)()
        sys.exit()
    todo = list(CHANNELS) if channel == "all" else channel.split(",")
    if cmd in ("unstick", "solvecheck"):
        todo = [c for c in todo if c not in CHANNELS or CHANNELS[c][1] != EXPLAINER]
    for ch in todo:
        use_channel(ch)
        if len(args) > 1 and "," not in channel and channel != "all":
            subs = args[1]
        else:
            subs = CHANNELS[CHANNEL][2]
        if len(todo) > 1:
            print(f"== {CHANNEL}")
        if cmd == "solves":
            solves(subs)
        elif cmd == "unstick":
            unstick(subs)
        elif cmd == "parsecheck":
            parsecheck(subs)
        elif cmd == "solvecheck":
            sys.path.insert(0, str(ROOT / "tools"))
            solvecheck()
        elif cmd == "extract":
            extract(subs, args[2] if len(args) > 2 else None)
        elif cmd == "packets":
            packets(int(args[1]))
        elif cmd == "merge":
            merge()
        elif cmd == "report":
            report()
        else:
            sys.exit(__doc__)
