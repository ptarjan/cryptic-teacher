"""tools/nation_scans.py: the pieces that need no scan (fake HOME, no live cache)."""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import nation_scans as ns  # noqa: E402


def line(text, x0=0, y0=0, h=40):
    return [(x0, y0, x0 + 10 * len(text), y0 + h, text)]


def test_expected_number_counts_weeks_from_the_anchor():
    assert ns.expected_number(datetime.date(1948, 1, 3)) == 244
    assert ns.expected_number(datetime.date(1947, 12, 27)) == 243


def test_number_of_votes_headings_near_the_count():
    day = datetime.date(1948, 1, 3)
    lines = [line("Crossword Puzzle No. 244"), line("CROSSWORD PUZZLE No. 244"), line("Crossword Puzzle No. 12")]
    assert ns.number_of(lines, day) == 244
    assert ns.number_of([line("Crossword Puzzle No. 12")], day) is None
    assert ns.number_of([line("nothing here")], day) is None


def test_parse_solution_reads_both_lists_and_joins_hyphenated_words():
    text = ("ACROSS :—1 BRICABRAC; 6 TIRER: 9 ANDIRON; 15 and 20 EAST INDIA COMPANY; 26 KEELS. "
            "DOWN :—1 BOAST; 2 INDIANA; 3 APRO- POS ; 4 RANGED.")
    across, down = ns.parse_solution(text)
    assert across[0] == ([1], "BRICABRAC")
    assert ([15, 20], "EASTINDIACOMPANY") in across
    assert [w for _, w in down] == ["BOAST", "INDIANA", "APROPOS", "RANGED"]


def test_answers_for_takes_each_side_in_order_and_checks_lengths():
    rows = ["...", "...", "..."]
    laid = {f"{n}-{d}": ("clue", "3", None) for n, d in
            [(1, "across"), (4, "across"), (5, "across"), (1, "down"), (2, "down"), (3, "down")]}
    across = [([1], "CAT"), ([9], "ORE"), ([5], "WED")]  # a misread number: the order stands
    down = [([1], "COW"), ([2], "ARE"), ([3], "TED")]
    words, note = ns.answers_for(rows, laid, across, down)
    assert words["4-across"] == "ORE" and len(words) == 6, note
    # a word of the wrong length is no answer
    words, _ = ns.answers_for(rows, laid, [([1], "CATS"), ([4], "ORE"), ([5], "WED")], down)
    assert "1-across" not in words
    # words that disagree at a crossing are all dropped
    words, note = ns.answers_for(rows, laid, [([1], "CAT"), ([4], "ORE"), ([5], "WED")],
                                 [([1], "XOW"), ([2], "ARE"), ([3], "TED")])
    assert words == {} and "clash" in note


def test_laid_fits_names_a_light_without_a_clue():
    rows = ["...", "...", "..."]
    laid = {"1-across": ("c", "3", None)}
    assert "no clue" in ns.laid_fits(rows, laid)
    assert "counts 4" in ns.laid_fits(rows, {"1-across": ("c", "4", None)})


def test_clue_boxes_cut_two_columns_under_the_grid_above_a_solution_list():
    lines = [line("Hill Billies? (8, 5)", 560, 2600), line("Alterrate business affairs. (7)", 1420, 2600),
             line("many novel things. (7)", 1420, 2660), line("SOLUTION TO PUZZLE No. 243", 1450, 3370)]
    boxes = ns.clue_boxes(lines, (476, 772, 2172, 2488))
    assert len(boxes) == 2 and boxes[0][2] <= boxes[1][2]
    assert boxes[1][3] <= 3360


def test_solution_text_reads_the_lines_below_the_heading():
    lines = [line("SOLUTION TO PUZZLE No. 243", 1451, 3370), line("ACROSS :—1 BRICABRAC;", 1346, 3429),
             line("DOWN :—1 BOAST;", 1346, 3480), line("an article far below", 1346, 4400)]
    number, text = ns.solution_text(lines)
    assert number == 243 and "BRICABRAC" in text and "article" not in text


def test_blocked_drops_bars():
    assert ns.blocked(["#.r", "b+."]) == ["#..", "..."]
