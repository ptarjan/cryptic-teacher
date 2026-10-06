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
# Every book status the ledger names is a book bucket.
for s, _, _ in cov.BOOK_PUZZLE_STATUSES:
    assert ("book", s) in cov.CAUSES, s
assert cov.book_status("shortlist-of-3") == "shortlist"
assert cov.book_status("exact-unique") == "unique-not-filed"
assert cov.book_status("something new") == "unknown-status"

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

# Scan classes off the cached listings: a PDF archive.org never OCR'd is
# "no-ocr", a year whose listing is not cached "no-listing", a date no item
# holds "no-scan".
import datetime
cache = tmp / "cache"
(cache / "items").mkdir(parents=True)
(cache / "items" / "_group_ft.json").write_text(json.dumps(
    [{"identifier": f"FinancialTimes{y}UKEnglish"} for y in (1980, 1981)]))
(cache / "items" / "FinancialTimes1981UKEnglish.json").write_text(json.dumps(
    {"files": [{"name": "Apr 01 1981, Financial Times, #28435, UK (en).pdf"}]}))
saved = ac.CACHE, ac.LEDGER, ac.corpus
ac.CACHE, ac.LEDGER, ac.corpus = cache, cache / "filed.jsonl", lambda s: ({}, {})
got = {d: c for d, c, _, _ in ac.unfiled(filer.PAPERS["ft"], datetime.date(1981, 4, 2))}
ac.CACHE, ac.LEDGER, ac.corpus = saved
assert (got["1981-04-01"], got["1981-04-02"], got["1980-04-01"], got["1972-04-04"]) == \
    ("no-ocr", "no-scan", "no-listing", "no-scan"), got

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
