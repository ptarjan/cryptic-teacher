// Offline mode end to end, in a real headless Chromium (tools/mobile_browser.js)
// with its service worker:
//
//   1. Loaded online, the app saves a batch of puzzles by itself.
//   2. A completed puzzle is dropped and not counted.
//   3. "Save now" shows progress, then adds puzzles the device does not hold yet, and the count
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

    // ---- 2. completed puzzles are not kept (Paul 10-30: "Completed puzzles
    // don't need to be saved offline"). Finish the open puzzle by writing its
    // solution into saved progress; Save now must then drop it from the device
    // and leave it out of the count.
    const solved = await ev(`(() => {
      const idx = {};
      window.CRYPTIC_INDEX.puzzles.forEach((p) => { idx[p.id] = p; });
      for (const id of Object.keys(window.CRYPTIC_PUZZLES)) {
        const puz = window.CRYPTIC_PUZZLES[id], row = idx[id];
        if (!row || !row.file || row.reprintOf || (puz.unclued || []).length) continue;
        if (!puz.entries.length || !puz.entries.every((e) => e.solution && e.position)) continue;
        if (puz.entries.some((e) => e.direction !== "across" && e.direction !== "down")) continue;
        const letters = {};
        puz.entries.forEach((e) => { for (let i = 0; i < e.length; i++) {
          letters[(e.position.x + (e.direction === "across" ? i : 0)) + "," + (e.position.y + (e.direction === "down" ? i : 0))] = e.solution[i];
        } });
        (puz.printed || []).forEach((q) => { delete letters[q.x + "," + q.y]; });
        localStorage.setItem("ct:" + id, JSON.stringify({ letters }));
        window.dispatchEvent(new StorageEvent("storage", { key: "ct:" + id }));
        return { id, file: row.file };
      }
      return null;
    })()`);
    assert(solved, "a loaded puzzle could be marked completed");
    const files = "caches.open('ct-puzzles-1').then((c) => c.keys()).then((k) => k.map((r) => decodeURIComponent(new URL(r.url).pathname)))";

    // ---- 3. Save now adds to it, and shows what it is doing (Paul 10-30:
    // "The save now button doesn't give the user feedback")
    await ev("document.querySelector('.tabbar a[data-tab=puzzles]').click()");
    await sleep(500);
    // Record every line the status shows, and whether the button was disabled
    // at that moment, so progress is checked without racing a poll.
    await ev(`(() => {
      const el = document.getElementById('offline-status'), btn = document.getElementById('btn-offline');
      window.__seen = [];
      new MutationObserver(() => window.__seen.push({ t: el.textContent, off: btn.disabled })).observe(el, { childList: true, characterData: true, subtree: true });
    })()`);
    await ev("document.getElementById('btn-offline').click()");
    const more = await until(`/^Saved \\d+ puzzles? — \\d+ puzzles ready offline$/.test(${status}) && ${status}`, 120000);
    assert(more, "Save now says what it saved: " + await ev(status));
    const seen = await ev("window.__seen");
    const prog = seen.filter((x) => /^Saving \d+ of \d+…$/.test(x.t));
    assert(prog.length > 0, "Save now shows progress while saving: " + JSON.stringify(seen));
    assert(prog.every((x) => x.off), "the button is disabled while saving");
    assert(await ev("!document.getElementById('btn-offline').disabled"), "the button is usable again afterwards");
    const second = await ev(held);
    assert(second > first, `Save now adds puzzles: ${first} -> ${second}`);
    assert(more && more.endsWith(`— ${second} puzzles ready offline`), `...and the count is the new total: "${more}" vs ${second}`);
    if (solved) {
      const left = (await ev(files)).filter((f) => f.includes("/puzzles/" + solved.file + ".gz"));
      assert(left.length === 0, "a completed puzzle is dropped from the device: " + left.join(","));
      assert(await ev(`document.getElementById('offline-status').textContent.startsWith("Saved")`), "the line stays on the result");
    }

    // ---- 4. no network
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
