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
      filter lists its reprint rows, and tapping one opens the original. */
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
process.exit(failures ? 1 : 0);
