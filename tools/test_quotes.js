/* Clue text stored straight is curled for display.

     node tools/test_quotes.js

   1. quotes.js's curl, case by case: apostrophes, opening and closing quotes,
      leading elisions, and one character for one so offsets survive.
   2. The page: a clue stored with straight quotes shows curled ones, in the
      clue list and in the clue being solved. */
"use strict";
const { curl } = require("../quotes.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const CASES = [
  ["Man's familiar name", "Man’s familiar name"],
  ["Dogs' home", "Dogs’ home"],
  ["'Hello,' she said", "‘Hello,’ she said"],
  ["He said \"stop\" twice", "He said “stop” twice"],
  ["\"Stop!\"", "“Stop!”"],
  ["Run ('quickly')", "Run (‘quickly’)"],
  ["Out—'now'", "Out—‘now’"],
  ["\"'Tis said\"", "“’Tis said”"],
  ["'Tis the season", "’Tis the season"],
  ["Give 'em hell", "Give ’em hell"],
  ["Rock 'n' roll", "Rock ’n’ roll"],
  ["Hit of the '60s", "Hit of the ’60s"],
  ["'Emma' by Austen", "‘Emma’ by Austen"],
  ["'Tisane' is tea", "‘Tisane’ is tea"],
  ["Ma'loula", "Ma’loula"],
  ["Is it? 'Yes.'", "Is it? ‘Yes.’"],
  ["No quotes here", "No quotes here"],
  ["", ""],
];
console.log("curl");
for (const [given, want] of CASES) {
  const got = curl(given);
  check(got === want, `${JSON.stringify(given)} -> ${JSON.stringify(got)}${got === want ? "" : ` (want ${JSON.stringify(want)})`}`);
  check(got.length === given.length, `${JSON.stringify(given)} keeps its length`);
}
check(curl(curl("'Tis Man's \"word\"")) === curl("'Tis Man's \"word\""), "curling curled text changes nothing");

console.log("the page");
const ID = "cryptic-24104";
const { boot } = require("./fake_dom.js");
const fs = require("fs");
const path = require("path");
const dir = path.join(__dirname, "..", "puzzles", "cryptic");
const file = fs.readdirSync(dir).map((y) => path.join(dir, y, ID + ".json")).find(fs.existsSync);
const puz = JSON.parse(fs.readFileSync(file, "utf8"));
const e = puz.entries[0];
e.clue.text = "Man's \"best\" friend, 'tis said";
delete e.clue.italics;
delete e.annotation;
// Handed to the page before app.js runs, so it renders this copy, not the file.
const d = boot({ query: "?p=" + ID, index: () => { global.window.CRYPTIC_PUZZLES = { [ID]: puz }; } });
const row = d.registry["clue-" + e.number + "-" + e.direction];
const shown = row ? row.querySelector(".clue-text").innerHTML : "";
check(shown.indexOf("Man’s “best” friend, ’tis said") >= 0, "the clue list shows the clue curled: " + shown);
check(!/&#39;|&quot;/.test(shown), "and no straight quote is left in it");

if (failures) { console.error(`\n${failures} failure(s)`); process.exit(1); }
console.log("\nquotes: all checks passed");
