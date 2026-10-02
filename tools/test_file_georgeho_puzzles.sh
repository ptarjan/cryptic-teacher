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
# georgeho cuts an answer off at its first break (TAM for TAM-O'-SHANTER);
# our parse of the same post has it whole and wins. A whole answer stays
# georgeho's, and so does a blog answer that does not start with its letters.
J = "https://times-xwd-times.livejournal.com/2243874.html"
cut = [("timesjumbo-1409", J, "Times Cryptic Jumbo 1409", "6d", "Scotch bonnet (3-1-7)", "TAM"),
       ("timesjumbo-1409", J, "Times Cryptic Jumbo 1409", "7d", "Distance (3-8)", "FAR"),
       ("timesjumbo-1409", J, "Times Cryptic Jumbo 1409", "8d", "Scot (9)", "DUNDONIAN")]
blog = {(6, "down"): "TAM-O-SHANTER", (7, "down"): "OFFREACHING", (8, "down"): "DUNDONIANS"}
rec, _ = G.record("timesjumbo-1409", cut, {J: "2019-11-22"}, blog)
print("WHOLE", [e["answer"] for e in rec["entries"]])
# The Times Jumbo prints on Saturdays, and on a bank holiday besides: one
# Monday and one Thursday among the neighbours leave the Saturdays the slots
# (timesjumbo-1304 is 13 January 2018, as the blog's title says).
import datetime, types
held_dates = {1300: "2017-12-26", 1302: "2018-01-01", 1305: "2018-01-20",
              1306: "2018-01-27", 1307: "2018-02-03", 1309: "2018-02-17",
              1297: "2017-12-09", 1299: "2017-12-23", 1310: "2018-02-24"}
G.puzzle_path = lambda s, n: n
G.read_puzzle_file = lambda p: {"date": held_dates.get(p)}
G.puzzle_paths = types.SimpleNamespace(find=lambda pid: int(pid.rsplit("-", 1)[1])
                                       if int(pid.rsplit("-", 1)[1]) in held_dates else None)
print("HOLIDAY", G.print_date({"series": "timesjumbo", "number": 1304}, 1302, 1305))
# Two bank-holiday Mondays among the neighbours' neighbours are still holidays
# (timesjumbo-1334, between 1332 on 7 July 2018 and 1335 on 28 July).
held_dates.clear()
held_dates.update({1325: "2018-05-26", 1326: "2018-05-28", 1327: "2018-06-02",
                   1329: "2018-06-16", 1330: "2018-06-23", 1331: "2018-06-30",
                   1332: "2018-07-07", 1335: "2018-07-28", 1336: "2018-08-04",
                   1337: "2018-08-11", 1339: "2018-08-25", 1340: "2018-08-27",
                   1341: "2018-09-01", 1342: "2018-09-08"})
print("HOLIDAYS", G.print_date({"series": "timesjumbo", "number": 1334}, 1332, 1335))
# georgeho dates times-xwd-times post 2484454 (Jumbo 1479, printed 16 January
# 2021) 2021-01-02, before the print date; the posts either side of it in
# LiveJournal's id order are 2021-02-04, so the one before it dates it. A daily
# blogged the evening before keeps its date, a url's date is the post's own,
# and a post whose predecessor is too early as well is not filed.
L = "https://times-xwd-times.livejournal.com/%d.html"
prev = G.previous_posts({L % 2484165: "2021-02-04", L % 2484454: "2021-01-02",
                         L % 2484524: "2021-02-04", "https://example.com/x": "2021-01-01"})
P16 = datetime.date(2021, 1, 16)
print("WRITEUP", prev.get(L % 2484454),
      G.write_up_date({"date": "2021-01-02", "link": L % 2484454, "previous": prev[L % 2484454]}, P16),
      G.write_up_date({"date": "2021-01-15", "link": L % 1}, P16),
      G.write_up_date({"date": "2021-01-02", "link": L % 1, "previous": "2021-01-03"}, P16),
      G.write_up_date({"date": "2021-01-02", "link": "https://www.fifteensquared.net/2021/01/02/x/"}, P16))
print("NODATE",G.record("x-1", [("x-1", "https://example.com/1.html", "X 1", "1a", "c", "A")])[1])
PY
)
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /,""); print}' <<<"$out"; }
check "a bank holiday's Jumbo does not make its weekday the series'" \
      "2018-01-13" "$(field HOLIDAY)"
check "two bank holidays' Jumbos do not make their weekday the series'" \
      "2018-07-21" "$(field HOLIDAYS)"
check "an answer georgeho cut off is taken whole from our parse of the same post" \
      "['TAMOSHANTER', 'FAR', 'DUNDONIAN']" "$(field WHOLE)"
check "a linked cell's suffix covers every number; a bare one takes the heading" \
      "[(13, 'across'), (15, 'across')] [(26, 'down'), (10, 'down')] None" "$(field LIGHTS)"
check "a count is read off the blogger's word breaks" "5,4 3-5 4" "$(field COUNT)"
check "the post date is the url's; numbers that start again are the downs; a missing count is marked" \
      "None 2010-01-04 250 [(1, 'across', 'Hands over exchange here (4)', False), (5, 'across', 'A Roman barrier (5,4)', True), (2, 'down', 'Wimps (8)', True)]" \
      "$(field REC)"
check "a linked answer is left for the grid to split" "[[3, 'down'], [4, 'down']] 2,1,4" "$(field LINKED)"
check "a setter the title omits comes from bigdave44's posts or fifteensquared's, else none" \
  "[(('indysunday', 1150), 'Glow-worm'), (('sundaytough', 3), 'proXimal'), (('toughie', 1031), 'Beam')]" "$(field OTHER)"
check "a write-up georgeho dates before the print takes the previous post's date, else is not filed" \
      "2021-02-04 2021-02-04 2021-01-15 None 2021-01-02" "$(field WRITEUP)"
check "a post with no date is not a record" "no post date" "$(field NODATE)"
if [ "$fails" -gt 0 ]; then echo "$fails FAILURE(S)"; exit 1; fi
echo "file_georgeho_puzzles: all checks passed"
