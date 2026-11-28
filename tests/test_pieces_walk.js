/* Walking genius-273 13A ("At that point, crux of lemma leads to proposition",
   THEOREM) through its questions: Indicator, Definition, Clue type, and then
   the pieces step asking "Which words give ...".

     node tests/test_pieces_walk.js

   Also the wrong-pick behaviour: a wrong lock-in keeps the picked words
   selected, so one word can be changed and tried again, and the "Not quite"
   line stays over the question, naming only what the help button offers as
   the picks change. */
"use strict";
const { boot } = require("../tools/fake_dom.js");

const ID = "genius-273";

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

const d = boot({ query: "?p=" + ID, storage: { "ct:nux": "9" } });
const reg = d.registry;
const puz = global.window.CRYPTIC_PUZZLES[ID];
const entry = puz.entries.find((e) => e.number === 13 && e.direction === "across");
const words = entry.clue.text.split(/\s+/);
const at = (w) => words.findIndex((x) => x.replace(/[^A-Za-z]/g, "").toLowerCase() === w);

const body = () => reg["hint-body"].innerHTML;
const page = () => body() + reg["hint-clue"].innerHTML;
const asking = () => body().includes('class="hint-step guess"');
const prompt = () => {
  const m = /class="hint-step guess"[\s\S]*?<p>([\s\S]*?)<\/p>/.exec(body());
  return m ? m[1] : "";
};
const lit = (i) => new RegExp('id="gw-' + i + '" class="gw on[ "]').test(page());
const lock = () => reg["guess-tell"].onclick();
const tap = (i) => reg["gw-" + i].onclick();

check(!!entry, "13A is in genius-273");
reg["clue-13-across"].listeners.click[0]();

const crux = at("crux"), of = at("of"), def = at("proposition"), wrong = at("lemma");
let defTested = false;

for (let guard = 0; guard < 8 && asking() && !/Which words give/.test(prompt()); guard++) {
  const p = prompt();
  if (/Which kind of clue/.test(p)) {
    const m = /id="gc-(\d+)" class="gc[^"]*">charade</i.exec(body());
    check(!!m, "the Clue type question offers charade");
    if (!m) break;
    reg["gc-" + m[1]].onclick();
  } else if (/Which words define/.test(p)) {
    if (!defTested) {
      defTested = true;
      tap(wrong);
      lock();
      check(asking() && /Which words define/.test(prompt()), "a wrong Definition pick keeps the same question up");
      check(lit(wrong), "a wrong Definition pick keeps the picked words selected");
      check(/Not quite/.test(body()), "the wrong pick says Not quite");
      check(/step-miss[^>]*>Not quite[^<]*change your picks/.test(body()), "with the picks kept, Not quite says to change them");
      tap(wrong);
      check(/step-miss[^>]*>Not quite[^<]*try again, or tap/.test(body()), "with the pick taken off, Not quite stays and says to tap Just tell me");
      tap(def);
      check(/step-miss[^>]*>Not quite[^<]*change your picks/.test(body()), "with a new pick, Not quite again says to change the picks");
      check(/\bon\b/.test(reg["gw-" + def].className) && !/\bon\b/.test(reg["gw-" + wrong].className), "the changed pick is the one now selected");
      lock();
    } else {
      tap(def);
      lock();
    }
  } else if (/tell you what to do/.test(p)) {
    tap(crux);
    tap(of);
    lock();
  } else {
    check(false, "unexpected question: " + p);
    break;
  }
}

check(defTested, "the Definition question was asked");
check(asking(), "a question is up after Indicator, Definition and Clue type");
check(body().includes('class="hint-step guess"'), "hint-body holds the question step");
check(body().includes("Which words give"), "the pieces question asks \"Which words give\"");

process.exit(failures ? 1 : 0);
