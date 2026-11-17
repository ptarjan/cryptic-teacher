"""sunday_count_off refuses a title off an unbroken weekly run (1985-11-17 read 3104 for 3106)."""
import datetime

import _path  # puts tools/ on sys.path
import file_archive_org_puzzles as fa

D = datetime.date


def held():
    return {3101: D(1985, 10, 13), 3110: D(1985, 12, 15), 3113: D(1986, 1, 5)}


def test_two_low_inside_unbroken_run_refused():
    assert fa.sunday_count_off(3104, D(1985, 11, 17), held())


def test_right_number_kept():
    assert fa.sunday_count_off(3106, D(1985, 11, 17), held()) is None


def test_skipped_number_run_not_forced():
    h = {3267: D(1988, 12, 18), 3270: D(1989, 1, 15)}
    assert fa.sunday_count_off(3269, D(1989, 1, 1), h) is None
