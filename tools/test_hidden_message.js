/* A solved clue shows its hidden letter, and the message fills in under the grid.

     node tools/test_hidden_message.js

   genius-273 carries the message "SUM TO FINAL" (P.messages) whose letters are
   the ones its across clues omit (annotation.hiddenLetter); 7-across LOOSE
   omits S. Unsolved, no clue row shows a letter and every slot is empty;
   solving 7-across badges that row alone and puts S in the first slot. */
"use strict";
const ID = "genius-273";
let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};
const text = (s) => s.replace(/<[^>]*>/g, "");

const d = require("./fake_dom.js").boot({ query: "?p=" + ID });
const puz = global.window.CRYPTIC_PUZZLES[ID];
const reg = d.registry;
const rowOf = (n, dir) => reg["clue-" + n + "-" + dir].querySelector(".clue-text").innerHTML;
const msg = () => reg["hidden-message"].innerHTML;
const letters = () => (msg().match(/hm-letter">([A-Z])</g) || []).map((s) => s.slice(-2, -1));

const seven = puz.entries.find((e) => e.number === 7 && e.direction === "across");
check(seven.solution === "LOOSE", "7-across is LOOSE");

console.log("unsolved");
const open = puz.entries.filter((e) => e.number !== 7 || e.direction !== "across");
check(!/hidden-letter/.test(rowOf(7, "across")), "7-across shows no letter before it is solved");
check((msg().match(/hm-slot/g) || []).length === 10 && letters().length === 0,
  "the message shows ten empty slots: " + text(msg()));
check((msg().match(/hm-gap/g) || []).length === 2, "the spaces show from the start");

console.log("solve 7-across");
reg["clue-7-across"].listeners.click[0]();
const kd = d.docListeners["keydown"][0];
for (const ch of seven.solution)
  kd({ key: ch, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
check(/<span class="hidden-letter"[^>]*>S<\/span>/.test(rowOf(7, "across")),
  "7-across shows the badge S: " + rowOf(7, "across"));
check(/^<span class="hm-row"><span class="hm-letter">S<\/span><span class="hm-slot">/.test(msg()),
  "S is in the message's first slot: " + msg());
check(letters().join("") === "S", "only S is filled: " + letters().join(""));
check(open.every((e) => !/hidden-letter/.test(rowOf(e.number, e.direction))),
  "no other clue shows a letter");

process.exit(failures ? 1 : 0);
