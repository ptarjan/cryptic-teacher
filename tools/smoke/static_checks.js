// Checks that need no clue and no corpus: the vendored QR decoder, cache-busting
// hashes, the front-door URLs, the abbreviation glossary, the grid measuring.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, appSrc, assert, fs, path, readBuilt } = T;
// --- the vendored decoder is the build vendor/README.md pins ---
// A dependency nobody can diff is one nobody reads. The hash is written down in
// prose next to the licence, and this is what stops the prose and the file
// drifting: a swapped decoder is the one place in this repo where "it still
// works" and "it is what we vendored" are different questions.
{
  const crypto = require("crypto");
  const doc = fs.readFileSync(path.join(ROOT, "vendor/README.md"), "utf8");
  const pinned = doc.match(/sha256\s+([0-9a-f]{64})/);
  const named = doc.match(/`(jsQR-[\d.]+\.js)`/);
  if (assert(pinned && named, "vendor/README.md still pins a filename and a sha256")) {
    const file = path.join(ROOT, "vendor", named[1]);
    assert(fs.existsSync(file), `${named[1]} is the file vendor/README.md names`);
    if (fs.existsSync(file)) {
      const got = crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
      assert(got === pinned[1],
        `vendor/${named[1]} hashes to the sha256 in vendor/README.md (got ${got})`);
    }
    assert(require("../app_src").read(ROOT).includes(`"vendor/${named[1]}"`),
      "app.js fetches the decoder by the pinned filename, so a bump cannot leave a 404 behind");
  }
}

// --- the decoder actually reads the squares this page draws ---
// The encoder is ours and the decoder is not, so "it is a valid QR code" and
// "that library can read it" are two claims. This is the second one, at the
// module count and quiet zone drawSyncQr uses, which is the only case the sync
// panel ever produces.
{
  const CTQR = require("../../qr.js");
  const jsQR = require("../../vendor/jsQR-1.4.0.js");
  const url = "https://cryptic.paultarjan.com/?sync=AEQ5FEY5";
  const rows = CTQR.encode(url);
  const S = 6, QUIET = 4, n = rows.length, w = (n + QUIET * 2) * S;
  const px = new Uint8ClampedArray(w * w * 4).fill(255);
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (!rows[r][c]) continue;
      for (let y = 0; y < S; y++) {
        for (let x = 0; x < S; x++) {
          const i = (((r + QUIET) * S + y) * w + (c + QUIET) * S + x) * 4;
          px[i] = px[i + 1] = px[i + 2] = 0;
        }
      }
    }
  }
  const hit = jsQR(px, w, w, { inversionAttempts: "dontInvert" });
  assert(hit && hit.data === url, "the vendored decoder reads a square qr.js drew");
}

// --- cache busting: index.html must reference current asset hashes ---
// (mobile browsers hold GitHub Pages' 4h max-age copies otherwise — docs/APP.md)
{
  const crypto = require("crypto");
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  // Enumerated off stamp_assets.py rather than retyped, so a new asset is
  // covered by this check the moment it is stamped. A hand-kept second list is
  // a list that goes stale, and the symptom is a phone serving four-hour-old
  // JavaScript against fresh HTML.
  const stamper = fs.readFileSync(path.join(ROOT, "tools/stamp_assets.py"), "utf8");
  const assetBlock = stamper.match(/ASSETS = \[([\s\S]*?)\]/);
  assert(assetBlock, "tools/stamp_assets.py still declares ASSETS = [...]");
  const stamped = (assetBlock ? assetBlock[1].match(/"([^"]+)"/g) || [] : [])
    .map((s) => s.slice(1, -1));
  assert(stamped.includes("app-core.js") && stamped.includes("sync/merge.js"),
    "the stamped-asset list still covers the app and the sync merge rules");
  // The reference has to be there; the stamp does not. Stamping is a build
  // step, so index.html is stored bare and the deploy workflow rewrites it on
  // its own checkout — a hash committed into a tracked file is churn on every
  // asset change and the thing the nightly rebase collides in. What this
  // catches is an asset renamed or dropped out of the page; the sweep below is
  // what catches a stamp that has gone stale.
  // An asset only the generated puzzle pages load (landing.js) is referenced
  // from the page builder, not from index.html, so that source counts too.
  const seoSrc = fs.readFileSync(path.join(ROOT, "tools/build_seo_pages.py"), "utf8");
  let stampedHere = 0;
  stamped.filter((rel) => rel.endsWith(".js") || rel.endsWith(".css")).forEach((rel) => {
    assert(html.includes(`${rel}?v=`) || html.includes(`${rel}"`) || seoSrc.includes(`"${rel}"`),
      `neither index.html nor tools/build_seo_pages.py still references ${rel}, which tools/stamp_assets.py stamps`);
    if (html.includes(`${rel}?v=`)) stampedHere++;
  });

  // The same hazard one level down, for the files the REPO commits: a stamp
  // written by hand or by the stamper can go stale, so every one of them is
  // resolved back to the file it names. The generated pages are not swept here
  // and cannot be: they are gitignored, built from the current assets on a
  // clean checkout by .github/workflows/pages.yml, so their stamps are right by
  // construction and a copy left lying in a working tree says nothing about
  // what gets deployed. What this catches is the tracked file that
  // rebuilding leaves pointing at a hash that no longer exists, which is a
  // 404 on the stylesheet and an unstyled page for anyone who arrives from
  // search. Every stamp in every HTML file is checked, so a page added later is
  // covered without being listed here.
  // Tracked files only, asked of git rather than guessed from a list here: the
  // ignore rules are where "generated" is defined, and a second copy of that
  // definition is a copy to disagree with.
  const stampedPages = require("child_process")
    .execFileSync("git", ["-C", ROOT, "ls-files", "-z", "*.html"], { encoding: "utf8" })
    .split("\0").filter(Boolean).map((rel) => path.join(ROOT, rel));
  // The generated pages write absolute URLs and index.html writes relative ones,
  // so a stamp is resolved back to a file on disk rather than pattern-matched:
  // a check that quietly skips the form it cannot parse is a check that passes
  // for the wrong reason.
  const current = {};
  let stampsChecked = 0;
  stampedPages.forEach((file) => {
    const src = fs.readFileSync(file, "utf8");
    for (const m of src.matchAll(/(?:href|src)="([^"]+\.(?:js|css))\?v=([0-9a-f]{8})"/g)) {
      const url = m[1];
      const rel = /^https?:/.test(url)
        ? url.replace(/^https?:\/\/[^/]+\//, "")
        : path.relative(ROOT, path.resolve(path.dirname(file), url));
      if (!fs.existsSync(path.join(ROOT, rel))) continue;  // someone else's asset
      stampsChecked++;
      if (!(rel in current)) {
        current[rel] = crypto.createHash("md5")
          .update(fs.readFileSync(path.join(ROOT, rel))).digest("hex").slice(0, 8);
      }
      assert(m[2] === current[rel],
        `${path.relative(ROOT, file)} points at a stale ${rel}?v=${m[2]} — the file ` +
        `hashes to ${current[rel]} now (rebuild: tools/build_seo_pages.py, then ` +
        `tools/stamp_assets.py)`);
    }
  });
  assert(stampedPages.some((f) => path.relative(ROOT, f) === "index.html"),
    "the app's own page is in the sweep: " + stampedPages.length + " tracked page(s)");
  // Every stamp the sweep's regex can see was resolved back to a real file
  // rather than skipped. Counted against what index.html actually carries, not
  // against the asset list: on a stored checkout that is zero, and after a
  // build it is every script and stylesheet on the list.
  assert(stampsChecked >= stampedHere,
    `every stamp resolved back to a real file: ${stampsChecked} of ${stampedHere}`);
}

// --- the app's own URLs resolve against the front door, not the address bar ---
// Opening a puzzle replaceState's the address bar to /puzzles/<id>/, so a bare
// relative "puzzles/..." built anywhere in app.js resolves one level deeper —
// /puzzles/<id>/puzzles/... — and 404s.
// A source rule, because this harness's DOM has no URL resolution and so cannot
// fail on the thing a browser fails on.
{
  const offenders = appSrc.split("\n").map((l, i) => ({ l, n: i + 1 }))
    .filter(({ l }) => /["'`]puzzles\//.test(l))
    .filter(({ l }) => !/\b(at|addressUrl)\(/.test(l) && !/new URL\(/.test(l) && !/^\s*(\/\/|\*)/.test(l));
  assert(!offenders.length,
    "app.js builds a URL from a bare \"puzzles/…\" literal. Once a puzzle is open "
    + "the address bar says /puzzles/<id>/, so that resolves one level deeper and "
    + "404s — wrap it in at() (or addressUrl() for the address bar): "
    + offenders.map((o) => `app.js:${o.n} ${o.l.trim()}`).join(" | "));
  assert(/function at\(rel\) \{ return new URL\(rel, homeUrl\(\)\)\.href; \}/.test(appSrc),
    "app.js still resolves the URLs it builds against the front door, with at()");
  assert(/function addressUrl\(rel\) \{[^}]*homeUrl\(\)/.test(appSrc),
    "app.js's addressUrl() still resolves against the front door, as at() does");
}

// The same hazard in index.html's own links: the page stays loaded while the
// address bar moves to /puzzles/<id>/, so a relative link to a page of the site
// 404s from the second puzzle on. Links to pages are rooted; assets are not,
// because they are fetched before the address bar moves.
{
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const bare = [...html.matchAll(/<a\b[^>]*\bhref="([^"]*)"/g)].map((m) => m[1])
    .filter((u) => !/^(\/|#|https?:|mailto:)/.test(u));
  assert(!bare.length, "index.html links to a page by a relative URL, which 404s once a "
    + "puzzle is open — root it with /: " + bare.slice(0, 5).join(" "));
}

// --- the solver's abbreviation glossary is the clue-writer's, not a copy ---
// abbreviations.js is generated by build_abbreviations.table() so that the
// table the hints teach and the table clueability.py builds words from cannot
// disagree. A file that differs from a fresh table() is a stale build.
{
  const js = fs.readFileSync(path.join(ROOT, "abbreviations.js"), "utf8");
  const table = new Function(js + "\n return ABBREVIATIONS;")();
  const fresh = JSON.parse(require("child_process").execFileSync("python3", ["-c",
    "import json, build_abbreviations as b; print(json.dumps(b.table()))"],
  { cwd: path.join(ROOT, "tools"), encoding: "utf8" }));
  assert(JSON.stringify(table) === JSON.stringify(fresh),
    "abbreviations.js is build_abbreviations.table() (run tools/build_abbreviations.py)");

  // And the glossary the solver can READ is the same table again, so a new
  // convention reaches the page the solver is sent to as well as the one the
  // hint quotes from.
  const senses = new Set();
  Object.values(table).forEach((words) => words.forEach((w) => senses.add(w)));

  // Each row has its own id, because a hint links to the one convention it just
  // named rather than to the top of four hundred rows. The slug is computed
  // here the same way app.js and build_abbreviations.py compute it, so a rule
  // that drifts in one of the three fails rather than silently producing dead
  // links.
  const anchor = (w) => "abbr-" + w.toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const page = readBuilt("abbreviations/index.html");
  {
    // The word itself may be wrapped in a link out to a clue that uses the
    // convention, so the term is compared with that unwrapped.
    const missing = [...senses].filter((w) => {
      const cell = `<div id="${anchor(w)}"><dt>`;
      const at = page.indexOf(cell);
      return at < 0 || page.slice(at + cell.length, page.indexOf("</dt>", at))
        .replace(/^<a href="[^"]+">|<\/a>$/g, "") !== w;
    });
    assert(missing.length === 0,
      "every sense in abbreviations.js is on the /abbreviations/ page, anchored (run "
        + `tools/build_abbreviations.py then tools/build_seo_pages.py) — missing `
        + `${missing.length}, e.g. ` + missing.slice(0, 3).join(", "));
  }

  // The hint's link has to land on that page: the glossary has its own URL,
  // separate from the lesson at /learn/.
  const appSrcGloss = require("../app_src").read(ROOT);
  assert(appSrcGloss.includes('"abbreviations/#abbr-"'),
    "a hint's glossary link points at the /abbreviations/ page");

  // A glossary word links to one real clue whose wordplay uses it. The page's
  // description says how many words do, so the count and the table are checked
  // against each other: a description that promises links the table does not
  // carry is the page telling a solver about a thing that is not there.
  const glossary = page.split('<dl class="glossary">').slice(1)
    .map((s) => s.split("</dl>")[0]).join("\n");
  // Each opens the clue in the app (solve_url): ?p=<id>&c=21A is 21-across.
  const clueLinks = [...glossary.matchAll(/href="[^"]*\?p=([^&"]+)&amp;c=(\d+)([AD])"/g)]
    .map(([m, id, n, d]) => [m, id, `${n}-${d === "A" ? "across" : "down"}`]);
  assert(clueLinks.length > 0,
    "the glossary links its words into the clues that use them "
      + "(run tools/build_seo_pages.py)");
  const puzzleHtml = {};
  const dead = clueLinks.filter(([, id, frag]) => {
    if (!(id in puzzleHtml)) {
      const f = path.join(ROOT, "puzzles", id, "index.html");
      puzzleHtml[id] = fs.existsSync(f) ? fs.readFileSync(f, "utf8") : "";
    }
    return !puzzleHtml[id].includes(`id="${frag}"`);
  });
  assert(dead.length === 0,
    `every glossary link lands on a clue that exists — ${dead.length} do not, e.g. `
      + dead.slice(0, 3).map(([, id, frag]) => `puzzles/${id}/#${frag}`).join(", "));
  const promised = (page.match(
    /<meta name="description" content="[^"]*?([\d,]+) of them link/) || [])[1];
  assert(Number(String(promised).replace(/,/g, "")) === clueLinks.length,
    `the glossary's description counts the links the table actually has `
      + `(it claims ${promised}, the table has ${clueLinks.length})`);

  // The glossary is on one indexable URL, not two competing for the same query:
  // /learn/ links to it instead of repeating the table.
  const learn = readBuilt("learn/index.html");
  assert(!learn.includes('<dl class="glossary">'),
    "/learn/ points at /abbreviations/ rather than duplicating the table");
  assert(/href="[^"]*abbreviations\/"/.test(learn),
    "/learn/ links to the standalone glossary");
}

// --- the grid measures its container, never the window ---
// Sizing cells off `100vw` ignores body's max-width and the flex column, and on
// iOS Safari resolves against a viewport that is still moving while the toolbar
// collapses: the grid drew small and jumped bigger at the first scroll.
// --cellsize must be declared once, off --gridspace, and no
// #grid rule may use a viewport unit — the breakpoints tune
// --cellcap. Asserted here because it is invisible in a headless DOM and the
// only place it shows up is on a real tablet.
{
  const all = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");
  // The one sanctioned exception: the `@supports not (width: 1cqi)` branch that
  // keeps pre-2023 browsers from getting no grid at all.
  const css = all.replace(/@supports not \(width: 1cqi\)\s*\{[^{}]*\{[^}]*\}[^}]*\}/g, "");
  const decls = css.match(/--cellsize\s*:/g) || [];
  assert(decls.length === 1,
    `--cellsize is declared exactly once (found ${decls.length}); breakpoints ` +
    `override --cellcap, not the whole calculation`);
  (css.match(/#grid\b[^{]*\{[^}]*\}/g) || []).forEach((rule) => {
    assert(!/\b\d*\.?\d+v(w|h|min|max)\b/.test(rule),
      "no #grid rule sizes itself in viewport units — use container units " +
      "(--gridspace) so the grid tracks its column, not the browser chrome: " + rule);
  });
  assert(/--gridspace:\s*calc\(100cqi/.test(css),
    "the grid's space comes from a container query unit");

  // And the cap is asked of the same ruler. A @media width rule is a second
  // ruler, and on a resume the two disagree for a frame: the window reads
  // narrow, so the cap comes off, while 100cqi already resolves against the
  // full-width column, and the grid draws oversized cells and snaps back.
  // One ruler cannot disagree with itself.
  {
    const caps = [...all.matchAll(/--cellcap:\s*999px/g)];
    assert(caps.length === 1,
      `the grid is uncapped in exactly one place (found ${caps.length})`);
    const before = all.slice(0, caps[0].index);
    assert(/@container[^{]*\{[^{}]*#grid\b[^{}]*\{\s*$/.test(before),
      "and that place is a @container query, not a window width: " + before.slice(-140));
  }

  // The wide-screen frame (no page scroll, grid sized to height, lists scroll on
  // their own) keeps the check buttons out of the bottom-left, where a webcam sits.
  assert(/@media \(min-width: 1280px\)[^{]*\{[\s\S]*?#app \.clue-list\s*\{[^}]*overflow-y:\s*auto/.test(all),
    "style.css keeps the wide-screen layout with independently scrolling clue lists");
  assert(/@media \(min-width: 1280px\)[^{]*\{[\s\S]*?\.toolbar\s*\{[^}]*grid-column:\s*2;\s*grid-row:\s*1/.test(all),
    "the wide layout puts the check toolbar top-right, never bottom-left");

  // --- and how big things are is asked about the pointer, not the width ---
  // As one query, an iPad shrinks when turned to the WIDER side: portrait
  // stacks and gets tablet cells and type, landscape falls through to the
  // desktop rules. Nothing else on the page would notice if they were merged.
  const media = [...all.matchAll(/@media([^{]+)\{((?:[^{}]|\{[^{}]*\})*)\}/g)]
    .map((m) => ({ q: m[1].trim(), body: m[2] }));
  const tablet = media.filter((b) => /max-width:\s*10\d\dpx/.test(b.q));
  assert(tablet.length, "style.css still has a tablet breakpoint to check");
  tablet.forEach((b) => {
    if (!/--cellcap|font-size/.test(b.body)) return;
    assert(/pointer:\s*coarse/.test(b.q),
      "a media query sizes cells or type off width alone, so a touch device gets " +
      "desktop sizing whenever it is wide enough — add (pointer: coarse): " + b.q);
  });
  // The other half of the same rule: how many columns fit IS a width question,
  // and a pointer test there would stack a wide desktop with a touch screen.
  media.filter((b) => /flex:\s*1 1 100%/.test(b.body)).forEach((b) => {
    assert(!/pointer/.test(b.q),
      "column stacking asks about the pointer, but it is about how much room " +
      "there is: " + b.q);
  });
}
