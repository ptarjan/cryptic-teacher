#!/usr/bin/env bash
# tools/showcase.py picks only what a file states: each detector on a real
# puzzle that has the feature and off the look-alike that does not.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import fetch_puzzle as fp
import showcase as sc

fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)

def real(pid):
    return fp.read_puzzle_file(fp.resolve_puzzle(pid))

def facts(pid):
    return sc.facts(real(pid), None)

# --- a hidden message counts only when the note says where to look ---
for pid in ("quiptic-733", "cyclops-820", "cryptic-23113"):
    check(f"{pid}'s note announces a hidden message", "hidden-message" in facts(pid)["tags"])
# "hidden in the clue" is wordplay, and an erratum mentions no grid at all.
for pid in ("cryptic-22863", "cryptic-25416", "cryptic-24355"):
    check(f"{pid} is no hidden message", "hidden-message" not in facts(pid)["tags"])

# --- jigsaws ---
check("an alphabetical jigsaw is a jigsaw", sc.puzzle_tags.has_tag(facts("cryptic-24331")["tags"], "jigsaw"))
check("an A-to-Z of 27 answers is in the alphabet section",
      "cryptic-24331" in [f["id"] for f in dict((x[0], x[3]) for x in sc.specs([facts("cryptic-24331")]))["alphabetical"]])
check("a theme note is not a jigsaw", not sc.puzzle_tags.has_tag(facts("cryptic-22863")["tags"], "jigsaw"))

# --- records ---
quote = real("cryptic-23801")
check("a quotation over seven lights is one 65-letter answer",
      sc.longest_answer(quote) == (65, 7), sc.longest_answer(quote))
slip = copy.deepcopy(quote)
for e in slip["entries"]:
    if e.get("group") and len(e["group"]) > 1:
        e["clue"]["enumeration"] = "3"
check("a count that disagrees with its squares sets no record",
      sc.longest_answer(slip)[0] < 65, sc.longest_answer(slip))
check("the 90-clue Jumbo counts 90 clues", facts("timesjumbo-1423")["answers"] == 90,
      facts("timesjumbo-1423")["answers"])
# Any book puzzle: one is dropped when its newspaper original is filed.
book = min(fp.ROOT.glob("puzzles/book/*/book-*.json")).stem
check("a book's year is not a print date", not facts(book)["dated"])
check("a book's number is volume and position, not an issue",
      not facts(book)["counted"])
check("a date-keyed number is not an issue", not facts("metro-20260902")["counted"])

# --- selection ---
def fake(i, series, **kw):
    f = {"id": f"{series}-{i}", "series": series, "number": i, "day": i, "dated": True,
         "answers": 28, "longest": None, "tags": [],
         "difficulty": None, "counted": True, "annotated": True}
    f.update(kw)
    return f
pool = ([fake(i, "cryptic", tags=["hidden-message", "jigsaw"]) for i in range(1, 9)]
        + [fake(i, "cyclops", tags=["hidden-message"]) for i in range(1, 3)])
got = sc.sections(pool)
check("/showcase/ shows the first of a ranking's own page",
      all(full is None or cards == full[1][:sc.PER_SECTION]
          for slug, _, _, cards, full in got if slug not in sc.puzzle_tags.TAGS))
check("/showcase/ shows a feature's cards from its own page",
      all(full is None or all(c in full[1] for c in cards) for *_, cards, full in got))
page = next(full for slug, *_, full in got if slug == "hidden-message")
check("a feature's own page lists every hinted puzzle with it, whatever the series",
      page[2] == "all 10" and len(page[1]) == 10, page[2])
few = sc.sections([fake(i, "mephisto", tags=["barred"]) for i in range(1, 9)])
check("a feature one series holds still gets its own page of all of them",
      next(full for slug, *_, full in few if slug == "barred")[2] == "all 8")
mixed = sc.sections([fake(i, "cryptic", tags=["barred"], annotated=i < 9) for i in range(1, 13)])
check("a feature's page says how many more the puzzle list holds unhinted",
      "4 more have it" in next(full for slug, *_, full in mixed if slug == "barred")[0])
msg = next(cards for slug, _, _, cards, _ in got if slug == "hidden-message")
check("no series takes more than its share of a section",
      sum(f["series"] == "cryptic" for f, _ in msg) == 3, [f["id"] for f, _ in msg])
check("a section with nothing to show is left out",
      "pangram" not in [slug for slug, *_ in got])

# --- only hinted puzzles; the burn is told which unhinted ones to do first ---
pool = [fake(i, "cryptic", tags=["hidden-message"], annotated=i % 2 == 0) for i in range(1, 9)]
shown = [f["id"] for _, _, _, cards, _ in sc.sections(pool) for f, _ in cards]
check("the showcase shows only annotated puzzles",
      shown and all(int(i.split("-")[1]) % 2 == 0 for i in shown), shown)
check("wanted() names the unhinted puzzles it would have shown",
      sorted(sc.wanted(pool)) == ["cryptic-1", "cryptic-7"],
      sc.wanted(pool))

# --- a pick opens the solver, and no reader page may link an answer page ---
import pathlib
import build_seo_pages as B
meta = {f["id"]: {"id": f["id"], "series": "cryptic", "number": f["number"],
                  "date": "2020-01-01", "annotated": True} for f in pool}
page = B.showcase_page(sc.sections(pool), meta)
check("a showcase row opens the puzzle in the app",
      f'href="{B.BASE}/?p=cryptic-8"' in page and "/puzzles/cryptic-8/" not in page)
check("a clue link opens the app on that clue",
      B.solve_url("cryptic-8", "21-across") == f"{B.BASE}/?p=cryptic-8&amp;c=21A")
def refused(rel, text):
    try:
        B.assert_no_answer_links(B.ROOT / rel, text)
    except SystemExit:
        return True
    return False
answer = f'<a href="{B.BASE}/puzzles/cryptic-8/#21-across">x</a>'
for rel in ("showcase", "abbreviations", "indicators", "learn", "difficulty"):
    check(f"/{rel}/ may not link an answer page", refused(f"{rel}/index.html", answer))
check("a relative answer link is refused too",
      refused("indicators/index.html", '<a href="../puzzles/cryptic-8/">x</a>'))
check("the hub and series links are not answer pages",
      not refused("showcase/index.html", f'<a href="{B.BASE}/puzzles/">x</a>'
                  f'<a href="{B.BASE}/puzzles/series/cryptic/">y</a>'))
row = B.hub_row(meta["cryptic-8"])
check("an archive row opens the app and links the answer page beside it",
      row.startswith(f'<li><a href="{B.BASE}/?p=cryptic-8">')
      and f'<a class="p-answers" href="{B.BASE}/puzzles/cryptic-8/">answers</a></li>' in row, row)
import re
check("an archive row dates itself in the app list's short form",
      re.search(r'<span class="p-meta">(\w{3} \d{1,2} \w{3} \d{4}|\d{4})</span>', row), row)
listing = f'<ul class="s-index">{row}</ul>'
check("the archive listings may link answer pages beside the row, their crawl path",
      not refused("puzzles/series/cryptic/2020/index.html", listing))
check("an archive row whose own link is the answer page is refused",
      refused("puzzles/series/cryptic/2020/index.html",
              f'<ul class="s-index"><li><a href="{B.BASE}/puzzles/cryptic-8/">x</a></li></ul>'))
check("the old-number chooser may link the answer pages it replaced",
      not refused("puzzles/30000/index.html",
                  f'<ul><li><a href="{B.BASE}/puzzles/cryptic-30000/">x</a></li></ul>'))

# --- easiest beside hardest; each list's whole ranking on its own page ---
# Two puzzles in each of eight series, undated so the oldest section takes none.
names = [f"s{n}" for n in range(8)]
pool = [fake(i, s, difficulty=(8 - n) + i / 10, dated=False)
        for n, s in enumerate(names) for i in (1, 2)]
got = {slug: (cards, full) for slug, _, _, cards, full in sc.sections(pool)}
hard = [f["id"] for f, _ in got["hardest"][0]]
easy = [f["id"] for f, _ in got["easiest"][0]]
check("the hardest lead with the top rating, one per series",
      hard[:2] == ["s0-2", "s1-2"], hard)
check("the easiest lead with the bottom rating, one per series",
      easy[:2] == ["s7-1", "s6-1"], easy)
full = [f["id"] for f, _ in got["hardest"][1][1]]
check("every section's /showcase/ cards are the first of its own page",
      all(full is None or cards == full[1][:sc.PER_SECTION] for cards, full in got.values()))
check("a page that holds every candidate says all", got["hardest"][1][2] == "all 8", got["hardest"][1][2])
check("a list's own page keeps the series cap /showcase/ shows",
      full == [f"{s}-2" for s in names], full)
meta = {f["id"]: {"id": f["id"], "series": f["series"], "number": f["number"],
                  "date": "2020-01-01", "annotated": True} for f in pool}
secs = sc.sections(pool)
pages = dict(B.showcase_list_pages(secs, meta))
hp = pages.get(B.ROOT / "showcase" / "hardest" / "index.html", "")
check("the hardest has its own page, rows opening the solver",
      f'href="{B.BASE}/?p=s7-2"' in hp and not refused("showcase/hardest/index.html", hp))
check("/showcase/ links the list's page",
      f'href="{B.BASE}/showcase/hardest/"' in B.showcase_page(secs, meta))
check("a list page may not link an answer page",
      refused("showcase/hardest/index.html", answer))
one = [fake(1, "cryptic", difficulty=1.0)]
check("a section that shows all it has gets no page",
      all(full is None for *_, full in sc.sections(one)), sc.sections(one))
check("the sitemap lists the list pages",
      f"{B.BASE}/showcase/hardest/" in B.sitemaps(B.index_json(), [f"{B.BASE}/showcase/hardest/"])[1][1])

# --- the oldest section: one puzzle per paper, oldest first ---
mk = lambda i, series, day, dated=True: {"id": i, "series": series, "day": day,
    "dated": dated, "annotated": True, "tags": [],
    "answers": 1, "longest": None, "difficulty": None, "number": 1, "counted": False}
old = sc.oldest_per_paper([mk("a2", "cryptic", 200), mk("a1", "cryptic", 100),
                           mk("t1", "times", 50), mk("b1", "cryptic", 10, False)])
check("the oldest shows one dated puzzle per paper, oldest first",
      [f["id"] for f in old] == ["t1", "a1"], [f["id"] for f in old])

# --- pangrams: every one, most repeats first; the rankings lead ---
# Undated, so the oldest section takes none; the most clues take the six fillers.
pool = [fake(i, f"filler{i}", answers=99, dated=False) for i in range(6)]
pool += [fake(1, "cryptic", tags=["pangram"], dated=False),
         fake(2, "cryptic", tags=["pangram"], dated=False),
         fake(3, "times", tags=["double-pangram"], dated=False),
         fake(4, "times", dated=False)]
got = {slug: cards for slug, _, _, cards, _ in sc.sections(pool)}
pg = [(f["id"], note) for f, note in got.get("pangram", [])]
check("every pangram shows, most repeats first, then newest, each noting its own tag",
      pg == [("times-3", "every letter twice in the grid"), ("cryptic-2", "every letter in the grid"),
             ("cryptic-1", "every letter in the grid")], pg)
order = [slug for slug, *_ in sc.specs([])]
check("the rankings lead, before the features",
      order[:4] == ["longest", "hardest", "easiest", "most-clues"], order)
old = [note for slug, _, _, cards, _ in sc.sections([fake(1, "cryptic")])
       if slug == "oldest" for _, note in cards]
check("the oldest cards carry no note beside the series badge", old == [""], old)

# --- one definition per feature: the app's filter and /showcase/ cannot drift ---
import puzzle_tags as pt
top = {t for t, info in pt.TAGS.items() if "implies" not in info}
feature_secs = {s[0]: s for s in sc.specs([]) if s[0] in pt.TAGS}
check("every filter feature has a showcase section or a stated reason it has none",
      set(feature_secs) | set(sc.NOT_SHOWCASED) == top
      and not set(feature_secs) & set(sc.NOT_SHOWCASED), sorted(top ^ set(feature_secs)))
check("every reason a feature is not showcased is stated",
      all(isinstance(r, str) and r.strip() for r in sc.NOT_SHOWCASED.values()), sc.NOT_SHOWCASED)
rankings = {"longest", "hardest", "easiest", "most-clues", "round-numbers"}
check("every other showcase section is a ranking, not a feature the filter lacks",
      {s[0] for s in sc.specs([])} - set(feature_secs) == rankings,
      {s[0] for s in sc.specs([])} - set(feature_secs))
check("a feature section's heading and blurb are its tag's label and blurb",
      all(h.lower() == pt.TAGS[t]["label"].lower() and b == pt.TAGS[t]["blurb"]
          for t, h, b, *_ in feature_secs.values()))
mixed = [fake(1, "a", tags=["numbered-jigsaw"]), fake(2, "b", tags=["jigsaw"]),
         fake(3, "c", tags=["quintuple-pangram"]), fake(4, "d", tags=["barred"])]
check("a feature section takes exactly the puzzles the filter's tag test does",
      all([f["id"] for f in s[3]] == [f["id"] for f in mixed if pt.has_tag(f["tags"], s[0])]
          for s in sc.specs(mixed) if s[0] in pt.TAGS))
check("the first-letters and in-the-grid features say which in their names",
      "first letters" in pt.TAGS["alphabetical"]["label"] and "grid" in pt.TAGS["pangram"]["label"])

print("\n%d failure(s)" % fails)
raise SystemExit(fails > 0)
PY
