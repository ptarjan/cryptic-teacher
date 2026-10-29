// Offline mode end to end, in a real headless Chromium (tools/mobile_browser.js)
// with its service worker:
//
//   1. Loaded online, the app saves a batch of puzzles by itself.
//   2. "Save now" adds puzzles the device does not hold yet, and the count
//      under it goes up (Paul 10-29: "Save now seems to do nothing").
//   3. With the server gone (wifi up but dead, so navigator.onLine may still
//      say true), the app opens, the Library lists the saved puzzles and only
//      those, and one of them opens with its grid and clues (Paul 10-29:
//      "Offline should show cached puzzles").
//
//     node tests/test_offline_library.js
"use strict";
const { withPhone } = require("../tools/mobile_browser.js");
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };

(async () => {
  const ran = await withPhone(async ({ goto, ev, sleep, network }) => {
    // Polls a page expression until it is truthy; the value, or null at the deadline.
    const until = async (js, ms) => {
      for (const end = Date.now() + ms; Date.now() < end; await sleep(250)) {
        try { const v = await ev(js); if (v) return v; } catch (e) { /* mid-navigation */ }
      }
      return null;
    };
    const status = "(document.getElementById('offline-status') || {}).textContent || ''";
    const held = "caches.open('ct-puzzles-1').then((c) => c.keys()).then((k) => k.length)";

    // ---- 1. the automatic batch
    await goto("/");
    const auto = await until(`/^\\d+ puzzles ready offline$/.test(${status}) && ${status}`, 120000);
    assert(auto, "loaded online, the app saves puzzles by itself: " + await ev(status));
    const first = await ev(held);
    assert(first > 0 && auto && Number.parseInt(auto, 10) === first, `the count says what the cache holds: "${auto}" vs ${first}`);

    // ---- 2. Save now adds to it
    await ev("document.querySelector('.tabbar a[data-tab=puzzles]').click()");
    await sleep(500);
    await ev("document.getElementById('btn-offline').click()");
    const more = await until(`/^Saved \\d+ more · \\d+ puzzles ready offline$/.test(${status}) && ${status}`, 120000);
    assert(more, "Save now says what it added: " + await ev(status));
    const second = await ev(held);
    assert(second > first, `Save now adds puzzles: ${first} -> ${second}`);
    assert(more && more.endsWith(`${second} puzzles ready offline`), `...and the count is the new total: "${more}" vs ${second}`);

    // ---- 3. no network
    await network(false);
    await goto("/");
    await ev("document.querySelector('.tabbar a[data-tab=puzzles]').click()");
    const note = await until("/offline/.test(document.getElementById('picker-note').textContent) && document.getElementById('picker-note').textContent", 20000);
    assert(note && note.includes(`${second} puzzles saved on this device`), "offline, the Library says it lists the saved puzzles: " + note);
    const list = await ev(`(() => {
      const li = [...document.querySelectorAll('#picker-list li')];
      const below = Number((document.getElementById('picker-more').textContent.match(/(\\d+) more match/) || [0, 0])[1]);
      return { drawn: li.length, below, unsaved: li.filter((l) => !/saved offline/.test(l.textContent)).length };
    })()`);
    assert(list.drawn > 1, "offline, the Library lists puzzles: " + JSON.stringify(list));
    assert(list.unsaved === 0, "every puzzle listed offline is a saved one: " + JSON.stringify(list));
    assert(list.drawn + list.below === second, `every saved puzzle is listed: ${list.drawn}+${list.below} vs ${second}`);

    // One that is not already open: it opens and is playable.
    const before = await ev("document.getElementById('puzzle-title').textContent");
    const tapped = await ev("(() => { const b = document.querySelector('#picker-list li:not(.current) button'); if (b) b.click(); return !!b; })()");
    assert(tapped, "offline, the Library has a saved puzzle besides the open one");
    const opened = await until(`document.getElementById('puzzle-title').textContent !== ${JSON.stringify(before)}
      && document.querySelectorAll('#grid .cell, #grid rect, #grid td').length > 0
      && document.querySelectorAll('.clue-list li').length > 0
      && document.getElementById('puzzle-title').textContent`, 20000);
    assert(opened, "a saved puzzle opens offline with its grid and clues: " + await ev("document.getElementById('puzzle-title').textContent"));
  });
  if (!ran) return;
  if (fails.length) { fails.forEach((f) => console.log("FAIL: " + f)); process.exit(1); }
  console.log("ok: offline library");
})().catch((e) => { console.error(e); process.exit(1); });
