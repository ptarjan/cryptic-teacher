#!/usr/bin/env python3
"""The puzzle file's shape: tools/data/puzzle.schema.json, and the one presence rule.

    python3 tools/puzzle_schema.py              # every puzzles/<series>/<year>/*.json, the clues-only files, the enums and the blog facts
    python3 tools/puzzle_schema.py cryptic-30066 times-29001

The same file's $defs/blogFacts is the shape of each row of
tools/data/blog_facts/<series>.json, checked by the no-argument run too.

Key order is the schema's: every object's keys come in its `properties`
order, so two files with the same content are the same bytes and a reader
finds `type` before `blocks` in every annotation. order() is how every write
obeys it (write_puzzle_file, the blog facts writers), and the validator
refuses a file whose keys are out of that order.

The rule: an absent key means empty. No puzzle file holds null, "", [] or {}
as a value; a clue the paper printed blank is `"clue": {"missing": true}`.
prune() is how every write obeys it:
fetch_puzzle.write_puzzle_file calls it, so a fetcher or an annotation that
hands over `"setter": None` or `"indicators": []` writes no key at all.

The schema is JSON Schema 2020-12, checked here by a small validator for the
keywords the file uses; a keyword it does not know is an error, so the file
cannot come to say more than this checks. Its enums are copies of the lists in
series.py, clue_types.json, fetch_puzzle.py, provenance.py, puzzle_integrity.py
and validate_annotations.py, and
check_enums() fails when a copy and its source disagree.
"""

import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
SCHEMA_PATH = TOOLS / "data" / "puzzle.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

def is_empty(v):
    return v is None or v == "" or v == [] or v == {}


def prune(value):
    """`value` with every null or empty object value removed, depth first, so
    an object left empty by its own pruning goes too. List items are kept."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            v = prune(v)
            if not is_empty(v):
                out[k] = v
        return out
    if isinstance(value, list):
        return [prune(v) for v in value]
    return value


def _properties_of(schema):
    """The `properties` an object under `schema` is keyed by, following $refs."""
    while "$ref" in schema and "properties" not in schema:
        schema = _resolve(schema["$ref"])
    return schema


def order(value, ref="#"):
    """`value` with every object's keys in its schema's `properties` order,
    depth first. Keys the schema does not list (a map such as a blog facts
    row's `entries`) keep their order, after the listed ones."""
    return _order(value, _resolve(ref) if ref != "#" else SCHEMA)


def _order(value, schema):
    schema = _properties_of(schema)
    if isinstance(value, dict):
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        out = {k: _order(value[k], props[k]) for k in props if k in value}
        for k, v in value.items():
            if k not in props:
                out[k] = _order(v, extra) if isinstance(extra, dict) else v
        return out
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_order(v, schema["items"]) for v in value]
    return value


# ------------------------------------------------------------- the validator

# `refused` is this file's own: {key: why} beside additionalProperties: false,
# so a key the schema leaves out on purpose (a derived field) says why it is
# refused instead of only that it is unknown.
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "$defs", "refused"}
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


_PLANS = {}     # id(schema node) -> (node, [(keyword fn, arg)]): a node is read once


def _plan(s, at):
    hit = _PLANS.get(id(s))
    if hit is None or hit[0] is not s:
        unknown = set(s) - ANNOTATIONS - set(KEYWORDS)
        if unknown:
            raise ValueError(f"schema at {at}: keyword(s) {sorted(unknown)} are not "
                             f"implemented by tools/puzzle_schema.py")
        hit = _PLANS[id(s)] = (s, [(KEYWORDS[kw], arg) for kw, arg in s.items() if kw in KEYWORDS])
    return hit[1]


def _check(v, s, at, out):
    for fn, arg in _plan(s, at):
        fn(v, arg, s, at, out)


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
    got = [k for k in v if k in arg]
    want = [k for k in arg if k in v]
    if got != want:
        out.append(f"{at}: keys in the order {', '.join(got)}; the schema's order is "
                   f"{', '.join(want)} (puzzle_schema.order() writes it)")


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
        if arg is False and k in s.get("refused", {}):
            out.append(f"{at}: key {k!r} is refused: {s['refused'][k]}")
        elif arg is False:
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
    return out + format_problems(puzzle)


# ------------------------------------------------------ derived fields
# The format (docs/PUZZLE_FORMAT.md "Design principles") stores no field that
# can be derived from others; the JSON Schema's `refused` lists name most of
# them, and format_problems() the ones only Python can see.

NAME_KEYS = ("prize", "title", "label")


def annotations(puzzle):
    """(path, holder entry, annotation) for every annotation in the puzzle:
    each entry's, each alsoLeads item's (seen as its light's own clue and
    group, as groups.as_leader does) and each offGrid clue's."""
    for i, e in enumerate(puzzle.get("entries") or []):
        if not isinstance(e, dict):
            continue
        if isinstance(e.get("annotation"), dict):
            yield f"$.entries[{i}].annotation", e, e["annotation"]
        for k, item in enumerate(e.get("alsoLeads") or []):
            if isinstance(item, dict) and isinstance(item.get("annotation"), dict):
                held = {**{x: v for x, v in e.items() if x not in ("alsoLeads", "annotation")}, **item}
                yield f"$.entries[{i}].alsoLeads[{k}].annotation", held, item["annotation"]
    for k, item in enumerate(puzzle.get("offGrid") or []):
        if isinstance(item, dict) and isinstance(item.get("annotation"), dict):
            yield (f"$.offGrid[{k}].annotation", {"number": k + 1, "direction": "offgrid", **item},
                   item["annotation"])


def format_problems(puzzle):
    """The derived fields only Python can see: a `spelling` equal to the
    display answer the entry already gives."""
    import annotation
    out = []
    if not isinstance(puzzle, dict):
        return out
    for at, held, ann in annotations(puzzle):
        if "spelling" in ann and held.get("solution"):
            try:
                derived = annotation.display_answer(held, puzzle)
            except (KeyError, TypeError):
                continue
            if ann["spelling"] == derived:
                out.append(f"{at}.spelling: {ann['spelling']!r} is the solution spaced by its "
                           f"enumeration, which annotation.view() derives; leave `spelling` out")
    return out


# ------------------------------------------------------ enums and their sources

def enum_sources():
    """$defs name -> the list that $defs entry's enum must equal."""
    import clue_types
    import fetch_puzzle
    import hidden_messages
    import provenance
    import puzzle_integrity
    import series
    import validate_annotations
    import wordplay
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
        "alterationOp": list(puzzle_integrity.ALTERATION_OPS),
        "hiddenLetterKind": list(hidden_messages.KINDS),
        "blog": list(provenance.WRITEUP_KINDS),
        "wordplayOp": sorted(set(wordplay.OPS.values()) | {"charade"}),
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
# A puzzle held as its clues alone (tools/clues_only.py): its own shape.
CLUES_ONLY = "#/$defs/cluesOnly"


def validate_clues_only(record):
    """Every way a clues_only/ file departs from $defs/cluesOnly."""
    out = []
    _check(record, {"$ref": CLUES_ONLY}, "$", out)
    return out


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
    # A clues_only/ path is checked against its own shape; anything else names a puzzle.
    clue_paths = [Path(a) for a in argv if Path(a).parts[:1] == ("clues_only",)]
    argv = [a for a in argv if Path(a).parts[:1] != ("clues_only",)]
    paths = ([fetch_puzzle.resolve_puzzle(a) for a in argv] if argv
             else [] if clue_paths else list(fetch_puzzle.puzzle_files()))
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
        if not argv and not clue_paths:
            import clues_only
            clue_paths = clues_only.files()
        for path in clue_paths:
            problems = validate_clues_only(json.loads(path.read_text(encoding="utf-8")))
            if problems:
                failed += 1
                print(f"clues-only {path.stem}: " + "; ".join(problems[:5]))
        blog_files = [] if argv or clue_paths else sorted(map(str, BLOG_FACTS.glob("*.json")))
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
