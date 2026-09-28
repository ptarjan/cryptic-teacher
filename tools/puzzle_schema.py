#!/usr/bin/env python3
"""The puzzle file's shape: tools/data/puzzle.schema.json, and the one presence rule.

    python3 tools/puzzle_schema.py              # every puzzles/<series>/<year>/*.json, the enums and the blog facts
    python3 tools/puzzle_schema.py cryptic-30066 times-29001

The same file's $defs/blogFacts is the shape of each row of
tools/data/blog_facts/<series>.json, checked by the no-argument run too.

The rule: an absent key means empty. No puzzle file holds null, "", [] or {}
as a value, except `clue`, which every entry has and which is "" on a clue the
paper printed blank (`clueMissing`). prune() is how every write obeys it:
fetch_puzzle.write_puzzle_file calls it, so a fetcher or an annotation that
hands over `"setter": None` or `"indicators": []` writes no key at all.

The schema is JSON Schema 2020-12, checked here by a small validator for the
keywords the file uses; a keyword it does not know is an error, so the file
cannot come to say more than this checks. Its enums are copies of the lists in
series.py, clue_types.json, provenance.py and validate_annotations.py, and
check_enums() fails when a copy and its source disagree.
"""

import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
SCHEMA_PATH = TOOLS / "data" / "puzzle.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

# Written even when empty: every entry has a clue, and "" is what a blank one is.
KEEP_EMPTY = frozenset({"clue"})


def is_empty(v):
    return v is None or v == "" or v == [] or v == {}


def prune(value):
    """`value` with every null or empty object value removed, depth first, so
    an object left empty by its own pruning goes too. List items are kept."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            v = prune(v)
            if k in KEEP_EMPTY or not is_empty(v):
                out[k] = v
        return out
    if isinstance(value, list):
        return [prune(v) for v in value]
    return value


# ------------------------------------------------------------- the validator

ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "$defs"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool,
         "null": type(None)}


def _is(v, t):
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, TYPES[t])


def _resolve(ref):
    if not ref.startswith("#/"):
        raise ValueError(f"only local $refs are supported, got {ref!r}")
    node = SCHEMA
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _check(v, s, at, out):
    unknown = set(s) - ANNOTATIONS - set(KEYWORDS)
    if unknown:
        raise ValueError(f"schema at {at}: keyword(s) {sorted(unknown)} are not "
                         f"implemented by tools/puzzle_schema.py")
    for kw, arg in s.items():
        if kw in KEYWORDS:
            KEYWORDS[kw](v, arg, s, at, out)


def _type(v, arg, s, at, out):
    ts = arg if isinstance(arg, list) else [arg]
    if not any(_is(v, t) for t in ts):
        out.append(f"{at}: {json.dumps(v, ensure_ascii=False)[:60]} is not {' or '.join(ts)}")


def _typed(t):
    """A keyword body that applies only to values of JSON type t, as the spec says."""
    def wrap(fn):
        return lambda v, arg, s, at, out: fn(v, arg, s, at, out) if _is(v, t) else None
    return wrap


@_typed("object")
def _properties(v, arg, s, at, out):
    for k, sub in arg.items():
        if k in v:
            _check(v[k], sub, f"{at}.{k}", out)


@_typed("object")
def _required(v, arg, s, at, out):
    for k in arg:
        if k not in v:
            out.append(f"{at}: missing required key {k!r}")


@_typed("object")
def _additional(v, arg, s, at, out):
    known = set(s.get("properties", {}))
    for k in v:
        if k in known:
            continue
        if arg is False:
            out.append(f"{at}: key {k!r} is not in the schema")
        elif isinstance(arg, dict):
            _check(v[k], arg, f"{at}.{k}", out)


@_typed("object")
def _min_properties(v, arg, s, at, out):
    if len(v) < arg:
        out.append(f"{at}: empty object — leave the key out instead")


@_typed("array")
def _items(v, arg, s, at, out):
    for i, x in enumerate(v):
        _check(x, arg, f"{at}[{i}]", out)


@_typed("array")
def _min_items(v, arg, s, at, out):
    if len(v) < arg:
        out.append(f"{at}: {len(v)} item(s), want at least {arg}"
                   + (" — leave the key out instead" if not v else ""))


@_typed("array")
def _max_items(v, arg, s, at, out):
    if len(v) > arg:
        out.append(f"{at}: {len(v)} items, want at most {arg}")


@_typed("array")
def _unique(v, arg, s, at, out):
    if arg and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
        out.append(f"{at}: repeats an item")


@_typed("string")
def _min_length(v, arg, s, at, out):
    if len(v) < arg:
        out.append(f"{at}: empty string — leave the key out instead")


@_typed("string")
def _pattern(v, arg, s, at, out):
    if not re.search(arg, v):
        out.append(f"{at}: {v!r} does not match {arg}")


def _minimum(v, arg, s, at, out):
    if _is(v, "number") and v < arg:
        out.append(f"{at}: {v} is below {arg}")


def _maximum(v, arg, s, at, out):
    if _is(v, "number") and v > arg:
        out.append(f"{at}: {v} is above {arg}")


def _enum(v, arg, s, at, out):
    if v not in arg or (isinstance(v, bool) and not any(x is v for x in arg)):
        shown = ", ".join(map(str, arg[:8])) + (", ..." if len(arg) > 8 else "")
        out.append(f"{at}: {json.dumps(v, ensure_ascii=False)[:60]} is not one of {shown}")


def _const(v, arg, s, at, out):
    if v != arg or type(v) is not type(arg):
        out.append(f"{at}: {json.dumps(v)[:60]} must be {json.dumps(arg)}"
                   + (" — leave the key out instead" if arg is True and v is False else ""))


def _ref(v, arg, s, at, out):
    _check(v, _resolve(arg), at, out)


def _any_of(v, arg, s, at, out):
    tries = []
    for sub in arg:
        got = []
        _check(v, sub, at, got)
        if not got:
            return
        tries.append(got)
    out.append(f"{at}: matches none of its alternatives: "
               + " | ".join("; ".join(t) for t in tries))


def _one_of(v, arg, s, at, out):
    tries = []
    for sub in arg:
        got = []
        _check(v, sub, at, got)
        tries.append(got)
    matched = sum(not t for t in tries)
    if matched == 1:
        return
    if matched:
        both = [sub for sub, t in zip(arg, tries) if not t]
        out.append(f"{at}: matches {json.dumps(both)[:120]}, want exactly one")
    else:
        out.append(f"{at}: matches none of its alternatives: "
                   + " | ".join("; ".join(t) for t in tries))


def _if(v, arg, s, at, out):
    probe = []
    _check(v, arg, at, probe)
    branch = s.get("else") if probe else s.get("then")
    if branch is not None:
        _check(v, branch, at, out)


KEYWORDS = {
    "type": _type, "properties": _properties, "required": _required,
    "additionalProperties": _additional, "minProperties": _min_properties,
    "items": _items, "minItems": _min_items, "maxItems": _max_items,
    "uniqueItems": _unique, "minLength": _min_length, "pattern": _pattern,
    "minimum": _minimum, "maximum": _maximum, "enum": _enum, "const": _const,
    "$ref": _ref, "anyOf": _any_of, "oneOf": _one_of, "if": _if,
    "then": lambda *a: None, "else": lambda *a: None,   # read by _if
}


def validate(puzzle):
    """Every way `puzzle` departs from the schema, as 'path: problem' strings."""
    out = []
    _check(puzzle, SCHEMA, "$", out)
    return out


# ------------------------------------------------------ enums and their sources

def enum_sources():
    """$defs name -> the list that $defs entry's enum must equal."""
    import clue_types
    import fetch_puzzle
    import provenance
    import series
    import validate_annotations
    return {
        "series": list(series.SERIES),
        "direction": list(fetch_puzzle.DIRECTIONS),
        "clueType": list(clue_types.NAMES),
        "selectWord": list(clue_types.SELECT_WORDS),
        "joke": list(validate_annotations.JOKE_KINDS),
        "acquiredBy": list(provenance.ACQUIRED_BY),
        "retrievedFrom": list(provenance.RETRIEVAL_CHANNELS),
        "gridOrigin": list(provenance.GRID_ORIGINS),
        "solutionOrigin": list(provenance.SOLUTION_ORIGINS),
        "annotator": list(provenance.ANNOTATORS),
        "blog": list(provenance.WRITEUP_KINDS),
    }


def check_enums():
    problems = []
    for name, want in enum_sources().items():
        got = SCHEMA["$defs"].get(name, {}).get("enum")
        if got != want:
            problems.append(f"$defs/{name} enum is {got} but its source says {want} — "
                            f"copy the source's list into {SCHEMA_PATH.name}")
    return problems


BLOG_FACTS = TOOLS / "data" / "blog_facts"


def validate_blog_facts(row):
    """Every way one puzzle's row of tools/data/blog_facts/ departs from $defs/blogFacts."""
    out = []
    _check(row, {"$ref": "#/$defs/blogFacts"}, "$", out)
    return out


def _check_blog_file(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return Path(path).name, {pid: p for pid, row in rows.items() if (p := validate_blog_facts(row))}


def _check_file(path):
    puzzle = json.loads(Path(path).read_text(encoding="utf-8"))
    return Path(path).stem, validate(puzzle)


def main(argv):
    import fetch_puzzle
    paths = ([fetch_puzzle.resolve_puzzle(a) for a in argv] if argv
             else list(fetch_puzzle.puzzle_files()))
    failed = 0
    for problem in check_enums():
        print(f"ENUM {problem}")
        failed += 1
    with ProcessPoolExecutor() as pool:
        for pid, problems in pool.map(_check_file, map(str, paths), chunksize=64):
            if problems:
                failed += 1
                shown = problems[:5] + ([f"... {len(problems) - 5} more"]
                                        if len(problems) > 5 else [])
                print(f"{pid}: " + "; ".join(shown))
        blog_files = [] if argv else sorted(map(str, BLOG_FACTS.glob("*.json")))
        for name, bad in pool.map(_check_blog_file, blog_files):
            for pid, problems in bad.items():
                failed += 1
                print(f"{name} {pid}: " + "; ".join(problems[:5]))
    if failed:
        print(f"puzzle schema: {failed} failure(s) over {len(paths)} puzzle(s) "
              f"— tools/data/puzzle.schema.json says what the shape is")
        return 1
    print(f"puzzle schema: {len(paths)} puzzle(s) and {len(blog_files)} blog facts file(s) "
          f"match tools/data/puzzle.schema.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
