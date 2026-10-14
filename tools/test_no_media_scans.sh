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
    # cross_validate.py all --new (after every filing unit) asks every adapter
    # its ids; the writers append to the folder manifests.
    "cross_validate.py": ["Independent.served", "FT.ids", "ArchiveOrg.ids", "ListenerReport.ids",
                          "Telegraph.ids", "Globe.fetch_one"],
    # gale_inbox sync's checklist, every minute: the scanned editions.
    "archive_coverage.py": ["scans", "unfiled", "fetched_editions"],
    # gale_fetch.py run() asks this every pass of its loop.
    "gale_fetch.py": ["have_docs"],
    # edition_queue plan (every corpus slice) dates each due Trove article.
    "file_trove_puzzles.py": ["article_date", "stamp_cause", "zones_held", "plan", "article_dirs", "input_hash",
                              "trove_inputs", "_fold_input"],
    # edition_queue's trove fetch slice plans off the caches.
    "fetch_trove.py": ["plan", "pending_zones", "fetched_ids", "zoned_ids", "_in"],
    # coverage.py daily (daily_update.sh): the FT PDFs fetched.
    "coverage.py": ["ft_pdf_rows", "trove_articles", "trove_dates"],
    "privateeye_wayback.py": ["lost", "summary", "summary_path", "summary_version"],
    # progress_record.py record (nightly): the read queue's size.
    "edition_backlog.py": ["_editions", "trove_counts"],
}
#: {file: [function]} that may not run a command on the host either (an ssh
#: `ls` of the Gale folders is a listing of the media disk too).
NO_SSH = {"gale_fetch.py": ["have_docs"]}
SCANS = {"glob", "rglob", "iterdir", "listdir", "scandir", "walk", "stat", "exists", "is_file", "is_dir"}
#: Paths on the SSD those functions may stat: gale_fetch's log in ~/.cache,
#: the repo's pins file.
SSD = {"FETCHED", "pins_path"}
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
