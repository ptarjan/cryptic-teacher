#!/bin/bash
# Does tools/fetch_privateeye.py read the issue off every title shape the
# archive ships, take the Eye's Christmas cover date as it prints it, and read
# the answer off an untagged fifteensquared row?
#
#     bash tools/test_privateeye_dates.sh
#
# Offline: the cover page is stubbed.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: want [$2] got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import datetime
import fetch_privateeye as pe

print("PAIRS", pe.issue_number(400, "Eye 1245/400"), pe.issue_number(821, "Eye 821/1666"),
      pe.issue_number(538, "Eye 538/ 1383"))
print("ALONE", pe.issue_number(434, "Eye 1279"), pe.issue_number(436, "Eye 1280   (2 Feb '11)"),
      pe.issue_number(434, "Eye 434"))

covers = {1: datetime.date(2011, 1, 7), 2: datetime.date(2016, 12, 20),
          3: datetime.date(2007, 1, 20)}
pe.fetch_cover_date = covers.get
day = lambda issue: pe.cover_date(99, f"Eye 99/{issue}")
print("COVERS", day(1), day(2), day(3))

# The cadence: the one issue between neighbours four weeks apart is dated;
# one between neighbours six weeks apart (a skipped week) is not.
import json, pathlib, tempfile
tmp = pathlib.Path(tempfile.mkdtemp())
for num, d in ((330, "2007-01-05"), (331, None), (332, "2007-02-02"), (333, None), (334, "2007-03-16")):
    (tmp / f"cyclops-{num}.json").write_text(
        json.dumps({"id": f"cyclops-{num}", "date": d, "entries": []}, indent=1) + "\n")
pe.date_by_cadence(tmp)
print("CADENCE", *(json.loads((tmp / f"cyclops-{n}.json").read_text())["date"] for n in (331, 333)))

# The untagged 2007 template: answer with its wordplay marked, a dash, a note.
rows = pe.parse_fifteensquared_rows(
    "<table><tr><th>Across</th></tr>"
    "<tr><td>10</td><td>PUB(L)IC HAIR &#8211; Bush in the clue</td></tr>"
    "<tr><td>12</td><td>IN THE PUB LIC(e) INTEREST &#8211; long</td></tr>"
    "<tr><td>9</td><td>(HARPO)&lt; &#8211; Does Marx ever</td></tr>"
    "<tr><td>18</td><td>IC in (WHIPS)*</td></tr>"
    "<tr><td>1</td><td>D\u00c9TENTE</td></tr></table>")
print("UNTAGGED", *(f"{k}={v}" for k, _, v in rows))

# A blog row numbered for no light of its length takes the one light left open.
def light(n, d, x, y, size):
    return {"id": f"{n}-{d}", "number": n, "direction": d, "position": {"x": x, "y": y},
            "length": size, "clue": "Clue (%d)" % size, "solution": None}
grid = {"entries": [light(1, "across", 0, 0, 3), light(1, "down", 0, 0, 3),
                    light(2, "down", 2, 0, 3), light(3, "across", 0, 2, 3)]}
def post(rows):
    return {"content": {"rendered": "<table><tr><th>Across</th></tr>" + "".join(
        f"<tr><td>{k}</td><td><strong>{v}</strong></td></tr>" for k, v in rows) + "</table>"}}
sol, _ = pe.solve_from_fifteensquared(grid, post([("1", "CAT"), ("4", "TEN"), ("1d", "CUT"), ("2d", "TIN")]))
print("STRAY", sol and sol["3-across"])
sol, why = pe.solve_from_fifteensquared(grid, post([("1", "CAT"), ("4", "TAP"), ("1d", "CUT"), ("2d", "TIN")]))
print("STRAY_CROSSES", sol, why.split(":")[0])
PY
)
got() { echo "$out" | sed -n "s/^$1 //p"; }
check "an issue/number pair is read in either order" "1245 1666 1383" "$(got PAIRS)"
check "a title naming one number names the issue" "1279 1280 None" "$(got ALONE)"
check "a Friday and a Christmas cover date are kept, another weekday is not" \
  "2011-01-07 2016-12-20 None" "$(got COVERS)"
check "an undated Cyclops between neighbours four weeks apart takes the Friday between" \
  "2007-01-19 None" "$(got CADENCE)"
check "an untagged answer is read up to its note; wordplay standing in for one is not" \
  "10=PUBLICHAIR 12=INTHEPUBLICINTEREST 1=DETENTE" "$(got UNTAGGED)"
check "a misnumbered blog row fills the one open light of its length" "TEN" "$(got STRAY)"
check "and only if it crosses" "None crossing conflict at column 2, row 2" "$(got STRAY_CROSSES)"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
