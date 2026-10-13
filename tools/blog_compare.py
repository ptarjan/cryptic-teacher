#!/usr/bin/env python3
"""Our annotations against what the blogs mark, clue by clue, over the corpus.

tools/blog_facts.py keeps what a write-up marks about each clue (the
definition underlined, the clue type named, the building blocks), in words of
our own clue and never the blogger's prose. Two uses come of it:

  * a clue we have not annotated is hinted from those facts until we do
    (fetch_puzzle.with_blog_facts, app.js blogAnn); this counts how many;
  * a clue we have annotated is compared with them, by the validator's own
    checks (validate_annotations.check_*_against_blog), so this report and
    what tools/annotate_check.py tells a run are the same judgement.

A disagreement is a prompt to look, never an overwrite: bloggers underline
wordplay and miss pieces as often as we do (see SOURCE_ANSWER_WRONG for how
far even an official key can be trusted). A clue a run has looked at and kept
is filed in tools/data/blog_disagree.json and not counted again. The puzzles
left with a disagreement are `due`: tools/prereset_backfill.sh re-checks
them once the annotation backlog is spent.

    python3 tools/blog_compare.py            # write tools/data/blog_compare.json
    python3 tools/blog_compare.py --print    # and print the rates and examples
    python3 tools/blog_compare.py --due      # the due puzzle ids, most disagreements first
    python3 tools/blog_compare.py --keep cryptic-30043 20-down definition "why ours stands"

--keep files one checked clue in tools/data/blog_disagree.json, for a run
re-checking an annotated puzzle (whose fixes are edits to the puzzle file, not
an _ann file, so annotate_check's `blogDisagree` filing is not there for it).

Reads only the repo: puzzles/ and tools/data/blog_facts/.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

import definitions
from fetch_puzzle import blog_facts_for, puzzle_files, puzzle_paths, read_puzzle_view, with_blog_facts
from json_merge import dump_lines
from groups import entry_id
import validate_annotations as V

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "blog_compare.json"
TABLE = ROOT / "tools" / "data" / "blog_disagree.json"
#: How many example disagreements of each kind the report keeps.
EXAMPLES = 12

KINDS = {
    "definition": V.check_definition_against_blog,
    "blocks": V.check_blocks_against_blog,
    "type": None,  # check_cryptic_definition_against_blog and check_type_against_blog
}


def tag_id(tag):
    """"12A" -> "12-across"."""
    m = re.match(r"(\d+)([AD])", tag)
    return m and f"{m[1]}-{'across' if m[2] == 'A' else 'down'}"


def warned(check, puzzle):
    """{entry id: warning} for one blog check run on the puzzle."""
    out = []
    check(puzzle, out)
    return {tag_id(w.split(":", 1)[0]): w for w in out}


def comparable(ann, fact):
    """Which kinds this clue gives both sides of: ours annotated and the blogger
    (not tools/letter_facts.py's inference) marking it."""
    inferred = set(fact.get("inferred") or ())
    out = []
    if definitions.texts(ann) and fact.get("definitions") and "definitions" not in inferred:
        out.append("definition")
    if ann.get("blocks") and any(not b.get("inferred") for b in fact.get("blocks") or ()):
        out.append("blocks")
    if V.types_of(ann) and fact.get("type") and "type" not in inferred:
        out.append("type")
    return out


def survey():
    by_series = collections.defaultdict(lambda: collections.Counter())
    examples = collections.defaultdict(list)
    due = {}
    cover = collections.Counter()
    for path in puzzle_files():
        p = read_puzzle_view(path)
        series = p.get("series", "cryptic")
        entries = [e for e in p["entries"] if not (e.get("clue") or {}).get("missing")]
        unhinted = [e for e in entries if not e.get("annotation")]
        cover["clues"] += len(entries)
        cover["unhinted_clues"] += len(unhinted)
        annotated_any = len(unhinted) < len(entries)
        cover["puzzles"] += 1
        cover["unhinted_puzzles"] += not annotated_any
        row = blog_facts_for(p)
        if not row:
            continue
        if unhinted:
            shown = with_blog_facts(p)
            got = [e for e in shown["entries"] if e.get("blog") and not e.get("annotation")]
            marked = [e for e in got if any(k not in (e["blog"].get("inferred") or ())
                                            for k in ("definitions", "type", "blocks", "indicators")
                                            if e["blog"].get(k))]
            cover["blog_hinted_clues"] += len(got)
            cover["blog_marked_clues"] += len(marked)
            if not annotated_any and got:
                cover["blog_hinted_puzzles"] += 1
            if annotated_any and got:
                cover["blog_hinted_partial_puzzles"] += 1
        if not annotated_any:
            continue
        hits = {k: warned(c, p) for k, c in KINDS.items() if c}
        hits["type"] = {**warned(V.check_type_against_blog, p),
                        **warned(V.check_cryptic_definition_against_blog, p)}
        mine = []
        for e in entries:
            ann, fact = e.get("annotation"), row["entries"].get(entry_id(e))
            if not ann or not fact:
                continue
            c = by_series[series]
            c["clues"] += 1
            for kind in comparable(ann, fact):
                c[f"{kind}_compared"] += 1
                if V.blog_kept(p, e, kind):
                    c[f"{kind}_kept"] += 1
            for kind in KINDS:
                w = hits[kind].get(entry_id(e))
                if not w:
                    continue
                c[f"{kind}_disagree"] += 1
                mine.append([entry_id(e), kind])
                if len(examples[kind]) < EXAMPLES * 4:
                    examples[kind].append({"puzzle": p["id"], "entry": entry_id(e),
                                           "clue": e["clue"].get("text", ""),
                                           "answer": e.get("solution") or "",
                                           "warning": w.split(": ", 1)[1]})
        if mine:
            due[p["id"]] = mine
    return by_series, examples, due, cover


def keep_ours(pid, eid, fields, why):
    """File (pid, eid) as checked against its blog and kept; what is wrong, or None."""
    fields = ",".join(f.strip() for f in fields.split(","))
    bad = [f for f in fields.split(",") if f not in V.BLOG_FIELDS]
    if bad:
        return f"{', '.join(bad)}: the fields are {', '.join(V.BLOG_FIELDS)}"
    if not why.strip():
        return "say in one sentence why ours stands"
    path = puzzle_paths.find(pid)
    if not path:
        return f"no puzzle {pid}"
    if eid not in {entry_id(e) for e in read_puzzle_view(path)["entries"]}:
        return f"{eid}: not an entry of {pid}"
    rows = json.loads(TABLE.read_text(encoding="utf-8"))
    rows[f"{pid}/{eid}"] = [fields, why.strip()]
    TABLE.write_text(dump_lines(rows), encoding="utf-8")
    return None


def rate(n, d):
    return round(100 * n / d, 2) if d else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--print", action="store_true", help="print the rates and examples")
    ap.add_argument("--due", action="store_true", help="print the due puzzle ids and exit")
    ap.add_argument("--keep", nargs=4, metavar=("PUZZLE", "ENTRY", "FIELDS", "WHY"),
                    help="file one clue as checked against its blog and kept")
    args = ap.parse_args()
    if args.keep:
        err = keep_ours(*args.keep)
        print(err or f"filed {args.keep[0]}/{args.keep[1]} in tools/data/blog_disagree.json")
        return 1 if err else 0
    if args.due:
        held = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        for pid, rows in sorted((held.get("due") or {}).items(), key=lambda kv: (-len(kv[1]), kv[0])):
            print(pid)
        return
    by_series, examples, due, cover = survey()
    summary = {}
    total = collections.Counter()
    for s, c in sorted(by_series.items()):
        total.update(c)
        summary[s] = {**dict(sorted(c.items())),
                      **{f"{k}_rate": rate(c[f"{k}_disagree"], c[f"{k}_compared"]) for k in KINDS}}
    summary["ALL"] = {**dict(sorted(total.items())),
                      **{f"{k}_rate": rate(total[f"{k}_disagree"], total[f"{k}_compared"]) for k in KINDS}}
    # A spread of examples, not the first few puzzles' worth.
    keep = {k: v[::max(1, len(v) // EXAMPLES)][:EXAMPLES] for k, v in examples.items()}
    report = {
        "_why": "Our annotations against the blogs' marked facts (tools/blog_compare.py). "
                "Rates are disagreements per clue where both sides mark that fact; "
                "`due` is each puzzle's clues still disagreeing, unfiled in blog_disagree.json, "
                "which tools/prereset_backfill.sh re-checks. A disagreement is a prompt to check, "
                "not an overwrite.",
        "coverage": dict(sorted(cover.items())),
        "summary": summary,
        "examples": keep,
        "due": dict(sorted(due.items())),
    }
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(due)} puzzles due, "
          f"{sum(map(len, due.values()))} clue disagreements")
    if args.print:
        print(json.dumps(report["coverage"], indent=1))
        for s, c in summary.items():
            print(f"{s:14} clues {c.get('clues', 0):6}  " + "  ".join(
                f"{k} {c.get(f'{k}_disagree', 0)}/{c.get(f'{k}_compared', 0)} ({c[f'{k}_rate']}%)" for k in KINDS))
        for k, v in keep.items():
            print(f"--- {k}")
            for x in v:
                print(f"  {x['puzzle']} {x['entry']} {x['clue']!r} = {x['answer']}: {x['warning'][:220]}")


if __name__ == "__main__":
    sys.exit(main())
