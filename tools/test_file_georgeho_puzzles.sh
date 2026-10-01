#!/bin/bash
# Does tools/file_georgeho_puzzles.py read georgeho's rows into the record the
# grid rebuild and file_blog_puzzles.build take?
#
#     bash tools/test_file_georgeho_puzzles.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import file_georgeho_puzzles as G
print("LIGHTS", G.lights_of("13/15a", "d"), G.lights_of("26,10", "d"), G.lights_of("Great", "a"))
print("COUNT", G.count_of("ROMAN WALL"), G.count_of("NON-FATAL"), G.count_of("SWAP"))
U = "http://bigdave44.com/2010/01/04/toughie-250/"
rows = [("toughie-250", U, "Toughie 250", "1a", "Hands over exchange here (4)", "SWAP"),
        ("toughie-250", U, "Toughie 250", "5", "A Roman barrier", "ROMAN WALL"),
        ("toughie-250", U, "Toughie 250", "2", "Wimps", "MILKSOPS"),
        ("toughie-250", U, "Toughie 250", "3/4", "Linked", "AT A LOSS"),
        ("toughie-250", U, "Toughie 250", "4", "See 3", "nan")]
rec, why = G.record("toughie-250", rows)
print("REC", why, rec["date"], rec["number"],
      [(e["number"], e["direction"], e["clue"], e["counted"]) for e in rec["entries"]])
print("LINKED", rec["unsplit"][0]["lights"], rec["unsplit"][0]["enumeration"])
# A title naming no setter takes the one bigdave44's posts on the puzzle
# name (a hints post too), else the fifteensquared post at its url's title.
import json, pathlib, tempfile
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "bd").mkdir(); (tmp / "fs").mkdir()
post = lambda pid, slug, title, body, link="": json.dumps({
    "id": pid, "slug": slug, "link": link, "date": "2022-02-14T00:00:00", "categories": [],
    "title": {"rendered": title}, "content": {"rendered": body}})
(tmp / "bd" / "1.json").write_text(post(1, "sunday-toughie-3", "Sunday Toughie 3 (Hints)",
                                        "<h2>Sunday Toughie No 3 by proXimal (Hints)</h2><p>Hints and Tips by Big Dave</p>"))
(tmp / "bd" / "2.json").write_text(post(2, "toughie-1031", "Toughie 1031",
                                        "<h2>Toughie No 1031 by Beam</h2>"))
(tmp / "bd" / "3.json").write_text(post(3, "toughie-1032", "Toughie 1032", "<h2>Toughie No 1032</h2>"))
(tmp / "fs" / "9.json").write_text(post(9, "", "Independent on Sunday 1150/Glow-worm", "",
                                        "https://fifteensquared.net/2012/03/11/independent-on-sunday-1150glow-worm/"))
wanted = [{"series": "sundaytough", "number": 3, "link": "http://bigdave44.com/2022/02/23/sunday-toughie-3-3/"},
          {"series": "toughie", "number": 1031, "link": "http://bigdave44.com/2013/08/14/toughie-1031/"},
          {"series": "toughie", "number": 1032, "link": "http://bigdave44.com/2013/08/15/toughie-1032/"},
          {"series": "indysunday", "number": 1150,
           "link": "https://www.fifteensquared.net/2012/03/11/independent-on-sunday-1150glow-worm/"}]
print("OTHER", sorted(G.other_setters(wanted, tmp / "bd", tmp / "fs").items()))
print("NODATE", G.record("x-1", [("x-1", "https://example.com/1.html", "X 1", "1a", "c", "A")])[1])
PY
)
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /,""); print}' <<<"$out"; }
check "a linked cell's suffix covers every number; a bare one takes the heading" \
      "[(13, 'across'), (15, 'across')] [(26, 'down'), (10, 'down')] None" "$(field LIGHTS)"
check "a count is read off the blogger's word breaks" "5,4 3-5 4" "$(field COUNT)"
check "the post date is the url's; numbers that start again are the downs; a missing count is marked" \
      "None 2010-01-04 250 [(1, 'across', 'Hands over exchange here (4)', False), (5, 'across', 'A Roman barrier (5,4)', True), (2, 'down', 'Wimps (8)', True)]" \
      "$(field REC)"
check "a linked answer is left for the grid to split" "[[3, 'down'], [4, 'down']] 2,1,4" "$(field LINKED)"
check "a setter the title omits comes from bigdave44's posts or fifteensquared's, else none" \
  "[(('indysunday', 1150), 'Glow-worm'), (('sundaytough', 3), 'proXimal'), (('toughie', 1031), 'Beam')]" "$(field OTHER)"
check "a post with no date is not a record" "no post date" "$(field NODATE)"
if [ "$fails" -gt 0 ]; then echo "$fails FAILURE(S)"; exit 1; fi
echo "file_georgeho_puzzles: all checks passed"
