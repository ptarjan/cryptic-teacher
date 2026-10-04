/* A jigsaw's solver is never told where an answer goes.

     node tools/test_jigsaw.js

   tools/puzzle_tags.py tags a puzzle "jigsaw" when its preamble withholds the
   answers' places, and "numbered-jigsaw" when it places some by the grid's
   numbers. Each property is asserted on a jigsaw and, as its mirror, on an
   ordinary puzzle with the same steps.

   1. listSaysNothing: the clue list is one list, in the answers' alphabetical
      order, with no number and no Down section.
   2. pickStaysOffGrid: picking a clue off the list highlights no square and
      moves no cursor; the panel shows its words and no number or letter strip.
   3. tapKeepsPick: tapping a square of another light leaves the picked clue
      in the panel, so the panel never names the square's clue.
   4. gridNumbers: a plain jigsaw's grid has no numbers; a numbered jigsaw's
      keeps them, and its clue list still has none. */
"use strict";
const { boot } = require("./fake_dom.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const JIGSAW = "cryptic-24331";
const NUMBERED = "cryptic-22297";
const PLAIN = "cryptic-30066";

function open(id) {
  const d = boot({ query: "?p=" + id });
  const puz = global.window.CRYPTIC_PUZZLES[id];
  return { d, puz, reg: d.registry, cols: puz.dimensions.cols };
}
const squares = (t) => t.reg["grid"].children.filter((el) => !el.classList.contains("block"));
const lit = (t) => squares(t).map((el, i) => (el.classList.contains("hl") || el.classList.contains("sel") ? i : -1))
  .filter((i) => i >= 0).join(",");
const numbered = (t) => squares(t).filter((el) => /class="num"/.test(el.innerHTML)).length;
const rows = (t, id) => t.reg[id].children;
const plain = (html) => html.replace(/<[^>]*>/g, "").replace(/&#39;/g, "'").replace(/&quot;/g, '"')
  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const rowText = (li) => plain(li.querySelector(".clue-text").innerHTML);
const at = (t, x, y) => t.reg["grid"].children[y * t.cols + x];

for (const [id, isJigsaw] of [[JIGSAW, true], [PLAIN, false]]) {
  const t = open(id);
  const tags = (global.window.CRYPTIC_INDEX.puzzles.find((p) => p.id === id) || {}).tags || [];
  const name = isJigsaw ? "" : " (mirror)";
  check(tags.includes("jigsaw") === isJigsaw, `${id} is${isJigsaw ? "" : " not"} tagged jigsaw: ${tags}`);

  // 1. listSaysNothing
  const across = rows(t, "clues-across"), down = rows(t, "clues-down");
  const nums = across.concat(down).filter((li) => /clue-num/.test(li.innerHTML)).length;
  if (isJigsaw) {
    check(across.length === t.puz.entries.length && down.length === 0,
      `listSaysNothing: every clue in one list (${across.length}/${t.puz.entries.length}, ${down.length} down)`);
    check(nums === 0, `listSaysNothing: no clue number on the list (${nums})`);
    check(t.reg["clues-down-section"].classList.contains("hidden") && t.reg["clues-across-h"].textContent === "Clues",
      "listSaysNothing: one section, headed Clues");
    const want = t.puz.entries.slice().sort((a, b) => a.solution.localeCompare(b.solution)).map((e) => e.clue.text);
    check(across.every((li, i) => rowText(li).startsWith(plain(want[i]).slice(0, 10))),
      "listSaysNothing: the list is in the answers' alphabetical order");
  } else {
    check(nums === across.length + down.length && down.length > 0,
      "listSaysNothing (mirror): an ordinary puzzle numbers its Across and Down clues");
  }

  // 2. pickStaysOffGrid: pick a clue whose light the cursor is not on
  const before = lit(t);
  const li = across[across.length - 1];
  li.listeners.click[0]();
  const after = lit(t);
  const clue = t.reg["hint-clue"].innerHTML;
  if (isJigsaw) {
    check(after === before, `pickStaysOffGrid: picking a clue lights no new square (${before} -> ${after})`);
    check(plain(clue).includes(rowText(li).slice(0, 10)), "pickStaysOffGrid: the panel shows the picked clue");
    check(!/entry-tag/.test(clue), "pickStaysOffGrid: the panel names no number");
    check(t.reg["hint-pattern"].innerHTML === "", "pickStaysOffGrid: no letter strip of the clue's squares");
    check(!/[?&]c=/.test(global.location.search + global.location.href),
      "pickStaysOffGrid: the address names no clue");
  } else {
    check(after !== before, "pickStaysOffGrid (mirror): picking an ordinary clue lights its squares");
    check(/entry-tag/.test(clue), "pickStaysOffGrid (mirror): an ordinary clue is named by number");
  }

  // 3. tapKeepsPick: tap the first square of a light that is not the pick's
  if (isJigsaw) {
    const picked = rowText(li).slice(0, 10);
    const other = t.puz.entries.find((e) => !e.clue.text.startsWith(picked));
    at(t, other.position.x, other.position.y).listeners.mousedown[0]({ preventDefault() {} });
    const now = plain(t.reg["hint-clue"].innerHTML);
    check(now.includes(picked) && !now.includes(other.clue.text.slice(0, 10)),
      "tapKeepsPick: tapping a square leaves the picked clue up, not the square's");
  }

  // 4. gridNumbers
  check((numbered(t) === 0) === isJigsaw, `gridNumbers${name}: ${numbered(t)} numbered squares`);
}

{
  const t = open(NUMBERED);
  const tags = (global.window.CRYPTIC_INDEX.puzzles.find((p) => p.id === NUMBERED) || {}).tags || [];
  check(tags.includes("numbered-jigsaw"), `${NUMBERED} is a numbered jigsaw: ${tags}`);
  check(numbered(t) > 0, "gridNumbers: a numbered jigsaw keeps the grid's numbers");
  check(!rows(t, "clues-across").some((li) => /clue-num/.test(li.innerHTML)),
    "gridNumbers: and its clue list still has none");
}

if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
console.log("all jigsaw checks passed");
