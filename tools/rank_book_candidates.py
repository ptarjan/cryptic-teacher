#!/usr/bin/env python3
"""Rank archive.org crossword books by whether acquiring one in full is worth it.

    python3 tools/rank_book_candidates.py                 # every candidate
    python3 tools/rank_book_candidates.py --only <id> ... # a few
    python3 tools/rank_book_candidates.py --out tools/data/book_candidates.json

Writes the `ranking` that tools/data/book_candidates.json holds. Acquiring a
book costs a loan, a full page walk and a reconstruction run per puzzle; this
buys that decision for a 34-leaf sample instead, and records WHY every refusal
is a refusal so the list can be re-read a year later without re-borrowing
anything.

WHY A SAMPLE AND NOT THE BOOK. Leaves 6-39 only — the front matter ends and the
first few puzzles begin there in every collection measured. A whole book pulled
to decide against it is a loan spent on nothing, and these are one-hour,
one-copy loans: the borrow is the scarce resource, not the CPU.

ONE LOAN AT A TIME, ALWAYS RETURNED. Every borrow goes through
tools/fetch_ia_book.borrowed(), whose finally clause hands the loan back on
every exit path including an exception. The books are walked strictly in
series, so this process never holds two.

WHAT IS MEASURED, and by whose thresholds. Nothing here invents a cutoff:

  * LIGHTS PER PUZZLE, the headline. tools/light_spec.build_spec() turns one
    parsed clue list into a light list and tools/grid_verdict.screen_spec()
    says whether that list could be a published 15x15 at all. Its MIN_LIGHTS
    (24) is the gate and its GOOD_LIGHTS (26-32) is what a healthy book reads.
    A book's score is the MEDIAN over the puzzles in its sample, because one
    mangled leaf should not condemn a book and one clean leaf should not sell
    it.
  * CLUE-NUMBER SURVIVAL, from tools/parse_penguin_book.build_quality_report()
    — the share of clues whose printed number survived OCR. Reported and
    ranked on, never rejected on: the reconstructor takes a list with holes in
    its numbering, so this describes scan quality rather than deciding
    anything. Missing whole CLUES is the fatal damage, and that shows up in
    the light count above.
  * PUZZLE COUNT, extrapolated from the puzzles found in the sampled leaves
    against the item's imagecount. An estimate, and labelled one: front and
    back matter make it run high, so it ranks the haul rather than promising
    it.

THE VERDICT. Acquire when the median light count clears
grid_verdict.MIN_LIGHTS, stays under the corpus p99 above it, and at least
half the sampled puzzles pass screen_spec clean. The upper bound is not
decoration: two of the books in this pool print two puzzles to a leaf, and a
45-light "puzzle" that is really two 22-light ones passes every rule
grid_verdict has. Everything else is a refusal, and the three kinds are kept
apart because only one of them is worth retrying:

  * rejected-on-form — the book was read fine and is the wrong SHAPE. Juvenile
    grids too small to be 15x15, barred thematic grids, prose histories that
    print almost no enumerations. Permanent; nothing will change it.
  * rejected-on-availability — archive.org has no such item, or lends no copy
    this account can read. A fact about access, not about the book.
  * undetermined — nothing about the BOOK was established. Either the borrow
    was refused and the availability endpoint would not say which refusal it
    was (fetch_ia_book's own borrow trap), or the sample came back full of
    healthy printed clues that tools/parse_penguin_book.py could not split
    into across and down, which is this repo's shortcoming and not the
    book's. Both are recorded as undetermined rather than guessed, because
    the alternative — filing a readable book under "rejected on form" — is a
    false statement that nobody would ever re-check.

THE RANKING GOES STALE. Items get taken down, loan pools shrink, and a rescan
changes the OCR under you. Re-run this; do not trust the file's numbers past
the date it carries.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_ia_book
import grid_verdict
import light_spec
import parse_penguin_book

UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; personal educational use)"}
METADATA_URL = "https://archive.org/metadata/{id}"
SAMPLE_DIR = Path("/tmp/cryptic-teacher-ia-samples")
DEFAULT_OUT = Path(__file__).resolve().parent / "data" / "book_candidates.json"

# TWO BOUNDS ON A SAMPLED LIGHT COUNT, measured here rather than taken from
# grid_verdict, because they judge whether the SAMPLE measured one puzzle at
# all — a question about this script's unit of measurement, not about whether
# a clue list could be a real grid, which is grid_verdict's job and stays
# there. Measured 2026-09-19 over the 15,636 15x15 grids in puzzles/: light
# counts run 20..46, median 29, p99 34, p99.9 38, and 0.249% print more
# than 36.
#
#   * a MEDIAN above 34 (the 99th percentile) is not a book of 15x15s. The
#     bound on a MEDIAN is deliberately far tighter than the bound on one
#     puzzle: a median over a dozen sampled puzzles sits near the population
#     median (29), so for it to clear the 99th percentile of individual
#     puzzles, the puzzles cannot be drawn from that population at all. Using
#     the individual p99.9 (38) here instead would pass a book of large
#     thematic magazine grids whose sampled median was 36 — which is exactly
#     what it did before this was written down.
#   * TWO PUZZLES GLUED INTO ONE LEAF read as one 45-light puzzle, and that
#     passes every rule in grid_verdict: 45 lights averaging 5.5 cells total
#     ~250, inside its 170..256 window. Nothing downstream would have caught
#     it, and the book sorted to the TOP of the ranking on a number that
#     described two puzzles.
#   * a leaf carrying TWO direction headers says the same thing structurally
#     and says it without a threshold, so it is checked first and preferred:
#     it names the cause (a two-page spread OCR'd as one leaf) instead of
#     inferring it from a count.
CORPUS_15X15_MEDIAN_LIGHTS_MAX = 34  # the corpus p99
CORPUS_15X15_LIGHTS_MAX = 46

# Leaves 6-39 (1-based, inclusive): past the front matter, into the puzzles,
# and a third of a short book — enough for several puzzles in every collection
# measured, cheap enough that judging a book costs one short loan.
FIRST_LEAF = 6
LAST_LEAF = 39

# The pool. Built 2026-09-19 from archive.org's advancedsearch over
# title:(crossword|cryptic|crosswords) crossed with the British broadsheet
# names, then hand-cut to collections that PRINT PUZZLES — dictionaries,
# solving guides and word lists never enter. The deliberate wrong-shape
# entries at the bottom are here to be rejected on form: a ranking that only
# ever sampled things it expected to like says nothing about its own gate.
#
# isbn_* stubs are listed explicitly because archive.org's SEARCH INDEX DOES
# NOT RETURN THEM — probing /metadata/isbn_<isbn13> directly is the only way
# they surface, so a search-only candidate list silently misses the biggest
# books in the pool.
CANDIDATES = [
    # --- already acquired from, so the sample is also a control ---
    "heraldcrosswordb0000unse",
    "newpenguinbkguar0000perk",
    # --- Penguin/Guardian volumes, search-invisible isbn_ stubs ---
    "isbn_9780140176438",
    "isbn_9780140176445",
    "isbn_9780140248098",
    "isbn_9780140277500",
    # --- Telegraph cryptic collections ---
    "isbn_9780330451789",
    "isbn_9780330350013",
    "isbn_9780330343763",
    "isbn_9780330325868",
    "isbn_9780330346429",
    "isbn_9780330339605",
    "dailytelegraphbi0000dail",
    "dailytelegraphcr0000dail",
    "sundaytelegraphb0000sund",
    "telegraphcryptic0000tele",
    "telegraphallnewc0000unse_a7j2",
    "telegraphallnewt0000tele",
    # --- Times ---
    "timescrypticcros0000time_i0s6",
    "timescrypticcros0000time",
    "timescrosswordbo0000unse",
    "isbn_9781902254067",
    "ninthpenguinbook0000unse",
    "tenthpenguinbook0000unse",
    # --- Guardian, Herald, Scotsman, Irish, Independent, FT, Observer ---
    "heraldcrosswordb0000calu",
    "guardiancrosswor0000perk",
    "scotsmancrosswor0000unse_i4i5",
    "crosairecrosswor0000croz",
    "penguinbookofind0000unse_y8k9",
    "penguinbookoffin0000unse",
    "thirdbookofindep0000rich",
    "isbn_0340126078",
    # --- Chambers/other cryptic collections ---
    "chambersbookofmo0000dext",
    "chambersbookofar0000arau",
    "chambersbookofar0000arau_e6k7",
    "crypticcrossword0000unse",
    "isbn_9780600616405",
    "101crypticcrossw0000unse",
    # --- Penguin/Guardian volumes 1, 4 and 6, PROBED TO PROVE THEY ARE ABSENT.
    # Listed so the file says "archive.org does not have this" rather than
    # going silent on three volumes of a series it has the rest of; the probe
    # is a metadata call and costs no loan.
    "isbn_9780140176421",
    "isbn_9780140176452",
    "isbn_9780140248081",
    # --- expected wrong shape; sampled anyway so the gate is shown working ---
    "listenercrosswor0000unse",
    "secondpuffincros0000cash",
    "youngpuffincross0000cave",
    "cluetoourlives800000balf",
    "dailytelegraph800000gilb",
]


# Facts about a candidate that the sample cannot measure and a reader needs.
# Kept out of the identifier list so that list stays a list of identifiers.
NOTES = {
    "isbn_9780140176421":
        "The New Penguin Book of The Guardian Crosswords volume 1 (John "
        "Perkin, 1993). ISBN confirmed against OpenLibrary edition "
        "OL10096302M.",
    "isbn_9780140176452":
        "The New Penguin Book of The Guardian Crosswords volume 4 (1994). "
        "THE ISBN ITSELF IS DERIVED, not confirmed: no library record spells "
        "out 'volume 4', so it comes from the run 9780140176421/438/445 "
        "incrementing by one per volume. A missing item under a derived ISBN "
        "is weaker evidence than a missing item under a confirmed one — if "
        "volume 4 matters, confirm the ISBN off a copy of the book first.",
    "isbn_9780140248081":
        "The New Penguin Book of The Guardian Crosswords volume 6 (1995). "
        "ISBN confirmed against isbnsearch records for John Perkin/Penguin.",
}


def metadata(identifier):
    """The item's metadata block, or {} when archive.org has no such item."""
    r = requests.get(METADATA_URL.format(id=identifier), headers=UA, timeout=30)
    r.raise_for_status()
    return r.json().get("metadata", {})


def sample_text(identifier):
    """Leaves FIRST_LEAF..LAST_LEAF of the book's page OCR, as a form-feed
    separated string — the same shape parse_penguin_book.load_leaves() reads.

    The loan is taken and returned by fetch_ia_book.borrowed(); this function
    adds no path that escapes its finally clause.
    """
    with fetch_ia_book.borrowed(identifier) as session:
        text = fetch_ia_book.fetch_full_text(session, identifier,
                                              max_pages=LAST_LEAF)
    leaves = text.split("\x0c")
    return "\x0c".join(leaves[FIRST_LEAF - 1:LAST_LEAF])


def measure(sample_path):
    """Everything the verdict weighs, from the sample on disk.

    Returns a dict, or raises ValueError when the parser cannot find a puzzle
    region at all — which is itself a finding (a prose book), not a crash.
    """
    puzzles = parse_penguin_book.parse_book(sample_path)
    report = parse_penguin_book.build_quality_report(puzzles)
    leaves = parse_penguin_book.load_leaves(sample_path)

    lights, numbered, clues, enumerated = [], [], [], []
    clean, jigsaw, merged, per_puzzle = 0, 0, 0, []
    for puzzle, row in zip(puzzles, report["puzzles"]):
        across, down, _notes, _damage = light_spec.build_spec(puzzle)
        n_lights = len(across) + len(down)
        reasons = grid_verdict.screen_spec(across, down)
        lights.append(n_lights)
        numbered.append(row["numbered_fraction"])
        clues.append(row["total_clues"])
        enumerated.append(row["enumeration_fraction"])
        if not reasons:
            clean += 1
        if row["mode"] != "across_down":
            jigsaw += 1
        # How many puzzles this leaf actually holds, read off the leaf's own
        # direction headers with the parser's own header test rather than a
        # regex of this script's invention. Two ACROSS headers on one leaf is
        # a two-page spread scanned as one, and every light count taken off
        # it describes two puzzles.
        leaf = leaves[puzzle["source_leaves"]["clue"]]
        heads = sum(1 for line in leaf.split("\n")
                    if parse_penguin_book._header_kind(line) == "ACROSS")
        if heads > 1:
            merged += 1
        per_puzzle.append({
            "puzzles_on_this_leaf": heads,
            "book_number": row["book_number"],
            "setter": row["setter"],
            "mode": row["mode"],
            "lights": n_lights,
            "total_clues": row["total_clues"],
            "numbered_fraction": row["numbered_fraction"],
            "enumeration_fraction": row["enumeration_fraction"],
            "screen_reasons": reasons,
        })

    if not lights:
        raise ValueError("the sampled leaves hold no parseable clue list")

    return {
        "puzzles_in_sample": len(puzzles),
        "median_lights": statistics.median(lights),
        "lights_range": [min(lights), max(lights)],
        "clue_number_survival_pct": round(100 * statistics.median(numbered), 1),
        "median_clues_printed": statistics.median(clues),
        "median_enumeration_pct": round(100 * statistics.median(enumerated), 1),
        "jigsaw_puzzles": jigsaw,
        "merged_leaf_puzzles": merged,
        "screen_clean": clean,
        "screen_clean_fraction": round(clean / len(lights), 3),
        "per_puzzle": per_puzzle,
    }


def judge(m):
    """(verdict, reason) by grid_verdict's thresholds and nothing else.

    THE THREE WAYS A LOW LIGHT COUNT HAPPENS ARE NOT THE SAME FINDING, and
    collapsing them into one "reject" is how a perfectly good book gets
    written off for a parser's shortcoming:

      * no lights at all out of a HEALTHY printed clue list — the book prints
        its Across/Down headers in a shape parse_penguin_book.py does not
        recognise, so the clues never get split by direction. That is a fact
        about this repo's parser, not about the book, so it is UNDETERMINED
        and it says what would settle it.
      * few lights with CLEAN enumerations — the OCR lost nothing, so the
        grids really are smaller than 15x15. Rejected on form, permanently.
      * few lights with DAMAGED enumerations — whole clues were lost to OCR,
        so nothing can be reconstructed from this scan. Also rejected on form,
        and the reason says it was the scan.
    """
    if m["merged_leaf_puzzles"] > m["puzzles_in_sample"] / 2:
        return "undetermined", (
            f"undetermined: {m['merged_leaf_puzzles']} of "
            f"{m['puzzles_in_sample']} sampled leaves carry TWO 'Across' "
            f"headers — this book prints two puzzles to a leaf (a two-page "
            f"spread scanned as one), so every per-puzzle figure here counts "
            f"two puzzles as one and the median of "
            f"{m['median_lights']:.0f} lights is two grids' worth. Nothing "
            f"downstream would catch it: two glued 15x15s land inside "
            f"grid_verdict's cell-total window. Teach the parser to split a "
            f"leaf at its second direction header, then re-sample")
    if m["median_lights"] > CORPUS_15X15_MEDIAN_LIGHTS_MAX:
        return "reject", (
            f"rejected-on-form: median {m['median_lights']:.0f} lights per "
            f"puzzle, above the {CORPUS_15X15_MEDIAN_LIGHTS_MAX} that is the "
            f"99th percentile of the 15,636 published 15x15s in puzzles/ "
            f"(median 29, whole range 20-{CORPUS_15X15_LIGHTS_MAX}). A median "
            f"over a dozen puzzles cannot sit above the 99th percentile of "
            f"the population it is supposedly drawn from, and the leaves hold "
            f"one puzzle each, so this is not the merge artefact above: these "
            f"are bigger-than-15x15 thematic grids, a shape "
            f"tools/reconstruct_grid.py does not derive")
    if m["median_lights"] == 0 and m["median_clues_printed"] >= grid_verdict.MIN_LIGHTS:
        return "undetermined", (
            f"undetermined: the sample prints a healthy "
            f"{m['median_clues_printed']:.0f} clues per puzzle at "
            f"{m['median_enumeration_pct']}% enumeration, but "
            f"tools/parse_penguin_book.py split none of them into across and "
            f"down ({m['jigsaw_puzzles']}/{m['puzzles_in_sample']} fell back "
            f"to flat mode), so no light list exists to judge. The book looks "
            f"fine and the parser cannot read its direction headers — teach "
            f"the parser this book's header shape and re-sample before "
            f"believing anything about it either way")
    if m["median_lights"] < grid_verdict.MIN_LIGHTS:
        scan_is_clean = m["median_enumeration_pct"] >= 90
        cause = (
            "the OCR is clean, so no clues were lost — the grids in this book "
            "are simply smaller than 15x15"
            if scan_is_clean else
            f"only {m['median_enumeration_pct']}% of clues kept their "
            f"enumeration, so whole clues were lost to OCR and this scan "
            f"cannot be reconstructed from")
        return "reject", (
            f"rejected-on-form: median {m['median_lights']:.0f} lights per "
            f"puzzle, below grid_verdict.MIN_LIGHTS={grid_verdict.MIN_LIGHTS}; "
            f"{cause}")
    if m["screen_clean_fraction"] < 0.5:
        return "reject", (
            f"rejected-on-form: only {m['screen_clean']} of "
            f"{m['puzzles_in_sample']} sampled puzzles pass "
            f"grid_verdict.screen_spec — the light lists that come out of "
            f"this book mostly cannot be a published 15x15")
    return "acquire", ""


def estimate_puzzles(m, imagecount):
    """Puzzles in the whole book, from the rate in the sampled leaves.

    Runs HIGH: front and back matter print no puzzles and the sample is taken
    where they do. Labelled an estimate everywhere it is printed.
    """
    if not imagecount or not m["puzzles_in_sample"]:
        return None
    leaves = LAST_LEAF - FIRST_LEAF + 1
    return round(m["puzzles_in_sample"] * int(imagecount) / leaves)


def sample_path_for(identifier):
    return SAMPLE_DIR / f"{identifier}.leaves{FIRST_LEAF}-{LAST_LEAF}.txt"


def rank_one(identifier, reuse_samples=False):
    """One row. With reuse_samples, a sample already on disk is re-measured
    instead of re-borrowed — changing how a sample is JUDGED must never cost
    43 more loans, and archive.org is not a scratch pad to re-run scoring
    against."""
    row = {"identifier": identifier,
           "url": f"https://archive.org/details/{identifier}"}
    if identifier in NOTES:
        row["note"] = NOTES[identifier]
    try:
        meta = metadata(identifier)
    except Exception as err:
        row.update(title=None, verdict="undetermined",
                   reason=f"undetermined: archive.org's metadata call failed "
                          f"({err}); nothing was borrowed, so this says "
                          f"nothing about the book — retry")
        return row

    if not meta:
        row.update(title=None, verdict="reject",
                   reason="rejected-on-availability: archive.org has no item "
                          "with this identifier")
        return row

    row["title"] = meta.get("title")
    row["year"] = meta.get("year") or meta.get("date")
    row["imagecount"] = meta.get("imagecount")
    row["lending"] = meta.get("access-restricted-item") in ("true", True)

    cached = sample_path_for(identifier)
    if reuse_samples and cached.exists():
        row["sample_chars"] = len(cached.read_text(encoding="utf-8"))
        row["sample_reused"] = True
        return finish(row, cached)

    try:
        text = sample_text(identifier)
    except SystemExit as err:
        message = str(err)
        if "cannot be determined" in message or "availability endpoint" in message:
            row.update(verdict="undetermined", reason=f"undetermined: {message}")
        else:
            row.update(verdict="reject",
                       reason=f"rejected-on-availability: {message}")
        return row
    except Exception as err:
        row.update(verdict="undetermined",
                   reason=f"undetermined: the page-OCR read failed "
                          f"({type(err).__name__}: {err}); retry")
        return row

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    path = sample_path_for(identifier)
    path.write_text(text, encoding="utf-8")
    row["sample_chars"] = len(text)
    return finish(row, path)


def finish(row, path):
    """Measure a sample already on disk and set the verdict."""
    try:
        m = measure(path)
    except ValueError as err:
        row.update(verdict="reject", puzzles_in_sample=0,
                   reason=f"rejected-on-form: {err} — prose, or a layout this "
                          f"book's clue lists are not printed in")
        return row

    row["puzzles_in_sample"] = m["puzzles_in_sample"]
    row["estimated_puzzle_count"] = estimate_puzzles(m, row.get("imagecount"))
    row["median_lights"] = m["median_lights"]
    row["lights_range"] = m["lights_range"]
    row["clue_number_survival_pct"] = m["clue_number_survival_pct"]
    row["median_clues_printed"] = m["median_clues_printed"]
    row["median_enumeration_pct"] = m["median_enumeration_pct"]
    row["screen_clean"] = m["screen_clean"]
    row["screen_clean_fraction"] = m["screen_clean_fraction"]
    row["per_puzzle"] = m["per_puzzle"]
    row["verdict"], row["reason"] = judge(m)
    return row


def sort_key(row):
    """Acquirable first, then by quality (median lights), then by haul."""
    return (row.get("verdict") != "acquire",
            -(row.get("median_lights") or 0),
            -(row.get("estimated_puzzle_count") or 0))


README = (
    "Which archive.org crossword books are worth acquiring in full, and why "
    "each refusal is a refusal. Derived {when} by tools/rank_book_candidates.py: "
    "one short loan per book through tools/fetch_ia_book.borrowed(), leaves "
    "{first}-{last} of the page OCR only, parsed by tools/parse_penguin_book.py, "
    "turned into light lists by tools/light_spec.py and judged by "
    "tools/grid_verdict.py's own thresholds (MIN_LIGHTS={min_lights}, "
    "GOOD_LIGHTS={good_lights}) — no cutoff is invented here. A book is "
    "ACQUIRE when its median light count clears MIN_LIGHTS and at least half "
    "its sampled puzzles pass screen_spec. estimated_puzzle_count is "
    "extrapolated from the sampled leaves against the item's imagecount and "
    "runs high, because front and back matter print no puzzles. "
    "THIS IS A MEASUREMENT AND IT GOES STALE: items get taken down, loan "
    "pools shrink, and a rescan changes the OCR underneath these numbers. "
    "Re-run the tool rather than trusting the figures past the date above."
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="just these identifiers")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--reuse-samples", action="store_true",
                     help="re-measure samples already under "
                          f"{SAMPLE_DIR} instead of borrowing again — for "
                          "changing how a sample is judged without spending "
                          "another loan on every book")
    ap.add_argument("--delay", type=float, default=2.0,
                     help="seconds between books, to stay a polite client")
    args = ap.parse_args(argv)

    ids = args.only or CANDIDATES
    rows = []
    for n, identifier in enumerate(ids, 1):
        print(f"[{n}/{len(ids)}] {identifier}", file=sys.stderr, flush=True)
        row = rank_one(identifier, reuse_samples=args.reuse_samples)
        # A run artefact, not a fact about the book: whether THIS run
        # re-measured a cached sample says nothing to a later reader, and the
        # cache it names lives in /tmp and will not outlive the week.
        reused = row.pop("sample_reused", False)
        print(f"    -> {row['verdict']}: lights={row.get('median_lights')} "
              f"puzzles~{row.get('estimated_puzzle_count')} "
              f"{row.get('reason', '')[:110]}", file=sys.stderr, flush=True)
        rows.append(row)
        # Incremental, so a run cut off partway still leaves what it learned.
        rows.sort(key=sort_key)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "README": README.format(when=datetime.now(timezone.utc).date().isoformat(),
                                     first=FIRST_LEAF, last=LAST_LEAF,
                                     min_lights=grid_verdict.MIN_LIGHTS,
                                     good_lights="-".join(
                                         str(x) for x in grid_verdict.GOOD_LIGHTS)),
            "estimate_calibration": (
                "estimated_puzzle_count is an UPPER BOUND, not a count. It "
                "extrapolates the puzzle density of leaves "
                f"{FIRST_LEAF}-{LAST_LEAF} across the item's whole imagecount, "
                "and the pages it never sees — front matter, and the "
                "solutions section, which in some books is a third of the "
                "book — print no puzzles. Against the two books already "
                "acquired from: The New Penguin Book of The Guardian "
                "Crosswords vol 5 estimates 71 against 58 real puzzles "
                "(1.2x), and The Herald Crossword Book vol 2 estimates 101 "
                "against the 43 filed from it (2.3x, though that 43 is what "
                "was taken, not proof of what the book holds). Rank on it; "
                "do not promise it."),
            "derived": datetime.now(timezone.utc).date().isoformat(),
            "sampled_leaves": [FIRST_LEAF, LAST_LEAF],
            "candidates_sampled": len(rows),
            "ranking": rows,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if n < len(ids) and not reused:
            time.sleep(args.delay)

    acquire = [r for r in rows if r["verdict"] == "acquire"]
    print(f"\n{len(acquire)}/{len(rows)} worth acquiring -> {args.out}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
