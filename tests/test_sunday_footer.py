"""sunday_footer_cut drops a Gale Sunday Times page's folio line ("54-STYLE") from a clue list; due() names its rows."""
import _path  # puts tools/ on sys.path
import file_archive_org_puzzles as fa
import fix_reasons


def test_folio_line_dropped():
    text = "28 Certain changes (6)\n29 Salesman with the consumer (8)\n54:STYLE"
    assert fa.sunday_footer_cut(text) == "28 Certain changes (6)\n29 Salesman with the consumer (8)"
    for line in ("46 ·STYl.E", "62·STYLe", "54-STYLE", "38· STYLE"):
        assert fa.sunday_footer_cut(line) == ""


def test_clues_kept():
    text = "4 Style guide (5)\n12 Gape at slim sound woman (6)"
    assert fa.sunday_footer_cut(text) == text


def test_due_row():
    row = {"edition": "GaleSundayTimes2001UKEnglish/2001-10-07", "inputs": "x", "readAt": "2026-11-01T18:42:16+00:00",
           "verdicts": [{"number": 3933, "pending": "no grid: the search found no grid",
                         "imageDisagrees": "across clue [] names no light the grid numbers after 29"}]}
    reason = [r for r in fix_reasons.registered().values() if r.text.startswith("a Gale Sunday Times 2000-02 page pending no grid")][0]
    assert reason.due(row)
    row["edition"] = "GaleSundayTimes2005UKEnglish/2005-10-07"
    assert not reason.due(row)
