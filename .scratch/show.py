import sys, json, glob
sys.path.insert(0, 'tools')
import wordplay
for arg in sys.argv[1:]:
    pid, num, dr = arg.split(':')
    f = glob.glob(f'puzzles/*/*/{pid}.json')[0]
    d = json.load(open(f))
    for e in d['entries']:
        if str(e['number']) == num and e['direction'][0] == dr:
            w = e['annotation'].get('wordplay')
            try:
                s = wordplay.render(w) if hasattr(wordplay, 'render') else None
            except Exception:
                s = None
            def strip(n):
                if not isinstance(n, dict):
                    return n
                return {k: (strip(v) if isinstance(v, dict) else [strip(x) for x in v] if isinstance(v, list) else v)
                        for k, v in n.items() if k not in ('note',)}
            print(arg, e['solution'], '|', e['clue']['text'])
            print('  ', json.dumps(strip(w)))
