import sys, json, glob
sys.path.insert(0, 'tools')
import validate_annotations as V, wordplay
lex = V._lexicon_letters()
under_any = '--any' in sys.argv


def walk(n, anc=()):
    if not isinstance(n, dict):
        return
    yield n, anc
    for p in n.get('parts') or []:
        yield from walk(p, anc + (n.get('op'),))


hits = []
for f in glob.glob('puzzles/*/*/*.json'):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if not isinstance(d, dict):
        continue
    for e in d.get('entries') or []:
        a = e.get('annotation') or {}
        for n, anc in walk(a.get('wordplay')):
            if 'op' in n or not n.get('gives') or not n.get('words'):
                continue
            if not under_any and 'reversal' not in anc:
                continue
            if set(anc) & {'hidden', 'anagram', 'alternate', 'deletion', 'first', 'last', 'middle', 'homophone'}:
                continue
            if '--charade' in sys.argv and not (anc and anc[-1] == 'charade'):
                continue
            g = wordplay.letters(n['gives']).lower()
            note = str(n.get('note') or '').lower()
            if '--note' in sys.argv and (g[::-1] not in note or g in note):
                continue
            if len(g) >= 3 and g not in lex and g[::-1] in lex:
                hits.append((d.get('id'), e['number'], e['direction'][0], n['words'], n['gives'], e.get('solution'), anc))
for h in hits:
    print(h)
print(len(hits))
