#!/usr/bin/env python3
# Does /learn/ teach every clue type with a real, recorded example, and does
# each type carry its own indicators?
# Every pick in tools/data/learn_examples.json must be printed, as a clue, in
# its own section of tools/tutorial.html; every clue-type section must open
# with a real clue; every <!-- indicators: TYPE --> marker must render that
# type's most used words with a link to its list on /indicators/; and the
# rendered page must have no standalone indicator table, must call
# abbreviations dictionary-backed rather than impossible to work out, and must
# link each solving blog it names.
#
#     python3 tests/test_learn_examples.py
#
# Reads the lesson, the picks and the lexicons; nothing here reads the corpus.
import html
import json
import re
import sys

import _path  # puts tools/ on sys.path

import build_seo_pages

fails = []


def result(key, ok):
    if ok is True:
        print(f"ok   {key}")
    else:
        print(f"FAIL {key}: {ok}")
        fails.append(key)


ROOT = build_seo_pages.ROOT
lesson = (ROOT / "tools" / "tutorial.html").read_text(encoding="utf-8")
picks = json.loads((ROOT / "tools" / "data" / "learn_examples.json").read_text(encoding="utf-8"))["examples"]

# Each section: from its h4 to the next heading.
sections = dict(re.findall(r'<h4 id="([\w-]+)">.*?</h4>(.*?)(?=<h[34]\b|\Z)', lesson, re.S))
clue_text = {sid: html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
             for sid, body in sections.items() if (m := re.search(r'<span class="clue">(.*?)</span>', body, re.S))}
intro = re.search(r'<span class="clue">(.*?)</span>', lesson[:lesson.index("<h3>The main clue types</h3>")], re.S)

result("every clue-type section opens with a real clue",
       sorted(set(sections) - set(clue_text)) or True)
for p in picks:
    got = (html.unescape(re.sub(r"<[^>]+>", "", intro.group(1))) if p["section"] == "intro" and intro
           else clue_text.get(p["section"], ""))
    result(f"{p['section']}: {p['clue']}",
           True if got.startswith(p["clue"]) else f"section shows {got!r}")
    result(f"{p['section']}: the pick says why", True if p.get("why") else "no reason recorded")
result("every section has a recorded pick",
       sorted(set(sections) - {p["section"] for p in picks}) or True)

markers = re.findall(r"<!-- indicators: (\w+) -->", lesson)
result("no standalone indicator table", True if "table" not in markers else "marker 'table' is back")
for t in markers:
    out = build_seo_pages.learn_indicators(re.match(r"<!-- indicators: (\w+) -->", f"<!-- indicators: {t} -->"))
    result(f"{t}: lists its indicators and links to its list",
           True if f"/indicators/#{t}\"" in out and "<em>" in out else out or "rendered nothing")

page = build_seo_pages.learn_page()
result("the page has no 'Common indicator words' block",
       True if "Common indicator words" not in page else "still there")
result("abbreviations are called dictionary-backed",
       True if "dictionary" in page and "cannot work these out" not in page else "old copy")
for blog, url in (("Fifteensquared", "https://fifteensquared.net/"),
                  ("Big Dave's Crossword Blog", "https://bigdave44.com/"),
                  ("Times for the Times", "https://timesforthetimes.co.uk/")):
    result(f"{blog} is linked", True if f'href="{url}">{blog}' in page.replace("&#x27;", "'") else "no link")
result("no leftover old examples",
       [s for s in ("Stale, ", "Sexpot", "Apple device", "Lousy payment", "with Ted") if s in page] or True)

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall ok")
