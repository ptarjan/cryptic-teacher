"""Collect (date, series, nitch, raw components, per-clue device detail) for
every SNITCH-rated puzzle we hold, into scratch/snitch_rows.json, the input
to scratch/snitch_weights.py and scratch/snitch_device.py."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import difficulty as D
from fetch_puzzle import read_puzzle_file, puzzle_is_annotated
sn = json.loads((ROOT / "tools/data/snitch.json").read_text())
rank = D.ranks()
rows = []
for pid, v in sn.items():
    path = ROOT / "puzzles" / f"{pid}.json"
    if not path.exists():
        continue
    puz = read_puzzle_file(path)
    r = D.raw(puz, rank)
    rows.append({"id": pid, "date": v["date"], "nitch": v["nitch"], "annotated": puzzle_is_annotated(puz), **r})
(ROOT / "scratch/snitch_rows.json").write_text(json.dumps(rows))
print(len(rows), sum(1 for r in rows if r["device"] is not None))
