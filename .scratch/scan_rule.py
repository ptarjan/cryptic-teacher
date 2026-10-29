import sys, json, glob
sys.path.insert(0, 'tools')
import validate_annotations as V

hits = []
for f in sorted(glob.glob('puzzles/*/*/*.json')):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if not isinstance(d, dict):
        continue
    for e in d.get('entries') or []:
        w = (e.get('annotation') or {}).get('wordplay')
        if isinstance(w, dict) and V.pre_reversed_leaf(w):
            hits.append(f"{d['id']}:{e['number']}:{e['direction'][0]}")
print(' '.join(hits))
print(len(hits))
