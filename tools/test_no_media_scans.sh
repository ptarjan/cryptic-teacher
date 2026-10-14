#!/bin/bash
# Does no scheduled tick walk the media disk?
#
#     bash tools/test_no_media_scans.sh
#
# The media disk (tools/downloads.py's ROOT, /Volumes/Media) spins; Paul
# 2026-10-14: "I don't want anything regularly scanning the spinning disk".
# The functions below run on a household schedule (every minute, every ten)
# and read what is there from tools/media_manifest.py's SSD manifests, which
# the writers append to. This fails on any listing, glob, walk or stat call
# in their bodies; reading the one file a job processes is done elsewhere.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import ast
import sys

#: {file: [function]} each scheduled tick runs (household-plugins/*/plugin.toml).
SCHEDULED = {
    # cryptic-gale-inbox, every minute: gale_inbox.py sync.
    "gale_inbox.py": ["sync", "_sync_locked", "kick", "fresh_unread", "staged_matches", "other_wanted",
                      "editions", "checklist"],
    # cryptic-books, every ten minutes: book_queue.py --next / --reread.
    "book_queue.py": ["text_of", "queue", "rereads"],
    "media_manifest.py": ["rows", "latest", "unread", "advance", "parse_new", "posts", "post_ids",
                          "comment_keys", "record_post", "record_comments",
                          "on_media", "record_file", "folder_files", "trove_hits"],
    # daily_update.sh's blog units (every 10 min / 3 h / nightly): the
    # fetchers append to the posts manifests, readers ask the manifests.
    "fetch_wp_blog.py": ["cached_ids", "fetch_category", "fetch_comments"],
    "fetch_times_listing.py": ["paper_dates", "capture_row"],
    "corroborate.py": ["times_listing", "_fifteensquared_index"],
    "post_index.py": ["entries", "by_link"],
    "fetch_fifteensquared.py": ["cached_post_ids", "post_categories", "category_post_files",
                                "cached_comment_ids", "fetch_posts", "fetch_comments"],
    "genius_puzzles.py": ["blog_posts", "have_file", "fetch", "file", "image_paths"],
    "andlit_azed.py": ["cached", "fetch"],
    "blog_facts.py": ["extract", "inputs_digest"],
    "blog_comment_difficulty.py": ["months", "comments_by_post", "post_ids"],
    # The parser those units run: posts from the manifest, past a cursor.
    "parse_timesforthetimes.py": ["run"],
    "parse_bigdave44.py": ["read_posts", "run"],
    "ft_puzzles.py": ["parse"],
    "azed_puzzles.py": ["parse"],
    # cross_validate.py all --new (after every filing unit) asks every adapter
    # its ids; the writers append to the folder manifests.
    "cross_validate.py": ["Independent.served", "FT.ids", "ArchiveOrg.ids", "ListenerReport.ids",
                          "Telegraph.ids", "Globe.fetch_one"],
    # gale_inbox sync's checklist, every minute: the scanned editions.
    "archive_coverage.py": ["scans", "unfiled", "fetched_editions"],
    # gale_fetch plan asks gale_listener.wanted: year pages, readings and the
    # ledger from the listener-* manifests.
    "gale_listener.py": ["wanted", "index", "_year_rows", "to_save", "saved_numbers", "solutions",
                         "report_lookups", "reading_numbers", "ledger_numbers"],
    # gale_fetch.py run() asks this every pass of its loop.
    "gale_fetch.py": ["have_docs"],
    # edition_queue plan (every corpus slice) dates each due Trove article.
    "file_trove_puzzles.py": ["article_date", "stamp_cause", "zones_held", "plan", "article_dirs", "input_hash",
                              "trove_inputs", "_fold_input"],
    # edition_queue's trove fetch slice plans off the caches.
    # blog:telegraph (every 3 h) asks served() which numbers the calendars repeat.
    "fetch_telegraph.py": ["served", "repeated", "held_calendar_rows", "record_calendar"],
    "fetch_trove.py": ["plan", "pending_zones", "fetched_ids", "zoned_ids", "_in"],
    # coverage.py daily (daily_update.sh): the FT PDFs fetched.
    "coverage.py": ["ft_pdf_rows", "trove_articles", "trove_dates"],
    "privateeye_wayback.py": ["lost", "summary", "summary_path", "summary_version"],
    # progress_record.py record (nightly): the read queue's size.
    "edition_backlog.py": ["_editions", "trove_counts"],
    "progress_record.py": ["backlog"],
    # edition_queue run, every 30 s: the editions just laid out, off the
    # edition manifests (media_manifest.edition_rows).
    "edition_queue.py": ["fresh"],
    # edition_queue plan (each replan) lists, keys and dates the archive.org
    # editions; each OCR pass matches the canberra files to the Times readings.
    "file_archive_org_puzzles.py": ["plan", "_plan_paper", "edition_dirs", "input_hash", "staged_at",
                                    "match_canberra", "source_readings"],
    # edition_queue's archive.org fetch slice plans off ia-groups and ia-items.
    "fetch_archive_org_editions.py": ["plan", "plan_listings", "_per_group", "held_rows", "_fold_key"],
}
SCHEDULED["media_manifest.py"] += ["edition_rows", "_fold_edition", "edition_rel"]
#: {file: [function]} that may not run a command on the host either (an ssh
#: `ls` of the Gale folders is a listing of the media disk too).
NO_SSH = {"gale_fetch.py": ["have_docs"]}
SCANS = {"glob", "rglob", "iterdir", "listdir", "scandir", "walk", "stat", "exists", "is_file", "is_dir"}
#: Paths on the SSD those functions may stat: gale_fetch's log in ~/.cache,
#: the repo's pins file, the repo's canberra puzzles (match_canberra).
SSD = {"FETCHED", "pins_path", "canberra"}
#: Calls naming a file in the repo (on the SSD), which may be stat-ed.
SSD_CALLS = {"puzzle_path"}
bad = []
for f, names in SCHEDULED.items():
    tree = ast.parse(open(f).read())
    defs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    defs.update({f"{c.name}.{n.name}": n for c in tree.body if isinstance(c, ast.ClassDef)
                 for n in c.body if isinstance(n, ast.FunctionDef)})
    for name in names:
        if name not in defs:
            bad.append(f"{f}: {name} is gone; update SCHEDULED")
            continue
        for node in ast.walk(defs[name]):
            if isinstance(node, ast.Call):
                fn = node.func
                called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                on = getattr(fn, "value", None)
                ssd = (isinstance(on, ast.Name) and on.id in SSD) or (
                    isinstance(on, ast.Call) and getattr(on.func, "id", "") in SSD_CALLS)
                if called in SCANS and not ssd:
                    bad.append(f"{f}:{node.lineno}: {name} calls {called}()")
                if called in ("ssh", "run", "check_output", "Popen") and name in NO_SSH.get(f, ()):
                    bad.append(f"{f}:{node.lineno}: {name} runs a command ({called}()) on the host")
# fetch_fifteensquared.py runs at every daily ft/azed/genius unit: its cache
# report reads every post, so only --status runs it.
tree = ast.parse(open("fetch_fifteensquared.py").read())
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
for stmt in main.body:
    guarded = isinstance(stmt, ast.If) and "status" in ast.unparse(stmt.test)
    if not guarded and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "status" for n in ast.walk(stmt)):
        bad.append(f"fetch_fifteensquared.py:{stmt.lineno}: main runs status() without --status")
if bad:
    print("A scheduled tick reads tools/media_manifest.py, not the media disk:\n" + "\n".join(bad))
    sys.exit(1)
print(f"ok: {sum(map(len, SCHEDULED.values()))} scheduled functions list, glob and stat nothing")
PY

# file_trove_puzzles plan and _run, with nothing new, stat no article dir
# and no zone dir: each article's inputs come from the trove-inputs manifest
# (input_hash), its list from trove-titles.
t=$(mktemp -d)
trap 'rm -rf "$t"' EXIT
mkdir -p "$t/dl/trove/7" "$t/dl/trove-clues/7" "$t/dl/.manifest" "$t/puzzles"
echo '{"title": "01 Jun 1972 - Crossword"}' > "$t/dl/trove/7/meta.json"
echo clues > "$t/dl/trove/7/ocr.txt"
: > "$t/dl/trove-clues/7/zone0.png"
echo '{"article": "7", "title": "01 Jun 1972 - Crossword"}' > "$t/dl/.manifest/trove-titles.jsonl"
echo '{"article": "7", "readings": true}' > "$t/dl/.manifest/trove-zones.jsonl"
for m in trove-titles trove-zones; do echo '{}' > "$t/dl/.manifest/$m.complete"; done
export CT_DOWNLOADS="$t/dl" VLM_READER_URL=
# The first run after this lands takes each article's inputs off the disk once.
python3 -c "
import file_trove_puzzles as F, downloads, json
h = F.input_hash(downloads.TROVE / '7')
import media_manifest as M
(downloads.TROVE / 'filed.jsonl').write_text(json.dumps({'article': '7', 'inputs': h, 'skip': 'test',
                                                         'readAt': '2026-10-14T00:00:00+00:00'}) + '\n')
# The old ledger moves to the SSD once, whole, and not again.
new = M.trove_ledger(downloads.TROVE)
assert new == M.DIR / 'trove-filed.jsonl' and new.exists() and not (downloads.TROVE / 'filed.jsonl').exists(), new
assert json.loads(new.read_text())['article'] == '7'"
python3 - "$t/puzzles" <<'PY'
import io, os, sys
import downloads, file_trove_puzzles as F
touched = []
mtime = (downloads.ROOT / ".manifest" / "trove-filed.jsonl").stat().st_mtime_ns
for name in ("stat", "lstat", "listdir", "scandir"):
    real = getattr(os, name)
    setattr(os, name, (lambda real: lambda p=".", *a, **k: (touched.append(p), real(p, *a, **k))[1])(real))
units = F.plan(puzzles=sys.argv[1])
tally = F.run(write=True, out=io.StringIO(), puzzles=sys.argv[1])
# The ledger, its lock and the folder holding them (scan_queue.lock makes it) aside.
media = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                and os.fspath(p).startswith(str(downloads.ROOT)) and "/.manifest/" not in os.fspath(p)
                and os.fspath(p) not in (str(downloads.TROVE), str(downloads.ROOT / ".manifest")) and not os.path.basename(p).startswith("filed.")})
# Nothing under downloads.TROVE at all (not the folder, not a ledger or lock), and the SSD ledger unwritten.
trove = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                and os.fspath(p).startswith(str(downloads.TROVE) + os.sep)
                and os.path.basename(os.fspath(p)) in ("filed.jsonl", "filed.lock", "filed.tmp")})
if trove or (downloads.ROOT / ".manifest" / "trove-filed.jsonl").stat().st_mtime_ns != mtime:
    print(f"FAIL file_trove_puzzles with nothing new touched the Trove ledger paths {trove} or rewrote the SSD ledger")
    sys.exit(1)
if units or tally != {"skipped: test": 1} or media:
    print(f"FAIL file_trove_puzzles plan/_run with nothing new: units {units}, tally {tally}, media paths statted {media}")
    sys.exit(1)
print("ok   file_trove_puzzles plan and _run with nothing new stat no Trove article or zone dir")
PY

# gale_listener.wanted (gale_fetch plan, each pass): once the memos are warm it
# touches nothing under the downloads root but the SSD manifests.
python3 - "$t" <<'PY'
import os, sys
from pathlib import Path
import downloads, gale_listener as g
dl = Path(sys.argv[1]) / "dl"
years, store = g.YEARS, g.STORE
years.mkdir(parents=True)
store.mkdir(parents=True)
for y in range(g.FIRST_YEAR, g.LAST_ISSUE.year + 1):
    (years / f"Y{y}.html").write_text(f'<td class="num">{y}</td><td class="title">T</td><td class="setter">S</td><td class="date">3 Jan</td>')
(store / "listener-1930.json").write_text('{"number": 1930}')
(store / "ledger.jsonl").write_text('{"sha": "a", "number": 1931, "reports": [1932]}\n')
first = g.wanted()  # cold: reads the disk once, fills the memos
touched = []
for name in ("stat", "lstat", "listdir", "scandir"):
    real = getattr(os, name)
    setattr(os, name, (lambda real: lambda p=".", *a, **k: (touched.append(p), real(p, *a, **k))[1])(real))
again = g.wanted()
media = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                and os.fspath(p).startswith(str(downloads.ROOT)) and "/.manifest/" not in os.fspath(p)})
if again != first or not first or media:
    print(f"FAIL gale_listener.wanted warm: {len(first)} then {len(again)} rows, media paths touched {media[:5]} ({len(media)})")
    sys.exit(1)
print("ok   gale_listener.wanted touches nothing on the media disk once its memos are warm")
PY

# fetch_telegraph.repeated (blog:telegraph, every 3 h): the cached calendars'
# rows come from the telegraph-calendar manifest, not a glob of the calendar folder.
python3 - "$t" <<'PY'
import json, os, sys
import downloads, fetch_telegraph as ft
cal = ft.CACHE / "calendar"
cal.mkdir(parents=True)
(cal / "2016.json").write_text(json.dumps({"calendar": {"cryptic-crossword-1": {"2016-04": {"18": "cryptic-crossword-37490", "19": "cryptic-crossword-37491"}}},
                                          "numbers": {"cryptic-crossword-1": {"2016-04": {"18": "28085", "19": "28085"}}}}))
first = ft.repeated()  # cold: reads the folder once, fills the manifest
ft._repeated.clear()
touched = []
for name in ("stat", "lstat", "listdir", "scandir"):
    real = getattr(os, name)
    setattr(os, name, (lambda real: lambda p=".", *a, **k: (touched.append(p), real(p, *a, **k))[1])(real))
again = ft.repeated()
media = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                and os.fspath(p).startswith(str(downloads.ROOT)) and "/.manifest/" not in os.fspath(p)})
if again != first or not first or media:
    print(f"FAIL fetch_telegraph.repeated warm: {first} then {again}, media paths touched {media[:5]} ({len(media)})")
    sys.exit(1)
print("ok   fetch_telegraph.repeated touches nothing on the media disk once its manifest is warm")
PY

# trove_solution_ocr._articles (every Trove read unit and --fill) and
# file_trove_puzzles.rekey_unchanged (every ledger_upkeep slice), once the
# article's files and titles are in the SSD memos, list and stat nothing
# under the Trove folders.
t2=$(mktemp -d)
trap 'rm -rf "$t" "$t2"' EXIT
mkdir -p "$t2/dl/trove/8" "$t2/dl/trove-clues/8" "$t2/dl/.manifest" "$t2/puzzles" "$t2/home"
echo '{"title": "SOLUTION - Trove"}' > "$t2/dl/trove/8/meta.json"
printf 'Monday 5 June 1972\nclues\n' > "$t2/dl/trove/8/ocr.txt"
echo x > "$t2/dl/trove/8/grid.jpg"
: > "$t2/dl/trove-clues/8/zone0.png"
echo '{"article": "8", "title": "SOLUTION - Trove"}' > "$t2/dl/.manifest/trove-titles.jsonl"
echo '{}' > "$t2/dl/.manifest/trove-titles.complete"
export PYTHONUSERBASE="$(python3 -m site --user-base)" HOME="$t2/home"
CT_DOWNLOADS="$t2/dl" VLM_READER_URL= python3 - "$t2/puzzles" <<'PY'
import json, os, sys
import downloads, file_trove_puzzles as F, media_manifest as M, scan_queue, trove_solution_ocr as T
cache = downloads.TROVE
# Cold: the first run takes the article's files off the disk once into trove-inputs and keeps its day.
F.input_hash(cache / "8")
cold = T._articles(cache)
assert [(str(d), s) for _, d, s in cold] == [(str(cache / "8"), True)], cold
T._ARTICLES.clear()
ledger = M.trove_ledger(cache)
ledger.write_text(json.dumps({"article": "8", "inputs": "old", "skip": "test", "readAt": "2099-01-01T00:00:00+00:00"}) + "\n")
touched = []
for name in ("stat", "lstat", "listdir", "scandir"):
    real = getattr(os, name)
    setattr(os, name, (lambda real: lambda p=".", *a, **k: (touched.append(p), real(p, *a, **k))[1])(real))
warm = T._articles(cache)
touched_articles = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                           and os.fspath(p).startswith(str(cache))})
if [r[1:] for r in warm] != [r[1:] for r in cold] or touched_articles:
    print(f"FAIL trove_solution_ocr._articles with the memos held: warm {warm}, Trove paths touched {touched_articles}")
    sys.exit(1)
del touched[:]
rekeyed = F.rekey_unchanged(ledger, cache, puzzles=sys.argv[1])
under = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                and os.fspath(p).startswith(str(cache))})
if rekeyed != 1 or under:
    print(f"FAIL file_trove_puzzles.rekey_unchanged with the memos held: rekeyed {rekeyed}, Trove paths touched {under}")
    sys.exit(1)
print("ok   trove_solution_ocr._articles and file_trove_puzzles.rekey_unchanged stat no Trove article dir")
PY

# The archive.org side: edition_queue.fresh (every 30 s), the filer's plan
# (each replan), match_canberra (each OCR pass) and the fetcher's plan, their
# memos warm, stat, list and glob nothing under the archive.org folders: the
# editions, their hashes and laid-out times come off the edition manifests,
# the readings off archiveorg-source and its SSD store, the group listings
# and item editions off ia-groups and ia-items.
mkdir -p "$t/canberra"
CT_DOWNLOADS="$t/ao" VLM_READER_URL= python3 - "$t" <<'PY'
import io, json, os, sys, time
from pathlib import Path
import downloads, media_manifest as M
ao, src = downloads.ARCHIVE_ORG, downloads.ARCHIVE_ORG_SOURCE
rel = "NewsUK1980UKEnglish/1980-01-05_1"
d = ao / rel
d.mkdir(parents=True)
(d / "pages.json").write_text(json.dumps({"item": "NewsUK1980UKEnglish", "date": "1980-01-05", "crossword_pages": []}))
src.mkdir(parents=True)
(src / "times-1.json").write_text(json.dumps({"id": "times-1", "date": "1980-01-05", "dimensions": {"cols": 1, "rows": 1},
    "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0}, "length": 1, "clue": {"text": "a b c d"}}]}))
(ao / "items").mkdir()
(ao / "items" / "NewsUK1980UKEnglish.json").write_text(json.dumps({"files": [{"name": "Jan 05 1980, 1_djvu.txt"}]}))
(ao / "items" / "_group_times.json").write_text(json.dumps([{"identifier": "NewsUK1980UKEnglish", "title": "The Times , 1980"}]))
# The manifests as their one-off builds left them, from before rows held a hash or names.
M.write(M.ARCHIVE_EDITIONS, [{"edition": rel, "at": time.time()}])
M.write(M.GALE_EDITIONS, [])
M.write("archiveorg-source", [{"key": "times-1.json", "at": 1}])
M.write("ia-items", [{"key": "NewsUK1980UKEnglish", "editions": {}, "at": 1}])
import edition_queue as eq, file_archive_org_puzzles as fa, fetch_archive_org_editions as fetch


def readers():
    return (eq.fresh(["times"], ao), fa.plan(fa.TIMES, ao),
            fa.match_canberra(src, write=False, out=io.StringIO(), canberra=Path(sys.argv[1]) / "canberra"),
            fetch.plan(str(ao), ["times"]), fa.staged_at(d))


first = readers()  # fills each memo off the disk once
touched = []
import builtins
real = {(os, n): getattr(os, n) for n in ("stat", "lstat", "listdir", "scandir")}
real.update({(io, "open"): io.open, (builtins, "open"): builtins.open})  # a file opened again is a read of the disk too
for (mod, name), fn in real.items():
    setattr(mod, name, (lambda fn: lambda p=".", *a, **k: (touched.append(p), fn(p, *a, **k))[1])(fn))
try:
    again = readers()
finally:
    for (mod, name), fn in real.items():
        setattr(mod, name, fn)
# The filer's ledgers (filed*.jsonl, their locks) are another job's; done.tsv the fetcher's.
media = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                and os.fspath(p).startswith((str(ao), str(src)))
                and not os.path.basename(os.fspath(p)).startswith(("filed", "done.tsv"))})
want = ([rel], [rel], {}, ["NewsUK1980UKEnglish/Jan 05 1980, 1"], first[4])
got = ([u["rel"] for u in again[0][1]], [u["rel"] for u in again[1][1]], again[2], [u["rel"] for u in again[3]], again[4])
if media or got != want or again != first:
    print(f"FAIL archive.org readers with warm memos: media paths statted {media}, got {got}, want {want}")
    sys.exit(1)
if fa.input_hash(d) != fa._input_hash_listed(d):
    print("FAIL the edition manifest's hash is not input_hash's form")
    sys.exit(1)
print("ok   edition_queue.fresh, the archive.org filer and fetcher plans and match_canberra stat no archive.org path")
PY
