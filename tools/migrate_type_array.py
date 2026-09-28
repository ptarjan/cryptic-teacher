#!/usr/bin/env python3
"""Rewrite every " + "-joined `type` string in puzzles/ and tools/data/blog_facts/
as an array of names from tools/data/clue_types.json.

A positional part ("first letters", "fifth letter", "alternate letters", ...)
becomes `letter_selection`, and which letters it keeps moves onto the block
that keeps them, as `select` (see clue_types.SELECT_WORDS). The block is the
one whose `gives` those letters of its fragment spell; failing that, the one
whose note names that position, then any position, then the block giving the
fewest letters.

Deterministic and idempotent: an array is left alone, so it can be re-run on
upstream after a pull.

    python3 tools/migrate_type_array.py            # rewrite in place
    python3 tools/migrate_type_array.py --dry-run  # counts only
"""
import glob
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import clue_types  # noqa: E402
import migrate_blog_fact_types  # noqa: E402

RENAME = {"hidden word": "hidden_word", "double definition": "double_definition",
          "cryptic definition": "cryptic_definition", "&lit": "and_lit"}
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
            "eighth", "ninth", "tenth", "eleventh", "twelfth"]
POSITION = {"first": "first", "last": "last", "middle": "middle", "outer": "outer",
            "alternate": "alternate", "regular": "regular", "prime": "prime",
            **{o: i for i, o in enumerate(ORDINALS, 1) if i > 1}}
NOTE_WORDS = {
    "first": r"\b(first|initial|head|opening|lead|leader|start|begin|tip|front)",
    "last": r"\b(last|final|tail|end|closing|stops on|back)",
    "middle": r"\b(middle|centre|center|heart|core|mid|inside|insides|inner|without its (first and last|outside|edges|ends|outer))",
    "outer": r"\b(outer|outside|outermost|edges?|borders?|extremes?|ends|first and last|gutless|insides gone|emptied|empty)\b",
    "alternate": r"\b(alternate|odd|even|every other|every second|regular)",
    "regular": r"\b(every (third|fourth|fifth)|regular)",
    "prime": r"\bprime",
}


def part_name(part):
    """(type name, select value or None) for one old type part."""
    part = part.strip()
    if part.endswith((" letter", " letters")):
        return "letter_selection", POSITION[part.split()[0]]
    return RENAME.get(part, part), None


def convert_type(s):
    """(names in order without duplicates, [select values in order])."""
    names, selects = [], []
    for part in s.split(" + "):
        if not part.strip():
            continue
        name, sel = part_name(part)
        if name not in clue_types.NAMES:
            raise SystemExit(f"type part {part!r} has no name in clue_types.json")
        if name not in names:
            names.append(name)
        if sel is not None and sel not in selects:
            selects.append(sel)
    return names, selects


def letters(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^A-Z]", "", s.upper())


def _word_pick(w, sel):
    if sel == "first":
        return {w[:1]}
    if sel == "last":
        return {w[-1:]}
    if sel == "outer":
        return {w[:1] + w[-1:]} if len(w) > 1 else set()
    if sel == "middle":
        n = len(w)
        return {w[(n - 1) // 2:n // 2 + 1], w[n // 2 - 1:n // 2 + 1] if n > 1 else w,
                w[n // 2:n // 2 + 1], w[1:-1]}
    if isinstance(sel, int):
        return {w[sel - 1]} if len(w) >= sel else set()
    return set()


def _run_pick(run, sel):
    if sel == "alternate":
        return {run[0::2], run[1::2]}
    if sel == "regular":
        return {run[k::s] for s in range(2, 7) for k in range(s)}
    return set()


def selects_gives(block, sel):
    """Does keeping `sel` letters of some run of the fragment's words spell gives?"""
    gives = letters(block.get("gives"))
    words = [letters(w) for w in re.split(r"[\s\-–—/]+", block.get("clueFragment") or "")]
    words = [w for w in words if w]
    if not gives or not words:
        return False
    if sel == "prime":
        return True
    for i in range(len(words)):
        for j in range(i + 1, len(words) + 1):
            run = words[i:j]
            if gives in _run_pick("".join(run), sel):
                return True
            picks = [""]
            for w in run:
                picks = [p + q for p in picks for q in _word_pick(w, sel)]
                if len(picks) > 64:
                    break
            if gives in picks:
                return True
    return False


def note_names(block, sel):
    note = (block.get("note") or "").lower()
    if isinstance(sel, int):
        return bool(re.search(rf"\b({ORDINALS[sel - 1]}|{sel}(st|nd|rd|th))\b", note))
    return bool(re.search(NOTE_WORDS[sel], note))


def place_selects(blocks, selects, stats):
    """Put each select value on the block that does that selecting."""
    for sel in selects:
        free = [b for b in blocks if "select" not in b]
        for how, pick in (
                ("letters", lambda b: selects_gives(b, sel)),
                ("note", lambda b: note_names(b, sel)),
                ("note_any", lambda b: any(note_names(b, s) for s in NOTE_WORDS))):
            hit = next((b for b in free if pick(b)), None)
            if hit is not None:
                break
        else:
            how, hit = "fewest_letters", min(free, key=lambda b: len(letters(b.get("gives"))),
                                             default=None)
        if hit is None:
            stats["select_unplaced"] += 1
        else:
            hit["select"] = sel
            stats["select_by_" + how] += 1


def migrate_annotation(ann, stats):
    t = ann.get("type")
    if not isinstance(t, str):
        return False
    names, selects = convert_type(t)
    ann["type"] = names
    stats["annotations"] += 1
    place_selects(ann.get("blocks") or [], selects, stats)
    return True


def reorder(ann):
    """Keep `select` right after `gives` so a block reads fragment, letters, how."""
    for i, b in enumerate(ann.get("blocks") or []):
        if "select" in b:
            sel = b.pop("select")
            out = {}
            for k, v in b.items():
                out[k] = v
                if k == "gives":
                    out["select"] = sel
            if "select" not in out:
                out["select"] = sel
            ann["blocks"][i] = out


def migrate_puzzles(stats, write):
    for f in sorted(glob.glob(str(ROOT / "puzzles" / "*" / "*" / "*.json"))):
        text = Path(f).read_text(encoding="utf-8")
        if '"type": "' not in text and '"type":"' not in text:
            continue
        puz = json.loads(text)
        changed = False
        for e in puz.get("entries", []):
            ann = e.get("annotation")
            if ann and migrate_annotation(ann, stats):
                reorder(ann)
                changed = True
        if changed and write:
            Path(f).write_text(json.dumps(puz, indent=1, ensure_ascii=False) + "\n",
                               encoding="utf-8")


def main():
    write = "--dry-run" not in sys.argv
    stats = Counter()
    migrate_puzzles(stats, write)
    migrate_blog_fact_types.migrate(stats, write)
    for k, v in sorted(stats.items()):
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
