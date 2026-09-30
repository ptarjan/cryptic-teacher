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

TITLES.tsv is `id<TAB>title` per video, from `yt-dlp --flat-playlist`.
The reasons file maps a moment id to {"reasons": [...], "quote": "..."}.
"""
import collections
import glob
import html
import json
import math
import re
import sys
from pathlib import Path

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

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
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
