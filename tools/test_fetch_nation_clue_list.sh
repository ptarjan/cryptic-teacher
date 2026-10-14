#!/bin/bash
# Does fetch_nation read a Nation clue list whole, through the sidebars and
# typesetting slips the site drops into it?
#
#     bash tools/test_fetch_nation_clue_list.sh
#
# 35 Nation puzzles were refused before their cold solve as "its across lengths
# are not symmetric" (clues_only.implausible), and the grids were never at
# fault: the "Current Issue" <aside> after 12-across (3502-3528), the
# "Puzzled?" note (3529) and a "Popular" carousel <section> (3418, 3450) ended
# the list early, as did "14Argued" set flush (3280), an escaped
# "strong&gt;27" (3494), a lone dash (3493), and "1 and 14D" / "See 7A"
# (3510, 3482). Synthetic markup in the pages' own shapes: no held page is read.
set -uo pipefail
cd "$(dirname "$0")/.."
out=$(PYTHONPATH="$PWD/tools" python3 - <<'PY'
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
PY
)
fails=0
expect() { grep -qxF "$1" <<<"$out" && echo "  ok: $2" || { echo "  FAIL: $2 (want '$1')"; echo "$out"; fails=$((fails+1)); }; }
expect "ACROSS 1,14:4,6 4:9 10:7 11:7 12:5 13:None" "an <aside>, a lone dash and an escaped tag do not end the across list"
expect "DOWN 2:5 3:4 14:None 15:4" "a Popular <section> and a number set flush do not end the down list"
expect "SEE See 1 across" "'See 1A' is a continuation and keeps its direction"
expect "BARE See 1" "a bare 'See 1' names no direction"
expect "TEXT Cheerful lad steals uranium" "the escaped tag leaves the clue's text clean"
expect "PACROSS 8,14,26:2,8,2,8,4,7,4,4,2-4 12:3,3 14:None 26:None" "a hidden paragraph counter does not hide the headings or the counts"
expect "PDOWN 1:6" "the counter does not glue onto the down list"
expect "LEADER 8 linked" "a linked 'See 12' printing the group's count is its leader, not a redirect"
[ "$fails" = 0 ] && echo "fetch_nation clue list: all checks passed" || echo "fetch_nation clue list: $fails FAILED"
exit $((fails > 0))
