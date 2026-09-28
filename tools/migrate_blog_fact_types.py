#!/usr/bin/env python3
"""Rewrite the blog facts' and the indicator lexicon's type strings as clue_types names.

A blog fact's "type" becomes a list of clue_types.NAMES ("charade + first
letter" -> ["charade", "letter_selection"]); the gold file's likewise; the
indicator lexicon's keys become names ("hidden" -> "hidden_word",
"selection" -> "letter_selection"). Each file is written back as the tool
that owns it writes it, so only the migrated lines change. Running it twice
changes nothing.

    python3 tools/migrate_blog_fact_types.py          # dry run: print the counts
    python3 tools/migrate_blog_fact_types.py --write
"""
import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from clue_types import NAMES

BLOG_FACTS = ROOT / "tools" / "data" / "blog_facts"
GOLD = ROOT / "tools" / "blog_facts_gold.jsonl"
INDICATORS = ROOT / "tools" / "data" / "lexicons" / "indicators.json"

RENAMED = {"hidden word": "hidden_word", "double definition": "double_definition",
           "cryptic definition": "cryptic_definition", "&lit": "and_lit",
           "hidden": "hidden_word", "selection": "letter_selection"}
POSITIONAL = {f"{where} letter{s}" for where in ("first", "last", "middle", "outer", "alternate")
              for s in ("", "s")}


def name_of(part):
    n = "letter_selection" if part in POSITIONAL else RENAMED.get(part, part)
    if n not in NAMES:
        sys.exit(f"type part {part!r} has no clue_types name")
    return n


def type_list(t):
    """An old " + "-joined type string as a list of names, in order, once each."""
    return list(dict.fromkeys(name_of(p) for p in t.split(" + ")))


def _migrate_fact(fact, stats, key):
    if isinstance(fact.get("type"), str):
        fact["type"] = type_list(fact["type"])
        stats[key] += 1
        return True
    return False


def _series_text(rows):
    """As blog_facts.write and letter_facts.write lay a series file out."""
    return "{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False, sort_keys=True)
                              for k, v in sorted(rows.items())) + "\n}\n"


def _lexicon_text(data):
    """As letter_facts.export_lexicons lays a lexicon out."""
    return "{\n" + ",\n".join(json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False)
                              for k, v in data.items()) + "\n}\n"


def migrate(stats: collections.Counter, write: bool):
    for f in sorted(BLOG_FACTS.glob("*.json")):
        rows = json.loads(f.read_text(encoding="utf-8"))
        changed = False
        for rec in rows.values():
            for fact in rec["entries"].values():
                changed |= _migrate_fact(fact, stats, "blog_fact_types")
        if changed and write:
            f.write_text(_series_text(rows), encoding="utf-8")

    lines = GOLD.read_text(encoding="utf-8").splitlines()
    out, changed = [], False
    for line in lines:
        r = json.loads(line)
        if _migrate_fact(r["gold"], stats, "blog_fact_gold_types"):
            changed = True
            line = json.dumps(r, ensure_ascii=False)
        out.append(line)
    if changed and write:
        GOLD.write_text("".join(l + "\n" for l in out), encoding="utf-8")

    lex = json.loads(INDICATORS.read_text(encoding="utf-8"))
    renamed = {name_of(k): v for k, v in lex.items()}
    if len(renamed) != len(lex):
        sys.exit(f"{INDICATORS}: two keys fold into one name: {sorted(lex)}")
    stats["indicator_keys"] += sum(k not in NAMES for k in lex)
    if list(renamed) != list(lex) and write:
        INDICATORS.write_text(_lexicon_text(renamed), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite the files; without it, only count")
    args = ap.parse_args()
    stats = collections.Counter()
    migrate(stats, args.write)
    print(dict(stats))
