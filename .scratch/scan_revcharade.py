import sys, json, glob
sys.path.insert(0, 'tools')
import validate_annotations as V, wordplay
lex = V._lexicon_letters()

hits = []
for f in sorted(glob.glob('puzzles/*/*/*.json')):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if not isinstance(d, dict):
        continue
    for e in d.get('entries') or []:
        a = e.get('annotation') or {}
        clue = (e.get('clue') or {}).get('text') or ''
        w = a.get('wordplay')
        if not isinstance(w, dict) or not clue:
            continue
        t = V._located(w, clue)
        low = clue.lower()
        for node in V._walk(t):
            if node.get('op') != 'reversal' or node.get('unchecked'):
                continue
            kids = [p for p in node.get('parts') or [] if isinstance(p, dict)]
            if len(kids) != 1 or kids[0].get('op') != 'charade' or kids[0].get('indicators'):
                continue
            parts = [p for p in kids[0].get('parts') or [] if isinstance(p, dict)]
            spans = [V._extent(p, clue, low) for p in parts]
            if len(parts) < 2 or None in spans:
                continue
            if all(spans[i + 1][0] < spans[i][0] for i in range(len(spans) - 1)):
                leaves = [p for p in parts if 'op' not in p and p.get('gives')]
                gl = [wordplay.letters(p['gives']).lower() for p in leaves]
                flag = sum(1 for g in gl if len(g) >= 3 and g not in lex and g[::-1] in lex)
                hits.append((f, e['number'], e['direction'][0], clue, e.get('solution'),
                             [(p.get('words'), p.get('gives'), p.get('op')) for p in parts], flag))
for h in hits:
    print(h)
print(len(hits))
