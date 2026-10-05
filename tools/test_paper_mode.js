/* Paper mode hides every right/wrong signal until "I'm done", then hands it all back.

     node tools/test_paper_mode.js

   Each property is asserted with paper mode on and, as its mirror, with it off,
   on the same grid and the same keystrokes. A test that only ever checks "no
   tick" cannot tell a hidden tick from a tick the test never managed to earn:
   the mirror proves the same steps DO earn one when nothing is hiding it.

   1. typingGivesNoSignal: a correct answer typed on paper gets no solved
      class or clean star in the clue list, no tick beside the clue, no meter,
      ladder or reveal, and nothing frozen into solvedWith. Off paper the same
      typing gets all of them.
   2. paperTools: on paper the letter and word checks are hidden and
      "I'm done" is shown; off paper the reverse.
   3. pickerWaits: a finished grid on paper is not "solved ✓" in the picker
      and solves no clue on the stats sheet; the same save off paper does both.
   4. doneCredits: "I'm done" ends paper mode for the puzzle, checks the grid,
      and credits every correct clue as solved with no rungs (solvedWith 0,
      the clean star), stamping the finish so the streak can count it.
   5. switchInPuzzle: the one paper switch is in the puzzle's toolbar, not on
      the puzzle list. Ticking it in a puzzle under way puts that puzzle on
      paper and makes paper the device default; unticking it hands every
      signal back and turns the default off. */
"use strict";
const fs = require("fs");
const path = require("path");
const { boot } = require("./fake_dom.js");

const ID = "cryptic-30066";
const KEY = "ct:" + ID;
const entryId = (e) => e.number + "-" + e.direction;

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

// One boot per scenario: booting again reassigns the globals app.js reads.
function open(storage) {
  const d = boot({ query: "?p=" + ID, storage });
  const puz = global.window.CRYPTIC_PUZZLES[ID];
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: d.registry["kbd"] });
  const hidden = (id) => d.registry[id].classList.contains("hidden");
  const saved = () => { const raw = d.storage[KEY]; return raw ? JSON.parse(raw) : null; };
  const flush = () => d.winListeners["blur"].forEach((f) => f());
  return { d, puz, key, hidden, saved, flush, reg: d.registry };
}

// Every square of the puzzle right, as a save: the "x,y" keys writeState uses.
function finishedSave(puz) {
  const letters = {};
  puz.entries.forEach((e) => {
    for (let i = 0; i < e.length; i++) {
      const x = e.position.x + (e.direction === "across" ? i : 0);
      const y = e.position.y + (e.direction === "across" ? 0 : i);
      letters[x + "," + y] = e.solution[i];
    }
  });
  return { letters, letterAt: {}, hintsShown: {}, hintsEarned: {}, revealsUsed: {},
           blocksAt: {}, solvedWith: {}, timing: {}, clearedAt: 0, updated: 1 };
}

// The stats sheet's "clues solved" figure, read off the saves as it is drawn.
function statsSolved(t) {
  t.reg["btn-stats"].onclick();
  const m = /<strong>(\d+)<\/strong><span>clues solved/.exec(t.reg["stats-body"].innerHTML);
  t.reg["btn-stats-close"].onclick();
  return m ? Number(m[1]) : null;
}

function pickerSays(t) {
  t.reg["btn-picker"].onclick();
  t.reg["picker-search"].value = "30066 cryptic";
  t.reg["picker-search"].listeners.input[0]();
  return t.reg["picker-list"].children.map((li) => li.children[0].innerHTML).join("");
}

// --- 1, 2: typing one correct answer, with the setting on and off ---
for (const paperOn of [true, false]) {
  const tag = paperOn ? "on paper" : "mirror, off paper";
  const t = open({ "ct:paper": JSON.stringify({ on: paperOn, open: {} }) });
  const entry = t.puz.entries.find((e) => e.solution && e.length >= 5);
  t.reg["clue-" + entryId(entry)].listeners.click[0]();
  for (const ch of entry.solution) t.key(ch);
  t.flush();
  const li = t.reg["clue-" + entryId(entry)];
  const solvedWith = (t.saved() || {}).solvedWith || {};
  const clue = t.reg["hint-clue"].innerHTML;
  if (paperOn) {
    check(!li.classList.contains("solved") && !li.classList.contains("no-hints"),
      `typingGivesNoSignal (${tag}): the clue list row is not marked solved`);
    check(!/clue-done/.test(clue), `typingGivesNoSignal (${tag}): no tick beside the clue: ${clue}`);
    check(t.reg["hint-meter"].innerHTML === "" && t.reg["hint-next"].childElementCount === 0
          && !/Reveal/.test(t.reg["hint-escape"].innerHTML),
      `typingGivesNoSignal (${tag}): no meter, no rung buttons, no reveal`);
    check(!(entryId(entry) in solvedWith),
      `typingGivesNoSignal (${tag}): nothing frozen in solvedWith: ${JSON.stringify(solvedWith)}`);
    check(/Paper mode/.test(t.reg["scorebar"].innerHTML), `paperTools (${tag}): the scorebar says paper mode is on`);
    check(t.hidden("chk-letter") && t.hidden("chk-entry") && t.hidden("chk-grid") && !t.hidden("paper-done"),
      `paperTools (${tag}): the letter, word and grid checks give way to I'm done`);
    check(!t.hidden("clear-entry") && !t.hidden("reset-puzzle"), `paperTools (${tag}): Clear and Reset stay`);
    check(!t.hidden("paper-switch") && t.reg["paper-toggle"].checked === true,
      `paperTools (${tag}): the switch is shown, ticked`);

    // --- 4 (partial grid): I'm done credits the one clue, clean ---
    t.reg["paper-done"].onclick();
    t.flush();
    const after = t.saved() || {};
    check(li.classList.contains("solved") && li.classList.contains("no-hints"),
      "doneCredits: after I'm done the typed clue is solved with the clean star");
    check((after.solvedWith || {})[entryId(entry)] === 0,
      "doneCredits: credited with no rungs: " + JSON.stringify(after.solvedWith));
    check(/correct/.test(t.reg["check-result"].textContent),
      "doneCredits: the grid check reports what it found: " + t.reg["check-result"].textContent);
    check(!JSON.parse(t.d.storage["ct:paper"]).open[ID], "doneCredits: the puzzle is off paper for good");
    check(!t.hidden("chk-entry") && t.hidden("paper-done") && t.reg["hint-meter"].innerHTML !== "",
      "doneCredits: the checks and the ladder are back");
  } else {
    check(li.classList.contains("solved") && li.classList.contains("no-hints"),
      `typingGivesNoSignal (${tag}): the same typing marks the row solved and clean`);
    check(/clue-done/.test(clue), `typingGivesNoSignal (${tag}): and ticks the clue`);
    check(solvedWith[entryId(entry)] === 0, `typingGivesNoSignal (${tag}): and freezes it in solvedWith`);
    check(!t.hidden("chk-entry") && t.hidden("paper-done"), `paperTools (${tag}): the usual checks, no I'm done`);
    check(!t.hidden("paper-switch") && t.reg["paper-toggle"].checked === false,
      `paperTools (${tag}): the switch is shown, unticked`);
  }
}

// --- 3, 4: a finished grid, saved on paper and off ---
{
  const puz = open({}).puz;
  const save = JSON.stringify(finishedSave(puz));
  for (const paperOn of [true, false]) {
    const tag = paperOn ? "on paper" : "mirror, off paper";
    const t = open({ [KEY]: save, "ct:paper": JSON.stringify({ on: paperOn, open: paperOn ? { [ID]: 1 } : {} }) });
    const stats = statsSolved(t);
    const rows = pickerSays(t);
    if (!paperOn) {
      check(/solved ✓/.test(rows), `pickerWaits (${tag}): the finished save reads solved ✓`);
      check(stats > 0, `pickerWaits (${tag}): and the stats sheet counts its clues: ${stats}`);
      continue;
    }
    check(stats === 0, `pickerWaits (${tag}): the stats sheet counts none of its clues yet: ${stats}`);
    check(rows && !/solved ✓/.test(rows), `pickerWaits (${tag}): the finished save is not solved ✓ yet: ${rows.slice(0, 200)}`);
    check(t.reg["celebrate"].classList.contains("hidden"), `pickerWaits (${tag}): no finish line either`);
    t.reg["picker-panel"].classList.add("hidden");
    t.reg["paper-done"].onclick();
    t.flush();
    const after = t.saved() || {};
    const sw = after.solvedWith || {};
    check(puz.entries.every((e) => sw[entryId(e)] === 0),
      "doneCredits: every clue credited clean: " + JSON.stringify(sw));
    check(!!(after.timing && after.timing.solvedAt), "doneCredits: the finish is stamped for the streak");
    check(/solved ✓/.test(pickerSays(t)), "doneCredits: and the picker now reads solved ✓");
    check(statsSolved(t) > 0, "doneCredits: and the stats sheet counts its clues");
  }
}

// --- 5: the switch lives in the puzzle, and works there ---
{
  const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  const main = html.slice(html.indexOf('<main id="app"'), html.indexOf("</main>"));
  check(html.split('id="paper-toggle"').length === 2, "switchInPuzzle: one paper switch in the page");
  check(main.includes('id="paper-toggle"') && main.includes('id="paper-switch"'),
    "switchInPuzzle: it is inside the puzzle view");
  const picker = html.slice(html.indexOf('id="picker-panel"'), html.indexOf('<main id="app"'));
  check(!/paper-toggle|paper-switch/.test(picker), "switchInPuzzle: and not on the puzzle list");

  const t = open({});
  const entry = t.puz.entries.find((e) => e.solution && e.length >= 5);
  t.reg["clue-" + entryId(entry)].listeners.click[0]();
  for (const ch of entry.solution) t.key(ch);
  const li = t.reg["clue-" + entryId(entry)];
  check(li.classList.contains("solved"), "switchInPuzzle (mirror, off paper): the typed clue shows solved");
  t.reg["paper-toggle"].checked = true;
  t.reg["paper-toggle"].onchange();
  const on = JSON.parse(t.d.storage["ct:paper"]);
  check(on.on === true && !!on.open[ID], "switchInPuzzle: ticking it puts this puzzle on paper and the default on");
  check(!li.classList.contains("solved") && t.hidden("chk-entry") && !t.hidden("paper-done")
        && t.reg["paper-toggle"].checked === true,
    "switchInPuzzle: the tick and the checks go, I'm done comes");
  t.reg["paper-toggle"].checked = false;
  t.reg["paper-toggle"].onchange();
  const off = JSON.parse(t.d.storage["ct:paper"]);
  check(off.on === false && !off.open[ID], "switchInPuzzle: unticking it takes the puzzle off paper and the default off");
  check(li.classList.contains("solved") && !t.hidden("chk-entry") && t.hidden("paper-done"),
    "switchInPuzzle: the tick and the checks come back");
}

if (failures) { console.log(failures + " failure(s)"); process.exit(1); }
console.log("paper mode: all checks passed");
