#!/usr/bin/env python3
# Does tools/genius_puzzles.py read an old Guardian article page's text
# without markup, keep the Genius's printed pair of counts, and does the write
# gate refuse a tag's remnant in any string?
#
#     python3 tools/test_genius_puzzles.py
#
# The article reader once began its capture mid-tag, so ` class="dcr-47amn7">`
# (the tag's rest, with no "<" for the tag strip to take) was filed as the
# preamble of 25 puzzles; and enumeration.split() cut "(4,3)" off genius-135's
# "(4,3) (7)" as an echo of the 7. Hand-built inputs, plus a look at those
# filed files.
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)
import enumeration as E
import file_blog_puzzles as F

fails = 0
lines = []


def emit(*parts):
    lines.append(" ".join(str(p) for p in parts))


def get(key):
    """The rest of the first output line that opens with KEY."""
    for l in lines:
        if l.startswith(key + " "):
            return l.split(" ", 1)[1]
    return ""


def check(what, got, want):
    global fails
    if got == want:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{want}], got [{got}]")
        fails += 1


import glob, json
import genius_puzzles as G
import enumeration as E
import validate_annotations as V

page = ('<div data-gu-name="standfirst" class="dcr-47amn7"></div>'
        '<aside data-gu-name="meta" class="dcr-1mjlkeb">byline</aside>'
        '<div data-gu-name="body" class="dcr-13wig6c"><p class="dcr-1s160rg">'
        '<strong>Across</strong><br/><strong>1</strong> Leaves disappear (4,3) (7)'
        '<br/><strong>5</strong> Nice art (7)</p></div>'
        '<div data-gu-name="footer">Explore more on these topics</div>')
text = G.article_text(page)
emit("text-no-markup", "class=" not in text and "dcr-" not in text)
parsed = G.parse_text(text)
emit("empty-standfirst-no-preamble", parsed["preamble"])
emit("pair-read", parsed["clues"][0]["clue"], "|", parsed["clues"][0]["enumeration"])

small = G.parse_text("In order to enter the competition, entries must be submitted in the form "
                     "below (including a valid email address). This grid was updated on 4 February "
                     "2015 to correct an error. In 11 clues the wordplay produces a letter. "
                     "Across 1 Clue words here (5)")
emit("small-print-cut", small["preamble"])

both = G.parse_text("Fill in the blanks. Across Down 1 Swiss bank (8) 5 Guardian setters (6) "
                    "1 Arm supporter (6) 2 Just a little (9)")
emit("headings-together", [(c["lights"][0][0], c["lights"][0][1][0]) for c in both["clues"]])
tail = G.parse_text("Clues ACross Instructions Eight solutions comprise the theme. GENIUS 165 SET BY VLAD "
                    "Down 1 Work for two (3,5) 3 See preamble 4 Open land (4) "
                    "1 See preamble 6 With money (3,2,1,4)")
emit("unheaded-run", [(c["lights"][0][0], c["lights"][0][1][0], c["clue"]) for c in tail["clues"]])

emit("split-echo", E.split("Set meal (5,1'4) (5,5)"))
emit("split-paired", E.split("Leaves disappear (4,3) (7)", paired=True))
emit("echoed", E.echoed("Leaves disappear (4,3) (7)"), E.echoed("Words (3) (7)"), E.echoed("Words (7)"))
c = E.clue("Leaves disappear (4,3) (7)", pairedCount=True)
emit("clue-paired", c)
emit("unsplit-paired", E.unsplit(c, {7}),
      E.unsplit({"text": "Leaves disappear (4,3)", "enumeration": "7"}, {7}))
emit("printed-paired", E.printed(c))

for i, s in enumerate(['class="dcr-47amn7">', "dcr-47amn7", '<p>x</p>', "Plain words (4,3)", "a class act"]):
    errs = []
    V.text_errors({"preamble": s}, errs)
    emit(f"markup{i}", bool(errs))

bad = [f for f in glob.glob("puzzles/genius/*/genius-*.json")
       if V.MARKUP_RE.search(json.dumps(json.load(open(f)), ensure_ascii=False).replace('\\"', '"'))]
emit("corpus-genius-clean", bad)

# genius-8's article page prints a T standing for each theme word, as its
# own word: "<strong>13</strong> T going west". Article text keeps it apart
# (even where the join is a word, "Ton hill"); PDF text rejoins a capital
# kerned off its word only when the join is one.
g8 = ('<div data-gu-name="body" class="dcr-13wig6c"><p><strong>Across</strong><br/>'
      '<strong>11</strong> T with a long T wasting nothing in 12, T: the key (4,10)<br/>'
      '<strong>13</strong> T going west in form of lottery (7,3)<br/>'
      '<strong>22</strong> An extended T on hill (4)</p></div>'
      '<div data-gu-name="footer">Explore more on these topics</div>')
emit("letter-apart", [c["clue"] for c in G.parse_text(G.article_text(g8))["clues"]])
emit("ligatures", G.flat("stu\ufb00 to sco\ufb00, \ufb01ne"))
emit("kern-rejoin", G.flat("T earful T going T his T urpin X and"))

# The filed corpus: a capital glued onto a common word that is no word with
# it ("Tgoing", "Xsupport") is the join above. genius-210's preamble is
# enciphered ("Pof pg uiftf"); NAMES are names the lexicon lacks.
import re, ft_pdf_puzzles as fpp
glued, NAMES = [], {"Edam", "Fred", "Jones", "Vera"}
for f in sorted(glob.glob("puzzles/genius/*/*.json")):
    p = json.load(open(f))
    if p["id"] == "genius-210":
        continue
    for t in [e["clue"].get("text", "") for e in p["entries"] if isinstance(e.get("clue"), dict)] + [p.get("preamble") or ""]:
        for m in re.finditer(r"(?<![A-Za-z'&-])([B-HJ-Z])([a-z]{2,})(?![A-Za-z'-])", t):
            r = fpp.rank(m.group(2))
            if m.group(0) not in NAMES and fpp.rank(m.group(0)) is None and r is not None and r < 3000:
                glued.append((p["id"], m.group(0)))
emit("corpus-no-glued-letter", glued)
f = glob.glob("puzzles/genius/*/genius-135.json")
if f:
    e = json.load(open(f[0]))["entries"][0]["clue"]
    emit("genius-135-1a", E.printed(e), e.get("pairedCount"))

# Layout faults that held 233 161 162 112 165 76 (2026-10-12).
cl = G.parse_text("Genius No 233 Across 8 Bit of theatre role almost went wrong 9 Outlines injuries, losing time "
                  "10 Amount of drink 11 Article about dancing in the Guardian? 12 Retreats in France from Poles "
                  "All down clues and solutions are normal. All across ones are shifted. Down 1 Upshot mostly (6) 2 Shiner (4)")
emit("countless", [(c["lights"][0][0], c["clue"]) for c in cl["clues"][:6]])
emit("countless-preamble", cl["preamble"])
lost = G.parse_text("Across 1 Light meat (6) Down 7 I live (4) 8 Dropping belt (4) 2 Amazing half day (10) 13 One taking over (8)")
emit("lost-leading-1", [c["lights"][0] for c in lost["clues"]])
stray = G.parse_text("Across 1 Light meat (6) Down 5 Press carpet (6) 19 Feature of brute (8) 7 By one (7) 19 Feature of brute (8) 20 Germany (7)")
emit("stray-copy", [c["lights"][0][0] for c in stray["clues"] if c["lights"][0][1] == "down"])
two = G.parse_text("Across 20 Short key (4,4) 22,17,3 Short key, article (6,7) 22,2,5 Overcome a novel (4,4,5) 23 Short book (3)")
emit("two-22s", [c["lights"] for c in two["clues"]])
st = G.parse_text("Across 1 See special instructions 10 Make out (9) 26 See special instructions (8) Down 2 One (7)")
emit("stub-uncounted", [(c["lights"][0][0], c["clue"]) for c in st["clues"]])
sl = [{"lights": [(12, "across")], "clue": "Heritage (3,8)", "enumeration": "3,8"},
      {"lights": [(2, "down")], "clue": "See 12 across", "enumeration": None},
      {"lights": [(12, "down")], "clue": "Jack (3)", "enumeration": "3"}]
G.see_links(sl)
emit("see-way", sl[0]["lights"], sl[2]["lights"])
# "1,13 ... (5,9,8)" across and a 1 down: "13 See 1" is already 1 across's (22).
both = G.parse_text("Across 1,13 A Fonteyn ruined (5,9,8) 13 See 1 Down 1 Condition arising (7,7) 2 Outfit (7)")
G.see_links(both["clues"])
emit("see-taken", [c["lights"] for c in both["clues"] if c["enumeration"]])
# Unheaded "See 8" with only 8 down leading: joins it (60's GRACIE FIELDS).
one = G.parse_text("Across 5 See 8 9 Kick (5) Down 8 Rochdale cries (6)")
G.see_links(one["clues"])
emit("see-own", [c["lights"] for c in one["clues"] if c["enumeration"]])
star = G.parse_text("Across 22 What Persians took (*,6) 24 Pub punch (10) Down 14 * (part 1) * (part 2) in the field (5,4)")
emit("star-count", [(c["lights"][0][0], c["enumeration"]) for c in star["clues"]])
emit("misprinted-60", sorted(G.misprinted(60)), sorted(G.misprinted(59)))
emit("unnumbered", G.unnumbered("Solutions to the remaining clues have their place About this (4,3) Anti pig (7) "
                                 "Art in tears (7) Barren function (4,5) Boy (5)"),
      G.unnumbered("8 Extremely insalubrious (8) 9 Novel (6) 10 Voyeur (13) 11 Story (9) 12 Vehicle (5)"))
pre = G.parse_text("Clues ACross Instructions Eight solutions comprise the theme, supporter and World Cup winners. "
                   "Deadline for entries is 23:59 GMT. GENIUS 165 SET BY VLAD Down 1 Work for two (3,5) 2 Stop (3)")
emit("preamble-165", pre["preamble"])
# Numbered clues stranded outside any heading the reader knows (157), a spaced byline and grid numbers
# left in the preamble, a setter named in the post's first words (103), a stretched grid (157).
sr = G.parse_text("across 8 Brown animal in city (8) 9 Novel about trouble (6) 10 Voyeur on trial (13) "
                  "Down 1 French department (6) 2 Place to learn (8) 3 Follower of Attlee (9) "
                  "rules anD requests Half the solutions are entered in a 10 across manner. "
                  "Genius no. 157 s et by P iCAROO n 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16")
emit("stranded-run", [(c["lights"][0][0], c["lights"][0][1][0]) for c in sr["clues"]])
emit("stranded-preamble", sr["preamble"])
emit("body-setter", G.post_setter({"title": {"rendered": "Guardian Genius 103"},
      "content": {"rendered": "<p> Lavatch  is a setter whose puzzles always change the word.</p>"}}),
      G.post_setter({"title": {"rendered": "Guardian Genius 84: elastic despair"},
      "content": {"rendered": "<p>This month&#8217;s theme involved removing words.</p>"}}))
fr = ([(0, 0, 285.3, 1.2, False)] * 8) + ([(0, 0, 1.3, 252.2, False)] * 8)
sq = G.unstretched(fr + [(0, 0, 17.6, 15.6, True)])
emit("unstretched", round(sq[-1][3] - sq[-1][1], 1))
for n, want in ((161, None), (162, None), (165, 8), (84, 0), (101, 2), (108, 6), (112, 5)):
    f = glob.glob(f"puzzles/genius/*/genius-{n}.json")
    if f:
        es = json.load(open(f[0]))["entries"]
        emit(f"filed-{n}", len(es), sum(bool(e["clue"].get("missing")) for e in es))
        emit(f"setter-{n}", json.load(open(f[0])).get("setter"))
f = glob.glob("puzzles/genius/*/genius-76.json")
if f:
    z = json.load(open(f[0]))
    emit("filed-76", z.get("cluesUnplaced"), z.get("preamble"),
          next(e["clue"]["text"] for e in z["entries"] if (e["number"], e["direction"]) == (27, "across")))
f = glob.glob("puzzles/genius/*/genius-250.json")
if f:
    z = json.load(open(f[0]))
    hd = next(e for e in z["entries"] if (e["number"], e["direction"]) == (1, "down"))
    emit("filed-250", z.get("cluesUnplaced"), sum("alteration" in e for e in z["entries"]),
          hd["solution"], hd["alteration"]["from"], hd["clue"]["enumeration"], z["preamble"].startswith("Normal") and "Twelve clues" in z["preamble"])
emit("placed-words", G.placed_words("<p>\u2013 SA CAUTION / CAU SA TION Heading away from Quantico, criminal gives warning (7)</p>",
                                     "Heading away from Quantico, criminal gives warning (7)"))
f = glob.glob("puzzles/genius/*/genius-233.json")
if f:
    z = json.load(open(f[0]))
    emit("filed-233", z["solutions"]["origin"],
          sum("enumeration" not in e["clue"] for e in z["entries"] if e["direction"] == "across"),
          sum("enumeration" in e["clue"] for e in z["entries"] if e["direction"] == "down"))
f = glob.glob("puzzles/genius/*/genius-7.json")
if f:
    z = json.load(open(f[0]))
    emit("unsolved-nosetter", z["solutions"]["origin"], z.get("setter"))
# A post whose answers do not go in files unsolved only once the grid matched
# the clue list: no grid-mismatch class falls back.
emit("fallback-classes", sorted(G.UNSOLVED_FALLBACK - G.ALTERABLE),
      any(k in G.UNSOLVED_FALLBACK for k in ("enumeration is not the entry's length", "lights left unclued",
                                             "grid numbering differs from clue list", "grid unread")))
import datetime
hc = G.hold_clues(999, {"setter": None, "preamble": "", "grid": None,
                        "clues": [{"lights": [(1, "across")], "enumeration": "7", "clue": "Water lily (7)"},
                                  {"lights": [(2, "down")], "enumeration": "5", "clue": "Some tree (5)"}]},
                  datetime.date(2007, 6, 4), "https://example.org/g999", write=False)
emit("hold-clues", hc[0] == G.HELD_CLUES, "grid unread" in G.GRID_MISFIT)
import clues_only as CO
emit("numbered-builder", CO.builder({"source": {"acquiredBy": "tools/genius_puzzles.py"}}) is CO._genius_numbered_build)
f = glob.glob("puzzles/genius/*/genius-44.json")
if f:  # the burn may since have solved it ("model"); only the post's answers are wrong
    emit("filed-44", json.load(open(f[0]))["solutions"]["origin"] != "writeup")

# Every clue printed unnumbered (280): the list and its instruction read apart,
# held clues-only, then placed on the printed grid once answered.
import clues_only
uc, up = G.unplaced_clues("A board devoid of soft fruit (4) Hard back (5) Clues are listed in alphabetical "
                          "order of their answers, to be entered jigsaw-fashion where they will fit. "
                          "Workforce keeping mum (3-4) Run dry (4)")
emit("unplaced-clues", uc)
emit("unplaced-preamble", up)
ws = ["ABCD", "HIJK", "AEH", "CFJ", "DGK", "FG"]
rec = {"number": 9999, "date": "2026-01-01", "setter": "Test", "preamble": "Fit them.",
       "source": {"url": "https://example.com/g"},
       "clues": {"unplaced": [{"clue": {"text": f"Clue {i}", "enumeration": str(len(w))}, "length": len(w)}
                              for i, w in enumerate(ws)]}}
grid = ["....", ".#..", "...."]
pz, why = G.promote_jigsaw(rec, {"unplaced": ws}, grid=grid)
emit("jigsaw-placed", why, sorted(pz["_parts"].items()), pz["cluesUnplaced"])
rec["clues"]["unplaced"].append({"clue": {"text": "Below the grid", "enumeration": "3"}, "length": 3})
pz, why = G.promote_jigsaw(rec, {"unplaced": ws + ["XYZ"]}, grid=grid)
emit("jigsaw-off-grid", why, pz["offGrid"], pz["_parts"]["1-offgrid"])
emit("jigsaw-off-grid-count", G.promote_jigsaw(rec, {"unplaced": ws + ["XY"]}, grid=grid)[1])
# The off-grid clue through the solve, the write gate and the validator.
import apply_solution, puzzle_integrity, validate_annotations, fetch_puzzle, groups
parts = pz.pop("_parts")
fill = {eid: letters for eid, (_, letters) in parts.items()}
emit("off-grid-fill", apply_solution.check_fill(pz, fill)[2], apply_solution.check_off_grid(pz, fill),
      apply_solution.check_off_grid(pz, {**fill, "1-offgrid": "XY"}))
for e in pz["entries"]:
    e["solution"] = fill[groups.entry_id(e)]
pz["offGrid"][0]["solution"] = "XYZ"
flags = []
puzzle_integrity.check_puzzle_text(pz, flags)
pz["offGrid"][0]["solution"] = "XYZW"
puzzle_integrity.check_puzzle_text(pz, flags)
emit("off-grid-gate", [f[2] for f in flags])
pz["offGrid"][0]["solution"] = "XYZ"
emit("off-grid-done", fetch_puzzle.puzzle_is_solved(pz), [groups.entry_id(e) for e in fetch_puzzle.unannotated_clues(pz)][-1])
pz["offGrid"][0]["annotation"] = {"type": ["charade"], "answer": "XYZ", "definitions": [{"text": "Below", "at": 3}],
    "blocks": [{"clueFragment": "the grid", "gives": "XYZ", "note": "n"}], "explanation": {"walkthrough": "w"}}
emit("off-grid-validate", [m.split(";")[0] for m in validate_annotations.validate_puzzle(pz)[1] if m.startswith("1-offgrid")])
emit("jigsaw-builder", clues_only.builder({"cluesUnplaced": True, "series": "genius",
      "source": {"acquiredBy": "tools/genius_puzzles.py"}}) is not None, 280 in G.SCHEMA_GAP)
# A grid read sound but a clue list not covering it light for light files
# unsolved on that grid (unsolved_special); a misread is still refused.
import copy
sg = [".....", ".#.#.", ".....", ".#.#.", "....."]
def sp(clues, preamble=None, article=False, marked=()):
    return {"grid": sg, "setter": "Test", "preamble": preamble, "article": article, "marked": set(marked),
            "origin": "a test", "clues": [{"lights": [l], "clue": f"{t} ({k})", "enumeration": k}
                                          for l, t, k in clues]}
base = [((1, "across"), "Alpha clue", "5"), ((1, "down"), "Down one", "5"), ((2, "down"), "Down two", "5"),
        ((3, "down"), "Down three", "5"), ((4, "across"), "Four", "5")]
d = datetime.date(2020, 1, 6)
pz, why = G.unsolved_special(9998, sp(base, "Five across is unclued."), d, "https://example.org/g")
emit("special-unclued", why, [e["clue"] for e in pz["entries"] if e["number"] == 5], pz["solutions"]["origin"])
emit("special-undeclared", G.unsolved_special(9998, sp(base, "Answers are normal."), d, "u")[1])
emit("special-marked", G.unsolved_special(9998, sp(base, "See preamble.", marked=[(5, "across")]), d, "u")[1])
extra = base + [((5, "across"), "Five", "5"), ((6, "down"), "No such light", "4")]
emit("special-extra", G.unsolved_special(9998, sp(extra, "Unclued lights."), d, "u")[1])
inpre = G.unsolved_special(9998, sp(base, "Two unclued. 5 Missed clue run on (5)"), d, "u")[1]
emit("special-clue-in-preamble", inpre)
loose = [((1, "across"), "Alpha clue", "7")] + base[1:] + [((5, "across"), "Five", "5")]
pz, why = G.unsolved_special(9998, sp(loose, "Entries lose two letters before entry."), d, "u")
e1 = next(e for e in pz["entries"] if e["number"] == 1 and e["direction"] == "across")
emit("special-loose", why, e1["clue"].get("enumeration"), e1["length"], "awaitsPreamble" in pz)
emit("special-loose-no-preamble", G.unsolved_special(9998, sp(loose), d, "u")[1])
pz, why = G.unsolved_special(9998, sp(loose, article=True), d, "u")
emit("special-loose-article", why, pz.get("awaitsPreamble"))
counted = sp(base + [((5, "across"), "", "5")], "Normal.")
counted["clues"][-1]["clue"] = "(5)"
pz, why = G.unsolved(9998, counted, d, "u")
emit("count-only-blank", why, [e["clue"] for e in pz["entries"] if e["number"] == 5])
allcounts = sp(base + [((5, "across"), "", "5")], "Normal.")
for c in allcounts["clues"]:
    c["clue"] = f"({c['enumeration']})"
G.MOST_UNCLUED, most = 3, G.MOST_UNCLUED
emit("count-only-many", G.unsolved(9998, allcounts, d, "u")[1])
G.MOST_UNCLUED = most
bl, bp = G.bulleted_clues("● Keeps elastic pants worn by date ● Most vulgar fan of Labour PM uncovered "
                          "stealing French art All clues are normal and all solutions are single words. However, "
                          "the solutions are in no particular order. ● Yellow colour? It might be this")
emit("bulleted", bl, "|", bp)
# An image-only PDF's clues file only when both OCR readers read them alike.
import ocr_clues
from PIL import Image
said = {}
real = ocr_clues.read_words, ocr_clues.lines_of
ocr_clues.read_words, ocr_clues.lines_of = (lambda crop, which: which), (lambda which: said[which])
G.OCR_BOXES[9997] = [(0, 0.5, 1, 1)]
page = Image.new("L", (100, 200), 255)
said.update(en5="Across\n7Lives in abandon (6)\n8 Spooner's fighting’usky? (8)\nDown\n1 Pip — hung (6)",
            times="Across\n7 Lives in abandon (6)\n8 Spooner's fighting 'usky? (8)\nDown\n1 Pip hung (6)")
got, why = G.ocr_page(9997, page)
emit("ocr-agree", why, [c["clue"] for c in got["clues"]])
said["times"] = said["times"].replace("abandon", "abanden")
emit("ocr-disagree", G.ocr_page(9997, page)[1])
ocr_clues.read_words, ocr_clues.lines_of = real
emit("special-classes", sorted(G.SPECIAL_UNSOLVED), sorted(G.SPECIAL_UNSOLVED - G.GRID_MISFIT))
z = clues_only.read("genius-280")
if z:
    emit("held-280", z.get("cluesUnplaced"), len(z["clues"]["unplaced"]), z["preamble"].startswith("Clues are listed"))

check('article text carries no tag remnant',
      get('text-no-markup'), 'True')
check('an empty standfirst is no preamble',
      get('empty-standfirst-no-preamble'), 'None')
check('the reader keeps both counts on the clue',
      get('pair-read'), 'Leaves disappear (4,3) (7) | 7')
check('competition small print and grid notes are cut',
      get('small-print-cut'), 'In 11 clues the wordplay produces a letter.')
check("headings printed together: first run is the first heading's",
      get('headings-together'), "[(1, 'a'), (5, 'a'), (1, 'd'), (2, 'd')]")
check('an unheaded run after Down is Across; See preamble is a stub',
      get('unheaded-run'), "[(1, 'd', 'Work for two (3,5)'), (3, 'd', 'See preamble'), (4, 'd', 'Open land (4)'), (1, 'a', 'See preamble'), (6, 'a', 'With money (3,2,1,4)')]")
check('an echo of one total is still cut by default',
      get('split-echo'), "('Set meal', '5,5')")
check('a paired split keeps the first count',
      get('split-paired'), "('Leaves disappear (4,3)', '7')")
check('echoed: same totals only',
      get('echoed'), 'True False False')
check('clue() carries pairedCount',
      get('clue-paired'), "{'text': 'Leaves disappear (4,3)', 'enumeration': '7', 'pairedCount': True}")
check('the gate passes a paired count, refuses an unflagged one',
      get('unsplit-paired'), 'False True')
check('printed() shows both counts',
      get('printed-paired'), 'Leaves disappear (4,3) (7)')
check('a tag remnant is markup',
      get('markup0'), 'True')
check('a bare dcr- class is markup',
      get('markup1'), 'True')
check('a tag is markup',
      get('markup2'), 'True')
check('a count is not markup',
      get('markup3'), 'False')
check('the word class is not markup',
      get('markup4'), 'False')
check('no filed Genius carries markup',
      get('corpus-genius-clean'), '[]')
check("an article's standalone letter stays a word (genius-8)",
      get('letter-apart'), "['T with a long T wasting nothing in 12, T: the key (4,10)', 'T going west in form of lottery (7,3)', 'An extended T on hill (4)']")
check('a PDF ligature is its letters (205)',
      get('ligatures'), 'stuff to scoff, fine')
check('no filed Genius glues a letter onto a word',
      get('corpus-no-glued-letter'), '[]')
check('a PDF capital kerned off its word rejoins unless it stands before a word (162, 182)',
      get('kern-rejoin'), 'Tearful T going This Turpin X and')
check('genius-135 1-across prints (4,3) (7)',
      get('genius-135-1a'), 'After onset of winter, ordinary leaves disappear (4,3) (7) True')
check('a list printed without counts is cut at its clue numbers (233)',
      get('countless'), "[(8, 'Bit of theatre role almost went wrong'), (9, 'Outlines injuries, losing time'), (10, 'Amount of drink'), (11, 'Article about dancing in the Guardian?'), (12, 'Retreats in France from Poles'), (1, 'Upshot mostly (6)')]")
check('the prose after a countless list stays the preamble',
      get('countless-preamble'), 'All down clues and solutions are normal. All across ones are shifted.')
check('a number that lost its leading 1 is mended (161)',
      get('lost-leading-1'), "[(1, 'across'), (7, 'down'), (8, 'down'), (12, 'down'), (13, 'down')]")
check('a stray copy of a later clue is dropped (162)',
      get('stray-copy'), '[5, 7, 19, 20]')
check('two clues headed by one number both read (209)',
      get('two-22s'), "[[(20, 'across')], [(22, 'across'), (17, 'across'), (3, 'across')], [(22, 'across'), (2, 'across'), (5, 'across')], [(23, 'across')]]")
check('See special instructions with no count is a stub; with one, a clue (112, 92)',
      get('stub-uncounted'), "[(1, 'See special instructions'), (10, 'Make out (9)'), (26, 'See special instructions (8)'), (2, 'One (7)')]")
check('See 12 across joins 12 across, not 12 down (162)',
      get('see-way'), "[(12, 'across'), (2, 'down')] [(12, 'down')]")
check('a See stub another heading already links joins no second leader (22, 16, 58)',
      get('see-taken'), "[[(1, 'across'), (13, 'across')], [(1, 'down')], [(2, 'down')]]")
check('an unheaded See N joins the only N leading (60)',
      get('see-own'), "[[(9, 'across')], [(8, 'down'), (5, 'across')]]")
check('a * count (a withheld word) ends a clue (17)',
      get('star-count'), "[(22, '*,6'), (24, '10'), (14, '5,4')]")
check('MISPRINTED names the misprinted counts the filer lets through (60)',
      get('misprinted-60'), "[(8, 'down'), (20, 'down')] []")
check('unnumbered clues in the preamble are counted; numbered ones are not (76, 157)',
      get('unnumbered'), '5 0')
check('a heading behind Clues, a header without No, and World Cup winners: preamble (165)',
      get('preamble-165'), 'Eight solutions comprise the theme, supporter and World Cup winners.')
check("a run under no known heading is the other way's clues (157)",
      get('stranded-run'), "[(1, 'd'), (2, 'd'), (3, 'd'), (8, 'a'), (9, 'a'), (10, 'a')]")
check('stranded clues, spaced byline and grid numbers leave only the preamble (157)',
      get('stranded-preamble'), 'Half the solutions are entered in a 10 across manner.')
check("a post opening 'X is a setter' names the setter; none otherwise (103, 84)",
      get('body-setter'), 'Lavatch None')
check('a stretched grid is squared before it is read (157)',
      get('unstretched'), '17.6')
if get('filed-76'):
    check('genius-76 files as a jigsaw: its unnumbered clues placed, the instruction its preamble',
          get('filed-76'), "True Solutions to the remaining clues have their indicated place at the table Carnivore's fur first")
if get('filed-250'):
    check('genius-250: jigsaw, twelve answers entered with a pair inserted, printed counts kept, instructions after the list kept',
          get('filed-250'), 'True 12 HANDLE HALE 4 True')
check("a jigsaw clue's answer and entry come off the post row printing it (250)",
      get('placed-words'), "['CAUTION', 'CAUSATION']")
if get('filed-233'):
    check('genius-233 files unsolved with no post, its 14 across clues printed without counts',
          get('filed-233'), 'unsolved 14 14')
if get('filed-112'):
    check("genius-112's quotation lights file unclued, their letters the post's quotation (article marks, no preamble)",
          get('filed-112'), '28 5')
if get('filed-108'):
    check("genius-108's six marked lights file unclued off the article page",
          get('filed-108'), '30 6')
if get('setter-84'):
    check('genius-84 files with no setter (series.py unbylined)',
          get('setter-84'), 'None')
if get('unsolved-nosetter'):
    check('an early Genius with no post and no setter named files unsolved with no setter (7)',
          get('unsolved-nosetter'), 'unsolved None')
check('a numbered list no grid takes is held clues-only, by direction',
      get('hold-clues'), 'True True')
check('a held numbered Genius has a builder (queued for the solve)',
      get('numbered-builder'), 'True')
check("only a grid matching its clues falls back to unsolved when the post's answers fail",
      get('fallback-classes'), '[] False')
if get('filed-44'):
    check("genius-44, whose post prints answers the reader misses, never takes the post's answers",
          get('filed-44'), 'True')
if get('filed-165'):
    check('genius-165 files its eight See-preamble lights unclued',
          get('filed-165'), '32 8')
check('an unnumbered list reads clue by clue, the instruction between two clues cut out (280)',
      get('unplaced-clues'), "[('A board devoid of soft fruit (4)', '4'), ('Hard back (5)', '5'), ('Workforce keeping mum (3-4)', '3-4'), ('Run dry (4)', '4')]")
check('the instruction among the unnumbered clues is the preamble (280)',
      get('unplaced-preamble'), 'Clues are listed in alphabetical order of their answers, to be entered jigsaw-fashion where they will fit.')
check("a Genius jigsaw's answers take the printed grid's lights, numbered there",
      get('jigsaw-placed'), "[] [('1-across', (0, 'ABCD')), ('1-down', (2, 'AEH')), ('2-down', (3, 'CFJ')), ('3-down', (4, 'DGK')), ('4-across', (5, 'FG')), ('5-across', (1, 'HIJK'))] True")
check('an answer taking no light of the printed grid is an offGrid clue',
      get('jigsaw-off-grid'), "[] [{'clue': {'text': 'Below the grid', 'enumeration': '3'}}] (6, 'XYZ')")
check("an off-grid answer whose length is not its clue's count is refused",
      get('jigsaw-off-grid-count'), '["1 answers that take no light of the printed grid do not match their clue\'s count: XY (3)"]')
check('an off-grid answer crosses nothing: only its count is checked',
      get('off-grid-fill'), '[] [] ["1-offgrid: \'XY\' is 2 letters, its clue counts 3"]')
check('the write gate passes an off-grid answer its count long, refuses another',
      get('off-grid-gate'), "['1-offgrid: solution XYZW is 4 letters, its enumeration (3) counts 3']")
check('an off-grid clue counts toward solved and annotated',
      get('off-grid-done'), 'True 1-offgrid')
check('an off-grid annotation is validated, its findings named by its id',
      get('off-grid-validate'), '["1-offgrid: definition \'Below\' is not at 3 in \'Below the grid\'"]')
check('a held Genius jigsaw has a builder (queued); 280 is out of SCHEMA_GAP',
      get('jigsaw-builder'), 'True False')
check('an unclued light the preamble declares files with a blank clue, unsolved',
      get('special-unclued'), "None [{'missing': True}] unsolved")
check('an unclued light nobody declares is a misread',
      get('special-undeclared'), '1 lights unclued, and the preamble says none is')
check('a light the clue list marks See preamble files unclued',
      get('special-marked'), 'None')
check('a listed light the grid lacks is refused',
      get('special-extra'), 'lights and clue list differ')
check('an unclued light whose clue ran into the preamble is a misread (265)',
      get('special-clue-in-preamble'), "5 across's clue is in the preamble: the clue list is misread")
check('a count the preamble alters keeps the printed count, the light its length',
      get('special-loose'), 'None 7 5 False')
check('a count off its light with no preamble printed is refused',
      get('special-loose-no-preamble'), 'the clue list does not cover the grid, and no preamble printed says why')
check("an article page's altered count files awaiting its preamble",
      get('special-loose-article'), 'None True')
check('a light printed with only its count files a blank clue keeping it (235, 63)',
      get('count-only-blank'), "None [{'missing': True, 'enumeration': '5'}]")
check('a list of bare counts is no set of unclued lights (144)',
      get('count-only-many'), "('6 clues print only a count', 'unsolved')")
check('bulleted clues read in order, the run-on instruction cut out (240)',
      get('bulleted'), "[('Keeps elastic pants worn by date', None), ('Most vulgar fan of Labour PM uncovered stealing French art', None), ('Yellow colour? It might be this', None)] | All clues are normal and all solutions are single words. However, the solutions are in no particular order.")
check('two OCR readers alike up to spaces, dashes and quotes file the fuller reading (150)',
      get('ocr-agree'), 'None [\'Lives in abandon (6)\', "Spooner\'s fighting \'usky? (8)", \'Pip — hung (6)\']')
check('a word the OCR readers read differently files nothing',
      get('ocr-disagree'), "7 across read two ways: 'Lives in abandon (6)' 'Lives in abanden (6)'")
check('the special classes are grid misfits the clues-only hold catches if refused',
      get('special-classes'), '["enumeration is not the entry\'s length", \'lights left unclued\'] []')
if get('held-280'):
    check('genius-280 is held clues-only: 39 unnumbered clues and its instruction',
          get('held-280'), 'True 39 True')

# image_paths asks the genius-files manifest for a Genius's pictures, never a
# glob of the media disk: nothing is on "disk" here but the manifest.
with tempfile.TemporaryDirectory() as gt:
    manifest = Path(gt) / "dl" / ".manifest"
    manifest.mkdir(parents=True)
    (manifest / "genius-files.jsonl").write_text(
        '{"key": "image/5-1", "at": 1}\n{"key": "image/5-0", "at": 1}\n'
        '{"key": "image/50-0", "at": 1}\n{"key": "pdf/5", "at": 1}\n')
    paths = subprocess.run(
        [sys.executable, "-c",
         "import genius_puzzles as G\nprint(' '.join(p.name for p in G.image_paths(5)))"],
        cwd=REPO / "tools", env={**os.environ, "CT_DOWNLOADS": str(Path(gt) / "dl")},
        capture_output=True, text=True).stdout.strip()
check("image_paths: off the genius-files manifest", paths, "5-0.img 5-1.img")

# A count that withholds its breaks closes a clue: Genius 236's "(11*)" (its
# preamble asterisks multi-word and hyphenated counts), 204's "(6, two
# words)" and "(8, hyphenated)". The grammar once missed them, so each such
# clue swallowed the next and both were held clues-only with merged clues.
text = ("Across 1 Rolled windbreak to cross cricket ground (11*) 6 Person sustaining equality (6) "
        "10 Sabre-rattling Asian beast (6, two words) 12 Devolved assembly required (8, hyphenated) "
        "14 Plain clue (5) Down 1 Vehicle taken into ramshackle restroom (12*) 2 Top (3)")
check("a count withholding its breaks closes its clue, the total its enumeration (236, 204)",
      "|".join(f"{c['lights'][0][0]}{c['lights'][0][1][0]}:{c['enumeration']}:{c['clue'][-6:]}"
               for c in G.parse_text(text)["clues"]),
      "1a:11: (11*)|6a:6:ty (6)|10a:6:words)|12a:8:nated)|14a:5:ue (5)|1d:12: (12*)|2d:3:op (3)")
check("enumeration.worded reads (11*), (6, two words), (8, hyphenated)",
      " ".join(str(x) for x in (E.worded("x (11*)"), E.worded("x (6, two words)"),
                               E.worded("x (8, hyphenated)"), E.worded("x (11)"))),
      "(11, None) (6, 2) (8, '-') None")
check("the answer's breaks replace a withheld split only when they fit it",
      " | ".join((F.worded("Beast (6, two words)", "3,3"), F.worded("Beast (6, two words)", "2,2,2"),
                 F.worded("Assembly (8, hyphenated)", "4-4"), F.worded("Assembly (8, hyphenated)", "4,4"),
                 F.worded("Ground (11*)", "5-2,4"), F.worded("Ground (11*)", "11"))),
      "Beast (3,3) | Beast (6, two words) | Assembly (4-4) | Assembly (8, hyphenated) | Ground (5-2,4) | Ground (11*)")

# Genius 238: a last "See 7" with the instructions after it and then the Down
# heading ran on to the first down clue's count, so 26 across swallowed the
# preamble and 1 down was lost; the grid then refused the clue list.
text = ("Across 7,26 Deliveries stopped (8,8) 9 Old illustrator (6) 26 See 7 Each of the four linked "
        "clues contains two definitions. Deadline for entries is 23:59. Down 1 Zip almost catching (6) "
        "2 Pull up on weight (6)")
got = G.parse_text(text)
check("a last See stub stops at the instructions after it (238)",
      "|".join(f"{c['lights'][0][0]}{c['lights'][0][1][0]}:{c['clue'][:7]}" for c in got["clues"]),
      "7a:Deliver|9a:Old ill|26a:See 7|1d:Zip alm|2d:Pull up")
check("...and the instructions are the preamble", (got["preamble"] or "")[:22], "Each of the four linke")

# Genius 265: a redacted clue prints "25 26 (4) group of ..." for "25 [] (4)" and
# "26 [] group of ...": 25 is a count-only light and 26 has its own clue.
got = G.parse_text("Across 22 Encounter resistance (9, 2 words) 25 26 (4) group of stunted mice (10) "
                   "27 Disinfectant (5) Down 1 A clue (6)")
check("a redacted clue's count goes back after its own head (265)",
      "|".join(f"{c['lights'][0][0]}{c['lights'][0][1][0]}:{c['enumeration']}:{c['clue'][:6]}"
               for c in got["clues"]),
      "22a:9, 2 words:Encoun|25a:4:(4)|26a:10:group |27a:5:Disinf|1d:6:A clue")
check("a head followed by an ordinary clue is left alone",
      G.unredacted("5 6 (4) Upper case (3)"), "5 6 (4) Upper case (3)")

# Genius 173: "(6;8)" on a clue for two lights of 6 and 8 cells is one answer
# per light, counted "6,8" as any linked clue; elsewhere "(a;b)" keeps b.
clues = [{"lights": [(8, "across"), (9, "across")], "clue": "Two answers (6;8)", "enumeration": "8"},
         {"lights": [(1, "across"), (2, "across")], "clue": "Altered (4;7)", "enumeration": "7"}]
G.paired_counts(clues, {(8, "across"): range(6), (9, "across"): range(8),
                        (1, "across"): range(5), (2, "across"): range(7)})
check("a two-light pair of counts equal to the lights' lengths is a linked count (173)",
      [c["enumeration"] for c in clues], ["6,8", "7"])

# Genius 46 and 200: "3,18 (See special instructions)" is dropped as unclued,
# so 18 down's "See 3" stands with no leader; its light is unclued too.
pdf = {"grid": ["...", "#.#", "..."], "preamble": None, "article": True,
       "marked": {(2, "down"), (3, "across")},
       "clues": [{"lights": [(1, "across")], "clue": "A (3)", "enumeration": "3"},
                 {"lights": [(3, "across")], "clue": "See 2", "enumeration": None}]}
check("a See stub whose leader was marked unclued is unclued (46, 200)",
      G.unclued_lights(pdf)[0], [(2, "down"), (3, "across")])

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all passed")
