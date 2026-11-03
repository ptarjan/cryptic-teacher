// The type rung and clues with two right answers.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { CLUE_TYPES, ROOT, TYPE_FAMILY, assert, clueText, entryId, fs, path, pickerRowFor, registry,
  shape } = T;
// --- the type rung asks too, and its answer is a family ---
// Every other part of a clue is something you can be asked to point at. This one
// is a choice among the seven the site teaches — and a ladder that asks about
// every part except the first is a ladder that answers its own first question.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      if (e.annotation && (e.annotation.type || []).length) { found = { id, e }; break; }
    }
    if (found) break;
  }
  assert(found, "some clue is annotated with a type");

  // Back to cold every time: reset clears the score, so what a wrong answer and
  // a right one each cost can be read off the same starting point.
  const open = (soft) => {
    registry["btn-picker"].onclick();
    const li = pickerRowFor(found.id);
    assert(li, "picker finds the puzzle to be asked about");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + entryId(found.e)].listeners.click[0]();
    const btn = registry["hint-next"].children.find((b) => /kind of clue/i.test(b.textContent || ""));
    if (!btn && soft) return null;  // a clue the app gives no type rung (a bare-letters rebus) is not the one to test
    assert(btn, `${found.id} ${entryId(found.e)} (type ${JSON.stringify(found.e.annotation.type)}, redo ${!!found.e.annotation.redo}): the type rung is offered: ` + registry["hint-next"].innerHTML);
    cold = registry["hint-body"].innerHTML;
    const before = registry["scorebar"].innerHTML;
    btn.onclick();
    return before;
  };
  // What a clue with nothing opened on it says, captured before anything is.
  let cold = null;
  // The buttons are written as markup, so they are read as markup: index to
  // label, escaped exactly as the page escaped it.
  const choices = () => {
    const out = new Map();
    const re = /id="gc-(\d+)" class="gc">([^<]+)</g;
    let m;
    while ((m = re.exec(registry["hint-body"].innerHTML))) out.set(m[2], m[1]);
    return out;
  };

  open();
  let html = registry["hint-body"].innerHTML;
  assert(html.includes("guess-choices"), "the type rung asks before it tells: " + html);
  // The strip is a grid of equal columns, not a row the type has to be shrunk
  // to fit. An odd number of chips would leave the last one alone in column
  // one, which is what happens with an odd-count family like "&lit", so the
  // last-of-an-odd-count rule that spans it is load-bearing and is checked
  // here rather than left to the eye.
  {
    const bare = fs.readFileSync(path.join(ROOT, "style.css"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "");
    assert(/\.guess-choices\s*\{[^}]*grid-template-columns:\s*1fr 1fr/.test(bare),
      "the family strip is two equal columns, not one squeezed row");
    assert(/\.guess-choices \.gc:last-child:nth-child\(odd\)\s*\{[^}]*grid-column:\s*1 \/ -1/.test(bare),
      "and an odd last chip spans both columns instead of orphaning");
    assert(!/class="guess-choices"[^>]*style=/.test(html),
      "the strip no longer sizes itself off its own width: " + html);
    assert(choices().size % 2 === 1,
      `the span rule only fires on an odd count and there are ${choices().size} families`);
  }
  assert(!html.includes('id="guess-check"'),
    "and one of nine is a tap, not a tap and then a confirm: " + html);
  assert(choices().size === 7,
    "all seven picker families are offered every time, never narrowed to the plausible "
      + "ones — the list is the vocabulary (rebus and reverse clue are folded into "
      + "their `picker` family, not offered): " + choices().size);

  // What it wanted, learned the expensive way, so the two answers below can be
  // told apart without this test knowing the app's own table of families.
  registry["guess-tell"].onclick();
  const rungOf = (h) => h.slice(h.indexOf("kind of clue is this?"));
  const named = (h) => [...rungOf(h).matchAll(/<p><strong>([^<]+)<\/strong>/g)].map((m) => m[1]);
  const told = named(registry["hint-body"].innerHTML);
  assert(told.length === 1, "the rung names the one family it was after: " + told);
  const right = told[0];
  // What the grader accepts, asked of the grader: a compound clue is right for
  // any family it is made of, and the rung names only the main one.
  const graded = () => {
    open();
    const out = {};
    for (const k of [...choices().keys()]) {
      open();
      registry["gc-" + choices().get(k)].onclick();
      out[k] = registry["hint-body"].innerHTML.includes("guess-verdict right");
    }
    return out;
  };
  const verdicts = graded();

  // Wrong is never a dead end: the rung opens all the same, and is charged for.
  const paid = open();
  const wrong = Object.keys(verdicts).find((k) => !verdicts[k]);
  registry["gc-" + choices().get(wrong)].onclick();
  html = registry["hint-body"].innerHTML;
  assert(html.includes("guess-verdict miss"), "a wrong family is graded: " + html);
  assert(html.includes(">" + right + "<"), "and the rung opens anyway, naming it: " + html);
  assert(registry["scorebar"].innerHTML !== paid,
    "being told costs what it has always cost: " + registry["scorebar"].innerHTML);

  // Right costs nothing. That is the whole reason to have a go.
  // The rung names the real family, which for a rare one (rebus, reverse clue)
  // is not a chip: it is folded into its `picker` family and answered by that
  // chip. So the chip to tap is the one the grader accepts, which is the named
  // family itself whenever that is a chip.
  const free = open();
  const rightChip = choices().has(right) ? right : Object.keys(verdicts).find((k) => verdicts[k]);
  assert(rightChip, "some chip is graded right for the family the rung names (" + right + "): "
    + JSON.stringify(verdicts));
  registry["gc-" + choices().get(rightChip)].onclick();
  html = registry["hint-body"].innerHTML;
  assert(html.includes("guess-verdict right"), "the right family is graded right: " + html);
  // The entrance is spent on the draw that first shows the verdict. The panel is
  // rewritten on every keystroke and every selection, so an animation left on it
  // replays while the solver is doing something else entirely — "the old 'yes
  // that's the one' is animating as I'm picking a new clue".
  assert(html.includes("guess-result fresh"), "the verdict arrives with an entrance: " + html);
  registry["clue-" + entryId(found.e)].listeners.click[0]();
  assert(!/guess-result fresh/.test(registry["hint-body"].innerHTML),
    "and does not replay it on the next draw: " + registry["hint-body"].innerHTML);
  assert(registry["scorebar"].innerHTML === free,
    "and a rung you worked out yourself is free: " + free + " -> " + registry["scorebar"].innerHTML);
  assert(registry["hint-meter"].innerHTML.includes("worked out"),
    "which the meter says, because that is the number this is all for: "
      + registry["hint-meter"].innerHTML);

  // A family too rare for a chip (rebus, reverse clue) is answered by the chip
  // its `picker` names, while the rung still names the real family.
  {
    const fams = CLUE_TYPES.families;
    const total = fams.reduce((a, f) => a + f.n, 0);
    const rare = fams.filter((f) => f.n < 0.005 * total);
    assert(rare.length === 2 && rare.every((f) => f.picker), "two folded families, each with a picker: " + JSON.stringify(rare));
    for (const f of rare) {
      const target = fams.find((g) => g.name === f.picker).label;
      // The first clues purely of the family that the app does offer a type rung on.
      let hit = null, tried = 0;
      for (const id of Object.keys(puzzles).sort()) {
        for (const e of puzzles[id].entries || []) {
          const t = (e.annotation && e.annotation.type) || [];
          if (!(e.annotation && !e.annotation.redo && t.length && TYPE_FAMILY[t[0]] === f.name && t.every((k) => TYPE_FAMILY[k] === f.name))) continue;
          found = { id, e };
          if (++tried > 25) break;
          if (open(true) !== null) { hit = found; break; }
        }
        if (hit || tried > 25) break;
      }
      // A family this rare is in a sixteenth of the corpus at best: a slice or the
      // sample may hold no clue purely of it. shape() skips this family then, and
      // the nightly's check_shapes.js fails if no slice at all found one.
      if (!shape(`a clue purely ${f.name}`, hit)) continue;
      found = hit;
      open();
      assert(!choices().has(f.label), `${f.label} is not a chip`);
      registry["guess-tell"].onclick();
      assert(named(registry["hint-body"].innerHTML)[0] === f.label,
        `the rung still names the real type ${f.label}: ` + named(registry["hint-body"].innerHTML));
      const v = graded();
      assert(v[target] && Object.keys(v).filter((k) => v[k]).length === 1,
        `${f.label} is answered by ${target} only: ` + JSON.stringify(v));
    }
  }

  // A compound clue names one family and grades every one it is made of right.
  // Which clue is compound is read off clue_types.json's families; what the rung
  // names and what the grader accepts are read off the page.
  {
    const hits = (t) => new Set(t.map((k) => TYPE_FAMILY[k])).size;
    found = null;
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        if (e.annotation && hits(e.annotation.type || []) >= 2) { found = { id, e }; break; }
      }
      if (found) break;
    }
    assert(found, "some clue is annotated with a compound type");
    open();
    registry["guess-tell"].onclick();
    const main = named(registry["hint-body"].innerHTML);
    assert(main.length === 1, `the rung on ${found.id} ${entryId(found.e)} (${found.e.annotation.type}) `
      + "names exactly one family: " + main);
    const v = graded();
    const secondary = Object.keys(v).find((k) => v[k] && k !== main[0]);
    assert(secondary, `a family other than ${main[0]} is graded right on `
      + `${found.e.annotation.type}: ` + JSON.stringify(v));
  }

  // An anagram that makes only part of the answer is not told to "add up to the
  // number in brackets": on CHOMPED, MP inside an anagram of COD HE, that line
  // sent a solver looking to shuffle MP in too (9740 27a).
  {
    const letters = (s) => String(s || "").replace(/[^A-Za-z]/g, "").length;
    // Anagram leads the type rung unless a definition or &lit family outranks it.
    const part = (a) => (a.type || []).includes("anagram")
      && !(a.type || []).some((k) => ["definition", "and_lit"].includes(TYPE_FAMILY[k]))
      && (a.assembly || {}).anagrams
      && a.assembly.anagrams.length
      && Math.max(...a.assembly.anagrams.map((x) => letters(x.gives))) < letters(a.answer);
    found = null;
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        if (e.annotation && part(e.annotation)) { found = { id, e }; break; }
      }
      if (found) break;
    }
    assert(found, "some clue's anagram makes only part of its answer");
    open();
    registry["guess-tell"].onclick();
    const rung = rungOf(registry["hint-body"].innerHTML);
    assert(/Anagram/.test(named(registry["hint-body"].innerHTML)[0] || "") && /come up short/.test(rung)
      && !/add up to the number in brackets/.test(rung),
      `${found.id} ${entryId(found.e)}: a partial anagram's type rung says its letters come up short — ` + rung);
  }

  // How the ladder works is said once and then stops. It is a line about the
  // whole ladder, so once a rung has been worked out it has been demonstrated,
  // and a solver who has done it does not need telling again on every clue they
  // open after. The second clue comes from the puzzle still open, the compound
  // clue's, which need not be the first puzzle with a typed clue.
  assert(/asks you a question before it tells you/.test(cold), "a cold clue says what the ladder is: " + cold);
  const other = (puzzles[found.id].entries || []).find(
    (x) => entryId(x) !== entryId(found.e) && x.annotation && (x.annotation.type || []).length);
  assert(other, "the puzzle has a second annotated clue to open cold");
  registry["clue-" + entryId(other)].listeners.click[0]();
  assert(!/asks before it tells/.test(registry["hint-body"].innerHTML),
    "and stops saying it once a rung has been worked out: " + registry["hint-body"].innerHTML);
}

// --- a clue that is two things at once has two right answers ---
// "There was a regularly indicator but I said it was a charade." Both are true
// of a compound type, and grading against one family alone marks the truth
// wrong and teaches that a clue has exactly one mechanism, which is the
// opposite of what the rung is for.
//
// The clue is found by a type naming mechanisms that CANNOT be the same family
// under any sane grouping — a charade is words laid end to end, letters picked
// out of a word are not — so this does not restate the app's own table and
// cannot pass by agreeing with a copy of it.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const t = (e.annotation || {}).type || [];
      if (t.includes("charade") && (t.includes("letter_selection") || t.includes("hidden_word"))) {
        found = { id, e };
        break;
      }
    }
    if (found) break;
  }
  if (shape("a clue that is a charade AND an extraction", found)) {
    const open = () => {
      registry["btn-picker"].onclick();
      const li = pickerRowFor(found.id);
      li.children[0].onclick();
      registry["reset-puzzle"].onclick();
      registry["clue-" + entryId(found.e)].listeners.click[0]();
      registry["hint-next"].children.find((b) => /kind of clue/i.test(b.textContent || "")).onclick();
    };
    const choices = () => {
      const out = new Map();
      const re = /id="gc-(\d+)" class="gc">([^<]+)</g;
      let m;
      while ((m = re.exec(registry["hint-body"].innerHTML))) out.set(m[2], m[1]);
      return out;
    };
    open();
    const labels = [...choices().keys()];   // while the question is still on screen
    registry["guess-tell"].onclick();
    const named = /kind of clue is this\?<\/span><p><strong>([^<]+)</
      .exec(registry["hint-body"].innerHTML);
    assert(named, "the rung names one family as the headline: " + registry["hint-body"].innerHTML);

    let also = 0, free = null;
    for (const label of labels) {
      if (named && label === named[1]) continue;
      const before = (open(), registry["scorebar"].innerHTML);
      registry["gc-" + choices().get(label)].onclick();
      if (!/guess-verdict right/.test(registry["hint-body"].innerHTML)) continue;
      also += 1;
      if (registry["scorebar"].innerHTML === before) free = label;
    }
    assert(also >= 1, "the other family in it is graded right too, not marked wrong: "
      + clueText(found.e) + " — " + found.e.annotation.type);
    // And right is right: a true answer that still costs a rung is a wrong answer
    // wearing a compliment.
    assert(free, "and costs nothing, the same as naming the headline one does");
  }
}
