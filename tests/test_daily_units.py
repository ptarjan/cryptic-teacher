#!/usr/bin/env python3
# Which daily units get the generated files (puzzles/index.*, the shims,
# abbreviations.js) rebuilt as their tree is set up? tools/daily_units.py
# GENERATED says, per unit kind; daily_update.sh asks it before sourcing
# tools/nightly_worktree.sh. A rebuild is a whole-corpus pass, and nearly
# every start finds HEAD moved, so a unit that reads none of them must not
# pay for it, and one that reads them must not start without them.
#
#     python3 tests/test_daily_units.py
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
import _path  # puts tools/ on sys.path
import daily_units as du

fails = []


def check(what, got, want):
    print(("ok   " if got == want else "FAIL ") + what + ("" if got == want else f": want {want!r}, got {got!r}"))
    if got != want:
        fails.append(what)


class Ledger:
    last_end, last_start = {}, {}
    def started_since(self, *a, **k): return 0
    def running(self, key): return False


# Every unit plan() can emit has a kind GENERATED names.
os.environ.update(DAILY_FRESH="p1", DAILY_PENDING="p2", DAILY_UNSOLVED="p1", DAILY_MISSES="p1 3a")
keys = [u.key for u in du.plan(Ledger(), 0)]
check("plan() emits annotate, miss and every phase", {k.split(":")[0] for k in keys} >= {"annotate", "miss", "wayback", "checks", "reports"}, True)
for k in keys:
    check(f"{k} has a kind in GENERATED", k.split(":", 1)[0] in du.GENERATED, True)

# Every live series is fetched: the slow ones on their own cadence, each a
# tools/<tool>.py whose --latest daily_update.sh's unit_fetch runs.
for f in du.SLOW_FETCHERS:
    check(f"fetch:{f} is planned", f"fetch:{f}" in keys, True)
    check(f"tools/{f}.py exists", os.path.exists(f"tools/{f}.py"), True)
    check(f"tools/{f}.py takes --latest", os.path.exists(f"tools/{f}.py") and "--latest" in open(f"tools/{f}.py").read(), True)
# The TLS's newest issue is looked for in CI, beside its backfill, and not here.
check("fetch:tls_puzzles is not planned locally", "fetch:tls_puzzles" in keys, False)
check("tls-backfill.yml runs tls_puzzles --latest",
      "tools/tls_puzzles.py --latest" in (REPO / ".github" / "workflows" / "tls-backfill.yml").read_text(), True)
# The steps .github/workflows/daily-units.yml took over (2026-11-15) run there and
# nowhere in daily_update.sh, so none runs twice.
units_yml = (REPO / ".github" / "workflows" / "daily-units.yml").read_text()
daily_sh = (REPO / "tools" / "daily_update.sh").read_text()
for step in ["fetch_puzzle.py --refresh-unsolved", "fetch_observer.py --refresh-unsolved",
             "fetch_privateeye.py --refresh-unsolved", "fetch_privateeye.py --backfill-dates",
             "fetch_snitch.py", "series_health.py --stale-only"]:
    check(f"{step} runs in daily-units.yml", step.split()[0] in units_yml and step.split()[-1] in units_yml, True)
    check(f"{step} is not run by daily_update.sh",
          [ln for ln in daily_sh.splitlines() if step.split()[0] in ln and not ln.lstrip().startswith("#")
           and (step.split()[-1] in ln or step.endswith(".py"))], [])
# bucket:telegraph (2026-11-15) runs in telegraph-bucket.yml and nowhere else; its raw cache
# comes back to the media disk by the add-only cache-sync unit.
bucket_yml = (REPO / ".github" / "workflows" / "telegraph-bucket.yml").read_text()
check("fetch_telegraph.py --holes all runs in telegraph-bucket.yml", "tools/fetch_telegraph.py --holes all" in bucket_yml, True)
check("fetch_telegraph.py --holes is not run by daily_update.sh",
      [ln for ln in daily_sh.splitlines() if "fetch_telegraph.py" in ln and "--holes" in ln and not ln.lstrip().startswith("#")], [])
check("bucket:telegraph is not planned locally", "bucket:telegraph" in keys, False)
check("bucket:telegraph is no unit of daily_update.sh", "unit_bucket_telegraph" in daily_sh, False)
check("cache-sync is planned", "cache-sync" in keys, True)
check("cache-sync runs tools/cache_sync.py", "python3 tools/cache_sync.py" in daily_sh, True)
check("telegraph-bucket.yml uploads the artifact cache-sync lands", "cache-telegraph-source-${{ github.run_id }}" in bucket_yml, True)
import cache_sync
# The fifteensquared fetches of the ft, azed and genius units (2026-11-15) run in
# fifteensquared-fetch.yml; the filers stay in the units (desktop search/OCR, media-disk copies).
fsq_yml = (REPO / ".github" / "workflows" / "fifteensquared-fetch.yml").read_text()
for cat in ('--category FT', '--category Azed', '--category "Guardian Genius"'):
    check(f"fifteensquared-fetch.yml fetches {cat}", cat in fsq_yml, True)
check("fetch_fifteensquared.py is not run by daily_update.sh",
      [ln for ln in daily_sh.splitlines() if "fetch_fifteensquared.py" in ln and not ln.lstrip().startswith("#")], [])
check("fifteensquared-fetch.yml uploads the artifact cache-sync lands", "cache-fifteensquared-${{ github.run_id }}" in fsq_yml, True)
check("cache_sync mirrors the fifteensquared folder", cache_sync.CACHES["fifteensquared"], cache_sync.downloads.FIFTEENSQUARED)
check("cache_sync finds the fifteensquared workflow", cache_sync.WORKFLOWS["fifteensquared"], "fifteensquared-fetch.yml")
check("the ft, azed and genius units still file", all(f"unit_{u}()" in daily_sh for u in ("ft", "azed", "genius")), True)
# The blog fetches of blog:times and blog:telegraph (posts, and the Times comments) run in
# blog-fetch.yml; the parsers and filers stay in the units.
blog_yml = (REPO / ".github" / "workflows" / "blog-fetch.yml").read_text()
check("blog-fetch.yml fetches both blogs", "blog: [timesforthetimes, bigdave44]" in blog_yml, True)
check("blog-fetch.yml uploads the artifact cache-sync lands", "cache-${{ matrix.blog }}-${{ github.run_id }}" in blog_yml, True)
check("fetch_wp_blog.py is not run by daily_update.sh",
      [ln for ln in daily_sh.splitlines() if "fetch_wp_blog.py" in ln and not ln.lstrip().startswith("#")], [])
for blog in ("timesforthetimes", "bigdave44"):
    check(f"cache_sync finds the {blog} workflow", cache_sync.WORKFLOWS[blog], "blog-fetch.yml")
    check(f"cache_sync records the {blog} posts in the manifest", cache_sync.MANIFESTED[blog], "posts")
check("cache_sync mirrors the timesforthetimes folder", cache_sync.CACHES["timesforthetimes"], cache_sync.downloads.TIMESFORTHETIMES)
check("a refetched comments month is merged, keeping a row only the old copy has",
      cache_sync.merged("comments/2026-11.json", b'[{"id": 1, "date": "a"}, {"id": 3, "date": "c"}]',
                        b'[{"id": 1, "date": "a"}, {"id": 2, "date": "b"}]'),
      b'[{"id": 1, "date": "a"}, {"id": 2, "date": "b"}, {"id": 3, "date": "c"}]')
check("a merge is idempotent", cache_sync.merged("comments/2026-11.json", b'[{"id": 1, "date": "a"}]', b'[{"id": 1, "date": "a"}]'), b'[{"id": 1, "date": "a"}]')
check("a post is never merged", cache_sync.merged("posts/1.json", b'{"a": 1}', b'{"a": 1, "b": 2}'), None)
check("cache_sync mirrors the telegraph-source folder", cache_sync.CACHES["telegraph-source"], cache_sync.downloads.TELEGRAPH)
check("slow fetchers stay out of after_tick's FETCHERS", set(du.SLOW_FETCHERS) & set(du.FETCHERS), set())
# The CI fetchers run in .github/workflows/fetch-puzzles.yml and nowhere else.
workflow = (REPO / ".github" / "workflows" / "fetch-puzzles.yml").read_text()
for f in du.CI_FETCHERS:
    check(f"fetch:{f} is not planned locally", f"fetch:{f}" in keys, False)
    check(f"{f} is in fetch-puzzles.yml", f in workflow, True)
for f in du.FETCHERS + du.SLOW_FETCHERS:
    check(f"{f} is not in fetch-puzzles.yml", f"tools/{f}.py" in workflow or f" {f}" in workflow.split("FETCHERS:")[1].split("\n")[0], False)

# progress-counts publishes /progress/'s counts off today's coverage ledger, so it waits for
# that ledger until LEDGER_WAIT_UNTIL, then records without it.
du.COVERAGE_STATE = Path(tempfile.mkdtemp())


def at(hour):
    return time.mktime((2026, 10, 15, hour, 0, 0, 0, 0, -1))


def plans_counts(t):
    return "progress-counts" in [u.key for u in du.plan(Ledger(), t)]


check("progress-counts waits for today's coverage ledger in the morning", plans_counts(at(3)), False)
check("the other phases do not wait for it", "checks" in [u.key for u in du.plan(Ledger(), at(3))], True)
check("progress-counts records without the ledger past LEDGER_WAIT_UNTIL", plans_counts(at(du.LEDGER_WAIT_UNTIL)), True)
(du.COVERAGE_STATE / "2026-10-15.json").write_text("{}")
check("progress-counts runs once today's ledger is saved", plans_counts(at(3)), True)
check("yesterday's ledger is not today's", plans_counts(time.mktime((2026, 10, 16, 3, 0, 0, 0, 0, -1))), False)

# The choice, read off what each unit runs before its own build step.
for k in [f"fetch:{f}" for f in du.FETCHERS + du.SLOW_FETCHERS] + ["wayback:privateeye", "solutions", "blog:times", "blog:telegraph", "cache-sync",
          "xval:globe", "ft", "azed", "progress-counts", "minute", "reports", "checks"]:
    check(f"{k} skips the start rebuild", du.reads_generated(k), False)
for k in ["annotate:p1", "miss:p1:3a"]:
    check(f"{k} keeps the start rebuild", du.reads_generated(k), True)

# The CLI daily_update.sh reads: "none" skips, anything else (an unknown kind
# prints nothing) rebuilds.
def generated(kind):
    r = subprocess.run([sys.executable, "tools/daily_units.py", "generated", kind],
                       capture_output=True, text=True)
    return r.stdout.rstrip("\n")


check("generated fetch:fetch_independent", generated("fetch:fetch_independent"), "none")
check("generated annotate:x", generated("annotate:x"), "all")
check("generated of an unknown kind prints nothing", generated("nosuch"), "")
# A fetch:* unit failing FETCH_FAIL_ALERT ticks in a row alerts once, with its own last error line.
import unit_queue
sent = []
unit_queue.alert = sent.append


class Rows:
    def __init__(self, rows): self.rows = rows
    def append(self, r): self.rows.append(r)


def ends(rcs, key="fetch:tls_puzzles", t0=1000):
    return [{"key": key, "event": "end", "at": t0 + i, "rc": rc, **({"err": "TLS 1622: no crossword image in the article"} if rc else {})}
            for i, rc in enumerate(rcs)]


n = du.FETCH_FAIL_ALERT
H = 3600
short = Rows(ends([1] * (n - 1)))
du.alert_fetch_streaks(short, now=1000 + 2 * H)
check("no alert one failure short and under 24h", sent, [])
du.alert_fetch_streaks(short, now=1000 + 25 * H)
check("alert when the first failure is over 24h old", len(sent), 1)
sent.clear()
rows = Rows(ends([1] * n))
du.alert_fetch_streaks(rows, now=1000 + H)
check("alert at N failures in a row", len(sent), 1)
check("alert carries the unit's error line", "TLS 1622: no crossword image in the article" in sent[0] and "fetch:tls_puzzles" in sent[0], True)
rows.rows += ends([1] * 5, t0=2000)
du.alert_fetch_streaks(rows, now=1000 + 30 * H)
check("throttled within a streak", len(sent), 1)
rows.rows += ends([3], t0=10 * H) + ends([1] * n, t0=11 * H)   # after the alert's own time, so rc 3 comes after it
du.alert_fetch_streaks(rows, now=12 * H)
check("rc 3 ends a streak; the next one alerts again", len(sent), 2)
sent.clear()
du.alert_fetch_streaks(Rows(ends([1] * n, key="solutions")), now=1000 + 99 * H)
check("only fetch:* units", sent, [])
sys.exit(1 if fails else 0)
