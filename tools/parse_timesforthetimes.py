#!/usr/bin/env python3
"""Turn cached timesforthetimes.co.uk posts into clue and answer records.

The Times withholds its grids, but this blog prints, for every puzzle, the
clue NUMBER under an Across or Down heading and the ANSWER. Number, direction
and answer length are the whole input to tools/reconstruct_grid.py, so these
records are what a Times grid gets rebuilt from. From about 2017 the posts
carry the clue TEXT and its enumeration too, which is what makes the puzzle
teachable rather than merely drawable.

Three eras of markup, one parser: the posts are flattened to lines and read as
a stream, because every era puts the number, the clue and the answer on lines
of their own once the tags are gone — a 2025 table cell, a 2020 <br>-separated
paragraph and a 2010 table row differ in tags and not in shape.

Reads the cache tools/fetch_timesforthetimes.py writes; never the network.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

CACHE = Path.home() / "cryptic-setter-data" / "timesforthetimes"
POSTS = CACHE / "posts"
OUT = CACHE / "parsed.jsonl"

SERIES = {
    11: "Daily Cryptic",
    12: "Quick Cryptic",
    21: "Weekend Cryptic",
    14: "Jumbo Cryptic",
    13: "Mephisto",
    24: "Monthly Club Special",
    26: "Other Crosswords",
}

#: How many entries each series really has, give or take a blogger who skipped
#: one. Outside this range the post is reported, never emitted: a parser that
#: quietly under-extracts is indistinguishable from a blogger who wrote less.
PLAUSIBLE = {
    "Daily Cryptic": (24, 34),
    "Quick Cryptic": (20, 30),
    "Weekend Cryptic": (24, 34),
    "Jumbo Cryptic": (40, 60),
    "Mephisto": (24, 42),
    "Monthly Club Special": (24, 42),
}

#: Tags that end a line of reading, whatever era drew them.
BREAKS = re.compile(r"</?(?:br|p|div|tr|td|th|li|h[1-6]|table|tbody)\b[^>]*>",
                    re.I)
TAG = re.compile(r"<[^>]+>")
HEADING = re.compile(r"^(across|down)\b[\s:.]*$", re.I)
NUMBERED = re.compile(r"^(\d{1,2})\s*[.):]?\s*(.*)$")
#: An answer is the line's leading run of capitals, ended by whichever mark
#: the wordplay hangs off — a dash, an equals sign or a semicolon. A plain
#: hyphen ends it only when a space follows, or WELL-KNOWN truncates to WELL.
ANSWER = re.compile(
    r"^([A-Z][A-Z0-9'\u2019()\[\]+,. \-]{1,70}?)"
    r"\s*(?:[\u2013\u2014=;]|-\s|-\s*$|$)")
#: Wordplay written into the answer itself: S(L)OUGH, YOR[I+C]K, RICE,PAPER.
#: The letters in order are the answer — the brackets are the blogger showing
#: their working, and the comma is the space between two words.
ANSWER_MARKUP = re.compile(r"[()\[\]+.]")
#: …except when the comma is what ends the answer, as in "NARCOSIS, anagram of
#: CAR". A word of the answer is printed in capitals; the wordplay that follows
#: a comma is prose, so the case of the next word settles which one it is.
WORDPLAY_COMMA = re.compile(r",\s+(?=[a-z])")
#: A deleted letter written in lower case inside the answer: SWANSON[g], IN(v).
DROPPED_LETTERS = re.compile(r"[\[(][a-z]+[\])]")
#: Deleted letters, marked two ways across the eras, are not in the answer.
DELETED = re.compile(r"<(s|strike|del)\b[^>]*>.*?</\1>", re.I | re.S)
BRACED = re.compile(r"\{[^}]*\}")
ENUM = re.compile(r"\((\d+[\d,\-–\s]*)\)\s*$")
#: Blog slugs put the puzzle number first: times-29572-…, qc-1255-by-hurley,
#: monthly-club-special-20231-…. The title is the fallback when it does not.
NUMBER_IN = re.compile(r"(\d{3,5})")


def lines(rendered):
    """Flatten post HTML to the lines the era-independent reader walks."""
    text = DELETED.sub("", rendered)
    text = BREAKS.sub("\n", text)
    text = TAG.sub("", text)
    text = html.unescape(text)
    text = BRACED.sub("", text)
    text = text.replace("\t", "\n").replace("\xa0", " ")
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]


def puzzle_number(post):
    m = NUMBER_IN.search(post.get("slug", ""))
    if not m:
        m = NUMBER_IN.search(html.unescape(post.get("title", {}).get("rendered", "")))
    return int(m.group(1)) if m else None


def is_answer(rest):
    """Is this line's head an answer, rather than a clue that opens in caps?"""
    rest = DROPPED_LETTERS.sub("", WORDPLAY_COMMA.split(rest, 1)[0])
    m = ANSWER.match(rest)
    if not m:
        return None
    word = ANSWER_MARKUP.sub("", m.group(1))
    letters = re.sub(r"[^A-Z]", "", word)
    if len(letters) < 3 or len(word) > 60:
        return None
    # Keep the letters, not the printing. A comma means a word break in one
    # era and a wordplay join in another (RICE,PAPER against A,CADE,MIA), and
    # a light is contiguous letters either way — the enumeration off the clue
    # is where the word breaks come from.
    return letters


def parse_post(post):
    """One post to its entries. Returns None for anything that is not a puzzle."""
    cats = post.get("categories", [])
    series = next((SERIES[c] for c in cats if c in SERIES), None)
    if series is None:
        return None

    entries, direction, num, clue, enum = [], None, None, None, None

    def flush(answer):
        if num is None or not answer:
            return
        entries.append({
            "number": num, "direction": direction or "across",
            "answer": answer,
            "clue": clue, "enumeration": enum,
        })

    for ln in lines(post["content"]["rendered"]):
        if not ln:
            continue
        if HEADING.match(ln):
            direction = HEADING.match(ln).group(1).lower()
            num, clue, enum = None, None, None
            continue
        m = NUMBERED.match(ln)
        if m:
            n, rest = int(m.group(1)), m.group(2).strip()
            if not rest:              # a bare number cell; its row follows
                num, clue, enum = n, None, None
                continue
            answer = is_answer(rest)
            if answer:                # number and answer on one line
                num, clue, enum = n, None, None
                flush(answer)
                num = None
                continue
            num, clue = n, rest       # number and clue text on one line
            e = ENUM.search(rest)
            enum = e.group(1).strip() if e else None
            continue
        answer = is_answer(ln)
        if answer and num is not None:
            flush(answer)
            num, clue, enum = None, None, None
            continue
        if num is not None and clue is None and ENUM.search(ln):
            clue = ln                 # the clue arrived in its own cell
            enum = ENUM.search(ln).group(1).strip()

    if not entries:
        return None
    return {
        "post_id": post["id"], "date": post["date"][:10], "slug": post["slug"],
        "link": post.get("link"), "series": series, "number": puzzle_number(post),
        "entries": entries,
    }


def enum_agrees(entry):
    """Does the answer have the length its own enumeration claims?

    The two come from different halves of the post — the clue line and the
    answer line — so agreement is the one check that catches a misread answer
    without a human reading it. Entries with no enumeration cannot be checked.
    """
    if not entry["enumeration"]:
        return None
    want = sum(int(n) for n in re.findall(r"\d+", entry["enumeration"]))
    return want == len(entry["answer"])


def plausible(rec):
    lo_hi = PLAUSIBLE.get(rec["series"])
    return lo_hi is None or lo_hi[0] <= len(rec["entries"]) <= lo_hi[1]


def run(write=True, limit=None):
    files = sorted(POSTS.glob("*.json"))
    if limit:
        files = files[:limit]
    if not files:
        print(f"no cached posts in {POSTS} — run tools/fetch_timesforthetimes.py")
        return None
    by_year, by_series, odd = {}, {}, []
    kept = withtext = checked = agreed = 0
    out = open(OUT, "w", encoding="utf-8") if write else None
    for f in files:
        post = json.loads(f.read_text(encoding="utf-8"))
        rec = parse_post(post)
        if rec is None:
            continue
        ok = plausible(rec)
        year = rec["date"][:4]
        texts = sum(1 for e in rec["entries"] if e["clue"])
        full_text = texts >= len(rec["entries"]) * 0.8
        y = by_year.setdefault(year, [0, 0, 0])
        y[0] += 1
        y[1] += ok
        y[2] += ok and full_text
        s = by_series.setdefault(rec["series"], [0, 0, 0])
        s[0] += 1
        s[1] += ok
        s[2] += ok and full_text
        if not ok:
            odd.append((rec["slug"], rec["series"], len(rec["entries"])))
            continue
        kept += 1
        withtext += full_text
        for e in rec["entries"]:
            a = enum_agrees(e)
            if a is not None:
                checked += 1
                agreed += a
        if out:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if out:
        out.close()
    return {"files": len(files), "kept": kept, "withtext": withtext,
            "checked": checked, "agreed": agreed,
            "odd": odd, "by_year": by_year, "by_series": by_series}


def report(r):
    print(f"{r['files']} cached post(s) read")
    print(f"{r['kept']} puzzle(s) parsed with a plausible entry count")
    print(f"  {r['withtext']} with clue text, "
          f"{r['kept'] - r['withtext']} number+answer only")
    print(f"{len(r['odd'])} post(s) failed the entry-count check "
          f"(parsed, not emitted)")
    if r["checked"]:
        pct = 100.0 * r["agreed"] / r["checked"]
        print(f"{r['agreed']}/{r['checked']} entries ({pct:.1f}%) have the "
              f"answer length their own enumeration claims")
    print("\nBY SERIES  (parsed / plausible / with clue text)")
    for s, (n, ok, t) in sorted(r["by_series"].items(), key=lambda kv: -kv[1][0]):
        print(f"  {s:<22} {n:>5} / {ok:>5} / {t:>5}")
    print("\nBY YEAR  (parsed / plausible / with clue text)")
    for y, (n, ok, t) in sorted(r["by_year"].items()):
        print(f"  {y}  {n:>4} / {ok:>4} / {t:>4}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true",
                    help="parse and report coverage without writing the output")
    ap.add_argument("--limit", type=int, help="read only the first N posts")
    ap.add_argument("--show", help="parse one cached post id or slug and print it")
    ap.add_argument("--odd", action="store_true",
                    help="list the posts that failed the entry-count check")
    a = ap.parse_args()

    if a.show:
        for f in POSTS.glob("*.json"):
            post = json.loads(f.read_text(encoding="utf-8"))
            if a.show in (str(post["id"]), post["slug"]):
                print(json.dumps(parse_post(post), ensure_ascii=False, indent=2))
                return 0
        print(f"no cached post {a.show}")
        return 2

    r = run(write=not a.status, limit=a.limit)
    if r is None:
        return 1
    report(r)
    if a.odd:
        print("\nFAILED THE ENTRY-COUNT CHECK")
        for slug, series, n in r["odd"][:80]:
            print(f"  {n:>3}  {series:<22} {slug}")
    if not a.status:
        print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
