# Repository layout

Where the repo keeps things: `tools/` holds the scripts, `tests/` the tests, `docs/` the
prose, `puzzles/` and `clues_only/` the data, and `.github/workflows/` the CI.
For any one file, read its own docstring or header comment.

## Downloaded source material

Everything a fetcher downloads lives outside the repo under one root on a
data disk (set in `tools/downloads.py` or by `CT_DOWNLOADS`; `python3
tools/downloads.py` prints it), one folder per source. `tools/downloads.py` is
the only place a folder is named, and `tests/test_downloads.py` fails on a
download path spelled anywhere else.

| Folder | What is in it | Filled by |
|---|---|---|
| archive_org_editions/ | archive.org newspaper scans and the filer's ledger | `tools/fetch_archive_org_editions.py` |
| archiveorg-source/ | the archive.org filer's reading of each puzzle | `tools/file_archive_org_puzzles.py` |
| trove/, trove-clues/ | Trove articles and the clue-column crops of each scan | `tools/fetch_trove.py` |
| ia-books/, book-reprints/ | borrowed and public archive.org book text; reprinted leaves | `tools/fetch_ia_book.py`, `tools/acquire_book.py` |
| ia-acquire/, ia-samples/ | per-book acquisition reports; candidate books' first leaves | `tools/acquire_book.py`, `tools/rank_book_candidates.py` |
| ft-pdf/, genius/, listener/, andlit-azed/ | publisher PDFs and archive pages | the series' own `*_puzzles.py` |
| NAME-source/ | each cross-checked source's cache (Guardian, Telegraph, Independent, Globe) | `tools/cross_validate.py`, `tools/fetch_telegraph.py` |
| times-feed/, times-listing/ | the Times puzzle feed and its Wayback listing | `tools/fetch_times_feed.py`, `tools/fetch_times_listing.py` |
| fifteensquared/, timesforthetimes/, bigdave44/, georgeho/ | solving blogs' posts and comments | `tools/fetch_fifteensquared.py`, `tools/fetch_wp_blog.py` |
| youtube/CHANNEL/subs/ | solve-along video subtitles | `tools/ctc_transcripts.py` reads them |
| cross-validate/ | per-source cross-validation reports | `tools/cross_validate.py` |
| probes/ | pages saved by hand while probing a new source; nothing reads them | by hand |

Two things stay elsewhere: Gale's pages, in their own folder on the same
data disk (`tools/gale_inbox.py`), and caches a tool
rebuilds from these (crops, OCR and VLM readings, ledgers of job state) in
`~/.cache`.
