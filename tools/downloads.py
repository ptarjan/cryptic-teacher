"""Where every fetcher keeps what it downloads: ROOT/<source>/.

One root, outside the repo and never under /tmp (a reboot wipes /tmp, and
getting a scan or a borrowed book back costs hours of crawling or another
loan). Every folder a fetcher fills is named here and nowhere else;
tools/test_downloads.sh fails on a path spelled anywhere else in tools/.
Derived caches a tool can rebuild from these (crops, OCR and VLM readings,
the integrity index) stay in ~/.cache. Gale's pages are the one exception:
they stay on the Mac's media disk, /Volumes/Media/Gale crosswords
(tools/gale_inbox.py).

    python3 tools/downloads.py      # print ROOT, for shell scripts
"""
import os
from pathlib import Path

# CT_DOWNLOADS moves the whole root, for a test that must not touch the real one.
ROOT = Path(os.environ.get("CT_DOWNLOADS") or Path.home() / "cryptic-setter-data")

# archive.org newspaper scans, <item>/<date>_<issue>/, and the filer's ledger
# (tools/fetch_archive_org_editions.py, tools/file_archive_org_puzzles.py).
ARCHIVE_ORG = ROOT / "archive_org_editions"
# The archive.org filer's reading of each puzzle, for tools/cross_validate.py.
ARCHIVE_ORG_SOURCE = ROOT / "archiveorg-source"
# Trove (National Library of Australia) articles, <article id>/, and the
# clue-column crops of each scan (tools/fetch_trove.py).
TROVE = ROOT / "trove"
TROVE_CLUES = ROOT / "trove-clues"
# Borrowed and public archive.org book text, <identifier>.txt
# (tools/fetch_ia_book.py, tools/acquire_book.py).
IA_BOOKS = ROOT / "ia-books"
# A book leaf that reprints a held puzzle: <held id>/<identifier>-<position>.txt.
BOOK_REPRINTS = ROOT / "book-reprints"
# tools/acquire_book.py's per-book report and public text layer.
IA_ACQUIRE = ROOT / "ia-acquire"
# The first leaves of candidate books, sampled by tools/rank_book_candidates.py.
IA_SAMPLES = ROOT / "ia-samples"
# YouTube solve-along subtitles, <channel>/subs/*.vtt (tools/ctc_transcripts.py).
YOUTUBE = ROOT / "youtube"
FT_PDF = ROOT / "ft-pdf"
GENIUS = ROOT / "genius"
LISTENER = ROOT / "listener"
ANDLIT_AZED = ROOT / "andlit-azed"
TELEGRAPH = ROOT / "telegraph-source"
TIMES_FEED = ROOT / "times-feed"
TIMES_LISTING = ROOT / "times-listing"
FIFTEENSQUARED = ROOT / "fifteensquared"
TIMESFORTHETIMES = ROOT / "timesforthetimes"
GEORGEHO = ROOT / "georgeho"
# tools/cross_validate.py's per-source report, <source>.jsonl.
CROSS_VALIDATE = ROOT / "cross-validate"

# Paths these folders were downloaded to before ROOT held them, each left a
# symlink to its folder here for a job started on code that still names it.
# migrate() unlinks those symlinks and moves in any real folder found there.
OLD_PATHS = {
    Path.home() / ".cache" / "archive_org_editions": ARCHIVE_ORG,
    Path.home() / ".cache" / "trove": TROVE,
    Path.home() / ".cache" / "trove-clues": TROVE_CLUES,
}


def migrate():
    """Retire OLD_PATHS. Run only with no corpus job alive: tools/corpus_queue.py
    calls it as it launches the pass. Returns what it did, one line each."""
    done = []
    for old, new in OLD_PATHS.items():
        if old.is_symlink():
            old.unlink()
            done.append(f"unlinked {old}")
        elif old.is_dir() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            done.append(f"moved {old} to {new}")
        elif old.exists():
            raise SystemExit(f"downloads: both {old} and {new} exist; merge them by hand")
    return done


if __name__ == "__main__":
    print(os.fspath(ROOT))
