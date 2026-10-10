#!/bin/bash
# Does the per-edition queue (tools/edition_queue.py) keep each edition's
# read a unit of its own: rows appended, the last standing, never a whole
# rewrite under another unit; one unit per edition; the most urgent first
# (Gale pages saved by hand, then never read, then the re-reads); a read
# only after the scans its solution needs, and a scan held while a read
# pool of reads is ready; a slow unit killed at its own
# limit without holding up the rest; a capped run saying what it left; and
# a TERM passed on to the units?
#
#     bash tools/test_edition_queue.sh
#
# Temp dirs only; no OCR, no VLM, no network.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cd "$REPO/tools" && TMP="$tmp" python3 - <<'EOF'
import contextlib, io, json, os, signal, sys, time
from pathlib import Path
import scan_queue as q
import vlm_reader
vlm_reader.reachable = lambda *a, **k: False
import file_archive_org_puzzles as f
import edition_queue as eq
eq.cpu_gate_reader = lambda: 0.0  # this host's load must not gate the tests' starts
eq.desktop_gate_reader = lambda: None  # nor whether Paul's desktop is busy
os.environ["CT_BURN_STATE"] = os.path.join(os.environ["TMP"], "no-burn")  # nor this host's burn

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

T = Path(os.environ["TMP"])
eq.DIR_CACHE, eq.HELD_CACHE, eq.LIKELY_CACHE = T / "dir_cache.pickle", T / "held_files.pickle", T / "likely.pickle"  # never this host's caches
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
f.inputs_of = lambda fh, found, series: fh
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
check("Gale pages saved by hand: rank 0, the latest laid out first", [("1987-03-03", 0), ("1987-03-02", 0)],
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
    lrow("1980-02-05_2", [90101], [v(90101)], sols=[90100]),  # answerless; 02-06's text prints its heading
    lrow("1980-02-06_3", [90102], [v(90102, **part(5))]),  # the next issue of 90101: its text links it
    lrow("1980-02-12_9", [90104], [v(90104)]),  # answerless, its next issue's text links nothing
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
      ["1980-02-06_3", "1980-02-04_1", "1980-01-21_0", "1980-02-13_10", "1980-01-22_0"],
      [g[0] for g in got if g[2] == 2])
check("the next issue of an answerless puzzle its text links is predicted; one its text does not link is not",
      ({"answers in the next issue's text": 1}, None),
      tuple(next(g[3] for g in got if g[0] == n) for n in ("1980-02-06_3", "1980-02-13_10")))
check("a grid read before read_framed two lights short is predicted, five short not",
      ({"solution grid read before read_framed": 1}, None),
      tuple(next(g[3] for g in got if g[0] == n) for n in ("1980-01-21_0", "1980-01-22_0")))
check("only the editions due as an answerless puzzle's next issue have their text read",
      ["1980-02-06_3", "1980-02-13_10"], sorted(text_read))
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
mend = {"readAt": "2026-10-09T00:00:00+00:00"}
check("blanks a vote fix landed for since the read, answers whole: predicted",
      "blanks a vote fix mends", f.short_cause("times", mend, v(90200, blank={"1-a": "'qx': not a word"}, **part(0)), {}))
check("mirror: a blank no vote fix mends holds it", None,
      f.short_cause("times", mend, v(90200, blank={"1-a": "junk"}, **part(0)), {}))
check("mirror: read after the fix, the same blank holds it", None,
      f.short_cause("times", {"readAt": "2026-10-11T00:00:00+00:00"}, v(90200, blank={"1-a": "'qx': not a word"},
                                                                        **part(0)), {}))
f.edition_dirs, f.input_hash, f.linked_solutions, f.text_headings = real[:4]
f._HELD_PATH.clear()
f._HELD_PATH.update(real[4])

# ---- the queue's order across papers, and --newer-than
os.utime(g2 / "pages.json", (time.time(), time.time()))
scans, reads = eq.plan(["gale", "times"], cache, before)
check("rank 0 first (Gale by hand), then never read, then the rest",
      ["1987-03-03", "1987-03-02", "1980-03-01_3", "1980-01-02_2", "1980-01-01_1"],
      [u["rel"].split("/")[1] for u in reads])
scans, reads = eq.plan(["gale", "times"], cache, before, newer=time.time() - 60)
check("--newer-than: only what was laid out since, and the scans it needs", (["1987-03-03"], ["1987-03-03"]),
      ([u["rel"].split("/")[1] for u in reads], [u["rel"].split("/")[1] for u in scans]))
with q.lock(cache / "filed-gale.jsonl"):
    notes = []
    scans, reads = eq.plan(["gale", "times"], cache, before, out=notes)
    check("a paper whose ledger a batch run holds is left out, and said", (False, True),
          (any(u["paper"] == "gale" for u in reads), "gale: a run holds" in notes[0]))

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
os.environ.update(OCR_REMOTE="micro@100.68.145.15", OCR_REMOTE_DEFER="1")
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
if b.get("ends", True) and not b.get("ps"):
    say(f"{{time.monotonic():.3f}} end {{unit['kind']}} {{unit['rel']}}")
outcome = b.get("outcome", {{}}).get(unit["rel"], "read" if unit["kind"] == "read" else "fetched")
sys.exit({eq.EXITS!r}.get(outcome, 1))
""")
def fake(**kw):
    behaviour.write_text(json.dumps(kw))
fake(sleep={"slow": 30})
def units(scans, reads):
    return lambda papers, cache=None, reread=None, newer=None, out=None: (
        [{"kind": "scan", "paper": "times", "rel": r, "rank": 1, "reason": "scan stale"} for r in scans],
        [{"kind": "read", "paper": "times", "rel": r, "rank": 1, "reason": "never read", "needs": n} for r, n in reads])
eq.plan = units(["s1"], [("r1", ["s1"]), ("slow", []), ("r2", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    t0 = time.monotonic()
    rc = eq.dispatch(["times"], cache, workers=2, scan_workers=1, read_seconds=2, replan=0.5)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
starts = [e[2] for e in ev if e[0] == "start"]
check("the dispatcher ends 0, every unit started once", (0, ["r1", "r2", "s1", "slow"]), (rc, sorted(starts)))
check("a read starts only after the scan it needs ends", True, ev.index(["end", "scan", "s1"]) < ev.index(["start", "read", "r1", "v1"]))
check("a unit past its limit is killed, the others not held up", (False, True, True),
      (["end", "read", "slow"] in ev, ["end", "read", "r2"] in ev, time.monotonic() - t0 < 15))
log.unlink()
fake(sleep={"n1": 1.0})
eq.plan = lambda papers, cache=None, reread=None, newer=None, out=None: (
    [{"kind": "scan", "paper": "times", "rel": "b1", "rank": 3, "reason": "scan stale"}],
    [{"kind": "read", "paper": "times", "rel": r, "rank": 1, "reason": "never read", "needs": []} for r in ("n1", "n2")])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a whole-corpus unit waits, in its own idle pool, until no new one is left to start", True,
      ev.index(["start", "read", "n2", "v1"]) < ev.index(["start", "scan", "b1", "v1"]))
log.unlink()
fake(sleep={"r1": 0.6, "r2": 0.6})
eq.plan = units(["s9"], [("r1", []), ("r2", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a scan no read waits on holds while a full read pool of reads is ready", True,
      ev.index(["start", "read", "r2", "v1"]) < ev.index(["start", "scan", "s9", "v1"]))
log.unlink()
eq.plan = units(["s9"], [("r1", []), ("r2", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("with fewer ready reads than read slots the scans start at once", True,
      ev.index(["start", "scan", "s9", "v1"]) < ev.index(["end", "read", "r1"]))
log.unlink()
fake(sleep={"s0": 1.5})
eq.plan = units(["s0", "s1"], [("r1", ["s1"])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a read whose days-after scan waits behind a full scan pool starts at once", True,
      ev.index(["start", "read", "r1", "v1"]) < ev.index(["end", "scan", "s0"]))
log.unlink()
fake(sleep={"s0": 1.5}, outcome={"bad": "failed"})
eq.plan = units(["s0", "r1", "bad"], [("r1", ["r1"]), ("bad", ["bad"])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a read whose own scan waits behind a full scan pool starts only after that scan ends done", True,
      ev.index(["end", "scan", "r1"]) < ev.index(["start", "read", "r1", "v1"]))
check("a read whose own scan failed is left for the next run, not read unscanned", False,
      ["start", "read", "bad", "v1"] in ev)
log.unlink()
fake()
hashes, f.input_hash = f.input_hash, lambda d: "h"
q.append(cache / "filed.jsonl", [{"edition": "done", "filesHash": "h", "scanKey": f.scan_key(), "scan": scan}])
eq.plan = units(["done", "s1"], [("done", ["done"])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a planned scan whose edition was scanned since (a kept plan) is not started; its read goes on, the others' scans run",
      (False, True, True), (["start", "scan", "done", "v1"] in ev, ["start", "read", "done", "v1"] in ev,
                            ["start", "scan", "s1", "v1"] in ev))
f.input_hash = hashes
log.unlink()
fake()
calls = []
def slow_replan(papers, cache=None, reread=None, newer=None, out=None):
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
log.unlink()
kept_ho = Path(os.environ["TMP"]) / "kept-handoff.json"
eq.plan = units([], [("k1", []), ("k2", [])])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, replan=0.1, handoff=kept_ho)
log.unlink()
def stalled(papers, cache=None, reread=None, newer=None, out=None):
    time.sleep(3)
    return [], []
eq.plan = stalled
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    t0 = time.monotonic()
    eq.dispatch(["times"], cache, workers=2, replan=0.1, handoff=kept_ho)
starts = [(float(line.split()[0]), line.split()[3]) for line in log.read_text().splitlines() if line.split()[1] == "start"]
check("the next run starts the kept plan's units before its own plan is made", (["k1", "k2"], True),
      (sorted(r for _, r in starts), all(t - t0 < 2 for t, _ in starts)))
log.unlink()
# A slice boundary: the next slice fills its free slots with what the last
# one had not started, at once, its ledger upkeep on the planner thread.
fake(sleep={"k2": 4, "k3": 4})
kept_ho = Path(os.environ["TMP"]) / "kept-handoff2.json"
eq.plan = units([], [(f"k{k}", []) for k in range(1, 6)])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=2, replan=60, seconds=2, handoff=kept_ho)
ran = {line.split()[3] for line in log.read_text().splitlines() if line.split()[1] == "start"}
log.unlink()
eq.plan = stalled
upkept = []
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    t0 = time.monotonic()
    eq.dispatch(["times"], cache, workers=4, replan=0.1, handoff=kept_ho,
                upkeep=lambda: (time.sleep(3), upkept.append(time.monotonic() - t0)))
starts = [(float(line.split()[0]), line.split()[3]) for line in log.read_text().splitlines() if line.split()[1] == "start"]
check("the next slice starts at once what the last left unstarted, not what it ran; upkeep beside it",
      (sorted({"k1", "k2", "k3", "k4", "k5"} - ran), True, 1, True),
      (sorted(r for _, r in starts), all(t - t0 < 2 for t, _ in starts), len(upkept), "k1" in ran))
log.unlink()
fake(sleep={"slow": 30})
eq.plan = units([], [(f"r{k}", []) for k in range(6)])
out = io.StringIO()
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=0.5, replan=60)
check("--seconds starts nothing after it and says what it left", (True, True),
      (len(log.read_text().splitlines()) <= 4, "left for the next run" in out.getvalue()))
log.unlink()
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
      (rc, time.monotonic() - t0 < 5, "end read slow" in log.read_text()))
log.unlink()
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
log.unlink()
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
log.unlink()
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
log.unlink()
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
log.unlink()
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

# ---- fresh code: a unit started after a code change runs the new code.
# The first unit changes the unit script as it runs (master moved under
# the tree); every unit started after it runs the changed script.
log.unlink()
fake(rewrite_on="c0", change=['VERSION = "v1"', 'VERSION = "v2"'], sleep={"c0": 0.5})
eq.plan = units([], [(f"c{k}", []) for k in range(4)])
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, replan=0.2)
ran = [e.split()[3:] for e in log.read_text().splitlines() if " start " in e]
check("a unit started after a code change runs the new code, none the old",
      [["c0", "v1"], ["c1", "v2"], ["c2", "v2"], ["c3", "v2"]], ran)

# ---- the queue itself follows its code: a change to it hands its running
# units to its new image (same pid, a child still) and re-execs.
log.unlink()
driver = T / "driver.py"
driver.write_text(f"""import os, sys
sys.path.insert(0, {str(Path.cwd())!r})
import edition_queue as eq
VERSION = "p1"
print(f"parent {{VERSION}} {{os.getpid()}}", file=sys.stderr, flush=True)
eq.cpu_gate_reader = lambda: 0.0
eq.mem_gate_reader = lambda: 1 << 40
eq.UNIT_SCRIPT = {str(eq.UNIT_SCRIPT)!r}
eq.plan = lambda papers, cache=None, reread=None, newer=None, out=None: (
    [], [{{"kind": "read", "paper": "times", "rel": r, "rank": 1, "reason": "never read", "needs": []}}
         for r in ("long", "r1", "r2")])
resume = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else None
sys.exit(eq.dispatch(["times"], {str(cache)!r}, workers=1, replan=0.3, resume=resume))
""")
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(driver), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
import subprocess
p = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True, timeout=60)
parents = [l.split()[1:] for l in p.stderr.splitlines() if l.startswith("parent ")]
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("a code change re-execs the queue once, same pid, new code", (0, ["p1", "p2"], True, True),
      (p.returncode, [v for v, _ in parents], len({pid for _, pid in parents}) == 1, "re-exec" in p.stderr))
check("its running unit is kept, not started again, reaped by the new image, then the rest start",
      (1, True, True, ["long", "r1", "r2"]),
      (sum(e[:3] == ["start", "read", "long"] for e in ev), "end read long: done" in p.stderr,
       ev.index(["end", "read", "long"]) < ev.index(["start", "read", "r1", "v1"]),
       [e[2] for e in ev if e[0] == "start"]))
# Mirror: a plan that takes minutes (a cold cache on the media mount) holds
# no re-exec back; the old code would run until the plan ended.
log.unlink()
slow = T / "slow_driver.py"
slow.write_text(driver.read_text().replace('VERSION = "p2"', 'VERSION = "p1"').replace("eq.plan = lambda papers", """import time
calls = []
def plan(*a, **k):
    calls.append(1)
    if len(calls) > 1 and VERSION == "p1":
        time.sleep(60)
    return quick(*a, **k)
eq.plan = plan
quick = lambda papers""").replace("replan=0.3, resume=resume", "replan=0.3, resume=resume, seconds=20"))
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(slow), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
slowed = subprocess.run([sys.executable, str(slow)], capture_output=True, text=True, timeout=60)
check("a code change re-execs the queue while its plan is still being made",
      ["p1", "p2"], [l.split()[1] for l in slowed.stderr.splitlines() if l.startswith("parent ")])
# Mirror: an image that has not yet made a plan of its own (it runs the kept
# one) makes it before re-exec'ing on the next change, so changes landing
# faster than a plan takes still get plans made on new code.
log.unlink()
busy = T / "busy_driver.py"
busy.write_text(driver.read_text().replace('VERSION = "p2"', 'VERSION = "p1"').replace("eq.plan = lambda papers", """import time
def plan(*a, **k):
    if VERSION == "p2":
        src = open(__file__).read()
        open(__file__, "w").write(src.replace('VERSION = "p2"', 'VERSION = "p3"'))
        time.sleep(1.5)
        print("plan made by p2", file=sys.stderr, flush=True)
    return quick(*a, **k)
eq.plan = plan
quick = lambda papers""").replace("replan=0.3, resume=resume", "replan=0.3, resume=resume, seconds=20"))
eq.UNIT_SCRIPT.write_text(eq.UNIT_SCRIPT.read_text().replace('VERSION = "v2"', 'VERSION = "v1"'))
fake(rewrite_on="long", rewrite=str(busy), change=['VERSION = "p1"', 'VERSION = "p2"'], sleep={"long": 3})
busied = subprocess.run([sys.executable, str(busy)], capture_output=True, text=True, timeout=60)
said = [l.split()[1] if l.startswith("parent ") else l for l in busied.stderr.splitlines()
        if l.startswith("parent ") or l == "plan made by p2"]
check("an image re-execs on a change only after making its own first plan",
      ["p1", "p2", "plan made by p2", "p3"], said)

# ---- --handoff: a slice's end hands its running units to the next run,
# which counts them in its pools and does not start them again.
log.unlink()
fake(sleep={"long": 4})
eq.plan = units([], [("long", []), ("r1", [])])
ho = T / "handoff.json"
out = io.StringIO()
t0 = time.monotonic()
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
    rc = eq.dispatch(["times"], cache, workers=1, seconds=0.5, handoff=ho)
check("a slice ends at once, handing over its running unit, and says it left work", (0, True, ["long"], True),
      (rc, time.monotonic() - t0 < 3, [r["unit"]["rel"] for r in json.loads(ho.read_text())],
       "left for the next run" in out.getvalue()))
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
      [("1930-04-02.pdf", 0, "saved by hand"), ("1930-04-09.pdf", 3, "version changed")],
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
os.environ["OCR_REMOTE"] = "micro@100.68.145.15"
check("with a desktop set the load gates fetches, not scans or reads", (True, False, False),
      tuple(eq.load_gated({"kind": k}) for k in ("fetch", "scan", "read")))
os.environ["OCR_REMOTE"] = ""
check("mirror: with no desktop the load gates every unit", (True, True, True),
      tuple(eq.load_gated({"kind": k}) for k in ("fetch", "scan", "read")))
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
# A unit the desktop keeps losing (its read ends the server there) is started
# again with the desktop until it has ended lost LOST_TRIES times, then with none: read here.
eq.LOST_TRIES = 1
os.environ["OCR_REMOTE"] = "micro@192.168.1.198"
real_prepare, eq.prepare = eq.prepare, lambda *a: None  # no desktop probe
fake(outcome={"d0": "lost"}, default=0.05, env=True)
log.unlink(missing_ok=True)
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, scan_workers=1, seconds=4, replan=0.5)
desk = [line.split(" ", 2)[2] for line in log.read_text().splitlines() if line.startswith("desktop ")]
check("a lost unit is started again with the desktop, then after LOST_TRIES with none",
      (["'micro@192.168.1.198'", "''"], True, False),
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
# code_reach keeps its answers per version of tools/: an edit is a new answer.
saved = code_reach.TOOLS, code_reach.STORE
code_reach.TOOLS, code_reach.STORE = T / "reach-tools", T / "reach-store"
code_reach.TOOLS.mkdir()
(code_reach.TOOLS / "ra.py").write_text("import rb\ndef f():\n    return rb.g()\n")
(code_reach.TOOLS / "rb.py").write_text("def g():\n    return 1\n")
first = (code_reach.modules("ra"), code_reach.key("ra", {"f"}))
again = (code_reach.modules("ra"), code_reach.key("ra", {"f"}), len(list(code_reach.STORE.glob("*.json"))))
(code_reach.TOOLS / "rb.py").write_text("def g():\n    return 2\n")
(code_reach.TOOLS / "ra.py").write_text("import rb\ndef f():\n    import rc\n    return rb.g()\n")
(code_reach.TOOLS / "rc.py").write_text("")
edited = (code_reach.modules("ra"), code_reach.key("ra", {"f"}))
check("code_reach answers again from its store, and anew after an edit",
      ({"ra", "rb"}, True, 1, {"ra", "rb", "rc"}, True),
      (first[0], again[:2] == first, again[2], edited[0], edited[1] != first[1]))
code_reach.TOOLS, code_reach.STORE = saved
lock_path = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-path", "code.lock"],
                           capture_output=True, text=True, check=True).stdout.strip()
with open(lock_path, "a") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    waiting = subprocess.Popen([sys.executable, "edition_queue.py", "-h"], stdout=subprocess.DEVNULL)
    time.sleep(3)
    blocked = waiting.poll() is None
    fcntl.flock(lk, fcntl.LOCK_UN)
check("a start waits while the tree moves, then runs", (True, 0), (blocked, waiting.wait(timeout=120)))

print("FAILS", fails)
sys.exit(1 if fails else 0)
EOF
rc=$?
[ "$rc" -eq 0 ] && echo "test_edition_queue: all passed" || echo "test_edition_queue: FAILED"
exit "$rc"
