// Numerical puzzles, typing against the panel, sync replies, link clues and
// bad-hint reports.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { assert, clueText, entryId, isAsking, panelHTML, pickerRowFor, registry, shape, stripTags } =
  T;
// --- a numerical puzzle takes digits ---
// Listener No 111 (`numeric: true`): every light is a number. The grid takes
// 0-9 from the keyboard and from a phone's soft keyboard (#kbd's input event),
// refuses letters there, and raises the number pad (inputmode). Booted fresh,
// like the block below.
{
  const id = "listener-111";
  const d = require("../fake_dom.js").boot({ query: "?p=" + id });
  const reg = d.registry;
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
  const puz = (global.window.CRYPTIC_PUZZLES || {})[id];
  if (assert(puz && puz.numeric === true, `${id} loads as a numerical puzzle`)) {
    assert(reg["kbd"].getAttribute("inputmode") === "numeric",
      "a numerical puzzle raises the phone's number pad: " + reg["kbd"].getAttribute("inputmode"));
    const cols = puz.dimensions.cols;
    const cellsOf = (e) => Array.from({ length: e.length }, (_, i) => reg["grid"].children[
      (e.direction === "across" ? e.position.y : e.position.y + i) * cols
      + (e.direction === "across" ? e.position.x + i : e.position.x)]);
    const [first, second] = puz.entries.filter((e) => /^[0-9]{2,}$/.test(e.solution || ""));
    assert(first && second, "two digit answers to type");
    reg["clue-" + entryId(first)].listeners.click[0]();
    // Letters are not a numerical puzzle's: typed over the whole light, none lands.
    first.solution.split("").forEach(() => key("A"));
    assert(!cellsOf(first).some((c) => c.classList.contains("solved-flash")),
      "letters typed into a numerical grid solve nothing");
    reg["clue-" + entryId(first)].listeners.click[0]();
    first.solution.split("").forEach((c) => key(c));
    assert(cellsOf(first).every((c) => c.classList.contains("solved-flash")),
      `typing ${first.solution} solves ${entryId(first)}: digits go into the grid`);
    // A soft keyboard that only fires `input`: digits kept, a letter dropped.
    reg["clue-" + entryId(second)].listeners.click[0]();
    second.solution.split("").forEach((c) => {
      reg["kbd"].value = "x" + c;
      reg["kbd"].listeners.input[0]({ target: reg["kbd"] });
    });
    assert(cellsOf(second).every((c) => c.classList.contains("solved-flash")),
      `the soft keyboard's digits solve ${entryId(second)}`);
  }
}

// --- typing does not rewrite the hint panel ---
// refreshAll() runs on every keystroke, and rebuilding the whole panel with it
// would tear down a hint body, rung row and escape hatch in which nothing had
// changed. The browser lays the block out again each time and it reads as
// the panel shivering under the typing, worst on iOS. Only the pattern row and
// the meter can differ while someone is typing.
//
// Booted fresh, and late in the file: boot() replaces the globals every earlier
// test is still holding.
{
  const d = require("../fake_dom.js").boot({ query: "?p=cryptic-30066" });
  const reg = d.registry;
  const el = (id) => reg[id];
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
  const puz = (global.window.CRYPTIC_PUZZLES || {})["cryptic-30066"];
  const entry = (puz.entries || []).find((e) => e.solution && e.annotation && e.length >= 5);
  assert(entry, "an annotated clue with a published answer to type into");
  reg["clue-" + entryId(entry)].listeners.click[0]();
  assert(el("hint-next").children.length, "the clue opens with rungs to take");

  const quiet = () => ["hint-body", "hint-next", "hint-escape"].map((id) => el(id).writes);
  const before = quiet();
  const patBefore = el("hint-pattern").writes;
  const buttons = el("hint-next").children.slice();
  const bodyBefore = el("hint-body").innerHTML;

  // One letter short of the answer: the last one would solve the entry, and a
  // solve is a change the panel SHOULD show.
  entry.solution.slice(0, -1).split("").forEach((c) => key(c));
  assert(el("hint-pattern").innerHTML.includes(
    `${entry.length - 1} of ${entry.length} letters in place`),
    "the letters really went into the grid: " + el("hint-pattern").innerHTML.slice(0, 90));
  assert(el("hint-pattern").writes > patBefore, "the pattern row is what typing updates");
  assert(String(quiet()) === String(before),
    `typing rewrote the hint panel: body/next/escape ${quiet()} vs ${before}`);
  // Node identity, not equal markup. Equal markup is what a rebuild that happens
  // to produce the same string also gives you; the same objects can only mean no
  // teardown happened, which is the thing that costs a repaint.
  assert(el("hint-next").children.length === buttons.length
    && buttons.every((b, i) => el("hint-next").children[i] === b),
    "the rung buttons survive typing as the very same nodes");

  // --- the panel still works after typing ---
  // Skipping a rebuild also skips re-attaching handlers, which is only sound
  // because the original nodes are still there with theirs live. Get that
  // pairing wrong and the hint button is dead — far worse than a flicker.
  const rung = el("hint-next").children[0];
  const label = rung.textContent;
  rung.onclick();
  if (isAsking(el("hint-body"))) reg["guess-tell"].onclick();
  assert(el("hint-body").innerHTML.includes("hint-step"),
    `taking "${label}" after typing showed nothing: ` + el("hint-body").innerHTML.slice(0, 140));
  assert(el("hint-body").innerHTML !== bodyBefore, "the body says something new");
  assert(el("hint-body").writes > before[0], "a real change is written, not skipped");
  assert(el("hint-next").children[0] !== buttons[0],
    "and the rung row is rebuilt once the ladder actually moves");

  // --- and the meter still follows a solve ---
  const meterBefore = el("hint-meter").innerHTML;
  key(entry.solution[entry.length - 1]);
  assert(el("hint-meter").innerHTML !== meterBefore && /Solved/.test(el("hint-meter").innerHTML),
    "the last letter updates the meter: " + el("hint-meter").innerHTML);
}

// --- a sync reply cannot undo what the solver just did ---
// A reply describes the moment its request left, and a request is in flight for
// as long as a round trip takes. Written into localStorage as the truth, it
// would delete anything done during that second — the letter typed, the rung
// opened — in front of the solver. So the reply is merged in.
//
// The stub resolves synchronously, on purpose. A real promise lands after this
// file has finished, and worse, an assertion thrown inside one is caught by the
// app's own .catch() and reported as "Offline — will retry" — a test that can
// only pass. Booted fresh.
{
  const d = require("../fake_dom.js").boot({ query: "?p=cryptic-30066" });
  const reg = d.registry;
  const KEY = "ct:cryptic-30066";
  const save = () => JSON.parse(d.storage[KEY]);
  // Resolves on the spot and chains through whatever the app hands back.
  const now = (v) => (v && typeof v.then === "function" ? v
    : { then(f) { return f ? now(f(v)) : now(v); }, catch() { return this; } });

  d.storage["ct:sync"] = JSON.stringify("TESTCODE");
  const puz = (global.window.CRYPTIC_PUZZLES || {})["cryptic-30066"];
  const entry = (puz.entries || []).find((e) => e.annotation && e.annotation.explanation.walkthrough);
  assert(entry, "a clue with a walkthrough rung to open");
  reg["clue-" + entryId(entry)].listeners.click[0]();

  // Climb to the walkthrough, taking whatever rungs this clue happens to have
  // and telling the quiz we do not want to guess.
  // A rung button reads "1 · Spot the indicator words", or "Show hint 1 · …" for
  // the next one up, and is disabled until its tier opens — so it is matched on
  // the label the ladder gives it, and only counts once it can be pressed.
  const rungs = () => reg["hint-next"].children;
  const named = (t) => rungs().find((b) => !b.disabled && (b.textContent || "").includes(t));
  let guard = 12;
  while (!named("Full walkthrough") && guard--) {
    rungs()[0].onclick();
    if (isAsking(reg["hint-body"])) reg["guess-tell"].onclick();
  }
  const walk = named("Full walkthrough");
  assert(walk, "the ladder reaches the walkthrough: " + rungs().map((b) => b.textContent));

  // Everything the server could still be holding from before that last click.
  global.flushTimers(200);
  const stale = { v: 1, puzzles: { "cryptic-30066": save() } };
  assert(stale.puzzles["cryptic-30066"].hintsShown[entryId(entry)].indexOf("walkthrough") < 0,
    "the stale copy predates the walkthrough, which is the whole point of it");

  // The panel prints the text HTML-escaped, so a walkthrough that opens on an
  // apostrophe is on screen as &#39; -- compare what the reader sees, not the source.
  const onScreen = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  walk.onclick();
  const shown = reg["hint-body"].innerHTML;
  assert(shown.includes(onScreen(entry.annotation.explanation.walkthrough.slice(0, 40))),
    "the walkthrough is on screen after the click");

  // The reply to a push that left before that click now lands.
  let pushed = null;
  global.fetch = (url, opts) => {
    pushed = JSON.parse(opts.body);
    return now({ ok: true, status: 200, json: () => now(stale) });
  };
  global.flushTimers(2500);
  assert(pushed, "the click really did schedule a push");
  assert(pushed.puzzles["cryptic-30066"].hintsShown[entryId(entry)].indexOf("walkthrough") >= 0,
    "and what we pushed includes the rung — a save still in its debounce is flushed first");
  assert(reg["hint-body"].innerHTML.includes(onScreen(entry.annotation.explanation.walkthrough.slice(0, 40))),
    "the walkthrough survives the reply: " + reg["hint-body"].innerHTML.slice(0, 120));
  assert(save().hintsShown[entryId(entry)].indexOf("walkthrough") >= 0,
    "and it survives in the saved state, not just on the screen");
  delete global.fetch;
}

// --- a clue is a link ---
// ?c=3D opens on that clue, so "which one are you stuck on" is answerable with a
// URL and a first-timer can be handed one clue instead of a whole 15x15. Booted
// fresh, because the ref has to survive openPuzzle rewriting the address bar to
// ?p= on its way in. Late in the file: boot() replaces the globals every earlier
// test is still holding.
{
  const fresh = (q) => require("../fake_dom.js").boot({ query: q });
  const clueOf = (r) => stripTags((r.registry["hint-clue"].innerHTML || ""), "");

  const dflt = clueOf(fresh("?p=cryptic-30066"));
  const asked = fresh("?p=cryptic-30066&c=3D");
  assert(clueOf(asked).startsWith("3D"),
    `?c=3D should open on 3 down, got ${clueOf(asked).slice(0, 40)}`);
  assert(clueOf(asked) !== dflt, "and that is not just where the puzzle opens anyway");

  assert(clueOf(fresh("?p=cryptic-30066&c=17d")).startsWith("17D"),
    "a lower-case ref works, because that is how people retype a link");

  // A link outliving its puzzle must still open the puzzle.
  assert(clueOf(fresh("?p=cryptic-30066&c=nope")) === dflt,
    "an unknown clue ref falls back to the first clue rather than erroring");
}

// --- a bad hint can be reported from the clue it is bad on ---
// Two taps and a sentence, in the strip the reveal button already lives in. No
// page, no form, no address to find: a reader who has just been taught something
// false will say so if it costs them nothing, and will not if it costs them a
// search for a contact link.
{
  const first = Object.keys(global.window.CRYPTIC_PUZZLES).sort()[0];
  const e = (global.window.CRYPTIC_PUZZLES[first].entries || [])[0];
  registry["btn-picker"].onclick();
  const li = pickerRowFor(first);
  if (assert(li, "picker finds a puzzle to report on")) {
    li.children[0].onclick();
    registry["clue-" + entryId(e)].listeners.click[0]();
    assert(/id="rp-open"/.test(registry["hint-escape"].innerHTML),
      "every clue offers it: " + registry["hint-escape"].innerHTML);
    registry["rp-open"].onclick();
    assert(/id="rp-note"/.test(registry["hint-escape"].innerHTML),
      "and opening it gives you the line to write on: " + registry["hint-escape"].innerHTML);
    // Something you can read your own sentence back in: more than one line at
    // rest, and it grows with the typing; the ceiling is CSS's.
    assert(/<textarea id="rp-note"[^>]*rows="[2-9]"/.test(registry["hint-escape"].innerHTML),
      "with room to write in: " + registry["hint-escape"].innerHTML);

    // Typing into the page re-renders the panel on every keystroke. A strip that
    // is rewritten while you are writing in it throws the sentence away.
    registry["rp-note"].value = "the definition is the wrong way round";
    registry["clue-" + entryId(e)].listeners.click[0]();
    assert(registry["rp-note"].value === "the definition is the wrong way round",
      "a redraw does not eat what you were typing: " + registry["rp-note"].value);

    let sent = null;
    const realFetch = global.fetch;
    global.fetch = (url, opt) => { sent = { url, opt }; return new Promise(() => {}); };
    registry["rp-send"].onclick();
    global.fetch = realFetch;
    if (assert(sent, "Send sends it")) {
      assert(/\/r$/.test(sent.url) && sent.opt.method === "POST",
        "to the report endpoint: " + sent.url + " " + sent.opt.method);
      const body = JSON.parse(sent.opt.body);
      assert(body.note === "the definition is the wrong way round", "with what was written");
      assert(body.clue === entryId(e) && body.puzzle,
        "and which clue it was about, which is the half the reporter should not have to type: "
          + JSON.stringify(body));
    }

    // --- and it is about the clue you are LOOKING at, after walking past others ---
    // The escape hatch's markup is byte-identical for every unsolved clue whose
    // report is not open, so setHTML — which skips a write when the new string
    // equals the old — rebinds nothing as you move between them. A bindReport
    // that closed over the entry it was last bound on would stay bound to it for
    // as long as the markup did not change, and file the report against a clue
    // the reader had left, with the reader's own words attached to it, which is
    // worse than losing the report.
    // Walk a few clues the way a solver does and check the last one is the one
    // that gets reported.
    const walkTo = (global.window.CRYPTIC_PUZZLES[first].entries || [])
      .filter((x) => registry["clue-" + entryId(x)]).slice(0, 4);
    if (assert(walkTo.length >= 2, "there are clues to walk between")) {
      walkTo.forEach((x) => registry["clue-" + entryId(x)].listeners.click[0]());
      const last = walkTo[walkTo.length - 1];
      registry["rp-open"].onclick();
      assert(/id="rp-note"/.test(registry["hint-escape"].innerHTML),
        "the report opens on the clue you walked to: " + registry["hint-escape"].innerHTML);
      registry["rp-note"].value = "this one, not the one four taps ago";
      let sent2 = null;
      const realFetch2 = global.fetch;
      global.fetch = (url, opt) => { sent2 = { url, opt }; return new Promise(() => {}); };
      registry["rp-send"].onclick();
      global.fetch = realFetch2;
      if (assert(sent2, "Send still sends it after walking")) {
        const body2 = JSON.parse(sent2.opt.body);
        assert(body2.clue === entryId(last),
          `the report names the clue on screen (${entryId(last)}), not one left behind: `
            + JSON.stringify(body2));
      }
    }
  }
}

// --- an indicator is a phrase, and its linking words are not the lesson ---
// "If the indicator has linking words it doesn't feel fair to lose. Like for
// spooner if I just choose spooner I should get it." Many of the corpus's
// indicators are more than one word — "starts to", "end of",
// "according to Spooner" — and demanding the exact span would mark a solver wrong
// for finding the thing and drawing its edge one word in. Finding every
// indicator and pointing at nothing else is what the rung asks, so that is what
// it marks; the phrase is then named in full, which is the teaching.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const tokensOf = (clue) => {
    const body = String(clue || "").replace(/\s*\([^()]*\)\s*$/, "");
    const out = [];
    const re = /\S+/g;
    let m;
    while ((m = re.exec(body))) out.push({ i: m.index, text: m[0] });
    return out;
  };
  // Located without a copy of the app's matcher: one occurrence, whole words.
  const spanTokens = (clue, frag) => {
    const at = clue.indexOf(frag);
    if (at < 0 || clue.indexOf(frag, at + 1) >= 0) return null;
    const hit = tokensOf(clue).map((t, n) => ({ t, n }))
      .filter(({ t }) => t.i < at + frag.length && at < t.i + t.text.length);
    if (!hit.length) return null;
    const first = hit[0].t, last = hit[hit.length - 1].t;
    if (first.i !== at || last.i + last.text.length !== at + frag.length) return null;
    return hit.map(({ n }) => n);
  };
  const openClue = (id, e) => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(id);
    if (!li) return false;
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(e)].listeners.click[0]();
    return true;
  };
  const rungs = () => registry["hint-next"].children;
  const rung = (re) => rungs().find((b) => re.test(b.textContent || "") && !b.disabled);
  const asking = () => isAsking(registry["hint-body"]);
  const pickable = (n) => panelHTML().includes(`id="gw-${n}"`);

  let found = null, tried = 0;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      if (found || tried > 60) break;
      const inds = ((e.annotation || {}).indicators) || [];
      if (!inds.length) continue;
      const spans = inds.map((t) => spanTokens(clueText(e), t.text));
      // Every phrase locatable, and at least one of them long enough to have a
      // word to leave out — a one-word indicator cannot pose this question.
      if (spans.some((s) => !s) || !spans.some((s) => s.length > 1)) continue;
      tried++;
      if (!openClue(id, e)) continue;
      const b = rung(/indicator/i);
      if (!b) continue;
      b.onclick();
      // Words another rung already named are settled scaffolding and not
      // offered, so a clue whose indicator overlaps its definition is skipped
      // rather than answered with a button that is not there.
      if (!asking() || spans.some((s) => !pickable(s[0]))) continue;
      found = { id, e, spans };
    }
    if (found) break;
  }
  shape("an indicator that is more than one word", found);
  if (found) {
    found.spans.forEach((s) => registry["gw-" + s[0]].onclick());
    registry["guess-check"].onclick();
    const html = panelHTML();
    assert(html.includes("guess-verdict right"),
      `${found.id} ${entryId(found.e)}: one word of each indicator is enough: ` + html);
    assert(html.includes("in full it’s"),
      "and the whole phrase is what comes back: " + html);

    // The other half of the rule: a phrase with no word picked at all is not
    // found, however many of the others are. Many clues have "in" as an entire
    // indicator, and a rung that let a solver skip one would be free.
    if (found.spans.length > 1) {
      openClue(found.id, found.e);
      rung(/indicator/i).onclick();
      if (assert(asking(), "the indicators rung asks again on a fresh clue")) {
        found.spans.slice(0, -1).forEach((s) => registry["gw-" + s[0]].onclick());
        registry["guess-check"].onclick();
        assert(!panelHTML().includes("guess-verdict right"),
          "an indicator with nothing pointed at it is not found: " + panelHTML());
      }
    }
  }
}

// --- solving a clue while a rung is quizzing you earns that rung ---
// The score was already settled the moment the clue went in, so the rung costs
// nothing either way — but the panel says which rungs were EARNED and which
// were bought, and a rung handed over at that moment must not arrive looking
// bought. Solving the clue is a better answer to "which words give which letters"
// than pointing at the words, so it is scored as one.
{
  const d = require("../fake_dom.js").boot({ query: "?p=quiptic-1396" });
  const reg = d.registry;
  const kd = d.docListeners["keydown"][0];
  const key = (k) => ({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
  const body = () => reg["hint-body"].innerHTML;
  const climbable = (b) => !!(b && b.onclick && !b.disabled && /^\d+ · /.test(b.textContent || ""));

  reg["clue-16-down"].listeners.click[0]();
  for (let i = 0; i < 8; i++) {
    const btns = reg["hint-next"].children;
    const blocks = btns.find((b) => climbable(b) && /building blocks/i.test(b.textContent));
    if (blocks) { blocks.onclick(); break; }
    const next = btns.find(climbable);
    if (!next) break;
    next.onclick();
    if (body().includes('class="hint-step guess"')) reg["guess-tell"].onclick();
  }
  assert(body().includes("gm-slot-"), "16D's blocks rung asks the matching question: " + body().slice(0, 300));
  assert(!body().includes("worked out · free"), "and it is unanswered until something answers it");

  "EVALUATED".split("").forEach((c) => kd(key(c)));
  assert(body().includes("worked out · free"),
    "solving the clue answers the question it was asking: " + body().slice(0, 600));
  assert(/Solved <strong>1\/30<\/strong>/.test(reg["scorebar"].innerHTML),
    "the clue is solved: " + reg["scorebar"].innerHTML);
  assert(/<strong>2<\/strong> hints used/.test(reg["scorebar"].innerHTML),
    "and only the two rungs actually bought are charged: " + reg["scorebar"].innerHTML);
}
