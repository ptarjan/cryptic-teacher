#!/usr/bin/env python3
# Does planning answer from manifests and the pickle, not the media disk
# (Paul: "Never scan over samba")? reprint_key lists and stats a folder per
# puzzle number off media_manifest's book-reprints (built once, appended by
# book_queue.save_reprint), and page_url reads an edition's pages.json once
# while its files stand (pages_facts, kept by save_likely).
#
#     python3 tests/test_plan_off_samba.py
#
# Everything under a temp downloads root; nothing outside it is touched.
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
os.chdir(TOOLS)
sys.path.insert(0, str(TOOLS))
tmp = Path(tempfile.mkdtemp())
os.environ["CT_DOWNLOADS"] = str(tmp)
os.environ.pop("CT_MANIFEST", None)

import book_queue
import downloads
import file_archive_org_puzzles as f
import media_manifest

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

def disk_key(names):
    """reprint_key's hash as it was made when each reading was stat'ed off the disk."""
    h = hashlib.sha256()
    for pid, name in names:
        h.update(f"{pid}/{name}:{(downloads.BOOK_REPRINTS / pid / name).stat().st_size}".encode())
    h.update(f"book vote {f.BOOK_VOTE}".encode())
    return h.hexdigest()[:16]

check("the media root is the temp dir", True, media_manifest.on_media(book_queue.REPRINT_DIR))
for pid, name, text in (("ftcryptic-7", "b-2.txt", "ACROSS\n1 a (3)\n"), ("ftcryptic-7", "a-1.txt", "ACROSS\n1 b (4)\n"),
                        ("ftcryptic-8", "a-1.txt", "ACROSS\n1 c (5)\n")):
    (downloads.BOOK_REPRINTS / pid).mkdir(parents=True, exist_ok=True)
    (downloads.BOOK_REPRINTS / pid / name).write_text(text)
want = disk_key([("ftcryptic-7", "a-1.txt"), ("ftcryptic-7", "b-2.txt"), ("ftcryptic-8", "a-1.txt")])
check("a puzzle with no reading has no reprint key", "", f.reprint_key([9], "ftcryptic"))
check("the key is the readings' names and sizes, as when listed off the disk", want, f.reprint_key([7, 8], "ftcryptic"))
check("the manifest holds each reading once, built once", True, media_manifest.complete(media_manifest.BOOK_REPRINTS))

# With the manifest built, a plan lists and stats no reprint folder.
touched = []
orig = book_queue.reprint_readings
book_queue.reprint_readings = lambda *a, **k: touched.append(a) or orig(*a, **k)
orig_stat = Path.stat
Path.stat = lambda self, *a, **k: (touched.append(str(self)) if "book-reprints" in str(self) else None) or orig_stat(self, *a, **k)
try:
    check("a replan keys the same", want, f.reprint_key([7, 8], "ftcryptic"))
    f.reprint_key(list(range(100, 300)), "ftcryptic")
finally:
    book_queue.reprint_readings = orig
    Path.stat = orig_stat
check("... and asks the disk for none of 200 puzzles' folders", [], touched)

# A reading the queue itself saves reaches the manifest, so the key moves.
book_queue.save_reprint("ftcryptic-8", "c", 3, [[1, 5, "s", {"clue": "new", "enumeration": "5"}]], [])
media_manifest._BOOK_REPRINTS.clear()
check("a saved reading makes the edition's reprint key move", True, f.reprint_key([8], "ftcryptic") != "")
check("... to what a listing of the disk gives", disk_key([("ftcryptic-8", "a-1.txt"), ("ftcryptic-8", "c-3.txt")]),
      f.reprint_key([8], "ftcryptic"))

# pages.json is read once while the edition's files stand.
ed = downloads.ARCHIVE_ORG / "GaleTimes1950UKEnglish" / "1950-01-02"
ed.mkdir(parents=True)
(ed / "pages.json").write_text(json.dumps({"url": "https://gale.example/p1", "edition": "x"}))
media_manifest.write(media_manifest.GALE_EDITIONS, [])  # edition_rows wants both manifests built
media_manifest.record_edition(ed)
reads = []
orig_read = Path.read_text
Path.read_text = lambda self, *a, **k: (reads.append(self.name) if self.name == "pages.json" else None) or orig_read(self, *a, **k)
try:
    found = {"item": "GaleTimes1950UKEnglish"}
    got = [f.page_url(ed, found, 3) for _ in range(5)] + [f.edition_of(ed, found)]
finally:
    Path.read_text = orig_read
check("page_url answers pages.json's url", ["https://gale.example/p1"] * 5, got[:5])
check("... and 6 asks read pages.json once", 1, len(reads))
check("the answer is kept for the next process", True, str(ed) in f._PAGES_FACTS)

# A held file's suspect verdict (complete() over every clue) is kept for the next process while its stat,
# the code and the lexicon stand; under another version it is judged again.
held = tmp / "held-99999.json"
held.write_text(json.dumps({"source": {"acquiredBy": f.TOOL}, "entries": [
    {"number": 1, "direction": "across", "clue": {"text": "A c4t sat", "enumeration": "3"}, "solution": ""},
    {"number": 2, "direction": "down", "clue": {"text": "Hound", "enumeration": "3"}, "solution": "CUR"}]}))
f._HELD_PATH["times", 99999] = held
want = f.suspect_held_file("times", 99999)
check("a held file's verdict is kept in this process", True, held in f._SUSPECT)
f._PAGES_FACTS.clear()
f.save_likely(tmp / "likely.pickle")
f._SUSPECT.clear()
f.load_likely(tmp / "likely.pickle")
orig_complete = f.complete
f.complete = lambda *a, **k: (_ for _ in ()).throw(AssertionError("judged again"))
try:
    check("... and the next process takes it without judging the file again", want, f.suspect_held_file("times", 99999))
finally:
    f.complete = orig_complete
f._SUSPECT.clear()
f._SUSPECT_VERSION[:] = ["other code"]
f.load_likely(tmp / "likely.pickle")
check("... but not under other code or another lexicon", False, held in f._SUSPECT)

print("test_plan_off_samba: " + ("failed" if fails else "all passed"))
sys.exit(1 if fails else 0)
