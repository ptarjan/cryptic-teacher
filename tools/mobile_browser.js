// A real headless Chromium, emulating an iPhone running the home-screen app:
// 390x844 touch viewport, display-mode standalone, coarse pointer, no hover,
// and touch input dispatched as real touchStart/Move/End events (a swipe).
// The fake-DOM tests cannot see scrolling or :hover/:active at all; this can.
//
//     const { withPhone } = require("./mobile_browser.js");
//     await withPhone(async ({ goto, ev, swipe, sleep }) => { ... });
//
// Serves the repo root on an ephemeral port, drives Chromium over the DevTools
// protocol (Node's global WebSocket, so no npm dependency). withPhone resolves
// to false, after saying why, when there is no Chromium: callers skip.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");
const ROOT = path.join(__dirname, "..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json", ".png": "image/png" };

function findChromium() {
  for (const p of [process.env.CHROMIUM, "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]) {
    if (p && fs.existsSync(p)) return p;
  }
  return null;
}

async function withPhone(body) {
  const bin = findChromium();
  if (!bin || typeof WebSocket !== "function") { console.log("SKIP: no Chromium (set CHROMIUM) or no global WebSocket"); return false; }
  // puzzles/index.js is generated, as for fake_dom; a rebuild reads every puzzle
  // file (minutes), so one already on disk is used as it is.
  if (!fs.existsSync(path.join(ROOT, "puzzles", "index.js"))) require("./reindex.js").reindex();
  const server = http.createServer((req, res) => {
    let p = path.join(ROOT, decodeURIComponent(req.url.split("?")[0].split("#")[0]));
    if (p.endsWith(path.sep)) p += "index.html";
    if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "content-type": TYPES[path.extname(p)] || "application/octet-stream" });
    fs.createReadStream(p).pipe(res);
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const site = "http://127.0.0.1:" + server.address().port;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ct-phone-"));
  const port = 9300 + Math.floor(Math.random() * 500);
  const ch = spawn(bin, ["--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=" + port,
    "--user-data-dir=" + dir, "about:blank"], { stdio: "ignore" });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    let tgt;
    for (let i = 0; i < 60 && !tgt; i++) {
      try { tgt = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch (e) { /* not up */ }
      if (!tgt) await sleep(200);
    }
    if (!tgt) throw new Error("Chromium never opened a page");
    const ws = new WebSocket(tgt.webSocketDebuggerUrl);
    await new Promise((r) => { ws.onopen = r; });
    let id = 0; const pend = {};
    ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } };
    const send = (method, params = {}) => new Promise((r) => { pend[++id] = r; ws.send(JSON.stringify({ id, method, params })); });
    const ev = async (e) => {
      const r = await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true });
      if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
      return r.result.result.value;
    };
    await send("Page.enable");
    await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
    await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
    await send("Emulation.setEmulatedMedia", { features: [{ name: "display-mode", value: "standalone" },
      { name: "pointer", value: "coarse" }, { name: "hover", value: "none" }] });
    await send("Page.addScriptToEvaluateOnNewDocument", { source: "Object.defineProperty(navigator,'standalone',{get:()=>true})" });
    const touch = (type, x, y) => send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x, y }] });
    // A finger dragging from y1 to y2; with `hold`, it stays down (no lift) so
    // a caller can look at the page mid-gesture.
    const swipe = async (x, y1, y2, hold) => {
      await touch("touchStart", x, y1);
      for (let i = 1; i <= 8; i++) { await touch("touchMove", x, y1 + (y2 - y1) * i / 8); await sleep(16); }
      if (!hold) { await touch("touchEnd"); await sleep(300); }
    };
    const lift = () => touch("touchEnd");
    // Until the app has drawn its tab bar: the 14MB index and the sandbox's
    // missing network (analytics) make the load slow, so poll rather than guess.
    const goto = async (p) => {
      await send("Page.navigate", { url: site + p });
      for (let i = 0; i < 150; i++) {
        await sleep(200);
        try { if (await ev("!!document.querySelector('.tabbar a') && typeof window.CRYPTIC_PUZZLES === 'object'")) break; } catch (e) { /* mid-navigation */ }
      }
      // A fresh profile gets the first-visit welcome dialog (a fixed, full-screen
      // modal), which would catch every touch; the people this tests are returning.
      await ev("(document.getElementById('welcome-skip') || { click() {} }).click()");
      await sleep(500);
    };
    await body({ goto, ev, swipe, lift, sleep, send, site });
    ws.close();
    return true;
  } finally {
    await new Promise((r) => { ch.once("exit", r); ch.kill("SIGKILL"); });
    server.close();
    fs.rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}
module.exports = { withPhone };
