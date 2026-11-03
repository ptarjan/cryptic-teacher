// The finish's devices, alsoLeads and offGrid clues.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, assert, entryId, fs, path, stripTags } = T;
// --- the finish names the devices you needed help with ---
// Booted with a finished save planted, the way a reopened puzzle or a synced
// device arrives: the recap has to come out of the saved ladder state alone.
{
  const shim = (id) => {
    const w = { CRYPTIC_PUZZLES: {} };
    new Function("window", fs.readFileSync(path.join(ROOT, "puzzles", id + ".js"), "utf8"))(w);
    return w.CRYPTIC_PUZZLES[id];
  };
  const square = (e, i) => (e.position.x + (e.direction === "across" ? i : 0)) + ","
    + (e.position.y + (e.direction === "across" ? 0 : i));
  const ID = "quiptic-1397";
  const B = shim(ID);
  const annotated = B.entries.filter((e) => !e.group && ((e.annotation || {}).type || []).length);
  const [b1, b2] = annotated;
  const at = Date.now() - 3600e3;
  const save = (solvedWith, revealsUsed) => {
    const letters = {}, letterAt = {};
    B.entries.forEach((e) => {
      for (let i = 0; i < e.length; i++) { letters[square(e, i)] = e.solution[i]; letterAt[square(e, i)] = at; }
    });
    return JSON.stringify({ letters, letterAt, solvedWith, hintsShown: {}, hintsEarned: {},
      revealsUsed, timing: { solvedAt: at }, updated: at });
  };
  const zero = Object.fromEntries(B.entries.map((e) => [entryId(e), 0]));
  const scoreline = (stored) => {
    const d = require("../fake_dom.js").boot({ query: "?p=" + ID, storage: { ["ct:" + ID]: stored } });
    const box = d.registry["celebrate"];
    assert(!box.classList.contains("hidden"), "a finished save opens on its scoreline");
    return box.children.map((c) => c.innerHTML).join("");
  };
  const clean = scoreline(save(zero, {}));
  assert(!/Your hints by clue type/.test(clean), "a puzzle finished with no hints has no recap: " + clean);

  const html = scoreline(save(Object.assign({}, zero, { [entryId(b1)]: 2 }), { [entryId(b2)]: 1 }));
  assert(/Your hints by clue type/.test(html), "a finish with hints lists what was used: " + html);
  const want = {};
  // Each clue counts once, under its most specific device, so the counts add
  // up to the number of clues that needed help.
  [b1, b2].forEach((e) => {
    const ts = e.annotation.type || [];
    const t = ts.find((x) => x !== "charade") || ts[0];
    if (t) want[t] = (want[t] || 0) + 1;
  });
  const got = Object.fromEntries([...html.matchAll(/href="[^"]*learn\/#([a-z-]+)">([^<]+)<\/a> <span class="muted">\d+ hints? · (\d+) clues?<\/span>/g)]
    .map((m) => [m[2], +m[3]]));
  const label = (t) => global.CRYPTIC_INDEX.clueTypes.types.find((x) => x.name === t).label;
  for (const [t, n] of Object.entries(want)) {
    assert(got[label(t)] === n, `the recap counts each clue that needed help once, under ${t} (${n}): ` + JSON.stringify(got));
  }
  assert(Object.keys(got).length === Object.keys(want).length,
    "and lists nothing those two clues did not use: " + JSON.stringify(got));
}

// --- one light leads two linked answers (alsoLeads) ---
// Genius 209's 22-across starts both IVOR HUGH JEGO and IVOR SORE BEACH BUM:
// one light, two clues. The second is a row of its own straight after the
// first; picking it, or one of its continuations, puts ITS clue in front of
// you; and the light's squares still belong to the real entry, so a tap on
// one picks the first clue and typing fills the grid.
{
  const ID = "smoke-alsoleads";
  const E = (number, direction, x, y, solution, clue, extra) => Object.assign(
    { number, direction, position: { x, y }, length: solution.length, solution, clue }, extra || {});
  const puz = {
    id: ID, number: 1, series: "quiptic", name: "Also-leads fixture", setter: "Smoke", date: "2026-01-01",
    dimensions: { cols: 5, rows: 5 }, solutions: true,
    entries: [
      E(1, "across", 0, 0, "ABCDE", { text: "First lead", enumeration: "5,5" },
        { group: ["1-across", "3-down"],
          alsoLeads: [{ clue: { text: "Second lead", enumeration: "5,5" }, group: ["1-across", "2-down"] }] }),
      E(4, "across", 0, 4, "IRMSQ", { text: "Bottom row", enumeration: "5" }),
      E(1, "down", 0, 0, "AFGHI", { text: "Left column", enumeration: "5" }),
      E(2, "down", 2, 0, "CJKLM", { text: "See 1 across" }),
      E(3, "down", 4, 0, "ENOPQ", { text: "See 1 across" }),
    ],
  };
  const d = require("../fake_dom.js").boot({
    query: "?p=" + ID,
    storage: { "ct:seen": JSON.stringify({ last: "2000-01-01", days: 5 }) },
    index: (ix) => {
      ix.puzzles.push({ id: ID, number: 1, series: "quiptic", name: puz.name, setter: puz.setter,
                        date: puz.date, file: ID + ".js", hasSolutions: true, annotated: false });
      global.window.CRYPTIC_PUZZLES = Object.assign(global.window.CRYPTIC_PUZZLES || {}, { [ID]: puz });
    },
  });
  const reg = d.registry;
  const hintText = () => stripTags(reg["hint-clue"].innerHTML, "");
  const across = reg["clues-across"].children.map((li) => li.id);
  assert(String(across) === "clue-1-across,clue-1-across~2,clue-4-across",
    "a light leading two answers lists both clues, the second straight after the first: " + across);
  const text = (id) => (reg[id] ? reg[id].querySelector(".clue-text").innerHTML : "");
  assert(/First lead/.test(text("clue-1-across")) && /Second lead/.test(text("clue-1-across~2")),
    "each row prints its own clue: " + text("clue-1-across") + " | " + text("clue-1-across~2"));
  assert(/Solved <strong>0\/4<\/strong>/.test(reg["scorebar"].innerHTML),
    "the second answer counts as a clue; its continuation does not: " + reg["scorebar"].innerHTML);
  const cols = puz.dimensions.cols;
  const cellEl = (x, y) => reg["grid"].children[y * cols + x];
  const lit = (x, y) => cellEl(x, y).classList.contains("hl") || cellEl(x, y).classList.contains("sel");
  const active = () => reg["clues-across"].children.concat(reg["clues-down"].children)
    .filter((li) => li.classList.contains("active")).map((li) => li.id).sort();

  // A continuation of the second answer: that answer's clue, its rows lit.
  reg["clue-2-down"].listeners.click[0]();
  assert(/Second lead/.test(hintText()),
    "picking 2-down shows the clue it continues, the second lead: " + reg["hint-clue"].innerHTML);
  assert(String(active()) === "clue-1-across~2,clue-2-down",
    "the second answer's rows are active, not the first's: " + active());
  assert([0, 1, 2, 3, 4].every((y) => lit(2, y)), "2-down's squares are highlighted");

  // The second answer's own row: its clue, on the light's squares.
  if (reg["clue-1-across~2"]) reg["clue-1-across~2"].listeners.click[0]();
  assert(/Second lead/.test(hintText()),
    "picking the second lead's row shows its clue: " + reg["hint-clue"].innerHTML);
  assert(String(active()) === "clue-1-across~2,clue-2-down", "and lights its own group: " + active());
  assert([0, 1, 2, 3, 4].every((x) => lit(x, 0)), "on the light's own squares");

  // The squares are the real entry's: a tap picks the first clue, and typing fills the grid.
  cellEl(1, 0).listeners.mousedown[0]({ preventDefault() {} });
  assert(/First lead/.test(hintText()),
    "a tap on the light picks the entry that owns its squares: " + reg["hint-clue"].innerHTML);
  assert(String(active()) === "clue-1-across,clue-3-down", "and its group: " + active());
  d.docListeners["keydown"][0]({ key: "B", preventDefault() {}, shiftKey: false, target: reg["kbd"] });
  assert(cellEl(1, 0).querySelector(".letter").textContent === "B",
    "typing on the light fills its square: " + JSON.stringify(cellEl(1, 0).querySelector(".letter").textContent));
}

// --- an off-grid clue (offGrid) ---
// Genius 280 enters some answers outside the grid. Such a clue owns no square:
// it is listed in a section of its own with a box for its answer, typing there
// moves no cursor, the box's letters are what solve it, picking it puts its
// clue in the hint panel, and the save holds its letters under its entry id.
{
  const ID = "smoke-offgrid";
  const E = (number, direction, x, y, solution, clue) =>
    ({ number, direction, position: { x, y }, length: solution.length, solution, clue });
  const puz = {
    id: ID, number: 1, series: "quiptic", name: "Off-grid fixture", setter: "Smoke", date: "2026-01-01",
    dimensions: { cols: 3, rows: 3 }, solutions: true,
    entries: [
      E(1, "across", 0, 0, "CAT", { text: "Pet", enumeration: "3" }),
      E(1, "down", 0, 0, "COW", { text: "Cattle", enumeration: "3" }),
    ],
    offGrid: [{
      clue: { text: "Divine beings in dog's disarray", enumeration: "4" }, solution: "GODS",
      annotation: { type: ["anagram"], answer: "GODS", definitions: [{ text: "Divine beings", at: 0 }],
                    indicators: [{ text: "disarray", for: "anagram" }],
                    blocks: [{ clueFragment: "dog's", gives: "DOGS", note: "letters to be rearranged" }] },
    }],
  };
  const bootIt = (storage) => require("../fake_dom.js").boot({
    query: "?p=" + ID,
    storage: Object.assign({ "ct:seen": JSON.stringify({ last: "2000-01-01", days: 5 }) }, storage),
    index: (ix) => {
      ix.puzzles.push({ id: ID, number: 1, series: "quiptic", name: puz.name, setter: puz.setter,
                        date: puz.date, file: ID + ".js", hasSolutions: true, annotated: true });
      global.window.CRYPTIC_PUZZLES = Object.assign(global.window.CRYPTIC_PUZZLES || {}, { [ID]: puz });
    },
  });
  const d = bootIt({});
  const reg = d.registry;
  const row = reg["clue-1-offgrid"];
  const listed = (reg["clues-offgrid"].children || []).map((li) => li.id);
  assert(String(listed) === "clue-1-offgrid" && !reg["offgrid-section"].classList.contains("hidden"),
    "an off-grid clue is listed in its own section: " + listed);
  const box = row && row.querySelector(".offgrid-answer");
  assert(box && box.tagName === "INPUT" && box.maxLength === 4, "its row carries an answer box of its length");

  row.listeners.click[0]();
  assert(/Off the grid.*Divine beings/.test(stripTags(reg["hint-clue"].innerHTML, "")),
    "picking it makes it the hint panel's clue: " + reg["hint-clue"].innerHTML);
  const sel = () => reg["grid"].children.findIndex((el) => el.classList.contains("sel"));
  const before = sel();

  box.value = "dogx";
  box.listeners.input[0]();
  assert(box.value === "DOGX", "the box keeps letters only, uppercased: " + box.value);
  assert(!row.classList.contains("solved"), "a wrong answer leaves it unsolved");
  assert(sel() === before && reg["grid"].children.every((el) => !el.querySelector(".letter").textContent),
    "typing in the box neither moves the cursor nor fills the grid");

  box.value = "gods";
  box.listeners.input[0]();
  assert(row.classList.contains("solved"), "the right answer marks it solved");
  assert(/Solved <strong>1\/3<\/strong>/.test(reg["scorebar"].innerHTML),
    "it counts as a clue: " + reg["scorebar"].innerHTML);

  global.flushTimers(200);
  const saved = JSON.parse(d.storage["ct:" + ID]);
  assert(saved.letters["1-offgrid"] === "GODS" && saved.letterAt["1-offgrid"] > 0,
    "the save holds its letters under its entry id: " + JSON.stringify(saved.letters));
  const again = bootIt({ ["ct:" + ID]: JSON.stringify(saved) }).registry;
  const box2 = again["clue-1-offgrid"] && again["clue-1-offgrid"].querySelector(".offgrid-answer");
  assert(box2 && box2.value === "GODS" && again["clue-1-offgrid"].classList.contains("solved"),
    "and a reload puts them back in the box: " + (box2 && box2.value));
}
