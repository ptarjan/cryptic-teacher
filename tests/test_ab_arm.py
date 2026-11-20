import collections
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import ab_arm
import ab_report


def test_arm_is_reproducible_and_valid():
    for i in range(50):
        pid = f"times-{i}"
        assert ab_arm.pick(pid) == ab_arm.pick(pid)
        assert ab_arm.pick(pid) in ab_arm.ARMS


def test_arms_all_drawn_roughly_evenly():
    c = collections.Counter(ab_arm.pick(f"sundaytimes-{i}") for i in range(2000))
    assert set(c) == set(ab_arm.ARMS)
    assert min(c.values()) > 350


def test_report_joins_and_summarises():
    t = datetime.datetime(2026, 11, 17, 20, 0, tzinfo=datetime.UTC)
    sec = datetime.timedelta(seconds=1)
    runs = [("a", "fable/high", t), ("b", "opus/medium", t + 600 * sec)]
    mk = lambda off, cost, fail: {"start": t + off * sec, "cost": cost, "clues": 10, "turns": 5,
                                  "wall_min": 4.0, "first_units": 1, "first_failed": fail}
    pairs = ab_report.join(runs, [mk(30, 3.0, 0), mk(630, 1.0, 1)])
    assert [a for a, _ in pairs] == ["fable/high", "opus/medium"]
    rows = ab_report.summarise(pairs, collections.Counter(a for _, a, _ in runs))
    assert rows["fable/high"]["cost_per_puzzle"] == 3.0
    assert rows["fable/high"]["first_check_pass"] == 1.0
    assert rows["opus/medium"]["first_check_pass"] == 0.0
    assert ab_report.arm_of("opus", "") == "opus/medium"
