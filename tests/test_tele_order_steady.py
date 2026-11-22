"""TELE_ORDER_STEADY: a Telegraph title is placed among the steady filed numbers, not a misread one."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import file_archive_org_puzzles as fa  # noqa: E402


def held_1984():
    held = {15302: datetime.date(1975, 3, 5)}
    day = datetime.date(1984, 6, 13)
    for i in range(30):
        d = day + datetime.timedelta(days=i)
        if d.weekday() != 6:
            held[fa.telegraph_expected_number(d)] = d
    held[18106] = datetime.date(1984, 6, 12)
    return held


class TeleOrderSteady(unittest.TestCase):
    def test_stray_neighbour_is_dropped(self):
        held = held_1984()
        day = datetime.date(1984, 5, 4)
        n = fa.telegraph_expected_number(day)
        number, why = fa.placed(n, day, fa.Held.of(held))
        self.assertIsNone(number)
        self.assertIn("out of date order", why)
        steady = fa.Held.of(held).steady(fa.telegraph_expected_number)
        self.assertNotIn(18106, steady)
        self.assertEqual(fa.placed(n, day, steady), (n, None))

    def test_due_row(self):
        from fix_reasons import registered
        due = registered()["20261122_1400_tele_order_steady"].due
        row = {"edition": "GaleTelegraph1984UKEnglish/1984-05-04", "inputs": "x", "readAt": "2026-11-01T03:00:00+00:00",
               "verdicts": [{"number": 18133, "cause": "number-date-mismatch",
                             "refused": "No 18133 on 1984-05-04 is out of date order with No 15302 on 1975-03-05 and No 18106 on 1984-06-12"}]}
        self.assertTrue(due(row))


if __name__ == "__main__":
    unittest.main()
