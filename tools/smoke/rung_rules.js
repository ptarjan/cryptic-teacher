// What rungs charge for, definition ends, double definitions and spotting.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { APP_BLOCKS, ARMED, CLUE_TYPES, ROOT, assert, clueText, defTexts, dismissNext, entryId, fs,
  isAsking, panelHTML, pickerRowFor, registry, shape } = T;
// --- nothing is charged for without being offered first ---
// A rung asks even when what is left to point at IS the answer. Skipping the
// question there, on the grounds that the answer is elimination, would on a
// two-word double definition — "County flags (5)" — skip every rung the clue
// has: the ladder would take its price and never ask. An easy question is a free
// rung, and a rung handed over unasked is one the solver paid for and was never
// given the chance to win.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const words = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(/\s+/)
    .filter(Boolean);
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      const defs = defTexts(a);
      if (defs.length < 2) continue;
      // The two definitions together are the whole clue, so once the question is
      // asked there is nothing left over to eliminate against.
      const clue = words(clueText(e).replace(/\([^)]*\)\s*$/, ""));
      if (clue.length && clue.length === words(defs[0]).length + words(defs[1]).length) {
        found = { id, e };
        break;
      }
    }
    if (found) break;
  }
  assert(found, "some clue is defined end to end by its two definitions");

  registry["btn-picker"].onclick();
  const li = pickerRowFor(found.id);
  assert(li, "picker finds the whole-clue definition puzzle");
  li.children[0].onclick();
  registry["reset-puzzle"].onclick();
  registry["clue-" + entryId(found.e)].listeners.click[0]();
  const btn = registry["hint-next"].children.find((b) => /definition/i.test(b.textContent || ""));
  assert(btn, "the definition rung is offered on " + clueText(found.e) + ": "
    + registry["hint-next"].innerHTML);
  btn.onclick();
  assert(registry["hint-body"].innerHTML.includes("hint-step guess"),
    "and it asks before it tells, even when the answer is the whole clue ("
      + clueText(found.e) + "): " + registry["hint-body"].innerHTML);
}

// --- every ladder names its precise type, double and cryptic definitions included ---
// Their family is "Definitions only", whose blurb offers BOTH arms and picks
// neither, so without the `.mechanism` line a solver reads the family label as
// the site having mis-typed the clue: "this feels like a double definition not a
// definition only". Driven through the real buttons on one clue of each type,
// because the claim is about what ends up on the screen.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const pick = (name) => {
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation;
        if (a && JSON.stringify(a.type) === JSON.stringify([name])) return { id, e, a };
      }
    }
    return null;
  };
  for (const name of ["double_definition", "cryptic_definition"]) {
    const want = CLUE_TYPES.types.find((t) => t.name === name).label;
    const found = pick(name);
    if (!shape("a clue typed " + want, found)) continue;
    registry["btn-picker"].onclick();
    const li = pickerRowFor(found.id);
    assert(li, "picker finds the " + want + " puzzle");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(found.e)].listeners.click[0]();
    // Climb the whole ladder: the line rides on the blocks rung, or on the
    // walkthrough when the clue has no blocks rung to carry it.
    for (let guard = 0; guard < 16; guard++) {
      const tell = registry["guess-tell"];
      if (tell && tell.onclick) { const fn = tell.onclick; tell.onclick = null; fn(); continue; }
      const b = registry["hint-next"].children.find(
        (x) => x.onclick && !x.disabled && (/^\d+ · /.test(x.textContent || "") || ARMED.test(x.textContent || "")));
      if (!b) break;
      b.onclick();
    }
    const body = registry["hint-body"].innerHTML;
    assert(body.includes('class="mechanism"') && body.includes(want),
      "the ladder names the mechanism on a " + want + " (" + clueText(found.e) + "): " + body);
    // The name, not the generic sentence: on these two types the type's blurb
    // wording only re-says the definition rung, and no rung may restate another.
    assert(!body.includes("there is no other wordplay")
        && !body.includes("no separate wordplay — the whole clue"),
      "and it does not restate the definition rung on a " + want + ": " + body);
  }
}

// --- where a definition ENDS is a judgement call ---
// Take "Communication made meaningless by this" (SCRAMBLER): picking just
// "Communication made meaningless" leaves off the two words that point back at
// the answer instead of defining it. Many definitions in the corpus end in a
// word like that, and a solver who stops one short of the
// line the annotation drew has still named the definition. Leaving off a word
// that carries meaning is a different thing and is still wrong — both are
// asserted, because leniency that cannot fail anybody teaches nothing.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  // app.js's list, restated: the test drives the app rather than reimplementing
  // it, so this picks the CASE and the app alone decides the verdict.
  const EDGE = ("a an the this these those it its one such by of for from with " +
                "in on at to and that as so s").split(" ");
  const bare = (s) => String(s).toLowerCase().replace(/[\u2018\u2019]/g, "'")
    .replace(/[^a-z']/g, "").replace(/^'+|'+$/g, "");
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      const defs = defTexts(a);
      if (defs.length !== 1) continue;
      const w = defs[0].split(/\s+/);
      if (w.length < 3 || clueText(e).indexOf(defs[0]) < 0) continue;
      if (EDGE.indexOf(bare(w[w.length - 1])) < 0) continue;
      if (EDGE.indexOf(bare(w[0])) >= 0) continue;   // the near-miss must be a real one
      found = { id, e };
      break;
    }
    if (found) break;
  }
  assert(found, "some clue's definition ends in a word a solver could fairly leave off");

  const askDef = () => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(found.id);
    assert(li, "picker finds the edge-word puzzle");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(found.e)].listeners.click[0]();
    const b = registry["hint-next"].children.find((x) => /definition/i.test(x.textContent || ""));
    assert(b, "the definition rung is offered on " + clueText(found.e));
    b.onclick();
  };
  const verdict = (pick) => {
    askDef();
    for (const i of pick) registry["gw-" + i].onclick();
    registry["guess-check"].onclick();
    return registry["hint-body"].innerHTML;
  };
  // Which words the annotation calls the definition, read back off one wrong
  // pick rather than worked out here a second time.
  const marks = (verdict([0]).match(/class="gw([^"]*)"/g) || [])
    .reduce((a, m, i) => (/hit|missed/.test(m) ? a.concat(i) : a), []);
  assert(marks.length >= 3, "the definition of " + clueText(found.e) + " is three words or more: "
    + JSON.stringify(marks));

  assert(/guess-verdict right/.test(verdict(marks.slice(0, -1))),
    "stopping one word short of the definition's optional end is right on "
      + clueText(found.e) + " (" + defTexts(found.e.annotation)[0] + ")");
  assert(!/guess-verdict right/.test(verdict(marks.slice(1))),
    "but dropping a word that carries the meaning is still wrong on " + clueText(found.e));
}

// --- a double definition has no building blocks of its own ---
// Its halves are its two definitions: the definition rung names both and asks
// for them, and each one's letters are the whole answer, so a blocks rung made
// of them would ask "which words give the answer?" of words the solver had just
// tapped. What such a block adds is its note on that sense, and the note rides
// on the definition rung instead. A block the split never named — a third
// definition — is still a building block, and the mirror below holds that.
// Which block is a sense is app.js's senseBlock: "A character" is the sense
// "character" named, not a third one.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const bare = (t) => String(t || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  const isDef = (a, b) => defTexts(a).some((d) => bare(d) === bare(b.clueFragment));
  const plain = (b) => b.note && /^[A-Za-z ,.;:-]+$/.test(b.note) && !b.soundsLike;
  const open = (id, e) => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(id);
    if (!li) return false;
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(e)].listeners.click[0]();
    return true;
  };
  const labels = () => registry["hint-next"].children.map((b) => b.textContent || "").join(" | ");
  let pure = null, third = null, straightThird = null;
  // A puzzle that is not a cryptic has no blocks rung (app.js straightLadder),
  // so there the split names every sense instead. APP_BLOCKS runs without the
  // open puzzle's index row, so its senseBlock is the cryptic ladder's.
  const straight = (id) => ((global.CRYPTIC_INDEX.puzzles || []).find((p) => p.id === id) || {}).style
    === "straight";
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      if (!a || JSON.stringify(a.type) !== '["double_definition"]' || defTexts(a).length < 2) continue;
      const bl = a.blocks || [];
      if (!pure && bl.length === 2 && bl.every((b) => isDef(a, b) && plain(b))) pure = { id, e, bl };
      // A file holds a third sense as a third definition, whose block carries
      // its `meaning` as the note and no letters.
      const extra = bl.filter((b) => !APP_BLOCKS.senseBlock(a, b) && plain(b) && isDef(a, b));
      if (!extra.length) continue;
      const flat = straight(id) && !(a.indicators || []).length;
      if (!flat && !third) third = { id, e };
      if (flat && !straightThird) straightThird = { id, e, extra };
    }
    if (pure && third && straightThird) break;
  }
  shape("a double definition whose blocks are its two definitions", pure);
  if (pure && open(pure.id, pure.e)) {
    assert(!/building blocks/i.test(labels()),
      `${pure.id} ${entryId(pure.e)}: "${clueText(pure.e)}" offers no building blocks: ${labels()}`);
    const def = registry["hint-next"].children.find((b) => /definition/i.test(b.textContent || ""));
    if (assert(def, `${pure.id} ${entryId(pure.e)}: the definition rung is offered: ${labels()}`)) {
      def.onclick();
      if (isAsking(registry["hint-body"])) registry["guess-tell"].onclick();
      const said = bare(registry["hint-body"].innerHTML.replace(/<[^>]*>/g, " "));
      pure.bl.forEach((b) => assert(said.includes(bare(b.note)),
        `${pure.id} ${entryId(pure.e)}: the note on "${b.clueFragment}" is on the definition rung: `
          + registry["hint-body"].innerHTML));
    }
  }
  shape("a double definition with a sense the split does not name", third);
  if (third && open(third.id, third.e)) {
    assert(/building blocks/i.test(labels()),
      `${third.id} ${entryId(third.e)}: "${clueText(third.e)}" keeps the building blocks for the sense `
        + `the definition rung never named: ${labels()}`);
  }
  shape("a straight puzzle's double definition with a third sense", straightThird);
  if (straightThird && open(straightThird.id, straightThird.e)) {
    const s = straightThird, where = `${s.id} ${entryId(s.e)}: "${clueText(s.e)}"`;
    assert(!/building blocks/i.test(labels()), `${where} is in a straight puzzle, which has no blocks rung: ${labels()}`);
    const def = registry["hint-next"].children.find((b) => /definition/i.test(b.textContent || ""));
    if (assert(def, `${where}: the definition rung is offered: ${labels()}`)) {
      def.onclick();
      if (isAsking(registry["hint-body"])) registry["guess-tell"].onclick();
      const said = bare(registry["hint-body"].innerHTML.replace(/<[^>]*>/g, " "));
      s.extra.forEach((b) => assert(said.includes(bare(b.note)),
        `${where}: with no blocks rung, the note on "${b.clueFragment}" is on the definition rung: `
          + registry["hint-body"].innerHTML));
    }
  }
}

// --- a piece that is all the clue has left is not asked ---
// Once the definition, the indicators and the link words are lit, a pure
// anagram's fodder is whatever remains, and "which words give it?" is a tap with
// one answer. The same holds for the last piece of a charade whose every word is
// claimed. The mirror: the first piece of that charade still asks, because
// there the solver has a real split to make.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const words = (s) => String(s || "").replace(/\s*\([^()]*\)\s*$/, "").split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w));
  const count = (list) => list.reduce((n, s) => n + words(s).length, 0);
  // Every word of the clue named exactly once, by counting: the rungs' spans and
  // the pieces add up to the clue and no fragment is written twice in it.
  const claimed = (e, a) => {
    const parts = [defTexts(a)[0], ...(a.indicators || []).map((i) => i.text), ...(a.linkWords || []),
      ...(a.blocks || []).map((b) => b.clueFragment)];
    return parts.every((p) => p && clueText(e).split(p).length === 2)
      && count(parts) === words(clueText(e)).length;
  };
  const open = (id, e) => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(id);
    if (!li) return false;
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(e)].listeners.click[0]();
    return true;
  };
  const asking = () => isAsking(registry["hint-body"]);
  const climbToBlocks = () => {
    for (let i = 0; i < 8; i++) {
      const open = registry["hint-next"].children.filter((b) => !b.disabled && b.onclick);
      const want = open.find((b) => /building blocks/i.test(b.textContent || ""));
      if (want) return want;
      if (!open[0]) return null;
      open[0].onclick();
      if (asking()) registry["guess-tell"].onclick();
    }
    return null;
  };
  let ana = null, cha = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      if (!a || defTexts(a).length > 1 || !claimed(e, a)) continue;
      const bl = a.blocks || [];
      const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
      // Fodder written as its own letters is never asked anyway; fodder that
      // resolves to the answer is the case this is about.
      if (!ana && JSON.stringify(a.type) === '["anagram"]' && bl.length === 1 && bl[0].gives
        && bare(bl[0].gives) !== bare(bl[0].clueFragment)) ana = { id, e };
      if (!cha && JSON.stringify(a.type) === '["charade"]' && bl.length === 2 && bl[0].gives !== bl[1].gives
        && bl.every((b) => b.gives && bare(b.gives) !== bare(b.clueFragment))) cha = { id, e, bl };
    }
    if (ana && cha) break;
  }
  shape("a pure anagram whose fodder is every unnamed word", ana);
  if (ana && open(ana.id, ana.e)) {
    const b = climbToBlocks();
    if (assert(b, `${ana.id} ${entryId(ana.e)}: the building blocks are reachable`)) {
      b.onclick();
      assert(!asking(), `${ana.id} ${entryId(ana.e)}: "${clueText(ana.e)}" hands its fodder over unasked: `
        + registry["hint-body"].innerHTML);
    }
  }
  shape("a two-piece charade whose every word is claimed", cha);
  if (cha && open(cha.id, cha.e)) {
    const b = climbToBlocks();
    if (assert(b, `${cha.id} ${entryId(cha.e)}: the building blocks are reachable`)) {
      b.onclick();
      if (assert(asking(), `${cha.id} ${entryId(cha.e)}: the first piece of "${clueText(cha.e)}" is asked`)) {
        registry["guess-tell"].onclick();
        assert(!registry["hint-next"].children.some((x) => /next piece/i.test(x.textContent || "")),
          `${cha.id} ${entryId(cha.e)}: the last piece comes with it, not behind a question: `
            + registry["hint-next"].children.map((x) => x.textContent).join(" | "));
      }
    }
  }
}

// --- the spotting rungs spend the type rung ---
// Once the definition and the indicator are both on screen, "what kind of clue
// is this?" has nothing left to tell anyone, so it must stop gating the assembly
// rung. BY EITHER ROUTE: earnedRungs is only written by a PERFECT guess, so
// keying on it would leave the turnstile standing after a near miss or a "just
// tell me" — hence both routes are walked below and asserted identical.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const spot = ["definition", "indicators"];
  const cands = [];
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      if (!a || !(a.indicators || []).length) continue;
      if (!defTexts(a).length || !(a.blocks || []).some((b) => b.clueFragment && b.gives)) continue;
      cands.push({ id, e });
    }
  }
  let found = cands[0] || null;

  const open = () => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(found.id);
    assert(li, "picker finds the puzzle to guess on");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(found.e)].listeners.click[0]();
  };
  const rung = (re) => registry["hint-next"].children.find((b) => re.test(b.textContent || ""));
  // Ladder positions rather than labels: every rung button is "<n> · <label>",
  // and n is the rung's place in this clue's ladder. It is the number read
  // off the screen, and it means the test never has to know what the assembly
  // rung is called.
  const at = (pred) => registry["hint-next"].children.filter(pred)
    .map((b) => ((b.textContent || "").match(/(\d+) ·/) || [])[1]);
  const locked = () => at((b) => b.disabled);
  const offeredN = () => at(() => true);
  // appendChild does not write innerHTML in the stub, so a failure message built
  // from it says nothing at all. Read the buttons.
  const offered = () => registry["hint-next"].children.map((b) => b.textContent).join(" | ");
  // Only a clue whose ladder actually shows the assembly rung (two locks cold)
  // can carry this test; some qualifying clues have a shorter ladder.
  found = null;
  for (const c of cands) {
    found = c;
    open();
    if (locked().length === 2) break;
    found = null;
  }
  assert(found, "some clue has a definition, an indicator, a named block and an assembly rung");
  // Which words answer this rung, asked of the app rather than worked out again
  // here: one wrong pick, and the marks that come back name the whole target.
  // A second copy of guessAsk's span arithmetic in the test would only ever
  // prove the copy right.
  const targetOf = (re) => {
    open();
    const b = rung(re);
    if (!b) return null;
    b.onclick();
    if (!panelHTML().includes("guess-clue ask")) return null;
    registry["gw-0"].onclick();
    registry["guess-check"].onclick();
    // One word that is already the whole target is a RIGHT answer, and a right
    // answer goes on to the next question, so there is no wrong-pick marking to
    // read: the target is that one word.
    if (registry["hint-body"].innerHTML.includes("guess-verdict right")) return [0];
    const marks = registry["hint-body"].innerHTML.match(/class="gw([^"]*)"/g) || [];
    return marks.reduce((acc, m, i) => (/hit|missed/.test(m) ? acc.concat(i) : acc), []);
  };
  const want = { definition: targetOf(/definition/i), indicators: targetOf(/indicator/i) };
  assert(want.definition && want.indicators,
    "the clue can pose both spotting questions: " + JSON.stringify(want));

  // --- and each rung's words are picked in that part's own colour ---
  // "Use the same colour for my selection as we use for indicator." The page
  // has exactly two highlight colours — green for a
  // definition, pink for an indicator and the fragments it works on — and
  // picking has no third, neutral one of its own, which would teach one colour
  // for "I chose this" and a different one for the thing just correctly chosen.
  const pickClass = (re) => {
    open();
    rung(re).onclick();
    return (panelHTML().match(/class="guess-clue ask[^"]*"/) || [""])[0];
  };
  const defPick = pickClass(/definition/i), indPick = pickClass(/indicator/i);
  assert(/pick-definition/.test(defPick),
    "the definition rung picks in the definition's colour: " + defPick);
  assert(/pick-indicators/.test(indPick),
    "the indicator rung picks in the indicator's colour: " + indPick);
  // And those classes are wired to the site's two colours rather than to a third:
  // a class name nothing paints is the same bug wearing a better name.
  const pickCss = fs.readFileSync(ROOT + "/style.css", "utf8");
  assert(/\.guess-clue\s*\{[^}]*--pick-bg:\s*var\(--ind-bg\)/.test(pickCss),
    "picking is the indicator's colour by default");
  assert(/\.pick-definition\s*\{[^}]*--pick-bg:\s*var\(--def-bg\)/.test(pickCss),
    "and the definition's on the definition rung");
  assert(/\.gw\.on\s*\{[^}]*var\(--pick-bg\)/.test(pickCss) &&
         /\.gw\.hit\s*\{[^}]*var\(--pick-bg\)/.test(pickCss),
    "and both the picking and the marking read it");

  // A word's box is the same size whichever of .gw's forms it is wearing —
  // button, span, known, still, on, hit, missed — because the markup puts
  // every one of them through the same .gw box (see pickableClueHTML): only
  // the border's colour, style, background and text colour may tell the
  // states apart. A rule here that snuck in a padding, margin or border WIDTH
  // makes the clue resize when tapping begins.
  // Comments come out first: a selector is whatever precedes a rule's "{", so a
  // comment naming .gw would be read as part of the selector after it.
  const gwCss = pickCss.replace(/\/\*[\s\S]*?\*\//g, "");
  // ONE quantifier over the selector. Two nested ones over overlapping classes
  // backtrack exponentially, and on a stylesheet this size that regex does not
  // return at all — it reads as a hung test, not a slow one.
  const gwRules = [...gwCss.matchAll(/(?:^|\n)([.\w][^{}]*)\{([^}]*)\}/g)];
  const boxProps = /\b(?:padding|margin)\b\s*:|border(?:-(?:top|right|bottom|left))?-width\s*:|(?<!-)\bborder\s*:\s*[\d.]/;
  gwRules.forEach(([, selector, body]) => {
    if (selector.trim() === ".gw" || !/\.gw(?:[.\s]|$)/.test(selector)) return;
    assert(!boxProps.test(body),
      `${selector.trim()} must not redeclare the box .gw sets — only its border's colour ` +
      `or style may differ between states: ${body.trim()}`);
  });

  // And that box is the clue's LEADING. .gw is an inline-block, and an
  // inline-block's margin box is the floor of the line box: a line-height under
  // the chip's own height is silently ignored, so the chip's height is the white
  // a reader sees between two lines of a clue that wrapped — which three
  // quarters of the corpus does at 1.3rem on a phone. The two are therefore one
  // declared sum, and the arithmetic is checked here because nothing in a
  // headless DOM has a pixel in it: the only place they drift apart is a real
  // phone holding a long clue.
  const gwBox = /--gw-box:\s*calc\(([\d.]+)em\s*\+\s*(\d+)px\)/.exec(gwCss);
  const gwLine = /--gw-line:\s*calc\(var\(--gw-box\)\s*\+\s*(\d+)px\)/.exec(gwCss);
  if (assert(gwBox && gwLine && +gwLine[1] > 0,
    "the clue's word box and its leading are declared as one sum (--gw-box, --gw-line)")) {
    const gwBody = (/(?:^|\n)\.gw\s*\{([^}]*)\}/.exec(gwCss) || [])[1] || "";
    const gwNum = (re) => { const m = re.exec(gwBody); return m ? +m[1] : NaN; };
    const gwText = gwNum(/line-height:\s*([\d.]+)/);
    assert(gwText === +gwBox[1],
      `--gw-box carries .gw's own line-height (${gwBox[1]}em declared vs ${gwText})`);
    const gwEdge = 2 * (gwNum(/padding:\s*([\d.]+)px/) + gwNum(/border:\s*([\d.]+)px/));
    assert(gwEdge === +gwBox[2],
      `--gw-box carries .gw's padding and border too (${gwBox[2]}px declared vs ${gwEdge}px)`);
  }
  [/\.hint-clue\s*\{([^}]*)\}/, /(?:^|\n)\.guess-clue\s*\{([^}]*)\}/].forEach((re) => {
    const m = re.exec(gwCss);
    assert(m && /line-height:\s*var\(--gw-line\)/.test(m[1]),
      "the clue's leading is that sum and never a number of its own: "
      + (m ? m[1].trim() : "rule missing"));
  });
  // Including inside a media query. The sweep above reads one rule per line and
  // cannot see the query wrapped round it, so a coarse-pointer query could buy a
  // thumb-sized box — and pay for it in leading on every clue it wrapped.
  [...gwCss.matchAll(/@media([^{]+)\{((?:[^{}]|\{[^{}]*\})*)\}/g)].forEach((q) => {
    [...q[2].matchAll(/\.gw\b[^{}]*\{([^{}]*)\}/g)].forEach((g) => {
      assert(!boxProps.test(g[1]),
        `@media${q[1]}gives .gw a box of its own; the clue's leading is that box on `
        + `every device, so grow --gw-box instead: ${g[1].trim()}`);
    });
  });

  // A marked run in the picker clue paints as ONE band, not a bead per word.
  // The picker cuts every mark into a piece per word and a piece per space (see
  // pickableClueHTML), so the pill padding and rounding that is right for a mark
  // wrapped round a whole phrase draws a row of blobs in there instead. Nothing
  // in this file can measure a pixel, so pin the CSS that undoes it: it must be
  // class-agnostic, because a rule that lists the mark classes it knows about
  // leaves the next one beaded, and it must sit AFTER the pill rules, because
  // the two selectors weigh the same and source order is the whole of what
  // decides which wins.
  const pills = [...pickCss.matchAll(/(?:^|\n)mark\.\w+[^{]*\{([^}]*)\}/g)]
    .filter((m) => /padding\s*:|border-radius\s*:/.test(m[1]));
  assert(pills.length >= 3, "a mark is still a pill everywhere else: " + pills.length);
  const band = /(?:^|\n)\.guess-clue mark\s*\{([^}]*)\}/.exec(pickCss);
  const bandPad = Number((/--band-pad:\s*(\d+)px/.exec(pickCss) || [, NaN])[1]);
  assert(band && /border-radius:\s*0\s*[;}]/.test(band[1] + "}") && bandPad > 0,
    "inside the picker clue a mark is a fragment of a band, not a pill: one rule "
    + "over every mark class, flattening its rounding and painting --band-pad past its own "
    + "glyphs: " + (band ? band[1] : "no rule"));
  // Room it PAINTS, never room it measures. Padding on an inline box is width,
  // and width on every piece of a run is the gap that beaded it, so the sides
  // have to come back as margin: the overlap is what welds the pieces into one
  // band, and a clue with a mark on it has to occupy exactly the width the same
  // clue does with none.
  assert(band && /padding:\s*var\(--band-pad\)\s*[;}]/.test(band[1] + "}")
    && /margin:\s*0 calc\(-1 \* var\(--band-pad\)\)/.test(band[1]),
    "and it paints that room without measuring it, or marking a word moves it: "
    + (band ? band[1] : "no rule"));
  assert(band && band.index > pills[pills.length - 1].index,
    "and it comes after the pill rules it undoes — same weight, so source order is all there is");
  // That same overlap is the only thing carrying the band across the 1px border
  // every .gw wears, the marked SPACE between two words included. Let it fall
  // under the border width and the run is beaded again at hairline width.
  const gwBorder = (/(?:^|\n)\.gw\s*\{[^}]*\bborder:\s*(\d+)px/.exec(pickCss) || [, null])[1];
  assert(gwBorder && bandPad >= Number(gwBorder),
    `the band paints ${bandPad}px past each piece, which has to reach under the `
    + `${gwBorder}px .gw border on either side of it`);
  assert(/(?:^|\n)\.guess-clue \.gw\s*\{[^}]*position:\s*relative/.test(pickCss),
    "and the word boxes paint above that, so a picked word keeps its border");

  // Cold, the ladder has two locks on it: the assembly rung and the walkthrough.
  open();
  const shut = locked();
  assert(shut.length === 2, "cold, assembly and walkthrough are both locked: " + offered());

  // Take the two spotting rungs, either by pointing at the words or by asking to
  // be told, and report what the ladder looks like afterwards.
  const bothSpotted = (earn) => {
    open();
    for (const k of spot) {
      rung(new RegExp(k.slice(0, 9), "i")).onclick();
      if (!earn) { registry["guess-tell"].onclick(); continue; }
      for (const i of want[k]) registry["gw-" + i].onclick();
      registry["guess-check"].onclick();
      // The verdict is read while the next question stands beside it; then that
      // question is skipped so the ladder is counted as it is after the rung.
      assert(registry["hint-body"].innerHTML.includes("guess-verdict right"),
        `the ${k} rung is earned, not bought: ` + registry["hint-body"].innerHTML);
      dismissNext();
    }
    return { locked: locked(), offered: offeredN(), score: registry["scorebar"].innerHTML,
             text: offered() };
  };

  for (const earn of [false, true]) {
    const how = earn ? "earned" : "asked for outright";
    const r = bothSpotted(earn);
    assert(r.offered.length === 3,
      `${how}: two rungs taken leaves three on the ladder: ` + r.text);
    assert(r.locked.length === 1 && shut.indexOf(r.locked[0]) >= 0,
      `${how}: exactly one of the two locks opened — the walkthrough keeps its own: `
        + r.text);
    assert(r.offered.indexOf(r.locked[0]) >= 0 && r.offered.length - r.locked.length === 2,
      `${how}: the assembly rung and the type rung are both takeable: ` + r.text);
    assert(new RegExp(`\\b${earn ? 0 : 2}</strong> hints used`).test(r.score),
      `${how}: skipping the type rung is free, and changes nothing else's price: `
        + r.score);
  }
}
