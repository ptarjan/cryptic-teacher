"""Parse-rate harness: python3 scratch/parse_probe.py times|bd44 [misses N] [hits N] [seed]"""
import sys, json, random, re, collections, pickle
from pathlib import Path
sys.path.insert(0, 'scratch')
import difficulty_calibration as dc
blog = sys.argv[1]
nm = int(sys.argv[2]) if len(sys.argv) > 2 else 0
nh = int(sys.argv[3]) if len(sys.argv) > 3 else 0
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1
d = 'timesforthetimes' if blog == 'times' else 'bigdave44'
cache = Path(f'/tmp/probe_{blog}.pkl')
if cache.exists():
    recs = pickle.loads(cache.read_bytes())
else:
    recs = []
    for l in (dc.DATA / d / 'parsed.jsonl').open():
        r = json.loads(l)
        p = dc.DATA / d / 'posts' / f"{r['post_id']}.json"
        if not p.exists(): continue
        j = json.loads(p.read_text())
        raw = j['content']['rendered'] if isinstance(j['content'], dict) else j['content']
        recs.append((r['series'], r['number'], r['date'], r['link'], raw))
    cache.write_bytes(pickle.dumps(recs))
fn = dc.times_minutes if blog == 'times' else (lambda t, raw: dc.bd_stars({'content': raw}, t)[0])
tot = collections.Counter(); got = collections.Counter(); miss = []; hit = []
for s, n, date, link, raw in recs:
    t = dc.text_of(raw)
    v = fn(t) if blog == 'times' else fn(t, raw)
    k = (s, date[:4] if date < '2016' else date[:4])
    tot[s] += 1; tot[date[:4]] += 1; tot['ALL'] += 1
    if v == 'DNF': got['DNF'] += 1
    if v is not None and v != 'DNF':
        got[s] += 1; got[date[:4]] += 1; got['ALL'] += 1; hit.append((s, n, date, link, v, t))
    else:
        miss.append((s, n, date, link, t))
for k in sorted(tot, key=str):
    print(f"{k:<22} {got[k]:>5}/{tot[k]:<5} {100*got[k]/tot[k]:5.1f}%")
rnd = random.Random(seed)
def clean(t): return re.sub(r'\s*\n\s*', ' / ', t)
recent_miss = [m for m in miss if m[2] >= '2016']
for s, n, date, link, t in rnd.sample(recent_miss, min(nm, len(recent_miss))):
    c = re.search(r'(?im)^\s*(across|1\s*$)', t)
    print('\nMISS', s, n, date, link); print(clean(t[:c.start() if c and c.start() > 100 else 900])[:900])
for s, n, date, link, v, t in rnd.sample(hit, min(nh, len(hit))):
    print('\nHIT', s, n, date, v, link); print(clean(t[:600]))
