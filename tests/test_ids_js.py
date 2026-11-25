import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import gen_ids_js
import series


def test_ids_js_is_current():
    assert gen_ids_js.OUT.read_text() == gen_ids_js.render(), \
        "sync/ids.js is stale: run python3 tools/gen_ids_js.py"


def test_every_series_key_fits():
    for key in series.SERIES:
        assert re.fullmatch(series.ID_SERIES, key), key
        assert series.puzzle_id(key, 1) == f"{key}-1"


def test_puzzle_id_refuses_what_the_grammar_refuses():
    for bad in [("a", 1), ("Times", 1), ("x-y", 1), ("a" * 13, 1), ("times", 1234567), ("times", -1)]:
        try:
            series.puzzle_id(*bad)
        except AssertionError:
            continue
        raise AssertionError(bad)
