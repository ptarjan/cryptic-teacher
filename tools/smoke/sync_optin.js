// Sync being opt-in, and localStorage persistence (which also ends the run).
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, SLICE, UNCACHED, assert, ciCache, corpus, fs, openId, path, registry, shapesSeen,
  storage } = T;
// --- sync is opt-in, and off means off ---
// Nobody's crossword leaves their browser because they visited the page. The
// only thing that turns it on is pressing the button, and the only thing that
// identifies you afterwards is the code — no email is ever asked for, so none
// can ever leak.
{
  assert(!storage["ct:sync"],
    "sync stays off until it is switched on — no code is minted just by loading the page");
  const src = require("../app_src").read(ROOT);
  const page = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  assert(/const SYNC_ENDPOINT = "http/.test(src), "the sync endpoint is configured");
  // Structural, not a search for the words: the page must never grow a field
  // that collects a credential. A password here would protect crossword letters
  // and create something worth stealing, which is the wrong trade in both
  // directions.
  assert(!/type="(password|email)"/.test(page),
    "the page asks for no password and no email — the code is the whole identity");
  const fetches = src.match(/fetch\(.*/g) || [];
  assert(/syncOn\(\)/.test(src) && fetches.filter((f) => f.includes('"/s/"')).length === 1,
    "there is exactly one place that sends a crossword, and it is gated on sync being on");
  // And the page as a whole leaves nothing else: a sentence the reader typed on
  // purpose about a bad hint, and a push subscription — an address, not a
  // crossword, and it only leaves when a paper is ticked. at() is the site's
  // own origin, so fetching a puzzle file from it sends nothing out.
  assert(fetches.every((f) => f.includes('"/s/"') || f.includes('"/r"')
      || f.includes('"/n"') || f.includes("/v?p=") || f.includes('"/v"')
      || f.startsWith('fetch(at("puzzles/') || f.startsWith('fetch(at("./")')
      || f.startsWith('fetch(at("sw.js")')),
    "nothing else leaves the page: " + fetches.join(" | "));
  // The counter is the only other thing that reaches the network, and what it
  // can carry is one name from the shared list — no grid, no code, no id. Two
  // separate things go to the same Worker and only one of them is about you.
  assert((src.match(/sendBeacon\(/g) || []).length === 2,
    "two things report to the Worker without being asked to: a milestone and a vote");
  assert(/sendBeacon\(\s*SYNC_ENDPOINT[^;]*new Blob\(\[name\]/.test(src),
    "and the whole of what the counter sends is the event name");
  // A vote is the other one, and what it carries is what was rated and which
  // way — no grid, no code, no id, and nothing that says who. The Worker keeps
  // it the same way (see /v there): the key name is the record.
  assert(/const body = `\$\{target\}\|\$\{verdict\}`/.test(src) &&
         /sendBeacon\(SYNC_ENDPOINT \+ "\/v", new Blob\(\[body\]/.test(src),
    "and the whole of a vote is the thing rated and the verdict");

  // One VAPID pair, two runtimes. The page and the Worker cannot share a file,
  // so the public key is written in both; if the copies drift, every push is
  // signed by a key the browser rejects and the only symptom is a silent 403.
  const wrangler = fs.readFileSync(path.join(ROOT, "sync/wrangler.toml"), "utf8");
  const appKey = (src.match(/VAPID_PUBLIC_KEY = "([A-Za-z0-9_-]+)"/) || [])[1];
  const workerKey = (wrangler.match(/^VAPID_PUBLIC_KEY = "([A-Za-z0-9_-]+)"/m) || [])[1];
  assert(appKey && appKey === workerKey,
    "app.js and sync/wrangler.toml carry the same VAPID public key");

  // A service worker's URL is its identity: the browser keys the registration on
  // it and re-fetches that same URL to update. A stamped sw.js?v=<hash> would
  // register a second worker while the first kept the subscription, so sw.js is
  // never stamped and never listed as an asset.
  const stamp = fs.readFileSync(path.join(ROOT, "tools/stamp_assets.py"), "utf8");
  assert(!/["']sw\.js["']/.test(stamp), "sw.js is not a stamped asset");
  assert(/serviceWorker\.register\((at\()?"sw\.js"\)?\)/.test(src),
    "and the page registers it at its bare URL");

  // The bridge ignores a message its own bot wrote unless it carries the wake
  // marker, so an alert posted straight to Discord is a failure report that
  // starts nothing. The bridge's tools/wake.sh owns that marker; this file must go through
  // it rather than hold a second copy of the bridge's rules.
  const alerts = fs.readFileSync(path.join(ROOT, "tools/alert.sh"), "utf8");
  assert(/"\$wake_sh" -c "\$ALERT_CHANNEL"/.test(alerts),
    "tools/alert.sh sends its alerts through the bridge's wake.sh");
  assert(!/discord\.com\/api/.test(alerts),
    "and posts to Discord nowhere itself");
  /* The quiet-hours control, in the panel that already asks which papers.
     Seven in the morning is the shipped default and is written into the markup
     as well as into app.js: a device that never opens this panel still gets the
     hold, because refreshNotify() re-asserts on every load. */
  const notifyHTML = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  assert(/<input type="time" id="notify-after" value="07:00">/.test(notifyHTML),
    "the notify panel offers a time of day, defaulting to 07:00");
  assert(/NOTIFY_AFTER_DEFAULT = "07:00"/.test(src),
    "and app.js defaults to the same 07:00 when nothing is stored");
  // The setting is a setting: without this the sync scan uploads "ct:notify-after"
  // as though it were a half-finished crossword called "notify-after".
  assert(/SYNC_RESERVED = \{[^}]*"notify-after": 1/.test(src),
    "ct:notify-after is reserved from the sync scan");
  // Same rule, and this one has a second edge: hasAnySave() reads the same list
  // to decide whether this browser has been here before. Unreserved, ct:nux is a
  // save — so writing the newcomer's cursor would itself prove the newcomer is a
  // regular, and the lines would be cancelled by the act of starting them.
  assert(/SYNC_RESERVED = \{[^}]*nux: 1/.test(src),
    "ct:nux is reserved: it is a cursor, not a crossword");

  /* The papers in this panel are a checklist — one chip per row, beside its own
     checkbox — and not the picker's column of rows, so they cancel the width
     floor .badge.series carries. Left on, the floor pads the short names
     ("book", "metro") out to a width the long ones ("independent",
     "globe & mail") overrun anyway, which is nine checkboxes wearing pills at
     four different widths. Asserted on the cancelling rule, because the floor
     itself is right where it lives and must stay. */
  const chipCss = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");
  const seriesFloor = (chipCss.match(/\.badge\.series\s*\{[^}]*\}/) || [""])[0];
  assert(/min-width:\s*[1-9]/.test(seriesFloor),
    "the series pill still carries a width floor for the picker's column: "
    + seriesFloor.replace(/\s+/g, " "));
  // Comments out first: the selector is whatever precedes the brace, and a
  // prose comment above a rule would otherwise be quoted back as its name.
  const unfloored = ((chipCss.replace(/\/\*[\s\S]*?\*\//g, " ")
    .match(/[^{}]*\{[^}]*min-width:\s*0[^}]*\}/g)) || [])
    .map((r) => r.slice(0, r.indexOf("{"))).join(" ").replace(/\s+/g, " ");
  assert(/#notify-list \.badge\.series/.test(unfloored),
    "and the notify panel's one-per-row chips cancel it, so a short paper name "
    + "is not padded out to a long one's width; what cancels it today: " + unfloored.trim());
  // A panel scrolls once its content passes 70vh, and a classic scrollbar
  // takes its width out of the content box. Without a reserved gutter the
  // picker's paper chips re-wrap as the list crosses that height.
  const panelRule = (chipCss.replace(/\/\*[\s\S]*?\*\//g, " ")
    .match(/(^|\})\s*\.panel\s*\{[^}]*\}/) || [""])[0];
  assert(/overflow:\s*auto/.test(panelRule) && /scrollbar-gutter:\s*stable/.test(panelRule),
    "a .panel scrolls and reserves its scrollbar gutter: " + panelRule.replace(/\s+/g, " "));

  // Changing the time with no paper ticked must not unsubscribe the device:
  // saveNotify([]) IS the unsubscribe, so "not before eight" would read as
  // "never" and the panel would silently empty itself.
  storage["ct:notify"] = JSON.stringify([]);
  delete storage["ct:notify-after"];
  registry["notify-after"].value = "08:30";
  (registry["notify-after"].listeners.change || []).forEach((fn) =>
    fn({ target: registry["notify-after"] }));
  assert(storage["ct:notify-after"] === JSON.stringify("08:30"),
    "the chosen time is stored: " + storage["ct:notify-after"]);
  assert(storage["ct:notify"] === JSON.stringify([]),
    "and changing it with nothing ticked leaves the papers alone");
  delete storage["ct:notify"];
  delete storage["ct:notify-after"];

  // One slot, one panel. All three are drawn in the same corner at the same
  // z-index (see .panel), so a second one opened behind the first is simply
  // invisible and its button reads as dead. Asserted on the set of visible
  // panels rather than on the one being opened, because the failure is never
  // about that one.
  const PANELS = ["sync-panel", "notify-panel", "picker-panel"];
  const openPanels = () => PANELS.filter((id) => !registry[id].classList.contains("hidden"));
  registry["btn-picker"].onclick();
  assert(openPanels().join() === "picker-panel", "the picker opens on its own: " + openPanels());
  registry["btn-sync"].onclick();
  assert(openPanels().join() === "sync-panel",
    "opening sync closes the picker instead of hiding behind it: " + openPanels());
  registry["btn-notify"].onclick();
  assert(openPanels().join() === "notify-panel",
    "and notifications close sync the same way: " + openPanels());
  registry["btn-notify-close"].onclick();
  assert(openPanels().length === 0, "closing the last one leaves none open: " + openPanels());

  registry["btn-sync"].onclick();
  assert(!registry["sync-panel"].classList.contains("hidden"), "the sync panel opens");
  assert(registry["sync-off"] && !registry["sync-off"].classList.contains("hidden"),
    "with sync off the panel offers to turn it on");
  registry["sync-start"].onclick();
  const code = storage["ct:sync"] && JSON.parse(storage["ct:sync"]);
  assert(/^[2-9A-HJ-KMNP-TV-Z]{8}$/.test(code || ""),
    `the minted code is 8 characters with no 0/O/1/I/L to mistype: ${code}`);
  // Copying is the only step of sync that happens outside the app, so it is the
  // easiest one to break without noticing: the code is useless until it reaches
  // the other device, and a Copy button that quietly puts nothing on the
  // clipboard looks identical to one that works.
  assert(registry["sync-code"].textContent === code, "the panel shows the code it minted");
  registry["sync-copy"].onclick();
  assert(global.navigator.clipboard.text === code,
    "Copy puts exactly the shown code on the clipboard");

  // Taking a code has to work on a device that ALREADY has one: two devices that
  // each turned sync on separately can only be joined by one of them adopting the
  // other's code, and that is the device holding the phone at the QR. Asserted
  // against the markup, because getElementById() in the stub invents any id it is
  // asked for and would answer happily for a field nobody can reach.
  const syncOffBlock = fs.readFileSync(path.join(ROOT, "index.html"), "utf8")
    .split('<div id="sync-off">')[1].split("</div>")[0];
  assert(!syncOffBlock.includes('id="sync-join-code"'),
    "the join field lives outside the sync-off block, so sync being on cannot hide it");
  registry["sync-join-code"].value = "ABCD2345";
  registry["sync-join"].onclick();
  assert(JSON.parse(storage["ct:sync"]) === "ABCD2345",
    "a device that is already syncing can adopt another device's code");

  // Seeded rather than relied on: what is being asserted is that *stopping sync*
  // does not delete grids, not what some earlier test left lying around.
  storage["ct:99999"] = JSON.stringify({ letters: { "0,0": "K" }, updated: 1 });
  registry["sync-stop"].onclick();
  assert(!storage["ct:sync"], "stopping sync forgets the code");
  assert(storage["ct:99999"],
    "stopping sync keeps your grids — it means stop sending them, not throw them away");
  delete storage["ct:99999"];
  registry["btn-sync-close"].onclick();
}

// --- localStorage persistence happened ---
// On the REAL clock, never the fake one: this timer ends the process, and a
// test further down that drains the fake clock generously would otherwise fire
// it and stop the suite mid-file — printing a pass for the tests that had run
// and saying nothing about the ones that never did.
global.realSetTimeout(() => {
  // Keyed on the puzzle actually open, not on a fixed id prefix: a test that only
  // passes for one range of puzzle numbers is asserting the wrong thing.
  assert(storage["ct:" + openId], `progress persisted to localStorage under ct:${openId}, got ` +
    JSON.stringify(Object.keys(storage)));
  const saved = JSON.parse(storage[Object.keys(storage).find((k) => /^ct:[a-z0-9]+-\d/.test(k))]);
  // Without a timestamp the merge cannot tell two devices apart, so this is
  // written whether or not sync is on — turning it on later must not find a
  // pile of undated saves.
  assert(saved && typeof saved.updated === "number" && saved.updated > 0,
    "every save is timestamped, so it can be merged later even if sync is off today");
  const missing = Object.keys(shapesSeen).filter((k) => !shapesSeen[k]);
  if (process.env.CT_SHAPES_OUT) {
    fs.writeFileSync(process.env.CT_SHAPES_OUT, JSON.stringify({ slice: SLICE.i, of: SLICE.n, shapes: shapesSeen }));
  } else if (missing.length) {
    console.log(`(no example here of: ${missing.join("; ")}; the nightly run checks the corpus holds them)`);
  }
  // The puzzles this run swept are the list it loaded, not what
  // window.CRYPTIC_PUZZLES holds by now: the later boots replace window.
  if (process.env.CT_RESULTS_OUT && !T.failures) {
    fs.writeFileSync(process.env.CT_RESULTS_OUT, JSON.stringify(ciCache.resultsFor("tools/smoke_test.js",
      corpus.map((p) => p.id), shapesSeen, UNCACHED.deferred)));
  }
  console.log(T.failures ? `\n${T.failures} FAILURE(S)` : "\nSMOKE TEST PASSED");
  process.exit(T.failures ? 1 : 0);
}, 400);
