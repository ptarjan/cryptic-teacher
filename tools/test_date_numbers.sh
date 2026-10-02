#!/bin/bash
# Is a date-keyed puzzle number (Metro, the Canberra Times) named by its day?
# Their papers print no number, so the stored number is the print date, and
# formatting it as a number gave "Cryptic 20,260,922 answers explained".
# Renders every numberIsDate series' page and refuses a separated number in the
# title, heading, description or archive row.
#
#     bash tools/test_date_numbers.sh
#
# Synthetic puzzles, so nothing here reads the corpus or writes to the tree.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY' 2>&1
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

# Mirror: a non-date number still names itself.
print("PLAIN", S.number_date("cryptic", 30111) is None
      and B.named({"series": "cryptic", "number": 30111}) == "Guardian Cryptic No 30,111")

PY
)
echo "$out"
for k in SOME PAGES PLAIN; do
  echo "$out" | grep -qx "$k True" || { echo "FAIL: $k"; exit 1; }
done
echo "PASS"
