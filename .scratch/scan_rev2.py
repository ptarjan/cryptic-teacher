import sys, json, glob, re
sys.path.insert(0, 'tools')
import validate_annotations as V, wordplay
lex = V._lexicon_letters()
SKIP = {'hidden', 'anagram', 'alternate', 'deletion', 'first', 'last', 'middle', 'homophone', 'spoonerism', 'select'}


def walk(n, anc=()):
    if not isinstance(n, dict):
        return
    yield n, anc
    for p in n.get('parts') or []:
        yield from walk(p, anc + (n.get('op'),))


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
        for n, anc in walk(a.get('wordplay')):
            if 'op' in n or not n.get('gives') or not n.get('words') or 'reversal' not in anc or set(anc) & SKIP:
                continue
            G = wordplay.letters(n['gives'])
            g = G.lower()
            if len(g) < 3 or g in lex or g[::-1] not in lex or V._known_pair(n['words'], G):
                continue
            note = str(n.get('note') or '').lower()
            named = re.search(r"\b" + g[::-1] + r"(?:s|es|d|ed|ing|er|ers)?\b", note) and g not in re.sub(r"[^a-z]", "", note)
            if V._known_pair(n['words'], G[::-1]) or named:
                hits.append((f.split('/')[-1][:-5], e['number'], e['direction'][0], n['words'], G, e.get('solution'), anc,
                             'pair' if V._known_pair(n['words'], G[::-1]) else 'note'))
for h in hits:
    print(h)
print(len(hits))
