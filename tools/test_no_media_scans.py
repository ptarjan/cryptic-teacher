#!/usr/bin/env python3
# Does no scheduled tick walk the media disk?
#
#     python3 tools/test_no_media_scans.py
#
# The media disk (tools/downloads.py's ROOT) spins; Paul
# 2026-10-14: "I don't want anything regularly scanning the spinning disk".
# The functions below run on a household schedule (every minute, every ten)
# and read what is there from tools/media_manifest.py's SSD manifests, which
# the writers append to. This fails on any listing, glob, walk or stat call
# in their bodies; reading the one file a job processes is done elsewhere.
import os
import shutil
import site
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
os.chdir(TOOLS)
sys.path.insert(0, str(TOOLS))

# Each section below ran as its own python3 in the shell, with its own
# environment and modules it stubs or patches (os.stat, io.open, ...): main()
# runs each in a fresh interpreter so nothing leaks from one to the next.

def section_scheduled(arg):
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
    # The fetcher's plan asks load_done which editions are done and not stale:
    # off archiveorg-done and the archiveorg-pages memo, not done.tsv and the dirs.
    SCHEDULED["fetch_archive_org_editions.py"] += ["load_done", "load_done_manifest", "_fold_done_row", "_fold_pages",
                                                   "unfetched", "count_titled", "_common_leaves", "_prior_leaves"]
    # corpus_queue's tick marks the filers' ledgers off the SSD stamps their writers keep.
    SCHEDULED["corpus_queue.py"] = ["ledger_marks"]
    SCHEDULED["scan_queue.py"] = ["ledger_mark", "stamped", "stamp_path"]
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


def section_trove_plan(arg):
    import io, os, sys
    import downloads, file_trove_puzzles as F
    touched = []
    mtime = (downloads.ROOT / ".manifest" / "trove-filed.jsonl").stat().st_mtime_ns
    for name in ("stat", "lstat", "listdir", "scandir"):
        real = getattr(os, name)
        setattr(os, name, (lambda real: lambda p=".", *a, **k: (touched.append(p), real(p, *a, **k))[1])(real))
    units = F.plan(puzzles=arg)
    tally = F.run(write=True, out=io.StringIO(), puzzles=arg)
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


def section_gale_listener(arg):
    import os, sys
    from pathlib import Path
    import downloads, gale_listener as g
    dl = Path(arg) / "dl"
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


def section_telegraph(arg):
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


def section_trove_solution(arg):
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
    rekeyed = F.rekey_unchanged(ledger, cache, puzzles=arg)
    under = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                    and os.fspath(p).startswith(str(cache))})
    if rekeyed != 1 or under:
        print(f"FAIL file_trove_puzzles.rekey_unchanged with the memos held: rekeyed {rekeyed}, Trove paths touched {under}")
        sys.exit(1)
    print("ok   trove_solution_ocr._articles and file_trove_puzzles.rekey_unchanged stat no Trove article dir")


def section_archive_org(arg):
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
    M.write("archiveorg-done", [])
    import edition_queue as eq, file_archive_org_puzzles as fa, fetch_archive_org_editions as fetch


    def readers():
        return (eq.fresh(["times"], ao), fa.plan(fa.TIMES, ao),
                fa.match_canberra(src, write=False, out=io.StringIO(), canberra=Path(arg) / "canberra"),
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
    # The filer's ledgers (filed*.jsonl, their locks) are another job's; done.tsv the fetcher's, whose plan reads archiveorg-done.
    media = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                    and os.fspath(p).startswith((str(ao), str(src)))
                    and not os.path.basename(os.fspath(p)).startswith("filed")})
    want = ([rel], [rel], {}, ["NewsUK1980UKEnglish/Jan 05 1980, 1"], first[4])
    got = ([u["rel"] for u in again[0][1]], [u["rel"] for u in again[1][1]], again[2], [u["rel"] for u in again[3]], again[4])
    if media or got != want or again != first:
        print(f"FAIL archive.org readers with warm memos: media paths statted {media}, got {got}, want {want}")
        sys.exit(1)
    if fa.input_hash(d) != fa._input_hash_listed(d):
        print("FAIL the edition manifest's hash is not input_hash's form")
        sys.exit(1)
    # edition_rows, asked once a queued scan a pass, merges the manifests again
    # only when a fold gains an edition, and still shows rows appended since.
    e1 = M.edition_rows()
    if M.edition_rows() is not e1:
        print("FAIL edition_rows merged the edition manifests again with nothing appended")
        sys.exit(1)
    M.record(M.ARCHIVE_EDITIONS, d, edition=rel, files="feedface", at=5)
    if M.edition_rows()[rel] != {"files": "feedface", "at": 5}:
        print(f"FAIL edition_rows missed a row appended for a known edition: {M.edition_rows()[rel]}")
        sys.exit(1)
    rel2 = "NewsUK1980UKEnglish/1980-01-12_1"
    M.record(M.GALE_EDITIONS, ao / rel2, edition=rel2, files="cafe", at=6)
    e2 = M.edition_rows()
    if e2.get(rel2) != {"files": "cafe", "at": 6} or e2[rel]["files"] != "feedface":
        print(f"FAIL edition_rows missed an edition appended to gale-editions: {e2}")
        sys.exit(1)
    # Another process's append is folded once EDITION_ROWS_FRESH lapses, not on
    # each ask: a queue pass asks once a queued unit and opens no manifest.
    import threading
    rel3 = "NewsUK1980UKEnglish/1980-01-19_1"
    with open(M.path(M.ARCHIVE_EDITIONS), "a") as f:
        f.write(json.dumps({"edition": rel3, "files": "beef", "at": 7}) + "\n")
    opened = []
    real_open = builtins.open
    builtins.open = lambda p, *a, **k: (opened.append(p), real_open(p, *a, **k))[1]
    try:
        e3 = M.edition_rows()
    finally:
        builtins.open = real_open
    if opened or rel3 in e3:
        print(f"FAIL edition_rows opened {opened} again within EDITION_ROWS_FRESH")
        sys.exit(1)
    me = threading.get_ident()
    M._EDITION_ROWS[me] = M._EDITION_ROWS[me][:5] + (time.monotonic() - M.EDITION_ROWS_FRESH,)
    if M.edition_rows().get(rel3) != {"files": "beef", "at": 7}:
        print("FAIL edition_rows missed another process's append once EDITION_ROWS_FRESH lapsed")
        sys.exit(1)
    print("ok   edition_rows is merged again only when an edition is appended, and shows rows appended since")
    print("ok   edition_queue.fresh, the archive.org filer and fetcher plans and match_canberra stat no archive.org path")


def section_load_done(arg):
    import builtins, io, json, os, sys
    import dir_cache, downloads, media_manifest as M
    import fetch_archive_org_editions as fetch
    ao = downloads.ARCHIVE_ORG
    title = lambda leaf: {"leaf": leaf, "headings": ["CROSSWORD NO 1,234"], "width": 9, "height": 9}
    # An undated item: two editions print it on leaf 30; a third has no titled page (stale).
    # A dated item holding one untitled edition, its near item printing it on leaf 4 (stale).
    eds = {("X1980", "ed_a"): [title(30)], ("X1980", "ed_b"): [title(30)], ("X1980", "ed_c"): [],
           ("per_times_the-times_1930-02-17_1", "per_times_the-times_1930-02-17_1"): [],
           ("per_times_the-times_1930-02-18_2", "per_times_the-times_1930-02-18_2"): [title(4)],
           ("Y1981", "ed_t"): [title(5)]}
    for (item, name), hits in eds.items():
        d = ao / item / fetch.slug_of(item, name)
        d.mkdir(parents=True)
        (d / "pages.json").write_text(json.dumps({"item": item, "edition": name, "leaves": 40, "crossword_pages": hits}))
    (ao / "done.tsv").write_text("".join(f"{i}\t{n}\t{fetch.DETECTOR_VERSION}\n" for i, n in eds)
                                 + f"Y1981\tgone\t{fetch.DETECTOR_VERSION}\nY1981\told\t1\n")
    M.build_archive_editions(out=io.StringIO())
    M.write(M.GALE_EDITIONS, [])
    fetch.build_done(out=io.StringIO())
    listed = fetch._load_done_listed(str(ao))  # the verdicts off the dirs, as before
    want = {k for k in eds if k[1] not in ("ed_c", "per_times_the-times_1930-02-17_1")} | {("Y1981", "gone")}
    cold = fetch.load_done(str(ao))  # fills archiveorg-pages off the disk once
    fetch.record_done(str(ao), "Y1981", "ed_new")  # the fetcher's append: no dir recorded, so done
    dir_cache._READ.clear()  # as a fresh process would
    touched = []
    real = {(os, n): getattr(os, n) for n in ("stat", "lstat", "listdir", "scandir")}
    real.update({(io, "open"): io.open, (builtins, "open"): builtins.open})
    for (mod, name), fn in real.items():
        setattr(mod, name, (lambda fn: lambda p=".", *a, **k: (touched.append(p), fn(p, *a, **k))[1])(fn))
    try:
        warm = fetch.load_done(str(ao))
    finally:
        for (mod, name), fn in real.items():
            setattr(mod, name, fn)
    media = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike))
                    and os.fspath(p).startswith(str(ao))})
    if listed != want or cold != want or warm != want | {("Y1981", "ed_new")} or media:
        print(f"FAIL fetch_archive_org_editions.load_done: listed {sorted(listed)}, cold {sorted(cold)}, "
              f"warm {sorted(warm)}, want {sorted(want)}; archive.org paths touched warm {media}")
        sys.exit(1)
    print("ok   fetch_archive_org_editions.load_done agrees with the dirs' verdicts and, warm, touches no archive.org path")


def section_corpus_queue(arg):
    import os, sys
    import downloads, corpus_queue as q, scan_queue
    for ledger in q.LEDGERS:
        with scan_queue.lock(ledger):
            pass  # the lock files exist, as a filer leaves them
    cold = q.ledger_marks()  # a ledger no writer has stamped yet: its stamp filled off the disk once
    touched = []
    real = {n: getattr(os, n) for n in ("stat", "lstat", "listdir", "scandir")}
    for name, fn in real.items():
        setattr(os, name, (lambda fn: lambda p=".", *a, **k: (touched.append(p), fn(p, *a, **k))[1])(fn))
    try:
        held, marks = q.ledger_held(), q.ledger_marks()
    finally:
        for name, fn in real.items():
            setattr(os, name, fn)
    root = str(downloads.ROOT) + os.sep
    media = sorted({os.fspath(p) for p in touched if isinstance(p, (str, os.PathLike)) and os.fspath(p).startswith(root)
                    and "/.manifest" not in os.fspath(p)})
    if media or held is not None or marks != cold:
        print(f"FAIL corpus_queue ledger_held/ledger_marks statted media paths {media} (held {held}, marks {marks} cold {cold})")
        sys.exit(1)
    ledger = downloads.ARCHIVE_ORG / "filed.jsonl"
    scan_queue.append(ledger, [{"edition": "x"}])
    st = ledger.stat()
    if q.ledger_marks()[str(ledger)] != [st.st_size, st.st_mtime_ns] or q.ledger_marks() == cold:
        print(f"FAIL a filer's append did not move corpus_queue's mark of {ledger}: {q.ledger_marks()}")
        sys.exit(1)
    print("ok   corpus_queue ledger_held and ledger_marks stat no lock, ledger, done.tsv or Trove dir on the media disk")


def prepare_trove(arg):
    import file_trove_puzzles as F, downloads, json
    h = F.input_hash(downloads.TROVE / '7')
    import media_manifest as M
    (downloads.TROVE / 'filed.jsonl').write_text(json.dumps({'article': '7', 'inputs': h, 'skip': 'test',
                                                             'readAt': '2026-10-14T00:00:00+00:00'}) + '\n')
    # The old ledger moves to the SSD once, whole, and not again.
    new = M.trove_ledger(downloads.TROVE)
    assert new == M.DIR / 'trove-filed.jsonl' and new.exists() and not (downloads.TROVE / 'filed.jsonl').exists(), new
    assert json.loads(new.read_text())['article'] == '7'



SECTIONS = {"scheduled": section_scheduled, "trove_plan": section_trove_plan, "gale_listener": section_gale_listener, "telegraph": section_telegraph, "trove_solution": section_trove_solution, "archive_org": section_archive_org, "load_done": section_load_done, "corpus_queue": section_corpus_queue, "prepare_trove": prepare_trove}


def run(section, arg="", **env):
    """One section in a fresh interpreter, as the shell's python3 was; the first failure ends the run."""
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--section", section, arg],
                       env={**os.environ, **env})
    if r.returncode:
        sys.exit(r.returncode)


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main():
    run("scheduled")

    # file_trove_puzzles plan and _run, with nothing new, stat no article dir
    # and no zone dir: each article's inputs come from the trove-inputs manifest
    # (input_hash), its list from trove-titles.
    t = Path(tempfile.mkdtemp())
    t2 = Path(tempfile.mkdtemp())
    try:
        (t / "puzzles").mkdir()
        write(t / "dl/trove/7/meta.json", '{"title": "01 Jun 1972 - Crossword"}\n')
        write(t / "dl/trove/7/ocr.txt", "clues\n")
        write(t / "dl/trove-clues/7/zone0.png", "")
        write(t / "dl/.manifest/trove-titles.jsonl", '{"article": "7", "title": "01 Jun 1972 - Crossword"}\n')
        write(t / "dl/.manifest/trove-zones.jsonl", '{"article": "7", "readings": true}\n')
        for m in ("trove-titles", "trove-zones"):
            write(t / f"dl/.manifest/{m}.complete", "{}\n")
        env = {"CT_DOWNLOADS": str(t / "dl"), "VLM_READER_URL": ""}
        # The first run after this lands takes each article's inputs off the disk once.
        run("prepare_trove", **env)
        run("trove_plan", str(t / "puzzles"), **env)

        # gale_listener.wanted (gale_fetch plan, each pass): once the memos are warm it
        # touches nothing under the downloads root but the SSD manifests.
        run("gale_listener", str(t), **env)

        # fetch_telegraph.repeated (blog:telegraph, every 3 h): the cached calendars'
        # rows come from the telegraph-calendar manifest, not a glob of the calendar folder.
        run("telegraph", str(t), **env)

        # trove_solution_ocr._articles (every Trove read unit and --fill) and
        # file_trove_puzzles.rekey_unchanged (every ledger_upkeep slice), once the
        # article's files and titles are in the SSD memos, list and stat nothing
        # under the Trove folders.
        (t2 / "puzzles").mkdir()
        (t2 / "home").mkdir()
        write(t2 / "dl/trove/8/meta.json", '{"title": "SOLUTION - Trove"}\n')
        write(t2 / "dl/trove/8/ocr.txt", "Monday 5 June 1972\nclues\n")
        write(t2 / "dl/trove/8/grid.jpg", "x\n")
        write(t2 / "dl/trove-clues/8/zone0.png", "")
        write(t2 / "dl/.manifest/trove-titles.jsonl", '{"article": "8", "title": "SOLUTION - Trove"}\n')
        write(t2 / "dl/.manifest/trove-titles.complete", "{}\n")
        # From here on the shell's HOME was the scratch one, its user site the real one.
        env.update(PYTHONUSERBASE=site.getuserbase(), HOME=str(t2 / "home"))
        run("trove_solution", str(t2 / "puzzles"), **{**env, "CT_DOWNLOADS": str(t2 / "dl")})

        # The archive.org side: edition_queue.fresh (every 30 s), the filer's plan
        # (each replan), match_canberra (each OCR pass) and the fetcher's plan, their
        # memos warm, stat, list and glob nothing under the archive.org folders: the
        # editions, their hashes and laid-out times come off the edition manifests,
        # the readings off archiveorg-source and its SSD store, the group listings
        # and item editions off ia-groups and ia-items.
        (t / "canberra").mkdir()
        run("archive_org", str(t), **{**env, "CT_DOWNLOADS": str(t / "ao")})

        # fetch_archive_org_editions.load_done (the fetcher's plan, each replan): the
        # done editions and their stale verdicts come off archiveorg-done and the
        # archiveorg-pages memo; it agrees with the verdicts worked out off the dirs,
        # and warm it opens, lists and stats nothing under the archive.org root.
        run("load_done", "", **{**env, "CT_DOWNLOADS": str(t / "ld"), "XDG_CACHE_HOME": str(t / "ld-cache")})

        # corpus_queue's checks (every tick of the corpus queue) look for a filer's
        # ledger lock on the SSD (scan_queue.lock_path), take the fetch marks off the
        # SSD manifests and the archive.org ledgers' marks off the SSD stamps their
        # writers keep (scan_queue.stamp): of the media disk they stat nothing once
        # the stamps exist, and a writer's append moves the mark.
        (t / "cq/.manifest").mkdir(parents=True)
        write(t / "cq/archive_org_editions/filed.jsonl", "")
        run("corpus_queue", "", **{**env, "CT_DOWNLOADS": str(t / "cq"), "HOME": str(t / "cq-home")})
    finally:
        shutil.rmtree(t, ignore_errors=True)
        shutil.rmtree(t2, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--section":
        SECTIONS[sys.argv[2]](sys.argv[3])
    else:
        main()
