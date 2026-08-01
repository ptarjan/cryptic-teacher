// Tutorial content for Cryptic Teacher. Injected into #tutorial by app.js.
window.TUTORIAL_HTML = `
<h2>How cryptic clues work</h2>

<p>Nearly every cryptic clue contains the same two things, side by side:</p>
<ul>
  <li>a <mark class="def">definition</mark> — a normal crossword-style definition of the answer,
      always at the <em>start or end</em> of the clue, and</li>
  <li>the <em>wordplay</em> — a recipe for building the answer letter by letter, often
      flagged by <mark class="ind">indicator words</mark>.</li>
</ul>
<p>The clue is written so the two halves read as one misleading sentence (the
<em>surface</em>). Your job is to find the seam between definition and wordplay. When you
solve a clue you get <strong>two independent confirmations</strong> — the definition fits
and the wordplay builds the same word — so you can be certain without checking any answers.</p>

<h3>The main clue types</h3>

<h4>Anagram</h4>
<div class="mini"><span class="clue">Destroying <mark class="ind">climate, sun</mark> <mark class="def">reaches highest point</mark> (10)</span><br>
"Destroying" signals an anagram of CLIMATE SUN (10 letters) → <strong>CULMINATES</strong>.
Anagram indicators suggest disorder: <em>broken, wild, drunk, confused, cooked, at sea…</em>
Count the fodder letters — they must exactly match the enumeration.</div>

<h4>Charade</h4>
<div class="mini"><span class="clue"><mark class="def">Give authority?</mark> Those people might (7)</span><br>
Pieces are simply chained: "those people" = 'EM + "might" = POWER → <strong>EMPOWER</strong>.
No indicator needed — the parts just follow each other.</div>

<h4>Container (insertion)</h4>
<div class="mini"><span class="clue">Stylish attempt <mark class="ind">to cover</mark> butt (6)</span><br>
One part goes inside another: TRY ("attempt") covering END ("butt") → TR(END)Y =
<strong>TRENDY</strong> ("stylish"). Watch for <em>holding, swallowing, wearing, about, in</em>.</div>

<h4>Hidden word</h4>
<div class="mini"><span class="clue"><mark class="def">Unyielding</mark> squad a man triumphantly <mark class="ind">arrests</mark> (7)</span><br>
The answer is sitting in plain sight: squ<strong>AD A MAN T</strong>riumphantly →
<strong>ADAMANT</strong>. Indicators: <em>some, part of, held by, arrests</em>.</div>

<h4>Homophone</h4>
<div class="mini"><span class="clue"><mark class="ind">Reportedly</mark> a cheap fastener for a horse (4)</span><br>
Sounds like another word: "cheap fastener" ≈ MANE/"main"… e.g. <em>we hear, on the radio,
called out</em> all flag sound-alikes. (Answer here: MANE, sounding like "main".)</div>

<h4>Reversal</h4>
<div class="mini"><span class="clue">Apple device <mark class="ind">set up</mark> date <mark class="def">feature on smartphone</mark> (6)</span><br>
MAC reversed ("set up" — this works in Down clues) + ERA ("date") → <strong>CAMERA</strong>.
Indicators: <em>back, returned, over, rising / set up</em> (down clues only).</div>

<h4>Deletion</h4>
<div class="mini"><span class="clue">Sexpot <mark class="ind">stripped</mark> for <mark class="def">show</mark> (4)</span><br>
Remove letters: (s)EXPO(t) "stripped" of its outside → <strong>EXPO</strong>.
Look for <em>headless, endless, gutted, short, almost, without</em>.</div>

<h4>Double definition</h4>
<div class="mini"><span class="clue"><mark class="def">Lousy payment</mark> for <mark class="def">cartoon</mark> (7)</span><br>
Two definitions of the same word, no wordplay at all → <strong>PEANUTS</strong>.
Often the shortest clues in the puzzle.</div>

<h4>&amp;lit ("and literally so")</h4>
<div class="mini">Rare and prized: the <em>whole clue</em> is simultaneously the definition
<em>and</em> the wordplay, traditionally flagged with an exclamation mark. Classic teaching
example: <span class="clue"><mark class="ind">Terribly</mark> angered!</span> — an anagram
("terribly") of ANGERED gives <strong>ENRAGED</strong>, and the entire clue, read plainly,
also defines it.</div>

<h3>Common indicator words</h3>
<table>
<tr><th>Type</th><th>Typical indicators</th></tr>
<tr><td>Anagram</td><td>broken, destroyed, confused, drunk, wild, cooked, exercising, mobile, at sea, in a mess, perished, transformed</td></tr>
<tr><td>Container</td><td>in, inside, holding, swallowing, wearing, about, around, covering, accepting, picking up, boxing</td></tr>
<tr><td>Hidden</td><td>some, part of, a bit of, held by, within, arrests, conceals</td></tr>
<tr><td>Homophone</td><td>we hear, reportedly, on the radio, said, called out, audibly</td></tr>
<tr><td>Reversal</td><td>back, returned, reflected, over, rejected; in down clues: up, rising, climbing, served up</td></tr>
<tr><td>Deletion</td><td>headless, endless, almost, most(ly), short, gutted, stripped, without, wanting, losing</td></tr>
<tr><td>First/last letters</td><td>initially, at first, opening of, finally, ultimately, at last, extremes of</td></tr>
</table>

<h3>Common abbreviations</h3>
<p>Setters lean on a shared stock of tiny substitutions. A starter set:</p>
<table>
<tr><td>a/one</td><td>A, I, AN</td><td>good</td><td>G</td><td>river</td><td>R</td></tr>
<tr><td>about</td><td>C, CA, RE</td><td>hospital</td><td>H</td><td>right/left</td><td>R / L</td></tr>
<tr><td>bishop</td><td>B, RR</td><td>island</td><td>I, AIT</td><td>run(s)</td><td>R</td></tr>
<tr><td>black</td><td>B</td><td>king</td><td>K, R, ER</td><td>sailor</td><td>AB, TAR, SALT</td></tr>
<tr><td>church</td><td>CH, CE</td><td>love/duck/round</td><td>O</td><td>soldier(s)</td><td>GI, RE, MEN, ANT</td></tr>
<tr><td>doctor</td><td>DR, MO, MB, GP</td><td>money</td><td>M, L, P, TIN</td><td>street</td><td>ST</td></tr>
<tr><td>female/male</td><td>F / M</td><td>note</td><td>DO–TI, A–G</td><td>time</td><td>T</td></tr>
<tr><td>quiet</td><td>P, SH</td><td>old</td><td>O, EX</td><td>with</td><td>W</td></tr>
</table>

<h3>A method that works</h3>
<ol>
  <li>Read the clue once for fun, then <strong>forget the surface</strong> — it is designed to mislead.</li>
  <li>Try the <strong>first word(s) and last word(s) as the definition</strong>; the rest is wordplay.</li>
  <li>Hunt for <strong>indicator words</strong> — they tell you which machinery is in play.</li>
  <li>Count letters relentlessly. If "confused" sits next to exactly 9 letters and the answer has 9, it's an anagram.</li>
  <li>Use crossing letters, and don't be too proud for the hint ladder — each level is designed to teach you the next skill, not to give the game away. Take them in any order: the suggested next one is offered first, but if you only want the indicators, take the indicators.</li>
</ol>
`;
