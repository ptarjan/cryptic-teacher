"""Write the Jumbo solution days tried so far, with outcomes, as tried.csv in the
Solutions folder on the Mac (over gale_fetch's ssh). docs.json lives on the server only,
so this is how the desktop sees it. Run: python3 tools/gale_jumbo_tried.py"""
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gale_docs
import gale_fetch


def rows(docs):
    """[(date, outcome, docId, title, how)] of each jumbo-solution entry, by date."""
    out = []
    for k, e in docs.items():
        if "/jumbo-solution/" not in k:
            continue
        day = k.rsplit("/", 1)[1]
        if "doc" in e:
            out.append((day, "got docId", e["doc"], e.get("title", ""), e.get("how", "")))
        elif "no crossword" in e.get("why", "") or "no issue" in e.get("why", ""):
            out.append((day, "no match", "", e.get("why", ""), ""))
        else:
            out.append((day, "error", "", e.get("why", ""), ""))
    return sorted(out)


def main():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "outcome", "docId", "title_or_reason", "how"])
    w.writerows(rows(gale_docs.load()))
    gale_fetch.put(buf.getvalue().encode(), "tried.csv", gale_fetch.TIMES_JUMBO_SOLUTIONS_DIR)
    print(f"wrote {len(buf.getvalue().splitlines()) - 1} rows")


if __name__ == "__main__":
    main()
