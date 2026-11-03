// Un-annotated puzzles, the address bar and reload landing.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { allPuzzles, assert, btnNames, canonicalLink, htmlEsc, pickerRowFor, readBuilt, registry,
  shape } = T;
// --- open an un-annotated puzzle (answers-only degradation) ---
// Reachable only by searching for it — which is exactly the escape hatch
// that makes hiding them by default acceptable.
// hasSolutions matters: the escape hatches asserted below are the reveal
// buttons, and a puzzle whose answers the Guardian hasn't published yet has
// nothing to reveal.
// Every clue, not merely `!annotated`: the index flag means "at least one clue
// is missing an annotation", so it also covers a puzzle 28 of whose 30 clues
// were annotated and two of which failed validation. The hint panel is per
// clue, so such a puzzle opens on a real ladder and correctly shows no Reveal —
// asserting the degraded panel on it tests the picker's luck, not the app.
const noneAnnotated = (p) => {
  const puz = global.window.CRYPTIC_PUZZLES[p.id];
  return puz && !puz.blog && puz.entries.every((e) => !e.annotation);
};
const autoPuzzle = allPuzzles.find((p) => !p.annotated && p.hasSolutions && noneAnnotated(p));
const autoRow = shape("a puzzle with no annotation and no blog", autoPuzzle)
  && pickerRowFor(autoPuzzle.id);
// Guarded: everything below is about the row, so without it the reads throw
// and the stack trace hides every later test rather than reporting one FAIL.
if (autoPuzzle && assert(autoRow, `picker finds ${autoPuzzle.id} when searched for`)) {
  assert(autoRow.children[0].innerHTML.includes("answers only"),
    `searching for ${autoPuzzle.id} surfaces the un-annotated puzzle`);
  autoRow.children[0].onclick();
  assert(registry["puzzle-title"].innerHTML.includes("answers only"), "answers-only puzzle opened");
  assert(registry["hint-body"].innerHTML.includes("answers only") || registry["hint-body"].innerHTML.includes("hasn"), "degraded hint panel message");
  assert(registry["hint-next"].children.some((b) => /Reveal answer/.test(b.textContent)),
    "answers-only puzzle offers Reveal answer: " + btnNames());
  assert(registry["hint-escape"].innerHTML.includes("Reveal one letter"), "answers-only puzzle offers letter escape hatch");
}
// A puzzle with none of our hints but a blog's marks on some clue has hints,
// so it must not be called "answers only" on either surface that badges it.
const blogPuzzle = allPuzzles.find((p) => !p.annotated && p.blog);
const blogRow = blogPuzzle && pickerRowFor(blogPuzzle.id);
if (blogPuzzle && assert(blogRow, `picker finds ${blogPuzzle.id} when searched for`)) {
  const html = blogRow.children[0].innerHTML;
  assert(html.includes("hints via " + htmlEsc(blogPuzzle.blog)) && !html.includes("answers only"),
    `a puzzle with blog hints is badged by its blog, not "answers only": ${blogPuzzle.id}`);
}

// --- picking a puzzle rewrites the address bar, because that is what gets shared ---
// A link has to hand over the puzzle on the screen. Left alone, the URL still
// says whatever the page booted on: the bare site root, which drops the reader
// on last night's puzzle, or a stale ?p= from the link they followed, which is
// worse because it looks deliberate.
//
// It says /puzzles/<id>/ rather than ?p=<id> wherever that page exists, because
// a crawler asking for ?p= is handed the app shell and the shell's single
// og:image — so every link pasted would preview as the same card. The query
// form survives for a puzzle with no write-up to point at.
{
  const urls = global.window.history.urls;
  const last = urls[urls.length - 1];
  // The clue ref is appended once the grid settles on a clue, so what has to
  // hold is that the URL names this puzzle and nothing else — asserting the
  // whole string would break every time the address bar learns to carry one
  // more thing about what is on screen.
  const shared = autoPuzzle.hasSolutions
    ? new RegExp(`^https://cryptic\\.paultarjan\\.com/puzzles/${autoPuzzle.id}/(\\?c=\\d+[AD])?$`)
    : new RegExp(`^https://cryptic\\.paultarjan\\.com/\\?p=${autoPuzzle.id}(&c=\\d+[AD])?$`);
  assert(shared.test(last),
    `opening No ${autoPuzzle.number} should leave its share URL in the address bar, `
      + `got ${JSON.stringify(urls)}`);
  // And the clue really does get named, so "look at 3 down" is a link.
  assert(/[?&]c=\d+[AD]$/.test(last),
    `the address bar should name the selected clue too, got ${last}`);
  const want = `https://cryptic.paultarjan.com/puzzles/${autoPuzzle.id}/`;
  assert(canonicalLink.href === want,
    `canonical should follow the opened puzzle to ${want}, got ${canonicalLink.href}`);
  // And the front door stays the front door. Booting on the remembered puzzle is
  // not a choice anybody made, so a bare site root must not rewrite
  // itself — a homepage declaring a puzzle as its canonical is the
  // de-indexing bug pointed the other way.
  if (!new URLSearchParams(global.location.search).get("p")) {
    assert(urls.length && urls.every((u) => u !== ""),
      "the boot open must not touch the URL when nothing asked for a puzzle");
  }
}

// --- a reload of the /puzzles/<id>/ address lands back in the app ---
// The address bar says /puzzles/<id>/ so that it copies and previews well, but
// that is also what a reload fetches: the static write-up. The app flags the
// tab in sessionStorage and the write-up's <head> sends a flagged tab back to
// ?p=, keeping the clue. No flag, as for a crawler or a fresh visitor, and the
// write-up stays.
{
  const key = `ct:app:${autoPuzzle.id}`;
  assert(global.sessionStorage.getItem(key) === "1",
    `opening ${autoPuzzle.id} should flag the tab in sessionStorage as ${key}`);
  const page = readBuilt(`puzzles/${autoPuzzle.id}/index.html`);
  const head = page.slice(0, page.indexOf("</head>"));
  const inline = [...head.matchAll(/<script>([\s\S]*?)<\/script>/gi)].map((m) => m[1])
    .find((src) => src.includes("sessionStorage"));
  if (assert(inline, `puzzles/${autoPuzzle.id}/ should carry the reload-back script in <head>`)) {
    const land = (flagged, type = "reload") => {
      let to = null;
      const store = { getItem: (k) => (flagged && k === key ? "1" : null) };
      const loc = { search: "?c=3A", replace: (u) => { to = u; } };
      const perf = { getEntriesByType: (t) => (t === "navigation" ? [{ type }] : []) };
      new Function("sessionStorage", "location", "URLSearchParams", "performance", inline)(store, loc, URLSearchParams, perf);
      return to;
    };
    const back = land(true);
    assert(back === `../../?p=${autoPuzzle.id}&c=3A`,
      `a flagged reload of puzzles/${autoPuzzle.id}/?c=3A should go to ../../?p=${autoPuzzle.id}&c=3A, got ${back}`);
    assert(land(true, "back_forward") === back, "a flagged back/forward to the write-up should return to the app");
    assert(land(false) === null, "an unflagged visit must stay on the static write-up");
    assert(land(true, "navigate") === null,
      "following an answers link must show the write-up even when the tab solved that puzzle");
  }
}
