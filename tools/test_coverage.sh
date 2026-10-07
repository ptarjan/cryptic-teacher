#!/bin/bash
# Does every coverage-ledger bucket name a module that exists; does every
# refusal the archive.org filer can stamp have a bucket; does a missing
# puzzle land in exactly one bucket, a recoverable claim beating one that is
# not; and does the daily run queue a note only when it carries work (a
# recoverable bucket or a regression), with -q, and never otherwise?
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
COVERAGE_STATE="$tmp/state" WAKE_SH="$tmp/wake.sh" python3 - "$tmp" <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "tools")
import archive_coverage as ac
import coverage as cov
ROOT_REAL = cov.ROOT
import file_archive_org_puzzles as filer

tmp = Path(sys.argv[1])

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
saved = ac.CACHE, ac.LEDGER, ac.corpus
ac.CACHE, ac.LEDGER, ac.corpus = cache, cache / "filed.jsonl", lambda s: ({}, {})
got = {d: c for d, c, _ in ac.unfiled(filer.PAPERS["ft"], datetime.date(1981, 4, 2))}
ac.CACHE, ac.LEDGER, ac.corpus = saved
assert (got["1981-04-01"], got["1981-04-02"], got["1980-04-01"], got["1972-04-04"]) == \
    ("not-fetched", "no-scan", "no-listing", "no-scan"), got

# A date no archive.org item holds is Gale's by hand inside its archive's
# span, no source's outside it, and a series with no Gale archive has none.
assert cov.scanless("ftcryptic", "1971-01-01") == ("gale", "by-hand-only")
assert cov.scanless("ftcryptic", "1887-06-01") == ("none", "no-source")
assert cov.scanless("telegraph", "1971-01-01") == ("none", "no-source")
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
print("coverage: ok")
PY
