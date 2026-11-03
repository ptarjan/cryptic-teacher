// Finished marks in the picker, link words and definition notes, the lesson page.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { CLIMBABLE, CLUE_TYPES, LADDER, ROOT, allPuzzles, answerShown, appSrc, assert, clueText,
  cpToIdx, enough, entryId, fs, htmlEsc, isAsking, openFromPicker, path, pickerRowFor, printedClue,
  registry, reopenForSweep, rungTemplateProse, saveFromAnotherTab, shape, storage, stripTags,
  takeRung } = T;
// --- the picker says which puzzles you have finished ---
// "Have I done this one?" is the first question the list has to answer. It is derived, not stored — from the saved letters against the
// loaded solutions — so a change to either side can silently break it without
// breaking anything else. Drive it from both directions: a complete correct
// grid must read solved, one letter short must not.
{
  const target = allPuzzles.find((p) => p.annotated && p.hasSolutions
    && global.window.CRYPTIC_PUZZLES[p.id]);
  const puz = global.window.CRYPTIC_PUZZLES[target.id];
  const letters = {};
  puz.entries.forEach((e) => {
    for (let i = 0; i < e.length; i++) {
      const x = e.position.x + (e.direction === "across" ? i : 0);
      const y = e.position.y + (e.direction === "across" ? 0 : i);
      letters[x + "," + y] = e.solution[i];
    }
  });
  const key = "ct:" + target.id;
  const kept = storage[key];
  const rowHTML = () => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(target.id);
    return li ? li.children[0].innerHTML : "";
  };

  // What the row says about progress, which is the only part of it these two
  // assertions are about. Read out rather than sliced off the front: the row
  // leads with the number, the setter, the date and four badges, so the first
  // 200 characters of it are the same whichever way this fails, and a failure
  // that cannot say which half of the `&&` went wrong sends the reader to the
  // wrong half.
  const progressIn = (html) =>
    (html.match(/<span class="p-prog[^"]*"[^>]*>([^<]*)</) || [, "(nothing at all)"])[1].trim();

  saveFromAnotherTab(key, JSON.stringify({ letters, updated: 1 }));
  const full = rowHTML();
  assert(/solved ✓/.test(full),
    `a complete, correct grid reads as solved in the picker, but the row says `
    + `"${progressIn(full)}"`);

  const oneShort = Object.assign({}, letters);
  delete oneShort[Object.keys(oneShort)[0]];
  saveFromAnotherTab(key, JSON.stringify({ letters: oneShort, updated: 1 }));
  const partial = rowHTML();
  const want = Object.keys(letters).length + " letters filled";
  assert(!/solved ✓/.test(partial) && new RegExp(want).test(partial),
    `one square short is not solved and says how far along it is: the row says `
    + `"${progressIn(partial)}", wanted "${want}"`);

  saveFromAnotherTab(key, kept);
}

// --- link words and definition notes reach the screen ---
// Both fields exist to answer a learner's question — "what does this word do?"
// and "why doesn't the definition match the answer?" — so data that never
// renders is worse than no data. Drive the real UI to a clue that has each.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const findClue = (field) => {
    const has = typeof field === "function" ? field
      : (a) => (Array.isArray(a[field]) ? a[field].length : a[field]);
    for (const id of Object.keys(puzzles).sort().reverse()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation;
        if (a && has(a)) return { id, e };
      }
    }
    return null;
  };
  const openClue = ({ id, e }) => {
    // Searched for rather than scanned out of the default list: the default list
    // is annotated-only, and a puzzle can carry annotated clues while its index
    // flag says otherwise (mid-annotation, or a partial hand-edit).
    reopenForSweep(id, entryId(e));
    const row = registry["clue-" + entryId(e)];
    assert(row && row.listeners.click, `clue list shows ${e.number}${e.direction[0]}: ${clueText(e)}`);
    row.listeners.click[0]();
    // The definition rung and NOTHING else, which is where linkWords
    // hang. By name and on its own: climbing to it by taking
    // whatever leads pins the ladder's order into a helper about something
    // else, and swallows the indicators rung that three later tests assert is
    // still on offer. It is tier 0, so it is reachable from cold whatever
    // leads.
    const defBtn = registry["hint-next"].children.find(
      (b) => b.onclick && !b.disabled && /definition/i.test(b.textContent));
    if (defBtn) takeRung(defBtn);
  };

  const linked = findClue("linkWords");
  assert(linked, "at least one annotation names its link words");
  openClue(linked);
  assert(registry["hint-body"].innerHTML.includes("is a link word:") || registry["hint-body"].innerHTML.includes("are link words:"),
    "link words are explained on the definition rung: " + registry["hint-body"].innerHTML);
  assert(registry["hint-clue"].innerHTML.includes('mark class="link"'),
    "link words are highlighted in the clue: " + registry["hint-clue"].innerHTML);

  // A link word touching the definition is the seam, not wordplay: the
  // definition rung must not quote it as the wordplay's first word.
  const seamLink = (a, e) => {
    const d = (a.definitions || [])[0];
    if (!d || d.at !== 0 || !d.text) return null;
    const rest = clueText(e).slice(d.text.length).trimStart().toLowerCase();
    return (a.linkWords || []).find((w) => w && rest.startsWith(w.toLowerCase())
      && !/[a-z0-9]/i.test(rest.charAt(w.length))) || null;
  };
  let seam = null;
  for (const id of Object.keys(puzzles).sort().reverse()) {
    const e = (puzzles[id].entries || []).find((x) => x.annotation && seamLink(x.annotation, x));
    if (e) { seam = { id, e }; break; }
  }
  if (seam) {
    openClue(seam);
    const w = seamLink(seam.e.annotation, seam.e);
    assert(!registry["hint-body"].innerHTML.includes("“" + w),
      `a link word next to the definition is not quoted as wordplay (${seam.id} ${entryId(seam.e)}): ` +
      registry["hint-body"].innerHTML);
  }

  // A definition's `note` explains why the definition does not agree with the ANSWER,
  // so it is written about the answer and routinely names it.
  // It belongs beside definitionFit on the walkthrough, not on the definition
  // rung. Assert BOTH ends: absent early, present late. Only checking that it is
  // shown somewhere would let it sit on the wrong rung.
  const noted = findClue((a) => (a.definitions || []).some((d) => d.note));
  assert(noted, "at least one annotation explains a definition that disagrees with its answer");
  openClue(noted);
  assert(!registry["hint-body"].innerHTML.includes("def-note"),
    "the definition note is NOT on the definition rung — it names the answer: " +
    registry["hint-body"].innerHTML);
  for (let i = 0; i < 8; i++) {
    const btn = registry["hint-next"].children[0];
    if (!CLIMBABLE(btn)) break;
    takeRung(btn);
  }
  assert(registry["hint-body"].innerHTML.includes("def-note"),
    "the definition note is shown on the walkthrough rung: " + registry["hint-body"].innerHTML);

  // --- a cryptic definition must not sell the answer on the blocks rung ---
  // The type has no wordplay, so the only "block" available is the whole clue
  // giving the whole answer, one rung after a hint that says there is nothing to
  // take apart. The validator rejects that annotation and app.js suppresses
  // `gives` for the type; this drives the real ladder to prove it, on every
  // cryptic definition there is.
  {
    const cds = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        if (JSON.stringify((e.annotation || {}).type) === '["cryptic_definition"]') cds.push({ id, e });
      }
    }
    shape("a cryptic definition whose answer the ladder must not leak", cds.length);
    // The fixed prose is the family and type blurbs and labels and every
    // literal stretch of the rungs' html templates in app.js: "picture
    // something else at first" is not a leak of FIRST, nor "Mechanism:
    // cryptic definition" of CRYPT (app.js masks a label only where it is the
    // answer as a word).
    const LADDER_PROSE = [...CLUE_TYPES.families.flatMap(f => [f.blurb, f.label]),
      ...CLUE_TYPES.types.flatMap(t => [t.blurb, t.label]),
      ...rungTemplateProse(appSrc).map(t => t.replace(/<[^>]*>|&[#\w]+;/g, " ")),
      // The rule chip's label, its lesson link and the general rules behind it
      // (DEVICE_RULES, FAMILY_RULES) are written once for every clue too:
      // "often flags the playful kind" is not a leak of FLAG.
      "rule", "More in the lesson",
      // The blog badge's provisional note (blogHintsBadge in app.js).
      "ours to come",
      ...[...appSrc.slice(appSrc.indexOf("const DEVICE_RULES = {"), appSrc.indexOf("const SELECT_OPS"))
        .matchAll(/"([^"]*)"/g)].map(m => m[1]),
      // The hint formula's fixed words (formulaOf in app.js): OP_WORDS, the
      // cutWords phrases and the connectives, read from the source so a new
      // label is covered at once.
      ...[...appSrc.slice(appSrc.indexOf("const cutWords = "), appSrc.indexOf("const chipless = "))
        .matchAll(/"([^"$]*)"|`([^`$]*)/g)].map(m => m[1] || m[2]),
      "minus", "inside", "with", "moved", "made from", "letter", "letters", "definition", "answer"]
      .map(t => (t || "").replace(/[^A-Za-z]/g, "").toUpperCase()).filter(Boolean);
    for (const cd of cds) {
      const ans = (cd.e.annotation.answer || "").replace(/[^A-Za-z]/g, "").toUpperCase();
      const where = `${cd.id} ${entryId(cd.e)} (${ans})`;
      // Under four letters the answer turns up in the ladder's own fixed prose —
      // "Either two plain definitions" for TWO — so, as in the validator's
      // check_cryptic_definition_blocks, it is too short to call a leak.
      const tooShort = ans.length < 4;
      openClue(cd);
      // Climb to the rung BEFORE the walkthrough: every rung a learner can buy
      // without committing to the last one must leave the answer unspoken.
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!CLIMBABLE(btn)) break;
        if (/walkthrough/i.test(btn.textContent)) break;
        takeRung(btn);
        // The rung's text, not its markup: tag names are letters too, and
        // "a spade a spade" + "</span>" reads as SPADES. The ladder's fixed
        // prose is cut out, each piece leaving a break: "built from any" reads
        // as OMAN, and no clue put it there.
        let bare = registry["hint-body"].innerHTML
          .replace(/<span class="step-label">[^<]*<\/span>|<div class="legend">[\s\S]*?<\/div>/g, " ")
          .replace(/<[^>]*>|&[#\w]+;/g, " ").replace(/[^A-Za-z]/g, "").toUpperCase();
        for (const fixed of LADDER_PROSE) bare = bare.split(fixed).join("-");
        assert(tooShort || !bare.includes(ans),
          `${where}: a rung before the walkthrough spells the answer out — ` +
          registry["hint-body"].innerHTML);
      }
      const btn = registry["hint-next"].children[0];
      assert(btn && /walkthrough/i.test(btn.textContent || ""),
        `${where}: the ladder still ends at the walkthrough, got ` +
        ((btn && btn.textContent) || "nothing"));
      takeRung(btn);
      // A clue the checker flagged shows "Being rewritten" in place of its walkthrough.
      assert(answerShown(registry["hint-body"].innerHTML, ans) || registry["hint-body"].innerHTML.includes('class="redo-note"'),
        `${where}: the walkthrough is where the answer finally appears: ` + registry["hint-body"].innerHTML);
    }
  }

  // --- the ladder's fixed prose never says the answer ---
  // The family and type sentences are written once for every clue of their
  // kind, so each of their words is somebody's answer: OTHER, CLUE, CHARADE and
  // dozens more would print on the type or blocks rung of their own clue.
  // app.js blanks the answer out of that prose (maskAnswer); this drives the
  // real ladder on every clue whose own family label, family blurb, type name or
  // type sentence contains its answer as a word, and reads those paragraphs.
  {
    const TYPE = Object.fromEntries(CLUE_TYPES.types.map((t) => [t.name, t]));
    const says = (text, answer) => {
      const words = String(answer || "").match(/[A-Za-z]+/g) || [];
      return words.length > 0 &&
        new RegExp(`\\b${words.join("[\\s\\-'\u2019]*")}\\b`, "i").test(String(text).replace(/<[^>]*>/g, " "));
    };
    const hits = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation || {};
        const t = a.type || [];
        if (!a.answer || !t.length) continue;
        const fam = CLUE_TYPES.families.find((f) => t.some((k) => TYPE[k].family === f.name)) || { label: "", blurb: "" };
        const prose = [fam.label, fam.blurb, ...t.flatMap((k) => [TYPE[k].label, TYPE[k].blurb])];
        if (says(prose.join(" "), a.answer)) hits.push({ id, e });
      }
    }
    shape("a clue whose answer is a word of its own family or type prose", hits.length);
    for (const h of hits) {
      openClue(h);
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!CLIMBABLE(btn) || /walkthrough/i.test(btn.textContent)) break;
        takeRung(btn);
        const html = registry["hint-body"].innerHTML;
        const fixed = html.match(/<p><strong>[\s\S]*?<\/p>|<p class="mechanism">[\s\S]*?<\/p>/g) || [];
        const leak = fixed.find((p) => says(p, h.e.annotation.answer));
        assert(!leak, `${h.id} ${entryId(h.e)} (${h.e.annotation.answer}): the ladder's fixed prose says the answer before the walkthrough — ${leak}`);
      }
    }
  }

  // --- the letters rung never prints the whole answer as letters ---
  // For a hidden word, a homophone or a double definition one block legitimately
  // resolves to the entire word, so the building blocks would hand the solve over
  // one rung early. app.js suppresses a `gives` that equals the answer;
  // this drives the real ladder on every clue that has such a block, rather than
  // trusting the annotation to keep choosing safe letters.
  {
    const bare = (s) => (s || "").replace(/[^A-Za-z]/g, "").toUpperCase();
    const risky = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation || {};
        const ans = bare(a.answer);
        // A soundsLike prints unmasked, so one that is the answer leaks the same way.
        if (ans && (a.blocks || []).some((b) => bare(b.gives) === ans || bare(b.soundsLike) === ans)) {
          risky.push({ id, e, ans });
        }
      }
    }
    shape("a block whose letters are the whole answer", risky.length);
    for (const r of risky) {
      openClue(r);
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!CLIMBABLE(btn)) break;
        if (/walkthrough/i.test(btn.textContent)) break;
        // Opened by hand rather than through takeRung(), because the question
        // stands BETWEEN the tap and the rung and takeRung answers it the
        // instant it appears. A sweep that never reads that screen cannot see
        // a leak that only happens on it: the rung's body suppressing a `gives`
        // that is the whole answer while the question in front of it prints
        // the same letters in its prompt ("Which words give APPLAUDED?"). One
        // rule about what a piece may show, two readers of it, both checked.
        btn.onclick();
        if (isAsking(registry["hint-body"])) {
          const asked = registry["hint-body"].innerHTML.match(/<span class="gives">([^<]*)<\/span>/g) || [];
          assert(!asked.some((s) => bare(stripTags(s, "")) === r.ans),
            `${r.id} ${entryId(r.e)} (${r.ans}): the question in front of the rung prints the answer — ${registry["hint-body"].innerHTML}`);
          registry["guess-tell"].onclick();
        }
        const spans = registry["hint-body"].innerHTML.match(/<span class="gives">([^<]*)<\/span>/g) || [];
        const spelled = spans.find((s) => bare(stripTags(s, "")) === r.ans);
        assert(!spelled,
          `${r.id} ${entryId(r.e)} (${r.ans}): the letters rung spells the answer out before the walkthrough`);
      }
    }
  }

  // --- the anagram ring carries the fodder, on the blocks rung, out of order ---
  // The ring is the fodder rearranged, so it is exactly as revealing as the rung
  // it sits on — and only while it sits on the rung that hands the fodder over.
  // It also must never deal the answer itself: a shuffle that happens to land on
  // the solve gives the clue away by luck, a rung before the walkthrough.
  let ringSample = null;  // first clue seen with a drawn ring, reused below to test typing
  {
    const bare = (s) => (s || "").replace(/[^A-Za-z]/g, "").toUpperCase();
    const anas = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation || {};
        const whole = ((a.assembly || {}).anagrams || []).find((x) => bare(x.gives) === bare(a.answer));
        const f = bare(whole && whole.fodder);
        if ((a.type || []).includes("anagram") && f.length >= 4) {
          anas.push({ id, e, f, ans: bare(a.answer) });
        }
      }
    }
    assert(enough(anas.length, 300), "the corpus has anagram fodder to ring: " + anas.length);
    let drawn = 0;
    for (const r of anas) {
      openClue(r);
      let bought = false;
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!CLIMBABLE(btn)) break;
        if (/building blocks/i.test(btn.textContent)) bought = true;
        takeRung(btn);
        const html = registry["hint-body"].innerHTML;
        if (!bought) {
          assert(!html.includes("anagram-ring"),
            `${r.id} ${entryId(r.e)}: the ring is on screen before the building blocks are bought`);
          continue;
        }
        if (!html.includes("anagram-ring")) break;  // no blocks rung on this clue
        if (!ringSample) ringSample = r;
        const tiles = [...html.matchAll(/data-ana="\d+"[^>]*>([A-Z])</g)].map((m) => m[1]);
        assert(tiles.slice().sort().join("") === r.f.split("").sort().join(""),
          `${r.id} ${entryId(r.e)}: the ring holds the fodder (${tiles.join("")} vs ${r.f})`);
        assert(tiles.join("") !== r.ans || new Set(r.f).size < 2,
          `${r.id} ${entryId(r.e)}: the ring dealt the answer itself`);
        drawn++;
        break;
      }
    }
    assert(enough(drawn, 300), "anagram rings drawn across the corpus: " + drawn);
  }

  // --- a multi-word answer breaks the ring where its words end ---
  // The ring reads clockwise from the top as position 1 of the answer onwards,
  // so a pinned letter says WHERE it goes — and in one unbroken circle of
  // thirteen for "KNIGHTS ERRANT" that is a position in a word the solver
  // cannot see the end of. One ring still, because the
  // letters are one jumble; the answer's shape is drawn through them as gaps.
  // Taken only when the words account for exactly the letters on the ring.
  {
    const multi = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation || {};
        const bareFod = (s) => String(s || "").toUpperCase().replace(/[^A-Z]/g, "");
        const whole = ((a.assembly || {}).anagrams || []).find((x) => bareFod(x.gives) === bareFod(a.answer));
        const fod = bareFod(whole && whole.fodder);
        const words = String(a.answer || "").toUpperCase().split(/[^A-Z]+/).filter(Boolean);
        if (fod.length >= 4 && words.length > 1
            && words.join("").length === fod.length) multi.push({ id, e, words });
      }
    }
    assert(enough(multi.length, 50), "the corpus has multi-word anagram answers: " + multi.length);
    let split = 0;
    for (const m of multi.slice(0, 40)) {
      openClue(m);
      let html = "";
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!CLIMBABLE(btn)) break;
        takeRung(btn);
        html = registry["hint-body"].innerHTML;
        if (html.includes("anagram-ring")) break;
      }
      if (!html.includes("anagram-ring")) continue;   // no blocks rung on this clue
      // One ring, whatever the answer's shape.
      const discs = (html.match(/class="ana-disc[ "]/g) || []).length;
      assert(discs === 1,
        `${m.id} ${entryId(m.e)}: ${m.words.join(" ")} drew ${discs} rings, not 1`);
      // Every letter is still on it, and each one knows which word it belongs
      // to — that mapping is what puts the gaps in the right places.
      const tiles = (html.match(/data-ana="\d+"/g) || []).length;
      assert(tiles === m.words.join("").length,
        `${m.id} ${entryId(m.e)}: ${tiles} tiles on the ring, answer has ${m.words.join("").length}`);
      m.words.forEach((w, i) => {
        const inWord = (html.match(new RegExp(`data-word="${i}"`, "g")) || []).length;
        assert(inWord === w.length,
          `${m.id} ${entryId(m.e)}: ${inWord} tiles before break ${i}, ${w} is ${w.length}`);
      });
      // Every word is broken from its neighbour, INCLUDING the last from the
      // first. A circle has no end, so a gap only between words leaves the last
      // word running straight into the first and the shape unreadable at
      // exactly the place it wraps. Measured off the tiles' own coordinates
      // rather than recomputing the layout formula here: the step between two
      // letters inside a word is one pitch, and across a break it is two.
      const pos = [...html.matchAll(
        /left:calc\(50% \+ (-?\d+)px\);\s*\n?\s*top:calc\(50% \+ (-?\d+)px\)/g)]
        .map((p2) => Math.atan2(Number(p2[2]), Number(p2[1])));
      assert(pos.length === tiles,
        `${m.id} ${entryId(m.e)}: read ${pos.length} tile positions off ${tiles} tiles`);
      const TAU = 2 * Math.PI;
      const steps = pos.map((a, i) => ((pos[(i + 1) % pos.length] - a) % TAU + TAU) % TAU);
      const unit = Math.min(...steps);
      // A tile's index in DOM order is its index in ring order, so the step
      // AFTER the last letter of word i is the break that follows it.
      let at = -1;
      m.words.forEach((w, i) => {
        at += w.length;
        assert(steps[at] > unit * 1.5,
          `${m.id} ${entryId(m.e)}: no gap after ${w}` +
          (i === m.words.length - 1 ? " — the ring wraps straight into the first word" : ""));
      });
      assert(steps.filter((x) => x > unit * 1.5).length === m.words.length,
        `${m.id} ${entryId(m.e)}: ${steps.filter((x) => x > unit * 1.5).length} gaps for ` +
        `${m.words.length} words — a gap sits somewhere that is not a word end`);
      split++;
    }
    // A 50-puzzle sample can hold only a handful: the floor is enough()'s, as above.
    assert(enough(split, 5), "broken rings actually drawn: " + split);
  }

  // --- typing edits the ring: a letter adds a tile, Backspace removes the
  // last one, anything else does nothing ---
  //
  // The ring is dealt by dealRing() and re-shuffled by the ana-shuffle button,
  // and also supports adding and deleting letters by typing, which app.js
  // implements as addRingLetter()/removeLastRingLetter() editing
  // `ring.letters`/`ring.order` directly, wired to #ana-kbd's keydown handler.
  // That is pure state and is exactly what this block checks. The FLIP
  // animation wired alongside it (playRingFlip in app.js) is not checkable
  // here: fake_dom's getBoundingClientRect() reports zero width and left for
  // every element (no real layout runs under Node), so every measured delta is
  // zero and a test asserting "the transform passed through a nonzero value" would be
  // asserting about the stub, not the app — it is exercised manually instead.
  {
    assert(ringSample, "an anagram ring sample was captured to test typing against");
    openClue(ringSample);
    for (let i = 0; i < 8; i++) {
      const btn = registry["hint-next"].children[0];
      if (!CLIMBABLE(btn)) break;
      takeRung(btn);
      if (registry["hint-body"].innerHTML.includes("anagram-ring")) break;
    }
    const tilesOf = () =>
      [...registry["hint-body"].innerHTML.matchAll(/data-ana="\d+"[^>]*>([A-Z])</g)].map((m) => m[1]);
    const before = tilesOf();
    assert(before.length >= 4, "ring sample has tiles before any typing: " + before.join(""));

    // Not checked here: a struck tile keeping its POSITION across a shuffle.
    // The tiles and the Shuffle button are written as
    // markup, and fake_dom stores innerHTML as a string without parsing it, so
    // neither #ana-shuffle nor any button.ana-tile is ever a node this harness
    // can click — the handlers in app.js that own that behaviour are not
    // reachable from here at all. Same reason the FLIP animation above is
    // exercised by hand. Typing is testable precisely because #ana-kbd is a
    // real element in index.html.

    const kd = registry["ana-kbd"].listeners.keydown[0];
    assert(kd, "#ana-kbd keydown handler wired");
    const keyEv = (k) => ({ key: k, preventDefault() {} });

    kd(keyEv("z"));
    const afterAdd = tilesOf();
    assert(afterAdd.length === before.length + 1,
      `a letter key appends a tile (${before.length} -> ${afterAdd.length}): ${afterAdd.join("")}`);
    assert(afterAdd[afterAdd.length - 1] === "Z",
      "the typed letter is drawn as the new tile: " + afterAdd.join(""));

    kd(keyEv("5"));
    assert(tilesOf().length === afterAdd.length,
      "a digit key does nothing to the ring: " + tilesOf().join(""));

    kd(keyEv("Backspace"));
    const afterBackspace = tilesOf();
    assert(afterBackspace.length === before.length,
      `Backspace removes the last tile (${afterAdd.length} -> ${afterBackspace.length}): ${afterBackspace.join("")}`);
    assert(afterBackspace.slice().sort().join("") === before.slice().sort().join(""),
      "Backspace removed exactly the typed letter, leaving the original fodder: " + afterBackspace.join(""));

    // Backspace past empty must not throw or go negative.
    for (let i = 0; i < before.length + 2; i++) kd(keyEv("Backspace"));
    assert(tilesOf().length === 0, "Backspace never takes the ring below zero tiles: " + tilesOf().join(""));
  }

  // --- a rung's name may ask its question, never answer it ---
  // The names of the rungs you have NOT bought are on screen the whole time —
  // that is how you choose one. So a name that varies with the clue type is a
  // free hint: an &lit definition rung called "How can the whole clue be
  // the definition?" gives a semi-&lit hidden word away unbought. Same
  // for "Where does the clue split?", "What is the clue really describing?",
  // "What each half means", and the singular/plural indicator label, which
  // hands over how many indicators there are.
  //
  // Checked as an invariant rather than as five strings: across every
  // annotated clue in the corpus, a rung key has exactly ONE name. Any future
  // branch that phrases a label for its type fails here whatever it says.
  {
    // Read off the buttons themselves rather than off any internal list: what
    // is being checked is precisely what a solver can see without paying.
    const names = new Map();   // label -> first clue that showed it
    const seenTypes = new Set();

    // Riding along on the same sweep: once every rung is bought, every fragment
    // the annotation named must be VISIBLY marked in the clue, on whole words.
    // A substring match (indexOf) finds 'in' inside "Conclud(in)g", "island",
    // "confusion", and a mark at the wrong position can land under the
    // definition and be dropped as an overlap, so buying the definition takes
    // an earlier hint off the screen.
    //
    // Checked off the rendered HTML, because that is the thing the solver looks
    // at, and over the whole corpus, because such failures are spread thin: a
    // couple of clues a puzzle, always the small function words a validator
    // would never think to doubt.
    const unesc = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
    // The clue as (text, class) runs, adjacent runs of one class joined, with
    // the setter's italics dropped — they cut the string for their own reasons
    // and a mark split by one is still a mark.
    const runs = (html) => {
      const out = [];
      // The line starts with the entry's own tag ("12A"), which is not clue text.
      html = html.replace(/^\s*<span class="entry-tag">[\s\S]*?<\/span>/, "");
      // The solved tick sits with the tag, not with the words: it is a mark
      // ABOUT the clue, so it is stripped for the same reason the tag is.
      html = html.replace(/^\s*<span class="clue-done[^"]*"[^>]*>[\s\S]*?<\/span>/, "");
      // A mark in the picker clue also says whether it is an end of its run
      // (data-edge — see markUp), which is about how it PAINTS and says nothing
      // about which part of the clue it is. Read the class and skip the rest.
      // The class is a LIST: a word that is its own indicator carries both
      // highlights, class="def ind". Read as one token it matches no mark at
      // all, and the word comes back unclassed.
      const re = /<mark class="([a-z0-9 ]+)"[^>]*>([\s\S]*?)<\/mark>|<[^>]*>|([^<]+)/g;
      let m;
      while ((m = re.exec(html)) !== null) {
        if (m[1] === undefined && m[3] === undefined) continue;      // any other tag
        const cls = m[1] === undefined ? "" : m[1];
        const text = unesc((m[1] === undefined ? m[3] : m[2]).replace(/<\/?i>/g, ""));
        if (out.length && out[out.length - 1].cls === cls) out[out.length - 1].text += text;
        else out.push({ cls, text });
      }
      return out;
    };
    // A multi-class mark read as unclassed makes every assertion below report a
    // missing highlight, which reads as an app bug and is not one. Proven here,
    // once, so that the clue-by-clue failures can be believed.
    assert(JSON.stringify(runs('<mark class="def ind" data-edge="start end">x</mark>'))
           === '[{"cls":"def ind","text":"x"}]',
      "runs() must read a mark that wears more than one class, got "
      + JSON.stringify(runs('<mark class="def ind" data-edge="start end">x</mark>')));
    const checkMarks = (id, e) => {
      const ann = e.annotation;
      // A reconstructed clue's label follows the clue (4c693d5357); it is not
      // clue text, so it is checked and then left out of the runs.
      const label = /\s*<span class="clue-reconstructed"[^>]*>[^<]*<\/span>/;
      const html = registry["hint-clue"].innerHTML;
      assert(label.test(html) === !!e.clue.reconstructed,
        `${id} ${entryId(e)}: the reconstructed label ${e.clue.reconstructed ? "is missing" : "shows on a printed clue"}`);
      const rs = runs(html.replace(label, ""));
      const plain = rs.map((r) => r.text).join("");
      assert(plain === printedClue(e),
        `${id} ${entryId(e)}: the marked-up clue is no longer the clue: ${JSON.stringify(plain)}`);
      let at = 0;
      const spans = rs.map((r) => { const i = at; at += r.text.length; return { ...r, i }; });
      const isLetter = (c) => !!c && /[A-Za-z]/.test(c);
      const whole = (i, len) =>
        !(isLetter(clueText(e)[i]) && isLetter(clueText(e)[i - 1])) &&
        !(isLetter(clueText(e)[i + len - 1]) && isLetter(clueText(e)[i + len]));
      // Every character of a mark's span, in clue coordinates.
      const covered = {};
      for (const s of spans) {
        if (!s.cls) continue;
        // A piece can wear more than one class — see clueMarks on a word that
        // is its own indicator — so each class covers it, not the pair.
        for (const cls of s.cls.split(/\s+/).filter(Boolean))
          for (let k = 0; k < s.text.length; k++) (covered[cls] = covered[cls] || new Set()).add(s.i + k);
      }
      const anyMarked = new Set([].concat(...Object.values(covered).map((v) => [...v])));
      for (const { text: frag } of ann.indicators || []) {
        if (!clueText(e).includes(frag)) continue;
        // An indicator is short and specific, so shortest-first guarantees it
        // wins any overlap outright: it must appear whole, in its own colour,
        // on a whole word — unless the clue never has it as one, as in a
        // run-together hashtag clue, where the part-word is all there is.
        const hits = [];
        for (let i = clueText(e).indexOf(frag); i >= 0; i = clueText(e).indexOf(frag, i + 1)) hits.push(i);
        const anyWhole = hits.some((i) => whole(i, frag.length));
        let ok = false;
        for (const i of hits) {
          if (ok) break;
          if (anyWhole && !whole(i, frag.length)) continue;
          ok = [...Array(frag.length).keys()].every((k) => (covered.ind || new Set()).has(i + k));
        }
        assert(ok,
          `${id} ${entryId(e)}: ${JSON.stringify(frag)} was bought as an indicator but is not ` +
          `marked on a whole word of the clue — a hint that has been paid for cannot ` +
          `leave the screen: ` + registry["hint-clue"].innerHTML);
      }
      // The definition may legitimately be interrupted — an &lit's indicator sits
      // inside it — so what is required of it is that none of it goes unmarked.
      const d0 = (ann.definitions || [])[0];
      const def = d0 && d0.text;
      const defAt = d0 ? cpToIdx(clueText(e), d0.at) : -1;
      assert(!d0 || clueText(e).slice(defAt, defAt + def.length) === def,
        `${id} ${entryId(e)}: the definition's \`at\` does not point at its text: ${JSON.stringify(d0)}`);
      if (def && clueText(e).slice(defAt, defAt + def.length) === def) {
        const at = defAt;
        const gap = [...Array(def.length).keys()].filter((k) => !anyMarked.has(at + k));
        assert(!gap.length || spans.some((s) => s.cls.split(/\s+/).includes("def")),
          `${id} ${entryId(e)}: the definition is not marked at all: ` + registry["hint-clue"].innerHTML);
      }
      // A definition whose words occur twice in the clue ("Sam, Tim, Rich and
      // Ali each cutting last cutting", definition "cutting", indicator "each
      // cutting last") is marked on the occurrence its `at` names, not on
      // another match.
      const defHits = [];
      for (let i = def ? clueText(e).indexOf(def) : -1; i >= 0; i = clueText(e).indexOf(def, i + 1)) defHits.push(i);
      if (defHits.length > 1 && defHits.includes(defAt)) {
        repeatedDefs.push(`${id} ${entryId(e)}`);
        // An indicator inside the definition takes its own words (see
        // clueMarks), so the rule is: all of it marked, some of it as def.
        const keys = [...Array(def.length).keys()];
        assert(keys.every((k) => anyMarked.has(defAt + k)) &&
               keys.some((k) => (covered.def || new Set()).has(defAt + k)),
          `${id} ${entryId(e)}: the definition ${JSON.stringify(def)} occurs ${defHits.length} times and ` +
          `is not marked at its \`at\` (${d0.at}): ` + registry["hint-clue"].innerHTML);
      }
    };
    const repeatedDefs = [];
    const openPuzzle = (id) => reopenForSweep(id);
    for (const id of Object.keys(puzzles).sort()) {
      const withAnn = (puzzles[id].entries || []).filter((e) => e.annotation);
      if (!withAnn.length) continue;
      openPuzzle(id);
      for (const e of withAnn) {
        const row = registry["clue-" + entryId(e)];
        if (!row || !row.listeners.click) continue;
        seenTypes.add(String(e.annotation.type));
        row.listeners.click[0]();
        // The ladder numbers its rungs in LADDER's order, on every clue in the
        // corpus. Checked by the NUMBER on each button rather than by the
        // button's position, because the row lists the rungs you can take
        // before the ones you can't; and checked as a subsequence rather than
        // as 1..5, because the ladder is built per clue — lots of clues have no
        // indicators rung and no blocks rung — and the row drops a rung once it
        // has been taken, so its number goes with it and the rest keep theirs.
        {
          const numbered = registry["hint-next"].children
            .map((b) => /^(\d+) · ([^·]*?)(?: · free)?$/.exec(b.textContent || ""))
            .filter(Boolean)
            .map((m) => ({ n: +m[1], label: m[2].trim() }))
            .sort((a, b) => a.n - b.n);
          const where = `${id} ${entryId(e)} (${e.annotation.type})`;
          const shownAs = () => numbered.map((r) => `${r.n} ${r.label}`).join(" | ");
          assert(numbered.every((r) => r.n >= 1 && r.n <= LADDER.length)
            && new Set(numbered.map((r) => r.n)).size === numbered.length,
            `${where}: every rung wears its own number in 1..${LADDER.length}: ` + shownAs());
          // Climbing by number and climbing by app.js's order are the same walk.
          let at = -1;
          const inOrder = numbered.every((r) => {
            at = LADDER.findIndex((x, j) => j > at && x.label === r.label);
            return at >= 0;
          });
          assert(inOrder,
            `${where}: the rungs are numbered in app.js's own ladder order (`
            + LADDER.map((r) => r.label).join(" → ") + "), but this clue offers "
            + shownAs());
        }
        for (let i = 0; i < 9; i++) {
          const btns = registry["hint-next"].children.filter((b) => b.onclick);
          if (!btns.length) break;
          for (const b of btns) {
            // "· free" is the price, not the name: every rung of a clue its
            // crossers already solved is free.
            const m = /^\d+ · (.*?)(?: · free)?$/.exec(b.textContent || "");
            if (m && !names.has(m[1])) names.set(m[1], `${id} ${entryId(e)} (${e.annotation.type})`);
          }
          takeRung(btns[0]);
        }
        checkMarks(id, e);
      }
    }
    assert(seenTypes.size > 20, "the sweep saw the corpus's variety of types: " + seenTypes.size);
    shape("a clue whose definition's words occur twice in it", repeatedDefs.length);
    // Five rungs exist, so five names exist. A sixth means a branch phrased a
    // label for its clue type, whatever the wording turned out to be.
    const LABEL_SET = LADDER.map((r) => r.label);
    const extra = [...names].filter(([n]) => !LABEL_SET.includes(n));
    assert(!extra.length,
      "a rung is named differently depending on the clue, so its button leaks the " +
      "type before it is bought: " +
      extra.map(([n, where]) => `${JSON.stringify(n)} — ${where}`).join("; "));
  }

  // --- the indicator rung says why THAT word indicates ---
  // Without it the rung names the words and then gives the sentence it gives
  // every anagram in the corpus. An indicator's `note` is the part that is
  // only true of this clue, so it has to be on the screen the moment it
  // exists in the file; a field that is written and never rendered is worse than
  // no field, because the backlog says the work is done.
  {
    const noted = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation || {};
        const n = (a.indicators || []).filter((i) => i.note);
        if (n.length) noted.push({ id, e, n });
      }
    }
    assert(noted.length, "some clue in the corpus explains its indicators");
    for (const s of noted.slice(0, 25)) {
      openClue(s);
      const btn = registry["hint-next"].children.find(
        (b) => b.onclick && /indicator/i.test(b.textContent) && !b.disabled);
      assert(btn, `${s.id} ${entryId(s.e)}: the indicators rung is offered`);
      if (!btn) continue;
      takeRung(btn);
      const html = registry["hint-body"].innerHTML;
      for (const { text: ind, note } of s.n) {
        assert(html.includes(note.replace(/&/g, "&amp;").replace(/'/g, "&#39;")),
          `${s.id} ${entryId(s.e)}: the note for ${JSON.stringify(ind)} never reaches the ` +
          `indicators rung: ` + html);
      }
      // And when every indicator is explained, the explanations are the whole
      // rung. Structural rather than a list of banned phrases, so a new piece of
      // generic wording cannot slip past by not being on the list — the
      // explanation has to be specific to this clue's context, never just text
      // filling space. Anything the clue type alone could have written is
      // filler beside a sentence about this clue. The one exception is the
      // rule chip (DEVICE_RULES), which is general on purpose: it is what the
      // solver takes to the next clue. It adds no text until tapped, and a tap
      // on it opens the rule with its lesson link.
      const inds = (s.e.annotation.indicators || []);
      if (inds.length && inds.every((i) => i.note)) {
        const rungOf = (h) => (h.split('<div class="hint-step">')
          .find((sec) => sec.includes("Spot the indicator words")) || "")
          .replace(/<\/div>[\s\S]*$/, "");
        const rulesIn = (h) => h.match(/<span class="device-rule">[\s\S]*?<\/span>/g) || [];
        const rung = rungOf(html);
        const chip = /<button type="button" class="rule-chip" data-rule="indicators"/.test(rung);
        assert(!inds.some((i) => i.for) || chip,
          `${s.id} ${entryId(s.e)}: the indicators rung ends on a chip for its device's rule: ` + rung);
        assert(!rulesIn(rung).length,
          `${s.id} ${entryId(s.e)}: the rule stays closed until its chip is tapped: ` + rung);
        if (chip) {
          const tap = () => registry["hint-body"].listeners.click[0]({ target: { dataset: { rule: "indicators" } } });
          tap();
          const rules = rulesIn(rungOf(registry["hint-body"].innerHTML));
          assert(rules.length,
            `${s.id} ${entryId(s.e)}: tapping the chip opens the rule for its device: ` + rung);
          assert(rules.every((r) => /href="[^"]*learn\/#[a-z-]+"/.test(r) && !/href="[^"]*puzzles\/[^"]*learn\//.test(r)),
            `${s.id} ${entryId(s.e)}: each rule links to its lesson section: ` + rules);
          tap();
          assert(!rulesIn(rungOf(registry["hint-body"].innerHTML)).length,
            `${s.id} ${entryId(s.e)}: a second tap closes the rule again`);
        }
        const rest = rung
          .replace(/<span class="step-label">[^<]*<\/span>/, "")
          .replace(/<ul class="ind-notes">[\s\S]*?<\/ul>/, "").trim();
        assert(!rest, `${s.id} ${entryId(s.e)}: every indicator has a note, so the rung ` +
          `should be those notes and nothing else — also found: ` + rest);
      }
    }
  }

  // --- a homophone must show you the word you say aloud ---
  // A blocks rung that reads “Cockney mob” → OARED and stops leaves HORDE, the
  // dropped aitch and the sound itself off-screen. The sounded form is a
  // tracked field rather than a sentence somebody might remember to write, so
  // drive every sound clue there is and check it reaches the page.
  {
    // Whether a sound clue must carry a soundsLike at all (a plain spoonerism need
    // not) is the validator's rule, validate_annotations.check_sound_names_its_source,
    // and it gates the push; this only checks that the ones that do carry one show it.
    const sound = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const t = (e.annotation || {}).type || [];
        // A clue flagged for redo (ann.redo) has its blocks rung and step-by-step
        // withheld on purpose (app.js, "Being rewritten"), so there is no rung to check.
        if ((t.includes("homophone") || t.includes("spoonerism")) && !e.annotation.redo
            && (e.annotation.blocks || []).some((b) => b.soundsLike)) sound.push({ id, e });
      }
    }
    assert(enough(sound.length, 20), "the corpus still has sound clues to check: " + sound.length);
    for (const s of sound) {
      const heard = (s.e.annotation.blocks || []).filter((b) => b.soundsLike);
      openClue(s);
      // Climb until the blocks rung has been bought.
      let html = "";
      // Escaped the way app.js escapes it: "I'D A" reaches the page as I&#39;D A.
      // What the blocks rung emits for a sounded block, character for character —
      // see the `b.soundsLike` line in app.js. Matching the markup and not the
      // words is the point: the bare phrase "said aloud" is also ordinary English
      // an indicator note may use ("the words before this are to be said aloud"),
      // so stopping on it breaks out of the ladder one rung early and fails a
      // blocks rung that was never bought.
      const sounded = (b) => `<span class="gives">${htmlEsc(b.soundsLike)}</span>`
        + ` <span class="muted">said aloud</span>`;
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!CLIMBABLE(btn)) break;
        takeRung(btn);
        html = registry["hint-body"].innerHTML;
        if (heard.every((b) => html.includes(sounded(b)))) break;
      }
      for (const b of heard) {
        assert(html.includes(sounded(b)),
          `${s.id} ${entryId(s.e)}: the blocks rung never shows ${b.soundsLike}, ` +
          `which is the whole mechanism — ` + html);
      }
    }
  }

  // --- "Next piece" is never a click that only hands a piece over ---
  // A piece with no fragment to point at, or no letters to ask for, has no
  // question in it: clicking for it gives it to you the instant the click lands.
  // Pacing the rung is meant to make it ask before it tells, so a step that can
  // only tell is a tap charged for nothing — clicking "Next piece" on building
  // blocks should not simply hand the blocks over for free. Those pieces
  // ride out with the piece before them, which is
  // invisible in the count and visible only here: drive every clue that has one
  // and check that every "Next piece" still offered opens a question.
  {
    const quiet = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const blocks = (e.annotation || {}).blocks || [];
        if (blocks.length > 1 && blocks.some((b) => !(b.clueFragment && b.gives))) {
          quiet.push({ id, e });
        }
      }
    }
    assert(quiet.length > 5, "the corpus still has question-less pieces to pace: " + quiet.length);
    for (const s of quiet.slice(0, 60)) {
      openClue(s);
      for (let i = 0; i < 10; i++) {
        const btn = registry["hint-next"].children[0];
        if (!CLIMBABLE(btn)) break;
        const label = btn.textContent;
        btn.onclick();
        const asking = isAsking(registry["hint-body"]);
        assert(asking || !/^Next building block · /.test(label),
          `${s.id} ${entryId(s.e)}: "${label}" handed a piece over without asking anything`);
        if (asking) registry["guess-tell"].onclick();
      }
    }
  }

  // --- a rung highlights its own words, on its own ---
  // Clue markup gated on the definition rung would make the legitimate route
  // (indicators first, work the definition out yourself) spend a hint and
  // light nothing, since tier 0 allows any order. Drive exactly that route, and
  // check both directions: what was asked for is marked, what wasn't is not.
  const withInd = (() => {
    for (const id of Object.keys(puzzles).sort().reverse()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation;
        // the indicator has to literally occur in the clue or there is nothing
        // to mark
        if (a && (a.indicators || []).some((s) => clueText(e).includes(s.text))) return { id, e };
      }
    }
    return null;
  })();
  assert(withInd, "at least one annotation names an indicator that occurs in its clue");
  openFromPicker(withInd.id);
  registry["clue-" + entryId(withInd.e)].listeners.click[0]();
  const indBtn = registry["hint-next"].children.find((b) => /indicator/i.test(b.textContent) && !b.disabled);
  assert(indBtn, "the indicators rung is offered from cold: " + registry["hint-next"].innerHTML);
  takeRung(indBtn);
  const marked = registry["hint-clue"].innerHTML;
  assert(marked.includes('mark class="ind"'),
    "the indicators rung highlighted nothing in the clue: " + marked);
  assert(!marked.includes('mark class="def"') && !marked.includes('mark class="link"'),
    "the indicators rung leaked definition markup: " + marked);
  const legend = (registry["hint-body"].innerHTML.match(/<div class="legend">[\s\S]*?<\/div>/) || [""])[0];
  assert(legend.includes('mark class="ind"') && !legend.includes('mark class="def"'),
    "the legend must name exactly the marks that were drawn: " + legend);

  // --- the walkthrough joins the definition to the answer ---
  // The blocks spell the answer out of the wordplay; the walkthrough also says
  // why the definition's words MEAN it. This tests the render path only — the
  // sentence is written by the annotator and policed by
  // check_definition_fit in tools/validate_annotations.py, so the field is
  // synthesised here rather than waiting on a puzzle that happens to carry one.
  {
    const e = withInd.e;
    e.annotation.explanation.definitionFit = "SMOKE-FIT: the answer is an instance of the definition.";
    registry["clue-" + entryId(e)].listeners.click[0]();
    let guard = 0;
    while (registry["hint-next"].children[0] && registry["hint-next"].children[0].onclick && guard++ < 8) {
      takeRung(registry["hint-next"].children[0]);
      if (answerShown(registry["hint-body"].innerHTML)) break;
    }
    const walk = registry["hint-body"].innerHTML;
    assert(walk.includes("SMOKE-FIT"),
      "the walkthrough never explains why the answer matches the definition: " + walk.slice(-400));
    const fitLine = (walk.match(/<p class="def-fit">[\s\S]*?<\/p>/) || [""])[0];
    // letters only: esc() turns an apostrophe in FERMAT'S LAST THEOREM into an
    // entity, so a raw substring match would flake on the puzzle, not the code
    const bare = (s) => s.replace(/[^A-Za-z]/g, "");
    assert(fitLine.includes('mark class="def"') && bare(fitLine).includes(bare(e.annotation.answer)),
      "the fit line must name both ends it is joining: " + fitLine);
    // The fit line is the last thing the walkthrough says and names the answer,
    // so the answer is printed once, not again under it (02ee84cec57).
    assert(!walk.includes("Answer:") && answerShown(walk, bare(e.annotation.answer).toUpperCase()),
      "with a fit line the answer is named there and printed once: " + walk.slice(-400));
    delete e.annotation.explanation.definitionFit;
  }
}

// --- the lesson is a page, not a panel ---
// It is a document you read end to end, too long for a collapsible section.
// So the header carries a link and the app carries no copy of the lesson at all.
{
  const home = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  assert(/<a class="ghost" href="https:\/\/cryptic\.paultarjan\.com\/learn\/" aria-label="How cryptic clues work"[^>]*>/.test(home),
    "the header links to the lesson at /learn/, and the aria-label carries its full name behind the one-word button");
  assert(!home.includes('id="tutorial"') && !home.includes("tutorial.js"),
    "index.html carries no in-page copy of the lesson");
}
