#!/bin/bash
# Does the per-edition queue (tools/edition_queue.py) keep each edition's
# read a unit of its own: rows appended, the last standing, never a whole
# rewrite under another unit; one unit per edition; the most urgent first
# (Gale pages saved by hand, then never read, then the re-reads); a read
# only after the scans its solution needs; a slow unit killed at its own
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

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

T = Path(os.environ["TMP"])
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
check("times: a stale scan and a never-scanned edition are scan units", ["1980-01-02_2", "1980-03-01_3"],
      [u["rel"].split("/")[1] for u in scans])
check("times: each read and why", [("1980-03-01_3", "never read", 1), ("1980-01-01_1", "--reread", 3),
                                   ("1980-01-02_2", "scan stale", 2)],
      [(u["rel"].split("/")[1], u["reason"], u["rank"]) for u in reads])
check("a read needs its own stale scan and those SOLUTION_DAYS after it, no other",
      {"1980-01-01_1": ["1980-01-02_2"], "1980-01-02_2": ["1980-01-02_2"], "1980-03-01_3": ["1980-03-01_3"]},
      {u["rel"].split("/")[1]: [r.split("/")[1] for r in u["needs"]] for u in reads})
check("a scan takes the rank of the most urgent read needing it", [2, 1], [u["rank"] for u in scans])
_, reads = f.plan(f.TIMES, cache, asked={"NewsUK1980UKEnglish/1980-01-01_1"})
check("annotation's ask makes a read due, forced", [("1980-01-01_1", "annotation asked", True)],
      [(u["rel"].split("/")[1], u["reason"], u["force"]) for u in reads if u["rel"].endswith("_1")])
gs, gr = f.plan(f.GALE, cache)
check("Gale pages saved by hand: rank 0, the latest laid out first", [("1987-03-03", 0), ("1987-03-02", 0)],
      [(u["rel"].split("/")[1], u["rank"]) for u in gr])
check("the Gale plan keeps to its own ledger", False, (cache / "filed-gale.jsonl").exists())

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

# ---- a scan made under the old whole-name key is re-keyed, not rescanned
rk = T / "rekey.jsonl"
q.append(rk, [{"edition": "a", "scanKey": f.whole_name_scan_key()}, {"edition": "b", "scanKey": "older"}])
check("rows under the old key take the narrowed one; others stay stale; once", (1, [f.scan_key(), "older"], 0),
      (f.rekey_scans(rk), [r["scanKey"] for r in q.jsonl_rows(rk)], f.rekey_scans(rk)))

# ---- the dispatcher: order, gating, limits, --seconds, TERM
log = T / "units.log"
def fake_unit(unit, cache, puzzles, reread):
    with open(log, "a") as fh:
        fh.write(f"{time.monotonic():.3f} start {unit['kind']} {unit['rel']}\n")
    time.sleep({"slow": 30}.get(unit["rel"], 0.2))
    with open(log, "a") as fh:
        fh.write(f"{time.monotonic():.3f} end {unit['kind']} {unit['rel']}\n")
    return "read"
eq.run_unit = fake_unit
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
check("a read starts only after the scan it needs ends", True, ev.index(["end", "scan", "s1"]) < ev.index(["start", "read", "r1"]))
check("a unit past its limit is killed, the others not held up", (False, True, True),
      (["end", "read", "slow"] in ev, ["end", "read", "r2"] in ev, time.monotonic() - t0 < 15))
log.unlink()
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
def fake_any(unit, cache, puzzles, reread):
    with open(log, "a") as fh:
        fh.write(f"{time.monotonic():.3f} start {unit['kind']} {unit['rel']}\n")
    time.sleep(0.3)
    return outcome.get(unit["rel"], "read" if unit["kind"] == "read" else "fetched")
eq.run_unit = fake_any
eq.plan = units([], [("r1", [])])
eq.FETCHERS = {"src": {"plan": lambda: [{"rel": f"e{k}", "reason": "not fetched"} for k in range(6)],
                       "run": None, "workers": 3, "seconds": 5}}
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    rc = eq.dispatch(["times"], cache, workers=1, fetch=["src"], replan=0.2)
ev = [line.split()[1:] for line in log.read_text().splitlines()]
check("fetch units run beside the reads, each once, in their own pool", (0, ["r1"], [f"e{k}" for k in range(6)]),
      (rc, [e[2] for e in ev if e[1] == "read"], sorted(e[2] for e in ev if e[1] == "fetch")))
log.unlink()
outcome = {"e0": "throttled", **{f"e{k}": "outage" for k in range(1, 4)}}
eq.FETCH_OUTAGES = 3
eq.FETCHERS["src"]["workers"] = 2
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=1, fetch=["src"], replan=0.2)
check("a 429 lowers the pool; FETCH_OUTAGES down in a row stop the source for the run", (True, True, False),
      ("at most 1 fetches at once" in err.getvalue(), "no more fetches this run" in err.getvalue(),
       "start fetch e5" in log.read_text()))

# ---- --handoff: a slice's end hands its running units to the next run,
# which counts them in its pools and does not start them again.
log.unlink()
def timed_unit(unit, cache, puzzles, reread):
    with open(log, "a") as fh:
        fh.write(f"{time.monotonic():.3f} start {unit['kind']} {unit['rel']}\n")
    time.sleep({"long": 4}.get(unit["rel"], 0.2))
    with open(log, "a") as fh:
        fh.write(f"{time.monotonic():.3f} end {unit['kind']} {unit['rel']}\n")
    return "read"
eq.run_unit = timed_unit
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
      (rc, sum(e == ["start", "read", "long"] for e in ev),
       ev.index(["end", "read", "long"]) < ev.index(["start", "read", "r1"]),
       "ended (taken over)" in err.getvalue(), ho.exists()))

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
      tuple(mg.room(n, lambda: mg.FLOOR + int(2.5 * mg.UNIT)) for n in (0, 1, 2)))
check("room: an unreadable figure gates nothing", True, mg.room(0, lambda: None))
check("available() reads this host", True, (mg.available() or 1) > 0)
check("cpu_room: under the load ceiling starts", True, mg.cpu_room(0, lambda: 3.0, cores=4))
check("cpu_room: at the ceiling does not", False, mg.cpu_room(0, lambda: 6.0 * 4, cores=4))
check("cpu_room: units begun this pass count against it", (True, False),
      tuple(mg.cpu_room(n, lambda: 6.0 * 4 - 0.5, cores=4) for n in (0, 1)))
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
eq.mem_gate_reader = None
log.unlink(missing_ok=True)
eq.plan = units([], [(f"m{k}", []) for k in range(3)])
eq.mem_gate_reader = lambda: 1 * G
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    eq.dispatch(["times"], cache, workers=3, scan_workers=1, seconds=2.2, replan=0.5)
check("short of memory nothing starts, and it says so once", (False, 1),
      (log.exists(), err.getvalue().count("memory-bound")))
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

print("FAILS", fails)
sys.exit(1 if fails else 0)
EOF
rc=$?
[ "$rc" -eq 0 ] && echo "test_edition_queue: all passed" || echo "test_edition_queue: FAILED"
exit "$rc"
