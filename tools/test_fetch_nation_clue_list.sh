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
PY
)
fails=0
expect() { grep -qxF "$1" <<<"$out" && echo "  ok: $2" || { echo "  FAIL: $2 (want '$1')"; echo "$out"; fails=$((fails+1)); }; }
expect "ACROSS 1,14:4,6 4:9 10:7 11:7 12:5 13:None" "an <aside>, a lone dash and an escaped tag do not end the across list"
expect "DOWN 2:5 3:4 14:None 15:4" "a Popular <section> and a number set flush do not end the down list"
expect "SEE See 1" "'See 1A' is a continuation"
expect "TEXT Cheerful lad steals uranium" "the escaped tag leaves the clue's text clean"
[ "$fails" = 0 ] && echo "fetch_nation clue list: all checks passed" || echo "fetch_nation clue list: $fails FAILED"
exit $((fails > 0))
