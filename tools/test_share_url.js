/* Picking a puzzle points the address bar at it, from whatever the bar said
   before; and the picker's menus are still set when you come back to it.

     node tools/test_share_url.js

   The harness's replaceState is swapped for one that resolves each URL against
   the current bar, as a browser does, so what is asserted is the address a
   reload or a share would actually open — not the string app.js passed.

   1. everyPickLands: from the site root, pick a puzzle with a write-up page,
      then one without, then the first again. Each pick leaves the bar naming
      the puzzle just picked: /puzzles/<id>/ for one with a page, the site root
      with ?p=<id> for one without — never /puzzles/<a>/?p=<b>, which reloads
      as a.
   2. throttledStillOpens: replaceState throwing (Safari's rate limit) does not
      stop the puzzle opening. Mirror: the same pick with a working
      replaceState does move the bar, so the throw really was in the path.
   3. menusKept: a paper and difficulty chosen in the picker are still chosen
      after opening a puzzle and coming back, and after a reload; the search
      box is the one thing that starts empty.
   4. bareNumberNavigates: ?p=<bare number> of a puzzle no other paper numbers
      the same is a real navigation to that puzzle's own address, keeping &c=,
      with the tab flag that sends the write-up back into the app; a shared
      number goes to the newest. Mirror: ?p=<full id> opens with no navigation. */
"use strict";
const { boot } = require("./fake_dom.js");

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
  return ok;
};

const HOME = "https://cryptic.paultarjan.com/";

function start(storage) {
  const d = boot({ storage });
  const h = global.window.history;
  const state = { bar: HOME, throws: false };
  h.replaceState = (_s, _t, url) => {
    if (state.throws) throw new Error("SecurityError: Attempt to use history.replaceState() more than 100 times per 10 seconds");
    state.bar = new URL(String(url), state.bar).href;
  };
  const reg = d.registry;
  // Opens the picker, searches for the puzzle's number and presses the row that
  // opens it — told apart by the tab flag pointUrlAtPuzzle sets, since a number
  // alone can match several papers.
  const pick = (p) => {
    reg["btn-picker"].onclick();
    reg["picker-search"].value = String(p.number);
    reg["picker-search"].listeners.input.forEach((f) => f());
    const key = `ct:app:${p.id}`;
    global.sessionStorage.removeItem(key);
    const rows = reg["picker-list"].children.slice();
    for (const li of rows) {
      const btn = li.children[0];
      if (!btn || !btn.onclick) continue;
      btn.onclick({ target: {} });
      if (global.sessionStorage.getItem(key)) return true;
      reg["btn-picker"].onclick();
    }
    return false;
  };
  return { d, reg, state, pick };
}

const where = (bar) => {
  const u = new URL(bar);
  const page = u.pathname.match(/^\/puzzles\/([^/]+)\/$/);
  return page ? page[1] : (u.pathname === "/" ? u.searchParams.get("p") : null);
};

{
  const { state, pick } = start();
  const all = global.window.CRYPTIC_INDEX.puzzles;
  const withPage = all.find((p) => p.hasSolutions && p.annotated);
  const noPage = all.find((p) => !p.hasSolutions);
  if (!withPage || !noPage) {
    check(false, "the index should hold a puzzle with a page and one without");
  } else {
    for (const p of [withPage, noPage, withPage, noPage]) {
      if (!check(pick(p), `the picker opens ${p.id}`)) continue;
      check(where(state.bar) === p.id,
        `after picking ${p.id} the bar names it (bar: ${state.bar})`);
    }
    check(new URL(state.bar).pathname === "/",
      `a puzzle with no page is addressed from the site root, not from the last page (bar: ${state.bar})`);

    // 2. A throwing replaceState must not take the open down with it.
    state.throws = true;
    const before = state.bar;
    check(pick(withPage), `with replaceState throwing, ${withPage.id} still opens`);
    check(state.bar === before, "and the bar is left as it was");
    state.throws = false;
    check(pick(noPage) && where(state.bar) === noPage.id,
      `mirror: with replaceState working the same pick moves the bar to ${noPage.id}`);
  }
}

// 3. The menus survive opening a puzzle, and a reload.
{
  const { d, reg, pick } = start();
  reg["btn-picker"].onclick();
  const values = (id) => [...reg[id].innerHTML.matchAll(/<option value="([^"]+)"/g)].map((m) => m[1]);
  const paper = values("picker-paper")[0];
  const band = values("picker-band")[0];
  if (check(paper && band, "both menus offer something to choose")) {
    reg["picker-paper"].value = paper;
    reg["picker-paper"].listeners.change.forEach((f) => f());
    reg["picker-band"].value = band;
    reg["picker-band"].listeners.change.forEach((f) => f());
    const some = global.window.CRYPTIC_INDEX.puzzles.find((p) => p.annotated);
    pick(some);
    reg["btn-picker"].onclick();
    check(reg["picker-paper"].value === paper && reg["picker-band"].value === band,
      `back in the picker after opening ${some.id}, the menus still say ${paper} / ${band}`);
    check(reg["picker-search"].value === "", "the search box starts empty");

    const again = start(Object.assign({}, d.storage)).reg;
    again["btn-picker"].onclick();
    check(again["picker-paper"].value === paper && again["picker-band"].value === band,
      "after a reload the menus still say what they were set to");
    // Mirror: setting them back to "all" is remembered too.
    again["picker-paper"].value = "";
    again["picker-paper"].listeners.change.forEach((f) => f());
    again["btn-picker"].onclick(); again["btn-picker"].onclick();
    check(again["picker-paper"].value === "", "choosing All papers is remembered as all");
  }
}

// 4. A bare number navigates to its puzzle's own address.
{
  const all = global.window.CRYPTIC_INDEX.puzzles;
  const count = {};
  all.forEach((p) => { count[p.number] = (count[p.number] || 0) + 1; });
  const unique = all.find((p) => p.hasSolutions && count[p.number] === 1);
  const shared = all.find((p) => count[p.number] > 1);
  const bootOn = (query) => {
    const d = boot({ query });
    return { replaced: global.location.replaced, session: global.sessionStorage, d };
  };
  if (check(unique && shared, "the index holds a unique and a shared number")) {
    const u = bootOn(`?p=${unique.number}&c=3D`);
    check(u.replaced && new URL(u.replaced).pathname === `/puzzles/${unique.id}/`
      && new URL(u.replaced).searchParams.get("c") === "3D",
      `?p=${unique.number}&c=3D navigates to /puzzles/${unique.id}/?c=3D (got ${u.replaced})`);
    check(u.session.getItem(`ct:app:${unique.id}`) === "1",
      "with the flag that sends the write-up back into the app");
    const newest = all.find((p) => p.number === shared.number);
    const s = bootOn(`?p=${shared.number}`);
    check(s.replaced && s.replaced.includes(encodeURIComponent(newest.id)),
      `?p=${shared.number}, shared, navigates to the newest, ${newest.id} (got ${s.replaced})`);
    const f = bootOn(`?p=${unique.id}`);
    check(!f.replaced, `mirror: ?p=${unique.id} opens in place (navigated to ${f.replaced})`);
  }
}

if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
console.log("all share-url checks passed");
