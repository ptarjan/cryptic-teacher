#!/bin/bash
# Does tools/ft_puzzles.py read every layout fifteensquared prints an FT post
# in, and share a linked answer out the way the grid has it?
#
#     bash tools/test_ft_puzzles.sh
#
# A misread answer is a wrong light length, and a wrong light length rebuilds
# a wrong grid or none. The fixtures are hand-written posts, one per layout,
# and a hand-built 5x5, so nothing here reads the blog cache or the corpus.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import ft_puzzles as F

def show(html):
    entries, unsplit = F.parse_entries(html)
    got = [f"{e['number']}{e['direction'][0]}={e['answer']}|{e['clue']}" for e in entries]
    return "; ".join(got + [f"unsplit {u['answer_printed']}" for u in unsplit])

# The table layout: number, answer, then the clue, a wordplay row under each.
# A clue can open with a number of its own ("16 9 church").
print("TABLE", show("""
<table><tr><td>ACROSS</td></tr>
<tr><td>1</td><td><span>STEAKHOUSE</span></td><td><div><span>Restaurant</span><span> takes off (10)</span></div></td></tr>
<tr><td colspan="2"></td><td>[ TAKES ]* HOUSE</td></tr>
<tr><td>6</td><td>CARP</td><td>Complain about (4)</td></tr>
<tr><td>DOWN</td></tr>
<tr><td>3/11/20</td><td>SECRET INTELLIGENCE SERVICE</td><td>16 9 church in Leicester (6,12,7)</td></tr>
<tr><td>5</td><td>MACK THE KNIFE</td><td>Old woman trained (4,3,5)</td></tr>
</table>"""))

# The list layout: "7. clue (n)", then the answer, then the wordplay.
print("LIST", show("""
<div class="fts-group">ACROSS</div>
<div><div><span>7. </span><span>She’s shown off wiles in Slam Era (6,8)</span></div>
<div>SERENA WILLIAMS</div><div><p>(WILES IN SLAM ERA)*</p></div></div>
<div><div><span>10. </span><span>When pub key’s on top of roof? (7)</span></div>
<div>ASPHALT</div><div><p>AS + PH + ALT</p></div></div>
<div class="fts-group">DOWN</div>
<div><div><span>1/9. </span><span>Nonpareil old city needs money (3,4,2,3,8)</span></div>
<div>THE BEST IN THE BUSINESS</div></div>"""))

# The older hand-made table: the number opens the clue's own cell.
print("OLD", show("""
<table><tr><td>ACROSS</td></tr>
<tr><td>1 Dismiss people in traditional event (4,4)</td><td> </td><td>SACK RACE</td><td> </td><td>SACK ( dismiss ) RACE</td></tr>
<tr><td>5 Booze cruises returning (6)</td><td> </td><td>SPIRIT</td><td> </td><td>TRIPS reversed</td></tr>
</table>"""))

print("TITLE", [(F.post_number(t), F.post_setter(t)) for t in (
    "Financial Times 18,489 by XELA", "Financial Times 18480 Mudd",
    "Financial Times 18,484 by Julius", "FT 16,342 / Rosa Klebb")])

# A linked answer the post prints whole: the grid's lights say where it breaks.
TINY = ("..#..",
        ".....",
        "#...#",
        ".....",
        "..#..")
lights = F.tg.rg.light_cells(TINY)
fill = {k: "".join(chr(65 + (y * 5 + x) % 26) for y, x in cs) for k, cs in lights.items()}
linked = [k for k in lights if len(lights[k]) == 5 and k[1] == "across"]
rec = {"entries": [{"number": n, "direction": d, "answer": a, "clue": "c (9)", "enumeration": None}
                   for (n, d), a in fill.items() if (n, d) not in linked],
       "unsplit": [{"lights": [list(k) for k in linked], "clue": "Linked (2,3,5)",
                    "enumeration": "2,3,5",
                    "answer_printed": f"{fill[linked[0]][:2]} {fill[linked[0]][2:]} {fill[linked[1]]}"}]}
split = F.split_by(rec, TINY)
print("SPLIT", [(e["number"], e["answer"], e["clue"]) for e in split["entries"]
                if (e["number"], e["direction"]) in linked],
      [(k[0], fill[k]) for k in linked])

# The Saturday prize is blogged on the Monday with Monday's puzzle.
recs = [{"number": n, "date": d} for n, d in ((100, "2026-09-14"), (101, "2026-09-15"),
        (102, "2026-09-16"), (103, "2026-09-17"), (104, "2026-09-18"),
        (105, "2026-09-21"), (106, "2026-09-21"), (107, "2026-09-22"))]
dates, _ = F.print_dates(recs)
print("DATES", " ".join(f"{n}:{dates[n]:%a}" for n in sorted(dates)))
PY
)
field() { printf '%s\n' "$out" | sed -n "s/^$1 //p"; }

check "the table layout, answer before clue, a clue opening with a number" \
  "1a=STEAKHOUSE|Restaurant takes off (10); 6a=CARP|Complain about (4); 3d=SECRET|16 9 church in Leicester (6,12,7); 11d=INTELLIGENCE|See 3; 20d=SERVICE|See 3; 5d=MACKTHEKNIFE|Old woman trained (4,3,5)" \
  "$(field TABLE)"
check "the list layout, and a linked answer with more words than lights left unsplit" \
  "7a=SERENAWILLIAMS|She’s shown off wiles in Slam Era (6,8); 10a=ASPHALT|When pub key’s on top of roof? (7); unsplit THE BEST IN THE BUSINESS" \
  "$(field LIST)"
check "the older table, number and clue in one cell" \
  "1a=SACKRACE|Dismiss people in traditional event (4,4); 5a=SPIRIT|Booze cruises returning (6)" \
  "$(field OLD)"
check "number and setter off each title shape" \
  "[(18489, 'Xela'), (18480, 'Mudd'), (18484, 'Julius'), (16342, 'Rosa Klebb')]" "$(field TITLE)"
check "a linked answer shared out at the grid's light break" \
  "[(5, 'FGHIJ', 'Linked (2,3,5)'), (8, 'PQRST', 'See 5')] [(5, 'FGHIJ'), (8, 'PQRST')]" "$(field SPLIT)"
check "the prize blogged on Monday dated to its Saturday" \
  "100:Mon 101:Tue 102:Wed 103:Thu 104:Fri 105:Sat 106:Mon 107:Tue" "$(field DATES)"

[ "$fails" -eq 0 ] && echo "all ok" || { echo "$fails failure(s)"; exit 1; }
