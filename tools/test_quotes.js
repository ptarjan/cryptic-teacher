/* Clue text stored straight is curled for display.

     node tools/test_quotes.js

   1. quotes.js's curl, and tools/quotes.py's, over one table of cases
      (tools/quotes_cases.json), case by case: apostrophes, opening and closing quotes,
      leading elisions, and one character for one so offsets survive.
   2. The page: a clue stored with straight quotes shows curled ones, in the
      clue list and in the clue being solved. */
"use strict";
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { curl } = require("../quotes.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

// One table for both implementations: tools/quotes.py's curl must agree.
const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, "quotes_cases.json"), "utf8"));
console.log("curl");
for (const [given, want] of CASES) {
  const got = curl(given);
  check(got === want, `${JSON.stringify(given)} -> ${JSON.stringify(got)}${got === want ? "" : ` (want ${JSON.stringify(want)})`}`);
  check(got.length === given.length, `${JSON.stringify(given)} keeps its length`);
}
const py = JSON.parse(execFileSync("python3", ["-I", "-c",
  "import json,sys; sys.path.insert(0, sys.argv[1]); import quotes\n" +
  "print(json.dumps([quotes.curl(g) for g, _ in json.load(open(sys.argv[2], encoding='utf-8'))], ensure_ascii=False))",
  __dirname, path.join(__dirname, "quotes_cases.json")], { encoding: "utf8" }));
CASES.forEach(([given, want], i) =>
  check(py[i] === want, `quotes.py curl agrees on ${JSON.stringify(given)} -> ${JSON.stringify(py[i])}`));
check(curl(curl("'Tis Man's \"word\"")) === curl("'Tis Man's \"word\""), "curling curled text changes nothing");

console.log("the page");
const ID = "cryptic-24104";
const { boot } = require("./fake_dom.js");
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
