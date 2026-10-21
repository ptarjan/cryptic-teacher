"""Helpers for apply_blog_answers' bigdave44 source: the two-paragraph clue layout
and the post-search fallback for puzzles whose slug guess misses."""
import html
import json
import re

#: A clue paragraph: number, a/d, the clue, and its enumeration, nothing after.
CLUE_ONLY = re.compile(r"^\s*\d{1,2}\s*(?:ac|dn|a|d)\b.*\(\s*\d[\d,\-–\s]*\)\s*$", re.I | re.S)
#: An answer the blogger hid in a spoiler span rather than in {curly brackets}.
HIDDEN_SPAN = re.compile(r'class="hidden-content">(.*?)</span>', re.S)
TAGS = re.compile(r"<[^>]+>")

#: series -> regex for a post title, with the puzzle number as {n}.
TITLES = {
    "telegraph": r"\bDT\s*(?:No\.?\s*)?{n}\b",
    "toughie": r"\bToughie\s*(?:No\.?\s*)?{n}\b",
    "sundaytel": r"\bST\s*(?:No\.?\s*)?{n}\b",
}


def join_split_clues(html_text):
    """scchua's layout puts the clue in one <p> and its answer, as { ANSWER }, in the
    next. Join the two with a <br> so they read like the single-paragraph layout."""
    paras = html_text.split("</p>")
    out, i = [], 0
    while i < len(paras):
        para = paras[i]
        bare = "hidden-content" not in para and "{" not in para
        if i + 1 < len(paras) and bare and CLUE_ONLY.match(html.unescape(TAGS.sub("", para))):
            para = para + "<br />" + paras[i + 1]
            i += 1
        out.append(para)
        i += 1
    return "</p>".join(out)


def title_matches(series, number, title):
    """True when `title` is this series' answer post for exactly `number`."""
    title = html.unescape(title)
    if "hint" in title.lower() and "review" not in title.lower():
        return False
    return bool(re.search(TITLES[series].format(n=number), title, re.I))


def search_posts(api, fields, series, number, fetch, cache_path):
    """Posts found by the blog's own search, kept only when the title names this
    series and number. `fetch` is apply_blog_answers.get; the result is cached."""
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    label = {"telegraph": "DT", "toughie": "Toughie", "sundaytel": "ST"}[series]
    found, _ = fetch(f'{api}?search=%22{label}+{number}%22&per_page=20&_fields={fields}')
    posts = [p for p in found if title_matches(series, number, p["title"]["rendered"])]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(posts), encoding="utf-8")
    return posts
