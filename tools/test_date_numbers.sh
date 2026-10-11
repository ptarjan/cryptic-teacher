#!/bin/bash
# Is a date-keyed puzzle number (Metro, the Canberra Times) named by its day?
# Their papers print no number, so the stored number is the print date, and
# formatting it as a number would read "Cryptic 20,260,922".
# Renders every numberIsDate series' page and refuses a separated number in the
# title, heading, description or archive row.
#
#     bash tools/test_date_numbers.sh
#
# Synthetic puzzles, so nothing here reads the corpus or writes to the tree.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>&1
import html
import re
import series as S
import build_seo_pages as B

dated = {k: S.meta(k)["numberIsDate"] for k in S.SERIES if "numberIsDate" in S.meta(k)}
print("SOME", {"metro", "canberra"} <= set(dated))

ok = True
for key, prefix in dated.items():
    num = int("20260922"[len(prefix):])
    day = S.number_date(key, num)
    puz = {"id": f"{key}-{num}", "series": key, "number": num, "setter": None,
           "date": day.isoformat(), "name": "x", "entries": [],
           "dimensions": {"cols": 15, "rows": 15}}
    page = B.puzzle_page(puz, {"annotated": True}, None, None)
    parts = re.findall(r"<title>(.*?)</title>|<h1>(.*?)</h1>|"
                       r'name="description" content="([^"]*)"', page)
    texts = [t for tup in parts for t in tup if t] + [B.named(puz)]
    words = f"{day:%A} {day.day} {day:%B %Y}"
    for t in texts:
        if re.search(r"\d,\d{3}", t) or str(num) in t or words not in t:
            ok = False
            print(f"BAD {key}: {t!r}")
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    if not title.startswith(f"{S.paper_kind(key)}, {words}"):
        ok = False
        print(f"BAD title {key}: {title!r}")
    if S.display_number(key, num) != f"{day.day} {day:%b %Y}":
        ok = False
        print(f"BAD display {key}: {S.display_number(key, num)!r}")
print("PAGES", ok)

# The archive row: the date in the date column like every other row, the
# paper and kind in the title slot ("Metro Cryptic"), as the answer page's
# prev/next links name it. The kind alone ("Cryptic") named no paper.
rows = True
for key in dated:
    num = int("20260922"[len(dated[key]):])
    day = S.number_date(key, num)
    row = B.hub_row({"id": f"{key}-{num}", "series": key, "number": num, "setter": None,
                     "date": day.isoformat()})
    want_num = f'<span class="p-num">{B.esc(S.paper_kind(key))}</span>'
    meta = re.search(r'<span class="p-meta">(.*?)</span>', row).group(1)
    if want_num not in row or not meta or str(day.year) not in meta:
        rows = False
        print(f"BAD row {key}: {row!r}")
print("ROWS", rows)

# Every series, not just today's date-keyed ones: a row whose title slot is a
# name rather than a number names the publisher, and two puzzles of one series
# never print the same title and date. Catches any series that falls back to
# its bare kind ("Cryptic"), whatever field it is missing.
def slots(row):
    return tuple(html.unescape(re.search(rf'<span class="{c}">(.*?)</span>', row).group(1))
                 for c in ("p-num", "p-meta"))
names = True
for key in sorted(S.SERIES):
    if S.is_book(key):
        continue
    prefix = S.meta(key).get("numberIsDate")
    pair = []
    for i, iso in enumerate(("2026-09-22", "2026-09-23")):
        num = (int(iso.replace("-", "")[len(prefix):]) if prefix is not None
               else 1000 + i)
        pair.append(slots(B.hub_row({"id": f"{key}-{num}", "series": key,
                                     "number": num, "setter": None, "date": iso})))
    for title, _ in pair:
        if not re.search(r"\d", title) and S.publisher(key) not in title:
            names = False
            print(f"BAD name {key}: {title!r} does not name {S.publisher(key)!r}")
    if pair[0] == pair[1]:
        names = False
        print(f"BAD name {key}: two puzzles both read {pair[0]!r}")
print("NAMES", names)

# Mirror: a non-date number still names itself.
print("PLAIN", S.number_date("cryptic", 30111) is None
      and B.named({"series": "cryptic", "number": 30111}) == "Guardian Cryptic No 30,111")

PY
)
# Mirror: the picker row prints exactly what the archive row prints, for a
# feed, a book and each date-keyed series. app.js's displayNumber() is run
# against tools/series.py display_number() on the same puzzles.
mirror=$(cd "$REPO" && PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>&1
import html, json, re, subprocess
import series as S
import build_seo_pages as B
books = {str(i): {"shelf": r["shelf"], "volume": r["volume"], "was": r["was"]}
         for i, r in S.BOOKS.items()}
dated = sorted(k for k in S.SERIES if "numberIsDate" in S.meta(k))
cases = [{"series": "cryptic", "number": 30127, "date": "2026-10-02"},
         {"series": "quiptic", "number": 999, "date": "2026-10-02"},
         {"series": "book", "number": 3018, "year": 1995}]
for k in dated:
    num = int("20260922"[len(S.meta(k)["numberIsDate"]):])
    cases.append({"series": k, "number": num, "date": S.number_date(k, num).isoformat()})
js = r"""
const src = require("fs").readFileSync("app.js", "utf8");
const cut = (a, b) => { const s = src.indexOf(a), e = src.indexOf(b, s); return src.slice(s, src.indexOf("\n  }\n", e) + 4); };
const body = cut("  const BOOKS = INDEX.books", "function displayNumber")
  + cut("  const WEEKDAYS", "function puzzleDate");
// pickerRow's title slot, lifted out of it whole.
const title = src.match(/const title = (isDateNumbered\(p\)[^;]*);/)[1];
const f = new Function("INDEX", body + "; return { displayNumber, title: (p) => " + title + " };")(JSON.parse(process.argv[1]));
console.log(JSON.stringify(JSON.parse(process.argv[2]).map((p) => [f.displayNumber(p), f.title(p)])));
"""
# The index's dateNumbered as fetch_puzzle.reindex() writes it.
got = json.loads(subprocess.run(["node", "-e", js, json.dumps({"books": books, "dateNumbered": S.date_numbered()}),
                                 json.dumps(cases)], capture_output=True, text=True, check=True).stdout)
ok = picker = True
for c, (g, t) in zip(cases, got):
    want = S.display_number(c["series"], c["number"])
    if g != want:
        ok = False
        print(f"BAD mirror {c['series']}-{c['number']}: app {g!r}, archive {want!r}")
    # The picker row's title slot is the archive row's, character for character.
    row = B.hub_row(dict(c, id=f"{c['series']}-{c['number']}", setter=None))
    slot = html.unescape(re.search(r'<span class="p-num">(.*?)</span>', row).group(1))
    if t != slot:
        picker = False
        print(f"BAD picker title {c['series']}-{c['number']}: app {t!r}, archive {slot!r}")
print("MIRROR", ok and len(got) == len(cases))
print("PICKER", picker and len(got) == len(cases))
PY
)
out="$out
$mirror"
echo "$out"
for k in SOME PAGES ROWS NAMES PLAIN MIRROR PICKER; do
  grep -qx "$k True" <<<"$out" || { echo "FAIL: $k"; exit 1; }
done
echo "PASS"
