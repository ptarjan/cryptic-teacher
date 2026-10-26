#!/usr/bin/env python3
# Does every coverage-ledger bucket name a module that exists; does every
# refusal the archive.org filer can stamp have a bucket; does a missing
# puzzle land in exactly one bucket, a recoverable claim beating one that is
# not; and does the daily run queue a note only when it carries work (a
# recoverable bucket or a regression), with -q, and never otherwise?
#
#     python3 tests/test_coverage.py
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, "tools")

tmp = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, tmp, ignore_errors=True)
os.environ["COVERAGE_STATE"] = str(tmp / "state")
os.environ["WAKE_SH"] = str(tmp / "wake.sh")


def fail(msg):
    print(f"FAIL {msg}")
    sys.exit(1)


def tools_py(code, **env):
    """`code` in a fresh interpreter run from tools/, as the shell's python3 -c did."""
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO / "tools", check=True, text=True,
                       stdout=subprocess.PIPE, env={**os.environ, **env})
    return r.stdout.rstrip("\n")


import archive_coverage as ac
import coverage as cov
ROOT_REAL = cov.ROOT
import file_archive_org_puzzles as filer


# Every bucket names an owner that exists, a fix, and its flags.
for (source, cause), c in cov.CAUSES.items():
    assert Path(c.owner).exists(), (source, cause, c.owner)
    assert c.fix.strip() and isinstance(c.actionable, bool) and isinstance(c.unknown, bool), (source, cause)
# Every scan class is a bucket, and every refusal the filer stamps is a class.
causes = {k for _, k in cov.CAUSES}
assert {k for k, *_ in ac.CLASSES} - {"no-scan"} <= causes
assert set(filer.REFUSALS) <= set(ac.CLASS), set(filer.REFUSALS) - set(ac.CLASS)
v = filer.refuse({"number": 1}, "not-a-grid", "1x2")
assert ac.verdict_class({"verdicts": [v]}, {}) == "not-a-grid"
try:
    filer.refuse({}, "made-up", "x")
    raise AssertionError("refuse took a cause REFUSALS lacks")
except ValueError:
    pass
# Every reason a blog filer or the FT PDF fetch records is a bucket.
import file_blog_puzzles, ft_pdf_puzzles
for blog in ("timesforthetimes", "bigdave44"):
    assert {(blog, k) for k in [*file_blog_puzzles.CAUSES, "filed", "answers-only"]} <= set(cov.CAUSES), blog
assert {("ft-pdf", k) for k in ft_pdf_puzzles.FETCH_CAUSES} <= set(cov.CAUSES)
# Every Trove cause is a bucket; a pending or refused row lands in its
# cause's; one read before causes lands in a no-cause bucket and is made due,
# except a read that reached the vote with no clue columns cached; a row
# without a cause is unwritable.
import file_trove_puzzles as trove
assert {("trove", k) for k, *_ in trove.CAUSES} <= set(cov.CAUSES)
(tmp / "trove" / "1").mkdir(parents=True)
(tmp / "trove" / "1" / "meta.json").write_text("{}")
(tmp / "trove-clues" / "5").mkdir(parents=True)
(tmp / "trove-clues" / "5" / "zone0.png").write_bytes(b"")
rows = [trove.ledger_row("1", "h", trove.wait({"grid": "image"}, "clues-unread", "clues unread: 5-across")),
        trove.ledger_row("2", "h", trove.refuse({}, "clues-dont-parse", "across clues do not parse")),
        {"article": "3", "inputs": "h", "grid": "image", "pending": "no reading of the page's clues"},
        {"article": "4", "inputs": "h", "pending": "no grid: x"},
        {"article": "5", "inputs": "h", "grid": "image", "pending": "no reading of the page's clues"},
        {"article": "6", "inputs": "h", "refused": "no print date in the OCR's first line"}]
(tmp / "trove" / "filed.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
cov.TROVE = tmp / "trove"
got = {b["cause"]: b["sample"] for b in cov.trove().result()["buckets"]}
assert got == {"clues-unread": ["article-1"], "clues-dont-parse": ["article-2"], "zones-not-fetched": ["article-3"],
               "pending-no-cause": ["article-4", "article-5"], "refused-no-cause": ["article-6"]}, got
due = [r["article"] for r in rows if trove.stamp_cause(r, tmp / "trove-clues")]
assert due == ["4", "5", "6"] and all(r["inputs"] == "" for r in rows[3:]), rows
for bad in ({"pending": "no grid: x"}, {"refused": "crashed"}, {"pending": "x", "cause": "crashed"},
            {"pending": "x", "cause": "made-up"}):
    try:
        trove.ledger_row("7", "h", bad)
        raise AssertionError(f"ledger_row wrote {bad}")
    except ValueError:
        pass
for stamp, cause in ((trove.wait, "crashed"), (trove.refuse, "no-grid"), (trove.wait, "made-up")):
    try:
        stamp({}, cause, "x")
        raise AssertionError(f"{stamp.__name__} took {cause}")
    except ValueError:
        pass

# Every book status the ledger names is a book bucket.
for s, _, _ in cov.BOOK_PUZZLE_STATUSES:
    assert ("book", s) in cov.CAUSES, s
assert cov.book_status({"status": "shortlist-of-3"}) == "shortlist"
assert cov.book_status({"status": "exact-unique", "filing": "filed unsolved"}) == "unique-not-filed"
assert cov.book_status({"status": "exact-unique", "filing": "refused"}) == "unique-refused"
assert cov.book_status({"status": "no-solution", "filing": "refused clues-only"}) == "clues-only-refused"
assert cov.book_status({"status": "something new"}) == "unknown-status"

# Every unfiled book position gets a named cause from the book's state:
# a due book's old report is ignored (an older reader numbered its leaves),
# and a book read by the reader in force is read off its report.
import acquire_book, book_queue
broot = tmp / "books"
(broot / "tools" / "data").mkdir(parents=True)
(broot / "puzzles" / "book" / "2000").mkdir(parents=True)
(broot / "clues_only" / "book").mkdir(parents=True)
(broot / "tools" / "data" / "renamed_ids.json").write_text("{}")
(broot / "tools" / "data" / "books.json").write_text(json.dumps({"books": [
    {"book_index": 1, "identifier": "fresh"}, {"book_index": 2, "identifier": "old-text"},
    {"book_index": 3, "identifier": "lost"}, {"book_index": 4, "identifier": "never"},
    {"book_index": 5, "identifier": "unlendable"}]}))
(broot / "tools" / "data" / "book_candidates.json").write_text(json.dumps({"ranking": [
    {"identifier": i, "estimated_puzzle_count": 6} for i in ("fresh", "old-text", "lost", "unlendable")]}))
(broot / "puzzles" / "book" / "2000" / "book-1001.json").write_text("{}")
(broot / "clues_only" / "book" / "book-1002.json").write_text("{}")
(broot / "puzzles" / "book" / "2000" / "book-3001.json").write_text("{}")
reads = broot / "reads.json"
reads.write_text(json.dumps({"fresh": {"on": "9999-01-01", "found": 5},
                             "unlendable": {"on": "2000-01-01", "not_lendable": "is_lendable=false"}}))
out = tmp / "reports"
for ident, rows in (("fresh", [{"book_number": 3, "status": "no-solution", "filing": "refused clues-only"},
                               {"book_number": 4, "status": "budget-exhausted"}]),
                    ("old-text", [{"book_number": 1, "status": "exact-unique", "filing": "filed unsolved"}])):
    (out / ident).mkdir(parents=True)
    (out / ident / "report.json").write_text(json.dumps({"puzzles": rows}))
texts = tmp / "texts"
texts.mkdir()
(texts / "old-text.txt").write_text("text")
import media_manifest  # the queue reads which texts are held off the SSD manifest
media_manifest.DIR = tmp / "manifest"
media_manifest.write(media_manifest.BOOK_TEXTS, [{"identifier": "old-text", "chars": 4, "at": 0}])
cov.ROOT, acquire_book.DEFAULT_OUT, book_queue.READS, book_queue.TEXT_DIR = broot, out, reads, texts
got = {(b["cause"], b["puzzles"]) for b in cov.books().result()["buckets"]}
assert got == {("clues-only-refused", 1), ("budget-exhausted", 1), ("read-no-report", 1), ("not-split", 1),
               ("reread-due", 6), ("borrow-queued", 5), ("not-lendable", 6)}, got
cov.ROOT = ROOT_REAL

# One bucket per missing puzzle: recoverable beats not, unclaimed is no-source.
led = cov.Ledger("x", "numbers")
led.exists = {1, 2, 3, 4}
led.filed = {1}
led.claim(2, "none", "no-source")
led.claim(2, "timesforthetimes", "no-grid")        # recoverable: replaces
led.claim(2, "none", "no-source")                  # not: does not
led.claim(3, "archive.org", "blank-clues")
led.claim(3, "timesforthetimes", "no-grid")        # both recoverable: first stands
try:
    led.claim(4, "blog", "made-up")
    raise AssertionError("claim took a bucket CAUSES lacks")
except KeyError:
    pass
r = led.result()
got = {(b["source"], b["cause"]): b["puzzles"] for b in r["buckets"]}
assert got == {("timesforthetimes", "no-grid"): 1, ("archive.org", "blank-clues"): 1, ("none", "no-source"): 1}, got
assert (r["exist"], r["filed"], r["missing"]) == (4, 1, 3)
assert r["buckets"][-1]["cause"] == "no-source"     # not recoverable sorts last

# Known (/progress/'s whole bar) counts every puzzle printed by today, as if
# the series is still going, or up to its last issue if it ended. A running
# series carries its newest held number on at its held run's pace; a series
# with one dated number stops at its highest held.
import datetime
import series as sm
D = datetime.date
weekly = lambda s, n: {1: D(2000, 1, 2), 53: D(2000, 12, 31)}.get(n)          # 52 weeks, 52 numbers
assert cov.due_number("azed", {1, 53}, D(2001, 1, 28), weekly) == 57
assert cov.due_number("azed", {1, 53}, D(2000, 12, 31), weekly) == 53
assert cov.due_number("azed", {1, 53}, D(2000, 6, 1), weekly) == 53   # never below held
assert cov.due_number("azed", {53}, D(2030, 1, 1), weekly) == 53      # no pace to carry
assert cov.due_number("listener", {4016}, D(2026, 10, 15), lambda s, n: None) == 4938, "weekly from the blog's No 4,930"
assert cov.due_number("listener", {5000}, D(2026, 10, 15), lambda s, n: D(2026, 8, 14) if n == 5000 else None) == 5008, "a later held number is the anchor"
assert cov.number_runs("nation", {258, 3503}, D(2026, 10, 12), weekly) == [(1, 3529)], "ended at lastIssue"
monthly = lambda s, n: {20000: D(2000, 1, 1), 270: D(2024, 2, 1), 290: D(2025, 10, 1)}.get(n)
assert cov.number_runs("timesclub", {20000, 20279, 270, 290}, D(2026, 10, 1), monthly) == \
    [(20000, 20279), (270, 302)], "a renumbered series: the old run ends, the new one runs"
assert cov.number_runs("metro", {9516}, D(2026, 10, 11), weekly) == [(9516, 10072)], \
    "a day count: from the oldest puzzle any source holds (firstIssue) to today's, not from No 1"
# A printed daily's own numbering caps its print dates: Nos 10 and 13 on the
# 1st and the 6th leave two puzzles for four missing days, so the two with
# the least evidence (no source, then no crossword found) are not counted.
led = cov.Ledger("times", "print dates")
led.filed = {"2000-01-01", "2000-01-06"}
led.exists = led.filed | {"2000-01-02", "2000-01-03", "2000-01-04", "2000-01-05"}
led.claim("2000-01-02", "archive.org", "not-read")
led.claim("2000-01-03", "archive.org", "no-crossword-found")
led.claim("2000-01-05", "archive.org", "not-read")
assert sorted(cov.surplus_dates(led, {10: "2000-01-01", 13: "2000-01-06"}, "1999-12-23")) == \
    ["2000-01-03", "2000-01-04"], "the surplus goes, weakest evidence first"
# Before the first filed number: No 10 is the tenth, so nine dates before it.
assert cov.surplus_dates(led, {10: "2000-01-01"}, "1999-12-20") == []
led.exists |= {"1999-12-%d" % d for d in range(20, 32)}
assert len(cov.surplus_dates(led, {10: "2000-01-01", 13: "2000-01-06"}, "1999-12-20")) == 3 + 2
# The reverse: Nos 1 and 5 on two dates with one missing date between leave
# three numbers for one slot, so two printed puzzles have no date of ours.
led = cov.Ledger("times", "print dates")
led.filed = {"2000-01-01", "2000-01-03"}
led.exists = led.filed | {"2000-01-02"}
assert cov.undated_numbers(led, {1: "2000-01-01", 5: "2000-01-03"}, "2000-01-01") == {"No 2": 2, "No 3": 3}, \
    "the paper's own count stands; the numbers with no date slot get their own keys"
assert cov.undated_numbers(led, {1: "2000-01-01", 3: "2000-01-03"}, "2000-01-01") == {}
# Every series has a Known rule: printed days, numbers, Trove dates, the book
# estimates, or none because it is a reprint of another or our own.
for s in sm.SERIES:
    m = sm.meta(s)
    rule = (s in ac.PRINTED or sm.first_number(s) is not None or "numberIsDayCount" in m
            or s in ("canberra", sm.BOOK_SERIES) or m.get("reprints") or m.get("unlisted"))
    assert rule, f"{s}: no Known rule in tools/coverage.py, so /progress/ falls back to downloaded"
# The Canberra Times holds one puzzle a print date, so an unfiled article keys
# by its date and a date's other articles add nothing.
day = {"1": D(1989, 1, 3), "2": D(1989, 1, 3)}
assert cov.trove_key("1", day) == cov.trove_key("2", day) == "canberra-890103"

# Scan classes off the cached listings: a PDF archive.org never OCR'd is an
# edition like any other ("not-fetched" until fetched), a year whose listing is not cached "no-listing", a date no item
# holds "no-scan".
import datetime
cache = tmp / "cache"
(cache / "items").mkdir(parents=True)
(cache / "items" / "_group_ft.json").write_text(json.dumps(
    [{"identifier": f"FinancialTimes{y}UKEnglish"} for y in (1980, 1981)]))
(cache / "items" / "FinancialTimes1981UKEnglish.json").write_text(json.dumps(
    {"files": [{"name": "Apr 01 1981, Financial Times, #28435, UK (en).pdf", "format": "Image Container PDF"}]}))
saved = ac.CACHE, ac.LEDGERS, ac.corpus
ac.CACHE, ac.LEDGERS, ac.corpus = cache, [cache / "filed.jsonl"], lambda s: ({}, {})
got = {d: c for d, c, _ in ac.unfiled(filer.PAPERS["ft"], datetime.date(1981, 4, 2))}
assert (got["1981-04-01"], got["1981-04-02"], got["1980-04-01"], got["1972-04-04"]) == \
    ("not-fetched", "no-scan", "no-listing", "no-scan"), got
# On the media disk a fetched edition is one the archiveorg-editions (or
# gale-editions) manifest holds: its pages.json is never stat-ed.
ed = {d: e for d, _, e in ac.unfiled(filer.PAPERS["ft"], datetime.date(1981, 4, 2))}["1981-04-01"]
(cache / ed).mkdir(parents=True)
(cache / ed / "pages.json").write_text("{}")
assert {d: c for d, c, _ in ac.unfiled(filer.PAPERS["ft"], datetime.date(1981, 4, 2))}["1981-04-01"] == "not-read"
import media_manifest as mm
mm_saved = mm.DIR, mm.on_media
item_row = {"key": "FinancialTimes1981UKEnglish", **ac._item_off_media("FinancialTimes1981UKEnglish")}
mm.DIR, mm.on_media = tmp / "mf", lambda f: True
mm.DIR.mkdir()
(mm.DIR / "gale-editions.jsonl").write_text("")
(mm.DIR / f"{ac.fetcher.IA_ITEMS}.jsonl").write_text(json.dumps(item_row) + "\n")
for rows_, want in (([], "not-fetched"), ([{"edition": ed}], "not-read")):
    (mm.DIR / "archiveorg-editions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_))
    got = {d: c for d, c, _ in ac.unfiled(filer.PAPERS["ft"], datetime.date(1981, 4, 2))}
    assert got["1981-04-01"] == want, (rows_, got)
mm.DIR, mm.on_media = mm_saved
ac.CACHE, ac.LEDGERS, ac.corpus = saved

# A date no archive.org item holds is Gale's by hand inside its archive's
# span, no source's outside it, and a series with no Gale archive has none.
assert cov.scanless("ftcryptic", "1971-01-01") == ("gale", "by-hand-only")
assert cov.scanless("ftcryptic", "1887-06-01") == ("none", "no-source")
assert cov.scanless("telegraph", "1971-01-01") == ("none", "no-source")
assert cov.scanless("times", "2014-12-31") == ("gale", "by-hand-only")
assert cov.scanless("times", "2015-06-01") == ("none", "no-source")
assert not cov.CAUSES[("gale", "by-hand-only")].actionable


def ledger(filed, buckets):
    rows = [{"source": s, "cause": c, "puzzles": n, **cov.CAUSES[(s, c)]._asdict(), "sample": ["k"]}
            for s, c, n in buckets]
    return {"at": "2026-10-06T05:50:00-06:00",
            "series": {"times": {"unit": "print dates", "exist": 100, "filed": filed,
                                 "missing": 100 - filed, "buckets": rows, "notes": []}}}


# No recoverable bucket and no regression: no note at all.
quiet = ledger(50, [("none", "no-source", 50)])
assert cov.note(quiet, None) is None
assert cov.note(quiet, quiet) is None
# The note carries the top three recoverable buckets, owner and count.
busy = ledger(50, [("archive.org", "blank-clues", 20), ("archive.org", "no-grid", 9),
                   ("timesforthetimes", "no-grid", 7), ("archive.org", "not-a-grid", 2),
                   ("none", "no-source", 12)])
text = cov.note(busy, None)
assert "20 times puzzles, archive.org blank-clues" in text and "tools/file_archive_org_puzzles.py" in text
assert "not-a-grid" not in text and "no-source" not in text, text
# A drop in filed, or a no-cause bucket that was empty before, is a regression.
assert cov.regressions(ledger(49, []), quiet) == ["times filed 50 -> 49 (-1)"]
unknown = ledger(50, [("trove", "pending-no-cause", 3)])
assert cov.regressions(unknown, quiet)[0].startswith("new no-cause bucket: times trove pending-no-cause 3")
assert cov.regressions(unknown, unknown) == []
assert "Regressions" in cov.note(ledger(49, [("none", "no-source", 51)]), quiet)

# daily(): saves the ledger, and queues with -q only when the note has work.
calls = tmp / "calls"
Path(os.environ["WAKE_SH"]).write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> {calls}\n')
os.chmod(os.environ["WAKE_SH"], 0o755)
for built, wakes in ((quiet, False), (busy, True)):
    calls.unlink(missing_ok=True)
    cov.build = lambda b=built: b
    cov.daily(dry=False)
    assert (cov.STATE / "latest.json").exists()
    assert calls.exists() == wakes, built
    if wakes:
        args = calls.read_text().split("\n")
        assert args[:3] == ["-q", "-c", "cryptic-crosswords"], args
# A blog post the grid search found more lights missing from than the
# tolerant search puts back is a partial post, not a search to retry; one gap
# (sundaytough 2's 23d) or no grid at all is still no-grid.
blogs = tmp / "blogs"
for blog in ("timesforthetimes", "bigdave44"):
    (blogs / blog).mkdir(parents=True)
    (blogs / blog / "parsed.jsonl").write_text("")
clue = lambda n: {"number": n, "direction": "across", "answer": "", "clue": "Clue words (5)", "enumeration": "5"}
recs = [{"post_id": i, "series": "toughie", "number": n, "date": "2010-01-01", "entries": [clue(k) for k in range(1, 25)]}
        for i, n in ((1, 92), (2, 101), (3, 2))]
(blogs / "bigdave44" / "parsed.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
(blogs / "bigdave44" / "attempts.jsonl").write_text(
    json.dumps({"post_id": 1, "how": "no grid: no light numbered 3, 11, 20"}) + "\n"
    + json.dumps({"post_id": 2, "how": "no grid"}) + "\n"
    + json.dumps({"post_id": 3, "how": "no grid: no light numbered 23"}) + "\n")
cov.BLOGS = blogs
got = {n: cause for _b, _s, n, _d, cause in cov.blog_rows()}
assert got == {92: "partial-post", 101: "no-grid", 2: "no-grid"}, got
assert not cov.CAUSES[("bigdave44", "partial-post")].actionable
print("coverage: ok")

# ft_pdf_rows asks the ft-pdf manifest which PDFs are fetched, never the disk:
# 2.pdf on disk but not in the manifest counts as not fetched.
(tmp / "dl" / "ft-pdf" / "pdf").mkdir(parents=True)
(tmp / "dl" / ".manifest").mkdir(parents=True)
(tmp / "dl" / "ft-pdf" / "index.json").write_text(
    '{"puzzles": {"1": {"date": "2020-01-01"}, "2": {"date": "2020-01-02"}}}\n')
(tmp / "dl" / "ft-pdf" / "pdf" / "2.pdf").write_text("")
(tmp / "dl" / ".manifest" / "ft-pdf.jsonl").write_text('{"key": "1.pdf", "at": 1}\n')
got = tools_py("import coverage as cov\nprint(sorted(cov.ft_pdf_rows()))", CT_DOWNLOADS=str(tmp / "dl"))
if got != "[(1, '2020-01-01', 'not-read'), (2, '2020-01-02', 'not-fetched')]":
    fail(f"ft_pdf_rows off the manifest: {got}")
print("ft_pdf_rows: ok")

# coverage.trove_articles lists the disk until trove-titles is complete, then
# asks only the manifest.
(tmp / "tv" / ".manifest").mkdir(parents=True)
(tmp / "tv" / "trove" / "5").mkdir(parents=True)
(tmp / "tv" / "trove" / "5" / "meta.json").write_text("{}\n")
(tmp / "tv" / ".manifest" / "trove-titles.jsonl").write_text('{"article": "9", "title": "x", "at": 1}\n')
tv = {"CT_DOWNLOADS": str(tmp / "tv")}
code = "import coverage as c; print(c.trove_articles())"
before = tools_py(code, **tv)
(tmp / "tv" / ".manifest" / "trove-titles.complete").write_text("{}\n")
after = tools_py(code, **tv)
if f"{before} {after}" != "['5'] ['9']":
    fail(f"trove_articles: {before} {after}")
print("trove_articles: ok")

# coverage.trove_dates reads the index listings until trove-dates is complete,
# then only the manifest; stamp_cause's zone check likewise off trove-zones.
(tmp / "tv" / "trove" / "index").mkdir(parents=True)
(tmp / "tv" / "trove-clues" / "7").mkdir(parents=True)
(tmp / "tv" / "trove" / "index" / "1980.jsonl").write_text('{"id": 5, "date": "Thursday 11 December 1980"}\n')
(tmp / "tv" / "trove-clues" / "7" / "zone0.png").write_text("")
(tmp / "tv" / ".manifest" / "trove-dates.jsonl").write_text(
    '{"article": "8", "date": "Friday 12 December 1980", "at": 1}\n')
(tmp / "tv" / ".manifest" / "trove-zones.jsonl").write_text(
    '{"article": "8", "readings": true, "at": 1}\n{"article": "7", "readings": false, "at": 1}\n')
q = '''import coverage as c, downloads, file_trove_puzzles as t
row = lambda a: {"article": a, "inputs": "h", "grid": "image", "pending": "x"}
print(c.trove_dates(), [a for a in "78" if not t.stamp_cause(row(a), downloads.TROVE_CLUES)])'''
before = tools_py(q, **tv)
(tmp / "tv" / ".manifest" / "trove-dates.complete").write_text("{}\n")
(tmp / "tv" / ".manifest" / "trove-zones.complete").write_text("{}\n")
after = tools_py(q, **tv)
if before != "{'5': datetime.date(1980, 12, 11)} ['8']":
    fail(f"trove_dates/zones listed: {before}")
if after != "{'8': datetime.date(1980, 12, 12)} ['7']":
    fail(f"trove_dates/zones manifest: {after}")
print("trove_dates, stamp_cause zones: ok")

# privateeye_wayback.lost reads the SSD summary fetch/fetch-ia/file write, not
# the captures: with it saved, the scans can go and the causes stand; a
# changed privateeye_wayback.py (version) indexes the disk again once.
(tmp / "pe" / "privateeye-wayback" / "ia").mkdir(parents=True)
(tmp / "pe" / "privateeye-wayback" / "ia" / "848_djvu.txt").write_text("no clues here\n")
(tmp / "pe" / "privateeye-wayback" / "refused.json").write_text('{"5": "grid does not rebuild"}\n')
got = tools_py('''
import json, shutil, privateeye_wayback as pw
causes = lambda: {n: c for n, c in pw.lost().items() if n in (2, 3, 69)}
first = causes()
s = json.loads(pw.summary_path().read_text())
assert s['ia'] == [3] and s['refused'] == ['5'], s
shutil.rmtree(pw.DIR)
second = causes()
s['version'] = 'old'
pw.summary_path().write_text(json.dumps(s))
print(first == second, first, causes())''', CT_DOWNLOADS=str(tmp / "pe"))
if got != ("True {2: 'scan-not-read', 3: 'scan-unparsed', 69: 'no-capture'} "
           "{2: 'scan-not-read', 3: 'scan-not-read', 69: 'no-capture'}"):
    fail(f"privateeye_wayback.lost off the summary: {got}")
print("privateeye_wayback.lost: ok")
