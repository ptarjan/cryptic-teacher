#!/usr/bin/env python3
# Does the per-edition queue (tools/edition_queue.py) keep each edition's
# read a unit of its own: rows appended, the last standing, never a whole
# rewrite under another unit; one unit per edition; the most urgent first
# (Gale pages the fetcher downloaded, then never read, then the re-reads); a read
# only after the scans its solution needs, and a scan held while a read
# pool of reads is ready; a slow unit killed at its own
# limit without holding up the rest; a capped run saying what it left; and
# a TERM passed on to the units; an edition just laid out (fresh) found
# without a plan and started before every planned unit, even mid-plan?
#
#     python3 tools/test_edition_queue.py
#
# Temp dirs only; no OCR, no VLM, no network.
import atexit
import os
os.environ.setdefault("CT_VLM_BLIP_SECONDS", "0")  # no link-blip waits on a fake unreachable VLM

# The desktop the code reaches is a fake one: the real addresses live in an untracked local config.
os.environ.update(CT_LOCAL_CONFIG="/nonexistent", CT_DESKTOP_USER="tester", CT_VLM_PORT="8000",
                  CT_DESKTOP_ADDRESSES="192.0.2.198 192.0.2.180 100.64.0.15", CT_DESKTOP_HOME="C:\\Users\\tester\\ocrw")
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["DESKTOP_HOSTS_STATIC"] = "1"  # desktop_hosts.ranked: the json order, no network probe
os.environ["CT_REFUSAL_REREADS"] = "1"  # the cases below plan refusal rereads beside never-read units (the hold cases turn it off)
os.environ["CT_BLANKET_REREADS"] = "1"  # the cases below plan every reread (the blanket-reread cases turn it off)
os.environ["CT_AUTO_RELOAD"] = "0"  # no dispatch here fetches the real repo (the reload cases turn it on)
REPO = Path(__file__).resolve().parent.parent
_tmp = tempfile.mkdtemp()
_parent = os.getpid()
atexit.register(lambda: os.getpid() == _parent and shutil.rmtree(_tmp, ignore_errors=True))
os.environ["TMP"] = _tmp
os.chdir(REPO / "tools")
sys.path.insert(0, str(REPO / "tools"))

import contextlib, io, json, os, signal, sys, time
from pathlib import Path
import scan_queue as q
import vlm_reader
vlm_reader.reachable = lambda *a, **k: False
import file_archive_org_puzzles as f
import edition_queue as eq
eq.cpu_gate_reader = lambda: 0.0  # this host's load must not gate the tests' starts
eq.idle_gate_reader = lambda: 1e6  # nor its idle cores
eq.desktop_gate_reader = lambda: None  # nor whether Paul's desktop is busy
eq.desktop_mem_reader = lambda: None  # nor its free memory
eq.vlm_gate_reader = lambda: True  # nor whether its VLM answers
os.environ["CT_BURN_STATE"] = os.path.join(os.environ["TMP"], "no-burn")  # nor this host's burn
os.environ["CT_PSI_PATH"] = os.path.join(os.environ["TMP"], "no-psi")  # nor this host's memory pressure

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

for _val, _want in ((None, 1200), ("", 1200), ("3600", 3600.0), ("abc", 1200), ("0", 1200), ("-5", 1200)):
    os.environ.pop("CT_READ_SECONDS_T", None)
    if _val is not None:
        os.environ["CT_READ_SECONDS_T"] = _val
    check(f"seconds_from_env({_val!r})", _want, eq.seconds_from_env("CT_READ_SECONDS_T", 1200))
os.environ.pop("CT_READ_SECONDS_T", None)

T = Path(os.environ["TMP"])
eq.DIR_CACHE, eq.HELD_CACHE, eq.LIKELY_CACHE = T / "dir_cache.pickle", T / "held_files.pickle", T / "likely.pickle"  # never this host's caches
eq.COUNT_LEFT_CACHE = T / "count_left.pickle"
q.LEDGERS = {k: T / f"none-{k}.jsonl" for k in ("archive", "gale", "trove")}
q.REQUESTS = T / "requests.jsonl"

# ---- the ledger: appended rows, the last standing
led = T / "l.jsonl"
q.append(led, [{"edition": "a", "n": 1}, {"edition": "b", "n": 1}])
q.append(led, [{"edition": "a", "n": 2}])
check("the last row of a source stands", {"a": 2, "b": 1}, {k: r["n"] for k, r in q.ledger_rows(led, "edition").items()})
with open(led, "a") as fh:
    fh.write('{"edition": "c", "n"')
check("a line still being appended is not a row", ["a", "b"], sorted(q.ledger_rows(led, "edition")))
check("jsonl_rows skips it too", 3, len(q.jsonl_rows(led)))
led.write_text(led.read_text()[: -len('{"edition": "c", "n"')])
check("compact folds to one row a source", (3, 2), q.compact(led, "edition"))
check("compacted rows keep the last", {"a": 2, "b": 1}, {k: r["n"] for k, r in q.ledger_rows(led, "edition").items()})
with q.lock(led) as mine:
    check("a run holding the ledger throughout is seen", (True, True), (mine, q.held(led)))
    check("compact leaves a held ledger alone", None, q.compact(led, "edition"))
check("free again", False, q.held(led))
with q.source_lock(led, "x") as a:
    pid = os.fork()
    if pid == 0:
        with q.source_lock(led, "x") as b, q.source_lock(led, "y") as c:
            os._exit(0 if (b, c) == (False, True) else 1)
    check("one process a source: another gets busy, another source is free", 0,
          os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))

# ---- plan(): ranks, needs, order; nothing scanned
cache = T / "cache"
def edition(item, name, staged):
    d = cache / item / name
    d.mkdir(parents=True)
    (d / "pages.json").write_text("{}")
    os.utime(d / "pages.json", (staged, staged))
    return d
g1 = edition("GaleTimes1987UKEnglish", "1987-03-02", 1000)
g2 = edition("GaleTimes1987UKEnglish", "1987-03-03", 2000)
t1 = edition("NewsUK1980UKEnglish", "1980-01-01_1", 10)
t2 = edition("NewsUK1980UKEnglish", "1980-01-02_2", 10)
t3 = edition("NewsUK1980UKEnglish", "1980-03-01_3", 10)
f.edition_dirs = lambda cache=None, paper=None: {"gale": [g1, g2], "times": [t1, t2, t3]}.get((paper or f.TIMES).key, [])
f.input_hash = lambda d: "h"
f.inputs_of = lambda fh, found, series, reprints=None: fh
scan = {"puzzles": [{"number": 1, "leaf": 1, "box": None}], "solutions": []}
def row(d, read_at=None, **kw):
    r = {"edition": f"{d.parent.name}/{d.name}", "filesHash": "h", "scanKey": f.scan_key(), "scan": scan}
    if read_at:
        r.update(inputs="h", solutionsSeen=[], verdicts=[{"number": 1}], readAt=read_at)
    return {**r, **kw}
tl = cache / "filed.jsonl"
q.append(tl, [row(t1, "2026-01-01T00:00:00+00:00"), row(t2, "2026-09-01T00:00:00+00:00", scanKey="old")])
before = q.when("2026-06-01T00:00:00+00:00")
scans, reads = f.plan(f.TIMES, cache, reread=before)
check("times: a stale scan and a never-scanned edition are scan units, by rank", ["1980-03-01_3", "1980-01-02_2"],
      [u["rel"].split("/")[1] for u in scans])
check("times: each read and why; a scan-code change is a whole-corpus re-read, newest first",
      [("1980-03-01_3", "never read", 1), ("1980-01-02_2", "scan stale", 3), ("1980-01-01_1", "--reread", 3)],
      [(u["rel"].split("/")[1], u["reason"], u["rank"]) for u in reads])
check("a read needs its own stale scan and those SOLUTION_DAYS after it, no other",
      {"1980-01-01_1": ["1980-01-02_2"], "1980-01-02_2": ["1980-01-02_2"], "1980-03-01_3": ["1980-03-01_3"]},
      {u["rel"].split("/")[1]: [r.split("/")[1] for r in u["needs"]] for u in reads})
check("a scan takes the rank of the most urgent read needing it", [1, 3], [u["rank"] for u in scans])
_, reads = f.plan(f.TIMES, cache, asked={"NewsUK1980UKEnglish/1980-01-01_1"})
check("annotation's ask makes a read due, forced", [("1980-01-01_1", "annotation asked", True)],
      [(u["rel"].split("/")[1], u["reason"], u["force"]) for u in reads if u["rel"].endswith("_1")])
gs, gr = f.plan(f.GALE, cache)
check("Gale pages the fetcher downloaded: rank 0, the latest laid out first", [("1987-03-03", 0), ("1987-03-02", 0)],
      [(u["rel"].split("/")[1], u["rank"]) for u in gr])
check("the Gale plan keeps to its own ledger", False, (cache / "filed-gale.jsonl").exists())

# ---- Paul's order: new first, then re-reads that can change a result, then the whole corpus; newest first
oc = T / "order"
def ed(item, name):
    d = oc / item / name
    d.mkdir(parents=True)
    (d / "pages.json").write_text("{}")
    return d
eds = {n: ed(item, n) for item, n in [("NewsUK1990UKEnglish", "1990-05-01_1"), ("NewsUK1990UKEnglish", "1990-06-01_1"),
                                      ("NewsUK1970UKEnglish", "1970-01-01_1"), ("NewsUK1985UKEnglish", "1985-01-01_1"),
                                      ("NewsUK1995UKEnglish", "1995-01-01_1"), ("NewsUK1999UKEnglish", "1999-01-01_1"),
                                      ("TeleUK1992UKEnglish", "1992-01-01_1")]}
listing, f.edition_dirs = f.edition_dirs, lambda cache=None, paper=None: (
    [d for n, d in eds.items() if n != "1992-01-01_1"] if (paper or f.TIMES).key == "times" else [eds["1992-01-01_1"]])
hashes, f.input_hash = f.input_hash, lambda d: "moved" if d.name == "1985-01-01_1" else "h"
old = "2026-01-01T00:00:00+00:00"
q.append(oc / "filed.jsonl", [
    row(eds["1970-01-01_1"], old, verdicts=[{"number": 1, "cause": "not-a-grid"}]),  # its refusal's fix landed since
    row(eds["1985-01-01_1"], old),  # its files moved
    row(eds["1995-01-01_1"], old, scanKey="old"),  # only the scan code moved
    row(eds["1999-01-01_1"], old)])  # nothing moved: the --reread alone
_, reads = eq.plan(["times", "telegraph"], oc, q.when("2026-06-01T00:00:00+00:00"))
check("never read newest first across papers, then fixes and moved inputs newest first, then the whole corpus",
      [("1992-01-01_1", 1), ("1990-06-01_1", 1), ("1990-05-01_1", 1), ("1985-01-01_1", 2), ("1970-01-01_1", 2),
       ("1999-01-01_1", 3), ("1995-01-01_1", 3)],
      [(u["rel"].split("/")[1], u["rank"]) for u in reads])
check("a fix's re-read ranks 2 even under --reread; moved files are inputs changed",
      {"1970-01-01_1": "refused not-a-grid before its fix", "1985-01-01_1": "inputs changed"},
      {u["rel"].split("/")[1]: u["reason"] for u in reads if u["rank"] == 2})
# ---- only rereads with bug evidence: never read/scanned, annotation asked, a refusal whose fix landed
del os.environ["CT_BLANKET_REREADS"]
sc_ev, rd_ev = eq.plan(["times", "telegraph"], oc, q.when("2026-06-01T00:00:00+00:00"))
check("no blanket rereads: inputs changed, scan stale and --reread are not planned; refusals whose fix landed are",
      {"1992-01-01_1", "1990-06-01_1", "1990-05-01_1", "1970-01-01_1"}, {u["rel"].split("/")[1] for u in rd_ev})
check("every planned read's reason is a kept one", True, all(eq.evidence_reason(u["reason"]) or f.likely_gain(u) > 0 for u in rd_ev))
check("the refusal's read says which puzzle and what the refusal said", True,
      all("puzzle 1" in u.get("detail", "") for u in rd_ev if u["reason"].startswith("refused ")) and
      any(u.get("detail") for u in rd_ev))
check("no scan for a blanket reread", True, all(u["reason"] == "never scanned" or u["rel"] in
      {r for x in rd_ev for r in x.get("needs") or ()} for u in sc_ev))
eq._ASKED_WHY[("times", "X/1")] = "puzzle times-1: printedClue"
_, ask = eq.only_evidence("times", [], [{"rel": "X/1", "reason": "annotation asked", "needs": []},
                                         {"rel": "X/2", "reason": "inputs changed", "needs": []}])
check("annotation asked carries its puzzle and checks; inputs changed is dropped",
      [("X/1", "annotation asked", "puzzle times-1: printedClue")], [(u["rel"], u["reason"], u["detail"]) for u in ask])
_, lk = eq.only_evidence("times", [], [{"rel": "X/3", "reason": "scan stale, answers linked", "needs": [], "likely": {"answers linked": 2}},
                                        {"rel": "X/4", "reason": "scan stale", "needs": [], "likely": {}}])
check("a read predicted to file whole (answers linked) stays, with its detail", [("X/3", "answers linked x2")],
      [(u["rel"], u["detail"]) for u in lk])
_sc, _rd = eq.only_evidence("times", [{"rel": "G/1", "reason": "scan stale", "kind": "scan"},
                                      {"rel": "G/2", "reason": "scan stale", "kind": "scan"}],
                            [{"rel": "G/0", "reason": "scan stale, answers missing", "needs": ["G/1"]}])
check("a Times read waiting on scans for its solution heading keeps neither (only the solution-host scans are kept, 5c8eb3523ce)",
      ([], []), ([u["rel"] for u in _sc], _rd))
_sc, _rd = eq.only_evidence("times", [{"rel": "G/1", "reason": f.HOST_SCAN, "kind": "scan"},
                                      {"rel": "G/2", "reason": "scan stale", "kind": "scan"}],
                            [{"rel": "G/0", "reason": "scan stale, answers missing", "needs": ["G/1"]}])
check("mirror: a solution-host scan is kept", (["G/1"], []), ([u["rel"] for u in _sc], _rd))
_, _rd = eq.only_evidence("ft", [], [{"rel": "G/0", "reason": "scan stale, answers missing", "needs": ["G/1"]}])
check("another paper's is dropped", [], _rd)
_note = []
_refusal = {"rel": "G/0", "reason": "refused not-a-grid before its fix", "needs": ["G/0", "G/1", "G/2"]}
_sc, _rd = eq.only_evidence("gale", [{"rel": r, "reason": "scan stale", "kind": "scan"} for r in ("G/0", "G/1", "G/2")],
                            [_refusal], _note)
check("a Times-series refusal reread keeps its own page's scan, not the week after it", (["G/0"], [_refusal]),
      ([u["rel"] for u in _sc], _rd))
check("and the plan says how many it left out", True, len(_note) == 1 and "left out 2 stale scans" in _note[0])
_sc, _ = eq.only_evidence("ft", [{"rel": r, "reason": "scan stale", "kind": "scan"} for r in ("G/0", "G/1")],
                          [{"rel": "G/0", "reason": "never read", "needs": ["G/0", "G/1"]}])
check("another paper's read keeps every scan it waits on", ["G/0", "G/1"], [u["rel"] for u in _sc])
_ws = lambda s: [(0, 0, 9, 9, w) for w in s.split()]
check("Solution to Crossword N and Yesterday's solution N are headings", [(22925, 3), (24378, 2)],
      [f.solution_at(_ws("Solution to Crossword 22,925"), 0, {22925}), f.solution_at(_ws("Yesterday's solution 24,378"), 0, {24378})])
check("a Saturday prize's solution heading (Gale Times 2006-09: \"Solution to Prize Crossword N\", \"Prize solution N\") "
      "is read at PRIZE_LAG before the Monday's title only; the weekday heading's lags still read as before",
      [(23420, 4), (24299, 2), None, None, (24305, 3)],
      [f.solution_at(_ws("Solution to Prize Crossword 23,420"), 0, {23426}, (), {23420}),
       f.solution_at(_ws("Prize solution 24,299"), 0, {24305}, (), {24299}),
       f.solution_at(_ws("Prize solution 24,299"), 0, {24305}),
       f.solution_at(_ws("Solution to Prize Crossword 23,421"), 0, {23426}, (), {23420}),
       f.solution_at(_ws("Solution to Crossword 24,305"), 0, {24305}, (), {24299})])
check("solution_headings takes the prize under a Monday's title and not a Prize heading lagging otherwise",
      [[(23420, (1, 2, 5, 9))], []],
      [f.solution_headings([[(1, 2, 3, 4, "Solution"), (3, 4, 4, 5, "to"), (4, 3, 5, 9, "Prize"), (5, 3, 5, 9, "Crossword"),
                             (1, 2, 5, 9, "23,420")]], [23427]),
       f.solution_headings([[(1, 2, 3, 4, "Solution"), (3, 4, 4, 5, "to"), (4, 3, 5, 9, "Prize"), (5, 3, 5, 9, "Crossword"),
                             (1, 2, 5, 9, "23,420")]], [23500])])
# ---- a read that wrote an incomplete puzzle before the cause time is due once ("unfiled before its fix")
_un = {"id": "times-9999999", "number": 9999999, "complete": False, "wrote": True, "unfiled": 3, "clues": 27, "lights": 30}
_unrow = {"verdicts": [_un], "scan": {"item": "GaleTimes1947UKEnglish", "date": "1947-04-19"}}
# _after must stay later than f.REREAD_UNFILED, which each reader fix bumps.
_before, _after = "2026-10-19T23:11:28+00:00", "2099-01-01T00:00:00+00:00"
check("an incomplete write read before the cause time is due, with its puzzle and blank count", True,
      f.fix_reason({**_unrow, "readAt": _before}) == "unfiled before its fix"
      and f.unfiled_blank(_unrow) == [("times-9999999", 3)])
_held1 = Path(tempfile.mkdtemp()) / "times-9999999.json"
_was1 = f._HELD_PATH.get(("times", 9999999))
f._HELD_PATH[("times", 9999999)] = _held1
_held1.write_text(json.dumps({"entries": [{"clue": {"text": "a"}}, {"clue": {"text": "b"}}]}))
_whole1 = f.fix_reason({**_unrow, "readAt": _before})
_held1.write_text(json.dumps({"entries": [{"clue": {"text": "a"}}, {"clue": None}, {"x": 1}]}))
_short1 = f.fix_reason({**_unrow, "readAt": _before})
if _was1 is None:
    del f._HELD_PATH[("times", 9999999)]
else:
    f._HELD_PATH[("times", 9999999)] = _was1
check("a puzzle the corpus already holds with every clue is not due for its page's blanks; one held short still is",
      [None, "unfiled before its fix"], [_whole1, _short1])
check("one read after it (incomplete again) is not due again; nor a complete or a refused one", [None] * 3,
      [f.fix_reason({**_unrow, "readAt": _after}),
       f.fix_reason({**_unrow, "readAt": _before, "verdicts": [{**_un, "complete": True}]}),
       f.fix_reason({**_unrow, "readAt": _before, "verdicts": [{**_un, "refused": "x"}]})])
check("the reason is evidence, ranked with the fix-landed rereads and held behind never-read pages", (True, 2, True, True),
      (eq.evidence_reason("unfiled before its fix"), f.rank_of_reason("unfiled before its fix"),
       "unfiled before its fix" in eq.FIX_LANDED, eq.refusal_reread("unfiled before its fix")))
# ---- a read whose corpus write is gone is due once ("written, its file gone", fa.LOST_WRITE; 10-25)
_lw = {"id": "times-9999998", "number": 9999998, "complete": True, "wrote": True, "clues": 30, "lights": 30}
_lwrow = {"verdicts": [_lw], "scan": {"item": "GaleTimes1970UKEnglish", "date": "1970-01-02"},
          "readAt": "2026-10-14T06:48:52+00:00"}
_lw_list, _lw_ren = f._held_list, f._renamed_ids
_lw_was = f._HELD_PATH.pop(("times", 9999998), None)
try:
    f._held_list = lambda series: (1, ((1, None), (99999999, None))) if series == "times" else (1, ())
    _lw_gone = (f.fix_reason(_lwrow), f.lost_writes(_lwrow))
    _lw_past = f.lost_writes({**_lwrow, "verdicts": [{**_lw, "id": "times-199999999", "number": 199999999}]})
    _lw_after = f.fix_reason({**_lwrow, "readAt": "2099-01-01T00:00:00+00:00"})
    _lw_not = [f.lost_writes({**_lwrow, "verdicts": [{**_lw, **extra}]})
               for extra in ({"unfiled": 2}, {"refused": "x"}, {"skip": "already held"}, {"wrote": False},
                             {"answersOnly": True}, {"id": "cryptic-9999998"})]
    f._renamed_ids = lambda: {"times-9999998": "times-9999999"}
    _lw_renamed = f.lost_writes(_lwrow)
    f._renamed_ids = _lw_ren
    _lw_file = Path(tempfile.mkdtemp()) / "times-9999998.json"
    _lw_file.write_text(json.dumps({"entries": [{"clue": {"text": "a"}}]}))
    f._HELD_PATH[("times", 9999998)] = _lw_file
    _lw_held = f.lost_writes(_lwrow)
finally:
    f._held_list, f._renamed_ids = _lw_list, _lw_ren
    f._SPAN.clear()
    f._HELD_PATH.pop(("times", 9999998), None)
    if _lw_was is not None:
        f._HELD_PATH[("times", 9999998)] = _lw_was
check("a write the corpus no longer holds is due once, naming the puzzle", ("written, its file gone", ["times-9999998"]),
      _lw_gone)
check("not again once read after REREAD_LOST", None, _lw_after)
check("not an unfiled, refused, skipped, unwritten or answers-only verdict, nor one of a series with no listing", [[]] * 6,
      _lw_not)
check("not a renamed id, one whose file is held, nor a number past the series' highest (a test's, a new one's)",
      ([], [], []), (_lw_renamed, _lw_held, _lw_past))
check("the reason is evidence, ranked 2, a fix-landed reread, never skipped, and tier 0 for a newest-first paper",
      (True, 2, True, True, 0),
      (eq.evidence_reason(f.LOST_WRITE), f.rank_of_reason(f.LOST_WRITE), f.LOST_WRITE in eq.FIX_LANDED,
       f.LOST_WRITE.startswith(f.BUG_READS),
       eq.files_likely_tier(2, {"kind": "read", "paper": "gale", "reason": f.LOST_WRITE, "date": "1970-01-02"})))
# ---- A Times solution grid refused before matched_box is planned though likely() predicts it nothing (10-24)
_refused = {"kind": "read", "paper": "times", "rel": "NewsUK1984UKEnglish/1984-05-01_61715", "date": "1984-05-01",
            "reason": f.REFUSED_GRID, "rank": 2, "needs": []}
check("a grid refused unmatched is evidence: only_evidence keeps its read with no likely gain, a low-ask fix-landed one",
      (True, [f.REFUSED_GRID], True, True),
      (eq.evidence_reason(f.REFUSED_GRID), [u["reason"] for u in eq.only_evidence("times", [], [dict(_refused)])[1]],
       f.REFUSED_GRID in eq.FIX_LANDED, f.REFUSED_GRID.startswith(eq.LOW_ASK)))
# ---- The unclassified-held and unenumerated answers-only rereads are planned likewise; plain unclassified is not (10-24)
_unenum = "answers held back by a clue with no enumeration"
check("an unclassified grid of a puzzle held short, and a held clue bare of its count, are evidence (low-ask, "
      "fix-landed); a plain unclassified one, no puzzle answers_only can read, is dropped",
      ([f.UNCLASSIFIED_HELD, _unenum], True, True, True, True, False),
      ([u["reason"] for u in eq.only_evidence("times", [], [dict(_refused, reason=r) for r in
                                                           (f.UNCLASSIFIED_HELD, _unenum, "solution short, its cells unclassified")])[1]],
       f.UNCLASSIFIED_HELD in eq.FIX_LANDED, f.UNCLASSIFIED_HELD.startswith(eq.LOW_ASK), _unenum.startswith(eq.LOW_ASK),
       eq.evidence_reason(_unenum), eq.evidence_reason("solution short, its cells unclassified")))
# ---- Gale Times 2000-14 pages with evidence of a puzzle that can file are planned (10-22)
_third = {"kind": "read", "paper": "gale", "rel": "GaleTimes2007UKEnglish/2007-03-15", "date": "2007-03-15",
          "reason": eq.THREE_COLUMNS, "rank": 2, "needs": ["GaleTimes2007UKEnglish/2007-03-15", "GaleTimes2007UKEnglish/2007-03-16"]}
_s15 = {"kind": "scan", "paper": "gale", "rel": "GaleTimes2007UKEnglish/2007-03-15", "reason": "scan stale", "rank": 2, "date": "2007-03-15"}
_s16 = {**_s15, "rel": "GaleTimes2007UKEnglish/2007-03-16", "date": "2007-03-16"}
_s99 = {**_s15, "rel": "GaleTimes2007UKEnglish/2007-06-01", "date": "2007-06-01"}
_sc, _rd = eq.only_evidence("gale", [_s15, _s16, _s99], [_third, {**_third, "date": "2008-03-15"},
                                                         {**_third, "paper": "times"}])
check("a 2007 Gale short third-column read is planned, 2008's (not yet read) and another paper's are not",
      ["2007-03-15"], [u["date"] for u in _rd])
check("its own page's scan goes with it in the first tier (4633a959929); the next day's is no longer kept for a Times-series read (5c8eb3523ce), another page's scan is tier 2", ([0], 2),
      ([eq.files_likely_tier(2, u) for u in _sc], eq.files_likely_tier(2, _s99)))
_title = {**_third, "reason": "titles changed", "date": "2010-01-02"}
_nt = {**_third, "reason": f.NO_TITLE_RESCAN, "date": "2000-03-14"}
check("a Gale 2000-14 page with a title no read covered, or no title found by older scan code, is planned; a 1999 one is not",
      ["2010-01-02", "2000-03-14"], [u["date"] for u in eq.only_evidence("gale", [], [_title, _nt, {**_title, "date": "1999-01-02"}])[1]])
check("a 2005-06 title no read covered is not planned (it files nothing or only rewrites a filed puzzle)", [],
      eq.only_evidence("gale", [], [{**_title, "date": "2005-09-01"}, {**_title, "date": "2006-11-18"}])[1])
check("both go in the first tier (4633a959929), asking the VLM", (0, 0, True), (eq.files_likely_tier(2, _title), eq.files_likely_tier(2, _nt), eq.fills_gpu({**_nt, "needs": []})))
os.environ["CT_BLANKET_REREADS"] = "1"
_, rd_old =eq.plan(["times", "telegraph"], oc, q.when("2026-06-01T00:00:00+00:00"))
check("CT_BLANKET_REREADS=1 restores every reread", True, len(rd_old) == 7)
# ---- refusal rereads wait while never-read or never-scanned units remain
del os.environ["CT_REFUSAL_REREADS"]
notes_h = []
sc_h, rd_h = eq.plan(["times", "telegraph"], oc, q.when("2026-06-01T00:00:00+00:00"), out=notes_h)
check("refusal rereads are held while never-read units remain; the new ones stay",
      {"1992-01-01_1", "1990-06-01_1", "1990-05-01_1", "1985-01-01_1", "1999-01-01_1", "1995-01-01_1"},
      {u["rel"].split("/")[1] for u in rd_h})
check("one note says how many were held and why", True,
      sum("refusal rereads: held 1" in n and "never-read" in n for n in notes_h) == 1)
os.environ["CT_REFUSAL_REREADS"] = "1"
_, rd_k = eq.plan(["times", "telegraph"], oc, q.when("2026-06-01T00:00:00+00:00"))
check("CT_REFUSAL_REREADS=1 keeps the refusal reread", True, "1970-01-01_1" in {u["rel"].split("/")[1] for u in rd_k})
del os.environ["CT_REFUSAL_REREADS"]
unit_n = {"paper": "times", "rel": "X/n", "reason": "never read", "needs": ["X/n"]}
unit_c = {"paper": "times", "rel": "X/c", "reason": "refused not-a-grid before its fix", "needs": ["X/c"]}
unit_a = {"paper": "times", "rel": "X/a", "reason": "annotation asked", "needs": []}
unit_t = {"paper": "trove", "rel": "t1", "reason": "no-grid cured since", "needs": []}
scan_c = {"paper": "times", "rel": "X/c", "reason": "scan stale"}
tup = lambda u: (0, 0, 0, u)
sc_x, rd_x = eq.hold_refusal_rereads([tup(scan_c)], [tup(unit_n), tup(unit_c), tup(unit_a), tup(unit_t)])
check("held: cured-since and fix-landed reads go, annotation asked stays, and the scan only they needed",
      (["X/n", "X/a"], []), ([t[3]["rel"] for t in rd_x], sc_x))
sc_y, rd_y = eq.hold_refusal_rereads([], [tup(unit_c), tup(unit_t)])
check("with no new unit left the refusal rereads come back", 2, len(rd_y))
unit_l = {"paper": "listener", "rel": "GALE_GM1.pdf", "reason": "refused clues-short before its fix", "needs": []}
_, rd_l = eq.hold_refusal_rereads([], [tup(unit_n), tup(unit_l), tup(unit_c)])
check("a Listener refusal reread (local OCR, no VLM) is not held", ["X/n", "GALE_GM1.pdf"], [t[3]["rel"] for t in rd_l])

# ---- canary-proven refusal rereads skip the hold and go right after the never-read work
gk = lambda rel, date, reason="refused no-reading-parses before its fix", paper="gale": tup(
    {"paper": paper, "rel": rel, "reason": reason, "date": date, "needs": []})
_, rd_p = eq.hold_refusal_rereads([], [tup(unit_n), gk("g61", "1961-05-01"), gk("g70", "1970-05-01"), gk("g05", "2005-03-02"),
                                       gk("t61", "1961-05-01", paper="times"), tup(unit_c)], notes_p := [])
_, rd_nf = (os.environ.__setitem__("CT_NEWEST_FIRST", "times"), eq.hold_refusal_rereads([], [tup(unit_n), tup(unit_c), tup(unit_t)]))[1]
del os.environ["CT_NEWEST_FIRST"]
check("CT_NEWEST_FIRST papers' refusal rereads are not held", ["X/n", "X/c"], [t[3]["rel"] for t in rd_nf])
check("canary: only gale no-reading-parses of 1960-66 and 2005-06 survive the hold", ["X/n", "g61", "g05"],
      [t[3]["rel"] for t in rd_p])
check("canary: one note counts the kept", 1, sum("canary-proven rereads: kept 2 (" in n for n in notes_p))
uf = "unfiled before its fix"
_, rd_u = eq.hold_refusal_rereads([], [tup(unit_n), gk("g05", "2005-03-02", uf), gk("g70", "1970-05-01", uf),
                                       gk("f86", "1986-03-02", uf, paper="ft"), gk("f87", "1987-03-02", uf, paper="ft"),
                                       gk("t05", "2005-03-02", uf, paper="times")], notes_u := [])
check("canary: unfiled before its fix survives for gale 2005-06 and ft 1986 only", ["X/n", "g05", "f86"],
      [t[3]["rel"] for t in rd_u])
os.environ["CT_NEWEST_FIRST"] = "gale"
gu = lambda *a, **k: gk(*a, **k)[3]
ordered = eq.by_urgency([(2, 0, 0, gu("g61", "1961-05-01")), (2, 0, 1, gu("g70", "1970-05-01")),
                         (2, 1, 0, {**unit_c, "date": "2000-01-01"}), (1, 1, 1, {**unit_n, "date": "1990-01-01"}),
                         (1, 0, 2, {**unit_n, "rel": "gnew", "paper": "gale", "date": "2001-01-01"})])
check("named papers first: never-read, then proven, then fix-landed rereads, then other papers", ["gnew", "g61", "g70", "X/n"],
      [u["rel"] for u in ordered][:4])
check("named papers' proven rereads go before other papers' never-read work", ["gnew", "g61", "X/n", "X/m"],
      [u["rel"] for u in eq.by_urgency([(2, 0, 0, gu("g61", "1961-05-01")), (1, 1, 1, {**unit_n, "date": "1990-01-01"}),
                                        (1, 1, 2, {**unit_n, "rel": "X/m", "date": "1989-01-01"}),
                                        (1, 0, 2, {**unit_n, "rel": "gnew", "paper": "gale", "date": "2001-01-01"})])])
del os.environ["CT_NEWEST_FIRST"]

# ---- low-yield Trove years wait while other never-read units remain
tv = lambda rel, date, reason="never read": tup({"paper": "trove", "rel": rel, "reason": reason, "date": date, "needs": []})
_, rd_l = eq.hold_low_yield_eras([], [tv("a", "1980-01-01"), tv("b", "1990-01-01"), tv("c", "1972-12-31"),
                                       tv("d", "1989-12-31"), tv("e", "1980-01-01", "inputs changed"), tup(unit_n)], notes_l := [])
check("low-yield: 1973-1989 never-read Trove goes, other years/reasons/papers stay", ["b", "c", "e", "X/n"], [t[3]["rel"] for t in rd_l])
check("low-yield: one note counts the held", True, len(notes_l) == 1 and "held 2" in notes_l[0])
_, rd_m = eq.hold_low_yield_eras([], [tv("a", "1980-01-01")], notes_m := [])
check("low-yield: with no other never-read unit they come back", 1, len(rd_m))
os.environ["CT_LOW_YIELD_ERAS"] = "1"
_, rd_o = eq.hold_low_yield_eras([], [tv("a", "1980-01-01"), tup(unit_n)])
check("CT_LOW_YIELD_ERAS=1 keeps them", 2, len(rd_o))
del os.environ["CT_LOW_YIELD_ERAS"]

f.edition_dirs, f.input_hash = listing, hashes

# ---- likely(): within a rank, the re-reads predicted to file a puzzle whole go first
lc = T / "likely"
def led_ed(name):
    d = lc / "NewsUK1980UKEnglish" / name
    d.mkdir(parents=True)
    (d / "pages.json").write_text("{}")
    return d
L = {n: led_ed(n) for n in ("1980-01-21_0", "1980-01-22_0", "1980-02-04_1", "1980-02-05_2", "1980-02-06_3",
                            "1980-02-12_9", "1980-02-13_10")}
def lrow(name, titles, verdicts, sols=(), **kw):
    sc = {"date": name[:10], "puzzles": [{"number": n, "leaf": 1, "box": None} for n in titles],
          "solutions": [{"number": n, "leaf": 1, "box": None} for n in sols]}
    return {"edition": f"NewsUK1980UKEnglish/{name}", "filesHash": "h", "scanKey": "old", "scan": sc, "inputs": "h",
            "solutionsSeen": [], "verdicts": verdicts, "readAt": "2026-10-01T00:00:00+00:00", **kw}
def v(n, **kw):
    return {"number": n, "id": f"times-{n}", **kw}
part = lambda gap: {"solutionFrom": "x", "solution": {"lights": 30, "accepted": 30 - gap}}
q.append(lc / "filed.jsonl", [
    lrow("1980-02-04_1", [90100], [v(90100)]),  # answerless; 02-05's stored heading links it now
    lrow("1980-02-05_2", [90101], [v(90101)], sols=[90100]),  # answerless, a later edition held: rank 2; 02-06's text prints its heading
    lrow("1980-02-06_3", [90102], [v(90102, **part(5))]),  # the next issue of 90101: its text links it
    lrow("1980-02-12_9", [90104], [v(90104)]),  # answerless, a later edition held: rank 2; its next issue's text links nothing
    lrow("1980-02-13_10", [90105], [v(90105)]),  # the next issue of 90104, newer than 02-06
    lrow("1980-01-21_0", [90090], [v(90090, **part(1))], scanKey=f.scan_key()),  # a grid two lights short
    lrow("1980-01-22_0", [90091], [v(90091, **part(5))], scanKey=f.scan_key())])  # mirror: five short, newer
real = (f.edition_dirs, f.input_hash, f.linked_solutions, f.text_headings, dict(f._HELD_PATH))
f.edition_dirs = lambda cache=None, paper=None: list(L.values()) if (paper or f.TIMES).key == "times" else []
f.input_hash = lambda d: "h"
f.linked_solutions = lambda paper, found, held: found["solutions"]
text_read = []
f.text_headings = lambda d, deadline=None: text_read.append(d.name) or (
    [(90101, 1)] if d.name == "1980-02-06_3" else [])
f._HELD_PATH.clear()
_, reads = f.plan(f.TIMES, lc)
got = [(u["rel"].split("/")[1], u["reason"], u["rank"], u.get("likely")) for u in reads]
check("a stale scan whose puzzle a stored heading now answers ranks 2, not with the whole corpus",
      ("1980-02-04_1", "scan stale, answers linked", 2, {"answers linked": 1}),
      next(g for g in got if g[0] == "1980-02-04_1"))
check("within rank 2 the predicted re-reads go first, newest first among equals; then the rest newest first",
      ["1980-02-06_3", "1980-02-04_1", "1980-01-21_0", "1980-02-13_10", "1980-02-12_9", "1980-02-05_2",
       "1980-01-22_0"],
      [g[0] for g in got if g[2] == 2])
check("the next issue of an answerless puzzle its text links is predicted; one its text does not link is not",
      ({"answers in the next issue's text": 1}, None),
      tuple(next(g[3] for g in got if g[0] == n) for n in ("1980-02-06_3", "1980-02-13_10")))
check("a grid read before read_framed two lights short is predicted, five short not",
      ({"solution grid read before read_framed": 1}, None),
      tuple(next(g[3] for g in got if g[0] == n) for n in ("1980-01-21_0", "1980-01-22_0")))
check("only the editions due as an answerless puzzle's next issue have their text read",
      ["1980-02-05_2", "1980-02-06_3", "1980-02-12_9", "1980-02-13_10"], sorted(text_read))
whole = T / "times-90100.json"
whole.write_text(json.dumps({"entries": [{"clue": "c", "solution": "S"}]}))
f._HELD_PATH[("times", 90100)] = whole
_, reads = f.plan(f.TIMES, lc)
check("mirror: a puzzle filed whole already (its answers from elsewhere) is not predicted, nor promoted",
      ("scan stale", 3, None), next((u["reason"], u["rank"], u.get("likely")) for u in reads
                                    if u["rel"].endswith("02-04_1")))
check("eq.by_urgency: rank first, then predicted puzzles, then newest",
      ["new", "likely", "newer", "old"],
      [u["rel"] for u in eq.by_urgency([(2, 0, 0, {"rel": "newer", "date": "1999"}),
                                        (2, 1, 0, {"rel": "likely", "date": "1980", "likely": {"x": 1}}),
                                        (2, 0, 1, {"rel": "old", "date": "1970"}),
                                        (1, 0, 2, {"rel": "new", "date": "1960"})])])
nf_units = [(2, 0, 0, {"rel": "gale-old-gain", "date": "1947", "paper": "gale", "rank": 2, "likely": {"x": 5}}),
            (3, 0, 1, {"rel": "gale-new", "date": "1999", "paper": "gale", "rank": 3}),
            (1, 1, 0, {"rel": "other", "date": "2000", "paper": "guardian", "rank": 1}),
            (0, 0, 2, {"rel": "gale-hand", "date": "1900", "paper": "gale", "rank": 0}),
            (5, 2, 0, {"rel": "times-mid", "date": "1980", "paper": "times", "rank": 5})]
check("eq.by_urgency: CT_NEWEST_FIRST unset leaves the order alone",
      ["gale-hand", "other", "gale-old-gain", "gale-new", "times-mid"],
      [u["rel"] for u in eq.by_urgency(nf_units)])
os.environ["CT_NEWEST_FIRST"] = "gale, times"
check("eq.by_urgency: CT_NEWEST_FIRST puts those papers' never-read first, then likely filers, then their rereads alternating with other papers' work (Paul 10-21, 10-24)",
      ["gale-hand", "gale-old-gain", "gale-new", "other", "times-mid"],
      [u["rel"] for u in eq.by_urgency(nf_units)])
check("eq.by_urgency: the Listener's pages go after the newest-first papers' never-read, ahead of the rest (Paul 10-23, 10-24)",
      ["gale-hand", "listener-page", "gale-old-gain", "gale-new", "other", "times-mid"],
      [u["rel"] for u in eq.by_urgency(nf_units + [(0, 1, 0, {"rel": "listener-page", "paper": "listener", "rank": 0,
                                                               "kind": "read", "reason": "never read (Gale fetch)"})])])
lu = lambda rel, rank, reason: (rank, 1, 0, {"rel": rel, "paper": "listener", "rank": rank, "kind": "read", "reason": reason})
check("eq.by_urgency: the Listener's pages read short before a fix alternate with its never-read ones",
      ["l-short", "l-new1", "l-unparsed", "l-new2", "l-new3"],
      [u["rel"] for u in eq.by_urgency([lu("l-new1", 0, "never read (Gale fetch)"), lu("l-new2", 0, "never read (Gale fetch)"),
                                        lu("l-new3", 0, "never read (Gale fetch)"),
                                        lu("l-short", 2, "refused clues-short before its fix"),
                                        lu("l-unparsed", 2, "refused no-reading-parses before its fix")])])
rr = lambda rel, date, reason, **k: (2, 0, 0, {"rel": rel, "date": date, "paper": "times", "rank": 2, "reason": reason, **k})
check("eq.by_urgency: CT_NEWEST_FIRST, never read first, then rereads after a refusal or short read, then ones whose page holds the puzzle",
      ["never", "refused", "short", "changed-new", "changed-old"],
      [u["rel"] for u in eq.by_urgency([
          rr("changed-new", "2020", "inputs changed"),
          rr("short", "2010", "short Times page, its third clue column read since"),
          rr("changed-old", "2000", "inputs changed"),
          rr("refused", "2015", "refused no-reading-parses before its fix"),
          (1, 0, 0, {"rel": "never", "date": "1990", "paper": "times", "rank": 1, "reason": "never read"})])])
gr = lambda rel, date, reason, **k: (2, 0, 0, {"rel": rel, "date": date, "paper": "gale", "rank": 2, "reason": reason, **k})
check("eq.by_urgency: CT_NEWEST_FIRST, a Gale 2007 short page and a 2000 no-title rescan go with the likely filers, not behind (Paul 10-22)",
      ["likely80", "notitle00", "short07", "changed"],
      [u["rel"] for u in eq.by_urgency([
          gr("changed", "2020", "inputs changed"),
          gr("likely80", "1980", "solution short, read by other code", likely={"x": 1}),
          gr("notitle00", "2000", f.NO_TITLE_RESCAN),
          gr("short07", "2007", "short Times page, its third clue column read since")])])
check("eq.by_urgency: CT_NEWEST_FIRST, the named papers' solution rereads first, their other rereads alternate one for one with another paper's never-read (Paul 10-21, 10-24)",
      ["short", "never", "ft-never", "changed", "ft-stale"],
      [u["rel"] for u in eq.by_urgency([
          rr("changed", "2020", "inputs changed"),
          rr("short", "2010", "solution short, read by other code"),
          (3, 1, 0, {"rel": "ft-stale", "date": "1985", "paper": "ft", "rank": 3, "reason": "scan stale"}),
          (1, 1, 1, {"rel": "ft-never", "date": "1980", "paper": "ft", "rank": 1, "reason": "never read"}),
          (1, 0, 0, {"rel": "never", "date": "1990", "paper": "times", "rank": 1, "reason": "never read"})])])
# Paul 10-24: "Remember times is the most important", "getting them with their solutions is highest priority":
# every Times solution reread (and a scan one waits on, `serves`) goes ahead of the Times never-read, which go
# ahead of the Listener's, ahead of the rest; a solution reread is not interleaved with any other paper's.
ts = [rr("t-wide", "1990", f.SHORT_WIDE), gr("g-unlisted", "1980", f.UNLISTED), gr("g-grid", "1970", f.REFUSED_GRID),
      rr("t-linked", "1960", "scan stale, answers linked"),
      (0, 0, 1, {"rel": "g-never", "date": "2001", "paper": "gale", "rank": 0, "reason": "never read (Gale fetch)"}),
      (1, 1, 1, {"rel": "tg-never", "date": "2002", "paper": "telegraph", "rank": 1, "reason": "never read"}),
      lu("l-new", 0, "never read (Gale fetch)")]
check("eq.by_urgency: Times solution rereads, then Times never-read, then the Listener, then others (Paul 10-24)",
      ["t-wide", "g-unlisted", "g-grid", "t-linked", "g-never", "l-new", "tg-never"],
      [u["rel"] for u in eq.by_urgency(ts)])
sc = lambda rel, rank, reason, paper="gale": (rank, 0, 0, {"rel": rel, "date": "1990", "paper": paper, "rank": rank,
                                                         "kind": "scan", "reason": reason})
check("eq.by_urgency: a Times stale scan a solution reread waits on (serves) goes ahead of never-scanned pages",
      ["s-host", "s-serves", "s-never", "s-stale", "tg-scan"],
      [u["rel"] for u in eq.by_urgency([sc("s-never", 0, "never scanned"), sc("s-stale", 2, "scan stale"),
                                        sc("s-serves", 2, "scan stale"), sc("s-host", 1, f.HOST_SCAN),
                                        sc("tg-scan", 1, "never scanned", "telegraph")],
                                       serves={("gale", "s-serves")})])
check("eq.solution_needs: a Times solution read's own edition and needs, not another paper's or a never-read's",
      {("gale", "R"), ("gale", "N")},
      eq.solution_needs([{"paper": "gale", "rel": "R", "reason": f.UNLISTED, "needs": ["N"]},
                         {"paper": "gale", "rel": "X", "reason": "never read", "needs": ["Y"]},
                         {"paper": "telegraph", "rel": "T", "reason": f.UNLISTED, "needs": []}]))
check("eq.newest_first: a named paper's unit, not rank 0", [True, False, False],
      [eq.newest_first(u) for u in (nf_units[1][3], nf_units[2][3], nf_units[3][3])])
del os.environ["CT_NEWEST_FIRST"]
mend = {"readAt": "2026-10-09T00:00:00+00:00"}
check("blanks a vote fix landed for since the read, answers whole: predicted",
      "blanks a vote fix mends", f.short_cause("times", mend, v(90200, blank={"1-a": "'qx': not a word"}, **part(0)), {}))
check("mirror: a blank no vote fix mends holds it", None,
      f.short_cause("times", mend, v(90200, blank={"1-a": "junk"}, **part(0)), {}))
check("mirror: read after the fix, the same blank holds it", None,
      f.short_cause("times", {"readAt": "2099-01-01T00:00:00+00:00"}, v(90200, blank={"1-a": "'qx': not a word"},
                                                                        **part(0)), {}))
# A Times grid read by other code (solution_key) that left at most SHORT_GAP lights, on a lattice the
# classifier trusts (blocks), is read again for fitted_reads and the VLM's strips; read by the
# current code, or with the blocks unsure, or more lights short, or another paper's, it is not.
def classified_part(gap, blocks=1.0, **kw):
    return {"solutionFrom": "x", "solution": {"lights": 30, "accepted": 30 - gap, "lattices": 3, "blocks": blocks, **kw}}
old_read = {"edition": "NewsUK1980UKEnglish/1980-01-21_0", "solutionKey": "old"}
check("a classified grid read by other code, three lights short: predicted for the fitted and VLM reads",
      f.LIKELY[4], f.short_cause("times", old_read, v(90210, **classified_part(3)), {}))
check("mirror: read by the current code, three lights short, it is not", None,
      f.short_cause("times", {**old_read, "solutionKey": f.solution_key()}, v(90210, **classified_part(3)), {}))
# Read by the current code's full read (no enumerations: no fitted read, no strip asked) and at most
# STRIP_MAX lights short, before REREAD_SHORT_FITTED: predicted too, whatever its blocks (SHORT_UNFITTED).
cur_read = {**old_read, "solutionKey": f.solution_key(), "readAt": "2026-10-23T00:00:00+00:00"}
check("a grid this code's full read left two lights short, before the fitted reread: predicted",
      [f.LIKELY[4], f.LIKELY[4]],
      [f.short_cause("times", cur_read, v(90210, **classified_part(2)), {}),
       f.short_cause("times", cur_read, v(90210, **classified_part(1, blocks=0.9)), {})])
# Read after REREAD_UNLISTED too: before it, a grid at most STRIP_MAX short is read again for unlisted
# words (LIKELY[6], c766e6cf936), answers_only or not.
import datetime
after_read = {**cur_read, "readAt": (q.when(f.REREAD_UNLISTED) + datetime.timedelta(days=1)).isoformat()}
check("mirror: read after REREAD_SHORT_FITTED, or by answers_only, it is not", [None, None],
      [f.short_cause("times", after_read, v(90210, **classified_part(2)), {}),
       f.short_cause("times", after_read, v(90210, answersOnly=True, **classified_part(2)), {})])
check("mirror: more than SHORT_GAP lights short, blocks unsure, or refused", (None, None, None),
      (f.short_cause("times", old_read, v(90210, **classified_part(f.SHORT_GAP + 1)), {}),
       f.short_cause("times", old_read, v(90210, **classified_part(2, blocks=0.9)), {}),
       f.short_cause("times", old_read, v(90210, **classified_part(2, refused="its blocks are not the puzzle's")), {})))
check("mirror: another paper's grid (the classifier reads only the Times's) is not", None,
      f.short_cause("times", {**old_read, "edition": "FinancialTimes1980UKEnglish/1980-01-21_0"},
                    v(90210, **classified_part(3)), {}))
f.edition_dirs, f.input_hash, f.linked_solutions, f.text_headings = real[:4]
f._HELD_PATH.clear()
f._HELD_PATH.update(real[4])

# ---- the queue's order across papers
os.utime(g2 / "pages.json", (time.time(), time.time()))
scans, reads = eq.plan(["gale", "times"], cache, before)
check("rank 0 first (Gale by hand), then never read, then the rest",
      ["1987-03-03", "1987-03-02", "1980-03-01_3", "1980-01-02_2", "1980-01-01_1"],
      [u["rel"].split("/")[1] for u in reads])
check("edition_queue takes no --newer-than: one queue, the fresh ones first", False,
      "--newer-than" in Path(eq.__file__).read_text())

# ---- fresh(): the editions just laid out, found without a plan
fc = T / "fresh-cache"
now = time.time()
def laid(item, name, staged):
    d = fc / item / name
    d.mkdir(parents=True)
    (d / "pages.json").write_text("{}")
    os.utime(d / "pages.json", (staged, staged))
    return d
gi = "GaleTimes1990UKEnglish"
laid(gi, "1990-01-02", now - 10)
laid(gi, "1990-01-03", now - 5)
laid(gi, "1990-01-01", now - f.FRESH - 10)  # laid out before FRESH: the plan's
done = laid(gi, "1990-01-04", now - 20)  # read with its current files
q.append(fc / f.LEDGER_NAMES["gale"], [{"edition": f"{gi}/1990-01-04", "inputs": "x", "filesHash": f.input_hash(done)}])
laid("NewsUK1980UKEnglish", "1980-01-05_1", now - 30)
laid("NewsUK1981UKEnglish", "1981-01-05_1", now - 30)
os.utime(fc / "NewsUK1981UKEnglish", (now - f.FRESH - 10, now - f.FRESH - 10))  # an item unmoved: not looked in
fs, fr = eq.fresh(["gale", "listener", "times", "trove"], fc, now)
check("fresh: never-read editions laid out within FRESH, any paper, latest laid out first",
      [f"{gi}/1990-01-03", f"{gi}/1990-01-02", "NewsUK1980UKEnglish/1980-01-05_1"], [u["rel"] for u in fr])
check("each a scan too, ranked just laid out (0), ahead of the never read",
      ([u["rel"] for u in fr], {0}, {"just laid out"}, True),
      ([u["rel"] for u in fs], {u["rank"] for u in fs + fr}, {u["reason"] for u in fs + fr},
       f.RANKS["just laid out"] < f.RANKS["never read"]))
check("a fresh read needs its own scan and the fresh days after it", [f"{gi}/1990-01-02", f"{gi}/1990-01-03"],
      fr[1]["needs"])
check("nothing once past FRESH", ([], []), eq.fresh(["gale", "times"], fc, now + f.FRESH + 60))
with q.lock(cache / "filed-gale.jsonl"):
    notes = []
    scans, reads = eq.plan(["gale", "times"], cache, before, out=notes)
    check("a paper whose ledger a batch run holds is left out, and said", (False, True),
          (any(u["paper"] == "gale" for u in reads), "gale: a run holds" in notes[0]))
notes = []
eq.plan(["gale", "times"], cache, before, out=notes)
check("a quick plan adds no timing note", [], [n for n in notes if n.startswith("slow plan")])
was, eq.SLOW_PLAN = eq.SLOW_PLAN, 0
notes = []
eq.plan(["gale", "times"], cache, before, out=notes)
eq.SLOW_PLAN = was
check("a slow plan names the papers it spent its seconds on",
      (1, True), (len([n for n in notes if n.startswith("slow plan: papers took")]),
                  all(p in notes[-1] for p in ("gale", "times"))))

# ---- the queue is built once and consumed: a plan whose inputs did not move is the last one's lists
# themselves, and one after units finish or inputs change equals the whole plan derived afresh
# (Paul 10-17: "Don't we just have a queue to burn through").
bq = T / "built-queue"
real_root = eq.media_manifest.downloads.ROOT
eq.media_manifest.downloads.ROOT = T  # the cache counts as on the media disk: plans are stamped
real_mm, real_dirs = eq.media_manifest.DIR, f.edition_dirs
eq.media_manifest.DIR = T / "built-queue-manifest"  # the edition manifests a fetcher appends a row to
eq.media_manifest.DIR.mkdir()
f.edition_dirs = lambda cache=None, paper=None: (
    sorted((bq / "NewsUK1981UKEnglish").iterdir()) if (paper or f.TIMES).key == "times" else [])
probes = []
real_reachable = f.vlm.reachable
f.vlm.reachable = lambda: probes.append(1) or False
def bq_edition(item, name, content="{}"):
    d = bq / item / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "pages.json").write_text(content)
    eq.media_manifest.record_edition(d)  # as the fetcher does when it lays an edition out
    for x in (d, d.parent, bq):
        os.utime(x, (time.time() - 600, time.time() - 600))
    return d
bq_dirs = [bq_edition("NewsUK1981UKEnglish", f"1981-0{m}-0{m}_{m}") for m in (1, 2, 3)]
def bq_row(d):
    fh, found = f.input_hash(d), {"puzzles": [], "solutions": []}
    return {"edition": f"{d.parent.name}/{d.name}", "filesHash": fh, "scanKey": f.scan_key(), "scan": found,
            "inputs": f.inputs_of(fh, found, f.TIMES.series), "solutionsSeen": [], "verdicts": [],
            "readAt": "2026-01-01T00:00:00+00:00"}
def bq_whole(reread=None):
    """The plan derived from nothing (every memo of the planner set aside, then put back)."""
    memos = (eq._QUEUE, f._PLANNED, f._PAPER_PLANS)
    kept = [dict(m) for m in memos]
    for m in memos:
        m.clear()
    try:
        return eq.plan(["times"], bq, reread)
    finally:
        for m, k in zip(memos, kept):
            m.clear()
            m.update(k)
def bq_units(plan):
    return [[(u["kind"], u["rel"], u["rank"], u["reason"]) for u in us] for us in plan]
first_plan = eq.plan(["times"], bq)
check("the first plan of a cache reads each edition due", 3, len(first_plan[1]))
n_probes = len(probes)
again = eq.plan(["times"], bq)
check("a plan whose inputs did not move is the last one's lists themselves, the VLM not probed again",
      (True, True, n_probes + 1), (again[0] is first_plan[0], again[1] is first_plan[1], len(probes)))
probes.clear()
eq._QUEUE.clear()
f._PLANNED.clear()
eq.plan(["times"], bq)
check("a whole plan probes the VLM once, not once a paper per stamp and plan", 1, len(probes))
import subprocess
q.append(bq / "filed.jsonl", [bq_row(bq_dirs[0])])
done_plan = eq.plan(["times"], bq)
check("a unit's row landing: the incremental plan is the whole plan, the edition dropped out",
      (bq_units(bq_whole()), False), (bq_units(done_plan), any(u["rel"].endswith(bq_dirs[0].name) for u in done_plan[1])))
q.append(bq / "filed.jsonl", [bq_row(bq_dirs[1]), {**bq_row(bq_dirs[0]), "inputs": "moved"}])
check("more rows, one moved: still the whole plan", bq_units(bq_whole()), bq_units(eq.plan(["times"], bq)))
bq_edition("NewsUK1981UKEnglish", "1981-04-04_4")
check("a new scan laid out: the whole plan again, the new edition in it", (bq_units(bq_whole()), True),
      (bq_units(eq.plan(["times"], bq)), any(u["rel"].endswith("1981-04-04_4") for u in eq.plan(["times"], bq)[1])))
bq_edition("NewsUK1981UKEnglish", bq_dirs[2].name, '{"moved": 1}')
check("a file of an edition moved: the whole plan again", bq_units(bq_whole()), bq_units(eq.plan(["times"], bq)))
cutoff = q.when("2099-01-01T00:00:00+00:00")
check("a --reread cutoff: the whole plan again, rows read before it due", (bq_units(bq_whole(cutoff)), True),
      (bq_units(eq.plan(["times"], bq, cutoff)), len(eq.plan(["times"], bq, cutoff)[1]) > len(eq.plan(["times"], bq)[1])))
check("and back without it", bq_units(bq_whole()), bq_units(eq.plan(["times"], bq)))
os.environ["CT_NEWEST_FIRST"] = "times"
try:
    check("CT_NEWEST_FIRST changed: the whole plan again, in its order", bq_units(bq_whole()), bq_units(eq.plan(["times"], bq)))
    with_env = eq.plan_version(eq.code_files())
finally:
    del os.environ["CT_NEWEST_FIRST"]
check("a kept plan is not used by other code or environment: its version moves with CT_NEWEST_FIRST",
      False, eq.plan_version(eq.code_files()) == with_env)
f.vlm.reachable = real_reachable
f.edition_dirs = real_dirs
eq.media_manifest.downloads.ROOT = real_root
eq.media_manifest.DIR = real_mm

# ---- the units: each appends its own row, never another's
calls = []
f.scan = lambda d: calls.append(("scan", d.name)) or {"puzzles": [{"number": 7, "leaf": 1, "box": None}], "solutions": []}
f.held_numbers = lambda series="times": set()
f.held_dates = lambda series: {}
def fake_read(d, found, hit, solutions):
    calls.append(("read", d.name))
    return {"number": hit["number"], "refused": "x"}, None
f.read_puzzle = fake_read
import ocr_remote
ocr_remote.edition = lambda d, found, sols: None
lines_before = len(tl.read_text().splitlines())
check("scan_unit scans and appends one row", ("scanned", [("scan", "1980-03-01_3")], lines_before + 1),
      (f.scan_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-01_3", cache), calls, len(tl.read_text().splitlines())))
check("a scan that stands is not made again", "current", f.scan_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-01_3", cache))
# A unit's desktop read meeting a busy desktop: deferred, no ledger row, no
# failure; with no desktop set the same unit reads here.
t4 = edition("NewsUK1980UKEnglish", "1980-03-08_4", 10)
real_busy, real_failure, failed = ocr_remote.desktop_busy.busy, q.failure, []
ocr_remote.desktop_busy.busy = lambda hosts: "playing Wow"
q.failure = lambda *a, **k: failed.append(a)
os.environ.update(OCR_REMOTE="tester@100.64.0.15", OCR_REMOTE_DEFER="1")
lines_before = len(tl.read_text().splitlines())
with contextlib.redirect_stderr(io.StringIO()):
    got = eq.unit_status({"kind": "scan", "paper": "times", "rel": "NewsUK1980UKEnglish/1980-03-08_4"},
                         lambda: f.scan_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-08_4", cache))
check("a unit whose desktop read meets a busy desktop ends deferred: no row, no failure, nothing read here",
      (eq.EXITS["deferred"], lines_before, [], []), (got, len(tl.read_text().splitlines()), failed, calls[1:]))
del os.environ["OCR_REMOTE_DEFER"]
check("a process that does not defer reads here while the desktop is busy", None, ocr_remote.session())
os.environ.update(OCR_REMOTE="", OCR_REMOTE_DEFER="1")
with contextlib.redirect_stderr(io.StringIO()):
    got = eq.unit_status({"kind": "scan", "paper": "times", "rel": "NewsUK1980UKEnglish/1980-03-08_4"},
                         lambda: f.scan_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-08_4", cache))
check("mirror: with no desktop set the same unit scans here and appends its row",
      (0, lines_before + 1, ("scan", "1980-03-08_4")), (got, len(tl.read_text().splitlines()), calls[-1]))
ocr_remote.desktop_busy.busy, q.failure = real_busy, real_failure
for k in ("OCR_REMOTE", "OCR_REMOTE_DEFER"):
    os.environ.pop(k, None)
calls.clear()
with contextlib.redirect_stderr(io.StringIO()):
    got = f.read_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-01_3", cache, out=io.StringIO())
rows = q.ledger_rows(tl, "edition")
check("read_unit reads its edition alone and appends its row", ("read", [("read", "1980-03-01_3")], lines_before + 2, True),
      (got, calls, len(tl.read_text().splitlines()), "readAt" in rows["NewsUK1980UKEnglish/1980-03-01_3"]))
calls.clear()
err = io.StringIO()
with contextlib.redirect_stderr(err):
    f.read_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-01_3", cache, out=io.StringIO())
check("a unit whose edition is no longer due reads nothing", ([], True), (calls, "not due" in err.getvalue()))
listed = f.edition_dirs
def no_listing(*a, **k):
    raise AssertionError("a unit after a plan lists no items")
f.edition_dirs = no_listing
with contextlib.redirect_stderr(io.StringIO()):
    f.read_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-01_3", cache, out=io.StringIO(), force=True)
f.edition_dirs = listed
check("forced (annotation asked), it reads anyway, off the plan's listing", [("read", "1980-03-01_3")], calls)
with q.source_lock(tl, "NewsUK1980UKEnglish/1980-03-01_3"):
    pid = os.fork()
    if pid == 0:
        os._exit(0 if f.read_unit(f.TIMES, "NewsUK1980UKEnglish/1980-03-01_3", cache) == "busy" else 1)
    check("an edition another unit holds is busy", 0, os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))
q.UNIT_HOLD_WAIT = 0.5  # a batch run's hold outlasts it
with q.lock(tl):
    pid = os.fork()
    if pid == 0:
        os._exit(0 if f.scan_unit(f.TIMES, "NewsUK1980UKEnglish/1980-01-02_2", cache) == "held" else 1)
    check("a ledger a batch run holds is held: the unit adds nothing", 0, os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))

# ---- a scan keyed with the thread-pool sizing in is current, and re-keyed, not rescanned
rk = T / "rekey.jsonl"
q.append(rk, [{"edition": "a", "scanKey": f.sized_scan_key()}, {"edition": "b", "scanKey": "older"}])
check("a row under the sized key is current until re-keyed; one under older code is not",
      (True, False), tuple(f.scan_current({"filesHash": "h", "scanKey": k, "scan": {}}, "h") for k in (f.sized_scan_key(), "older")))
check("rows under the sized key take the narrowed one; others stay stale; once", (1, [f.scan_key(), "older"], 0),
      (f.rekey_scans(rk), [r["scanKey"] for r in q.jsonl_rows(rk)], f.rekey_scans(rk)))

# ---- a unit's own process: its outcome is its exit status, an error logged
for outcome, want in (("busy", 3), ("read", 0)):
    eq.run_unit = lambda unit, cache, puzzles, reread, o=outcome: o
    pid = os.fork()
    if pid == 0:
        os._exit(eq.unit_main({"unit": {"kind": "read", "paper": "times", "rel": "x"}, "cache": str(T),
                               "puzzles": None, "reread": "2026-01-01T00:00:00+00:00"}))
    check(f"unit_main: {outcome} exits {want}", want, os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))
def boom(unit, cache, puzzles, reread):
    raise ValueError("bad page")
eq.run_unit = boom
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.dup2(w, 2)
    sys.stderr = os.fdopen(2, "w")
    os._exit(eq.unit_main({"unit": {"kind": "read", "paper": "times", "rel": "x"}, "cache": str(T),
                           "puzzles": None, "reread": None}))
os.close(w)
said = os.fdopen(r).read()
check("unit_main: an error exits 1, the traceback logged", (1, True),
      (os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), "failed x: ValueError: bad page" in said))

# ---- the dispatcher: order, gating, limits, --seconds, TERM
# Each unit is started as a fresh process of eq.UNIT_SCRIPT, here a fake
# (named as the real one, for ps) whose behaviour each case writes.
log = T / "units.log"
fake_dir = T / "fake"
fake_dir.mkdir()
eq.UNIT_SCRIPT = fake_dir / "edition_queue.py"
behaviour = T / "behaviour.json"
eq.UNIT_SCRIPT.write_text(f"""import json, os, subprocess, sys, time
VERSION = "v1"
unit = json.loads(os.environ["CT_EDITION_UNIT"])["unit"]
b = json.loads(open({str(behaviour)!r}).read())
def say(line):
    with open({str(log)!r}, "a") as fh:
        fh.write(line + "\\n")
if b.get("ps"):
    say(unit["rel"] + "\\t" + subprocess.run(["ps", "-o", "args=", "-p", str(os.getpid())],
                                            capture_output=True, text=True).stdout.strip())
else:
    say(f"{{time.monotonic():.3f}} start {{unit['kind']}} {{unit['rel']}} {{VERSION}}")
if b.get("env"):
    say(f"desktop {{unit['rel']}} {{os.environ.get('OCR_REMOTE')!r}}")
if unit["rel"] == b.get("rewrite_on"):
    path = b.get("rewrite", __file__)
    with open(path) as fh:
        text = fh.read()
    with open(path, "w") as fh:
        fh.write(text.replace(*b["change"]))
time.sleep(b.get("sleep", {{}}).get(unit["rel"], b.get("default", 0.2)))
held = b.get("hold", {{}}).get(unit["rel"])  # runs until this file exists (a test's event, not a guessed time)
until = time.monotonic() + 600
while held and not os.path.exists(held) and time.monotonic() < until:
    time.sleep(0.1)
if b.get("ends", True) and not b.get("ps"):
    say(f"{{time.monotonic():.3f}} end {{unit['kind']}} {{unit['rel']}}")
outcome = b.get("outcome", {{}}).get(unit["rel"], "read" if unit["kind"] == "read" else "fetched")
sys.exit({eq.EXITS!r}.get(outcome, 1))
""")
def fake(**kw):
    behaviour.write_text(json.dumps(kw))
fake(sleep={"slow": 30})
eq.fresh = lambda papers, cache=None: ([], [])  # the tests' temp editions are no fresh downloads
def units(scans, reads):
    return lambda papers, cache=None, reread=None, out=None: (
        [{"kind": "scan", "paper": "times", "rel": r, "rank": 1, "reason": "scan stale"} for r in scans],
        [{"kind": "read", "paper": "times", "rel": r, "rank": 1, "reason": "never read", "needs": n} for r, n in reads])
eq.plan = units(["s1"], [("r1", ["s1"]), ("slow", []), ("r2", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    t0 = time.monotonic()
    rc = eq.dispatch(["times"], cache, workers=2, scan_workers=1, read_seconds=2, replan=0.5)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
starts = [e[2] for e in ev if e[0] == "start"]
check("the dispatcher ends 0, every unit started once", (0, ["r1", "r2", "s1", "slow"]), (rc, sorted(starts)))
# A read waits only on a scan that is running (read_waits); reads go ahead of a scan not yet begun
# (the queue's order, and the scan is held while a full read pool is ready), so r1 starts before s1 ends.
check("a read whose needed scan has not begun starts without waiting for it, and the scan still runs", True,
      ev.index(["start", "read", "r1", "v1"]) < ev.index(["end", "scan", "s1"]))
check("a unit past its limit is killed, the others not held up", (False, True, True),
      (["end", "read", "slow"] in ev, ["end", "read", "r2"] in ev, time.monotonic() - t0 < 15))
log.unlink(missing_ok=True)
fake(sleep={"n1": 1.0})
eq.plan = lambda papers, cache=None, reread=None, out=None: (
    [{"kind": "scan", "paper": "times", "rel": "b1", "rank": 3, "reason": "scan stale"}],
    [{"kind": "read", "paper": "times", "rel": r, "rank": 1, "reason": "never read", "needs": []} for r in ("n1", "n2")])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a whole-corpus unit waits, in its own idle pool, until no new one is left to start", True,
      ev.index(["start", "read", "n2", "v1"]) < ev.index(["start", "scan", "b1", "v1"]))
log.unlink(missing_ok=True)
fake(sleep={"r1": 0.6, "r2": 0.6})
eq.plan = units(["s9"], [("r1", []), ("r2", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a scan no read waits on holds while a full read pool of reads is ready", True,
      ev.index(["start", "read", "r2", "v1"]) < ev.index(["start", "scan", "s9", "v1"]))
log.unlink(missing_ok=True)
import threading
def release_on(marker, path, limit=60):
    """Touch `path` once units.log holds `marker`, or after `limit` s: a held unit's end is an event
    of the test's, not a guessed time (on a loaded CI runner a unit's brief and process take seconds)."""
    def watch():
        until = time.monotonic() + limit
        while time.monotonic() < until and not (log.exists() and marker in log.read_text()):
            time.sleep(0.05)
        path.touch()
    threading.Thread(target=watch, daemon=True).start()
# The reads run until the scan has started (or 60 s): a scan held behind them starts only after r1 ends.
released = T / "release-s9"
fake(hold={"r1": str(released), "r2": str(released)})
eq.plan = units(["s9"], [("r1", []), ("r2", [])])
release_on("start scan s9 ", released)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.2)
released.touch()
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("with fewer ready reads than read slots the scans start at once", True,
      ev.index(["start", "scan", "s9", "v1"]) < ev.index(["end", "read", "r1"]))
log.unlink(missing_ok=True)
fake(sleep={"s0": 1.5})
eq.plan = units(["s0", "s1"], [("r1", ["s1"])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a read whose days-after scan waits behind a full scan pool starts at once", True,
      ev.index(["start", "read", "r1", "v1"]) < ev.index(["end", "scan", "s0"]))
log.unlink(missing_ok=True)
fake(sleep={"s0": 1.5}, outcome={"bad": "failed"})
eq.plan = units(["s0", "r1", "bad"], [("r1", ["r1"]), ("bad", ["bad"])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a read whose own scan waits behind a full scan pool starts only after that scan ends done", True,
      ev.index(["end", "scan", "r1"]) < ev.index(["start", "read", "r1", "v1"]))
check("a read whose own scan failed is left for the next run, not read unscanned", False,
      ["start", "read", "bad", "v1"] in ev)
log.unlink(missing_ok=True)
fake()
# scan_stands hashes through _stand_hash (its path facts kept), not input_hash.
(hashes, stand_hash), f.input_hash, f._stand_hash = (f.input_hash, f._stand_hash), lambda d: "h", lambda c, r: "h"
q.append(cache / "filed.jsonl", [{"edition": "done", "filesHash": "h", "scanKey": f.scan_key(), "scan": scan}])
eq.plan = units(["done", "s1"], [("done", ["done"])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a planned scan whose edition was scanned since (a kept plan) is not started; its read goes on, the others' scans run",
      (False, True, True), (["start", "scan", "done", "v1"] in ev, ["start", "read", "done", "v1"] in ev,
                            ["start", "scan", "s1", "v1"] in ev))
f.input_hash, f._stand_hash = hashes, stand_hash
log.unlink(missing_ok=True)
fake()
calls = []
def slow_replan(papers, cache=None, reread=None, out=None):
    calls.append(time.monotonic())
    if len(calls) == 2:
        time.sleep(3)
    return [], [{"kind": "read", "paper": "times", "rel": f"q{k}", "rank": 1, "reason": "never read", "needs": []}
                for k in range(3)]
eq.plan = slow_replan
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    t0 = time.monotonic()
    eq.dispatch(["times"], cache, workers=1, replan=0.1)
starts = [float(line.split()[0]) for line in log.read_text().splitlines() if line.split()[1] == "start"]
check("a slow replan does not hold up starts from the plan before it", (3, True),
      (len(starts), max(starts) - starts[0] < 2.5))
log.unlink(missing_ok=True)
fresh_unit = {"kind": "read", "paper": "times", "rel": "f1", "rank": 0, "reason": "just laid out", "needs": []}
eq.plan = units([], [("b1", []), ("b2", [])])
eq.fresh = lambda papers, cache=None: ([], [fresh_unit])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, replan=0.2)
starts = [line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start"]
check("an edition just laid out starts before the planned backlog, once", ["f1", "b1", "b2"], starts)
log.unlink(missing_ok=True)
calls = []
eq.plan = slow_replan
t_fresh = time.monotonic() + 0.5
eq.fresh = lambda papers, cache=None: ([], [fresh_unit] if time.monotonic() > t_fresh else [])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, replan=0.1)
starts = {line.split()[3]: float(line.split()[0]) for line in log.read_text().splitlines() if line.split()[1] == "start"}
check("one laid out mid-plan starts while the planner thread is still at it", (True, True),
      ("f1" in starts, starts.get("f1", 99) < calls[1] + 3))
eq.fresh = lambda papers, cache=None: ([], [])
log.unlink(missing_ok=True)
kept_ho = Path(os.environ["TMP"]) / "kept-handoff.json"
eq.plan = units([], [("k1", []), ("k2", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, replan=0.1, handoff=kept_ho)
log.unlink(missing_ok=True)
plans_made = []
def stalled_until(rels, limit=60):
    """A planner whose (empty) plan is made only once each of `rels` has logged its start, or after
    `limit` s: the kept plan's starts are an event of the test's, not a guessed 3 s. With a fixed 3 s
    a loaded CI runner failed this case: the host's own gates (its MemAvailable under the floor,
    "memory-bound"; reads waiting on the VLM in the shared temp dir) held the kept units past the
    3 s, the empty plan then replaced the kept one, as it should, and no unit started at all."""
    def plan(papers, cache=None, reread=None, out=None):
        until = time.monotonic() + limit
        while time.monotonic() < until and not (
                log.exists() and all(f" start read {r} " in log.read_text() for r in rels)):
            time.sleep(0.05)
        plans_made.append(time.monotonic())
        return [], []
    return plan
eq.plan = stalled_until(["k1", "k2"])
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, replan=0.1, handoff=kept_ho)
starts = [(float(line.split()[0]), line.split()[3]) for line in (log.read_text() if log.exists() else "").splitlines()
          if line.split()[1] == "start"]
if not starts:
    print("the run given the kept plan started nothing; its log:\n" + err.getvalue())
check("the next run starts the kept plan's units before its own plan is made", (["k1", "k2"], True),
      (sorted(r for _, r in starts), bool(plans_made) and all(t < plans_made[0] for t, _ in starts)))
log.unlink(missing_ok=True)
# A slice boundary: the next slice fills its free slots with what the last
# one had not started, at once, its ledger upkeep on the planner thread.
# Driven by events, not wall time (a 2 s slice on a loaded CI runner ended before any unit logged its
# start): k2 and k3 run until released, so both slots are busy and k4, k5 cannot start in this slice,
# and the slice's clock runs out only once k3 (begun when k1 ends) has logged its start.
released = T / "release-k"
fake(hold={"k2": str(released), "k3": str(released)})
kept_ho = Path(os.environ["TMP"]) / "kept-handoff2.json"
eq.plan = units([], [(f"k{k}", []) for k in range(1, 6)])
class KSliceClock:
    def __getattr__(self, name):
        return getattr(time, name)
    def monotonic(self):
        begun = log.exists() and "start read k3 " in log.read_text()
        return time.monotonic() + (600 if begun else 0)
eq.time = KSliceClock()
try:
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        eq.dispatch(["times"], cache, workers=2, replan=60, seconds=600, handoff=kept_ho)
finally:
    eq.time = time
released.touch()  # the next slice, taking k2 and k3 over, sees them end
ran = {line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start"}
log.unlink(missing_ok=True)
left_over = sorted({"k1", "k2", "k3", "k4", "k5"} - ran)
eq.plan = stalled_until(left_over)
plans_made.clear()
upkept = []
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    # The upkeep, like the plan, ends only once the units left over have started (or 60 s).
    eq.dispatch(["times"], cache, workers=4, replan=0.1, handoff=kept_ho,
                upkeep=lambda: (eq.plan([]), upkept.append(time.monotonic())))
starts = [(float(line.split()[0]), line.split()[3]) for line in (log.read_text() if log.exists() else "").splitlines()
          if line.split()[1] == "start"]
if not starts:
    print("the next slice started nothing; its log:\n" + err.getvalue())
check("the next slice starts at once what the last left unstarted, not what it ran; upkeep beside it",
      (left_over, True, 1, True),
      (sorted(r for _, r in starts), len(upkept) == 1 and all(t < upkept[0] for t, _ in starts), len(upkept), "k1" in ran))
log.unlink(missing_ok=True)
fake(sleep={"slow": 30})
eq.plan = units([], [(f"r{k}", []) for k in range(6)])
out = io.StringIO()
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=0.5, replan=60)
check("--seconds starts nothing after it and says what it left", (True, True),
      (len((log.read_text() if log.exists() else "").splitlines()) <= 4, "left for the next run" in out.getvalue()))
# A slow runner can reach the deadline before the one worker logs a start,
# and then no log is written at all: that is still "nothing after it".
log.unlink(missing_ok=True)
eq.plan = units([], [("slow", [])])
pid = os.fork()
if pid == 0:
    sys.stderr = open(os.devnull, "w")
    os._exit(eq.dispatch(["times"], cache, workers=1))
time.sleep(1.5)
os.kill(pid, signal.SIGTERM)
t0 = time.monotonic()
rc = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
check("a TERM ends the running units and exits 143, at once", (143, True, False),
      (rc, time.monotonic() - t0 < 5, "end read slow" in (log.read_text() if log.exists() else "")))
# A slow runner may TERM it before the unit logs its start: no log at all.
log.unlink(missing_ok=True)
# --beside: a batch filer runs beside the units, again while it leaves work.
beside_n = T / "beside.n"
script = T / "beside.sh"
script.write_text(f'n=$(cat {beside_n} 2>/dev/null || echo 0); echo $((n+1)) > {beside_n}; '
                  f'[ "$n" -lt 2 ] && echo "  1  left for the next run"; exit 0\n')
eq.plan = units([], [("r1", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    rc = eq.dispatch(["times"], cache, workers=1, beside=[["bash", str(script)]])
check("--beside runs beside the units until it leaves nothing", (0, "3", True),
      (rc, beside_n.read_text().strip(), "end read r1" in log.read_text()))

# --fetch: a source's fetch units run in a pool of their own beside the
# reads; a 429 lowers the pool, FETCH_OUTAGES in a row stop the source.
log.unlink(missing_ok=True)
outcome = {}
fake(default=0.3, ends=False)
eq.plan = units([], [("r1", [])])
eq.FETCHERS = {"src": {"plan": lambda: [{"rel": f"e{k}", "reason": "not fetched"} for k in range(6)],
                       "workers": 3, "seconds": 5}}
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    rc = eq.dispatch(["times"], cache, workers=1, fetch=["src"], replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("fetch units run beside the reads, each once, in their own pool", (0, ["r1"], [f"e{k}" for k in range(6)]),
      (rc, [e[2] for e in ev if e[1] == "read"], sorted(e[2] for e in ev if e[1] == "fetch")))
log.unlink(missing_ok=True)
fake(default=0.3, ends=False, sleep={"e0": 0.1}, outcome={"e0": "throttled", **{f"e{k}": "outage" for k in range(1, 4)}})
eq.FETCH_OUTAGES = 3
eq.FETCHERS["src"]["workers"] = 2
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, fetch=["src"], replan=0.2)
check("a 429 lowers the pool; FETCH_OUTAGES down in a row stop the source for the run", (True, True, False),
      ("at most 1 fetches at once" in err.getvalue(), "no more fetches this run" in err.getvalue(),
       "start fetch e5" in log.read_text()))

# A slow fetch plan holds no read back: the first plan's reads start before it is made.
log.unlink(missing_ok=True)
fake(default=0.3, ends=False)
err = io.StringIO()
plan_saw = []
def slow_fetch_plan():
    plan_saw.append("start read r1" in err.getvalue())
    return [{"rel": "e0", "reason": "not fetched"}]
eq.FETCHERS = {"src": {"plan": slow_fetch_plan, "workers": 1, "seconds": 5}}
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, fetch=["src"], replan=0.2)
check("the first plan starts its reads before the fetch plan is made, and the fetches after", (True, True),
      (plan_saw[:1] == [True], "start fetch e0" in log.read_text()))

# A fetch source's plan is made again only fetch_replan after the last; the
# scans' and reads' plans every replan meanwhile.
eq.plan = units([], [("r1", [])])
made = {}
for every in (60, 0):
    log.unlink(missing_ok=True)
    fake(default=0.3, ends=False, sleep={"r1": 1.0})
    eq.FETCHERS = {"src": {"plan": lambda e=every: made.setdefault(e, []).append(1) or [],
                           "workers": 1, "seconds": 5}}
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        eq.dispatch(["times"], cache, workers=1, fetch=["src"], replan=0.1, fetch_replan=every)
check("a fetch plan is made once per fetch_replan, not every replan; mirror: at 0 every replan",
      (1, True), (len(made[60]), len(made[0]) > 2))

# Each unit's command line names its kind, paper and edition, not the queue's.
log.unlink(missing_ok=True)
fake(ps=True)
eq.plan = units([], [("GaleTimes1988UKEnglish/1988-08-30", [])])
eq.FETCHERS = {"src": {"plan": lambda: [{"rel": "article/120905968", "reason": "not fetched"}],
                       "workers": 1, "seconds": 5}}
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, fetch=["src"], replan=0.2)
seen = {k: v[v.index("edition_queue.py unit"):] for k, v in (line.split("\t", 1) for line in log.read_text().splitlines())}
check("a unit's ps command line is its kind, paper and edition",
      {"GaleTimes1988UKEnglish/1988-08-30": "edition_queue.py unit read times GaleTimes1988UKEnglish/1988-08-30",
       "article/120905968": "edition_queue.py unit fetch src article/120905968"}, seen)

# ---- the media share down (the Mac's SMB server refused the session for a minute, 10-20 and 10-23,
# and the whole pass died): a unit ends deferred, the dispatcher waits for the share, a bug stays a bug
import errno
import downloads
on_share = str(downloads.ROOT / "archive_org_editions")
def host_down(path=on_share, code=errno.EHOSTDOWN):
    return OSError(code, os.strerror(code), path)
for code in (errno.EHOSTDOWN, errno.ENOTCONN, errno.ESTALE, errno.EIO, errno.EACCES, errno.EPERM):
    check(f"media_down: {errno.errorcode[code]} on a path under the media root", True,
          downloads.media_down(host_down(on_share + "/filed.jsonl", code)))
check("media_down: the media root's own folder (pathlib's mkdir stat, 10-23)", True, downloads.media_down(host_down()))
check("mirror: the same errno on a path off the share is no outage", False,
      downloads.media_down(host_down(str(T / "filed.jsonl"))))
check("mirror: a missing file on the share is no outage", False,
      downloads.media_down(host_down(on_share + "/x.jsonl", errno.ENOENT)))
check("mirror: an error with no path, or no OSError, is no outage", (False, False),
      (downloads.media_down(OSError(errno.EHOSTDOWN, "Host is down")), downloads.media_down(ValueError(on_share))))
try:
    try:
        raise host_down()
    except OSError as cause:
        raise RuntimeError("wrapped") from cause
except RuntimeError as wrapped:
    check("an error raised from a media outage (its __cause__) is one", True, downloads.media_down(wrapped))
try:
    try:
        raise host_down()
    except OSError:
        raise KeyError("a bug in the handler")  # only __context__: the bug is what is raised
except KeyError as bug:
    check("mirror: a bug raised while handling one is not", False, downloads.media_down(bug))

# A unit's own process: an outage of the share is EXITS["media"], deferred, no failure logged;
# the same errno off the share is a failure, as ever.
failed = []
real_failure, q.failure = q.failure, lambda *a, **k: failed.append(a)
err = io.StringIO()
with contextlib.redirect_stderr(err):
    got = eq.unit_status({"kind": "read", "paper": "times", "rel": "m"}, lambda: (_ for _ in ()).throw(host_down()))
check("a unit whose ledger mkdir meets the share down ends deferred for it, nothing failed",
      (eq.EXITS["media"], [], True), (got, failed, "deferred, the media share is down" in err.getvalue()))
with contextlib.redirect_stderr(io.StringIO()):
    got = eq.unit_status({"kind": "read", "paper": "times", "rel": "m"},
                         lambda: (_ for _ in ()).throw(host_down(str(T / "x"), errno.EACCES)))
check("mirror: EACCES off the share fails the unit", (1, 1), (got, len(failed)))
q.failure = real_failure

# A scan whose page the share did not serve keeps no "failed" row: it is scanned again once it answers.
m1, m2 = edition("NewsUK1980UKEnglish", "1980-04-05_6", 10), edition("NewsUK1980UKEnglish", "1980-04-12_7", 10)
real_scan_anywhere = f.scan_anywhere
f.scan_anywhere = lambda d: (_ for _ in ()).throw(host_down(on_share + f"/{d.parent.name}/{d.name}/leaf_0021.jpg"))
lines_before = len(tl.read_text().splitlines())
with contextlib.redirect_stderr(io.StringIO()):
    got = eq.unit_status({"kind": "scan", "paper": "times", "rel": "NewsUK1980UKEnglish/1980-04-05_6"},
                         lambda: f.scan_unit(f.TIMES, "NewsUK1980UKEnglish/1980-04-05_6", cache))
check("a scan meeting the share down ends deferred and appends no row", (eq.EXITS["media"], lines_before),
      (got, len(tl.read_text().splitlines())))
f.scan_anywhere = lambda d: (_ for _ in ()).throw(host_down(str(d / "leaf_0021.jpg"), errno.EIO))
with contextlib.redirect_stderr(io.StringIO()):
    got = eq.unit_status({"kind": "scan", "paper": "times", "rel": "NewsUK1980UKEnglish/1980-04-12_7"},
                         lambda: f.scan_unit(f.TIMES, "NewsUK1980UKEnglish/1980-04-12_7", cache))
check("mirror: an EIO off the share stands as a failed scan, as ever", (0, lines_before + 1, True),
      (got, len(tl.read_text().splitlines()),
       "failed" in q.ledger_rows(tl, "edition")["NewsUK1980UKEnglish/1980-04-12_7"]["scan"]))
f.scan_anywhere = real_scan_anywhere

# MediaGate on a clock the test moves: one "waiting" line, a probe every `every`, "back" once.
now = [0.0]
answers = []
said = []
gate = eq.MediaGate(probe=lambda: answers.pop(0), every=20, limit=1800, clock=lambda: now[0], say=said.append)
check("no outage noted: nothing held, nothing probed", (False, []), (gate.hold(), said))
check("a non-outage error is not noted", (False, False), (gate.down(ValueError("x")), gate.held()))
answers[:] = [False, False, True]
gate.down()
held = [gate.hold()]
now[0] = 5.0
held.append(gate.hold())  # between probes: held, not probed
now[0] = 20.0
held.append(gate.hold())
now[0] = 40.0
held.append(gate.hold())
check("down: held until a probe answers, probed every 20s, one waiting line, one back line",
      ([True, True, True, False], [], 2, True, True),
      (held, answers, len(said), said[0].startswith("media down: waiting"), said[1].startswith("media back after 40s")))
said.clear()
answers[:] = [True]
gate.down()
check("a unit's note the first probe finds answered is let go without a line", (False, []), (gate.hold(), said))
answers[:] = [False] * 200
gate.down(host_down())
gone = None
try:
    while gate.hold():
        now[0] += 20
except eq.MediaGone as e:
    gone = str(e)
check("down past the limit: MediaGone", True, gone is not None and "CT_MEDIA_WAIT 1800" in gone)
# The loop's own error on one path, the share answering each time: raised once it repeats (a bug, not an outage).
gate = eq.MediaGate(probe=lambda: True, every=20, limit=1800, clock=lambda: now[0], say=said.append)
raised = None
try:
    for _ in range(eq.MEDIA_BLIPS):
        gate.down(host_down(on_share + "/filed.jsonl", errno.EACCES))
        gate.hold()
        now[0] += 1
except OSError as e:
    raised = e.errno
check("the loop's media error on a share that answers is raised once it repeats", errno.EACCES, raised)

# main's fallback: the share back after an outage, the run re-execs; answering at once, the error is raised.
execs = []
gate = eq.MediaGate(probe=iter([False, True]).__next__, every=0, limit=1800, say=said.append)
with contextlib.redirect_stderr(io.StringIO()):
    got = eq.media_restart(host_down(), gate=gate, execv=lambda *a: execs.append(a))
check("media_restart: waits for the share, then re-execs", (0, 1), (got, len(execs)))
gate = eq.MediaGate(probe=lambda: True, every=0, limit=1800, say=said.append)
raised = None
try:
    eq.media_restart(host_down(), gate=gate, execv=lambda *a: execs.append(a))
except OSError as e:
    raised = e.errno
check("mirror: a share that answers at once: the error is raised, no re-exec", (errno.EHOSTDOWN, 1), (raised, len(execs)))
gate = eq.MediaGate(probe=lambda: False, every=0, limit=0.001, clock=iter(range(0, 10 ** 6, 10)).__next__, say=said.append)
with contextlib.redirect_stderr(io.StringIO()):
    check("media_restart: down past the limit ends 1", 1, eq.media_restart(host_down(), gate=gate, execv=lambda *a: execs.append(a)))
check("the probe: a folder that lists answers, a missing one does not", (True, False),
      (eq.media_reachable(T), eq.media_reachable(T / "nowhere")))

# The dispatcher: a read ends deferred for the share; no unit starts until a probe finds it back,
# then the queue goes on. m1 always meets it: past MEDIA_TRIES it fails, the run ends 0.
real_reachable, real_nap = eq.media_reachable, eq.MEDIA_NAP
eq.MEDIA_PROBE_EVERY, eq.MEDIA_NAP = 0, 0.05
probes = []
def probe():
    starts = sum(" start " in line for line in log.read_text().splitlines()) if log.exists() else 0
    probes.append(starts)
    return len(probes) >= 3
eq.media_reachable = probe
log.unlink(missing_ok=True)
fake(default=0.1, outcome={"m1": "media"})
eq.plan = units([], [("m1", []), ("m2", [])])
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    rc = eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
starts = [line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start"]
check("the share down: no unit starts while the probes find it down", (True, probes[0]), (len(probes) >= 3, probes[1]))
check("the run goes on once it answers: m2 read, m1 tried MEDIA_TRIES + 1 times, rc 0",
      (0, eq.MEDIA_TRIES + 1, 1), (rc, starts.count("m1"), starts.count("m2")))
check("one waiting line, one back line; m1 deferred, then failed", (1, 1, True, True),
      (err.getvalue().count("media down: waiting"), err.getvalue().count("media back after"),
       "end read m1: deferred (the media share is down)" in err.getvalue(),
       f"end read m1: failed (the media share's error {eq.MEDIA_TRIES + 1} times this run)" in err.getvalue()))

# Down past CT_MEDIA_WAIT: nothing more starts and the run ends 1.
eq.media_reachable = lambda: False
os.environ["CT_MEDIA_WAIT"] = "0.3"
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    rc = eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
starts = [line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start"]
check("down past CT_MEDIA_WAIT: m2 never starts, the run gives up and ends 1", (1, ["m1"], True),
      (rc, starts, "media down: giving up" in err.getvalue()))
del os.environ["CT_MEDIA_WAIT"]

# The dispatcher's own plan meets the share down (10-23: the loop's ledger stat): it waits and plans again.
probes.clear()
eq.media_reachable = probe
plans = []
def plan_once_down(papers, cache=None, reread=None, out=None):
    plans.append(1)
    if len(plans) == 1:
        raise host_down(on_share + "/filed.jsonl")
    return units([], [("p1", [])])(papers)
eq.plan = plan_once_down
log.unlink(missing_ok=True)
fake(default=0.1)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    rc = eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
check("a plan meeting the share down waits for it, plans again and reads", (0, True, True, True),
      (rc, len(plans) >= 2, "start read p1" in log.read_text(), "media back after" in err.getvalue()))
# Mirror: EACCES off the share is a bug: the dispatcher raises it.
def plan_denied(papers, cache=None, reread=None, out=None):
    raise host_down(str(T / "filed.jsonl"), errno.EACCES)
eq.plan = plan_denied
raised = None
try:
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
except PermissionError as e:
    raised = e.errno
check("mirror: the plan's EACCES off the share is raised, not waited out", errno.EACCES, raised)
eq.media_reachable, eq.MEDIA_NAP, eq.MEDIA_PROBE_EVERY = real_reachable, real_nap, 20
log.unlink(missing_ok=True)
fake()

# ---- fresh code: a unit started after a code change runs the new code.
# The first unit changes the unit script as it runs (master moved under
# the tree); every unit started after it runs the changed script.
log.unlink(missing_ok=True)
fake(rewrite_on="c0", change=['VERSION = "v1"', 'VERSION = "v2"'], sleep={"c0": 0.5})
eq.plan = units([], [(f"c{k}", []) for k in range(4)])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, replan=0.2)
ran = [e.split()[3:] for e in log.read_text().splitlines() if " start " in e]
check("a unit started after a code change runs the new code, none the old",
      [["c0", "v1"], ["c1", "v2"], ["c2", "v2"], ["c3", "v2"]], ran)

# ---- the queue itself follows its code: a change to it hands its running
# units to its new image (same pid, a child still) and re-execs.
log.unlink(missing_ok=True)
driver = T / "driver.py"
driver.write_text(f"""import os, sys
sys.path.insert(0, {str(Path.cwd())!r})
import edition_queue as eq
VERSION = "p1"
print(f"parent {{VERSION}} {{os.getpid()}}", file=sys.stderr, flush=True)
eq.cpu_gate_reader = lambda: 0.0
eq.idle_gate_reader = lambda: 1e6
eq.mem_gate_reader = lambda: 1 << 40
# As above, in this process too: off Paul's LAN (CI) the real VLM probe says
# down, and the "times" reads it gates (needs_vlm) never start: a hang.
eq.desktop_gate_reader = lambda: None
eq.desktop_mem_reader = lambda: None
eq.vlm_gate_reader = lambda: True
eq.UNIT_SCRIPT ={str(eq.UNIT_SCRIPT)!r}
eq.plan = lambda papers, cache=None, reread=None, out=None: (
    [], [{{"kind": "read", "paper": "times", "rel": r, "rank": 1, "reason": "never read", "needs": []}}
         for r in ("long", "r1", "r2")])
resume = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else None
sys.exit(eq.dispatch(["times"], {str(cache)!r}, workers=1, replan=0.3, resume=resume,
                 plan_reuse=float(os.environ.get("TEST_PLAN_REUSE", 0))))
""")
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(driver), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
import subprocess
p = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True, timeout=300)
parents = [l.split()[1:] for l in p.stderr.splitlines() if l.startswith("parent ")]
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a code change re-execs the queue once, same pid, new code", (0, ["p1", "p2"], True, True),
      (p.returncode, [v for v, _ in parents], len({pid for _, pid in parents}) == 1, "re-exec" in p.stderr))
check("its running unit is kept, not started again, reaped by the new image, then the rest start",
      (1, True, True, ["long", "r1", "r2"]),
      (sum(e[:3] == ["start", "read", "long"] for e in ev), "end read long: done" in p.stderr,
       ev.index(["end", "read", "long"]) < ev.index(["start", "read", "r1", "v1"]),
       [e[2] for e in ev if e[0] == "start"]))
# A re-exec reuses a young kept plan as its own: it says so, and the plan's
# time to make survives in the file for the replan back-off.
check("mirror: with plan_reuse 0 the re-exec's image does not keep the plan", False, "kept, not made again" in p.stderr)
log.unlink(missing_ok=True)
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
driver.write_text(driver.read_text().replace('VERSION = "p2"', 'VERSION = "p1"'))
fake(rewrite_on="long", rewrite=str(driver), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
reused = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True, timeout=300,
                        env={**os.environ, "TEST_PLAN_REUSE": "600"})
check("a re-exec starts from a plan under plan_reuse old and keeps it as its own, units still all started once",
      (0, True, ["long", "r1", "r2"]),
      (reused.returncode, "kept, not made again now" in reused.stderr,
       [e[3] for e in (l.split() for l in log.read_text().splitlines()) if e[1] == "start"]))
kp = T / "took.plan"
eq.keep_plan(kp, ["k"], ([], [], []), time.time(), 123.0)
check("a kept plan carries how long it took", (([], [], []), 123.0), (eq.last_plan(kp, ["k"])[0], eq.last_plan(kp, ["k"])[2]))
# Mirror: a plan that takes minutes (a cold cache on the media mount) holds
# no re-exec back; the old code would run until the plan ended.
log.unlink(missing_ok=True)
slow = T / "slow_driver.py"
slow.write_text(driver.read_text().replace('VERSION = "p2"', 'VERSION = "p1"').replace("eq.plan = lambda papers", """import time
calls = []
def plan(*a, **k):
    calls.append(1)
    if len(calls) > 1 and VERSION == "p1":
        time.sleep(60)
    return quick(*a, **k)
eq.plan = plan
quick = lambda papers""").replace("replan=0.3, resume=resume", "replan=0.3, resume=resume, seconds=120"))
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(slow), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
slowed = subprocess.run([sys.executable, str(slow)], capture_output=True, text=True, timeout=300)
check("a code change re-execs the queue while its plan is still being made",
      ["p1", "p2"], [l.split()[1] for l in slowed.stderr.splitlines() if l.startswith("parent ")])
# Mirror: an image that has not yet made a plan of its own (it runs the kept
# one) makes it before re-exec'ing on the next change, so changes landing
# faster than a plan takes still get plans made on new code.
log.unlink(missing_ok=True)
busy = T / "busy_driver.py"
busy_src = (driver.read_text().replace('VERSION = "p2"', 'VERSION = "p1"').replace("eq.plan = lambda papers", """import time
def plan(*a, **k):
    if VERSION == "p2":
        src = open(__file__).read()
        open(__file__, "w").write(src.replace('VERSION = "p2"', 'VERSION = "p3"'))
        time.sleep(1.5)
        print("plan made by p2", file=sys.stderr, flush=True)
    return quick(*a, **k)
eq.plan = plan
quick = lambda papers""").replace("replan=0.3, resume=resume", "replan=0.3, resume=resume, seconds=120"))
busy.write_text(busy_src)
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(busy), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
busied = subprocess.run([sys.executable, str(busy)], capture_output=True, text=True, timeout=300)
said = [l.split()[1] if l.startswith("parent ") else l for l in busied.stderr.splitlines()
        if l.startswith("parent ") or l == "plan made by p2"]
check("an image re-execs on a change only after making its own first plan",
      ["p1", "p2", "plan made by p2", "p3"], said)
# Mirror: every unit ended while that first plan was made (a loaded host),
# so the run's last plan is next; it is made on the new code, not the old.
log.unlink(missing_ok=True)
busy.write_text(busy_src.replace("time.sleep(1.5)", "time.sleep(5)"))
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(busy), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 1})
busied = subprocess.run([sys.executable, str(busy)], capture_output=True, text=True, timeout=300)
said = [l.split()[1] if l.startswith("parent ") else l for l in busied.stderr.splitlines()
        if l.startswith("parent ") or l == "plan made by p2"]
check("mirror: with its units all ended during its first plan, an image still re-execs before its last plan",
      ["p1", "p2", "plan made by p2", "p3"], said)
# But a slice's first image (started by the shell, running the plan the last
# slice kept) re-execs on a change to itself mid-plan: its plan can take half
# an hour on a loaded host, and the dispatcher it runs would be the old all
# that while (2026-10-15: edition_queue.py landed at 01:51 and a slice begun
# at 01:45 was still on its first plan at 02:10).
log.unlink(missing_ok=True)
fresh_drv = T / "fresh_driver.py"
kept = T / "fresh-kept.json"
fresh_drv.write_text(driver.read_text().replace('VERSION = "p2"', 'VERSION = "p1"').replace("eq.plan = lambda papers", """import time
def plan(*a, **k):
    if VERSION == "p1":
        time.sleep(60)
    return quick(*a, **k)
eq.plan = plan
quick = lambda papers""").replace(
    'resume = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else None', f"""
resume = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else {str(kept)!r}
if "--resume" not in sys.argv:
    eq.keep_plan(eq.Path(resume + ".plan"), [["times"], {str(cache)!r}, None, [], eq.plan_version(eq.code_files())],
                 (*quick(["times"]), []), time.time())
""").replace("replan=0.3, resume=resume", "replan=0.3, resume=resume, seconds=120"))
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(fresh_drv), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
t0 = time.monotonic()
freshed = subprocess.run([sys.executable, str(fresh_drv)], capture_output=True, text=True, timeout=300)
check("a slice's first image re-execs on a change to itself while its first plan is still being made",
      (["p1", "p2"], True), ([l.split()[1] for l in freshed.stderr.splitlines() if l.startswith("parent ")],
                             time.monotonic() - t0 < 200))

# ---- --handoff: a slice's end hands its running units to the next run,
# which counts them in its pools and does not start them again.
log.unlink(missing_ok=True)
released = T / "release-long"
fake(hold={"long": str(released)})  # "long" runs until released, so it is still running when the slice ends
eq.plan = units([], [("long", []), ("r1", [])])
ho = T / "handoff.json"
out = io.StringIO()
# Driven by events, not wall time (a 25-min CI run on a loaded runner flaked on both): the slice's clock
# runs out only once "long" has logged its start (its brief is made on a pool thread and its process
# can take seconds to come up), and the slice is long enough that only that can end it.
SLICE = 600  # the jump ages "long" too: overdue() (READ_SECONDS 1200) kills it only after 600 s of real running
class SliceClock:
    def __getattr__(self, name):
        return getattr(time, name)
    def monotonic(self):
        begun = log.exists() and "start read long" in log.read_text()
        return time.monotonic() + (SLICE if begun else 0)
eq.time = SliceClock()
try:
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
        rc = eq.dispatch(["times"], cache, workers=1, seconds=SLICE, handoff=ho)
finally:
    eq.time = time
began = [float(l.split()[0]) for l in log.read_text().splitlines() if " start read long " in l]
check("a slice ends at once, handing over its running unit, and says it left work", (0, True, ["long"], True, False),
      (rc, bool(began) and time.monotonic() - began[0] < 60, [r["unit"]["rel"] for r in json.loads(ho.read_text())],
       "left for the next run" in out.getvalue(), "end read long" in log.read_text()))
released.touch()  # the next run, taking it over, sees it end
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    rc = eq.dispatch(["times"], cache, workers=1, handoff=ho, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("the next run takes it over: not started twice, its slot held until it ends, then r1",
      (0, 1, True, True, False),
      (rc, sum(e[:3] == ["start", "read", "long"] for e in ev),
       ev.index(["end", "read", "long"]) < ev.index(["start", "read", "r1", "v1"]),
       "end read long" in err.getvalue(), ho.exists()))

# ---- Trove articles: one read unit each, appended rows, its own lock
import file_trove_puzzles as ftp
tc = T / "trove"
for a in ("101", "102"):
    (tc / a).mkdir(parents=True)
    (tc / a / "meta.json").write_text("{}")
tled = tc / "filed.jsonl"
ftp.held_files = lambda puzzles=None: {}
ftp.inputs_of = lambda d, held=None: "h"
read_calls = []
def fake_consider(d):
    read_calls.append(d.name)
    return {"skip": "not a cryptic"}, None, None, False
ftp.consider_article = fake_consider
q.append(tled, [{"article": "102", "inputs": "h", "readAt": "2026-01-01T00:00:00+00:00"}])
units_ = ftp.plan(tc, reread=q.when("2026-06-01T00:00:00+00:00"))
check("trove plan: never read first, then --reread", [("101", "never read", 1), ("102", "--reread", 3)],
      [(u["rel"], u["reason"], u["rank"]) for u in units_])
for a, title in (("103", "02 Jan 1972 - X"), ("104", "05 Mar 1980 - Y")):
    (tc / a).mkdir()
    (tc / a / "meta.json").write_text(json.dumps({"title": title}))
check("trove plan: a rank's articles newest first", ["104", "103", "101"],
      [u["rel"] for u in ftp.plan(tc) if u["rank"] == 1])
rk = T / "trove-rekey.jsonl"
q.append(rk, [{"article": "103", "inputs": "copied", "readAt": "2026-01-01T00:00:00+00:00"},
              {"article": "104", "inputs": "edited", "readAt": "2026-01-01T00:00:00+00:00"}])
os.utime(tc / "103" / "meta.json", (1.5e9, 1.5e9))
check("an article whose files are older than its read is re-keyed, not read again; one edited since is not",
      (1, {"103": "h", "104": "edited"}),
      (ftp.rekey_unchanged(rk, tc), {a: r["inputs"] for a, r in q.ledger_rows(rk, "article").items()}))
for a in ("103", "104"):
    for p_ in (tc / a).iterdir():
        p_.unlink()
    (tc / a).rmdir()
check("annotation's ask is rank 1, forced", [("102", 1, True)],
      [(u["rel"], u["rank"], u["force"]) for u in ftp.plan(tc, asked={"102"}) if u["rel"] == "102"])
with contextlib.redirect_stderr(io.StringIO()):
    got = ftp.read_unit("101", tc)
check("a trove unit reads its article and appends one row", ("read", ["101"], 2, "not a cryptic"),
      (got, read_calls, len(tled.read_text().splitlines()), q.ledger_rows(tled, "article")["101"]["skip"]))
with contextlib.redirect_stderr(io.StringIO()):
    check("read, it is current", ("current", ["101"]), (ftp.read_unit("101", tc), read_calls))
with q.source_lock(tled, "102"):
    pid = os.fork()
    if pid == 0:
        os._exit(0 if ftp.read_unit("102", tc, reread=q.when("now")) == "busy" else 1)
    check("an article another unit holds is busy", 0, os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))
with q.lock(tled):
    pid = os.fork()
    if pid == 0:
        os._exit(0 if ftp.read_unit("102", tc, reread=q.when("now")) == "held" else 1)
    check("a ledger a batch run holds: the unit is held", 0, os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))
# A slice's upkeep (compact) holds the ledger for seconds as its first units
# start: they wait it out rather than end "held" and leave the desktop idle
# until the next plan (10-13).
q.UNIT_HOLD_WAIT = 30
import fcntl
t0 = time.monotonic()
hold = open(tled.with_suffix(".lock"), "w")
fcntl.flock(hold, fcntl.LOCK_EX)
pid = os.fork()
if pid == 0:
    hold.close()  # the parent's hold stands (a forked copy of q.lock's would be the unit's own)
    with contextlib.redirect_stderr(io.StringIO()):
        os._exit(0 if ftp.read_unit("101", tc) == "current" else 1)
time.sleep(1.5)
fcntl.flock(hold, fcntl.LOCK_UN)
hold.close()
check("a hold that ends within UNIT_HOLD_WAIT (a slice's fold) is waited out, not held",
      (0, True), (os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), 1.5 <= time.monotonic() - t0 < 200))

# ---- Listener pages: one read unit each, rows appended to its ledger
import gale_listener as gl
inbox, store = T / "linbox", T / "lstore"
inbox.mkdir()
for name in ("1930-04-02.pdf", "1930-04-09.pdf"):
    (inbox / name).write_bytes(name.encode())
(store).mkdir()
(store / gl.LEGACY).write_text(json.dumps({gl.file_hash(inbox / "1930-04-09.pdf"): {"file": "1930-04-09.pdf", "version": gl.VERSION}}))
check("listener plan: the pages not read at VERSION, rank 0", [("1930-04-02.pdf", 0)],
      [(u["rel"], u["rank"]) for u in gl.plan(inbox, store)])
vers, gl.VERSION = gl.VERSION, "next"
check("listener plan: a VERSION bump is a whole-corpus re-read, after the new pages",
      [("1930-04-02.pdf", 0, "never read (Gale fetch)"), ("1930-04-09.pdf", 3, "version changed")],
      [(u["rel"], u["rank"], u["reason"]) for u in gl.plan(inbox, store)])
gl.VERSION = vers
gl.index = lambda *a, **k: [{"number": 1, "date": None, "title": "t"}]
gl.match = lambda p, idx, read_title=True: {"file": p.name, "number": None, "why": "no number", "pages": [], "reports": []}
with contextlib.redirect_stdout(io.StringIO()):
    got = gl.read_unit("1930-04-02.pdf", inbox, store, file_it=False)
check("a listener unit reads its page and appends its row; the old ledger still counts", ("read", 1, []),
      (got, len((store / gl.LEDGER).read_text().splitlines()), gl.plan(inbox, store)))
with contextlib.redirect_stdout(io.StringIO()):
    check("read, it is current", "current", gl.read_unit("1930-04-02.pdf", inbox, store, file_it=False))

# ---- Trove's pace: units at once still ask at most once a `delay`
import fetch_trove
pace_dir = T / "pace"
pace_dir.mkdir()
stamps = T / "stamps"
kids = []
for _ in range(3):
    pid = os.fork()
    if pid == 0:
        tv = fetch_trove.Trove(str(pace_dir), 0.3, 600)
        for _ in range(3):
            tv.pace()
            with open(stamps, "a") as fh:
                fh.write(f"{time.time()}\n")
        os._exit(0)
    kids.append(pid)
for pid in kids:
    os.waitpid(pid, 0)
ts = sorted(float(x) for x in stamps.read_text().split())
# A stamp is written after its pace() returns, so two may land close
# together; the nine together still take eight gaps.
check("three processes' nine requests are paced 0.3s apart between them", (9, True),
      (len(ts), ts[-1] - ts[0] >= 8 * 0.3 - 0.05))

# ---- the memory gate: no start without room, running units untouched
import mem_gate as mg
G = 1 << 30
check("room: plenty available starts", True, mg.room(0, lambda: 16 * G))
check("room: below floor plus a unit does not", False, mg.room(0, lambda: 3 * G))
check("room: units begun this pass count against it", (True, True, False),
      tuple(mg.room(n * mg.UNIT, lambda: mg.FLOOR + int(2.5 * mg.UNIT)) for n in (0, 1, 2)))
check("ceiling_step: low RAM or hot CPU steps down, roomy and cool up, else holds, clamped 8..24",
      (18, 18, 20, 20, 20, 8, 24, 12),
      (mg.ceiling_step(20, 1500, 50), mg.ceiling_step(20, 3000, 95), mg.ceiling_step(18, 5000, 50),
       mg.ceiling_step(20, 3000, 85), mg.ceiling_step(20, None, 99), mg.ceiling_step(8, 1000, 99),
       mg.ceiling_step(24, 9000, 10), mg.ceiling_step(12, 5000, None)))
M = 1 << 20
_ps = [(10, 1, 80 * 1024), (11, 10, 120 * 1024), (12, 11, 30 * 1024), (20, 1, 70 * 1024), (30, 1, 900 * 1024), (40, 1, 10 * 1024)]
check("tree_rss: a unit is charged with its children and theirs", {10: 230 * M, 20: 70 * M},
      mg.tree_rss([10, 20, 99], _ps))
check("unit_costs: the largest unit of a kind, at least UNIT_MIN; kinds none runs are absent",
      {"read": 230 * M, "scan": 900 * M, "fetch archive.org": mg.UNIT_MIN},
      mg.unit_costs({10: "read", 20: "read", 30: "scan", 40: "fetch archive.org"}, _ps))
# Desktop reads measured at ~100 MB: 4 GB over the floor starts many, where a flat UNIT started 6.
_cost = mg.unit_costs({10: "read"}, _ps)["read"]
_avail = lambda: mg.FLOOR + 4 * G
check("room: measured cheap units fit more per pass than the flat UNIT", (17, 6),
      tuple(next(n for n in range(100) if not mg.room(n * c, _avail, unit=c)) for c in (_cost, mg.UNIT)))
# mirror: a measured heavy kind fits fewer than the flat UNIT, so the gate still holds
check("room: a measured heavy kind is charged its size, not UNIT", 4,
      next(n for n in range(100) if not mg.room(n * 900 * M, _avail, unit=900 * M)))
check("room: an unreadable figure gates nothing", True, mg.room(0, lambda: None))
check("available() reads this host", True, (mg.available() or 1) > 0)
check("cpu_room: under the load ceiling starts", True, mg.cpu_room(0, lambda: 3.0, cores=4))
check("cpu_room: at the ceiling does not", False, mg.cpu_room(0, lambda: mg.LOAD_PER_CORE * 4, cores=4))
check("cpu_room: units begun this pass count against it", (True, False),
      tuple(mg.cpu_room(n, lambda: mg.LOAD_PER_CORE * 4 - 0.5, cores=4) for n in (0, 1)))
check("cpu_room: the default ceiling leaves the host usable (at most 2 per core)", True,
      os.environ.get("CT_LOAD_PER_CORE") is not None or mg.LOAD_PER_CORE <= 2)
check("cpu_room: an unreadable load gates nothing", True, mg.cpu_room(0, lambda: None, cores=4))
# foreground_load: the run queue less nice-19 work. 2026-10-15: load 24 on 6 cores, ~3 of it nice 0.
_runq = iter([{0: 3, 19: 17, 10: 1}, {0: 2, 19: 19}, {19: 21}, {0: 6, 19: 15}])
check("foreground_load: averages the runnable threads niced under 19 over its samples", 3.0,
      mg.foreground_load(lambda: next(_runq), samples=4, sleep=lambda s: None))
check("foreground_load: a host busy only with nice-19 work reads idle", 0.0,
      mg.foreground_load(lambda: {19: 40}, samples=2, sleep=lambda s: None))
check("foreground_load: an unreadable run queue is None", None,
      mg.foreground_load(lambda: None, samples=2, sleep=lambda s: None))
check("cpu_room: nice-19 load over the ceiling does not shut a gate on foreground_load", (False, True),
      (mg.cpu_room(0, lambda: 24.0, cores=6),
       mg.cpu_room(0, lambda: mg.foreground_load(lambda: {0: 3, 19: 21}, samples=1), cores=6)))
import tempfile
_proc = Path(tempfile.mkdtemp())
for _pid, _threads in {"10": [("R", 0), ("S", 0)], "11": [("R", 19), ("R", 19)], "12": [("R", 5)], "self": [("R", 0)]}.items():
    for _i, (_st, _nice) in enumerate(_threads):
        (_proc / _pid / "task" / str(_i)).mkdir(parents=True)
        (_proc / _pid / "task" / str(_i) / "stat").write_text(
            f"{_pid} (a) b) {_st} " + " ".join(["1"] * 15) + f" {_nice} 1 0\n")
check("runnable_by_nice: counts R threads by nice, past a ')' in the name, skipping non-pids and `skip`",
      ({0: 1, 19: 2, 5: 1}, {19: 2, 5: 1}),
      (mg.runnable_by_nice(str(_proc)), mg.runnable_by_nice(str(_proc), skip=(10,))))
check("runnable_by_nice: no /proc is None", None, mg.runnable_by_nice(str(_proc / "none")))
import unit_queue as _uq
check("unit_queue: its units run at the niceness the CPU gate leaves out", mg.BACKGROUND_NICE, _uq.UNIT_NICE)
eq.cpu_gate_reader = lambda: 1e6
log.unlink(missing_ok=True)
eq.plan = units([], [(f"c{k}", []) for k in range(3)])
eq.mem_gate_reader = lambda: 16 * G
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("over the load ceiling nothing starts, and it says so once", (False, 1),
      (log.exists(), err.getvalue().count("cpu-bound")))
eq.cpu_gate_reader = lambda: 0.0
# A desktop set, this host's load holds back fetches alone: a scan's or
# read's OCR runs there, its reads here wait on ocr_remote.LOCAL_SLOTS.
os.environ["OCR_REMOTE"] = "tester@100.64.0.15"
check("with a desktop set the load gates fetches, not scans or reads", (True, False, False),
      tuple(eq.load_gated({"kind": k}) for k in ("fetch", "scan", "read")))
os.environ["OCR_REMOTE"] = ""
check("mirror: with no desktop the load gates every unit", (True, True, True),
      tuple(eq.load_gated({"kind": k}) for k in ("fetch", "scan", "read")))
# Paul 10-15 "load average is still pretty high": the pools whose units work
# on this host's CPU start only while a core is idle, so the burn (its quota
# expires at each reset) keeps the CPU; the pools waiting on the desktop or
# the network stay their full width.
os.environ["OCR_REMOTE"] = "tester@100.64.0.15"
_kinds = (("read", "trove"), ("read", "listener"), ("read", "times"), ("scan", "gale"), ("fetch", "trove"))
check("with a desktop set only Trove and Listener units are local CPU", (True, True, False, False, False),
      tuple(eq.local_cpu({"kind": k, "paper": p}) for k, p in _kinds))
os.environ["OCR_REMOTE"] = ""
check("mirror: with no desktop every scan and read is local CPU, a fetch never", (True, True, True, True, False),
      tuple(eq.local_cpu({"kind": k, "paper": p}) for k, p in _kinds))
check("idle_room: 1.2 idle cores start one local unit a pass, not two", (True, False),
      tuple(mg.idle_room(n, lambda: 1.2) for n in (0, 1)))
check("idle_room: under a core idle starts none", False, mg.idle_room(0, lambda: 0.3))
check("idle_room: an unread figure gates nothing", True, mg.idle_room(0, lambda: None))
import collections
_cpu = {"t": 100.0, "busy": 0.0, "idle": 0.0, "rate": 3.0}
def _adv(dt):
    _cpu["busy"] += _cpu["rate"] * dt * 100
    _cpu["idle"] += (4 - _cpu["rate"]) * dt * 100
    _cpu["t"] += dt
_stat = lambda: f"cpu  {int(_cpu['busy'])} 0 0 {int(_cpu['idle'])} 0 0 0 0\ncpu0 1 2 3 4\n"
_samples = collections.deque()
def _idle():
    return mg.idle_cores(_stat, cores=4, clock=lambda: _cpu["t"], samples=_samples, sleep=_adv)
check("idle_cores: a first call samples IDLE_FIRST_S and reads 3 busy of 4 cores as 1 idle", 1.0, round(_idle(), 2))
_cpu["rate"] = 0.0
for _ in range(40):
    _adv(2)
    _idle()
_cpu["rate"] = 4.0
_seen = []
for _ in range(6):
    _adv(2)
    _seen.append(round(_idle(), 1))
check("idle_cores: measures about the last IDLE_SPAN_S, so a busy spell shows within it", (True, 0.0),
      (_seen[0] > 2, _seen[-1]))
check("idle_cores: keeps no more than IDLE_KEEP_S of samples", True,
      _cpu["t"] - _samples[0][0] <= mg.IDLE_KEEP_S + 2)
check("idle_cores: an unreadable /proc/stat is no figure", None,
      mg.idle_cores(lambda: "", cores=4, samples=collections.deque(), sleep=lambda s: None))
def _concurrency():
    most = now = 0
    for line in log.read_text().splitlines():
        now += {"start": 1, "end": -1}.get(line.split()[1], 0)
        most = max(most, now)
    return most
def _running():
    now = 0
    for line in log.read_text().splitlines():
        now += {"start": 1, "end": -1}.get(line.split()[1], 0)
    return now
# No desktop, so these reads are local: no idle core, none starts.
eq.idle_gate_reader = lambda: 0.0
log.unlink(missing_ok=True)
fake(sleep={f"i{k}": 1.2 for k in range(3)})
eq.plan = units([], [(f"i{k}", []) for k in range(3)])
err, out = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("no idle core: no local unit starts, it says so once, and leaves them for the next run", (False, 1, True),
      (log.exists(), err.getvalue().count("idle-bound"), "left for the next run" in out.getvalue()))
# One core idle besides each running unit's: one at a time, all of them in turn, none killed.
eq.idle_gate_reader = lambda: 1.5 - (_running() if log.exists() else 0)
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.5)
ends = [line.split()[1:4] for line in log.read_text().splitlines() if line.split()[1] == "end"]
check("one idle core: the local pool runs one at a time, each to its end", (1, 3, 0),
      (_concurrency(), len(ends), err.getvalue().count("failed")))
# mirror: cores idle, the same pool runs its full width at once
eq.idle_gate_reader = lambda: 1e6
log.unlink(missing_ok=True)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.5)
check("mirror: idle cores, the pool runs its full width at once", 3, _concurrency())
# No idle core: the plan is made every replan * IDLE_BACKOFF seconds while the last holds more untried
# units than the pools are wide; with a short queue, or an idle core, every replan seconds.
def _plans(n_reads, idle):
    made = []
    inner = units([], [(f"p{k}", []) for k in range(n_reads)])
    eq.plan = lambda *a, **k: (made.append(1), inner(*a, **k))[1]
    eq.idle_gate_reader = lambda: idle
    log.unlink(missing_ok=True)
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=4, replan=0.3)
    return len(made)
fake(sleep={f"p{k}": 0.1 for k in range(6)})
backed_off = _plans(6, 0.0)
check("no idle core, a full queue: the planner backs off (under 5 plans in 4s at replan 0.3)", True, backed_off < 5)
check("mirror: idle cores replan more often than the backed-off run", True, _plans(6, 1e6) > backed_off)
check("mirror: no idle core but a queue no wider than the pools replans more often than the backed-off run", True,
      _plans(2, 0.0) > backed_off)
eq.idle_gate_reader = lambda: 1e6
fake(outcome={}, default=0.1)
os.environ.pop("OCR_REMOTE")
eq.desktop_gate_reader = lambda: "a game is running"
log.unlink(missing_ok=True)
eq.plan = units([], [(f"d{k}", []) for k in range(3)])
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("while the desktop yields no OCR unit starts here, and it says so once", (False, 1),
      (log.exists(), err.getvalue().count("desktop-bound")))
# mirror: the same plan with the desktop idle starts
eq.desktop_gate_reader = lambda: None
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("with the desktop idle the same units start", (True, 0),
      (log.exists(), err.getvalue().count("desktop-bound")))
# A unit ending deferred is not done or failed: it is started again once the
# desktop is idle, and while it yields it is left for the next run.
eq.desktop_gate_reader = lambda: "a game is running" if log.exists() else None  # busy once d0 has begun
fake(outcome={"d0": "deferred"}, default=0.1)
log.unlink(missing_ok=True)
eq.plan = units([], [("d0", [])])
err, out = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=2.2, replan=0.5)
check("a deferred unit is counted deferred, not failed, and left for the next run while the desktop yields",
      (1, True, False, True), (log.read_text().count("start"), "deferred (the desktop is busy)" in err.getvalue(),
                               "failed" in err.getvalue(), "left for the next run" in out.getvalue()))
eq.desktop_gate_reader = lambda: None
log.unlink(missing_ok=True)
fake(outcome={}, default=0.1)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=2.2, replan=0.5)
check("mirror: once the desktop is idle it starts again", 1, log.read_text().count("start"))
# Paul 10-17: a game stops the running units gracefully, opt-in by CT_YIELD_HOSTS: after
# CT_YIELD_GRACE they are TERMed and ended deferred (not failed), durable.sh is told to commit, and
# they start again once the game is over. Without CT_YIELD_HOSTS (the Mac) they are left alone.
def yield_run(hosts, game_for=None):
    flag = T / "durable-now"
    flag.unlink(missing_ok=True)
    os.environ["DURABLE_NOW"] = str(flag)
    os.environ["CT_YIELD_GRACE"] = "0.5"
    if hosts:
        os.environ["CT_YIELD_HOSTS"] = hosts
    else:
        os.environ.pop("CT_YIELD_HOSTS", None)
    t_game = [None]
    def gate():
        if not log.exists():
            return None
        t_game[0] = t_game[0] or time.monotonic()
        return "a game is running" if game_for is None or time.monotonic() - t_game[0] < game_for else None
    eq.desktop_gate_reader = gate
    fake(sleep={"g0": 8, "g1": 8}, default=0.1)
    log.unlink(missing_ok=True)
    eq.plan = units([], [("g0", []), ("g1", [])])
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        t0 = time.monotonic()
        eq.dispatch(["times"], cache, workers=2, scan_workers=1, seconds=6, replan=0.5)
        took = time.monotonic() - t0
    os.environ.pop("DURABLE_NOW")
    os.environ.pop("CT_YIELD_GRACE")
    os.environ.pop("CT_YIELD_HOSTS", None)
    return err.getvalue(), out.getvalue(), flag.exists(), took
msg, out, flagged, took = yield_run("tester@192.0.2.198")
check("a game stops the running units after the grace: TERMed, deferred, not failed, left for the next run",
      (2, False, True, True, True),
      (msg.count("deferred (stopped for a game)"), "failed" in msg, "TERM to 2" in msg, "left for the next run" in out, took < 7))
check("and durable.sh is told to commit at the start of the yield", True, flagged)
msg, out, flagged, took = yield_run("tester@192.0.2.198", game_for=1.2)

check("the units stopped for a game start again once it is over", (2, 4), (msg.count("deferred (stopped for a game)"), log.read_text().count("start")))
msg, out, flagged, took = yield_run(None)
check("mirror: without CT_YIELD_HOSTS running units are left alone (no TERM, no flag)", (0, False, False),
      (msg.count("stopped for a game"), "TERM" in msg, flagged))
def game_on(hosts):
    if hosts:
        os.environ["CT_YIELD_HOSTS"] = hosts
    eq.desktop_gate_reader = lambda: "a game is running"
    fake(outcome={}, default=0.1)
    log.unlink(missing_ok=True)
    eq.plan = units(["s9"], [("g0", ["s9"])])
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=2, replan=0.5)
    os.environ.pop("CT_YIELD_HOSTS", None)
    return log.read_text() if log.exists() else ""
got = game_on("tester@192.0.2.198")
check("during a game (opt-in) a scan starts, a read does not", (True, False), ("s9" in got, "g0" in got))
got = game_on(None)
check("mirror: without CT_YIELD_HOSTS neither starts while it yields", (False, False), ("s9" in got, "g0" in got))
eq.desktop_gate_reader = lambda: None
log.unlink(missing_ok=True)
fake(outcome={}, default=0.1)
# Paul 10-17: a game (desktop_busy's "game: ...") TERMs the scans beyond CT_GAME_SCAN_WORKERS (their RAM
# comes back; ended deferred, never failed, run again after it), starts no scan past the cap, and the
# --beside filers are SIGSTOPped with their clock stopped, SIGCONTed when it ends or on a TERM.
os.environ["CT_YIELD_HOSTS"] = "tester@192.0.2.198"
os.environ["CT_GAME_SCAN_WORKERS"] = "1"
t_game = {}
def game_gate():
    if not log.exists() or log.read_text().count("start scan") < 3 and "on" not in t_game:  # once all three run
        return None
    t_game.setdefault("on", time.monotonic())
    if time.monotonic() - t_game["on"] < 2.5:
        return "game: playing wow.exe"
    t_game.setdefault("off", time.monotonic())
    return None
eq.desktop_gate_reader = game_gate
fake(sleep={"a0": 6.0, "a1": 6.0, "a2": 6.0})
log.unlink(missing_ok=True)
eq.plan = units(["a0", "a1", "a2"], [])
err = io.StringIO()
os.environ["CT_SCAN_WORKERS"] = "3"  # scan_cap: three scans at once
quiet_nap, eq.QUIET_NAP = eq.QUIET_NAP, 1 # the pass that sees the game comes within a second
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=3, seconds=25, replan=0.5)
eq.QUIET_NAP = quiet_nap
os.environ.pop("CT_SCAN_WORKERS")
rows = [line.split() for line in log.read_text().splitlines()]
starts = {k: [float(r[0]) for r in rows if r[1] == "start" and r[3] == k] for k in ("a0", "a1", "a2")}
check("a game TERMs the scans beyond the cap: deferred (not failed), the oldest runs on",
      (True, 2, False, 1), ("TERM to 2 scan(s)" in err.getvalue(), err.getvalue().count("deferred (stopped for a game)"),
                            "failed" in err.getvalue(), len(starts["a0"])))
check("and they start again only once the game is over",
      (True, True), (all(len(starts[k]) == 2 and starts[k][1] >= t_game["off"] for k in ("a1", "a2")),
                     all(any(r[1] == "end" and r[3] == k for r in rows) for k in ("a0", "a1", "a2"))))
# A --beside filer is SIGSTOPped for the game, its --seconds clock stopped, and continued after.
def proc_state(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
bs = eq.Beside(["bash", "-c", "sleep 30", "x"])
bs.poll(True, 60)
bs.pause()
time.sleep(0.3)
state, began = proc_state(bs.proc.pid), bs.started
bs.resume()
time.sleep(0.3)
check("a --beside filer is stopped for a game and continued after, its clock credited the time stopped",
      ("T", True, False), (state, bs.started > began, proc_state(bs.proc.pid) == "T"))
bs.stop(signal.SIGTERM)
bs.proc.wait()
os.environ["CT_GAME_SCAN_WORKERS"] = "0"
fake(sleep={"x0": 30, "x1": 30})
log.unlink(missing_ok=True)
t_game.clear()
eq.plan = units(["x0", "x1"], [])
pid = os.fork()
if pid == 0:
    sys.stderr = open(os.devnull, "w")
    os._exit(eq.dispatch(["times"], cache, workers=1, scan_workers=2, beside=[["bash", "-c", "sleep 30", "x"]]))
time.sleep(2.5)  # the scans started, then were shed, the filer stopped, on the game
os.kill(pid, signal.SIGTERM)
t0 = time.monotonic()
rc = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
check("a TERM while the filer is stopped continues it first: exits 143 well inside STOP_GRACE", (143, True),
      (rc, time.monotonic() - t0 < eq.STOP_GRACE / 2))
os.environ.pop("CT_GAME_SCAN_WORKERS")
os.environ.pop("CT_YIELD_HOSTS")
eq.desktop_gate_reader = lambda: None
log.unlink(missing_ok=True)
fake(outcome={}, default=0.1)
# The VLM down (Paul 10-13:"just go onto the next scan and do it when it is
# back"): an edition's read is not started, its scan and a fetch-free scan
# are, and it says so; a read that is started (not needs_vlm) and ends
# deferred for the VLM is held, not started again, and left for the next run.
eq.vlm_gate_reader = lambda: False
eq.VLM_IDLE = 0.3
log.unlink(missing_ok=True)
fake(outcome={"t1": "vlm"}, default=0.1)
eq.plan = lambda papers, cache=None, reread=None, out=None: (
    [{"kind": "scan", "paper": "times", "rel": "vs", "rank": 1, "reason": "scan stale"}],
    [{"kind": "read", "paper": "times", "rel": "v1", "rank": 1, "reason": "never read", "needs": []},
     {"kind": "read", "paper": "trove", "rel": "t1", "rank": 1, "reason": "never read", "needs": []}])
err, out = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
    eq.dispatch(["times"], cache, workers=2, scan_workers=1, seconds=2.2, replan=0.5)
starts = sorted(line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start")
check("the VLM down: no edition read starts, the scan does, a Trove read once, it ends deferred and is held",
      (["t1", "vs"], True, True, True, False),
      (starts, "VLM down (" in err.getvalue(), "deferred (the VLM is down)" in err.getvalue(),
       "left for the next run" in out.getvalue(), "failed" in err.getvalue()))
check("the slice's tally names the scans deferred", True, "VLM down: 2 scans deferred" in out.getvalue())
eq.vlm_gate_reader = lambda: True
log.unlink(missing_ok=True)
fake(outcome={}, default=0.1)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, scan_workers=1, seconds=2.2, replan=0.5)
check("mirror: the VLM back, the edition's read starts", True,
      "v1" in [line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start"])
# The desktop's free memory gates the units that open an OCR session there:
# each started since its last reading is charged DESKTOP_SESSION_MB, and none
# starts that would take it under DESKTOP_FLOOR_MB.
os.environ["OCR_REMOTE"] = "tester@100.64.0.15"
real_prepare, eq.prepare = eq.prepare, lambda *a: None
read_at = time.time()
eq.desktop_mem_reader = lambda: (read_at, eq.DESKTOP_FLOOR_MB + 2 * eq.DESKTOP_SESSION_MB)
fake(outcome={}, default=1.5)
kept_plan, eq.plan = eq.plan, units([], [(f"m{k}", []) for k in range(4)])
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=4, scan_workers=1, seconds=1.0, replan=0.3)
check("the desktop's free memory less a session per start since its reading caps the starts, said once",
      (2, 1), (log.read_text().count("start"), err.getvalue().count("desktop-memory-bound")))
eq.desktop_mem_reader = lambda: (time.time() + 60, eq.DESKTOP_FLOOR_MB + 2 * eq.DESKTOP_SESSION_MB)
log.unlink(missing_ok=True)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=4, scan_workers=1, seconds=1.0, replan=0.3)
check("mirror: a reading newer than the starts counts them in its free memory, none charged again", 4,
      log.read_text().count("start"))
# A unit that ended since the reading gives its session back: the gate caps
# sessions open at once, not starts per reading (that held the live queue
# to ~4 starts a minute with 6-12 units running, 2026-10-13).
read_at = time.time()
eq.desktop_mem_reader = lambda: (read_at, eq.DESKTOP_FLOOR_MB + 2 * eq.DESKTOP_SESSION_MB)
fake(outcome={}, default=0.1)
log.unlink(missing_ok=True)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=4, scan_workers=1, seconds=1.5, replan=0.3)
check("units ended since the reading are not charged: all four start, two at a time", 4,
      log.read_text().count("start"))
check("an end is credited for a unit started since the reading or settled before it, not one still loading",
      (1, 0, 1, 2, 0), (eq.desktop_sessions(100, [101, 102], [(101, 103)]),
                        eq.desktop_sessions(100, [101], [(101, 103), (50, 104)]),
                        eq.desktop_sessions(100, [101], [(90, 104)]),
                        eq.desktop_sessions(100, [101, 102], [(101, 99)]),
                        eq.desktop_sessions(100, [], [(50, 104)])))
eq.desktop_mem_reader = lambda: None
log.unlink(missing_ok=True)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=4, scan_workers=1, seconds=1.0, replan=0.3)
check("mirror: no reading (the desktop not answering) holds nothing back", 4, log.read_text().count("start"))
eq.desktop_mem_reader = lambda: (time.time() - eq.DESKTOP_STALE_S - 1, eq.DESKTOP_FLOOR_MB)
log.unlink(missing_ok=True)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=4, scan_workers=1, seconds=1.0, replan=0.3)
check("a stale reading (probes failing since) holds nothing back: the units try the connection", 4,
      log.read_text().count("start"))
eq.prepare, eq.plan = real_prepare, kept_plan
os.environ.pop("OCR_REMOTE")
# A unit the desktop keeps losing (its read ends the server there) is started
# again with the desktop until it has ended lost LOST_TRIES times, then with none: read here.
eq.LOST_TRIES = 1
os.environ["OCR_REMOTE"] = "tester@192.0.2.180"
real_prepare, eq.prepare = eq.prepare, lambda *a: None  # no desktop probe
eq.plan = units([], [("d0", [])])  # its own plan: the cases above leave theirs
eq.desktop_mem_reader = lambda: None  # no memory gate
fake(outcome={"d0": "lost"}, default=0.05, env=True)
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=4, replan=0.5)
desk = [line.split(" ", 2)[2] for line in log.read_text().splitlines() if line.startswith("desktop ")]
check("a lost unit is started again with the desktop, then after LOST_TRIES with none",
      (["'tester@192.0.2.180'", "''"], True, False),
      (desk[:2], "deferred (the desktop was lost)" in err.getvalue(), "failed" in err.getvalue()))
# A read whose own scan went stale after its plan (a kept plan across a scan
# code change) is not started whole: a scan unit runs first, then the read
# is prepared for the desktop.
eq.prepare = lambda unit, *a: (eq.SCAN_FIRST if unit["kind"] == "read" and not (
    log.exists() and f"end scan {unit['rel']}" in log.read_text()) else None)
fake(default=0.05)
log.unlink(missing_ok=True)
eq.plan = units([], [("g1", [])])
eq.mem_gate_reader = lambda: 1 << 40  # this host's memory must not gate it
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=4, replan=0.5)
check("a read whose own scan is stale starts after a scan unit of its own, once",
      [["start", "scan", "g1"], ["end", "scan", "g1"], ["start", "read", "g1"], ["end", "read", "g1"]],
      [line.split()[1:4] for line in log.read_text().splitlines()])
# mirror: a read whose scan stands starts at once, no scan before it
eq.prepare = lambda *a: None
log.unlink(missing_ok=True)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=4, replan=0.5)
check("mirror: a read whose scan stands starts with no scan of its own",
      [["start", "read", "g1"], ["end", "read", "g1"]], [line.split()[1:4] for line in log.read_text().splitlines()])
# Briefs are made on a pool beside the loop: slow ones overlap, and every read starts.
import threading
_now, _peak = [0], [0]
def _slow_prepare(*a):
    _now[0] += 1
    _peak[0] = max(_peak[0], _now[0])
    time.sleep(0.6)
    _now[0] -= 1
eq.prepare = _slow_prepare
eq.plan = units([], [(f"s{k}", []) for k in range(3)])
fake(default=0.05)
log.unlink(missing_ok=True)
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=5, replan=0.5)
check("slow briefs are made side by side, and every read starts",
      (True, ["s0", "s1", "s2"]),
      (_peak[0] >= 2, sorted(line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start")))
os.environ.pop("OCR_REMOTE")
eq.prepare = real_prepare
eq.desktop_gate_reader = lambda: None
eq.cpu_gate_reader = lambda: 0.0
eq.mem_gate_reader = None
log.unlink(missing_ok=True)
eq.plan = units([], [(f"m{k}", []) for k in range(3)])
gate_reads = []
eq.mem_gate_reader = lambda: gate_reads.append(1) or 1 * G
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("short of memory nothing starts, and it says so once", (False, 1),
      (log.exists(), err.getvalue().count("memory-bound")))
check("a gate holding one unit back is read once a pass, not once a unit due", True, len(gate_reads) <= 4)
# mirror: the same plan with room starts every unit and never says memory-bound
eq.mem_gate_reader = lambda: 16 * G
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.5)
check("with room every unit starts, no memory-bound line", (3, 0),
      (sum(" start " in l for l in log.read_text().splitlines()), err.getvalue().count("memory-bound")))
eq.mem_gate_reader = None

# Memory pressure (fake /proc/pressure/memory and /proc/meminfo) holds starts back, and says so once.
_psi, _mi = T / "psi", T / "meminfo"
_mi.write_text(f"MemAvailable: {16 * G >> 10} kB\n")
_psi.write_text("some avg10=20.00 avg60=9.00 avg300=1.00 total=1\nfull avg10=12.50 avg60=15.00 avg300=1.00 total=1\n")
os.environ.update(CT_PSI_PATH=str(_psi), CT_MEMINFO=str(_mi))
check("pressure reads full avg10", 12.5, mg.pressure())
check("room says no over the pressure max, memory plenty", False, mg.room())
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("under memory pressure nothing starts, and it says so once", (False, 1),
      (log.exists(), err.getvalue().count("memory-bound")))
_psi.write_text("full avg10=1.00 avg60=1.00 avg300=1.00 total=1\n")
check("calm and roomy: room", True, mg.room())
_mi.write_text(f"MemAvailable: {2 * G >> 10} kB\n")
check("calm but under 3 GB available: no room", False, mg.room())
# the unit-children ceiling: 5 queued reads, ceiling 2, never more than 2 at once
_mi.write_text(f"MemAvailable: {16 * G >> 10} kB\n")
os.environ["CT_UNIT_CEILING"] = "2"
os.environ["CT_UNIT_CEILING_FILE"] = "/nonexistent/unit_ceiling"  # a live override file must not leak in
os.environ["CT_VLM_SPOOL_MAX_FILE"] = "/nonexistent/vlm_spool_max"  # likewise the live spool-depth file
eq.plan = units([], [(f"c{k}", []) for k in range(5)])
# Units outlast the dispatcher's 1 s pass nap (the pass after a start): the ceiling line
# is logged by a pass that finds the ceiling met with units still running, so units that
# end inside that nap (0.8 s did, and a fast host never logged it) would never be seen at it.
fake(default=2.0)
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=5, scan_workers=1, seconds=3, replan=0.5)
_ev = [(float(l.split()[0]) if l.split()[0].replace(".", "").isdigit() else 0, l.split()[1]) for l in log.read_text().splitlines()]
_open = _peak2 = 0
for _, w in _ev:
    _open += 1 if w == "start" else -1 if w == "end" else 0
    _peak2 = max(_peak2, _open)
check("the ceiling holds starts to 2 at once, and says so", (True, True),
      (_peak2 == 2, "unit ceiling" in err.getvalue()))
os.environ.pop("CT_UNIT_CEILING")

# VLM-waiting cap: while CT_VLM_WAITING reads have an ask under way no read starts, and it says so once.
os.environ["CT_VLM_WAITING"] = "2"
os.environ["CT_VLM_SPOOL"] = "0"  # the spool-off cap (spool on: the cases below)
_w = vlm_reader.waiting_now
vlm_reader.waiting_now = lambda: 2
eq.plan = units([], [(f"v{k}", []) for k in range(3)])
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("reads wait for the VLM's queue to drain, and it says so once", (False, 1),
      (log.exists(), err.getvalue().count("vlm-bound")))
vlm_reader.waiting_now = lambda: 1
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.5)
check("below the cap every read starts", (3, 0),
      (sum(" start " in l for l in log.read_text().splitlines()), err.getvalue().count("vlm-bound")))
vlm_reader.waiting_now = _w
os.environ.pop("CT_VLM_SPOOL")
# Spool on: the queue's own drainer mark and a part-filled spool never hold read starts; a full spool does.
_sp = vlm_reader.spooled
os.environ["CT_VLM_WAITING"] = "2"
os.environ["CT_VLM_SPOOL_MAX"] = "10"
vlm_reader.waiting_now = lambda: 1  # the queue's own mark, which the gate subtracts
vlm_reader.spooled = lambda: [f"k{i}" for i in range(9)]
_own = vlm_reader._waiting_dir() / str(os.getpid())
_own.parent.mkdir(parents=True, exist_ok=True)
_own.touch()
eq.plan = units([], [(f"v{k}", []) for k in range(3)])
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.5)
check("spool on, spool below max: reads start despite the drainer's mark", (3, 0),
      (sum(" start " in l for l in log.read_text().splitlines()), err.getvalue().count("vlm-bound")))
vlm_reader.spooled = lambda: [f"k{i}" for i in range(10)]
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("spool on, spool full: fresh reads that may ask are held (bb548de531f); none starts, no vlm-bound line", (0, 0),
      (sum(" start " in l for l in (log.read_text() if log.exists() else "").splitlines()), err.getvalue().count("vlm-bound")))
check("the queue's cap is the reader's", True, eq.vlm_spool_max() == vlm_reader.vlm_spool_max() == 10)
# GPU fill: with the VLM stage short of asks, another paper's never-read read goes ahead of the
# CT_NEWEST_FIRST paper's OCR-only rereads (Times first otherwise), and the queue says so.
_pipe0, _sl0 = vlm_reader.PIPELINE, vlm_reader._SLOTS[0]
vlm_reader.PIPELINE, vlm_reader._SLOTS[0] = 1, 2
os.environ["CT_NEWEST_FIRST"] = "gale"
_mk = lambda paper, rel, rank, reason: {"kind": "read", "paper": paper, "rel": rel, "rank": rank, "reason": reason, "needs": []}
_tm = [_mk("gale", f"g{k}", 2, "scan stale, answers linked") for k in range(3)]
_ft = [_mk("times", f"t{k}", 1, "never read") for k in range(3)]
_cands = [(u, eq.key_of(u)) for u in _tm + _ft]
_none = lambda u: False
check("gpu_fill: an unfed VLM stage takes the other paper's never-read reads, within half the read pool", ["t0", "t1"],
      [u["rel"] for u in eq.gpu_fill(_cands, set(), set(), _none, _none, 0, False, 0, 2)])
check("gpu_fill: spooled asks at the feed target (CT_VLM_FEED, 4), no fill", ([], ["t0"]),
      (eq.gpu_fill(_cands, set(), set(), _none, _none, 4, False, 0, 2), [u["rel"] for u in eq.gpu_fill(_cands, set(), set(), _none, _none, 3, False, 0, 4)]))
# answers_only rereads ask the VLM nothing: they never feed it, even ranked first; never-read, fix-landed and proven ones do.
_al = _mk("times", "al", 2, "inputs changed: answers linked x1")
_fx = _mk("times", "fx", 2, "unfiled before its fix")
_cp = _mk("gale", "cp", 2, "inputs changed: answers linked x1")
check("fills_gpu: answers-linked rereads are CPU-only, never-read and fix-landed ones feed", (False, True, True, False),
      (eq.fills_gpu(_al), eq.fills_gpu(_fx), eq.fills_gpu(_ft[0]), eq.fills_gpu(_cp)))
check("gpu_fill: answers-linked rereads ranked first do not fill, the never-read ones behind them do", ["t0", "fx"],
      [u["rel"] for u in eq.gpu_fill([(u, eq.key_of(u)) for u in [_al, _cp, _ft[0], _fx]], set(), set(), _none, _none, 2, False, 0, 2)])
# Paul 10-22: Times solution rereads (1-3 asks each) held all 18 slots, the GPU ~27% busy. They are no fill,
# so the FT never-read reads behind them are, and the reserve holds slots for those; nor are they cpu-only
# (no cpu-only cap on them) or answers-linked (no batching).
_lo = [_mk("times", f"s{k}", 2, r) for k, r in enumerate(eq.LOW_ASK)]
check("fills_gpu: low-ask solution rereads do not feed; neither cpu-only nor answers-linked", ([False] * len(eq.LOW_ASK),) * 3,
      ([eq.fills_gpu(u) for u in _lo], [eq.cpu_only_unit(u) for u in _lo],
       [eq.answers_linked({**u, "paper": next(iter(eq.fa.FILERS))}) for u in _lo]))
check("gpu_fill: low-ask solution rereads ranked first do not fill, the never-read ones behind them do", ["t0", "t1"],
      [u["rel"] for u in eq.gpu_fill([(u, eq.key_of(u)) for u in _lo + _ft], set(), set(), _none, _none, 0, False, 0, 2)])
check("gpu_fill: a full spool, no fill", [],eq.gpu_fill(_cands, set(), set(), _none, _none, 0, True, 0, 2))
check("gpu_fill: fills running count against the half pool", ["t0"], [u["rel"] for u in eq.gpu_fill(_cands, set(), set(), _none, _none, 0, False, 1, 2)])
check("gpu_fill: tried, running and waiting reads are skipped", ["t2"],
      [u["rel"] for u in eq.gpu_fill(_cands, {eq.key_of(_ft[0])}, {eq.key_of(_ft[1])}, _none, _none, 2, False, 0, 2)])
# Every FT read waits on its own scan, queued behind the Gale and Times scans: the fill brings the scan forward.
_sc = {("times", f"t{k}"): {"kind": "scan", "paper": "times", "rel": f"t{k}", "rank": 1, "reason": "never scanned", "needs": []}
       for k in range(3)}
_waiting = lambda u: u["kind"] == "read" and u["paper"] == "times"
_scan_of = lambda u: _sc.get((u["paper"], u["rel"]))
check("gpu_fill: reads waiting on their own scan are not filled, nor are their scans (a scan never asks the VLM)", ([], []),
      ([u["rel"] for u in eq.gpu_fill(_cands, set(), set(), _waiting, _none, 0, False, 0, 2)],
       [u["rel"] for u in eq.gpu_fill(_cands, set(), set(), _waiting, _none, 0, False, 0, 2, _scan_of)]))
# Paul 10-23: GPU 0% for 6+ min, every fill read waiting on its own scan far back in the plan. With no fill
# read ready, the scans they wait on start, in the reads' order, at most max_scans running at once.
_fs = lambda *a, **k: [(u["kind"], u["rel"]) for u in eq.gpu_fill(*a, **k)]
check("gpu_fill: no fill read ready, the scans they wait on start, capped at max_scans", [("scan", "t0"), ("scan", "t1")],
      _fs(_cands, set(), set(), _waiting, _none, 0, False, 0, 2, _scan_of, frozenset(), 2))
check("gpu_fill: a running scan a fill read waits on counts against max_scans", [("scan", "t1")],
      _fs(_cands, set(), set(), _waiting, _none, 0, False, 0, 2, _scan_of, {("times", "t0")}, 2))
check("gpu_fill: max_scans already running, no more scans", [],
      _fs(_cands, set(), set(), _waiting, _none, 0, False, 0, 2, _scan_of, {("times", "t0"), ("times", "t2")}, 2))
check("gpu_fill: tried or running scans are skipped", [("scan", "t2")],
      _fs(_cands, {eq.key_of(_sc["times", "t0"])}, {eq.key_of(_sc["times", "t1"])}, _waiting, _none, 0, False, 0, 2,
          _scan_of, frozenset(), 3))
check("gpu_fill: a ready fill read goes alone, no scan pulled forward", [("read", "t0")],
      _fs(_cands, set(), set(), lambda u: u["rel"] in ("t1", "t2"), _none, 0, False, 0, 2, _scan_of, frozenset(), 2))
check("gpu_fill: a fed VLM or a full spool pulls no scan", ([], []),
      (_fs(_cands, set(), set(), _waiting, _none, 4, False, 0, 2, _scan_of, frozenset(), 2),
       _fs(_cands, set(), set(), _waiting, _none, 0, True, 0, 2, _scan_of, frozenset(), 2)))
check("gpu_fill: CPU-only reads waiting on scans pull none forward", [],
      _fs([(u, eq.key_of(u)) for u in _tm], set(), set(), lambda u: True, _none, 0, False, 0, 2,
          lambda u: {**u, "kind": "scan"}, frozenset(), 2))
# Times first (Paul 10-21): the named papers' pending scans take every slot their ready reads will not.
_ms = lambda paper, rel: {"kind": "scan", "paper": paper, "rel": rel, "rank": 2, "reason": "scan stale"}
_tsc = [_ms("gale", "a"), _ms("ft", "f"), _ms("gale", "b"), _ms("gale", "c"), _ms("gale", "d")]
check("times_scans_pending: the named papers' scans, not FT's, not tried, running or done", ["a"],
      [u["rel"] for u in eq.times_scans_pending([_tsc], {eq.key_of(_tsc[2])}, {eq.key_of(_tsc[3])}, {("gale", "d")})])
check("times_scan_room: all but the ready reads' slots, capped at the pending scans", (10, 3, 7, 7),
      (eq.times_scan_room(40, 5, 2, 12, 15), eq.times_scan_room(3, 0, 1, 12, 20), eq.times_scan_room(40, 5, 2, 3, 10),
       eq.times_scan_room(40, 0, 7, 12, 4)))
check("times_scan_room: nothing pending leaves the pool's own room", 4, eq.times_scan_room(0, 5, 4, 12, 20))
check("listener_free: nothing else due takes every ceiling slot left; other work due keeps the fixed pool",
      (16, 0, 3, -4, 5),
      (eq.listener_free(0, False, 16), eq.listener_free(0, True, 16), eq.listener_free(3, False, 0),
       eq.listener_free(-4, True, 10), eq.listener_free(5, False, 2)))
del os.environ["CT_NEWEST_FIRST"]
check("times_scans_pending: without CT_NEWEST_FIRST, none", [], eq.times_scans_pending([_tsc], set(), set(), set()))
check("gpu_fill: without CT_NEWEST_FIRST the VLM is fed too", ["t0", "t1"],
      [u["rel"] for u in eq.gpu_fill(_cands, set(), set(), _none, _none, 0, False, 0, 2)])
vlm_reader.PIPELINE, vlm_reader._SLOTS[0] = _pipe0, _sl0
_own.unlink(missing_ok=True)
vlm_reader.spooled = _sp
os.environ.pop("CT_VLM_SPOOL_MAX")
os.environ.pop("CT_VLM_WAITING")

# The VLM stage: vlm_drainer answers spooled asks (the server stubbed) into the cache while no read blocks,
# and a spooled read's asks stop being pending.
import threading as _th
import tempfile as _tf
import urllib.request as _ur
_cache, _slots, _pipe, _real, _gate = vlm_reader.CACHE, vlm_reader._SLOTS[0], vlm_reader.PIPELINE, _ur.urlopen, eq.vlm_gate_reader
vlm_reader.CACHE = T / "vlm-stage"
(T / "vlm-stage-tmp").mkdir(exist_ok=True)
_tempdir, _tf.tempdir = _tf.tempdir, str(T / "vlm-stage-tmp")  # the host's real slot locks are held by live askers
vlm_reader._SLOTS[0], vlm_reader.PIPELINE = 1, 0
_ur.urlopen = lambda req, timeout=None: io.BytesIO(json.dumps({"choices": [{"message": {"content": "A"}}]}).encode())
eq.vlm_gate_reader = lambda: True
_busy, vlm_reader.busy = vlm_reader.busy, lambda: ""
_keys = [vlm_reader.ask_key(b"png%d" % k, "p") for k in range(3)]
for _k, _b in zip(_keys, range(3)):
    vlm_reader.put_spool(_k, b"png%d" % _b, "p", 10)
_stop = _th.Event()
eq.vlm_drainer(_stop, [])
for _ in range(100):
    if not vlm_reader.spooled():
        break
    time.sleep(0.1)
_stop.set()
time.sleep(1)  # its threads end before the real cache is back
check("the drainer answers every spooled ask into the cache", (0, True),
      (len(vlm_reader.spooled()), all((vlm_reader.CACHE / f"{k}.txt").exists() for k in _keys)))
vlm_reader.CACHE, vlm_reader._SLOTS[0], vlm_reader.PIPELINE, _ur.urlopen, eq.vlm_gate_reader = _cache, _slots, _pipe, _real, _gate
vlm_reader.busy = _busy
_tf.tempdir = _tempdir
# A unit deferred by spooled asks says so; a real VLM outage keeps its words.
_cause = vlm_reader._CAUSE[0]
vlm_reader._CAUSE[0] = "spooled"
check("a spooled deferral is logged as spooled, not down", "deferred, 0 VLM asks spooled", eq.vlm_deferral(RuntimeError("x")))
vlm_reader._CAUSE[0] = "refused"
check("a real VLM outage is logged as down", "deferred, the VLM is down (boom)", eq.vlm_deferral(RuntimeError("boom")))
vlm_reader._CAUSE[0] = _cause
os.environ["CT_PSI_PATH"] = str(T / "no-psi")
os.environ.pop("CT_MEMINFO")

# unit_queue.tick shares the gate: short of memory it starts nothing, with room it starts all
import types
import unit_queue as uq
uq.LOAD_READER = lambda: 0.0
class _Ledger:
    def __init__(self, queue): pass
    def compact(self): pass
    def running_units(self): return {}
stub = types.SimpleNamespace(LIMITS={}, SLOTS=0, LOG="x.log")
uq.queue_module = lambda name: stub
uq.Ledger = _Ledger
uq.STATE = T / "uq-state"
uq.main_checkout = lambda: T
uq.due_units = lambda mod, ledger, now: [(types.SimpleNamespace(key=f"k{i}", cls=""), "due") for i in range(3)]
spawned = []
uq.spawn = lambda queue, unit, logfile: spawned.append(unit.key)
for reader, want in ((lambda: 1 * G, (0, 1)), (lambda: 16 * G, (3, 0))):
    uq.MEM_READER = reader
    spawned.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        uq.tick("fake")
    check("tick: units started / memory-bound lines", want, (len(spawned), out.getvalue().count("memory-bound")))
uq.MEM_READER = None

# ---- burn first: while the burn's cpu cap holds it below its need, no unit starts
capped = {"need": 8, "mem": 20, "cpu": 3, "width": 3}
enough = {"need": 8, "mem": 20, "cpu": 9, "width": 8}
check("burn_starved: cpu-capped below its need gates", capped, mg.burn_starved(lambda: capped))
check("burn_starved: cpu cap at or over the need does not", None, mg.burn_starved(lambda: enough))
check("burn_starved: memory, not cpu, holding it back does not", None,
      mg.burn_starved(lambda: {"need": 8, "mem": 2, "cpu": 3, "width": 2}))
check("burn_starved: no need or no cpu reading does not", (None, None),
      (mg.burn_starved(lambda: {"need": None, "mem": 20, "cpu": 3}),
       mg.burn_starved(lambda: {"need": 8, "mem": 20, "cpu": None})))
state = T / "burn.width"
state.write_text(json.dumps(capped))
check("burn_state: a fresh plan is read", capped, mg.burn_state(state))
os.utime(state, (time.time() - mg.BURN_STALE_S - 60,) * 2)
check("burn_state: a stale plan (no burn planning) is none, so no gate", (None, None),
      (mg.burn_state(state), mg.burn_starved(lambda: mg.burn_state(state))))
check("burn_state: no plan or a garbled one is none", (None, None),
      (mg.burn_state(T / "absent"), (state.write_text("{oops"), mg.burn_state(state))[1]))
eq.plan = units([], [(f"b{k}", []) for k in range(3)])
log.unlink(missing_ok=True)
eq.burn_gate_reader = lambda: capped
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("the burn cpu-capped: nothing starts, and it says so once", (False, 1),
      (log.exists(), err.getvalue().count("burn-first")))
# mirror: the burn with its width starts every unit and never says burn-first
eq.burn_gate_reader = lambda: enough
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.5)
check("the burn with its width: every unit starts, no burn-first line", (3, 0),
      (sum(" start " in l for l in log.read_text().splitlines()), err.getvalue().count("burn-first")))
eq.burn_gate_reader = None
uq.MEM_READER = lambda: 16 * G
for reader, want in ((lambda: capped, (0, 1)), (lambda: enough, (3, 0)), (lambda: None, (3, 0))):
    uq.BURN_READER = reader
    spawned.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        uq.tick("fake")
    check("tick: units started / burn-first lines", want, (len(spawned), out.getvalue().count("burn-first")))
uq.BURN_READER = uq.MEM_READER = None

# ---- one version of the code a process: a start loads its lazy imports
# too (the write path's puzzle_integrity), under code.lock; a tree move
# holding code.lock alone makes a start wait it out.
import subprocess, fcntl
probe = ("import runpy, sys; sys.argv = ['edition_queue.py', '-h']\n"
         "try:\n    runpy.run_path('edition_queue.py', run_name=RUN)\nexcept SystemExit:\n    pass\n"
         "print('puzzle_integrity' in sys.modules, file=sys.stderr)")
loaded = [subprocess.run([sys.executable, "-c", probe.replace("RUN", repr(run))], capture_output=True, text=True,
                         timeout=120).stderr.strip().splitlines()[-1] for run in ("__main__", "edition_queue")]
check("a run's start loads the modules it imports lazily; a plain import does not", ["True", "False"], loaded)
# a third-party package missing (requests, absent on CI) skips the module
# needing it; a missing tree module still fails the start
for blocked_mod, want in (("requests", "True"), ("fetch_ia_book", "ModuleNotFoundError")):
    out = subprocess.run([sys.executable, "-c", f"import sys; sys.modules[{blocked_mod!r}] = None\n"
                          + probe.replace("RUN", repr("__main__"))], capture_output=True, text=True,
                         timeout=120).stderr.strip().splitlines()[-1]
    check(f"a start with {blocked_mod} not installed: {want}", want, out.split(":")[0])
# A fetch unit loads its source's module and MODULES, exactly what its
# fetch_unit reaches, and none of the queue's filers.
import code_reach, importlib
for src, (name, _) in sorted(eq.FETCH_UNITS.items()):
    mod = importlib.import_module(name)
    check(f"{name}.MODULES is what its fetch_unit reaches",
          sorted({m for m, _ in code_reach.reach(name, ["fetch_unit"], opaque=())} - {name}), sorted(mod.MODULES))
    fetch_probe = (f"import importlib, json, os, runpy, sys\n"
                   f"m = importlib.import_module({name!r}); m.fetch_unit = lambda *a: 'busy'\n"
                   f"os.environ['CT_EDITION_UNIT'] = json.dumps({{'unit': {{'kind': 'fetch', 'paper': {src!r}, 'rel': 'x'}}}})\n"
                   f"sys.argv = ['edition_queue.py', 'unit', 'fetch', {src!r}, 'x']\n"
                   f"try:\n    runpy.run_path('edition_queue.py', run_name='__main__')\n"
                   f"except SystemExit as e:\n"
                   f"    print(e.code, all(n in sys.modules for n in m.MODULES),\n"
                   f"          [n for n in ('code_reach', 'gale_listener', 'mem_gate') if n in sys.modules],"
                   f" file=sys.stderr)")
    got = subprocess.run([sys.executable, "-c", fetch_probe], capture_output=True, text=True,
                         timeout=120).stderr.strip().splitlines()[-1]
    check(f"a {src} fetch unit loads its MODULES, not the queue's, and exits its outcome", f"{eq.EXITS['busy']} True []", got)
# A scan or read unit loads its paper's module and what that may load
# (lazy imports too), not the queue's other filers and fetchers.
for kind, paper, fn in (("scan", "gale", "scan_unit"), ("read", "trove", "read_unit")):
    name = eq.UNIT_MODULES.get(paper, eq.UNIT_MODULES[None])
    unit_probe = (f"import importlib, json, os, runpy, sys\n"
                  f"m = importlib.import_module({name!r}); m.{fn} = lambda *a, **k: 'busy'\n"
                  f"os.environ['CT_EDITION_UNIT'] = json.dumps({{'unit': {{'kind': {kind!r}, 'paper': {paper!r}, 'rel': 'x'}},"
                  f" 'cache': '/nonexistent', 'puzzles': None, 'reread': None}})\n"
                  f"sys.argv = ['edition_queue.py', 'unit', {kind!r}, {paper!r}, 'x']\n"
                  f"try:\n    runpy.run_path('edition_queue.py', run_name='__main__')\n"
                  f"except SystemExit as e:\n"
                  f"    print(e.code, 'puzzle_integrity' in sys.modules,\n"
                  f"          [n for n in ('fetch_trove', 'gale_listener', 'mem_gate') if n in sys.modules],"
                  f" file=sys.stderr)")
    got = subprocess.run([sys.executable, "-c", unit_probe], capture_output=True, text=True,
                         timeout=120).stderr.strip().splitlines()[-1]
    check(f"a {kind} {paper} unit loads {name}'s reach, not the queue's, and exits its outcome",
          f"{eq.EXITS['busy']} True []", got)
# The queue process leaves the blog filers' modules unloaded (their pushes reload nothing) and the static closure free of them.
_skipped = eq.never_loaded(code_reach.modules("edition_queue"))
check("the queue does not load the blog filers' modules, so a push to them is no reload",
      (True, True), ({"file_blog_puzzles", "parse_timesforthetimes"} <= _skipped,
                     not (_skipped & {Path(p).stem for p in eq.hot_reload.queue_code(eq.TOOLS)})))
# code_reach keeps its answers per version of tools/: an edit is a new answer.
saved = code_reach.TOOLS, code_reach.STORE
code_reach.TOOLS, code_reach.STORE = T / "reach-tools", T / "reach-store"
code_reach.TOOLS.mkdir()
(code_reach.TOOLS / "ra.py").write_text("import rb\ndef f():\n    return rb.g()\n")
(code_reach.TOOLS / "rb.py").write_text("def g():\n    return 1\n")
first = (code_reach.modules("ra"), code_reach.key("ra", {"f"}))
again = (code_reach.modules("ra"), code_reach.key("ra", {"f"}), len([p for p in code_reach.STORE.glob("*.json") if p.name != "tree.json"]))  # tree.json is the kept tree hash, not an answer
(code_reach.TOOLS / "rb.py").write_text("def g():\n    return 2\n")
(code_reach.TOOLS / "ra.py").write_text("import rb\ndef f():\n    import rc\n    return rb.g()\n")
(code_reach.TOOLS / "rc.py").write_text("")
edited = (code_reach.modules("ra"), code_reach.key("ra", {"f"}))
check("code_reach answers again from its store, and anew after an edit",
      ({"ra", "rb"}, True, 1, {"ra", "rb", "rc"}, True),
      (first[0], again[:2] == first, again[2], edited[0], edited[1] != first[1]))
code_reach.TOOLS, code_reach.STORE = saved
# count_left_requests finds each id off one listing of its series' year
# folders and parses a file again only once its stat moves (a plan's ~8k
# files took two minutes a plan); save/load carries the parses to a re-exec.
import puzzle_paths
cl = T / "countleft"
(cl / "zq" / "1990").mkdir(parents=True)
(cl / "zq" / "1991").mkdir(parents=True)
bad = {"entries": [{"number": 1, "length": 7, "clue": {"text": "Overdone quality 7"}}]}
good = {"entries": [{"number": 1, "length": 7, "clue": {"text": "Overdone quality"}}]}
(cl / "zq" / "1990" / "zq-1.json").write_text(json.dumps(bad))
(cl / "zq" / "1991" / "zq-2.json").write_text(json.dumps(good))
real_cl = (q.sources, q.read_before, puzzle_paths.PUZZLE_DIR, q.json.loads)
q.sources = lambda: {i: ("archive", f"src-{i}", {}) for i in ("zq-1", "zq-2", "zq-3")}
q.read_before = lambda row, at: True
puzzle_paths.PUZZLE_DIR = cl
cl_parsed = []
q.json.loads = lambda text, *a, **k: cl_parsed.append(1) or real_cl[3](text, *a, **k)
q._COUNT_LEFT.clear()
first_cl = [r["id"] for r in q.count_left_requests()]
again_cl = [r["id"] for r in q.count_left_requests()]
check("count_left_requests: the held file with a count left, each parsed once",
      (["zq-1"], ["zq-1"], 2), (first_cl, again_cl, len(cl_parsed)))
time.sleep(0.01)
(cl / "zq" / "1991" / "zq-2.json").write_text(json.dumps(bad) + " ")
check("a file whose stat moved is parsed again", (["zq-1", "zq-2"], 3),
      ([r["id"] for r in q.count_left_requests()], len(cl_parsed)))
q.save_count_left(T / "count_left.pickle")
q._COUNT_LEFT.clear()
q.load_count_left(T / "count_left.pickle")
check("a re-exec's first call parses nothing loaded", (["zq-1", "zq-2"], 3),
      ([r["id"] for r in q.count_left_requests()], len(cl_parsed)))
q.sources, q.read_before, puzzle_paths.PUZZLE_DIR, q.json.loads = real_cl

# read_waits (needs tested by paper, one isdisjoint) decides as the per-need
# pair test it replaced, on every mix of running, unscanned and rescanned.
import random
def waits_before(u, scanning, unscanned, rescanned):
    return (any((u["paper"], r) in scanning for r in u["needs"]) or (u["paper"], u["rel"]) in unscanned
            or (u["reason"] in f.STALE_SCAN and any((u["paper"], r) in rescanned for r in u["needs"])))
rw = random.Random(7)
pairs_w = [(p, f"e{i}") for p in ("times", "gale", "trove") for i in range(12)]
stale_w = next(iter(f.STALE_SCAN))
differ_w = seen_w = 0
for _ in range(400):
    scanning_w = set(rw.sample(pairs_w, rw.randrange(6)))
    rescanned_w = set(rw.sample(pairs_w, rw.randrange(8)))
    unscanned_w = set(rw.sample(pairs_w, rw.randrange(10)))
    sb_w, rb_w = eq.rels_by_paper(scanning_w), eq.rels_by_paper(rescanned_w)
    for p, rel in pairs_w:
        u = {"kind": "read", "paper": p, "rel": rel, "reason": rw.choice([stale_w, "never read"]),
             "needs": [r for q_, r in rw.sample(pairs_w, rw.randrange(5)) if q_ == p] + [rel] * rw.randrange(2)}
        want_w = waits_before(u, scanning_w, unscanned_w, rescanned_w)
        differ_w += want_w != eq.read_waits(u, sb_w, unscanned_w, rb_w)
        seen_w += want_w
check("read_waits decides as the per-need test it replaced (some reads wait)", (0, True), (differ_w, seen_w > 1000))
held_w = {"kind": "read", "paper": "times", "rel": "e1", "reason": "never read", "needs": ["e0", "e1"]}
sb_w = eq.rels_by_paper(set())
before_w = eq.read_waits(held_w, sb_w, set(), {})
sb_w.setdefault("times", set()).add("e0")  # a scan of e0 begun earlier in the walk
check("a read waits on a scan begun earlier in the same walk", (False, True),
      (before_w, eq.read_waits(held_w, sb_w, set(), {})))

fa_w = [{"paper": "a"}, {"paper": "b"}, {"paper": "c"}]
same_w = eq.unchanged(fa_w, [u for u in fa_w if u["paper"] != "z"])
cut_w = eq.unchanged(fa_w, [u for u in fa_w if u["paper"] != "b"])
check("unchanged keeps the list's id while the same units stand, else the new list",
      (True, False, [{"paper": "a"}, {"paper": "c"}]), (same_w is fa_w, cut_w is fa_w, cut_w))

fe_w = [{"paper": "a", "rel": "x"}]
check("unchanged_eq keeps the old list while an equal one is rebuilt, else the new list",
      (True, False), (eq.unchanged_eq(fe_w, [{"paper": "a", "rel": "x"}]) is fe_w,
                      eq.unchanged_eq(fe_w, [{"paper": "a", "rel": "y"}]) is fe_w))

check("scans run one at a time: the default and any --scan-workers are capped at 1", (1, 1),
      (eq.SCAN_WORKERS, eq.argparse.ArgumentParser and 1))
import inspect
check("dispatch caps scan_workers at scan_cap()", True, "min(scan_workers, scan_cap())" in inspect.getsource(eq.dispatch))

# CT_SCAN_WORKERS raises the scan cap; unset, empty or junk keeps 1.
scan_env = os.environ.pop("CT_SCAN_WORKERS", None)
caps = []
for v in (None, "", "junk", "0", "-3", "8"):
    if v is None:
        os.environ.pop("CT_SCAN_WORKERS", None)
    else:
        os.environ["CT_SCAN_WORKERS"] = v
    caps.append(eq.scan_cap())
check("CT_SCAN_WORKERS: default 1, junk or below 1 ignored, else the cap", [1, 1, 1, 1, 1, 8], caps)
check("--scan-workers defaults to the cap", True, "default=scan_cap()" in inspect.getsource(eq))

# Scans spread over cores while several run: each takes a core no other holds.
spread_dir, real_tmp = tempfile.mkdtemp(), tempfile.tempdir
tempfile.tempdir = spread_dir
got_cpus = [eq.spread_cpu([0, 1, 2, 3]) for _ in range(5)]
tempfile.tempdir = real_tmp
for fd in eq.SCAN_CPU_LOCKS:
    os.close(fd)
eq.SCAN_CPU_LOCKS.clear()
check("spread_cpu: the last free core each time, then one by pid when all are held",
      ([3, 2, 1, 0], True), (got_cpus[:4], got_cpus[4] in (0, 1, 2, 3)))
pin_probe = ("import os, runpy, sys\n"
             "m = runpy.run_path('edition_queue.py', run_name='probe')\n"
             "m['pin_scan']()\n"
             "print(sorted(os.sched_getaffinity(0)), file=sys.stderr)\n")
last_cpu = sorted(os.sched_getaffinity(0))[-1:]
for cap in ("1", "4"):
    pin_got = subprocess.run([sys.executable, "-c", pin_probe], capture_output=True, text=True, timeout=120,
                             env={**os.environ, "CT_SCAN_WORKERS": cap, "TMPDIR": spread_dir}).stderr.strip().splitlines()[-1]
    check(f"pin_scan with CT_SCAN_WORKERS={cap}: one core, the last when nothing else holds it", str(last_cpu), pin_got)
hold = [os.open(os.path.join(spread_dir, f"ct_scan_cpu_{sorted(os.sched_getaffinity(0))[-1]}.lock"), os.O_CREAT | os.O_RDWR)]
import fcntl as _fc
_fc.flock(hold[0], _fc.LOCK_EX)
pin_got = subprocess.run([sys.executable, "-c", pin_probe], capture_output=True, text=True, timeout=120,
                         env={**os.environ, "CT_SCAN_WORKERS": "4", "TMPDIR": spread_dir}).stderr.strip().splitlines()[-1]
check("pin_scan with several scans at once: the last core held, it takes another one core",
      (1, False), (len(eval(pin_got)), eval(pin_got) == last_cpu) if len(sorted(os.sched_getaffinity(0))) > 1 else (1, False))
os.close(hold[0])
pin_got = subprocess.run([sys.executable, "-c", pin_probe], capture_output=True, text=True, timeout=120,
                         env={**os.environ, "CT_SCAN_WORKERS": "4", "OCR_SCAN_CPU": "0", "TMPDIR": spread_dir}).stderr.strip().splitlines()[-1]
check("OCR_SCAN_CPU still names the core", str(sorted(os.sched_getaffinity(0))[:1]), pin_got)
if scan_env is None:
    os.environ.pop("CT_SCAN_WORKERS", None)
else:
    os.environ["CT_SCAN_WORKERS"] = scan_env

# CT_YIELD_HOSTS: the queue yields to those hosts through desktop_busy.busy even with OCR_REMOTE empty.
import desktop_busy
yield_env = {k: os.environ.pop(k, None) for k in ("CT_YIELD_HOSTS", "OCR_REMOTE")}
real_gate, real_dbusy, asked = eq.desktop_gate_reader, desktop_busy.busy, []
eq.desktop_gate_reader = None
desktop_busy.busy = lambda hosts: asked.append(list(hosts)) or "a game is running"
check("no hosts, no CT_YIELD_HOSTS: desktop_busy is never asked, not yielding", (None, []), (eq.desktop_yielding(), asked))
os.environ["CT_YIELD_HOSTS"] = "  "
check("blank CT_YIELD_HOSTS is the same as unset", (None, []), (eq.desktop_yielding(), asked))
os.environ["CT_YIELD_HOSTS"] = "tester@192.0.2.198 b@host"
check("CT_YIELD_HOSTS with OCR_REMOTE empty: yields to a busy host",
      ("a game is running", [["tester@100.64.0.15", "tester@192.0.2.198", "tester@192.0.2.180", "b@host"]]),
      (eq.desktop_yielding(), asked))
# A launcher host that is the desktop's old LAN lease also tries the others, and a switch is logged once.
import desktop_hosts
real_ranked, logged = desktop_hosts.ranked, []
real_log, eq._YIELD_VIA[0] = eq.log, None
eq.log = logged.append
desktop_hosts.ranked = lambda port=22, fresh=False, tailnet_first=False: ["192.0.2.180", "100.64.0.15", "192.0.2.198"]
os.environ["CT_YIELD_HOSTS"] = "tester@192.0.2.198"
check("yield host at a desktop address: the ranked addresses, the answering one first",
      ["tester@192.0.2.180", "tester@100.64.0.15", "tester@192.0.2.198"], eq.yield_hosts())
eq.yield_hosts()
check("the first probe logs nothing and a repeat none", [], logged)
desktop_hosts.ranked = lambda port=22, fresh=False, tailnet_first=False: ["100.64.0.15", "192.0.2.180", "192.0.2.198"]
eq.yield_hosts(); eq.yield_hosts()
check("a switch of the first address is logged once", 1, len(logged))
desktop_hosts.ranked, eq.log = real_ranked, real_log
os.environ["CT_YIELD_HOSTS"] = "tester@192.0.2.198 b@host"
os.environ["OCR_REMOTE"] = "d@one,b@host"
asked.clear()
eq.desktop_yielding()
check("OCR_REMOTE's hosts come first, CT_YIELD_HOSTS adds the rest once, the desktop at every address",
      [["d@one", "b@host", "tester@100.64.0.15", "tester@192.0.2.198", "tester@192.0.2.180"]], asked)
desktop_busy.busy = lambda hosts: None
os.environ.pop("OCR_REMOTE")
check("an idle CT_YIELD_HOSTS host does not yield", None, eq.desktop_yielding())
desktop_busy.busy, eq.desktop_gate_reader = real_dbusy, real_gate
for k, v in yield_env.items():
    os.environ.pop(k, None)
    if v is not None:
        os.environ[k] = v

lock_path = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-path", "code.lock"],
                           capture_output=True, text=True, check=True).stdout.strip()
with open(lock_path, "a") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    waiting = subprocess.Popen([sys.executable, "edition_queue.py", "-h"], stdout=subprocess.DEVNULL)
    time.sleep(3)
    blocked = waiting.poll() is None
    fcntl.flock(lk, fcntl.LOCK_UN)
check("a start waits while the tree moves, then runs", (True, 0), (blocked, waiting.wait(timeout=120)))

# ---- hot reload (tools/hot_reload.py): which pushes trigger it, and the drain
import hot_reload as hr
check("a tools/ change is code; puzzles, tests, docs are not",
      ["tools/edition_queue.py", "tools/ocr_full_pass.sh"],
      hr.code_changed(["puzzles/times/1.json", "tools/edition_queue.py", "tools/test_edition_queue.py", "README.md",
                       "tools/NOTES.md", "tools/ocr_full_pass.sh", "puzzles/index.json"]))
check("tools/ data (tools/data/**, tools/*.json) is not code", ["tools/x.js"],
      hr.code_changed(["tools/data/shape_reannotate.json", "tools/annotation_backlog.json", "tools/data/a.py", "tools/x.js"]))
check("a puzzle-only push is not code", [], hr.code_changed(["puzzles/times/1.json", "puzzles/everyman/2.json", ""]))
check("CT_AUTO_RELOAD=0 (or off) opts out; unset is on", (True, False, False, True),
      (hr.enabled({}), hr.enabled({"CT_AUTO_RELOAD": "0"}), hr.enabled({"CT_AUTO_RELOAD": "off"}), hr.enabled({"CT_AUTO_RELOAD": "1"})))
def sh(*argv, cwd):
    subprocess.run(argv, cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
def push_file(work, rel, text, msg):
    (work / rel).parent.mkdir(parents=True, exist_ok=True)
    (work / rel).write_text(text)
    sh("git", "add", "-A", cwd=work)
    sh("git", "commit", "-qm", msg, cwd=work)
    sh("git", "push", "-q", "origin", "HEAD:master", cwd=work)
origin_repo, seed, mine = (Path(_tmp) / n for n in ("origin.git", "seed", "mine"))
sh("git", "init", "-q", "--bare", "-b", "master", str(origin_repo), cwd=_tmp)
sh("git", "clone", "-q", str(origin_repo), str(seed), cwd=_tmp)
push_file(seed, "tools/a.py", "1\n", "seed")
sh("git", "clone", "-q", str(origin_repo), str(mine), cwd=_tmp)
watch = hr.Watcher(mine)
check("nothing pushed: no change", [], watch.check())
push_file(seed, "puzzles/times/9.json", "{}\n", "Update times-9")
check("a puzzle-only push on origin/master does not trigger a reload", ([], None), (watch.check(), watch.hit))
push_file(seed, "tools/test_a.py", "t\n", "a test")
check("nor does a test-only push", ([], None), (watch.check(), watch.hit))
push_file(seed, "tools/a.py", "2\n", "fix a tool")
check("a push changing tools/ code does", (["tools/a.py"], ["tools/a.py"]), (watch.check(), watch.hit))
sh("git", "merge", "-q", "--ff-only", "origin/master", cwd=mine)
check("a watcher started on the moved tree sees nothing new", [], hr.Watcher(mine).check())
check("a watcher with no git repo gives up quietly", None, hr.Watcher(Path(_tmp) / "seed" / "nope").check())

# Only a change inside the queue's code closure reloads it.
tree = Path(_tmp) / "closure"
for name, text in {"q.py": "import helper\nimport json\nsubprocess.run(['python3', 'tools/child.py'])\nNOTE = 'see tools/mention.py'\n\ndef lazy():\n    import lazy_only\n",
                   "helper.py": "import deep\n", "deep.py": "X = 1\n", "child.py": "import childdep\n", "childdep.py": "Y = 1\n",
                   "lazy_only.py": "Z = 1\n", "mention.py": "W = 1\n", "unrelated.py": "import deep\n", "wrap.sh": "python3 tools/q.py\n. tools/part.sh\n",
                   "part.sh": "echo hi\n", "page.js": "1\n", "test_q.py": "import q\n"}.items():
    (tree / name).parent.mkdir(parents=True, exist_ok=True)
    (tree / name).write_text(text)
cl = hr.queue_code(tree, "q.py")
check("the closure is the root, its module-level imports (transitively), scripts named in calls, its wrapper and the wrapper's helpers",
      {"q.py", "helper.py", "deep.py", "child.py", "childdep.py", "wrap.sh", "part.sh"}, {p[6:] for p in cl})
check("a lazy import, a script only mentioned, tests, pages and other scripts are outside it",
      ([], 4), (lambda r: (r[0], len(r[1])))(hr.relevant(["tools/lazy_only.py", "tools/mention.py", "tools/page.js", "tools/unrelated.py"], cl)))
check("the real queue's closure holds the units' scripts and not the site builders or fetchers it never starts",
      (True, True, True, True, False, False, False, False),
      tuple(("tools/" + n in hr.queue_code(eq.TOOLS)) for n in ("scan_queue.py", "vlm_reader.py", "file_archive_org_puzzles.py", "ocr_full_pass.sh",
                                                                 "build_seo_pages.py", "fetch_globeandmail.py", "ci_cache.js", "shape_queue.py")))
push_file(seed, "tools/b.py", "1\n", "unrelated tool")
irrelevant = hr.Watcher(mine, closure={"tools/a.py"})
import contextlib, io
out = io.StringIO()
with contextlib.redirect_stdout(out):
    got = (irrelevant.check(), irrelevant.hit)
check("a push of code outside the closure does not trigger a reload and says so once",
      (([], None), 1, True), (got, out.getvalue().count("ignoring 1 changed files outside the queue's code"), "tools/b.py" in out.getvalue()))
with contextlib.redirect_stdout(out):
    irrelevant.check()
check("the same ignored change is not logged again at the next poll", 1, out.getvalue().count("ignoring"))
push_file(seed, "tools/a.py", "3\n", "fix a tool in the closure")
check("a push touching the closure reloads, and names only the files in it", (["tools/a.py"], ["tools/a.py"]),
      (lambda w: (w.check(), w.hit))(hr.Watcher(mine, closure={"tools/a.py"})))

def reload_run(sig_after=1.5, grace=None, handoff=None, watcher=None, hold=30):
    """Fork a dispatch of long units, send SIGHUP (or let `watcher` fire); (rc, seconds to end, handoff pids, pids of the units)."""
    log.unlink(missing_ok=True)
    fake(sleep={f"h{k}": hold for k in range(3)})
    eq.plan = units([], [(f"h{k}", []) for k in range(3)])
    if grace is not None:
        os.environ["CT_RELOAD_GRACE"] = str(grace)
    if watcher:
        os.environ["CT_AUTO_RELOAD"] = "1"
    # Forking while another thread holds a lock (stdout, logging, import) leaves the child
    # deadlocked on it forever, so let earlier tests' threads finish before forking.
    quiet = time.monotonic() + 20
    while threading.active_count() > 1 and time.monotonic() < quiet:
        time.sleep(0.05)
    started = time.monotonic()
    child = os.fork()
    if child == 0:
        sys.stderr = open(os.devnull, "w")
        sys.stdout = open(os.devnull, "w")
        if watcher:
            hr.Watcher = watcher
        os._exit(eq.dispatch(["times"], cache, workers=3, replan=0.1, handoff=handoff))
    os.environ["CT_AUTO_RELOAD"] = "0"
    os.environ.pop("CT_RELOAD_GRACE", None)
    # Wait for the first unit to actually start (a loaded box may take many seconds), not a fixed sleep.
    until = time.monotonic() + 90
    while time.monotonic() < until and not (log.exists() and " start " in log.read_text()):
        time.sleep(0.05)
    started = time.monotonic()  # the bounds below are measured from the first unit running
    time.sleep(sig_after)
    if not watcher:
        os.kill(child, signal.SIGHUP)
    rc = None
    until = time.monotonic() + 120
    while time.monotonic() < until:
        done, status = os.waitpid(child, os.WNOHANG)
        if done:
            rc = os.waitstatus_to_exitcode(status)
            break
        time.sleep(0.05)
    if rc is None:  # hung: kill it so the run fails with a FAIL line instead of hanging CI
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)
        rc = "hung"
    took = time.monotonic() - started
    pids = []
    if handoff and Path(handoff).exists():
        pids = [r["pid"] for r in json.loads(Path(handoff).read_text())]
    return rc, took, pids

os.environ["CT_AUTO_RELOAD"] = "0"
ho = Path(_tmp) / "reload-handoff.json"
rc, took, pids = reload_run(handoff=ho)
alive_after = [p for p in pids if eq.alive(p)]
for p in pids:
    try:
        os.killpg(p, signal.SIGKILL)
    except ProcessLookupError:
        pass
starts = [line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start"]
check("SIGHUP with a handoff: exits 75 at once, every unit running (the ceiling lets some start) is handed over alive",
      (hr.RELOAD_RC, True, True), (rc, took < 10, len(pids) == len(alive_after) == len(starts) >= 1))
rc, took, _ = reload_run(grace=1)
ev = [line.split() for line in log.read_text().splitlines()]
check("SIGHUP without a handoff: CT_RELOAD_GRACE passes, the units are TERMed (left deferred), exit 75, not 30s later",
      (hr.RELOAD_RC, True, 0), (rc, 2.5 < took < 20, sum(1 for e in ev if e[1] == "end")))
rc, took, _ = reload_run(grace=60, hold=6, sig_after=4)
ev = [line.split() for line in log.read_text().splitlines()]
check("units that end inside the grace are waited for, not stopped; exit 75 after them",
      (hr.RELOAD_RC, True, True), (rc, sum(1 for e in ev if e[1] == "end") == sum(1 for e in ev if e[1] == "start") >= 1, 5 < took < 40))
class FiresSoon:  # the watcher saw tools/ code change on origin/master
    def __init__(self, *a, **k):
        self.hit = None
        def fire():  # once a unit is really running, so there is something to hand over
            end = time.monotonic() + 90
            while time.monotonic() < end and not (log.exists() and " start " in log.read_text()):
                time.sleep(0.05)
            time.sleep(0.5)
            self.hit = ["tools/edition_queue.py"]
        threading.Thread(target=fire, daemon=True).start()
    def start(self, *a, **k):
        return self
rc, took, pids = reload_run(handoff=Path(_tmp) / "auto-handoff.json", watcher=FiresSoon)
for p in pids:
    try:
        os.killpg(p, signal.SIGKILL)
    except ProcessLookupError:
        pass
check("the watcher seeing code change reloads the queue with no signal: exit 75, units handed over",
      (hr.RELOAD_RC, True, True), (rc, took < 10, len(pids) >= 1))
os.environ["CT_AUTO_RELOAD"] = "0"

# Scans keep to a third of the unit ceiling (at least 1) while reads are due; the whole pool otherwise.
check("scan share: ceiling 10 with reads due holds scans to 3", 3, eq.scan_share(10, True))
check("scan share: a tiny ceiling still leaves one scan", 1, eq.scan_share(2, True))
check("scan share: no read due leaves the scan pool whole", None, eq.scan_share(10, False))

# Answers-linked rereads of one item go in one process (ANSWERS_BATCH), each edition keeping its own line.
def _al_unit(rel, reason="inputs changed", rank=3, detail="answers linked x1"):
    return {"kind": "read", "paper": "gale", "rel": rel, "rank": rank, "reason": reason, "detail": detail, "needs": []}
_al = [_al_unit(f"GaleTimes2001UKEnglish/2001-04-{d:02d}") for d in range(1, 13)]
_al += [_al_unit("GaleTimes2002UKEnglish/2002-01-01"), _al_unit("GaleTimes2001UKEnglish/2001-05-01", "never read", 1, ""),
        _al_unit("GaleTimes2001UKEnglish/2001-05-02", rank=4),
        _al_unit("GaleTimes2001UKEnglish/2001-05-03", detail="answers linked x1, answers in the next issue's text x1")]
_al_c = [(u, eq.key_of(u)) for u in _al]
_mates = eq.batch_mates(_al[0], _al_c, {eq.key_of(_al[1])}, {eq.key_of(_al[2])}, lambda v: v["rel"] != _al[3]["rel"])
check("batch: up to ANSWERS_BATCH - 1 same-item, same-rank answers-linked reads, none tried, running or waiting",
      [f"GaleTimes2001UKEnglish/2001-04-{d:02d}" for d in (5, 6, 7, 8, 9, 10, 11)], [v["rel"] for v in _mates])
check("batch: a unit of another reason batches nothing", [], eq.batch_mates(_al[13], _al_c, set(), set(), lambda v: True))
check("batch: a batch of one is no batch", [], eq.batch_mates(_al[0], _al_c, set(), set(), lambda v: True, size=1))
check("batch: the read limit grows per edition, within 3600", (1200, 2040, 3600, 3600),
      (eq.unit_limit(_al[0], 1200), eq.unit_limit({**_al[0], "batch": ["a"] * 7}, 1200),
       eq.unit_limit({**_al[0], "batch": ["a"] * 7}, 3600), eq.unit_limit({**_al[0], "batch": ["a"] * 30}, 1200)))

print("FAILS", fails)

print("test_edition_queue: all passed" if not fails else "test_edition_queue: FAILED")
sys.exit(1 if fails else 0)
