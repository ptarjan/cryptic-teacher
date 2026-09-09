#!/usr/bin/env python3
"""Measure the favourite-clue signal in the fifteensquared comment cache.

Commenters name the clue they liked best. That is the only per-clue quality
judgement we have from outside this project, so it is what tools/craft_score.py
has to be tested against. A named favourite is almost always the ANSWER in
capitals ("MAYONNAISE was my favourite"), sometimes a grid reference ("18d"),
so resolving one needs the puzzle it belongs to. This reports how many
favourites survive that join, and writes the resolved votes for scoring.

Run with no arguments; --json <path> also dumps one record per resolved vote.
"""

import argparse
import collections
import glob
import html
import json
import os
import re

CACHE = os.path.expanduser("~/cryptic-setter-data/fifteensquared")
PUZZLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "puzzles")

# "my favourite was", "COD", "pick of the bunch". Deliberately narrow: the
# comments are full of favourite songs, films and TV roles, and a loose pattern
# buys mentions that no join can ever resolve.
FAVOURITE = re.compile(
    r"(?i)\b(cod|codded|favourites?|favorites?|clue of the day|pick of the|best clue|"
    r"top clue|clue of the week|standout clue|favourite clue|star clue)\b"
)
# Fifteensquared titles: "Guardian Cryptic 29,599 by Paul", "Everyman 3,906/22 August".
TITLE = re.compile(r"(?i)\b(guardian cryptic|guardian quiptic|quiptic|independent on sunday|"
                   r"independent|everyman|guardian)\b[^0-9]{0,12}([0-9][0-9,]*)")
SERIES = {
    "guardian cryptic": "cryptic",
    "guardian": "cryptic",
    "guardian quiptic": "quiptic",
    "quiptic": "quiptic",
    "independent": "independent",
    "independent on sunday": "indysunday",
    "everyman": "everyman",
}
CAPS = re.compile(r"\b[A-Z][A-Z'’-]*(?:\s+[A-Z][A-Z'’-]*)*\b")
GRIDREF = re.compile(r"(?i)\b([0-9]{1,2})\s*(across|down|ac\b|dn\b|a\b|d\b)")
STOPCAPS = {"COD", "LOI", "FOI", "NHO", "DNF", "PDM", "I", "A", "OK", "TV", "US", "UK", "BBC"}


def load_corpus():
    """id -> {answers: {normalised answer: entry id}, refs: {(n, dir): entry id}}."""
    out = {}
    for path in sorted(glob.glob(os.path.join(PUZZLES, "*.js"))):
        raw = open(path, encoding="utf-8").read()
        if "/*JSON-START*/" not in raw:
            continue
        body = raw.split("/*JSON-START*/", 1)[1].rsplit("/*JSON-END*/", 1)[0]
        try:
            puz = json.loads(body)
        except ValueError:
            continue
        if "entries" not in puz:   # puzzles/index.js is in the same glob
            continue
        answers, refs = {}, {}
        for e in puz.get("entries", []):
            sol = (e.get("solution") or "").upper()
            if sol:
                answers[re.sub(r"[^A-Z]", "", sol)] = e["id"]
            refs[(e["number"], e["direction"][0])] = e["id"]
        out[puz["id"]] = {"answers": answers, "refs": refs}
    return out


def puzzle_id(title):
    m = TITLE.search(title)
    if not m:
        return None
    return "%s-%s" % (SERIES[m.group(1).lower()], m.group(2).replace(",", ""))


def text_of(rendered):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(rendered)).split())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", help="write the resolved votes here")
    ap.add_argument("--top", type=int, default=15, help="how many most-cited clues to print")
    ap.add_argument("--window", type=int, default=60,
                    help="characters either side of the favourite word a candidate may sit in")
    args = ap.parse_args()

    corpus = load_corpus()
    posts = sorted(glob.glob(os.path.join(CACHE, "posts", "*.json")))
    stats = collections.Counter()
    votes = collections.Counter()
    vote_rows = []
    joined_posts = set()

    for path in posts:
        post = json.load(open(path, encoding="utf-8"))
        stats["posts"] += 1
        title = post["title"]
        title = title["rendered"] if isinstance(title, dict) else title
        pid = puzzle_id(text_of(title))
        puz = corpus.get(pid) if pid else None
        if pid:
            stats["posts_identified"] += 1
        if puz:
            stats["posts_in_corpus"] += 1

        cpath = os.path.join(CACHE, "comments", os.path.basename(path))
        if not os.path.exists(cpath):
            continue
        for c in json.load(open(cpath, encoding="utf-8")):
            stats["comments"] += 1
            body = text_of(c["content"]["rendered"] if isinstance(c["content"], dict) else c["content"])
            if not FAVOURITE.search(body):
                continue
            stats["comments_favouriting"] += 1
            if not puz:
                continue
            stats["comments_favouriting_in_corpus"] += 1

            # Only candidates sitting beside the favourite word count. A comment
            # that says "couldn't parse GRUEL. Favourite was WHOA" names two
            # answers and likes one of them.
            spans = [m.span() for m in FAVOURITE.finditer(body)]

            def near(start, end):
                return any(start < b + args.window and end > a - args.window for a, b in spans)

            hits = set()
            for m in CAPS.finditer(body):
                key = re.sub(r"[^A-Z]", "", m.group(0))
                if len(key) < 3 or m.group(0) in STOPCAPS:
                    continue
                if key in puz["answers"] and near(*m.span()):
                    hits.add(puz["answers"][key])
            for m in GRIDREF.finditer(body):
                eid = puz["refs"].get((int(m.group(1)), m.group(2)[0].lower()))
                if eid and near(*m.span()):
                    hits.add(eid)
            if not hits:
                continue
            stats["comments_resolved"] += 1
            joined_posts.add(pid)
            for eid in hits:
                votes[(pid, eid)] += 1
                vote_rows.append({"puzzle": pid, "entry": eid, "author": c.get("author_name"),
                                  "date": c.get("date"), "comment": c["id"]})

    print("fifteensquared favourites survey")
    for k in ("posts", "posts_identified", "posts_in_corpus", "comments",
              "comments_favouriting", "comments_favouriting_in_corpus", "comments_resolved"):
        print("  %-32s %7d" % (k, stats[k]))
    print("  %-32s %7d" % ("clues with >=1 vote", len(votes)))
    print("  %-32s %7d" % ("puzzles with >=1 vote", len(joined_posts)))
    if votes:
        print("\nmost-cited clues")
        for (pid, eid), n in votes.most_common(args.top):
            print("  %2d  %-22s %s" % (n, pid, eid))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(vote_rows, fh, indent=1)
        print("\nwrote %d votes to %s" % (len(vote_rows), args.json))


if __name__ == "__main__":
    main()
