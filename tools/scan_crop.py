#!/usr/bin/env python3
"""The printed clues of an archive.org scan, cut out for the annotator.

    python3 tools/scan_crop.py times-18826    # prints the crop's path

A puzzle tools/file_archive_org_puzzles.py filed is OCR of a newspaper page,
and a clue its readers cut short or garbled ("Mournful supporter in English
lac") is still whole on the page. This cuts the box the filer's readers read
the clues in out of the page: the filer's ledger (<cache>/filed.jsonl) names
the edition, leaf and number that filed the id, and the RapidOCR cache under
<crops>/rapid/ holds the box it read. The crop is cached as
<crops>/clues/<id>.png and cut again when the reading's cache is newer.

Prints why there is no crop (not filed off a scan, the edition or its reading
no longer cached) and exits 1.
"""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import file_archive_org_puzzles as filer  # noqa: E402
from fetch_puzzle import read_puzzle_file, resolve_puzzle  # noqa: E402


class NoCrop(Exception):
    """Why a puzzle has no crop."""


def verdict(pid, cache):
    """(edition dir, verdict) of the ledger row that filed `pid`."""
    ledger = cache / "filed.jsonl"
    if not ledger.exists():
        raise NoCrop(f"no ledger at {ledger}")
    found = None
    for line in ledger.read_text().splitlines():
        row = json.loads(line)
        for v in row.get("verdicts") or []:
            if v.get("id") == pid and (found is None or v.get("wrote") or not found[1].get("wrote")):
                found = (cache / row["edition"], v)
    if found is None:
        raise NoCrop(f"{ledger} has no verdict filing {pid}")
    return found


def clue_box(d, number, crops):
    """(box, cache file) the filer's RapidOCR read the clues of `number` in."""
    for path in sorted((crops / "rapid").glob(f"{d.name}_{number}.*.json")):
        cached = json.loads(path.read_text())
        if isinstance(cached, dict):
            return tuple(cached["box"]), path
    raise NoCrop(f"no RapidOCR reading of {d.name} No {number} under {crops / 'rapid'}")


def crop(pid, cache=None, crops=None):
    """The path of `pid`'s clue crop, cut if missing or stale; NoCrop says why
    not. `cache` and `crops` default to the filer's."""
    cache, crops = cache or filer.CACHE, crops or filer.CROPS
    puzzle = read_puzzle_file(resolve_puzzle(pid))
    if (puzzle.get("source") or {}).get("acquiredBy") != filer.TOOL:
        raise NoCrop(f"{pid} was not filed off an archive.org scan")
    d, v = verdict(pid, cache)
    box, reading = clue_box(d, v["number"], crops)
    out = crops / "clues" / f"{pid}.png"
    if out.exists() and out.stat().st_mtime >= reading.stat().st_mtime:
        return out
    leaf = d / f"leaf_{v['leaf']:04d}.jpg"
    if not leaf.exists():
        raise NoCrop(f"{leaf} is no longer cached")
    out.parent.mkdir(parents=True, exist_ok=True)
    img = filer.page(d, v["leaf"])
    img.crop(box).convert("L").save(out)
    return out


def main(argv):
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__.strip())
        return 2
    try:
        print(crop(argv[0]))
    except NoCrop as why:
        print(f"scan_crop: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
