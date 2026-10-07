#!/usr/bin/env python3
"""The coverage ledger: every series' puzzles that exist, the ones filed, and
each missing puzzle in exactly one cause bucket that names the module owning
its fix.

    python3 tools/coverage.py                  # the ranked ledger
    python3 tools/coverage.py --json out.json  # the same, machine-readable
    python3 tools/coverage.py daily [--dry-run] # save it, diff against the last
                                               # save, queue a note when there is work

Unit: one puzzle of one series, deduplicated. A daily series that
tools/archive_coverage.py counts by print date (PRINTED there) is keyed by
date, every other numbered series by its number, a book by its position.
Denominators:

  printed dailies   every print date back to the first crossword (archive_coverage)
  numbered series   first_number() (series.py) to the highest number held or listed
  canberra          Trove articles the filer read and did not skip as no cryptic
  book              each book's estimated_puzzle_count (tools/data/book_candidates.json,
                    an upper bound), its printed_count (tools/data/books.json, where the
                    book states one), or the puzzles its last read split, if more

Each missing puzzle is claimed by the sources that know about it, and every
claim is a (source, cause) pair from CAUSES, read off the pipeline's own
fields, never its prose. A record that holds only prose gets that pipeline's
"*-no-cause" bucket: a gap in the record, owned by the module that wrote it.
A claim from a source that can still deliver beats one that cannot; a puzzle
no source claims is ("none", "no-source").

The ledger reads caches and files only, in well under a minute. It is not a
corpus job.
"""
import argparse
import collections
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import archive_coverage
import file_trove_puzzles
import series as series_meta

HOME = Path.home()
STATE = Path(os.environ.get("COVERAGE_STATE", HOME / ".cache" / "coverage_ledger"))
BLOGS = HOME / "cryptic-setter-data"
FT_PDF = BLOGS / "ft-pdf"
TROVE = HOME / ".cache" / "trove"
ROOM = "cryptic-crosswords"
WAKE_SH = os.environ.get("WAKE_SH", "/Users/pt/github/household/tools/wake.sh")
TOP = 3

Cause = collections.namedtuple("Cause", "owner fix actionable unknown")

#: report.json puzzles[].status of a book position that was not filed.
BOOK_PUZZLE_STATUSES = [
    ("shortlist", "tools/grid_verdict.py", "two or three plausible fills: a person picks"),
    ("damaged-light-list", "tools/parse_penguin_book.py", "fills exist but the OCR lost clues: the book reader"),
    ("no-solution", "tools/parse_penguin_book.py", "no grid prints this light list: a misread enumeration or order"),
    ("budget-exhausted", "tools/acquire_book.py", "the search ran out (NODE_BUDGET, WALL_SECONDS)"),
    ("unparseable", "tools/reconstruct_grid.py", "the light spec was refused"),
    ("rejected-before-search", "tools/grid_verdict.py", "the spec failed the plausibility gate"),
    ("unique-refused", "tools/acquire_book.py", "exact-unique and the filer refused it: report.json filing_problems"),
    ("unique-not-filed", "tools/acquire_books.sh", "exact-unique and filed, yet the corpus lacks it: its publish failed (.books.log)"),
    ("clues-only-refused", "tools/clues_only.py", "the clues-only filer refused it: report.json filing_problems"),
    ("cut-short", "tools/acquire_books.sh", "the re-read's 90-minute bound ended the run before this search landed"),
    ("split-moved", "tools/acquire_book.py", "this read split the book differently: the leaf is filed under another position (report.json filed_as)"),
    ("id-taken", "tools/acquire_book.py", "this read split the book differently and another puzzle holds this leaf's id"),
    ("reprint", "tools/acquire_book.py", "the leaf is a held puzzle reprinted: kept as a reading of it (report.json reprint_of)"),
    ("duplicate-in-read", "tools/acquire_book.py", "the scan holds this leaf's page twice: filed once, under the first position (report.json same_as)"),
    ("unknown-status", "tools/acquire_book.py", "a status coverage.BOOK_PUZZLE_STATUSES does not list: add it"),
]


def book_status(row):
    """The BOOK_PUZZLE_STATUSES key of an unfiled report row."""
    status, filing = row.get("status"), row.get("filing")
    if filing == "refused clues-only":
        return "clues-only-refused"
    if status == "exact-unique":
        return "unique-refused" if filing == "refused" else "unique-not-filed"
    if (status or "").startswith("shortlist-of-"):
        return "shortlist"
    return status if any(s == status for s, _, _ in BOOK_PUZZLE_STATUSES) else "unknown-status"


def _causes():
    out = {}
    # The newspaper scans: archive_coverage's classes, for archive.org and the
    # Gale pages the same filer reads.
    for key, _means, fix, recoverable, owner in archive_coverage.CLASSES:
        if key == "no-scan":
            continue  # ("none", "no-source") below
        for source in (("trove",) if key == "canberra-reprint" else ("archive.org", "gale")):
            out[(source, key)] = Cause(owner, fix, recoverable, key == "refused-no-cause")
    out[("gale", "by-hand-only")] = Cause(
        "tools/gale_inbox.py", "only a Gale page Paul downloads by hand (Gale's terms forbid scripts): "
        "tools/gale_inbox.py files what lands", False, False)
    out[("none", "no-source")] = Cause(
        "tools/first_issue.py", "no source we know prints it: find one (tools/first_issue.py SOURCES)", False, False)
    import file_blog_puzzles
    for blog, filer in (("timesforthetimes", "tools/file_times_puzzles.py"),
                        ("bigdave44", "tools/file_telegraph_puzzles.py")):
        out[(blog, "grid-not-tried")] = Cause(
            "tools/times_grids.py", f"rebuild its grid: times_grids.py --blog {blog} (the nightly "
            "tries every new post with clues; this bucket only fills when a run was skipped)", True, False)
        out[(blog, "answers-only")] = Cause(
            "tools/times_grids.py", "the post gives answers and wordplay, no clues (times_grids.has_clues), "
            "mostly 2007-2016: exhausted on the blog; only another source's clues can file it", False, False)
        out[(blog, "no-grid")] = Cause(
            "tools/times_grids.py", "the grid search found none (attempts.jsonl `how`); a parser fix "
            "that changes the post's lights makes it due (light_key), and a search fix needs "
            "--retry-failed", True, False)
        out[(blog, "grid-not-filed")] = Cause(
            filer, f"a grid is rebuilt and the filer's {file_blog_puzzles.FILINGS} has no row for it: "
            "run the filer, which writes one per grid", True, True)
        out[(blog, "filed")] = Cause(
            filer, "the filer filed it and puzzles/ lacks it: the nightly's commit or push lost it", True, False)
        for key, words in file_blog_puzzles.CAUSES.items():
            out[(blog, key)] = Cause(
                filer, f"the filer refused it: {words} ({file_blog_puzzles.FILINGS} `cause`)"
                + ("; a grid rebuilt from an answers-only post, exhausted on the blog" if key == "no-clue" else ""),
                key != "no-clue", False)
    import andlit_azed
    out[("andlit", "not-fetched")] = Cause(
        "tools/andlit_azed.py", "the nightly fetches its Guardian copy through andlit.org.uk's "
        "index (AZED_PER_NIGHT a night), then files it", True, False)
    out[("andlit", "not-read")] = Cause(
        "tools/andlit_azed.py", "its copy is cached and no filing run has tried it: andlit_azed.py file", True, False)
    for key, means in andlit_azed.CAUSES.items():
        out[("andlit", key)] = Cause(
            "tools/andlit_azed.py", f"held.json: {means}",
            key not in ("not-text", "other-puzzle", "special", "post-misses"), False)
    out[("ft-pdf", "not-fetched")] = Cause("tools/ft_pdf_puzzles.py", "fetch its PDF", True, False)
    import ft_pdf_puzzles
    for key, means in ft_pdf_puzzles.FETCH_CAUSES.items():
        out[("ft-pdf", key)] = Cause(
            "tools/ft_pdf_puzzles.py", f"fetch_failed.json `cause`: {means}"
            + ("; `ft_pdf_puzzles.py fetch` tries it again" if key == "transient" else "; exhausted"),
            key == "transient", False)
    out[("ft-pdf", "not-read")] = Cause("tools/ft_pdf_puzzles.py", "the PDF is fetched and never filed: run the filer", True, False)
    out[("ft-pdf", "refused-no-cause")] = Cause(
        "tools/ft_pdf_puzzles.py", "attempts.jsonl says filed false with prose only: record a cause enum", True, True)
    out[("trove", "not-read")] = Cause("tools/file_trove_puzzles.py", "fetched, never read: run the filer", True, False)
    for key, _outcome, _means, fix, recoverable, owner in file_trove_puzzles.CAUSES:
        out[("trove", key)] = Cause(owner, fix, recoverable, False)
    for outcome in ("pending", "refused"):
        out[("trove", f"{outcome}-no-cause")] = Cause(
            "tools/file_trove_puzzles.py",
            f"{outcome} with no `cause`: file_trove_puzzles.stamp_cause makes it due, the next read records one",
            True, True)
    out[("trove", "written-not-filed")] = Cause(
        "tools/file_trove_puzzles.py", "the ledger has an id and no file holds it", True, False)
    for status in ("no-credentials", "borrow-refused", "lending-limit", "text-not-public"):
        out[("book", status)] = Cause(
            "tools/acquire_book.py", f"archive.org said {status}: the loan, not the reader (report.json status)", True, False)
    out[("book", "not-lendable")] = Cause(
        "tools/acquire_book.py", "archive.org lends no copy and will not let this account read it "
        "(book_reads.json not_lendable): out of the queue for good; only different access reads it", False, False)
    out[("book", "reread-due")] = Cause(
        "tools/acquire_books.sh", "read by an older reader, its text on disk: the hourly job reads every due "
        "book with text on disk (book_queue.py --reread), its grid searches on the desktop", True, False)
    out[("book", "borrow-queued")] = Cause(
        "tools/acquire_books.sh", "unread, or its text lost: only a loan reads it, up to 3 loans a run "
        "(BORROWS_PER_RUN) in book_queue.py --next order, while archive.org lends", True, False)
    out[("book", "not-split")] = Cause(
        "tools/parse_penguin_book.py", "past the last puzzle the reader split: the estimate runs high, "
        "or the splitter missed leaves", True, False)
    out[("book", "read-no-report")] = Cause(
        "tools/acquire_book.py", "book_reads.json records a read under the reader in force and no report.json "
        "row says why this position is unfiled", True, True)
    # A read book's per-puzzle status (tools/grid_verdict.py verdict(), and
    # acquire_book.py's own two), for each position not filed.
    for status, owner, fix in BOOK_PUZZLE_STATUSES:
        out[("book", status)] = Cause(owner, fix, status not in ("split-moved", "id-taken", "reprint", "duplicate-in-read"),
                                      status in ("unique-not-filed", "unknown-status"))
    return out


#: Every bucket a claim may land in: (source, cause) -> who owns the fix.
CAUSES = _causes()


class Ledger:
    """One series' puzzles: those that exist, those filed, and one claim per
    missing puzzle."""

    def __init__(self, name, unit):
        self.name, self.unit = name, unit
        self.exists, self.filed = set(), set()
        self.claims = {}
        self.notes = []

    def claim(self, key, source, cause):
        if (source, cause) not in CAUSES:
            raise KeyError(f"{self.name}: ({source!r}, {cause!r}) is not in coverage.CAUSES")
        old = self.claims.get(key)
        if old is None or (not CAUSES[old].actionable and CAUSES[(source, cause)].actionable):
            self.claims[key] = (source, cause)

    def result(self):
        self.exists |= self.filed
        buckets = collections.defaultdict(list)
        for key in self.exists - self.filed:
            buckets[self.claims.get(key, ("none", "no-source"))].append(key)
        rows = []
        for (source, cause), keys in buckets.items():
            c = CAUSES[(source, cause)]
            rows.append({"source": source, "cause": cause, "puzzles": len(keys), "owner": c.owner,
                         "fix": c.fix, "actionable": c.actionable, "unknown": c.unknown,
                         "sample": sorted(map(str, keys))[:3]})
        rows.sort(key=lambda r: (not r["actionable"], -r["puzzles"]))
        return {"unit": self.unit, "exist": len(self.exists), "filed": len(self.filed),
                "missing": len(self.exists) - len(self.filed), "buckets": rows, "notes": self.notes}


def jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]
    except OSError:
        return []


def held_numbers(series):
    """The numbers of `series` filed in puzzles/ or held clues-only, read off
    the file names."""
    out = set()
    for p in [*(ROOT / "puzzles" / series).glob(f"*/{series}-*.json"),
              *(ROOT / "clues_only" / series).glob(f"{series}-*.json")]:
        try:
            out.add(int(p.stem.rsplit("-", 1)[1]))
        except ValueError:
            pass
    return out


def day_after(date):
    return (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()


# ------------------------------------------------------------ the sources

def blog_rows():
    """(blog, series, number, print-date candidates, cause) of every blog post
    our series key claims. A post's date is its print date or the day before."""
    import file_blog_puzzles
    import file_times_puzzles
    import times_grids
    for blog in ("timesforthetimes", "bigdave44"):
        d = BLOGS / blog
        grids = {r["post_id"] for r in jsonl(d / "grids.jsonl")}
        tried = {r["post_id"] for r in jsonl(d / "attempts.jsonl")}
        filings = {r["post_id"]: r["cause"] for r in jsonl(d / file_blog_puzzles.FILINGS)}
        for r in jsonl(d / "parsed.jsonl"):
            if not isinstance(r.get("number"), int):
                continue
            if blog == "timesforthetimes":
                if r.get("series") not in file_times_puzzles.LABELS:
                    continue
                key, dated = file_times_puzzles.target(r)
            else:
                key, dated = r.get("series"), True
            pid = r["post_id"]
            if pid in grids:
                cause = filings.get(pid, "grid-not-filed")
            else:
                cause = ("answers-only" if not times_grids.has_clues(r) else
                         "no-grid" if pid in tried else "grid-not-tried")
            day = r.get("printed") or (r.get("date") or "")[:10]
            dates = ([day] if r.get("printed") else [day, day_after(day)]) if dated and day else []
            yield blog, key, r["number"], dates, cause


def ft_pdf_rows():
    """(number, date, cause) of every FT puzzle the PDF index lists."""
    try:
        index = json.loads((FT_PDF / "index.json").read_text())["puzzles"]
    except (OSError, ValueError, KeyError):
        return
    try:
        failed = json.loads((FT_PDF / "fetch_failed.json").read_text())
    except (OSError, ValueError):
        failed = {}
    last = {}
    for r in jsonl(FT_PDF / "attempts.jsonl"):
        last[str(r.get("number"))] = r
    for n, meta in index.items():
        a = last.get(n)
        if a is not None:
            cause = None if a.get("filed") else "refused-no-cause"
        elif (FT_PDF / "pdf" / f"{n}.pdf").exists():
            cause = "not-read"
        else:
            cause = failed[n]["cause"] if n in failed else "not-fetched"
        if cause:
            yield int(n), meta.get("date"), cause


def andlit_rows():
    """(number, cause) of every Azed andlit.org.uk's index lists, unfiled or not."""
    import andlit_azed
    try:
        held = {int(k): v for k, v in json.loads(andlit_azed.HELD.read_text()).items()}
    except (OSError, ValueError):
        held = {}
    for n in andlit_azed.index():
        cause = held.get(n) or ("not-read" if andlit_azed.cached(n) else "not-fetched")
        yield n, cause


def gale_rows(by_number):
    """(series, date, cause) of every Gale page the scan filer has read and not filed."""
    for row in archive_coverage.ledger().values():
        ed = row["edition"]
        if not ed.startswith("GaleTimes"):
            continue
        yield "times", ed.split("/", 1)[1][:10], archive_coverage.verdict_class(row, by_number)


#: The Gale archives of the Alberta Research Portal by series: (first, last)
#: print date held. A date archive.org lacks inside one is there by hand only.
GALE_SPANS = {
    "times": ("1785-01-01", "2019-12-31"),        # The Times Digital Archive
    "ftcryptic": ("1888-01-02", "2010-12-31"),    # Financial Times Historical Archive
}


def scanless(series, date):
    """The (source, cause) of a print date no archive.org item holds."""
    span = GALE_SPANS.get(series)
    return ("gale", "by-hand-only") if span and span[0] <= date <= span[1] else ("none", "no-source")


def printed(series, paper, today):
    """A daily counted by print date: archive_coverage's classes, then the
    blogs, the FT PDFs and Gale where they can deliver what the scans cannot."""
    led = Ledger(series, "print dates")
    for date, cls, _ed in archive_coverage.unfiled(paper, today):
        led.exists.add(date)
        if cls is None:
            led.filed.add(date)
        elif cls == "no-scan":
            led.claim(date, *scanless(series, date))
        else:
            led.claim(date, "trove" if cls == "canberra-reprint" else "archive.org", cls)
    return led


def claim_dated(led, source, dates, cause):
    """Claim the first of `dates` that `led` has missing."""
    for d in dates:
        if d in led.exists and d not in led.filed:
            led.claim(d, source, cause)
            return


def build(today=None):
    import file_archive_org_puzzles as filer  # slow (the OCR stack), once
    today = today or datetime.datetime.now().astimezone().date()
    ledgers = {}
    for paper in filer.PAPERS.values():
        if paper.series in archive_coverage.PRINTED and paper.series not in ledgers:
            ledgers[paper.series] = printed(paper.series, paper, today)
    times_numbers = archive_coverage.corpus("times")[1] if "times" in ledgers else {}
    for s, date, cls in gale_rows(times_numbers):
        if s in ledgers and cls:
            claim_dated(ledgers[s], "gale", [date], cls)
    numbered = {}
    for s in series_meta.SERIES:
        first = series_meta.first_number(s)
        if first is not None and s not in ledgers:
            numbered[s] = (first, held_numbers(s), set())
    for blog, s, n, dates, cause in blog_rows():
        if s in ledgers:
            claim_dated(ledgers[s], blog, dates, cause)
        elif s in numbered:
            numbered[s][2].add((n, blog, cause))
    if "azed" in numbered:
        for n, cause in andlit_rows():
            numbered["azed"][2].add((n, "andlit", cause))
    for s, (first, held, listed) in numbered.items():
        led = Ledger(s, "numbers")
        # Up to the highest number held: a blog's stray number (a typo, another
        # series' run) must not invent thousands of puzzles; the daily fetch
        # owns the numbers past it.
        top = max(held, default=first - 1)
        led.exists = set(range(first, top + 1))
        led.filed = held & led.exists
        for n, blog, cause in listed:
            if n >= first:
                led.claim(n, blog, cause)
        ledgers[s] = led
    if "ftcryptic" in ledgers:
        for _n, date, cause in ft_pdf_rows():
            if date:
                claim_dated(ledgers["ftcryptic"], "ft-pdf", [date[:10]], cause)
    ledgers["canberra"] = trove()
    ledgers["book"] = books()
    return {"at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "series": {s: led.result() for s, led in sorted(ledgers.items())}}


def trove():
    led = Ledger("canberra", "Trove articles read as a cryptic")
    led.filed = {p.stem for p in (ROOT / "puzzles" / "canberra").glob("*/canberra-*.json")}
    read = set()
    zones = file_trove_puzzles.zones_of(TROVE)
    for r in jsonl(TROVE / "filed.jsonl"):
        art = str(r.get("article"))
        read.add(art)
        if r.get("skip"):
            continue
        if r.get("id"):
            led.exists.add(r["id"])
            led.claim(r["id"], "trove", "written-not-filed")
            continue
        key = f"article-{art}"
        led.exists.add(key)
        file_trove_puzzles.stamp_cause(r, zones)
        if r.get("refused") or r.get("pending"):
            led.claim(key, "trove", r.get("cause") or ("refused-no-cause" if r.get("refused") else "pending-no-cause"))
    unread = [p.parent.name for p in TROVE.glob("*/meta.json") if p.parent.name not in read]
    for art in unread:
        led.exists.add(f"article-{art}")
        led.claim(f"article-{art}", "trove", "not-read")
    if unread:
        led.notes.append(f"{len(unread)} fetched articles are unread; some may prove not to be cryptics")
    return led


def books():
    import acquire_book
    import book_queue
    led = Ledger("book", "book positions (estimated_puzzle_count, an upper bound)")
    registry = json.loads((ROOT / "tools" / "data" / "books.json").read_text())["books"]
    try:
        est = {r["identifier"]: r.get("estimated_puzzle_count")
               for r in json.loads((ROOT / "tools" / "data" / "book_candidates.json").read_text())["ranking"]}
    except (OSError, ValueError, KeyError):
        est = {}
    reads = book_queue.reads()
    filed = collections.defaultdict(set)
    for n in held_numbers("book"):
        filed[n // 1000].add(n % 1000)
    unmeasured, no_id = [], []
    for b in registry:
        i, ident = b["book_index"], b["identifier"]
        got = filed.get(i, set())
        led.filed |= {f"{i}:{p}" for p in got}
        try:
            report = json.loads((acquire_book.DEFAULT_OUT / ident / "report.json").read_text())
        except (OSError, ValueError):
            report = {}
        rows = {r.get("book_number"): r for r in report.get("puzzles", [])}
        split = (reads.get(ident) or {}).get("found") or 0
        # The positions an estimate, a read or a filed puzzle proves exist, at least.
        count = max([b.get("printed_count") or 0, est.get(ident) or 0, split]
                    + [n for n in rows if isinstance(n, int)] + list(got))
        if not count:
            unmeasured.append(ident)
        due = book_queue.due(ident)
        stop = report.get("status")
        if not due:
            no_id += [f"{i}:{n}" for n, r in rows.items() if r.get("status") == "id-taken"]
        for p in range(1, count + 1):
            if p in got:
                continue
            led.exists.add(f"{i}:{p}")
            if book_queue.not_lendable(ident):
                cause = "not-lendable"
            elif stop and ("book", stop) in CAUSES:
                cause = stop  # the read stopped at the text: a loan refused
            elif due:
                # A report from an older reader numbers its leaves that
                # reader's way, so its rows are not this position's.
                cause = "reread-due" if book_queue.text_of(ident) else "borrow-queued"
            elif p in rows:
                cause = book_status(rows[p])
            elif split and p > split:
                cause = "not-split"
            else:
                cause = "read-no-report"
            led.claim(f"{i}:{p}", "book", cause)
    if no_id:
        # Not a position: the position is filed, by another puzzle of the book.
        led.notes.append(f"{len(no_id)} book puzzles are unfiled because a re-read split moved another "
                         f"puzzle onto their id (report.json id-taken; tools/acquire_book.py): {', '.join(no_id[:5])}")
    if unmeasured:
        led.notes.append(f"{len(unmeasured)} of {len(registry)} books have no puzzle count until their first "
                         f"read (never sampled for book_candidates.json, no printed_count): {', '.join(unmeasured[:5])}"
                         + (" ..." if len(unmeasured) > 5 else ""))
    return led


# ------------------------------------------------------------ reading it

def ranked(ledger, actionable=True):
    """Every (series, bucket) of the ledger, largest first."""
    out = [(s, b) for s, row in ledger["series"].items() for b in row["buckets"]
           if b["actionable"] == actionable]
    return sorted(out, key=lambda sb: -sb[1]["puzzles"])


def report(ledger, top=25):
    rows = ledger["series"].values()
    out = [(f"Coverage ledger {ledger['at']}: {sum(r['filed'] for r in rows):,} filed of "
            f"{sum(r['exist'] for r in rows):,} puzzles that exist."),
           "", "Missing puzzles by bucket, those a module can still recover first:"]
    for s, b in ranked(ledger)[:top]:
        out.append(f"  {b['puzzles']:7,}  {s:<12} {b['source']:<16} {b['cause']:<20} {b['owner']}: {b['fix']}")
    out += ["", "Not recoverable by any pipeline we have:"]
    for s, b in ranked(ledger, False)[:10]:
        out.append(f"  {b['puzzles']:7,}  {s:<12} {b['source']:<16} {b['cause']:<20} {b['fix']}")
    out += ["", f"{'series':<14}{'unit':<22}{'exist':>8}{'filed':>8}{'missing':>9}"]
    for s, r in ledger["series"].items():
        out.append(f"{s:<14}{r['unit'][:21]:<22}{r['exist']:8,}{r['filed']:8,}{r['missing']:9,}")
        out += [f"    note: {n}" for n in r["notes"]]
    return "\n".join(out)


def regressions(ledger, previous):
    """What got worse since `previous`: a series filing fewer puzzles, and
    every no-cause bucket that was empty before."""
    out = []
    before = (previous or {}).get("series", {})
    for s, r in ledger["series"].items():
        p = before.get(s)
        if p is None:
            continue
        if r["filed"] < p["filed"]:
            out.append(f"{s} filed {p['filed']:,} -> {r['filed']:,} ({r['filed'] - p['filed']:+,})")
        was = {(b["source"], b["cause"]) for b in p["buckets"] if b["puzzles"]}
        for b in r["buckets"]:
            if b["unknown"] and b["puzzles"] and (b["source"], b["cause"]) not in was:
                out.append(f"new no-cause bucket: {s} {b['source']} {b['cause']} {b['puzzles']:,} "
                           f"({b['owner']}: {b['fix']})")
    return out


def note(ledger, previous):
    """The note for the room, or None when there is nothing to act on. It
    carries the work itself: the top buckets and any regression."""
    top = ranked(ledger)[:TOP]
    regs = regressions(ledger, previous)
    if not top and not regs:
        return None
    before = (previous or {}).get("series", {})
    lines = ["Coverage ledger (tools/coverage.py): puzzles lost, largest recoverable buckets first."]
    for s, b in top:
        p = next((x["puzzles"] for x in before.get(s, {}).get("buckets", [])
                  if (x["source"], x["cause"]) == (b["source"], b["cause"])), None)
        delta = "" if p is None or p == b["puzzles"] else f" ({b['puzzles'] - p:+,} since last run)"
        lines.append(f"- {b['puzzles']:,} {s} puzzles, {b['source']} {b['cause']}{delta}: "
                     f"{b['owner']}, {b['fix']}. e.g. {', '.join(b['sample'])}")
    if regs:
        lines.append("Regressions since the last run:")
        lines += [f"- {r}" for r in regs]
    return "\n".join(lines)


def daily(dry):
    ledger = build()
    try:
        previous = json.loads((STATE / "latest.json").read_text())
    except (OSError, ValueError):
        previous = None
    print(report(ledger))
    text = note(ledger, previous)
    if not dry:
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / f"{ledger['at'][:10]}.json").write_text(json.dumps(ledger, indent=1))
        if (STATE / "latest.json").exists():
            os.replace(STATE / "latest.json", STATE / "previous.json")
        (STATE / "latest.json").write_text(json.dumps(ledger, indent=1))
    if text is None:
        print("\nno recoverable bucket and no regression: no note")
        return ledger, None
    print("\n" + ("[dry run] would queue for #" + ROOM + ":\n" if dry else "") + text)
    if not dry:
        r = subprocess.run([WAKE_SH, "-q", "-c", ROOM, text], timeout=60, check=False)
        if r.returncode:
            print(f"wake.sh exited {r.returncode}", file=sys.stderr)
            sys.exit(r.returncode)
    return ledger, text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", choices=["daily"], help="save, diff and queue the note")
    ap.add_argument("--dry-run", action="store_true", help="daily: neither save nor queue")
    ap.add_argument("--json", type=Path, help="write the ledger here")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args(argv)
    if args.cmd == "daily":
        ledger, _ = daily(args.dry_run)
    else:
        ledger = build()
        print(report(ledger, args.top))
    if args.json:
        args.json.write_text(json.dumps(ledger, indent=1))


if __name__ == "__main__":
    main()
