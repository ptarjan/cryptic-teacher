#!/usr/bin/env python3
# Does puzzle_integrity catch every kind of defect it claims to, and do its two
# exception tables forgive exactly the findings they name, and nothing else?
#
#     python3 tests/test_puzzle_integrity.py
#
# This tests the CHECKER, on fixtures: real puzzles copied into memory or into
# a scratch puzzles/ directory and mutated there, so it runs in seconds and
# never writes under the repo's puzzles/. Whether the corpus itself is clean is
# a different question, answered by running the checker over all of it:
#
#     python3 tools/puzzle_integrity.py --quiet
#
# CI runs that once, as its own step, not here.
#
# Every flag in puzzle_integrity.FLAGS, plus DUPLICATE, has a fixture below
# that raises it and only it (a DUPLICATE shares every clue, so NEARDUP comes
# with it); the test fails if FLAGS grows a kind that has no fixture here.
#
# PUBLISHED_WRONG and UNLINKED_IN_SOURCE are keyed by (puzzle id, whole finding
# string), so that forgiving one sentence forgives nothing else about that
# clue. The property under test: lengthening every key's finding string by one
# trailing space must reproduce every finding the tables forgive, since a
# prefix or substring match would still swallow some of them. Both tables are
# checked separately, with their sizes read off len(), so a key that no longer
# matches a live finding fails the run. Every key names its puzzle, so only the
# puzzles the tables name are read for this.
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))
scratch = Path(tempfile.mkdtemp())
fails = 0


def run_block(fn, merge=True, **env):
    """Run fn in a forked child, as the old python3 heredoc was its own process.

    Returns (output, exit code); the child's stderr joins its output if merge."""
    with tempfile.TemporaryFile("w+") as cap:
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            code = 0
            try:
                os.environ.update(env)
                sys.stdout = open(cap.fileno(), "w", closefd=False)
                if merge:
                    sys.stderr = sys.stdout
                fn()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
                if isinstance(e.code, str):
                    print(e.code, file=sys.stderr)
            except BaseException:
                traceback.print_exc()
                code = 1
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(code)
        _, status = os.waitpid(pid, 0)
        cap.seek(0)
        return cap.read(), os.waitstatus_to_exitcode(status)


def check(out, wanted, what):
    global fails
    if wanted in out:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    wanted to find: {wanted}\n    in: {out}")
        fails += 1


def absent(out, unwanted, what):
    global fails
    if unwanted in out:
        print(f"  FAIL: {what}\n    did not want to find: {unwanted}\n    in: {out}")
        fails += 1
    else:
        print(f"  ok: {what}")


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want}\n    got  {got}")
        fails += 1


def field(key, out):
    """awk '$1==key {print $2}' over out, as a command substitution gives it."""
    return "\n".join((l.split()[1] if len(l.split()) > 1 else "")
                     for l in out.splitlines() if l.split() and l.split()[0] == key).rstrip("\n")


def awk(out, key, *cols, rest=False):
    """awk '$1==key {print $col ...}' (rest: everything after $1, as substr($0, 2) once $1 is blanked);
    a first-column match on the extra arg `cols` ending in a str also requires $2 to equal it."""
    want = None
    if cols and isinstance(cols[-1], str):
        *cols, want = cols
    res = []
    for line in out.splitlines():
        f = line.split()
        if not f or f[0] != key or (want is not None and (len(f) < 2 or f[1] != want)):
            continue
        if rest:
            res.append(line.split(None, 1)[1] if len(f) > 1 else "")
        else:
            res.append(" ".join(f[c - 1] if len(f) >= c else "" for c in cols).rstrip(" ") if len(cols) == 1
                       else " ".join(f[c - 1] if len(f) >= c else "" for c in cols))
    return "\n".join(res).rstrip("\n")


def grep(pattern, out):
    return "\n".join(l for l in out.splitlines() if re.search(pattern, l))


def grep_c(pattern, text):
    return str(sum(1 for l in text.splitlines() if re.search(pattern, l)))


def cut_f2(text):
    """cut -d' ' -f2- on each line."""
    return "\n".join(l.split(" ", 1)[1] if " " in l else l for l in text.splitlines())


def died(out, what):
    """A block that died prints no fields, and empty fields say nothing of why."""
    global fails
    if re.search(r"^Traceback", out, re.M):
        print(f"  FAIL: {what} crashed:")
        print("\n".join("    " + l for l in out.splitlines()))
        fails += 1



def block_out1():
    import copy
    from datetime import date
    import puzzle_integrity as pi
    from groups import entry_id

    TODAY = date(2026, 10, 5)
    # cryptic-24104 holds two findings UNLINKED_IN_SOURCE forgives, so every
    # mutation below also proves forgiving them does not blank out the rest of it.
    # cryptic-24447 holds the corpus's three-plus-light group ALL AND SUN DRY.
    # times-29329 is annotated, so its clue can be edited out from under its annotation.
    # times-15602 is an OCR (newspaper) file, for the checks only those get.
    base = {pid: pi.read_puzzle_file(pi.puzzle_paths.find(pid))
            for pid in ("cryptic-24104", "cryptic-24447", "times-29329", "times-15602")}


    def kinds(pid, mutate=None):
        p = copy.deepcopy(base[pid])
        if mutate:
            mutate(p, {entry_id(e): e for e in p["entries"]})
        flags = []
        pi.check_puzzle(p, TODAY, flags)
        return ",".join(sorted({f[0] for f in flags})) or "none"


    def reorder(p, by):
        g = by["13-across"]["group"]
        by["13-across"]["group"] = [g[0]] + g[1:][::-1]


    def alter(p, by):
        p["preamble"] = "Some answers are altered."
        by["2-down"]["alteration"] = {"from": "YANKS", "steps": [{"op": "anagram"}]}


    def off_board(p, by):
        # Unanswered, so the shifted light breaks no crossing: GRID alone.
        by["1-across"]["position"]["x"] = 1
        del by["1-across"]["solution"]


    MUTATIONS = {
        "LENGTH": ("cryptic-24104", lambda p, by: by["1-across"]["clue"].update(enumeration="3,4,2,1,6")),
        "ORDER": ("cryptic-24447", reorder),
        "APOSTROPHE": ("cryptic-24104", lambda p, by: by["1-across"]["clue"].update(enumeration="3,4,2,1'5")),
        "CROSS": ("cryptic-24104", lambda p, by: by["1-across"].update(solution="Z" + by["1-across"]["solution"][1:])),
        "CELLS": ("cryptic-24104", lambda p, by: p.update(printed=[{"x": 0, "y": 0, "letter": "Z"}])),
        "ALTERED": ("cryptic-24104", alter),
        "GRID": ("cryptic-24104", off_board),
        "NUMBER": ("cryptic-24104", lambda p, by: by["30-across"].update(number=31)),
        "SETTER": ("cryptic-24104", lambda p, by: p.update(setter="Unknown")),
        "SHAPE": ("cryptic-24104", lambda p, by: by["2-down"]["clue"].update(text="")),
        "PROV": ("cryptic-24104", lambda p, by: p["solutions"].update(origin="bogus")),
        # The clue cleaned in place and its annotation left quoting the old words.
        # A known copy of another puzzle, filed under its own id.
        "REPRINT": ("cryptic-24104", lambda p, by: p["source"].update(reprintOf="times-1")),
        # An OCR channel's ";" whose counts fill the light: a misread "," (7D's
        # count as the scan read it).
        "COUNT": ("times-15602", lambda p, by: by["7-down"]["clue"].update(enumeration="6;3")),
        "CURLY": ("cryptic-24104", lambda p, by: by["2-down"]["clue"].update(
            text=by["2-down"]["clue"]["text"] + " \u2018it\u2019s\u2019 of\ufb01ce")),
        "DASH": ("cryptic-24104", lambda p, by: by["2-down"]["clue"].update(
            text=by["2-down"]["clue"]["text"] + " -- or not...")),
        # An OCR clue with a speck read as a quote and its number leaked after it.
        "LEAD": ("times-15602", lambda p, by: by["7-down"]["clue"].update(
            text='"7 ' + by["7-down"]["clue"]["text"])),
        "QUOTE": ("times-29329", lambda p, by: by["20-down"]["clue"].update(
            text=by["20-down"]["clue"]["text"].replace("Dip ", "Plunge "))),
    }
    for pid in base:
        print("PRISTINE", pid, kinds(pid))
    for flag, (pid, mutate) in MUTATIONS.items():
        print("FLAG", flag, kinds(pid, mutate))
    # DATE, FILED and NEARDUP are cross-file; the CLI section below raises them.
    print("UNCOVERED", ",".join(sorted(set(pi.FLAGS) - set(MUTATIONS) - {"DATE", "FILED", "NEARDUP"})) or "none")

def block_out_pre():
    import copy
    from datetime import date
    import puzzle_integrity as pi

    real = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104"))
    for name, pre in (("BARE", None), ("WITH", "1 Across is unclued.")):
        p = copy.deepcopy(real)
        p["entries"][0]["clue"]["text"] = "See preamble"
        if pre:
            p["preamble"] = pre
        flags = []
        pi.check_puzzle(p, date(2026, 10, 5), flags)
        print(name, pi.awaits_preamble(p), any("preamble" in f[2] for f in flags))
    try:
        p = copy.deepcopy(real)
        p["entries"][0]["clue"]["text"] = "Unclued (see the preamble)"
        pi.refuse_bad_write(p)
        print("WRITE allowed")
        print("INDEXED", pi.awaits_preamble(p))
    except pi.RefusedWrite as e:
        print("WRITE", f"refused: {e}")
    for name, slug in (("SPECIAL", "playfair"), ("PLAIN", "plain-christmas"), ("COMP", "plain-competition-puzzle"),
                       ("BARENUM", "")):
        p = copy.deepcopy(real)
        p["series"] = "azed"
        p["source"]["url"] = f"https://fifteensquared.net/2021/08/22/azed-no-2566{'-' + slug if slug else ''}/"
        print(name, pi.awaits_preamble(p))

def block_out_cover():
    import copy
    from datetime import date, timedelta
    import puzzle_integrity as pi
    import series

    today = date(2026, 10, 14)
    for name, pid, ahead in (("TLS2", "tls-1620", 2), ("TLSLEAD", "tls-1620", series.cover_date_lead("tls")),
                             ("TLSPAST", "tls-1620", series.cover_date_lead("tls") + 1),
                             ("DAILY1", "cryptic-24104", 1)):
        p = copy.deepcopy(pi.read_puzzle_file(pi.puzzle_paths.find(pid)))
        p["date"] = (today + timedelta(days=ahead)).isoformat()
        flags = []
        pi.check_shape(p, today, flags)
        print(name, any("in the future" in f[2] for f in flags))
    print("LISTENER", series.cover_date_lead("listener"))

def block_out_await():
    import copy, json, os
    from datetime import date
    from pathlib import Path
    import await_preamble
    import fetch_puzzle
    import puzzle_integrity as pi
    import puzzle_paths

    path = puzzle_paths.find("cryptic-24319")
    real = pi.read_puzzle_file(path)
    bare = copy.deepcopy(real)
    del bare["preamble"]
    print("WHICH", "-".join(await_preamble.which(path, bare)) or "none")
    print("HELD", "-".join(await_preamble.which(path, real)) or "none")
    other = copy.deepcopy(bare)
    broken = next(e for e in other["entries"] if e.get("annotation")
                  and not e["annotation"].get("definedByPreamble"))
    broken["annotation"]["wordplay"] = {"words": broken["clue"]["text"].split()[0]}
    print("OTHER", "-".join(await_preamble.which(path, other)) or "none")
    supplied = copy.deepcopy(bare)
    for e in supplied["entries"]:
        if (e.get("annotation") or {}).pop("definedByPreamble", None):
            e["annotation"]["wordplay"] = {"gives": e["solution"]}
    print("SUPPLIED", "-".join(await_preamble.left_to_preamble(supplied)) or "none")
    flagged = dict(bare, awaitsPreamble=True)
    print("FLAGGED", pi.awaits_preamble(flagged))
    print("ARRIVED", pi.awaits_preamble(dict(flagged, preamble="Unclued answers are birds.")))
    flags = []
    pi.check_puzzle(dict(flagged, preamble="Unclued answers are birds."), date(2026, 10, 10), flags)
    print("BESIDE", any("awaitsPreamble beside" in f[2] for f in flags))
    out = Path(os.environ["SCRATCH"]) / f"{real['id']}.json"
    out.parent.mkdir(parents=True)
    fetch_puzzle.write_puzzle_file(out, copy.deepcopy(flagged))
    fetch_puzzle.write_puzzle_file(out, copy.deepcopy(bare))
    print("KEPT", json.loads(out.read_text()).get("awaitsPreamble"))
    fetch_puzzle.write_puzzle_file(out, dict(copy.deepcopy(flagged), preamble="Unclued answers are birds."))
    print("DROPPED", "awaitsPreamble" not in json.loads(out.read_text()))

def block_out2():
    import contextlib, copy, io, json, os, re
    from datetime import date, timedelta
    from pathlib import Path
    import puzzle_integrity as pi
    import puzzle_paths

    real = pi.read_puzzle_file(puzzle_paths.find("cryptic-24447"))
    root = Path(os.environ["SCRATCH"])
    puzzle_paths.PUZZLE_DIR = root / "puzzles"
    pi.CACHE = root / "integrity-rows.pickle"
    puzzle_paths.PUZZLE_DIR.mkdir(parents=True)


    def put(p):
        path = puzzle_paths.file_for(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(p))
        return path


    def sibling(day, same_clues=0):
        """cryptic-24448 on `day`; its first `same_clues` clues are 24447's, the
        rest made its own."""
        p = copy.deepcopy(real)
        p.update(id="cryptic-24448", number=24448, date=day)
        p["source"]["url"] = p["source"]["url"].replace("24447", "24448")
        for i, e in enumerate(p["entries"]):
            if i >= same_clues and e["clue"].get("text"):
                e["clue"]["text"] = f"Other {i} " + e["clue"]["text"]
        return p


    def cli(name):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = pi.main([])
        text = out.getvalue()
        tallies = {m[0]: int(m[1]) for m in re.findall(r"^  (\w+) +(\d+)", text, re.M)}
        raised = ",".join(sorted(k for k, n in tallies.items() if n)) or "none"
        print(name, rc, raised)


    put(real)
    day = date.fromisoformat(real["date"])
    later, earlier = str(day + timedelta(days=7)), str(day - timedelta(days=7))
    for name, p in [("CLEAN", sibling(later)),
                    ("DATE", sibling(earlier)),
                    ("NEARDUP", sibling(later, same_clues=len(real["entries"]) - 1)),
                    ("DUPLICATE", sibling(later, same_clues=len(real["entries"])))]:
        path = put(p)
        cli(name)
        print("REFUSED", name, [Path(k).name for k in pi.refused([str(path)], date.today())])
        path.unlink()
    # The same copy, listed in clue_index.REPRINTS: one puzzle the paper printed twice.
    import clue_index
    clue_index.REPRINTS[frozenset(("cryptic-24447", "cryptic-24448"))] = "fixture"
    path = put(sibling(later, same_clues=len(real["entries"])))
    cli("REPRINT")
    path.unlink()

def block_combo():
    from datetime import datetime, timezone
    import puzzle_integrity as pi

    today = datetime.now(timezone.utc).date()

    # Every key names its puzzle, so the puzzles the tables name are the only
    # ones whose findings the tables can change. check_shape reads neither table,
    # so it runs once per puzzle; every variant below reruns the rest in memory.
    # A key naming a puzzle not filed yet is puzzle_integrity's FILED finding
    # (check_table_ids, tested below), not this check's: its rows are left out.
    named = sorted({pid for pid, _ in [*pi.PUBLISHED_WRONG, *pi.UNLINKED_IN_SOURCE]
                    if pi.puzzle_paths.find(pid)})
    pi.PUBLISHED_WRONG = {k: v for k, v in pi.PUBLISHED_WRONG.items() if k[0] in named}
    pi.UNLINKED_IN_SOURCE = {k: v for k, v in pi.UNLINKED_IN_SOURCE.items() if k[0] in named}
    cache = []
    for pid in named:
        puzzle = pi.read_puzzle_file(pi.puzzle_paths.find(pid))
        cache.append((puzzle, pi.check_shape(puzzle, today, [])))

    def length_count():
        # Every check that consults the tables, so a dropped key shows up in this
        # total whichever check would have produced its finding. The counts below
        # are read off len(table), so a check left out here reads as keys that
        # forgive nothing and fails the run.
        flags = []
        for puzzle, checkable in cache:
            pi.check_length(puzzle, checkable, flags)
            pi.check_grid(puzzle, flags)
            pi.check_numbering(puzzle, flags)
            pi.check_cross(puzzle, checkable, flags)
        return len(flags)

    orig_pw = dict(pi.PUBLISHED_WRONG)
    orig_uis = dict(pi.UNLINKED_IN_SOURCE)
    print("TABLE_SIZES", len(orig_pw), len(orig_uis))
    print("BASELINE", length_count())

    def lengthen(table):
        # One trailing space on every finding string. A prefix or substring match
        # would still find the original text inside this and stay silent; an exact
        # match cannot, and the finding must reappear.
        return {(pid, finding + " "): note for (pid, finding), note in table.items()}

    pi.PUBLISHED_WRONG = lengthen(orig_pw)
    pi.UNLINKED_IN_SOURCE = lengthen(orig_uis)
    print("LENGTHENED_BOTH", length_count())
    pi.PUBLISHED_WRONG, pi.UNLINKED_IN_SOURCE = orig_pw, orig_uis

    pi.PUBLISHED_WRONG = {}
    print("DROP_PUBLISHED_WRONG", length_count())
    pi.PUBLISHED_WRONG = orig_pw

    pi.UNLINKED_IN_SOURCE = {}
    print("DROP_UNLINKED_IN_SOURCE", length_count())
    pi.UNLINKED_IN_SOURCE = orig_uis

    print("RESTORED", length_count())

def block_unheld():
    import puzzle_integrity as pi

    named = {pid for pid, _ in [*pi.PUBLISHED_WRONG, *pi.UNLINKED_IN_SOURCE]}
    held = {pid for pid in named if pi.puzzle_paths.find(pid)}
    flags = []
    pi.check_table_ids(held, flags)
    print("ALL_HELD", len(flags), *(p for _, p, _ in flags))
    pi.PUBLISHED_WRONG = {**pi.PUBLISHED_WRONG, ("genius-99999", "1-across: anything"): "ahead of its file"}
    flags = []
    pi.check_table_ids(held, flags)
    print("UNHELD", len(flags), *(f"{f}:{p}" for f, p, _ in flags))

def block_out3():
    import copy
    from datetime import datetime, timezone
    import puzzle_integrity as pi
    from groups import entry_id

    today = datetime.now(timezone.utc).date()
    path = pi.puzzle_paths.find("cryptic-24104")
    puzzle = copy.deepcopy(pi.read_puzzle_file(path))
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    target = by_id["1-across"]
    assert target.get("solution"), "fixture assumption broken: 1-across has no solution"
    # A grid-length mismatch is checked and flagged before either exception table
    # is even consulted (see check_length), so no baseline could ever suppress it
    # -- exactly the kind of unrelated defect that must still surface next to the
    # two findings cryptic-24104 already has baselined (13-across and 16-down).
    target["length"] = target["length"] + 1

    flags = []
    checkable = pi.check_shape(puzzle, today, flags)
    pi.check_length(puzzle, checkable, flags)
    findings = [f[2] for f in flags if f[0] == "LENGTH"]
    print("TOTAL", len(findings))
    print("NEW_DEFECT", any(f.startswith("1-across:") for f in findings))
    print("PAIR_SILENT", not any(f.startswith("13-across:") or f.startswith("16-down:")
                                  for f in findings))

def block_out4():
    import copy
    from datetime import datetime, timezone
    import puzzle_integrity as pi

    today = datetime.now(timezone.utc).date()
    # A real puzzle, so the fixture cannot drift out of the shape the checker reads.
    # clue.missing on every entry is the state the 2005-2008 Saturday prize puzzles are
    # in: answers scraped, clue text never fetched. Per-entry forgiveness finds nothing
    # wrong with any single one of them, which is the whole reason the puzzle is asked.
    puzzle = copy.deepcopy(pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104")))


    def blank(p, entries):
        for e in entries:
            e["clue"] = {"enumeration": str(e["length"]), "missing": True}
        flags = []
        pi.check_shape(p, today, flags)
        return [f[2] for f in flags if "blank" in f[2]]


    one = copy.deepcopy(puzzle)
    print("ONE_BLANK", len(blank(one, one["entries"][:1])))
    whole = copy.deepcopy(puzzle)
    found = blank(whole, whole["entries"])
    print("ALL_BLANK", len(found))
    print("BLANK_SAYS", found == [f"all {len(whole['entries'])} clues are blank"])

def block_out5():
    import copy
    import puzzle_integrity as pi
    from apply_solution import check_geometry
    from groups import entry_id

    # A real 15x15, so the fixture cannot drift out of the shape the checker reads.
    puzzle = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104"))
    print("PRISTINE", len(check_geometry(puzzle)))

    # 1-across is 15 cells of a 15-wide grid. Shifted one column right it is the
    # same light, still crossing everything, and no longer on the board.
    off = copy.deepcopy(puzzle)
    by_id = {entry_id(e): e for e in off["entries"]}
    assert by_id["1-across"]["length"] == off["dimensions"]["cols"], "fixture assumption broken"
    by_id["1-across"]["position"]["x"] = 1
    found = check_geometry(off)
    print("OFFBOARD", len(found))
    print("OFFBOARD_SAYS", found == ["1-across: 15 cells across from (1,0) runs off a 15x15 grid"])

    # No exception table forgives it, and the write path refuses it: a light off
    # the board is a cell no reader can draw, whatever a note says about why.
    pi.PUBLISHED_WRONG[(off["id"], found[0])] = "a note cannot put a cell on the board"
    flags = []
    pi.check_grid(off, flags)
    print("FORGIVEN_STILL_FLAGS", [w for _, _, w in flags] == found)
    try:
        pi.refuse_bad_write(off)
        print("WRITE_REFUSED", False)
    except pi.RefusedWrite as err:
        print("WRITE_REFUSED", "runs off a 15x15 grid" in str(err))
    del pi.PUBLISHED_WRONG[(off["id"], found[0])]

    # A second across laid over the first four cells of 1-across: the shape a
    # mis-templated grid takes when a light is split or a block lands in the wrong
    # square. Numbered like 1-across so that only the overlap rule can speak.
    over = copy.deepcopy(puzzle)
    twin = copy.deepcopy({entry_id(e): e for e in over["entries"]}["1-across"])
    twin["length"] = 4
    over["entries"].append(twin)
    found = check_geometry(over)
    print("OVERLAP", len(found))
    print("OVERLAP_SAYS", all(f == f"cell ({x}, 0): 2 across lights share it — "
                              "1-across, 1-across" for x, f in enumerate(found)))

def block_out6():
    from datetime import date
    import puzzle_integrity as pi
    import series

    book = series.book_number("newpenguinbkguar0000perk", 1)
    DAY = "2014-12-31"
    def shape(series_key, number, **when):
        flags = []
        pi.check_shape({"id": f"{series_key}-{number}", "series": series_key,
                        "number": number, **when,
                        "entries": [{"number": 1, "direction": "across", "clue": {"text": "x", "enumeration": "1"}}]},
                       date(2026, 9, 25), flags)
        return sum(1 for kind, _pid, msg in flags
                   if kind == "SHAPE" and ("date" in msg or "year" in msg))
    print("BOOK_RIGHT", shape("book", book, year=series.published("book", book)))
    print("BOOK_UNDATED", shape("book", book))
    print("BOOK_WRONG_YEAR", shape("book", book, year=1996))
    print("BOOK_DAY", shape("book", book, year=series.published("book", book), date=DAY))
    print("PAPER_RIGHT", shape("cryptic", 30000, date=DAY))
    print("PAPER_YEAR", shape("cryptic", 30000, year=1995))
    print("PAPER_JUNK", shape("cryptic", 30000, date="1995"))
    print("PAPER_MS", shape("cryptic", 30000, date=1419984000000))
    print("PAPER_NO_DAY", shape("cryptic", 30000, date="2014-02-30"))
    print("PAPER_COMPACT", shape("cryptic", 30000, date="20141231"))

def block_out7():
    import json, os, shutil
    from datetime import date
    from pathlib import Path
    import puzzle_integrity as pi
    import puzzle_paths

    real = puzzle_paths.find("cryptic-24104")
    puzzle = pi.read_puzzle_file(real)
    puzzle_paths.PUZZLE_DIR = Path(os.environ["SCRATCH"]) / "puzzles"
    pi.CACHE = Path(os.environ["SCRATCH"]) / "integrity-rows.pickle"
    right = puzzle_paths.file_for(puzzle)
    right.parent.mkdir(parents=True)
    shutil.copy(real, right)
    (puzzle_paths.PUZZLE_DIR / "index.json").write_text("{}")

    def filed():
        files = pi.listing()
        flags, _ = pi.audit(files, pi.published(files), date(2026, 9, 25))
        return sorted(what for kind, _pid, what in flags if kind == "FILED")

    print("CLEAN", len(filed()))
    wrong = puzzle_paths.PUZZLE_DIR / "cryptic" / "1999" / right.name
    wrong.parent.mkdir()
    right.rename(wrong)
    print("WRONG_YEAR", filed() == [f"puzzles/cryptic/1999/cryptic-24104.json belongs at {right.relative_to(puzzle_paths.PUZZLE_DIR.parent)}"])
    wrong.rename(right)
    flat = puzzle_paths.PUZZLE_DIR / right.name
    shutil.copy(right, flat)
    print("FLAT", filed() == [f"puzzles/cryptic-24104.json belongs at {right.relative_to(puzzle_paths.PUZZLE_DIR.parent)}"])
    flat.unlink()
    misnamed = right.with_name("cryptic-24105.json")
    right.rename(misnamed)
    print("MISNAMED", len(filed()))

def block_out_rows():
    import json, os, shutil
    from datetime import date
    from pathlib import Path
    import puzzle_integrity as pi
    import puzzle_paths
    import row_cache

    d = Path(os.environ["SCRATCH"])
    reals = [puzzle_paths.find(pid) for pid in ("cryptic-24104", "times-29329", "times-15602")]
    puzzle_paths.PUZZLE_DIR = d / "puzzles"
    pi.CACHE = d / "integrity-rows.sqlite"
    row_cache.STORE = d / "rows.sqlite"
    pi.ROW_CACHE_MIN = 1
    for real in reals:
        to = puzzle_paths.file_for(pi.read_puzzle_file(real))
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(real, to)
    viewed = []
    view = pi.read_puzzle_view
    pi.read_puzzle_view = lambda p: viewed.append(p.name) or view(p)

    def run(today, cached=True):
        pi.ROW_CACHE_MIN = 1 if cached else 10**9
        viewed.clear()
        files = pi.listing()
        out = pi.audit(files, pi.published(files), today)
        return out, sorted(viewed)

    today = date(2026, 10, 5)
    plain, _ = run(today, cached=False)
    cold, n = run(today)
    print("COLD", len(n), cold == plain)
    warm, n = run(today)
    print("WARM", len(n), warm == plain)
    edited = puzzle_paths.file_for(pi.read_puzzle_file(reals[0]))
    p = json.loads(edited.read_text())
    p["date"] = "2027-01-01"
    edited.write_text(json.dumps(p))
    plain, _ = run(today, cached=False)
    again, n = run(today)
    print("EDITED", n == [edited.name], again == plain, any("in the future" in f[2] for f in again[0]))
    later = date(2027, 1, 2)
    plain, _ = run(later, cached=False)
    past, n = run(later)
    print("HORIZON", n == [edited.name], past == plain, not any("in the future" in f[2] for f in past[0]))

def block_out8():
    import copy
    import puzzle_integrity as pi

    held = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104"))
    other = copy.deepcopy(held)
    for e in other["entries"]:
        e["solution"] = "Q" * e["length"]
    fixed = copy.deepcopy(held)
    fixed["entries"][0]["solution"] = "Q" * fixed["entries"][0]["length"]
    withdrawn = copy.deepcopy(held)
    for e in withdrawn["entries"][4:]:
        e.pop("solution", None)


    def filed(new):
        flags = []
        pi.check_rewrite(held, new, flags)
        return sum(f[0] == "FILED" for f in flags)


    print("ANOTHER", filed(other))
    print("ONE_FIXED", filed(fixed))
    print("WITHDRAWN", filed(withdrawn))

def block_out9():
    import copy
    import fetch_puzzle
    import puzzle_integrity as pi

    # cryptic-23115 prints "Big hitting" on 16 and 17 down (THUMPING, WHOPPING):
    # the Guardian's own feed serves each light's clue, so that is the setter's.
    held = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-23115"))
    ocr = copy.deepcopy(held)
    ocr["source"]["retrievedFrom"] = "newspaper"


    def dups(p):
        flags = []
        pi.check_duplicated_clues(p, flags)
        return len(flags)


    print("FEED", dups(held))
    print("OCR", dups(ocr))
    fetch_puzzle.SOURCE_CLUE_WRONG[("cryptic-23115", "17-down")] = ("Big hitting", "Printed clue", "evidence")
    print("FIXED", dups(ocr))
    del fetch_puzzle.SOURCE_CLUE_WRONG[("cryptic-23115", "17-down")]
    # Listener No 3 prints "An exclamation." for 32 across and 2 down: one clue
    # in both lists is printed twice, no misread.
    lists = copy.deepcopy(ocr)
    across = next(e for e in lists["entries"] if e["direction"] == "across")
    for e in lists["entries"]:
        if (e["number"], e["direction"]) == (17, "down"):
            e["clue"] = {"text": "Another clue"}
    across["clue"] = {"text": "Big hitting"}
    print("LISTS", dups(lists))
    blanked = copy.deepcopy(ocr)
    for e in blanked["entries"]:
        if (e["number"], e["direction"]) in ((16, "down"), (1, "down")):
            e["clue"] = {"text": "", "missing": True}


    def blanks(old):
        flags = []
        pi.check_rewrite(old, blanked, flags)
        return ",".join(sorted(f[2].split(":")[0] for f in flags if f[0] == "SHAPE"))


    print("REWRITE_OCR", blanks(ocr))
    print("REWRITE_FEED", blanks(held))
    # quiptic-71's 20-down: the feed serves a placeholder, which SOURCE_CLUE_WRONG
    # prints as nothing; blanking it loses nothing, and only that light.
    served = next(e for e in held["entries"] if (e["number"], e["direction"]) == (16, "down"))["clue"]["text"]
    fetch_puzzle.SOURCE_CLUE_WRONG[("cryptic-23115", "16-down")] = (served, "", "evidence")
    print("REWRITE_PLACEHOLDER", blanks(held))
    del fetch_puzzle.SOURCE_CLUE_WRONG[("cryptic-23115", "16-down")]

def block_out10():
    import copy
    from datetime import date
    import puzzle_integrity as pi
    from groups import entry_id

    p0 = pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-24104"))


    def shape(clue):
        p = copy.deepcopy(p0)
        next(e for e in p["entries"] if entry_id(e) == "1-across")["clue"] = clue
        flags = []
        pi.check_puzzle(p, date(2026, 10, 5), flags)
        return sum("only an enumeration" in f[2] for f in flags)


    print("BARE", shape({"text": "(8)", "enumeration": "9"}))
    print("MISSING", shape({"enumeration": "9", "missing": True}))

def block_out11():
    import copy, json, os, shutil
    from pathlib import Path
    import puzzle_integrity as pi
    import puzzle_paths

    real = {n: pi.read_puzzle_file(puzzle_paths.find(f"ftcryptic-{n}")) for n in (8021, 8029, 8034)}
    puzzle_paths.PUZZLE_DIR = Path(os.environ["SCRATCH"]) / "puzzles"
    for p in real.values():
        dest = puzzle_paths.file_for(p)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(p))


    def refused(p, old=None):
        try:
            pi.refuse_misdated_write(p, old)
            return "allowed"
        except pi.RefusedWrite as e:
            return "refused" if all(k == "DATE" for k, _, _ in e.flags) else f"other {e}"


    def numbered(n, day, url="https://archive.org/details/x"):
        p = copy.deepcopy(real[8021])
        p["id"], p["number"], p["date"] = f"ftcryptic-{n}", n, day
        p["source"] = {**p["source"], "url": url}
        return p


    print("IN_ORDER", refused(numbered(8022, "1992-12-07")))
    print("BEFORE_BELOW", refused(numbered(8022, "1992-12-04")))
    print("AFTER_ABOVE", refused(numbered(8030, "1992-12-22")))
    print("SAME_AS_ABOVE", refused(numbered(8027, "1992-12-15")))
    later = copy.deepcopy(real[8021])
    later["date"] = "1992-12-12"
    later["source"] = {**later["source"], "url": later["source"]["url"].replace("Dec%2005", "Dec%2012")}
    print("LATER_REPRINT", refused(later, real[8021]))
    print("REWRITE_SAME_DAY", refused(copy.deepcopy(real[8021]), real[8021]))
    print("NEIGHBOURS", [x and x[0] for x in pi.filed_neighbours(numbered(8030, "1992-12-16"))])

def block_out12():
    import tempfile, time, os
    from pathlib import Path
    import puzzle_integrity as pi
    d = Path(tempfile.mkdtemp())
    pi.CACHE = d / "integrity-rows.sqlite"
    pi.CACHE.write_text("legacy")
    a = pi.cache_path("a" * 40)
    b = pi.cache_path("b" * 40)
    old = pi.cache_path("c" * 40)
    old.write_text("x"); os.utime(old, (1, 1))
    conn = pi._open_cache()
    conn.execute("INSERT INTO rows(blob, pid, digest, nkeys, held) VALUES('x','p','d',0,x'00')"); conn.commit()
    conn.close()
    pi._fingerprint = lambda: "b" * 40
    pi._open_cache().close()
    print("SEPARATE", pi.cache_path(pi._fingerprint()) == b and b.exists())
    print("LEGACY_GONE", not pi.CACHE.exists())
    print("STALE_PRUNED", not old.exists())

def block_out13():
    import copy, json, glob
    import puzzle_integrity as pi
    p = json.load(open(glob.glob("puzzles/genius/*/genius-43.json")[0]))
    assert p.get("setter") is None
    def setter_flags(new, old):
        try:
            pi.refuse_bad_write(new, old)
        except pi.RefusedWrite as e:
            return [w for f, _, w in e.flags if f == "SETTER"]
        return []
    solved = copy.deepcopy(p)
    solved["solutions"] = {**(p.get("solutions") or {}), "origin": "model"}
    print("SOLVED_NO_SETTER", "refused" if setter_flags(solved, p) else "allowed")
    print("NEW_NO_SETTER", "refused" if setter_flags(solved, None) else "allowed")
    had = copy.deepcopy(p); had["setter"] = "Araucaria"
    print("DROPS_SETTER", "refused" if setter_flags(solved, had) else "allowed")
    # The pre-push runs the full report on the pushed file: it must not flag it
    # either, or the solve commits and never pushes (genius-26, 10-13).
    rep = []; pi.check_setter(solved, rep)
    print("REPORT_SOLVED_NO_SETTER", "flagged" if rep else "clean")
    junk = copy.deepcopy(solved); junk["setter"] = "Unknown"
    print("PLACEHOLDER", "refused" if setter_flags(junk, p) else "allowed")

def block_out14():
    import puzzle_integrity as pi
    def entry(enum, sol):
        return {"number": 1, "direction": "across", "position": {"x": 0, "y": 0},
                "length": len(sol), "solution": sol, "clue": {"text": "Theme", "enumeration": enum}}
    def flags(enum, sol):
        e = entry(enum, sol); out = []
        pi.check_length({"id": "genius-38", "series": "genius", "entries": [e]}, [e], out)
        return [f for f in out if f[0] == "LENGTH"]
    print("SECOND_SIDE", "refused" if flags("6;4,6", "TENLETTERS") else "allowed")
    print("FIRST_SIDE", "refused" if flags("6;4,6", "SIXSIX") else "allowed")
    print("NEITHER", "refused" if flags("6;4,6", "SEVENLT") else "allowed")

def block_out15():
    import puzzle_integrity as pi
    def flags(lead_enum, leg_text, series="cryptic"):
        lead = {"number": 19, "direction": "across", "position": {"x": 0, "y": 0}, "length": 4,
                "solution": "WOOD", "group": ["19-across", "13-across"],
                "clue": {"text": "Bowl dropped where Ada Doom saw something nasty", "enumeration": lead_enum}}
        leg = {"number": 13, "direction": "across", "position": {"x": 0, "y": 2}, "length": 4,
               "solution": "SHED", "clue": {"text": leg_text, "enumeration": None}}
        out = []
        pi.check_length({"id": "cryptic-21704", "series": series, "entries": [leg, lead]}, [leg, lead], out)
        return [f for f in out if f[0] == "LENGTH"]
    print("OWN_OVER_POINTER", "refused" if flags("4", "See 19") else "allowed")
    print("OWN_OVER_POINTER_TELEGRAPH", "refused" if flags("4", "See 19 across", "telegraph") else "allowed")
    print("WHOLE_OVER_POINTER", "refused" if flags("4,4", "See 19") else "allowed")
    print("OWN_OVER_CLUED_LEG", "refused" if flags("4", "Hut for storage") else "allowed")
    print("NEITHER_OVER_POINTER", "refused" if flags("5", "See 19") else "allowed")


try:
    print("each per-file check flags its own defect, and nothing else")
    out1, _ = run_block(block_out1)
    died(out1, "the per-file fixtures")
    for pid in ("cryptic-24104", "cryptic-24447"):
        same(f"{pid} as published is clean", awk(out1, "PRISTINE", 3, pid), "none")
    for line in out1.splitlines():
        if line.startswith("FLAG "):
            _, flag, raised = (line.split(None, 2) + ["", ""])[:3]
            same(f"a {flag} defect is flagged {flag} alone", raised, flag)
    same("every flag in FLAGS has a fixture", field("UNCOVERED", out1), "none")

    print("a clue that says 'See preamble' with no preamble is written, and never sent for annotation")
    out_pre, _ = run_block(block_out_pre)
    died(out_pre, "the see-preamble fixture")
    same("an Azed special from its blog awaits its preamble", field("SPECIAL", out_pre), "True")
    same("a plain Christmas Azed does not", field("PLAIN", out_pre), "False")
    same("a plain competition Azed does not", field("COMP", out_pre), "False")
    same("an Azed post named by number alone does not", field("BARENUM", out_pre), "False")
    same("'See preamble' with no preamble awaits its preamble", field("BARE", out_pre), "True")
    same("'See preamble' with a preamble does not", field("WITH", out_pre), "False")
    same("the write path accepts it", field("WRITE", out_pre), "allowed")
    same("'(see the preamble)' awaits too", field("INDEXED", out_pre), "True")

    print("a cover-dated weekly may be dated its issue's day, a few days ahead; nothing else may")
    out_cover, _ = run_block(block_out_cover)
    died(out_cover, "the cover-date fixture")
    same("tls-1621, posted Wednesday and dated Friday's issue, is not in the future", field("TLS2", out_cover), "False")
    same("a TLS dated exactly its lead ahead is allowed", field("TLSLEAD", out_cover), "False")
    same("a TLS dated past its lead is in the future", field("TLSPAST", out_cover), "True")
    same("a daily dated tomorrow is in the future", field("DAILY1", out_cover), "True")
    same("the Listener, printed the day it is dated, has no lead", field("LISTENER", out_cover), "0")

    print("a run that left answers to a missing preamble marks the puzzle to await one")
    out_await, _ = run_block(block_out_await, SCRATCH=str(scratch) + "/await")
    died(out_await, "the await-preamble fixture")
    same("the run's sole failure is the missing preamble: its entries are listed", grep_c("[0-9][AD]", field("WHICH", out_await)), "1")
    same("a puzzle holding its preamble awaits none", field("HELD", out_await), "none")
    same("letters a block takes from the preamble lean on it too", grep_c("[0-9][AD]", field("SUPPLIED", out_await)), "1")
    same("a run that failed on anything else too is parked instead", field("OTHER", out_await), "none")
    same("awaitsPreamble keeps it from the annotators", field("FLAGGED", out_await), "True")
    same("until a preamble is filed", field("ARRIVED", out_await), "False")
    same("the flag beside a preamble is flagged", field("BESIDE", out_await), "True")
    same("a rewrite with no preamble keeps the flag", field("KEPT", out_await), "True")
    same("filing a preamble drops it", field("DROPPED", out_await), "True")

    print("the CLI on a scratch corpus: clean exits 0; DUPLICATE, NEARDUP and DATE across files exit 1")
    out2, _ = run_block(block_out2, SCRATCH=str(scratch) + "/cli")
    died(out2, "the scratch-corpus CLI")
    same("two clean puzzles: exit 0, every tally 0", cut_f2(grep(r"^CLEAN ", out2)), "0 none")
    same("a later number dated earlier: exit 1, DATE alone", cut_f2(grep(r"^DATE ", out2)), "1 DATE")
    same("all but one clue shared: exit 1, NEARDUP alone", cut_f2(grep(r"^NEARDUP ", out2)), "1 NEARDUP")
    # A copy shares every clue too, so NEARDUP rides along with DUPLICATE.
    same("the same puzzle under another id: exit 1, DUPLICATE", cut_f2(grep(r"^DUPLICATE ", out2)), "1 DUPLICATE,NEARDUP")
    same("--refused holds back a clean sibling: no", grep(r"^REFUSED CLEAN ", out2), "REFUSED CLEAN []")
    same("--refused holds back a sibling dated before its number: yes", grep(r"^REFUSED DATE ", out2), "REFUSED DATE ['cryptic-24448.json']")
    same("the same puzzle as a listed reprint: exit 0, every tally 0", cut_f2(grep(r"^REPRINT ", out2)), "0 none")

    print("exactness: a lengthened key must not still match, and dropping one table must not touch the other")
    combo, _ = run_block(block_combo)
    died(combo, "the exactness check")
    n_pw = awk(combo, "TABLE_SIZES", 2)
    n_uis = awk(combo, "TABLE_SIZES", 3)
    same("the puzzles the tables name report nothing with both tables in place", field("BASELINE", combo), "0")
    same(f"lengthening every key by one trailing space reproduces all {int(n_pw) + int(n_uis)} findings", field("LENGTHENED_BOTH", combo), str(int(n_pw) + int(n_uis)))
    same(f"dropping PUBLISHED_WRONG alone reproduces its own {n_pw} finding(s), not UNLINKED_IN_SOURCE's", field("DROP_PUBLISHED_WRONG", combo), n_pw)
    same(f"dropping UNLINKED_IN_SOURCE alone reproduces its own {n_uis} finding(s), not PUBLISHED_WRONG's", field("DROP_UNLINKED_IN_SOURCE", combo), n_uis)
    same("both tables restored, clean again", field("RESTORED", combo), "0")

    print("a table key naming a puzzle not filed is a FILED finding, not a crash")
    unheld, _ = run_block(block_unheld)
    died(unheld, "the unfiled-key check")
    same("every puzzle the tables name is filed", awk(unheld, "ALL_HELD", 2, rest=True), "0")
    same("a key naming an unfiled puzzle: one FILED finding for it", awk(unheld, "UNHELD", 2, 3), "1 FILED:genius-99999")

    print("non-blanket suppression: baselining a finding must not blank out the rest of its puzzle")
    out3, _ = run_block(block_out3, merge=False)
    same("exactly one LENGTH finding survives in the mutated cryptic-24104", field("TOTAL", out3), "1")
    same("it is the injected 1-across defect", field("NEW_DEFECT", out3), "True")
    same("the baselined 13-across/16-down pair stays silent", field("PAIR_SILENT", out3), "True")

    print("a grid with no puzzle in it: every clue blank is one finding, one blank clue is none")
    out4, _ = run_block(block_out4, merge=False)
    same("one clue the setter left blank is not a defect", field("ONE_BLANK", out4), "0")
    same("a puzzle with no clue text at all is exactly one finding", field("ALL_BLANK", out4), "1")
    same("and it counts the clues it actually read", field("BLANK_SAYS", out4), "True")

    print("grid geometry: a light off the board and two acrosses on one cell are findings")
    out5, _ = run_block(block_out5, merge=False)
    same("the puzzle as published is a coherent grid", field("PRISTINE", out5), "0")
    same("a light off the board is exactly one finding", field("OFFBOARD", out5), "1")
    same("and it names the light, the run and the board", field("OFFBOARD_SAYS", out5), "True")
    same("PUBLISHED_WRONG naming an off-board light does not forgive it", field("FORGIVEN_STILL_FLAGS", out5), "True")
    same("and the writer refuses to put it on disk", field("WRITE_REFUSED", out5), "True")
    same("two acrosses over four cells is four findings", field("OVERLAP", out5), "4")
    same("each names the cell and both lights", field("OVERLAP_SAYS", out5), "True")

    print("a book puzzle holds its book's year and no date; only a book holds a year")
    # Synthetic puzzles, so the check is exercised whatever the corpus holds.
    out6, _ = run_block(block_out6, merge=False)
    same("the registry's year passes", field("BOOK_RIGHT", out6), "0")
    same("a book puzzle with no year is flagged", field("BOOK_UNDATED", out6), "1")
    same("a book puzzle under another year is flagged", field("BOOK_WRONG_YEAR", out6), "1")
    same("a book puzzle with a day is flagged", field("BOOK_DAY", out6), "1")
    same("a paper's day passes", field("PAPER_RIGHT", out6), "0")
    same("a paper's puzzle holding a year, and no date, is flagged twice", field("PAPER_YEAR", out6), "2")
    same("a date that is only a year is flagged", field("PAPER_JUNK", out6), "1")
    same("a date in epoch milliseconds is flagged", field("PAPER_MS", out6), "1")
    same("a date that is not a calendar day is flagged", field("PAPER_NO_DAY", out6), "1")
    same("a date not written YYYY-MM-DD is flagged", field("PAPER_COMPACT", out6), "1")

    print("a file not at file_for is FILED: wrong year, flat stray, wrong name")
    out7, _ = run_block(block_out7, merge=False, SCRATCH=str(scratch) + "")
    same("a puzzle at file_for is not flagged (nor is the generated index)", field("CLEAN", out7), "0")
    same("a puzzle in the wrong year folder names where it belongs", field("WRONG_YEAR", out7), "True")
    same("a stray flat puzzles/<id>.json names where it belongs", field("FLAT", out7), "True")
    same("a file named for another id is flagged", field("MISNAMED", out7), "1")

    print("a whole run keeps each file's findings: a warm run views nothing, an edit views its file again")
    out_rows, _ = run_block(block_out_rows, SCRATCH=str(scratch) + "/rows", CT_JOBS="1")
    died(out_rows, "the row-cache fixture")
    same("a cold run views every file and finds what an uncached run finds", awk(out_rows, "COLD", 2, 3), "3 True")
    same("a warm run views no file and finds the same", awk(out_rows, "WARM", 2, 3), "0 True")
    same("an edited file alone is viewed again, its new finding found", field("EDITED", out_rows) + " " + awk(out_rows, "EDITED", 3, 4), "True True True")
    same("a future date reached by today views its file again and drops the finding", field("HORIZON", out_rows) + " " + awk(out_rows, "HORIZON", 3, 4), "True True True")

    print("a rewrite may not replace the held puzzle with another one")
    out8, _ = run_block(block_out8, merge=False)
    same("another puzzle's answers over a held file are refused", field("ANOTHER", out8), "1")
    same("one corrected answer is not another puzzle", field("ONE_FIXED", out8), "0")
    same("most answers withdrawn to blank is not another puzzle", field("WITHDRAWN", out8), "0")

    print("an OCR reading may not file one clue on two lights")
    out9, _ = run_block(block_out9, merge=False)
    same("a placeholder SOURCE_CLUE_WRONG prints as nothing may be blanked, any other clue is kept", field("REWRITE_PLACEHOLDER", out9), "1-down")
    same("a feed's clue on two lights is the setter's", field("FEED", out9), "0")
    same("an OCR reading's clue on two lights is refused", field("OCR", out9), "1")
    same("unless SOURCE_CLUE_WRONG prints one of them", field("FIXED", out9), "0")
    same("one clue in the ACROSS and DOWN lists is printed in each", field("LISTS", out9), "0")
    same("blanking an OCR reading's clue on two lights loses nothing, any other clue is kept", field("REWRITE_OCR", out9), "1-down")
    same("a feed's clue on two lights is a clue a rewrite keeps", field("REWRITE_FEED", out9), "1-down,16-down")

    print("a clue whose text is only a count is refused; stored as missing with no text, it passes")
    out10, _ = run_block(block_out10)
    died(out10, "the bare-count fixture")
    same("text of nothing but a count is flagged", field("BARE", out10), "1")
    same("missing with no text is not", field("MISSING", out10), "0")

    # DATE at write time (2026-10-11): the FT full pass re-filed ftcryptic-8021
    # (first printed 5 December 1992) off the 12 December scan that prints it
    # again, and filed second puzzles under the dates of archive.org items that
    # bind another issue's pages in; the checkpoint's pre-push then refused.
    out11, _ = run_block(block_out11, merge=False, SCRATCH=str(scratch) + "/date")
    died(out11, "the write-time DATE fixture")
    same("a date between its filed neighbours is written", field("IN_ORDER", out11), "allowed")
    same("a date on or before the puzzle numbered below is refused", field("BEFORE_BELOW", out11), "refused")
    same("a date on or after the puzzle numbered above is refused", field("AFTER_ABOVE", out11), "refused")
    same("a second puzzle on the next one's day is refused", field("SAME_AS_ABOVE", out11), "refused")
    same("a filed puzzle moved to a later scan's date is refused", field("LATER_REPRINT", out11), "refused")
    same("a rewrite keeping the filed date is untouched", field("REWRITE_SAME_DAY", out11), "allowed")
    check(out11, "NEIGHBOURS [8029, 8034]", "neighbours are the nearest filed numbers either side")

    out12, _ = run_block(block_out12, merge=False)
    died(out12, "the cache-per-fingerprint fixture")
    check(out12, "SEPARATE True", "a different source fingerprint opens its own cache file")
    check(out12, "LEGACY_GONE True", "the old shared single-file cache is removed")
    check(out12, "STALE_PRUNED True", "stale caches of other fingerprints are pruned")

    # No setter never holds a write (Paul's rule: never hold a puzzle for its
    # form). Genius 43 was filed unsolved with no byline; the backfill's solve
    # turned its origin to "model", and refuse_bad_write refused it on SETTER
    # (2026-10-13, eight Genius solves). Only dropping a held byline still refuses.
    out13, _ = run_block(block_out13, merge=False)
    died(out13, "the no-setter write fixture")
    same("a solved puzzle filed with no byline is written", field("SOLVED_NO_SETTER", out13), "allowed")
    same("a new puzzle with no byline is written", field("NEW_NO_SETTER", out13), "allowed")
    same("and the integrity report does not flag the solved one (the pre-push runs it)", field("REPORT_SOLVED_NO_SETTER", out13), "clean")
    same("a write dropping the held byline is refused", field("DROPS_SETTER", out13), "refused")
    same("a placeholder byline is still refused", field("PLACEHOLDER", out13), "refused")

    # "(6;4,6)" is two counts: a themed Genius prints the clue's answer, then what
    # the grid holds. genius-38 was refused as 16 letters over 10 (2026-10-13).
    out14, _ = run_block(block_out14, merge=False)
    died(out14, "the two-count enumeration fixture")
    same("a themed (6;4,6) over ten cells is its entry count", field("SECOND_SIDE", out14), "allowed")
    same("a themed (6;4,6) over six cells is its clue count", field("FIRST_SIDE", out14), "allowed")
    same("a (6;4,6) over seven cells is still refused", field("NEITHER", out14), "refused")

    # A leading clue counting only its own light, over legs that are bare
    # pointers: the Guardian 1999-2005 (cryptic-21704's WOOD "(4)" + "See 19"
    # SHED) and the Telegraph today. The pointer links the group; a leg with a
    # clue of its own leaves the lead held to the whole answer's count.
    out15, _ = run_block(block_out15, merge=False)
    died(out15, "the own-count leader fixture")
    same("a lead counting its own light over a See-N leg is allowed", field("OWN_OVER_POINTER", out15), "allowed")
    same("and in the Telegraph too", field("OWN_OVER_POINTER_TELEGRAPH", out15), "allowed")
    same("a lead counting the whole answer is still allowed", field("WHOLE_OVER_POINTER", out15), "allowed")
    same("a lead counting its own light over a leg with its own clue is refused", field("OWN_OVER_CLUED_LEG", out15), "refused")
    same("a count that is neither the light's nor the answer's is refused", field("NEITHER_OVER_POINTER", out15), "refused")

    print("puzzle_integrity: all checks passed" if not fails else f"puzzle_integrity: {fails} FAILED")

finally:
    shutil.rmtree(scratch, ignore_errors=True)
sys.exit(1 if fails else 0)
