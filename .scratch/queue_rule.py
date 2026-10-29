"""Queue every clue pre_reversed_leaf flags (except the reported one, fixed by hand) in shape_reannotate.json."""
import sys, json
sys.path.insert(0, 'tools')
import puzzle_paths
import shape_queue as Q
import validate_annotations as V

why = "preReversedLeaf: " + Q._why("preReversedLeaf")
new = []
for path in puzzle_paths.puzzle_files():
    try:
        pz = json.loads(open(path).read())
    except (OSError, ValueError):
        continue
    pid = pz.get("id")
    if not pid or Q.exempt(pid):
        continue
    for e in pz.get("entries") or []:
        w = (e.get("annotation") or {}).get("wordplay")
        if isinstance(w, dict) and V.pre_reversed_leaf(w):
            new.append(f"{pid}#{Q.clue_key(e)}")
with Q.locked():
    rows = json.loads(Q.PATH.read_text())
    have = {r["id"]: r for r in rows}
    added = 0
    for i in new:
        if i in have:
            r = have[i]
            if "preReversedLeaf" not in Q.reason_names(r["reason"]):
                r["reason"] += "; " + why
                r.pop("tried", None)
                added += 1
        else:
            rows.append({"id": i, "reason": why})
            added += 1
    Q.write(Q.dump(rows))
print(len(new), "flagged,", added, "queued")
print(' '.join(new))
