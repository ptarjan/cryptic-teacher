// Pointing at words, the blocks rung and runs of words.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { APP_BLOCKS, ROOT, assert, clueText, defTexts, dismissNext, docListeners, entryId, ev, fs,
  isAsking, kd, panelHTML, path, pickerRowFor, registry, shape, storage, stripTags } = T;
// --- point at the words before the rung names them ---
// Three rungs ask first and tell second. Two things have to hold and they pull
// apart: the rung must still arrive whatever you answer (this is a lesson, not
// a gate), and answering it correctly must actually cost nothing, or the
// discount is decoration.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  // A clue whose definition is the opening words of the clue, so the test can
  // name the right buttons without owning a second copy of the matcher.
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const defs = defTexts(e.annotation);
      const def = defs[0];
      if (!def || !clueText(e).startsWith(def)) continue;
      // Whole words, and one definition: a double definition asks for both
      // halves at once and the opening words are then only part of the answer.
      if (defs.length > 1 || !/\s/.test(clueText(e)[def.length] || "")) continue;
      const words = def.trim().split(/\s+/).length;
      // Not the whole clue: guessAsk refuses a question whose answer is
      // everything, and rightly. The enumeration is not a word on offer.
      const offered = clueText(e).replace(/\s*\([^()]*\)\s*$/, "");
      if (words >= offered.split(/\s+/).length) continue;
      found = { id, e, words };
      break;
    }
    if (found) break;
  }
  assert(found, "some clue defines with its opening words");

  const openIt = () => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(found.id);
    assert(li, "picker finds the puzzle to guess on");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(found.e)].listeners.click[0]();
  };
  const defBtn = () => registry["hint-next"].children.find(
    (b) => /definition/i.test(b.textContent || "") && !b.disabled);

  openIt();
  // The clue must not resize the moment tapping starts: at rest every word is
  // already its own .gw box (an inert one — see .gw.still), so tapping only
  // ever recolours borders that were already taking up the room. Pin the
  // BOX COUNT, not a class name, because a
  // clue that renders as plain flowing text at rest and as N bordered chips
  // once tapping starts passes a "contains guess-clue" check just fine while
  // still reflowing under the solver.
  // The worded count "(7, two words)" stays in the text and is not a box
  // (app.js clueTokens).
  const wordCount = (clue) =>
    (clue.replace(/\(\s*\d{1,2}\s*,\s*(two|three|four|five|six|seven|eight)\s+words\s*\)\s*$/i, "")
      .match(/\S+/g) || []).length;
  const boxCount = (html) => (html.match(/class="gw/g) || []).length;
  const restingHTML = registry["hint-clue"].innerHTML;
  const restingBoxes = boxCount(restingHTML);
  assert(restingBoxes === wordCount(clueText(found.e)),
    "every word of the clue is boxed even when nothing is being asked: " + restingHTML);
  const btn = defBtn();
  assert(btn, "the definition rung is offered: " + registry["hint-next"].innerHTML);
  btn.onclick();
  assert(boxCount(registry["hint-clue"].innerHTML) === restingBoxes,
    "and tapping neither adds nor removes a single box, only recolours them: "
      + `${restingBoxes} at rest, ${boxCount(registry["hint-clue"].innerHTML)} tapping`);
  let html = panelHTML();
  // "guess-clue" alone does not tell asking apart from resting — the clue's
  // words are chip-wrapped in both states, so the box never resizes
  // switching between them (see .gw.still in style.css). "ask" is the class
  // that only the actually-asking form carries.
  assert(html.includes("guess-clue ask"), "the definition rung asks before it tells: " + html);
  assert(!html.includes("hint-step\"><span class=\"step-label\">2 ·"),
    "the rung is not handed over while the question is still open: " + html);
  // One clue on the screen, and it is the real one: the words are targets where
  // they are read, not in a second copy in the body.
  assert(/id="gw-\d+"/.test(registry["hint-clue"].innerHTML),
    "the clue's own words are the targets: " + registry["hint-clue"].innerHTML);
  assert(!/id="gw-\d+"/.test(registry["hint-body"].innerHTML),
    "and there is no second copy of the clue to point at instead: "
      + registry["hint-body"].innerHTML);
  assert(!registry["hint-clue"].innerHTML.includes('mark class="def"'),
    "nor is the answer given away by the highlight: " + registry["hint-clue"].innerHTML);
  assert(registry["hint-next"].innerHTML === "",
    "the other rungs are not offered as a way around the question: " + registry["hint-next"].innerHTML);

  // Right: exactly the words, nothing else.
  for (let i = 0; i < found.words; i++) registry["gw-" + i].onclick();
  registry["guess-check"].onclick();
  dismissNext();
  html = panelHTML();
  // The verdict lands on the words as well as in a sentence: "3 of 5" never says
  // WHICH three, and which three is the lesson.
  assert(html.includes("guess-verdict right"), "a correct guess is told so: " + html);
  assert((html.match(/class="gw on hit"/g) || []).length === found.words,
    `every word of a right answer is marked right on the clue itself: ${html}`);
  assert(!/class="gw[^"]*(spare|missed)"/.test(html),
    "and nothing is marked wrong: " + html);
  // The marked clue is not an animation, and the rung is not on a delay. Both
  // arrive on the tap and both are still there afterwards: "it flashes too fast
  // for me to read" was a reading deadline nobody asked for.
  assert(html.includes("hint-step"), "the rung opens on the same tap: " + html);
  assert(!/id="gw-\d+"/.test(html),
    "and the graded words stop being buttons rather than stopping taps: " + html);
  global.flushTimers(10000);
  assert(panelHTML() === html,
    "nothing is on a timer: the verdict and its marked clue stay put: "
      + registry["hint-body"].innerHTML);
  assert(registry["hint-clue"].innerHTML.includes('mark class="def"'),
    "the definition is highlighted once the rung is up");
  // And it is highlighted as one band. The picker prints the clue a word at a
  // time, so a run arrives as a piece per word and a piece per space; the pieces
  // may differ only at the run's two ENDS, which is what style.css rounds off.
  // An unmarked character anywhere between the first piece and the last is a
  // gap the band cannot cross.
  {
    const lit = registry["hint-clue"].innerHTML;
    const run = lit.match(/<mark class="def"[^>]*>[\s\S]*?<\/mark>/g) || [];
    const edges = (p) => ((p.match(/data-edge="([^"]*)"/) || [, ""])[1]).split(" ").filter(Boolean);
    assert(run.length && edges(run[0]).includes("start")
           && edges(run[run.length - 1]).includes("end"),
      "the definition's first and last pieces are the ends of the run: " + lit);
    assert(run.slice(1, -1).every((p) => !edges(p).length),
      "and no piece inside it claims to be an end — those are the beads: " + lit);
    const whole = lit.slice(lit.indexOf(run[0]),
      lit.lastIndexOf(run[run.length - 1]) + run[run.length - 1].length);
    const bare = stripTags(whole.replace(/<mark class="def"[^>]*>[\s\S]*?<\/mark>/g, ""), "");
    assert(bare === "",
      "and the spaces between its words are marked too, so the band is unbroken: "
        + JSON.stringify(bare));
  }
  assert(/\b0<\/strong> hints used/.test(registry["scorebar"].innerHTML),
    "a rung you earned costs nothing: " + registry["scorebar"].innerHTML);

  // Wrong: every word in the clue is never the answer to any of these.
  openIt();
  defBtn().onclick();
  const words = (panelHTML().match(/id="gw-\d+"/g) || []).length;
  assert(words > found.words, "the clue offers more words than the definition uses");
  for (let i = 0; i < words; i++) registry["gw-" + i].onclick();
  registry["guess-check"].onclick();
  html = panelHTML();
  assert(html.includes("guess-verdict miss"), "a wrong guess is told so: " + html);
  assert((html.match(/class="gw on hit"/g) || []).length === found.words &&
         /class="gw on spare"/.test(html),
    `the words that were doing the job are told apart from the ones that weren't: ${html}`);
  assert(html.includes("hint-step"), "and the rung still opens — never a gate: " + html);
  global.flushTimers(10000);
  assert(panelHTML() === html,
    "a miss is left on screen to be read too: " + registry["hint-body"].innerHTML);
  assert(/\b1<\/strong> hints used/.test(registry["scorebar"].innerHTML),
    "a rung you did not earn still costs one: " + registry["scorebar"].innerHTML);

  // And the escape hatch out of the question itself.
  openIt();
  defBtn().onclick();
  assert(panelHTML().includes("guess-clue ask"), "asked again");
  registry["guess-tell"].onclick();
  assert(registry["hint-body"].innerHTML.includes("hint-step"), "“Just tell me” tells you");
  assert(!registry["hint-body"].innerHTML.includes("guess-verdict"),
    "declining to guess is not graded");
  assert(/\b1<\/strong> hints used/.test(registry["scorebar"].innerHTML),
    "and costs what the rung has always cost: " + registry["scorebar"].innerHTML);

  // And the other way out: you stop hunting for the definition because you have
  // just written the answer into the grid. Leaving the question up would be the
  // site quizzing you on a clue you had already beaten, so the rung is handed
  // over — free, the score being settled. Quietly: one clue
  // coming out gets no announcement, only the finished grid does.
  openIt();
  defBtn().onclick();
  assert(panelHTML().includes("guess-clue ask"), "asked a third time");
  // Typed, not clicked square by square: a click on a crossing cell can pick
  // the other entry, and moving to another clue abandons the guess by design.
  // The solver being described here never left the clue.
  for (let i = 0; i < found.e.length; i++) kd(ev(found.e.solution[i]));
  html = registry["hint-body"].innerHTML;
  assert(!isAsking(registry["hint-body"]),
    "solving the clue takes the question away: " + html);
  assert(html.includes("hint-step"),
    "and hands over the rung it was asking about rather than dropping it: " + html);
  assert(html.indexOf("class=\"paper\"") < 0,
    "and throws no paper at a single clue: " + html);
}

// --- the blocks rung pays out one piece at a time, and never takes anything back ---
// A charade's assembly is "read the pieces in order", so a rung that hands over
// every piece at once is not a hint, it is the answer — and 78% of annotated
// clues are built from more than one piece. Each piece is its own question and
// its own reveal, and whether to go on to the next one is the solver's call.
// One rung, one price, however many pieces are taken.
//
// And, same screen: opening a new hint must not delete the previous verdict or
// empty the rung buttons, or the panel collapses under the solver at the moment
// a new question appears below.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const escHtml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  // Exactly how the rung renders a piece's letters, so "is piece 2 on screen"
  // is a question about the markup and not about whether one answer's letters
  // happen to appear inside another's.
  const givesSpan = (s) => `<span class="gives">${escHtml(s)}</span>`;
  const tokensOf = (clue) => {
    const body = String(clue || "").replace(/\s*\([^()]*\)\s*$/, "");
    const out = [];
    const re = /\S+/g;
    let m;
    while ((m = re.exec(body))) out.push({ i: m.index, text: m[0] });
    return out;
  };
  // The test only takes on fragments it can locate WITHOUT a copy of the app's
  // matcher: exactly one occurrence, on whole-word boundaries. Anything fuzzier
  // is a candidate skipped, not a wrong answer submitted.
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
  // Climb to the named rung, taking whatever is offered and declining every
  // question on the way, so the blocks rung is reached with the tier-0 rungs up.
  const climbTo = (re) => {
    for (let i = 0; i < 8; i++) {
      const want = rung(re);
      if (want) return want;
      const b = rungs().find((x) => !x.disabled);
      if (!b) return null;
      b.onclick();
      if (asking()) registry["guess-tell"].onclick();
    }
    return null;
  };
  const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
  // The pieces the matching question would be made of: every building block
  // that names words in the clue and shows letters that are not those same
  // words. What a block shows is app.js's blockLetters (see APP_BLOCKS).
  const { blockLetters, buildingBlocks } = APP_BLOCKS;
  const pairsOf = (e) => {
    const a = e.annotation;
    if (!a || a.redo) return [];  // a clue flagged for redo has no blocks rung
    return buildingBlocks(a).map((b) => ({ ...b, gives: blockLetters(a, b) }))
      .filter((b) => b.clueFragment && b.gives && bare(b.clueFragment) !== bare(b.gives));
  };

  // Two pairs is not a matching question: the last pairing is forced in any of
  // them, and with two the first one IS the last, so placing one chunk placed
  // the other. Those clues get the paced question instead. Asserted before the
  // walk below so it opens its own clue and leaves no state behind.
  {
    let two = null;
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        if (pairsOf(e).length !== 2) continue;
        if (!openClue(id, e)) continue;
        const b = climbTo(/building blocks/i);
        if (!b) continue;
        b.onclick();
        two = { id, e, html: registry["hint-body"].innerHTML };
        break;
      }
      if (two) break;
    }
    if (shape("a two-piece clue to check the floor against", two)) {
      assert(!/id="gm-slot-\d+"/.test(two.html),
        `a two-piece clue is asked a piece at a time, not matched (${two.id} ${
          entryId(two.e)}): ` + two.html.slice(0, 300));
    }
  }

  let walked = null, tried = 0;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      if (walked || tried > 30) break;
      const a = e.annotation;
      // Pieces are ALL the blocks, in clue order — the same list the rung draws
      // and the same one the questions are numbered off. A clue whose first two
      // pieces give the same letters cannot answer "is piece 2 on screen yet",
      // so it is skipped rather than guessed at.
      const bl = (a && !a.redo && a.blocks) || [];  // a redo clue has no blocks rung
      if (bl.length < 2) continue;
      // The growth check below taps a wrong definition, so the clue needs one in
      // its own words: not one its puzzle's preamble supplies.
      if (a.definedByPreamble || !(a.definitions || []).length) continue;
      if (!bl[0].gives || !bl[1].gives || bl[0].gives === bl[1].gives) continue;
      if (!bl[0].clueFragment || !bl[1].clueFragment) continue;
      const spans = bl.map((b) => b.clueFragment ? spanTokens(clueText(e), b.clueFragment) : null);
      if (spans.slice(0, 2).some((s) => !s)) continue;
      // The pieces the matching question is made of: the app leaves out any
      // fragment that IS its own letters, because that chip pairs itself.
      const pairs = pairsOf(e);
      if (pairs.length < 3) continue;
      // Two pieces giving the same chunk are graded right either way round, so
      // "did this row get its own chip" is not a question about that clue.
      if (pairs.filter((b, i) => pairs.findIndex((x) => x.gives === b.gives) !== i).length) continue;
      tried++;
      if (!openClue(id, e)) continue;
      const blocks = climbTo(/building blocks/i);
      if (!blocks) continue;
      // Whatever the climb cost is the baseline: the blocks rung must add
      // nothing to it while its own question is still open, and nothing to it at
      // all if every piece asked for is answered right.
      const paid = registry["scorebar"].innerHTML;
      blocks.onclick();
      if (!asking()) continue;
      walked = { id, e, bl, paid, pairs };
    }
    if (walked) break;
  }
  assert(walked, "somewhere in the corpus the blocks rung asks its matching question "
    + `(tried ${tried} clues with two or more locatable pieces)`);
  if (!walked) throw new Error("the blocks rung asks nothing — see the FAIL above");

  // One question about the whole charade, not one click per piece. Every
  // fragment gets a row, every chunk a chip, and nothing is paired up for you.
  // Paced a click each, by the last piece the question would answer itself by
  // elimination.
  let html = panelHTML();
  const idsIn = (re) => (html.match(re) || []).length;
  assert(idsIn(/id="gm-slot-\d+"/g) === walked.pairs.length,
    `a row per fragment (${walked.pairs.length}): ` + html);
  assert(idsIn(/id="gm-chip-\d+"/g) === walked.pairs.length,
    "and a chip per chunk, none of them spent yet: " + html);
  walked.pairs.forEach((b) => assert(!html.includes(givesSpan(b.gives)),
    `${b.gives} is on the strip to be placed, never placed for you: ` + html));
  assert(/id="guess-check"[^>]*disabled/.test(html),
    "and it cannot be checked while rows are still empty: " + html);

  // Which chip is which, read off the markup rather than off the app's own
  // ordering — a test that asked the app where it put things would agree with
  // it however it was shuffled.
  const chipAt = {};
  String(html).replace(/id="gm-chip-(\d+)"[^>]*>([^<]*)</g,
    (_, n, text) => { chipAt[text] = +n; return ""; });
  assert(Object.keys(chipAt).length === walked.pairs.length,
    "every chunk is legible on the strip: " + JSON.stringify(chipAt));
  assert(walked.pairs.map((b) => chipAt[b.gives]).join() !== walked.pairs.map((_, i) => i).join(),
    "the chunks are shuffled — in clue order the question is answered by reading "
      + "straight down the rows: " + JSON.stringify(chipAt));

  // Either order pairs. A row tapped with nothing in hand arms itself and waits
  // for a chunk.
  registry["gm-slot-0"].onclick();
  assert(/id="gm-slot-0" class="gm-slot armed"/.test(panelHTML()),
    "a row tapped first arms itself: " + panelHTML());
  registry["gm-chip-" + chipAt[walked.pairs[0].gives]].onclick();
  assert(/id="gm-slot-0" class="gm-slot on"/.test(panelHTML()),
    "and the next chunk tapped lands in it: " + panelHTML());
  // A pair made leaves the strip exactly where it was, the placed chunk's
  // space kept and hidden. Closing the gap would slide the next chunk under the
  // finger that had just placed one, wearing that finger's hover border — the
  // page appearing to pick out the next answer.
  {
    const strip = (h) => ((String(h).match(/<p class="gm-chips">([\s\S]*?)<\/p>/) || [])[1] || "")
      .match(/<button[^>]*>[^<]*<\/button>/g) || [];
    const text = (b) => stripTags(b, "");
    const after = strip(panelHTML());
    assert(after.map(text).join("|") === strip(html).map(text).join("|"),
      "placing a chunk moves no other chunk on the strip: "
        + strip(html).map(text).join("|") + " became " + after.map(text).join("|"));
    const spent = after.filter((b) => !/id="gm-chip-/.test(b));
    assert(spent.length === 1 && /class="gc spent"/.test(spent[0]) && /disabled/.test(spent[0]),
      "and the placed one stays as a dead placeholder, not a chip to tap: " + after.join(""));
    const bare = fs.readFileSync(path.join(ROOT, "style.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    assert(/\.gm-chips \.gc\.spent\s*\{[^}]*visibility:\s*hidden/.test(bare),
      "and it is hidden by visibility, which keeps its space, not display, which gives it up");
  }
  // Hand it back, so the walk below starts from the empty board it expects.
  registry["gm-slot-0"].onclick();
  registry["gm-chip-" + chipAt[walked.pairs[0].gives]].onclick();
  assert(/id="gm-slot-0" class="gm-slot"/.test(panelHTML()),
    "and tapping a filled row empties it again: " + panelHTML());

  // Answer it, right, by pairing every row with its own chunk.
  walked.pairs.forEach((b, i) => {
    registry["gm-chip-" + chipAt[b.gives]].onclick();
    registry["gm-slot-" + i].onclick();
  });
  assert(!/id="guess-check"[^>]*disabled/.test(panelHTML()),
    "a full board can be checked: " + panelHTML());
  registry["guess-check"].onclick();
  dismissNext();

  html = panelHTML();
  assert(!asking(), "answering it ends the question: " + html);
  // The question covered every piece, so answering it settles every piece.
  // Anything still paced here would be make-work.
  walked.pairs.forEach((b) => assert(html.includes(givesSpan(b.gives)),
    `${b.gives} is handed over with the rest of the split: ` + html));
  assert(!rung(/next piece/i),
    "and no piece is left to buy: " + registry["hint-next"].innerHTML);
  assert(registry["scorebar"].innerHTML === walked.paid,
    "nothing was bought — the question was answered right: "
      + registry["scorebar"].innerHTML);

  // --- the panel only ever grows ---
  // A graded verdict on one rung, then a different rung asked for. Both the
  // verdict and the ladder must still be there: deleting either one moves every
  // word on the screen at the moment the solver is being asked to read.
  assert(openClue(walked.id, walked.e), "reopen the clue for the growth check");
  const def = rung(/definition/i);
  assert(def, "the definition rung is offered: " + registry["hint-next"].innerHTML);
  def.onclick();
  assert(asking(), "and asks before telling: " + registry["hint-body"].innerHTML);
  // Deliberately wrong, so there is a verdict to lose. The last word of a clue is
  // never the whole definition of one that starts with it.
  const last = (panelHTML().match(/id="gw-(\d+)"/g) || []).pop();
  if (assert(last, "the definition question offers words to tap: " + panelHTML()))
    registry[last.slice(4, -1)].onclick();
  registry["guess-check"].onclick();
  assert(registry["hint-body"].innerHTML.includes("guess-verdict"), "graded");
  // On to a rung that poses its own question, since that is the moment the old
  // verdict could be swept away to make room for the new one.
  let before = "";
  for (let i = 0; i < 5 && !asking(); i++) {
    const another = rungs().find((b) => !b.disabled);
    assert(another, "another rung is still on offer: " + rungs().length);
    before = registry["hint-body"].innerHTML;
    another.onclick();
  }
  assert(asking(), "a second question gets asked: " + registry["hint-body"].innerHTML);
  const after = registry["hint-body"].innerHTML;
  assert(after.includes("guess-verdict"),
    "asking for a new hint does not delete the verdict you were reading: " + after);
  // One thing does go: the verdict's graded copy of the clue (verdictHTML's
  // `quiet`), because the clue line above is now the tapping surface for the new
  // question and two copies of the same words is a duplicate. A long clue's copy is longer than the question that replaces it,
  // so the growth is measured without it.
  const kept = (h) => h.replace(/<p class="guess-clue mk[^"]*">[\s\S]*?<\/p>/g, "");
  assert(kept(after).length >= kept(before).length,
    `the panel only ever grows (${walked.id} ${entryId(walked.e)}): `
      + kept(before).length + " -> " + kept(after).length
      + "\nbefore: " + before + "\nafter: " + after);
  // The ladder stays reachable while a question stands, so a solver who simply
  // picked the wrong rung is not cornered. Switching abandons the question; it never answers
  // it, so nothing is earned by leaving.
  assert(rungs().some((b) => !b.disabled),
    "and another rung can still be taken while the question stands: "
      + registry["hint-next"].innerHTML);
  {
    const other = rungs().find((b) => !b.disabled);
    const label = other.textContent;
    const before2 = registry["hint-body"].innerHTML;
    // The standing question is swapped for the new one, not kept: a choice or
    // pairs question draws its options in the panel, a tap-in-the-clue question
    // draws none there, so the question's own size may fall across a switch. What
    // must not shrink is everything settled above it (verdicts, rungs), and the
    // question always goes last in the body. Text, not markup: the switch moves
    // the hint-focus wrapper from the verdict to the new question and drops the
    // verdict's "fresh" class, ~33 characters of tags with nothing taken away
    // (run 41158582032).
    // Tags stripped to a fixed point (one pass can leave a tag the strip itself
    // joined up: code-scanning alert 54).
    const untag = (h) => { let was; do { was = h; h = h.replace(/<[^>]*>/g, ""); } while (h !== was); return h; };
    const settled = (h) => untag(kept(h).replace(/(<div id="hint-focus">)?<div class="hint-step guess"[\s\S]*$/, ""));
    const grew = settled(before2).length;
    other.onclick();
    const after2 = registry["hint-body"].innerHTML;
    assert(settled(after2).length >= grew, "the panel still only grows across a switch: " + label
      + " (" + grew + " -> " + settled(after2).length + ")\nbefore: " + before2 + "\nafter: " + after2);
    // The rung the solver walked away from was never answered, so nothing new
    // may be marked as worked out on the way past.
    const won = (h) => (h.match(/hint-step won/g) || []).length;
    assert(won(after2) === won(before2),
      `an abandoned question earns nothing: ${won(before2)} -> ${won(after2)} on ${label}`);
    assert(registry["hint-next"].children.length > 0,
      "and the ladder row is still there after the switch");
  }

  // --- putting a question back down costs nothing ---
  // The tap that opened it meant "show me this rung", and a solver who reads
  // the question and cannot honestly answer it must not be cornered into
  // buying the rung to escape ("having a building block charge me with no way
  // to get it free when the letter match doesn't feel good"). Nothing was
  // shown, so the price is unchanged and the rung
  // goes back on the ladder, still willing to ask.
  const paidBefore = registry["scorebar"].innerHTML;
  const bodyBefore = registry["hint-body"].innerHTML;
  registry["guess-later"].onclick();
  assert(!asking(), "\"Not yet\" takes the question off the table: "
    + registry["hint-body"].innerHTML);
  assert(registry["scorebar"].innerHTML === paidBefore,
    "and charges nothing for it: " + paidBefore + " -> " + registry["scorebar"].innerHTML);
  // Measured without the verdict's clue copy, which comes back once the clue
  // line stops being a tapping surface and can outweigh the question it replaces.
  assert(kept(registry["hint-body"].innerHTML).length < kept(bodyBefore).length,
    "the question is gone, not merely disarmed: " + registry["hint-body"].innerHTML);
  const back = rungs().find((b) => !b.disabled);
  assert(back, "the ladder is live again: " + registry["hint-next"].innerHTML);
  back.onclick();
  assert(asking() || registry["scorebar"].innerHTML !== paidBefore,
    "and the rung it declined can still be reached: " + registry["hint-body"].innerHTML);
}

// --- a save with the blocks rung shown and no count reveals nothing extra ---
// A save can have "blocks" in hintsShown with no count to say how far it got —
// one from before the rung was paced, or one a sync merge damaged. piecesShown()
// cannot tell them apart and must not act as if it can: either way, the right
// read is that nothing beyond what is already implied has been shown.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  let target = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      if (!a) continue;
      if ((a.blocks || []).length >= 2 && (a.blocks || []).some((b) => b.gives)) {
        target = { id, e };
        break;
      }
    }
    if (target) break;
  }
  if (shape("a multi-piece blocks rung to damage", target)) {
    const { id, e } = target;
    const key = "ct:" + id;
    const kept = storage[key];
    // hintsShown says the rung was opened; blocksAt says nothing at all.
    storage[key] = JSON.stringify({ hintsShown: { [entryId(e)]: ["blocks"] }, updated: Date.now() });

    registry["btn-picker"].onclick();
    const li = pickerRowFor(id);
    assert(li, `the picker can reopen puzzle ${puzzles[id].number} to reload the damaged save`);
    if (li) {
      li.children[0].onclick();
      registry["clue-" + entryId(e)].listeners.click[0]();
      const html = registry["hint-body"].innerHTML;
      assert(!/class="gives"/.test(html),
        "a rung shown with no blocksAt count reveals no pieces on reload, not every piece: "
          + html.slice(0, 300));
    }

    if (kept === undefined) delete storage[key]; else storage[key] = kept;
  }
}

// --- a run of words is one gesture, and a settled word is not a choice ---
// Two things asked for on the same screen. Dragging across the words picks
// the run under the finger, because a definition IS a run and four taps is four
// chances to be interrupted. And a word an earlier rung already named cannot be
// offered as an answer to the next one: it is on the screen as fact, so letting
// it be picked means marking someone wrong for reading.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  // Definition at the front, indicators somewhere else, so the test can name the
  // definition's buttons without a second copy of the span matcher.
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      const defs = defTexts(a);
      if (defs.length !== 1 || !(a.indicators || []).length) continue;
      const def = defs[0];
      if (!clueText(e).startsWith(def) || !/\s/.test(clueText(e)[def.length] || "")) continue;
      const words = def.trim().split(/\s+/).length;
      const all = clueText(e).replace(/\s*\([^()]*\)\s*$/, "").split(/\s+/).length;
      // Two words at least, or there is no run to drag across; and never the
      // whole clue, which guessAsk refuses to make a question of.
      if (words < 2 || words >= all) continue;
      if ((a.indicators || []).some((t) => def.includes(t.text))) continue;
      found = { id, e, words, all };
      break;
    }
    if (found) break;
  }
  assert(found, "some clue opens with a two-word definition and has an indicator");

  const open = () => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(found.id);
    assert(li, "picker finds the puzzle to drag on");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(found.e)].listeners.click[0]();
  };
  const rung = (re) => registry["hint-next"].children.find(
    (b) => re.test(b.textContent || "") && !b.disabled);
  const fire = (type, ev) => (docListeners[type] || []).forEach((f) => f(ev));
  // The harness lays the words out one x apart on y=0 — see elementFromPoint.
  const dragAcross = (from, to) => {
    registry["gw-" + from].listeners.pointerdown[0]({});
    fire("pointermove", { clientX: to, clientY: 0 });
    fire("pointerup", {});
  };
  const onNow = () => (panelHTML().match(/class="gw on"/g) || []).length;

  // Drag the definition's run in one gesture.
  open();
  rung(/definition/i).onclick();
  dragAcross(0, found.words - 1);
  assert(onNow() === found.words,
    `a drag picks every word it crossed and no others: ${registry["hint-body"].innerHTML}`);
  assert(!registry["guess-check"].disabled, "and arms the check button");
  registry["guess-check"].onclick();
  assert(registry["hint-body"].innerHTML.includes("guess-verdict right"),
    "so the run can be the whole answer: " + registry["hint-body"].innerHTML);

  // A tap is still a tap: pointerdown and pointerup on the same word must toggle
  // rather than be swallowed as the tail of a drag.
  open();
  rung(/definition/i).onclick();
  registry["gw-0"].listeners.pointerdown[0]({});
  fire("pointermove", { clientX: 0, clientY: 0 });
  fire("pointerup", {});
  registry["gw-0"].onclick();
  // Read off the elements, not the panel's HTML. A tap repaints the words where
  // they stand and rebuilds nothing, so the string the panel was last built from
  // still describes the moment before the tap. In a browser the class attribute
  // and innerHTML are one fact; in this DOM they are two, and the class is the
  // one a tap writes.
  assert(registry["gw-0"].classList.contains("on")
         && !registry["gw-1"].classList.contains("on")
         && !registry["guess-check"].disabled,
    "a tap that never left the word still toggles it, and only it: "
    + registry["gw-0"].className + " / " + registry["gw-1"].className
    + " / check disabled: " + registry["guess-check"].disabled);

  // Settled words: take the definition, then be asked about the indicators.
  open();
  rung(/definition/i).onclick();
  registry["guess-tell"].onclick();
  const ind = rung(/indicator/i);
  assert(ind, "the indicators rung is offered next: " + registry["hint-next"].innerHTML);
  ind.onclick();
  const html = registry["hint-body"].innerHTML;
  if (html.includes("guess-clue")) {
    const asked = html.slice(html.indexOf("guess-clue"));
    assert((asked.match(/class="gw known"/g) || []).length === found.words,
      "every word the definition rung named is marked as already known: " + asked);
    for (let i = 0; i < found.words; i++) {
      assert(!asked.includes(`id="gw-${i}"`),
        `and word ${i} is not a button to be marked wrong for: ` + asked);
    }
    assert(/id="gw-\d+"/.test(asked), "while the rest of the clue is still in play: " + asked);
  } else {
    // Legitimate: with the definition settled, what was left may BE the answer,
    // and a question answerable by elimination is not asked at all.
    assert(html.includes("hint-step"), "or the question is dropped, not broken: " + html);
  }
}
