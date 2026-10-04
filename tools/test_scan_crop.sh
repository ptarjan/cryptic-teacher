#!/bin/bash
# Does the annotator get the printed clues of a puzzle filed off a scan?
#
#     bash tools/test_scan_crop.sh
#
# A scratch cache holds one edition, its ledger row and the RapidOCR reading's
# box, for times-18826 (filed by tools/file_archive_org_puzzles.py):
#   - tools/scan_crop.py cuts that box out of the leaf, and cuts it again only
#     when the reading is newer;
#   - a puzzle not filed off a scan, or missing from the ledger, has no crop;
#   - validate_annotations.scan_read lets a row through only when its evidence
#     says it was read off the scan and the scan can be shown.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$REPO" && python3 - "$tmp" <<'PY'
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, "tools")
from PIL import Image
import file_archive_org_puzzles as filer
import scan_crop
import validate_annotations as V

tmp = Path(sys.argv[1])
cache, crops = tmp / "editions", tmp / "crops"
d = cache / "NewsUK1992UKEnglish" / "1992-01-28_64240"
d.mkdir(parents=True)
Image.new("L", (400, 600), 255).save(d / "leaf_0015.jpg")
(cache / "filed.jsonl").write_text(json.dumps({
    "edition": "NewsUK1992UKEnglish/1992-01-28_64240",
    "verdicts": [{"number": 18826, "leaf": 15, "id": "times-18826", "wrote": True}]}) + "\n")
reading = crops / "rapid" / "1992-01-28_64240_18826.ch.json"
reading.parent.mkdir(parents=True)
reading.write_text(json.dumps({"box": [10, 300, 210, 580], "words": []}))

fails = 0
def check(what, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + what)
    fails += not ok

out = scan_crop.crop("times-18826", cache, crops)
check("the crop is the reading's box", Image.open(out).size == (200, 280))
before = out.stat().st_mtime_ns
time.sleep(0.01)
scan_crop.crop("times-18826", cache, crops)
check("a cached crop is not cut again", out.stat().st_mtime_ns == before)
os.utime(reading, ns=(before + 10**9, before + 10**9))
scan_crop.crop("times-18826", cache, crops)
check("a newer reading is cut again", out.stat().st_mtime_ns != before)

def refused(pid, cache=cache):
    try:
        scan_crop.crop(pid, cache, crops)
    except scan_crop.NoCrop as why:
        return str(why)
    return None
check("a puzzle not filed off a scan has none", "not filed off" in (refused("cryptic-29000") or ""))
check("a puzzle the ledger never filed has none", "no verdict" in (refused("times-18844") or ""))

filer.CACHE, filer.CROPS = cache, crops
key = ("times-18826", "7-down")
V.SOURCE_CLUE_WRONG[key] = ("Mournful", "Mournful x", V.SCAN_READ + "the page prints it whole")
check("a row read off the scan passes", V.scan_read(*key))
V.SOURCE_CLUE_WRONG[key] = ("Mournful", "Mournful x", "OCR misread: a letter")
check("a misread row is not a scan read", not V.scan_read(*key))
V.SOURCE_CLUE_WRONG[key] = ("Mournful", "Mournful x", V.SCAN_READ + "the page prints it whole")
filer.CACHE = tmp / "nowhere"
check("a scan read with no scan to show fails", not V.scan_read(*key))
print(f"scan_crop: {'all checks passed' if not fails else f'{fails} FAILED'}")
sys.exit(fails > 0)
PY
