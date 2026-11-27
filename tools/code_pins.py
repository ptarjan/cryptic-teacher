"""Code keys that stand as the key they replaced.

A code key (tools/code_reach.py) moves with any edit to the code it covers, and what was read under
the old key is then read again. An edit that moves no result (memory held, a cache, a log line) is
pinned here instead: the key of the code after the edit, as computed, to the key the results stand
under. file_gale_listener.code_key answers the pinned key; the next edit computes a key no pin names,
and moves as ever. This module is left out of the reach of the keys it pins (a pin cannot be part of
the code whose key it names). The archive.org scans' keys have their own pins
(file_archive_org_puzzles.CORPUS_KEYS)."""

#: {the key as computed: the key it stands as}, each with the edit that moved it and what showed
#: that edit moves no result.
STANDS = {
    # ocr_clues.read_words held its upscaled image as planes (upscaled_planes), and file_gale_listener.code_key
    # took these pins: the same image bytes, cache name, reduction and words (tests/test_read_words_planes.py).
    "e4203a9eabd54183": "d585db93f7b3d46e",  # listener_grid's GRID_CODE: ~11,700 Listener pages' grids
    "bb25f3e31f03d90a": "445be7454385737b",  # file_gale_listener's join_key
    # listener_gaps.fill_columns reads "(23) text" columns and takes a clue in a countless list by the page's own
    # words (FILL_FIX): only the pages of tools/data/listener_fill_clues.json move; refused numbers elsewhere
    # are not rejoined (their cached transcriptions are read again by a page's own reread).
    "234ea287bf880305": "445be7454385737b",  # file_gale_listener's join_key
    # listener_gaps.fill/fill_columns report a spooled (unanswered) ask (Filled.pending) and run() then withholds
    # the verdict's joinKey (gapsPending): a number whose asks are answered is joined again, nothing else moves.
    "ec13d012a15c6479": "445be7454385737b",  # file_gale_listener's join_key
    # listener_gaps.column_boxes/boxes_of run a crop down to the page's measured clue block and the clues missing
    # under the column (reach, CROP_FIX): only the pages of tools/data/listener_crop_clues.json move; refused
    # numbers elsewhere are not rejoined.
    "97c94443cfbac066": "445be7454385737b",  # file_gale_listener's join_key
    # file_gale_listener.build splits a clue's own count off its words (ENUM_FIX): only the pages of
    # tools/data/listener_enum_clues.json move; refused numbers elsewhere are not rejoined.
    "518107eb8b89e740": "445be7454385737b",  # file_gale_listener's join_key
    # listener_gaps.fill_columns takes a blank light's clue its own OCR line spells out in a list with no counts
    # (OWN_FIX): only the pages of tools/data/listener_own_clues.json move; refused numbers elsewhere are not rejoined.
    "78b51cb84315a6bc": "445be7454385737b",  # file_gale_listener's join_key
    # file_gale_listener.build also drops a count's second copy from a clue text whose enumeration the vote kept
    # (No 3756's "... (7)", enumeration "7"), and stale_refused lists a number whose write the gate refused
    # (refusedWrite, no "lacks"): only those verdicts are joined again; refused numbers elsewhere are not.
    "fe3f5af71784c0a8": "286e728875b34dcc",  # file_gale_listener's join_key
}
