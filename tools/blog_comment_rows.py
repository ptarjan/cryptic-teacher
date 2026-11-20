"""Answer rows read from the comments under a Times for the Times post.

A post sometimes leaves lights out and a commenter lists them ("There are just
the 4 easies: 5a SOLVER ..."). Each comment with at least two markers of the
form `<n><a|d> ... (len) ANSWER` gives rows. They only ever fill a light the
post gave no row for; apply_blog_answers.judge() still checks them against the
crossings, the file's answers and its annotations.
"""

import html
import json
import re

MARK = re.compile(r"(?<![\w(])(\d{1,2})\s?(a|d|ac|dn)\b[.:)]?\s", re.I)
LEN = re.compile(r"\((\d+(?:[,\-\s]+\d+)*)\)")
WORD = re.compile(r"[A-Z'’\-]+")
SPACED = re.compile(r"\b(?:[A-Z]\s){3,}[A-Z]\b")
DROPPED = re.compile(r"^\(([A-Z])\)\s*")      # "(B) ASSET": the bracketed letter is dropped


def comments(post_id, cache_dir, get):
    """[{"t": html}] of the post's comments, cached on disk beside the posts."""
    path = cache_dir / f"comments-{post_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    out, page = [], 1
    while True:
        batch, _h = get("https://timesforthetimes.co.uk/wp-json/wp/v2/comments"
                        f"?post={post_id}&per_page=100&page={page}")
        out += [{"t": c["content"]["rendered"]} for c in batch]
        if len(batch) < 100:
            break
        page += 1
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def _answer(tail):
    """The leading capitals of `tail`, up to a full stop or comma."""
    tail = SPACED.sub(lambda m: m.group(0).replace(" ", ""), tail)
    tail = re.sub(r"\b1\b", "I", tail)
    tail = DROPPED.sub("", tail.strip())
    run = []
    for tok in tail.split():
        core = re.sub(r"[().,;:!?]", "", tok)
        if not (core and WORD.fullmatch(core)):
            break
        run.append(tok)
        if tok.endswith((".", ",")):
            break
    return " ".join(run)


def rows_from(cs):
    """[(direction, number, answer)] from comments listing at least two answers."""
    rows = {}
    for c in cs:
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c["t"])))
        marks = list(MARK.finditer(text))
        found = []
        for i, m in enumerate(marks):
            seg = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
            ln = LEN.search(seg)
            ans = _answer(seg[ln.end():]) if ln else ""
            if ans:
                found.append((int(m.group(1)),
                              "across" if m.group(2)[0].lower() == "a" else "down", ans))
        if len(found) >= 2:
            for num, way, ans in found:
                rows.setdefault((way, num), ans)
    return [(way, num, ans) for (way, num), ans in rows.items()]


def extra_rows(rec, cs):
    """The comment rows for lights the post's own rows do not mention."""
    have = {(d, n) for d, n, *_ in rec["rows"]}
    return [r for r in rows_from(cs) if (r[0], r[1]) not in have]
