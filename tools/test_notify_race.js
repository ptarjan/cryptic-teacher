/* Two papers ticked in quick succession, with the network slow.

     node tools/test_notify_race.js

   "There is a race condition when checking many boxes on my windows chrome. I
   checked one and it didn't check but others worked" (Paul, 2026-09-08).

   saveNotify() takes one save at a time, which is right — two PUTs in flight
   and the slower answer is the one the Worker keeps. What was wrong was what
   happened to the tick that arrived during a save: it returned early, so the
   tick went nowhere, and then the first save finished and redrew the panel from
   the store, which unticked the box the reader had just ticked. On a fast
   connection the window is a few milliseconds and nothing is ever lost; on a
   slow one it is every box tapped after the first.

   That is behaviour across two round trips, so it cannot be read out of the
   source: this drives the real change listener in app.js against a fetch that
   does not answer until the test lets it. Shelled out from tools/smoke_test.js
   because the suite there is synchronous and a race needs promises to settle.

   Nothing here reaches the network. fetch is a function in this file. */
"use strict";
const { boot } = require("./fake_dom.js");

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};
// Promises settle on the microtask queue, which drains only when this function
// yields. Awaiting a resolved promise a few times is what gives the app its
// turn between one assertion and the next.
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

const dom = boot();
const { registry } = dom;

// Everything the push path asks the browser for, and nothing more. The
// subscription is an address; here it is a string, because the only thing the
// app does with it is JSON it into the body.
const sub = { toJSON: () => ({ endpoint: "https://example.invalid/p/1" }),
              unsubscribe: () => Promise.resolve(true) };
global.Notification = { permission: "granted",
                        requestPermission: () => Promise.resolve("granted") };
global.window.PushManager = function PushManager() {};
navigator.serviceWorker = {
  register: () => Promise.resolve({ pushManager: { getSubscription: () => Promise.resolve(sub) } }),
};

// The Worker, made to answer when this test says so. Every PUT is parked here
// with the papers it carried, and release() answers the oldest one the way the
// real Worker does: with the list it just stored.
const parked = [];
const sentSeries = [];
global.fetch = (url, opt) => {
  const series = JSON.parse(opt.body).series;
  sentSeries.push(series.join(","));
  return new Promise((resolve) => parked.push(() => resolve({
    ok: true, status: 200, json: () => Promise.resolve({ series }),
  })));
};
const release = async () => { (parked.shift() || (() => {}))(); await settle(); };

const stored = () => JSON.parse(global.localStorage.getItem("ct:notify") || "[]");
// A change event as the browser raises it: the box that moved, and its state.
const tick = (series, on) => (registry["notify-list"].listeners.change || [])
  .forEach((fn) => fn({ target: { dataset: { series }, checked: on } }));

(async () => {
  registry["btn-notify"].onclick();
  check(!registry["notify-panel"].classList.contains("hidden"), "the notify panel opens");

  tick("cryptic", true);
  await settle();
  check(parked.length === 1, "the first tick is on the wire: " + parked.length);

  // The second and third tick land while that PUT is still unanswered — which
  // is the whole bug. They must be remembered, not dropped.
  tick("everyman", true);
  tick("quiptic", true);
  await settle();
  check(parked.length === 1, "a tick during a save does not start a second save");

  await release();
  check(parked.length === 1, "the answer to the first releases the queued one");
  await release();
  check(parked.length === 0, "and nothing is left in flight");

  const end = stored().slice().sort().join(",");
  check(end === "cryptic,everyman,quiptic",
    "all three papers ticked are saved, not just the first: " + end);
  check(sentSeries[sentSeries.length - 1].split(",").length === 3,
    "and the last thing sent carried all three: " + sentSeries.join(" | "));

  // Un-ticking during a save is the same path and must not be lost either.
  tick("everyman", false);
  await settle();
  tick("quiptic", false);
  await settle();
  await release();
  await release();
  check(stored().join(",") === "cryptic",
    "un-ticking during a save takes too: " + stored().join(","));

  // The store is the truth again once it all settles, so a save that fails
  // still repaints the boxes from what the Worker actually agreed to.
  tick("everyman", true);
  await settle();
  parked.shift();                       // the answer never comes
  global.fetch = () => Promise.reject(new Error("offline"));
  tick("indysunday", true);
  await settle();
  check(stored().join(",") === "cryptic",
    "a save that never answers stores nothing: " + stored().join(","));

  console.log(failures ? `\n${failures} FAILURE(S)` : "\nNOTIFY RACE TEST PASSED");
  process.exit(failures ? 1 : 0);
})();
