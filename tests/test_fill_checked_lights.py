#!/usr/bin/env python3
"""fill_checked_lights fills a blank only from crossings or the write-up's own word."""
import fill_checked_lights as f


def entry(number, direction, x, y, length, solution=""):
    return {"number": number, "direction": direction, "position": {"x": x, "y": y},
            "length": length, "solution": solution}


def puzzle(entries, partial):
    return {"id": "times-1", "number": 1, "date": "2010-01-01", "entries": entries,
            "solutions": {"blog": "timesforthetimes", "partial": partial}}


def main():
    # 1-across is crossed in every cell by the three down lights.
    p = puzzle([entry(1, "across", 0, 0, 3), entry(1, "down", 0, 0, 3, "CAT"),
                entry(2, "down", 1, 0, 3, "ARE"), entry(3, "down", 2, 0, 3, "TEA")], ["1-across"])
    assert f.fill_puzzle(p, "") == {"1-across": "CAT"}, f.fill_puzzle(p, "")
    f.apply(p, {"1-across": "CAT"})
    assert "partial" not in p["solutions"] and p["entries"][0]["solution"] == "CAT"

    # One unchecked cell of a long light: only the write-up's word fills it.
    def long_one(text):
        e = [entry(1, "across", 0, 0, 5)] + [entry(n, "down", n - 1, 0, 2, w)
                                             for n, w in ((1, "WA"), (2, "OA"), (4, "DA"), (5, "SA"))]
        return f.fill_puzzle(puzzle(e, ["1-across"]), text)
    assert long_one("the blog says words here") == {"1-across": "WORDS"}
    assert long_one("the answer was WOXDS here") == {}                  # not a word
    assert long_one("it is nothing") == {}
    assert long_one("no mention") == {}

    # A word that merely fits a three-letter light is chance, never a fill.
    e = [entry(1, "across", 0, 0, 3), entry(1, "down", 0, 0, 2, "BA"), entry(3, "down", 2, 0, 2, "TA")]
    assert f.fill_puzzle(puzzle(e, ["1-across"]), "BAT BIT") == {}

    # Two answered lights that disagree at a cell: leave the file alone.
    e = [entry(1, "across", 0, 0, 3, "CAT"), entry(1, "down", 0, 0, 3, "DOG"), entry(4, "across", 0, 2, 3)]
    assert f.fill_puzzle(puzzle(e, ["4-across"]), "") == {}
    print("ok   fill_checked_lights fills only what the grid or the write-up settles")


if __name__ == "__main__":
    main()
