"""INDY_TWO_LINE: the Independent's heading split over lines ("THE INDEPENDENT Crossword" over "No. 2297 ... by Aelred", or the
number on the Saturday prize crossword's ACROSS/DOWN row under the entry coupon) is read by indy_two_line; the reason's rescan is
due once for an untitled Independent row."""
import _path  # puts tools/ on sys.path

import file_archive_org_puzzles as fa
import fix_reasons

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def line(x0, y0, x1, y1, text):
    ws = text.split()
    step = (x1 - x0) / len(ws)
    return [(x0 + k * step, y0, x0 + (k + 1) * step - 4, y1, w) for k, w in enumerate(ws)]


banner = line(229, 3335, 1279, 3463, "THE INDEPENDENT Crossword Ande")
under = [line(190, 3448, 281, 3475, "o.2297"), line(838, 3447, 947, 3478, "by Aelred")]
check("a number line under the banner is read", [n for n, _ in fa.indy_two_line([banner, *under], 2307)] == [2297])
check("a number past the slack is not", not fa.indy_two_line([banner, *under], 2800))
check("no banner, no heading", not fa.indy_two_line(under, 2307))
check("no setter, no heading", not fa.indy_two_line([banner, under[0]], 2307))
sat = [line(223, 4006, 1832, 4063, "The first five correct Solutions THE INDEPENDENT Crossword"),
       line(363, 4269, 485, 4304, "ACROSS"), line(1089, 4269, 1211, 4304, "No. 2475"), line(1715, 4266, 1812, 4302, "by Phi")]
check("the Saturday number on the ACROSS row is read", [n for n, _ in fa.indy_two_line(sat, 2483)] == [2475])
check("a number line above its banner is not a heading", not fa.indy_two_line(
    [line(1089, 3000, 1211, 3030, "No. 2475"), line(1715, 3000, 1812, 3030, "by Phi"), sat[0]], 2483))
row = {"edition": "GaleIndependent1994UKEnglish/1994-11-22", "readAt": "2026-11-10T23:28:24+00:00", "inputs": "x",
       "scan": {"date": "1994-11-22", "item": "GaleIndependent1994UKEnglish", "puzzles": [], "solutions": [], "indyLooked": True,
                "wholeUntitled": True}, "verdicts": []}
reason = [r for r in fix_reasons.registered().values() if "two-line heading" in r.text][0]
row["scanKey"] = sorted(fa.current_keys(fa.GALE_INDEPENDENT))[0]
check("an untitled Independent row read before the push is rescanned", reason.rescan(row))
check("a scan with the INDY_TWO_LINE stamp is not", not reason.rescan(dict(row, scan=dict(row["scan"], **{fa.INDY_TWO_LINE_LOOKED: True}))))
check("a row with a verdict is not", not reason.rescan(dict(row, verdicts=[{"number": 1}])))
check("a Sunday row is not", not reason.rescan(dict(row, edition="GaleIndependentSunday1994UKEnglish/1994-11-20")))
raise SystemExit(1 if fails else 0)
