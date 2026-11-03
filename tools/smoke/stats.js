// First-visit cursor, the stats panel, jigsaws and hint-rule links.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, assert, entryId, fs, groupsOf, isAsking, nuxLine, path } = T;
// --- the first-visit cursor, on browsers this harness cannot be ---
// Down here with the other fresh boots, not up beside the rest of the NUX
// checks: a second boot() takes the globals over, and the primary instance
// every test above drives goes on writing its beacons through them.
//
// A first visit is a BROWSER that has been here one day, not a page load that
// happened to be the first of a day. reportVisit stops early once it has sent
// today's beacon, so the cursor must be decided above that stop, or anyone who
// opens the site twice in a day sees the lines on neither load. The seeded
// tally says days: 1, so these lines are still owed.
{
  const today = new Date().toISOString().slice(0, 10);
  const again = require("../fake_dom.js").boot({
    storage: { "ct:seen": JSON.stringify({ last: today, days: 1 }) } });
  assert(!again.registry["welcome"].classList.contains("hidden"),
    "a second load on a browser's first day is still met by the dialog");
  assert(again.storage["ct:nux"] === "0",
    "and the cursor is seeded past the once-a-day beacon gate: " + again.storage["ct:nux"]);
  // Saying you already solve cryptics spends the whole cursor, not one step of
  // it: everything left is the same lesson, and offering the next sentence to
  // someone who just said no is the tour this is not.
  again.registry["welcome-skip"].onclick();
  assert(again.registry["welcome"].classList.contains("hidden")
         && again.registry["nux"].classList.contains("hidden"),
    "skipping puts the whole thing away, dialog and lines both");
  assert(Number(again.storage["ct:nux"]) >= 4,
    "and spends the cursor past the last line: " + again.storage["ct:nux"]);
  // Pressing the rung the scrim is holding open is the whole point of the
  // sequence, so it is walked end to end once: dialog, hole over one button,
  // press, and the page comes back up. A scrim that outlived the press would
  // leave the site dark for a solver who did exactly what it asked.
  const press = require("../fake_dom.js").boot({
    storage: { "ct:seen": JSON.stringify({ last: today, days: 1 }) } });
  press.registry["welcome-go"].onclick();
  const litRung = () => press.registry["hint-next"].children.filter(
    (c) => /rung-point/.test(c.className || ""))[0];
  const lit = litRung();
  assert(lit && !press.registry["spotlight"].classList.contains("hidden"),
    "starting lights one rung and darkens the rest of the page");
  const firstLabel = lit.textContent;
  lit.onclick();
  assert(!press.registry["spotlight"].classList.contains("hidden"),
    "a question on the table keeps the scrim — the hole moves to the question");
  // The sentence outlives the scrim on purpose: this rung asks before it tells,
  // and the line is spent by the ladder running out, not by a button going down.
  // And while the question is up it says the answer to it. That pointing at the
  // right words yourself opens a rung for nothing is the one thing a newcomer
  // cannot discover by pressing buttons, so the walk shows it being done.
  assert(/costs you nothing/.test(nuxLine(press.registry))
         && /tap what is lit up/.test(nuxLine(press.registry)),
    "the line says the step is theirs to win: " + nuxLine(press.registry));
  // And it POINTS rather than reading the answer out: naming the words in the
  // sentence would teach this one clue, where pointing at them teaches the
  // gesture that makes a rung free anywhere on the site.
  assert(/walk-point/.test(press.registry["hint-clue"].innerHTML)
         || /walk-point/.test(press.registry["hint-body"].innerHTML),
    "what would answer it wears the pulse: " + press.registry["hint-clue"].innerHTML.slice(0, 300));
  assert(/\?|hint-step/.test(press.registry["hint-body"].innerHTML),
    "the press put something in the panel to read: "
    + press.registry["hint-body"].innerHTML.slice(0, 200));
  // Picking every lit word moves the pulse and the hole onto the button that
  // grades them: selecting is half the gesture, and a light left on the
  // question block would leave the newcomer hunting for what to press next.
  const pulsing = Object.keys(press.registry).filter((id) => /^gw-\d+$/.test(id)
    && /walk-point/.test(press.registry[id].className || ""));
  if (pulsing.length && press.registry["guess-check"]) {
    assert(!/walk-point/.test(press.registry["guess-check"].className || ""),
      "the check button waits until the words are picked");
    pulsing.forEach((id) => press.registry[id].onclick());
    assert(/walk-point/.test(press.registry["guess-check"].className || ""),
      "once the lit words are picked the check button takes the pulse: "
      + press.registry["guess-check"].className);
  }
  // And the walk goes on. One press teaches what one button does; the row is
  // what the line is about, so opening a rung hands the light to the next one
  // rather than ending the lesson.
  press.registry["guess-tell"].onclick();
  const second = litRung();
  assert(second && second.textContent !== firstLabel,
    "the light moves down the ladder instead of going out: "
    + (second ? second.textContent : "nothing lit"));
  assert(!press.registry["spotlight"].classList.contains("hidden"),
    "and the scrim comes back around it");
  assert(/a bit more/.test(nuxLine(press.registry)),
    "the line changes its words once they have taken one: " + nuxLine(press.registry));
  // ...and having taught the site, the site shuts up. The ladder line is spent
  // by the last rung rather than the first, and the two after it are spent one
  // hint each, so a second ladder empties the slot for good: a newcomer gets
  // these sentences once in their life, not a banner that returns every session.
  const pressTake = () => {
    const b = press.registry["hint-next"].children[0];
    if (!b || !b.onclick || b.disabled || b.id === "hx-entry") return false;
    b.onclick();
    if (isAsking(press.registry["hint-body"])) press.registry["guess-tell"].onclick();
    return true;
  };
  // The walk's last instruction. Once the pieces are out, the only rung left in
  // the row charges, so the light leaves the ladder for the grid: work it out
  // and type it in, which is the one way of finishing a clue that costs nothing.
  let typing = false;
  for (let i = 0; i < 12 && !typing; i += 1) {
    if (/into the highlighted squares/.test(nuxLine(press.registry))) { typing = true; break; }
    if (!pressTake()) break;
  }
  assert(typing, "the walk ends by asking them for the answer: " + nuxLine(press.registry));
  assert(/they make [A-Z]/.test(nuxLine(press.registry)),
    "and it gives them the answer to type, so the lesson is where it goes: " + nuxLine(press.registry));
  assert(/walk-point/.test(press.registry["hint-pattern"].innerHTML || ""),
    "and the boxes lit are the strip in the panel, beside the pieces they are worked out from");
  assert(!/walk-point/.test(press.registry["hint-body"].innerHTML || ""),
    "and nothing else in the panel is pointed at: the line has given the answer");
  assert(!press.registry["spotlight"].classList.contains("hidden"),
    "with the scrim still up around them — the walk lightboxes every step it has");
  for (let i = 0; i < 12 && Number(press.storage["ct:nux"]) < 2; i += 1) {
    if (!pressTake()) break;
  }
  assert(press.storage["ct:nux"] === "2",
    "the whole ladder spends exactly one line: " + press.storage["ct:nux"]);
  assert(press.registry["spotlight"].classList.contains("hidden"),
    "and the scrim goes out with it — there is no next rung to point at");
  press.registry["reset-puzzle"].onclick();
  for (let i = 0; i < 12 && Number(press.storage["ct:nux"]) < 4; i += 1) {
    if (!pressTake()) break;
  }
  // The walk ends by saying it has ended, rather than by a line simply not
  // coming back — and with nothing lit, because there is nothing left to show.
  assert(!press.registry["nux"].classList.contains("hidden")
         && /that is the tour/i.test(nuxLine(press.registry)),
    "the last line says the tour is over: " + nuxLine(press.registry));
  assert(press.registry["spotlight"].classList.contains("hidden"),
    "and points at nothing: the page is handed back");
  for (let i = 0; i < 12 && Number(press.storage["ct:nux"]) < 5; i += 1) {
    if (!pressTake()) break;
  }
  assert(press.registry["nux"].classList.contains("hidden"),
    "the lines are finite: " + nuxLine(press.registry));
  assert(Number(press.storage["ct:nux"]) >= 5,
    "the cursor is spent past the last line: " + press.storage["ct:nux"]);

  // The other side of the same decision: a tally of more than one day is a
  // returning solver, who must never be taught the site.
  const regular = require("../fake_dom.js").boot({
    storage: { "ct:seen": JSON.stringify({ last: today, days: 5 }) } });
  assert(regular.registry["welcome"].classList.contains("hidden"),
    "a regular is not stopped by the dialog");
  assert(regular.registry["nux"].classList.contains("hidden"),
    "a regular gets no line: " + nuxLine(regular.registry));
  assert(regular.storage["ct:nux"] === "null",
    "and is marked owed none of them, once: " + regular.storage["ct:nux"]);
}
// --- the stats panel is derived from the saves, and only from them ---
// Booted fresh with saves planted, the way a device that has been solving for
// a while arrives: every figure has to come out of those saves and nothing the
// app stored beside them. Three finished puzzles: D forty days ago with three
// hints on every clue, A two days ago clean, B yesterday with one clue on two
// hints and one on a revealed letter.
{
  const shim = (id) => {
    const w = { CRYPTIC_PUZZLES: {} };
    new Function("window", fs.readFileSync(path.join(ROOT, "puzzles", id + ".js"), "utf8"))(w);
    return w.CRYPTIC_PUZZLES[id];
  };
  const noon = (daysAgo) => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate() - daysAgo, 12).getTime(); };
  const square = (e, i) => (e.position.x + (e.direction === "across" ? i : 0)) + ","
    + (e.position.y + (e.direction === "across" ? 0 : i));
  // A finished save: every square right, each clue charged `cost(e)` rungs.
  const finished = (puz, at, cost = () => 0, extra = {}) => {
    const letters = {}, letterAt = {}, solvedWith = {};
    puz.entries.forEach((e) => {
      for (let i = 0; i < e.length; i++) { letters[square(e, i)] = e.solution[i]; letterAt[square(e, i)] = at; }
      solvedWith[entryId(e)] = cost(e);
    });
    return JSON.stringify(Object.assign({ letters, letterAt, solvedWith, hintsShown: {}, hintsEarned: {},
      revealsUsed: {}, timing: { solvedAt: at }, updated: at }, extra));
  };
  // Clues, counted the way the scorebar counts them: a linked group is one.
  // A further answer a light leads (alsoLeads) is a clue of its own.
  const clueCount = (puz) => puz.entries.filter((e) => !puz.entries.some((l) =>
    l !== e && groupsOf(l).some((grp) => grp.slice(1).includes(entryId(e))))).length
    + puz.entries.reduce((n, e) => n + (e.alsoLeads || []).length, 0);
  const A = shim("cryptic-30066"), B = shim("quiptic-1397"), D = shim("quiptic-1398");
  const [b1, b2] = B.entries.filter((e) => !e.group);
  const planted = {
    "ct:seen": JSON.stringify({ last: "2000-01-01", days: 5 }),
    "ct:quiptic-1398": finished(D, noon(40), () => 3),
    "ct:cryptic-30066": finished(A, noon(2)),
    "ct:quiptic-1397": finished(B, noon(1), (e) => (e === b1 ? 2 : 0), { revealsUsed: { [entryId(b2)]: 1 } }),
  };
  // By clue type: each solved clue under every type its annotation names, the
  // clean share and hints per clue recounted here from the same saves.
  const typeOf = (e) => ((e.annotation || e.blog || {}).type || []);
  const leaders = (puz) => puz.entries.filter((e) => !puz.entries.some((l) =>
    l !== e && (l.group || []).slice(1).includes(entryId(e))));
  const byType = {};
  [[A, () => 0], [B, (e) => (e === b1 ? 2 : e === b2 ? 1 : 0)], [D, () => 3]].forEach(([puz, cost]) =>
    leaders(puz).forEach((e) => typeOf(e).forEach((t) => {
      const r = byType[t] = byType[t] || { n: 0, clean: 0, cost: 0 };
      r.n++; r.cost += cost(e); if (!cost(e)) r.clean++;
    })));
  const ranked = Object.entries(byType).filter(([, r]) => r.n >= 5)
    .sort(([, a], [, b]) => b.clean / b.n - a.clean / a.n || a.cost / a.n - b.cost / b.n);
  const weakest = ranked[ranked.length - 1][0];
  const d = require("../fake_dom.js").boot({ query: "?p=quiptic-1396", storage: planted });
  const reg = d.registry;
  // The practise link needs an unsolved clue of the weakest type in a puzzle the
  // app has loaded, and a fresh boot loads only the open puzzle, the saved ones
  // and the newest: which of them holds a clue of that type is a fact about
  // whatever was published and annotated last, not about the stats. So the
  // newest annotated puzzle that holds one is loaded here, the way a visitor
  // who had browsed to it would have.
  const planter = global.CRYPTIC_INDEX.puzzles.find((p) => p.annotated && !(p.tags || []).includes("jigsaw")
    && !(p.tags || []).includes("numbered-jigsaw") && !(p.id in planted) && !("ct:" + p.id in planted)
    && p.id !== "quiptic-1396" && (() => {
      const puz = shim(p.id);
      return puz && puz.entries.some((e) => e.solution && !e.offGrid && typeOf(e).includes(weakest));
    })());
  assert(planter, "some annotated puzzle holds a clue of the weakest type, " + weakest + ", to practise");
  if (planter) d.window.CRYPTIC_PUZZLES[planter.id] = shim(planter.id);
  reg["btn-stats"].onclick();
  const html = reg["stats-body"].innerHTML;
  const stat = (label) => (new RegExp(`<strong>([^<]*)</strong><span>${label}</span>`).exec(html) || [])[1];
  const solved = clueCount(A) + clueCount(B) + clueCount(D), clean = clueCount(A) + clueCount(B) - 2;
  assert(!reg["stats-panel"].classList.contains("hidden"), "the Stats button opens the stats panel");
  assert(stat("puzzles finished") === "3", "three finished puzzles: " + stat("puzzles finished"));
  assert(stat("clues solved") === String(solved), `${solved} clues solved: ` + stat("clues solved"));
  assert(stat("with no hints") === Math.round(100 * clean / solved) + "%",
    "clean is the share priced at nothing, by the scorebar's own rule: " + stat("with no hints"));
  const bars = [...html.matchAll(/<span class="hist-bar"[^>]*>(\d+)<\/span>/g)].map((m) => +m[1]);
  assert(String(bars) === String([clean, 1, 1, clueCount(D)]),
    "the histogram buckets clues at 0, 1, 2 and 3+ hints, a revealed letter counting as one: " + bars);
  assert(/fell from 3\.0 to 0\.\d over 30 days/.test(html),
    "the trend compares the last 30 days with the 30 before: " + (/Your hints[^<]*/.exec(html) || [])[0]);
  assert(/<strong>2 days<\/strong> in a row/.test(html) && /best 2 days/.test(html),
    "yesterday and the day before are a live streak of two, nothing finished today yet");
  assert(/<strong>2<\/strong>-day streak/.test(reg["streak"].innerHTML),
    "and the streak shows beside the scorebar, outside the panel: " + reg["streak"].innerHTML);
  const shown = [...html.matchAll(/<li class="(reached|ahead)">/g)].map((m) => m[1]);
  assert(/<li class="reached">First puzzle with no hints/.test(html)
    && shown.filter((c) => c === "reached").length <= 3 && shown.filter((c) => c === "ahead").length === 2,
    "the last three milestones reached are listed with their day, then the next two: " + shown);
  assert(!/\b(seconds?|minutes?|hours?|time|speed|fast)\b/i.test(html.replace(/<[^>]*>/g, " ")),
    "the stats never mention time or speed: the score counts hints");
  // The rows the page shows, against the counts made above.
  const typeRows = [...html.matchAll(/<div class="type-row([^"]*)"><span class="type-label">([^<]*)<\/span>.*?<span class="type-num">([^<]*)<\/span>/g)]
    .map((m) => ({ cls: m[1], label: m[2], num: m[3] }));
  const labelOf = Object.fromEntries(global.CRYPTIC_INDEX.clueTypes.types.map((t) => [t.name, t.label]));
  assert(typeRows.length === Object.keys(byType).length, "a row per clue type solved: " + JSON.stringify(typeRows));
  Object.entries(byType).forEach(([t, r]) => {
    const row = typeRows.find((x) => x.label === labelOf[t]);
    const want = (r.n >= 5 ? Math.round(100 * r.clean / r.n) + "%" : "–") + " · " + (Math.round(10 * r.cost / r.n) / 10).toFixed(1);
    assert(row && row.num === want, `${t}: ${want}, fewer than 5 clues unranked: ` + JSON.stringify(row));
    assert(row.cls.includes("few") === (r.n < 5), `${t} is marked few exactly when under 5 clues`);
  });
  assert(typeRows.find((x) => x.cls.includes("weakest")).label === labelOf[weakest],
    "the weakest is the ranked type with the lowest clean share: " + weakest);
  const practise = /<a class="practise" href="[^"]*\?p=([^&"]+)&c=(\d+[AD])">Practise your weakest/.exec(html);
  assert(practise, "a practise link names a puzzle and a clue: " + (/<a class="practise[^>]*>/.exec(html) || [])[0]);
  const [, pid, pref] = practise;
  const target = global.window.CRYPTIC_PUZZLES[decodeURIComponent(pid)];
  const clue = target && target.entries.find((e) => e.number + (e.direction === "across" ? "A" : "D") === pref);
  assert(clue && typeOf(clue).includes(weakest) && !planted["ct:" + decodeURIComponent(pid)],
    `and it opens an unsolved ${weakest} clue: ${pid} ${pref}`);

  // The shelf: finished in each series with a save, most first, never out of
  // the archive's size (that total is daunting and only says how much we hold).
  const shelf = [...html.matchAll(/<div class="shelf-row">[\s\S]*?<span class="shelf-n">([^<]*)<\/span>/g)].map((m) => m[1]);
  assert(String(shelf) === String(["2", "1"]),
    "the shelf holds quiptic 2 then cryptic 1 finished, and no series untouched: " + shelf);
  assert(!/\//.test(shelf.join("")), "and no shelf count is out of a total: " + shelf);

  // The year: a cell per local day since the Sunday 51 weeks back, shaded by
  // clues solved, a clean finish ringed.
  const cells = [...html.matchAll(/<rect [^>]*class="(l\d)( clean)?"><title>([^<]*)<\/title>/g)];
  assert(cells.length === 51 * 7 + new Date().getDay() + 1, "52 weeks of days up to today: " + cells.length);
  // The day as app.js's localDay writes it, read out of app.js so the two cannot drift.
  const dayLabel = (() => {
    const src = require("../app_src").read(ROOT);
    const from = src.indexOf("const MONTHS = ");
    const to = src.indexOf("\n", src.indexOf("function localDay", from));
    assert(from > 0 && to > from, "MONTHS and localDay are still in app.js to be read");
    const localDay = new Function(src.slice(from, to) + "\n  return localDay;")();
    return (t) => localDay(new Date(t));
  })();
  const cellOn = (t) => cells.find((m) => m[3].startsWith(dayLabel(t) + ":"));
  assert(cellOn(noon(2))[3].startsWith(`${dayLabel(noon(2))}: ${clueCount(A)} clues`) && cellOn(noon(2))[2],
    "two days ago holds A's clues and is ringed for its clean finish: " + cellOn(noon(2))[0]);
  assert(cellOn(noon(1))[3].includes(`${clueCount(B)} clues`) && !cellOn(noon(1))[2],
    "yesterday holds B's clues, not ringed, B having needed hints: " + cellOn(noon(1))[0]);
  assert(cellOn(noon(3))[1] === "l0", "a day with nothing solved is unshaded");
  assert(cells[cells.length - 1][3].startsWith(dayLabel(Date.now()) + ":"), "the last cell is today");

  const rank = (/<p class="rank"><strong>(\w+)/.exec(html) || [])[1];
  assert(rank && rank !== "Novice" && /Next, \w+: /.test(html), "clean solves earn a rank above Novice: " + rank);

  // Ranks count clean and low-hint solves, not volume: the same clues, every
  // one bought with hints, is still a Novice.
  const dirty = Object.assign({}, planted, {
    "ct:cryptic-30066": finished(A, noon(2), () => 2),
    "ct:quiptic-1397": finished(B, noon(4), () => 3),
  });
  const d2 = require("../fake_dom.js").boot({ query: "?p=quiptic-1396", storage: dirty });
  d2.registry["btn-stats"].onclick();
  const html2 = d2.registry["stats-body"].innerHTML;
  assert(/<p class="rank"><strong>Novice/.test(html2), "hints bought never raise the rank: " + html2.slice(0, 80));
  assert(/<strong>0 days<\/strong> in a row/.test(html2) && /best 1 day\b/.test(html2),
    "two days since the last finish ends the streak, and apart they are runs of one");
  assert(d2.registry["streak"].innerHTML === "", "no streak, nothing beside the scorebar");

  // A solve that reaches a milestone pops a toast per achievement, each a link
  // to the stats, and the next solve that reaches none pops nothing.
  const d3 = require("../fake_dom.js").boot({ query: "?p=quiptic-1396",
    storage: { "ct:seen": JSON.stringify({ last: "2000-01-01", days: 5 }) } });
  const typeIn = (dom, e) => {
    dom.registry["clue-" + entryId(e)].listeners.click[0]();
    e.solution.split("").forEach((c) => dom.docListeners["keydown"][0](
      { key: c, preventDefault() {}, shiftKey: false, target: dom.registry["kbd"] }));
  };
  const Q = global.window.CRYPTIC_PUZZLES["quiptic-1396"];
  const [q1, q2] = Q.entries.filter((e) => !e.group && e.direction === "across");
  const toasts = d3.registry["toasts"].children;
  assert(toasts.length === 0, "a fresh page has no toasts");
  typeIn(d3, q1);
  const said = toasts.map((t) => t.innerHTML);
  assert(said.length === 2 && /First clue solved/.test(said[0]) && /First clue with no hints/.test(said[1])
    && said.every((h) => /href="#stats"/.test(h)),
    "the first clean solve pops a toast per milestone, each linking to the stats: " + said.join(" | "));
  typeIn(d3, q2);
  assert(toasts.length === 2, "and the next solve, reaching none, pops nothing: " + toasts.length);
  assert(d3.registry["stats-panel"].classList.contains("hidden"), "the stats are closed until asked for");
  toasts[0].onclick({ preventDefault() {}, target: toasts[0] });
  assert(!d3.registry["stats-panel"].classList.contains("hidden"), "clicking a toast opens the stats");

  // Achievements earned before this page loaded, or on another device, never
  // toast: the planted saves already hold every early milestone and a rank, and
  // one more clean clue reaches none of them again.
  const d4 = require("../fake_dom.js").boot({ query: "?p=quiptic-1396", storage: planted });
  typeIn(d4, q1);
  const again = d4.registry["toasts"].children.map((t) => t.innerHTML).join(" | ");
  assert(!/First clue|Rank:/.test(again), "nothing already earned is announced again: " + again);
}

// --- a jigsaw's clue list and clue picks say nothing about where answers go ---
{
  const ID = "cryptic-24331";   // "fit them into the diagram jigsaw-wise"
  const d = require("../fake_dom.js").boot({ query: "?p=" + ID });
  const reg = d.registry;
  const J = global.window.CRYPTIC_PUZZLES[ID];
  const list = reg["clues-across"].children;
  assert(list.length === J.entries.length && reg["clues-down"].children.length === 0,
    "a jigsaw's clues are one list, with no Down section");
  assert(!list.some((li) => /clue-num/.test(li.innerHTML)), "a jigsaw's clue list carries no clue numbers");
  assert(!reg["grid"].children.some((el) => /class="num"/.test(el.innerHTML)), "a jigsaw's grid carries no numbers");
  const lit = () => reg["grid"].children.map((el) => (el.classList.contains("hl") || el.classList.contains("sel") ? 1 : 0)).join("");
  const before = lit();
  list[list.length - 1].listeners.click[0]();
  assert(lit() === before, "picking a jigsaw clue lights no square of the grid");
  assert(!/entry-tag/.test(reg["hint-clue"].innerHTML) && reg["hint-pattern"].innerHTML === "",
    "a picked jigsaw clue's panel names no number and draws no letter strip of its squares");
}

// --- every hint rule links to a section the lesson really has ---
// The indicator and type rungs end on a general rule for the device with a
// link into /learn/, and the finish recap links each device it counts the same
// way. Every clue type and every family needs a rule, and every `learn` id has
// to be an id in tools/tutorial.html, or the link lands at the top of the page.
{
  const src = require("../app_src").read(ROOT);
  const tableOf = (name) => {
    const at = src.indexOf(`const ${name} = {`);
    assert(at >= 0, `app.js defines ${name}`);
    return src.slice(at, src.indexOf("\n  };\n", at));
  };
  const keysOf = (t) => [...t.matchAll(/^ {4}(\w+): \{ learn: "([a-z-]+)"/gm)].map((m) => [m[1], m[2]]);
  const devices = keysOf(tableOf("DEVICE_RULES")), families = keysOf(tableOf("FAMILY_RULES"));
  const types = JSON.parse(fs.readFileSync(path.join(ROOT, "tools", "data", "clue_types.json"), "utf8"));
  const missingT = types.types.map((t) => t.name).filter((n) => !devices.some(([k]) => k === n));
  assert(!missingT.length, "every clue type has a rule in DEVICE_RULES — missing " + missingT);
  const missingF = types.families.map((f) => f.name).filter((n) => !families.some(([k]) => k === n));
  assert(!missingF.length, "every family has a rule in FAMILY_RULES — missing " + missingF);
  const lesson = fs.readFileSync(path.join(ROOT, "tools", "tutorial.html"), "utf8");
  const dead = [...devices, ...families].filter(([, id]) => !lesson.includes(`id="${id}"`));
  assert(!dead.length, "every rule's lesson link has its section in tools/tutorial.html — missing "
    + dead.map(([k, id]) => `${k} → #${id}`).join(", "));
}
