"""Where every fetcher keeps what it downloads: ROOT/<source>/.

One root, outside the repo and never under /tmp (a reboot wipes /tmp, and
getting a scan or a borrowed book back costs hours of crawling or another
loan). Every folder a fetcher fills is named here and nowhere else;
tests/test_downloads.py fails on a path spelled anywhere else in tools/.
Derived caches a tool can rebuild from these (crops, OCR and VLM readings,
the integrity index) stay in ~/.cache. Gale's pages are the one exception:
they stay on the media disk, under its "Gale crosswords" folder
(tools/gale_inbox.py).

    python3 tools/downloads.py      # print ROOT, for shell scripts
"""
import errno
import os
from pathlib import Path

import local_config

# The media disk (the local config's media_root), at the same path on the
# host that owns it and in the bridge container (a bind mount). On the boot
# disk the downloads filled the host.
# CT_DOWNLOADS moves the whole root, for a test that must not touch the real one.
ROOT = Path(os.environ.get("CT_DOWNLOADS") or local_config.path("media_root") + "/cryptic-setter-data")
#: The whole media disk (Gale's "Gale crosswords" folder is on it, beside ROOT); ROOT itself under CT_DOWNLOADS.
MEDIA_ROOT = (ROOT if os.environ.get("CT_DOWNLOADS") or not local_config.path("media_root").strip()
              else Path(local_config.path("media_root")))
#: The media disk's "Gale crosswords" folder, beside ROOT (on the Mac, and over its share on the
#: desktop, where the local config's media_root is not the share's mount but CT_DOWNLOADS is):
#: each Gale paper's pages, <paper>/ and <paper>/Fetched/ (tools/gale_fetch.py, tools/gale_listener.py).
GALE_CROSSWORDS = ROOT.parent / "Gale crosswords"
#: What an outage of the media share raises on a path under it (the Mac's SMB server refusing the
#: session for a minute, 10-20 and 10-23: EHOSTDOWN; a dropped or stale mount: ENOTCONN, ESTALE,
#: EIO; a session the server restricts: EACCES, EPERM). media_down.
MEDIA_DOWN_ERRNOS = frozenset({errno.EHOSTDOWN, errno.ENOTCONN, errno.ESTALE, errno.EIO, errno.EACCES, errno.EPERM})


def on_media(path):
    """Whether `path` (a str, bytes or Path) is under ROOT or MEDIA_ROOT. Spelled, not
    resolved: resolving would ask the share that is down."""
    if path is None:
        return False
    p = os.path.abspath(os.fsdecode(path))
    for root in {os.path.abspath(ROOT), os.path.abspath(MEDIA_ROOT)}:
        if root != os.sep and (p == root or p.startswith(root.rstrip(os.sep) + os.sep)):
            return True
    return False


def media_down(e):
    """Whether exception `e` (or what it was raised from, its __cause__) is the media share
    not answering: an OSError of MEDIA_DOWN_ERRNOS on a path under the media root. Such a
    unit is deferred and the edition queue waits for the share (edition_queue.MediaGate);
    any other error, or one of these errnos elsewhere, stays the bug it is."""
    seen = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if (isinstance(e, OSError) and e.errno in MEDIA_DOWN_ERRNOS
                and (on_media(e.filename) or on_media(e.filename2))):
            return True
        e = e.__cause__
    return False


def _unmounted():
    """Whether ROOT is the empty folder an unmounted disk leaves. A share that does not answer
    (media_down's errnos) is no boot-disk folder: nothing can be written there either."""
    try:
        return ROOT.exists() and not (ROOT / ".on-media-disk").exists()
    except OSError as e:
        if e.errno in MEDIA_DOWN_ERRNOS:
            return False
        raise


# Only the real disk holds this file: with Media unmounted the path is an empty
# folder (Docker makes one for the mount), and filling it would fill the boot disk.
# Where the path is absent (CI, the site build) nothing can be written there,
# so importing stays harmless.
if not os.environ.get("CT_DOWNLOADS") and _unmounted():
    raise SystemExit(f"{ROOT}/.on-media-disk is missing: the media disk is not mounted")

# archive.org newspaper scans, <item>/<date>_<issue>/, and the filer's ledger
# (tools/fetch_archive_org_editions.py, tools/file_archive_org_puzzles.py).
ARCHIVE_ORG = ROOT / "archive_org_editions"
#: The ledger of the Gale Times pages tools/gale_fetch.py lays out there
#: (file_archive_org_puzzles.GALE): its own, so reading them never waits on
#: the full pass's hold on <ARCHIVE_ORG>/filed.jsonl.
GALE_LEDGER = ARCHIVE_ORG / "filed-gale.jsonl"
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
# times-for-the-times' old LiveJournal posts the WordPress blog never got,
# html/<post id>.html, and their parsed.jsonl/grids.jsonl
# (tools/file_livejournal_puzzles.py).
LIVEJOURNAL = ROOT / "livejournal"
# The Nation's puzzle pages, html/<slug>.html, and the sitemap's list of them
# (tools/fetch_nation.py).
NATION = ROOT / "nation"
# Wayback snapshots of private-eye.co.uk's crossword page, <timestamp>.html,
# and the CDX listing of them (tools/privateeye_wayback.py).
PRIVATE_EYE_WAYBACK = ROOT / "privateeye-wayback"
# tools/cross_validate.py's per-source report, <source>.jsonl.
CROSS_VALIDATE = ROOT / "cross-validate"
# The Moby Thesaurus II, <dir>/mthesaur.txt, data only (tools/fetch_moby.py);
# tools/det_synonyms.py compacts it into ~/.cache/detsolve/moby.json.gz.
MOBY = ROOT / "moby"

# Paths these folders were downloaded to before ROOT held them, each left a
# symlink to its folder here for a job started on code that still names it.
# migrate() unlinks those symlinks and moves in any real folder found there.
OLD_PATHS = {
    Path.home() / ".cache" / "archive_org_editions": ARCHIVE_ORG,
    Path.home() / ".cache" / "trove": TROVE,
    Path.home() / ".cache" / "trove-clues": TROVE_CLUES,
    Path.home() / ".cache" / "detsolve" / "moby": MOBY,
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
