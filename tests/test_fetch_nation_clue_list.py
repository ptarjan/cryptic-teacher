#!/usr/bin/env python3
# Does fetch_nation read a Nation clue list whole, through the sidebars and
# typesetting slips the site drops into it?
#
#     python3 tests/test_fetch_nation_clue_list.py
#
# 35 Nation puzzles were refused before their cold solve as "its across lengths
# are not symmetric" (clues_only.implausible), and the grids were never at
# fault: the "Current Issue" <aside> after 12-across (3502-3528), the
# "Puzzled?" note (3529) and a "Popular" carousel <section> (3418, 3450) ended
# the list early, as did "14Argued" set flush (3280), an escaped
# "strong&gt;27" (3494), a lone dash (3493), and "1 and 14D" / "See 7A"
# (3510, 3482). Synthetic markup in the pages' own shapes: no held page is read.
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
_real_stdout, sys.stdout = sys.stdout, io.StringIO()

import fetch_nation as F
page = """<article><p><strong>ACROSS</strong>
<p><strong> 1</strong> and 14D Noticed a tool melting (4,6)
<p style="padding-left: 181px;">&#8211;
<p><strong> 4</strong> Put in other words (9)
<p><strong>10</strong> Our dean mangled a poem (7)\t\t<aside class="left current-issue">
<h4>Current Issue</h4><div><a href="#">View our current issue</a></div></aside>
<p><strong>11</strong> Article in the paper (7)
<p>strong&gt;12 Cheerful lad steals uranium (5)
<p><strong>13</strong> See 1A
<p><strong>DOWN</strong>
<p><strong> 2</strong> Believer behind universal connection (5)
<section id="popular-" class="popular-articles"><div><h2>Popular</h2><ol>
<li><h3>The Myths of Anne Carson</h3></li></ol></div></section>
<p><strong>3</strong>Argued page was in front (4)
<p><strong>14</strong> See 1
<p><strong>15</strong> Retreated (4)
<p>SOLUTION TO PUZZLE NO. 3504
</article>"""
lists, _ = F.clue_lists(F.lines_of(page))
for d in ("across", "down"):
    print(d.upper(), " ".join(f"{r['number']}:{r['enumeration']}" for r in lists[d]))
print("SEE", lists["across"][-1]["clue"])
print("TEXT", lists["across"][4]["clue"])
print("BARE", lists["down"][2]["clue"])
# 3520: a hidden paragraph counter flush after every line; 3466: a linked
# leader whose clue is "See 12" but which prints the group's enumeration.
page = """<article><p><strong>ACROSS</strong><span class="paranum hidden">2</span>
<p><strong>8</strong>, 14A and 26 See 12 (2,8,2,8,4,7,4,4,2-4)<span class="paranum hidden">3</span>
<p><strong>12</strong> Tehran lunatic forms an organization (3,3)<span class="paranum hidden">4</span>
<p><strong>14</strong> See 8<span class="paranum hidden">5</span>
<p><strong>26</strong> See 8<span class="paranum hidden">6</span>
<p><strong>DOWN</strong><span class="paranum hidden">7</span>
<p><strong>1</strong> East Coast university (6)<span class="paranum hidden">8</span>
</article>"""
lists, _ = F.clue_lists(F.lines_of(page))
for d in ("across", "down"):
    print("P" + d.upper(), " ".join(f"{r['number']}:{r['enumeration']}" for r in lists[d]))
import light_spec
across, down, _, _ = light_spec.build_spec(lists)
print("LEADER", across[0][0], across[0][2])
# 3507's serial comma and 3325's "&amp; ;": each lost its link, so the group's
# whole count went on one light (24 cells, 8 cells) and no grid was found.
page = """<article><p><strong>ACROSS</strong>
<p><strong>&ensp;1</strong> &amp; ; <strong>30&ensp;</strong>Play double Dutch with a pole? (4,4)
<p><strong>15</strong>, 18, 5D, and 21D Weak theater delivery person (6,6,6,4,2)
<p><strong>18</strong> See 15
<p><strong>30</strong> See 1
<p><strong>DOWN</strong>
<p><strong>5</strong> See 15
<p><strong>21</strong> See 15
</article>"""
lists, _ = F.clue_lists(F.lines_of(page))
print("LINKS", " ".join(f"{r['number']}:{r['enumeration']}" for r in lists["across"][:2]))
# A symmetric grid's i-th across light mirrors the i-th from the end (3499's
# "1 and 4 across (5,8)", 3325's "1 & 30 (4,4)", 3418's "11 and 31 (7,10)").
across = [[1, None], [4, None], [9, 9], [11, 7], [20, 9], [28, 8], [29, 5]]
down = [[1, 6], [2, None], [3, None]]
left = F.mirror_lengths(across, down, [([("across", 0), ("across", 1)], 13),
                                       ([("down", 1), ("down", 2)], 10)])
print("MIRROR", " ".join(str(lg[1]) for lg in across), left)
across = [[1, None], [5, 7], [8, 7], [30, None]]
F.mirror_lengths(across, [], [([("across", 0), ("across", 3)], 8)])
print("HALVES", across[0][1], across[3][1])
# 3466: a leader whose clue is "See 4" leads; build must not follow it to 4.
page = """<html><head><meta property="og:title" content="Puzzle No. 3466" />
<meta property="article:published_time" content="2018-05-01T00:00:00" /></head><body>
<article><p>This article appears in the May 21, 2018 issue.</p>
<p><strong>ACROSS</strong>
<p><strong>1</strong> and 5 See 4 (5,5)
<p><strong>4</strong> Organization whose slogan is spoofed at 1 and 5 (5)
<p><strong>5</strong> See 1
<p><strong>DOWN</strong>
<p><strong>1</strong> First down (5)
<p><strong>2</strong> Second down (5)
<p><strong>3</strong> Third down (5)
</article></body></html>"""
grid = [".....", ".#.#.", ".....", ".#.#.", "....."]
puzzle, why = F.build(page, "https://example.org/puzzle-no-3466/", {}, grid=grid)
lead = next(e for e in puzzle["entries"] if e["number"] == 1 and e["direction"] == "across") if puzzle else {}
print("SEELEAD", why, lead.get("group"), (lead.get("clue") or {}).get("text"))
# Crossword Classic 14 (1948): "(8) (hyphenated)" still prints the count.
page = """<article><p>ACROSS
<p>27 The sword, or the man who wields it. (8) (hyphenated)
<p>28 Loudest when last. (6)
<p>DOWN
<p>19 It has wings. (7) (hyphenated)
</article>"""
lists, _ = F.clue_lists(F.lines_of(page))
print("HYPH", " ".join(f"{r['number']}:{r['enumeration']}" for r in lists["across"] + lists["down"]),
      "|", lists["across"][0]["clue"])
# 1614: "26 and 27 See 6 across" closes on its pointer (not swallowing the
# note below the list) and is two continuations, one row each.
page = """<article><p>ACROSS
<p>6, 25, 26 and 27 Mother's aboard (5,3,5,4)
<p>25 See 6 across
<p>DOWN
<p>22 See 1 down
<p>26 and 27 See 6 across
<p>Frank W. Lewis, who for more than six decades wrote the puzzle, died on Nov. 18.
</article>"""
lists, _ = F.clue_lists(F.lines_of(page))
print("SEEPAIR", " | ".join(f"{r['number']}:{r['clue']}" for r in lists["down"]))
# 1614: "6 See 15 (6)" is a continuation printing a stray count, not a
# leader; masked as one, the group was short and build refused it.
page = """<html><head><meta property="og:title" content="Puzzle No. 3467" />
<meta property="article:published_time" content="2018-05-01T00:00:00" /></head><body>
<article><p>This article appears in the May 28, 2018 issue.</p>
<p><strong>ACROSS</strong>
<p><strong>1</strong> and 2 down First and second (5,5)
<p><strong>4</strong> Middle across (5)
<p><strong>5</strong> Last across (5)
<p><strong>DOWN</strong>
<p><strong>1</strong> First down (5)
<p><strong>2</strong> See 1 across (4)
<p><strong>3</strong> Third down (5)
</article></body></html>"""
puzzle, why = F.build(page, "https://example.org/puzzle-no-3467/", {}, grid=grid)
lead = next(e for e in puzzle["entries"] if e["number"] == 1 and e["direction"] == "across") if puzzle else {}
print("STRAY", why, lead.get("group"))
# Classic 25: one pinned split fits capped; the others finish capped empty
# and are not searched uncapped (where they ran out of budget). A capped
# run-out still holds the grid back.
def stub(table):
    def unique_grid(spec, **kw):
        n = [l for num, d, l in spec if num == 2 and d == "down"][0]
        return table[(n, "max_black_run" in kw)]
    return unique_grid
real = F.rg.unique_grid
F.paired_lengths, real_pl = (lambda *a: [{("down", 0): 3, ("down", 1): 5}, {("down", 0): 4, ("down", 1): 4},
                                          {("down", 0): 5, ("down", 1): 3}]), F.paired_lengths
pa = [[1, 5], [4, 5]]
pd = [[2, None], [3, None]]
grp = [([("down", 0), ("down", 1)], 8)]
fit = (["G"], None)
none = (None, "the search found no grid")
out_ = (None, "the search ran out of budget")
F.rg.unique_grid = stub({(3, True): none, (3, False): out_, (4, True): fit, (5, True): none, (5, False): out_})
ok1 = F._search_paired(pa, pd, grp, 5, None, None)
F.rg.unique_grid = stub({(3, True): out_, (4, True): fit, (5, True): none, (5, False): out_})
ok2 = F._search_paired(pa, pd, grp, 5, None, None)
F.rg.unique_grid = stub({(3, True): none, (3, False): fit, (4, True): none, (4, False): none, (5, True): none, (5, False): none})
ok3 = F._search_paired(pa, pd, grp, 5, None, None)
F.rg.unique_grid = real
print("PAIRED", ok1, "|", ok2[1], "|", ok3)
F.paired_lengths = real_pl
# Crossword Classic #N print the grid as a timestamp-named upload; only they.
import nation_images as NI
up = '<img src="http://www.thenation.com/wp-content/uploads/2015/03/1225388684-large2.jpg">'
classic = '<meta property="og:title" content="Crossword Classic #24" />' + up
other = '<meta property="og:title" content="Puzzle No. 3000" />' + up
print("CLASSICIMG", (NI.image_url(classic, "grid") or "").rsplit("/", 1)[-1], NI.image_url(other, "grid"))

out = sys.stdout.getvalue().splitlines()
sys.stdout = _real_stdout
fails = 0


def expect(want, what):
    global fails
    if want in out:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what} (want {want!r})")
        print("\n".join(out))
        fails += 1


expect("ACROSS 1,14:4,6 4:9 10:7 11:7 12:5 13:None", "an <aside>, a lone dash and an escaped tag do not end the across list")
expect("DOWN 2:5 3:4 14:None 15:4", "a Popular <section> and a number set flush do not end the down list")
expect("SEE See 1 across", "'See 1A' is a continuation and keeps its direction")
expect("BARE See 1", "a bare 'See 1' names no direction")
expect("TEXT Cheerful lad steals uranium", "the escaped tag leaves the clue's text clean")
expect("PACROSS 8,14,26:2,8,2,8,4,7,4,4,2-4 12:3,3 14:None 26:None", "a hidden paragraph counter does not hide the headings or the counts")
expect("PDOWN 1:6", "the counter does not glue onto the down list")
expect("LEADER 8 linked", "a linked 'See 12' printing the group's count is its leader, not a redirect")
expect("LINKS 1,30:4,4 15,18,5,21:6,6,6,4,2", "a serial comma and a stray '&amp; ;' keep a linked clue's numbers")
expect("MIRROR 5 8 9 7 9 8 5 [([('down', 1), ('down', 2)], 10)]", "a linked across light takes its mirror's length; an open down pair stays a group")
expect("HALVES 4 4", "two linked lights that mirror each other split their total")
expect("SEELEAD None ['1-across', '5-across'] See 4", "a leader whose clue is 'See 4' leads its group and keeps its clue")
expect("HYPH 27:8 28:6 19:7 | The sword, or the man who wields it. (hyphenated)", "a '(hyphenated)' note after the count keeps the count and stays with the clue")
expect("SEEPAIR 22:See 1 down | 26:See 6 across | 27:See 6 across", "'26 and 27 See 6 across' closes on its pointer and is one row per light")
expect("STRAY None ['1-across', '2-down']", "a continuation printing a stray count is not masked as a leader")
expect("PAIRED (['G'], None) | the search ran out of budget | (['G'], None)", "a split the capped search finishes empty is not re-searched uncapped once another fits; a capped run-out still holds; with no capped fit the uncapped pass runs")
expect("CLASSICIMG 1225388684-large2.jpg None", "a Crossword Classic page's timestamp-named upload is its grid picture; no other page's is")

if fails == 0:
    print("fetch_nation clue list: all checks passed")
else:
    print(f"fetch_nation clue list: {fails} FAILED")
sys.exit(1 if fails else 0)
