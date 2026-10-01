#!/bin/bash
# Does tools/ft_puzzles.py read every layout fifteensquared prints an FT post
# in, and share a linked answer out the way the grid has it?
#
#     bash tools/test_ft_puzzles.sh
#
# A misread answer is a wrong light length, and a wrong light length rebuilds
# a wrong grid or none. The fixtures are hand-written posts, one per layout,
# and a hand-built 5x5, so nothing here reads the blog cache or the corpus.
# The layouts without counts are rows cut from real fifteensquared posts.
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

# The table whose clue is only the answer's hover text, beside a "vote" link;
# the blogger's definition slash is no part of the clue.
print("TITLED", show("""
<table><tr><td colspan="4"><strong>Across</strong></td></tr>
<tr><td><span title="Shrink&#8217;s terms / of employment (8)"><strong>9</strong></span></td>
<td><strong>CONTRACT</strong></td><td><a href="http://x/cod.aspx?clueId=9+across">vote</a></td>
<td>Double definition</td></tr>
<tr><td><span title="Preserve postgrad qualification in wood (6)"><strong>10</strong></span></td>
<td><strong>EMBALM</strong></td><td><a href="http://x/cod.aspx?clueId=10+across">vote</a></td>
<td>MBA in ELM</td></tr></table>"""))

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

# Clues printed with no count, Independent 8934 / Dac: number, clue, then the
# answer and wordplay. The count is the one the answer spells.
print("NOCOUNT", show("""
<table><tbody><tr><td colspan="3"><strong>Across</strong></td></tr>
<tr><td>1</td><td><strong> </strong></td><td><span><em><span>Remember</span> everything taking place behind play area</em></span></td></tr>
<tr><td></td><td><strong>RECALL</strong></td><td><span>ALL</span> (everything) after <span>REC</span> (play area)</td></tr>
<tr><td>4</td><td><strong> </strong></td><td><span><em>Trawl netting most of favourite <span>type of fish</span></em></span></td></tr>
<tr><td></td><td><strong>SEA PERCH</strong></td><td><span>SEARCH</span> (trawl) around or ‘netting’ <span>PE</span><del>t</del> (favourite)</td></tr>
<tr><td>13</td><td><strong> </strong></td><td><span><em>Serviceman’s uniform</em></span></td></tr>
<tr><td></td><td><strong>REGULAR</strong></td><td>Double definition</td></tr>
</tbody></table>"""))

# Independent 7699 / Klingsor: the number opens the clue's own line.
print("NOCOUNT_INLINE", show("""
<p><strong>Across</strong></p>
<p>1  <span>TV comedy Addams Family&#8217;s final run?  Could be</span><br />
<strong>DAD&#8217;S ARMY</strong><br />
(ADDAMS Y R)*  The Y and the R are in the anagram fodder.</p>
<p>5  <span>Clubs reportedly want people who&#8217;ll give a hand for pay</span><br />
<strong>CLAQUE</strong><br />
Okay, I put in CLIQUE because nothing else seemed to fit.</p>"""))

# Independent 18,702 / Bluth: the answer first, the clue, then the wordplay.
# An answer with only its wordplay after it has no clue to take.
print("NOCOUNT_AFTER", show("""
<table><tbody><tr><td><strong>Across</strong></td><td></td><td></td></tr>
<tr><td><strong>01</strong></td><td><strong>ELBOW GREASE</strong></td><td>Sally Bowles missing start of stage musical – it’s<em> hard work</em></p>
<p>*(<strong>BOWLE</strong>&lt;s&gt;) + GREASE (=musical)</td></tr>
<tr><td><strong>07</strong></td><td><strong>DUE</strong></td><td>Short song <em>expected</em></p>
<p><strong>DUE</strong>&lt;t&gt; (=song); “short” means last letter is dropped</td></tr>
<tr><td><strong>09</strong></td><td><strong>LOCUM</strong></td><td>*(<strong>COLUM</strong>&lt;n&gt;)</td></tr>
</tbody></table>"""))

# Counts printed, answers not in capitals: Independent 8208 / Quixote prints
# "Facial", Independent 8231 / Nestor ends the wordplay "= PENDULUM".
print("BYCOUNT", show("""
<table><tr><td></td><td><b>Across</b></td></tr>
<tr><td valign="top">1.</td><td colspan="3"><font color="blue">Beauty treatment? Female having a cold one gets a line reduced (6)</font></td></tr>
<tr><td></td><td valign="top"><font color="red"><b>Facial</b></font></td><td></td><td valign="top">F(emale) = a c I + a l[ine]</td></tr>
<tr><td valign="top">12.</td><td colspan="3"><font color="blue">A learner just getting excited about the old man who was a philosopher? (4-4,6)</font></td></tr>
<tr><td></td><td valign="top"><font color="red"><b>Jean-Paul Sartre</b></font></td><td></td><td valign="top">(A learner just)* around pa</td></tr>
</table>
<p><strong>DOWN</strong></p>
<p>6 <span>Vacillator</span>&#8216;s choice about finishing university(8)</p>
<p>Plum (choice) about end (finishing) + u (university) = PENDULUM</p>"""))

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

# The Saturday prize is blogged on the Monday with Monday's puzzle, and a
# Wednesday blogged a day late on the Thursday with Thursday's.
recs = [{"number": n, "date": d} for n, d in ((100, "2026-09-14"), (101, "2026-09-15"),
        (102, "2026-09-16"), (103, "2026-09-17"), (104, "2026-09-18"),
        (105, "2026-09-21"), (106, "2026-09-21"), (107, "2026-09-22"),
        (108, "2026-09-24"), (109, "2026-09-24"))]
dates = F.print_dates(recs)
print("DATES", " ".join(f"{n}:{dates[n]:%a}" for n in sorted(dates)))
# Christmas Day's post pulls 248 back onto 247's day; neither is left undated.
dates = F.print_dates([{"number": n, "date": d} for n, d in (
    (246, "2025-12-22"), (247, "2025-12-23"), (248, "2025-12-24"),
    (249, "2025-12-25"), (250, "2025-12-26"))])
print("CLASH", " ".join(f"{n}:{dates[n]:%d}" for n in sorted(dates)))

# The FT reprints an old puzzle under a new number: the copy is skipped, named
# by the file already holding it, and a puzzle of its own still files.
import json, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
def built(number, clue):
    return {"id": f"ftcryptic-{number}", "number": number, "dimensions": {"cols": 5, "rows": 5},
            "entries": [{"number": 1, "direction": "across",
                         "position": {"x": 0, "y": 0}, "length": 5, "clue": {"text": clue}, "solution": "ABCDE"}]}
(tmp / "parsed.jsonl").write_text("".join(json.dumps({"post_id": n, "number": n, "date": "2026-09-01"}) + "\n"
                                          for n in (300, 301)))
(tmp / "grids.jsonl").write_text("".join(json.dumps({"post_id": n, "number": n, "date": "2026-09-01", "grid": []}) + "\n"
                                         for n in (300, 301)))
F.CACHE = tmp
F.ftp.sequence_window = lambda recs: (lambda date, number: True)
F.print_dates = lambda recs: {}
F.puzzle_path = lambda series, number: tmp / f"{series}-{number}.json"
F.ftp.build = lambda rec, row, series, day: (built(row["number"], "Old clue (5)" if row["number"] == 300 else "New clue (5)"), None)
F.held_by_content = lambda: {F.puzzle_integrity.content_hash(built(100, "Old clue (5)")): "ftcryptic-100"}
filed, skipped = F.file(write=False)
print("REPRINT", filed, sorted(k for k in skipped if k.startswith("reprint")))

# A file written before the parser tidied clues is tidied on the next run:
# the blogger's definition slash goes from the clue and from the annotation's
# quotation of it. A file another tool wrote is left alone.
held = {**built(300, "Withdraw / cash"), "source": {"acquiredBy": F.GENERATOR}}
held["entries"][0]["clue"]["enumeration"] = "5"
held["entries"][0]["annotation"] = {"definition": "Withdraw /"}
(tmp / "ftcryptic-300.json").write_text("{}")
written = {}
F.read_puzzle_file = lambda path: json.loads(json.dumps(held))
F.write_puzzle_file = lambda path, puzzle, **kw: written.update({path.name: puzzle})
F.held_by_content = lambda: {}
F.file(write=True)
e = written["ftcryptic-300.json"]["entries"][0]
print("RETEXT", e["clue"]["text"], "|", e["annotation"]["definition"])
held["source"]["acquiredBy"] = "tools/ft_pdf_puzzles.py"
written.clear()
F.file(write=True)
print("RETEXT_OTHER", "ftcryptic-300.json" in written)
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
check "clues with no count: the count from the answer, a verdict is no clue" \
  "1a=RECALL|Remember everything taking place behind play area (6); 4a=SEAPERCH|Trawl netting most of favourite type of fish (3,5); 13a=REGULAR|Serviceman’s uniform (7)" \
  "$(field NOCOUNT)"
check "clues with no count, opening on the number's own line" \
  "1a=DADSARMY|TV comedy Addams Family’s final run? Could be (4,4); 5a=CLAQUE|Clubs reportedly want people who’ll give a hand for pay (6)" \
  "$(field NOCOUNT_INLINE)"
check "clues with no count after the answer, wordplay alone is no clue" \
  "1a=ELBOWGREASE|Sally Bowles missing start of stage musical – it’s hard work (5,6); 7a=DUE|Short song expected (3); 9a=LOCUM|None" \
  "$(field NOCOUNT_AFTER)"
check "an answer not in capitals read off the clue's count" \
  "1a=FACIAL|Beauty treatment? Female having a cold one gets a line reduced (6); 12a=JEANPAULSARTRE|A learner just getting excited about the old man who was a philosopher? (4-4,6); 6d=PENDULUM|Vacillator‘s choice about finishing university(8)" \
  "$(field BYCOUNT)"
check "a clue held only in the answer's title is the clue, never the vote link; the slash goes" \
  "9a=CONTRACT|Shrink’s terms of employment (8); 10a=EMBALM|Preserve postgrad qualification in wood (6)" \
  "$(field TITLED)"
check "a held file of this tool's is tidied, its annotation's quotation with it" \
  "Withdraw cash | Withdraw" "$(field RETEXT)"
check "a held file another tool wrote is not tidied" "False" "$(field RETEXT_OTHER)"
check "number and setter off each title shape" \
  "[(18489, 'Xela'), (18480, 'Mudd'), (18484, 'Julius'), (16342, 'Rosa Klebb')]" "$(field TITLE)"
check "a linked answer shared out at the grid's light break" \
  "[(5, 'FGHIJ', 'Linked (2,3,5)'), (8, 'PQRST', 'See 5')] [(5, 'FGHIJ'), (8, 'PQRST')]" "$(field SPLIT)"
check "a puzzle blogged late dated to its own day: the prize to its Saturday" \
  "100:Mon 101:Tue 102:Wed 103:Thu 104:Fri 105:Sat 106:Mon 107:Tue 108:Wed 109:Thu" "$(field DATES)"
check "a run of numbers with no day of its own fitted between its neighbours" \
  "246:20 247:22 248:23 249:24 250:26" "$(field CLASH)"
check "an FT reprint under a new number skipped as the puzzle it repeats" \
  "['ftcryptic-301'] ['reprint of ftcryptic-100']" "$(field REPRINT)"

[ "$fails" -eq 0 ] && echo "all ok" || { echo "$fails failure(s)"; exit 1; }
