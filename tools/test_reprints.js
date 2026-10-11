/* A paper that reprints another's puzzle is listed, and every way in opens the
   original.

     node tools/test_reprints.js

   1. fetch_puzzle.reprint_rows() turns an original's source.reprintedIn into
      one `reprints` row per reprint, newest first, named in the reprinting
      paper's style, and takes the field off the puzzle row.
   2. ?p=<reprint id> goes to the original; progress saved under the reprint id
      moves to the original's; the mirror: an id nobody reprinted stays put.
   3. The original says which paper printed it and as what; the mirror: a
      puzzle nobody reprinted says nothing.
   4. The picker's paper menu lists the reprinting paper with its count, the
      filter lists its reprint rows, and tapping one opens the original.
   5. A book puzzle renamed to the newspaper puzzle it reprints
      (tools/data/renamed_ids.json) is a reprint row at its book id and year,
      directly or through a chain; a renumbering inside the book, an id a
      puzzle holds, a deleted target and a non-book rename are not. The book's
      picker list shows it with its year, the original names the book, and
      coverage.held_numbers() counts it as the book's. */
"use strict";
const { execFileSync } = require("child_process");
const { boot } = require("./fake_dom.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

{
  const out = execFileSync("python3", ["-c", `
import json, sys
sys.path.insert(0, ${JSON.stringify(__dirname)})
import fetch_puzzle as F
rows = [{"id": "timesquick-3146", "date": "2026-05-22", "reprintedIn": [
          {"series": "globeandmail", "number": 3146, "date": "2026-07-10"}]},
        {"id": "timesquick-3147", "date": "2026-05-25", "reprintedIn": [
          {"series": "globeandmail", "number": 3147, "date": "2026-07-13"}]},
        {"id": "times-1", "date": "2026-05-25", "reprintedIn": []}]
print(json.dumps({"reprints": F.reprint_rows(rows), "left": [sorted(r) for r in rows]}))
`], { encoding: "utf8" });
  const { reprints, left } = JSON.parse(out);
  check(reprints.length === 2 && reprints[0].id === "globeandmail-3147",
    "one row per reprint, newest first: " + reprints.map((r) => r.id).join(","));
  const r = reprints[1];
  check(r.name === "Globe and Mail cryptic crossword No 3,146" && r.reprintOf === "timesquick-3146"
    && r.date === "2026-07-10" && r.originalDate === "2026-05-22" && r.number === 3146,
    "the row names the reprint and points at the original: " + JSON.stringify(r));
  check(left.every((k) => !k.includes("reprintedIn")), "the puzzle rows lose reprintedIn");
}

// A book puzzle renamed to the newspaper puzzle it reprints is the same row,
// at the book's id and year, and coverage still counts it as the book's.
{
  const out = execFileSync("python3", ["-c", `
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(__dirname)})
import fetch_puzzle as F, coverage as C
rows = [{"id": "times-18574", "series": "times", "date": "1991-06-01", "reprintedIn": []},
        {"id": "book-35009", "series": "book", "year": 1993, "reprintedIn": []},
        {"id": "independent-9900", "series": "independent", "date": "2018-01-01", "reprintedIn": []},
        {"id": "timesquick-3146", "series": "timesquick", "date": "2026-05-22", "reprintedIn": [
          {"series": "globeandmail", "number": 3146, "date": "2026-07-10"}]}]
renamed = {"book-35006": "times-18574",          # out of the book: a reprint row
           "book-35007": "book-35990", "book-35990": "times-18574",  # a chain out of it
           "book-35008": "book-35009",            # renumbered inside the book: none
           "book-35009": "times-1",               # an old id a puzzle holds today: none
           "book-35010": "times-2",               # its puzzle deleted: none
           "indysunday-9900": "independent-9900", # a misfiling corrected, no book: none
           "globeandmail-3146": "timesquick-3146"} # already a reprint row: once
got = F.reprint_rows(rows, renamed)
tmp = Path(tempfile.mkdtemp())
for rel in ("puzzles/times/1991/times-18574.json", "puzzles/book/1993/book-35009.json",
            "tools/data/renamed_ids.json"):
    (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp / rel).write_text(json.dumps(renamed) if rel.endswith("renamed_ids.json") else "{}")
C.ROOT = tmp
print(json.dumps({"rows": got, "held": sorted(C.held_numbers("book"))}))
`], { encoding: "utf8" });
  const { rows, held } = JSON.parse(out);
  check(rows.map((r) => r.id).join(",") === "globeandmail-3146,book-35990,book-35007,book-35006",
    "a book id renamed out of its book (directly or by a chain) gets a row, by day then number; "
    + "a renumbering, a held id, a deleted target and a non-book rename get none: "
    + rows.map((r) => r.id).join(","));
  const b = rows.find((r) => r.id === "book-35006") || {};
  check(b.series === "book" && b.number === 35006 && b.year === 1993 && !("date" in b)
    && b.name === "Times cryptic crossword, Times Crosswords book 17 No 6"
    && b.reprintOf === "times-18574" && b.originalDate === "1991-06-01",
    "the book row is named and dated as the book prints it: " + JSON.stringify(b));
  check(held.join(",") === "35006,35007,35009,35990",
    "coverage counts the renamed-out positions as the book's filed puzzles: " + held.join(","));
}

// A synthetic reprint of a real listed puzzle, under a number no file has.
let ORIG, OTHER;
const REPRINT = { series: "globeandmail", number: 99999, id: "globeandmail-99999", date: "2099-01-01",
  name: "Globe and Mail cryptic crossword No 99,999" };
const withReprint = (idx) => {
  const solved = idx.puzzles.filter((p) => p.hasSolutions && p.date && p.series !== REPRINT.series);
  ORIG = solved[0]; OTHER = solved[1];
  idx.reprints = [Object.assign({ reprintOf: ORIG.id, originalDate: ORIG.date }, REPRINT)];
  idx.papers[REPRINT.series] = idx.papers[REPRINT.series] || "Globe and Mail";
  idx.groups[REPRINT.series] = idx.groups[REPRINT.series] || "Globe and Mail";
};

{
  boot({ query: "?p=" + REPRINT.id, index: withReprint });
  check(String(global.location.replaced || "").includes(ORIG.id),
    `?p=${REPRINT.id} goes to the original ${ORIG.id}: ${global.location.replaced}`);
}
{
  const d = boot({ query: "?p=" + OTHER.id, index: withReprint,
    storage: { ["ct:" + REPRINT.id]: JSON.stringify({ letters: { "0,0": "A" } }) } });
  check(!!d.storage["ct:" + ORIG.id] && !("ct:" + REPRINT.id in d.storage),
    "progress saved under the reprint id moves to the original's");
  check(!global.location.replaced, "(mirror) an id nobody reprinted opens in place");
  check(d.registry["puzzle-reprint"].classList.contains("hidden"),
    "(mirror) a puzzle nobody reprinted says nothing about reprints");
}
{
  const d = boot({ query: "?p=" + ORIG.id, index: withReprint });
  const note = d.registry["puzzle-reprint"].textContent;
  check(!d.registry["puzzle-reprint"].classList.contains("hidden")
    && note.startsWith("The Globe and Mail printed this as No 99,999 on 1 January 2099: it is the ")
    && note.includes(ORIG.name),
    "the original says who reprinted it: " + note);

  // The held reprint files (tools/data/reprints_pending.json) still list under
  // the paper until they are folded, so the counts are the paper's own plus one.
  const own = global.CRYPTIC_INDEX.puzzles.filter((p) => p.series === REPRINT.series).length;
  const reg = d.registry;
  reg["btn-picker"].onclick();
  check(new RegExp(`value="${REPRINT.series}">[^<]* \\(${(own + 1).toLocaleString("en-GB")}\\)<`)
    .test(reg["picker-paper"].innerHTML),
    `the paper menu lists the reprinting paper with its count (${own} + 1)`);
  reg["picker-paper"].value = REPRINT.series;
  reg["picker-paper"].listeners.change[0]();
  const isReprint = (li) => li.children[0].innerHTML.includes("No 99,999");
  const rows = reg["picker-list"].children;
  check(rows.filter(isReprint).length === 1,
    "filtering on the reprinting paper lists its reprint row");
  const back = boot({ query: "?p=" + OTHER.id, index: withReprint });
  back.registry["btn-picker"].onclick();
  back.registry["picker-paper"].value = REPRINT.series;
  back.registry["picker-paper"].listeners.change[0]();
  back.registry["picker-list"].children.find(isReprint).children[0].onclick({});
  check(back.registry["puzzle-title"].innerHTML.startsWith(ORIG.name.replace(/&/g, "&amp;")),
    "tapping the reprint row opens the original: " + back.registry["puzzle-title"].innerHTML.slice(0, 80));
}
// A book's reprint row (a year, no date) lists under the book with its year,
// and the original names the book it is reprinted in.
{
  const BOOK = { series: "book", number: 35998, id: "book-35998", year: 1993,
    name: "Times cryptic crossword, Times Crosswords book 17 No 998" };
  const withBook = (idx) => {
    ORIG = idx.puzzles.filter((p) => p.hasSolutions && p.date && p.series !== "book")[0];
    idx.reprints = [Object.assign({ reprintOf: ORIG.id, originalDate: ORIG.date }, BOOK)];
  };
  const d = boot({ query: "?p=" + ORIG.id, index: withBook });
  const note = d.registry["puzzle-reprint"].textContent;
  check(note.startsWith("Reprinted as Times Crosswords book 17 No 998 (1993): it is the ")
    && note.includes(ORIG.name), "the original names the book that reprints it: " + note);
  const row = (() => {
    const reg = d.registry;
    reg["btn-picker"].onclick();
    reg["picker-paper"].value = "book";
    reg["picker-paper"].listeners.change[0]();
    reg["picker-search"].value = "998";
    reg["picker-search"].listeners.input[0]();
    return reg["picker-list"].children.find((li) => li.children[0].innerHTML.includes("No 998"));
  })();
  check(!!row && row.children[0].innerHTML.includes("1993"),
    "filtering on the book lists the reprint row with the book's year: "
    + (row ? row.children[0].innerHTML.slice(0, 160) : "no row"));
}
process.exit(failures ? 1 : 0);
