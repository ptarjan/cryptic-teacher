/* The Letters tab: the anagram wheel, a free tab on the step track.

     node tests/test_free_wheel.js

   1. It is on no clue before the clue type is known, and never on a clue that
      is not an anagram, even once its type step is open.
   2. On an anagram clue, opening the Clue type step (here by "Just tell me")
      puts it on the track right after Clue type.
   3. Tapping it brings the wheel to the front, empty, with the clue's own
      words as the picker. It is no hint: the score and every other tab are
      unchanged.
   4. Letters typed into it appear as tiles, and Backspace takes one off.
   5. Another tab picked over it hides it, and coming back finds the letters
      as they were left. */
"use strict";
const fs = require("fs");
const path = require("path");
const { boot } = require("../tools/fake_dom.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const entryId = (e) => e.number + "-" + e.direction;

// The anagram family, read off the clue types the app grades by.
const CLUE_TYPES = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "tools/data/clue_types.json"), "utf8"));
const FAMILY = Object.fromEntries(CLUE_TYPES.types.map((t) => [t.name, t.family]));
const isAna = (e) => ((e.annotation || {}).type || []).some((t) => FAMILY[t] === FAMILY.anagram);

const id = "quiptic-1396";
const d = boot({ query: "?p=" + id, storage: { "ct:nux": "9" } });
const reg = d.registry;
const entries = global.window.CRYPTIC_PUZZLES[id].entries;
const usable = (e) => e.annotation && e.solution && !e.offGrid && !e.linkedTo && (e.annotation.type || []).length;
const plain = entries.find((e) => usable(e) && !isAna(e));
const ana = entries.find((e) => usable(e) && isAna(e));
const track = () => reg["hint-track"].children;
const letters = () => track().find((b) => /\bletters\b/.test(b.className || ""));
const tiles = () => [...reg["hint-body"].innerHTML.matchAll(/class="ana-tile[^"]*"[\s\S]*?>([A-Z])<\/button>/g)].map((m) => m[1]);
const score = () => reg["scorebar"].innerHTML;
const others = () => track().filter((b) => b !== letters()).map((b) => b.className + ":" + b.textContent).join("|");
const pick = (e) => reg["clue-" + entryId(e)].listeners.click[0]();

// Open the Clue type step by asking for it and being told.
function tellType() {
  const t = track().find((b) => /Clue type/.test(b.textContent || ""));
  if (!t || !t.onclick) return false;
  if (!/\bopen\b/.test(t.className || "")) {
    t.onclick();
    if (reg["guess-tell"] && reg["guess-tell"].onclick) reg["guess-tell"].onclick();
  }
  return /\bopen\b/.test((track().find((b) => /Clue type/.test(b.textContent || "")) || {}).className || "");
}

check(!!plain && !!ana, `a plain clue (${plain && plain.solution}) and an anagram (${ana && ana.solution}) found`);

// --- 1: nowhere before the type is known, never on a non-anagram ---
pick(plain);
check(!letters(), "no Letters tab on a fresh non-anagram clue");
check(tellType(), "the plain clue's Clue type step opens");
check(!letters(), "and still none once its type is known: " + others());
pick(ana);
check(!letters(), "no Letters tab on an anagram before its type is known: " + others());

// --- 2: told the type, the tab arrives after Clue type ---
check(tellType(), "the anagram's Clue type step opens");
const tab = letters();
check(!!tab, "the Letters tab is on the track: " + others());
const at = track().indexOf(tab);
check(at > 0 && /Clue type/.test(track()[at - 1].textContent || ""), "right after Clue type: " + track().map((b) => b.textContent).join(" | "));
check(tab && /\bltr\b/.test(tab.className) && tab.getAttribute("role") === "tab", "a step tab in its own colour: " + (tab && tab.className));
check(tab && !/\b(avail|open|locked)\b/.test(tab.className), "and never a step to buy or a note");

// --- 3: opening it is free ---
const before = others(), paid = score();
tab.onclick();
check(reg["hint-body"].innerHTML.includes("anagram-ring"), "tapping it draws the ring");
check(tiles().length === 0, "which starts empty");
check(reg["hint-clue"].innerHTML.includes("data-aw=") && !reg["hint-body"].innerHTML.includes("ana-word"),
  "the clue's own words are the picker, with no second row of chips");
check(/\bsel\b/.test(letters().className) && letters().getAttribute("aria-selected") === "true", "the Letters tab is the one selected");
check(others() === before, "every other tab is unchanged: " + others());
check(score() === paid, "and so is the score");

// --- 4: typing ---
const word = "TEARS";
const type = (k) => reg["ana-kbd"].listeners.keydown[0]({ key: k, preventDefault() {} });
word.split("").forEach(type);
check(tiles().sort().join("") === word.split("").sort().join(""),
  "typed letters appear in the ring: " + tiles().join(""));
check(score() === paid, "still no hint charged");
type("Backspace");
check(tiles().length === word.length - 1, "Backspace takes one off");

// --- 5: one front panel, letters remembered ---
const typeTab = track().find((b) => /Clue type/.test(b.textContent || ""));
typeTab.onclick();
check(/<div class="hint-pending" role="tabpanel" hidden>/.test(reg["hint-body"].innerHTML), "another tab picked hides the wheel");
check(!reg["hint-clue"].innerHTML.includes("data-aw="), "and the clue's words stop feeding it");
check(!/\bsel\b/.test(letters().className), "the Letters tab lets go of the selection");
letters().onclick();
check(tiles().length === word.length - 1, "coming back finds the letters as they were left: " + tiles().join(""));
pick(plain);
pick(ana);
check(!!letters(), "the tab is still there after leaving the clue and coming back");
letters().onclick();
check(tiles().length === word.length - 1, "and so are the letters: " + tiles().join(""));

if (failures) { console.error(failures + " failed"); process.exit(1); }
console.log("all passed");
