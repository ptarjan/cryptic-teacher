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
}
