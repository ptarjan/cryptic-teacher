#!/usr/bin/env python3
"""Rewrite the parts of README.md and docs/ that the repo already knows the answer to.

A README goes stale one true sentence at a time. Every count in it was correct
the day it was typed, every tool in its file list existed, every default it
quoted matched the script -- and then the nightly job added a puzzle, someone
added a tool, someone changed a default, and the file quietly started lying.
Nothing fails when that happens, which is exactly why it keeps happening.

So the facts are not typed here at all. Regions of README.md,
docs/NIGHTLY.md and docs/LAYOUT.md are generated between HTML-comment markers, from the same files
the app and the schedulers read:

    LADDER   the hint rungs, with app.js's own labels and in its order
    KNOBS    the scheduling defaults, parsed out of the shell scripts (docs/NIGHTLY.md)
    LAYOUT   what is in the repo, file by file (docs/LAYOUT.md)

Everything outside those markers is prose about how the thing works, which is
the part a person should be writing. If you find yourself wanting to type a
number into it, put the number in here instead.

    python3 tools/build_readme.py           rewrite the generated regions
    python3 tools/build_readme.py --check   exit 1 if they are out of date

tools/daily_update.sh runs it when its rebase conflicts. Counts of puzzles and
clues are not generated here: they change every day, so they live on the live
site (/progress/, built from the same puzzle files at each deploy). The check
is what makes the regions safe: a tool added without a description, or a
default changed without the README following, fails it rather than rotting
quietly.
"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
LAYOUT_DOC = REPO / "docs" / "LAYOUT.md"
NIGHTLY_DOC = REPO / "docs" / "NIGHTLY.md"

# What each tracked file is for, in one line. This table is the reason the
# layout block cannot go stale: build_layout() compares its keys against the
# files git is actually tracking and refuses to write anything if the two
# disagree, so a tool added without a description is a build failure and a
# description left behind by a deleted tool is the same. Order is the order the
# README prints; the blank-string keys are section headings.
LAYOUT = [
    ("", "index.html, style.css, app.js", "the app (vanilla HTML/CSS/JS)"),
    ("", "analytics.js", "the one shared GA snippet every page loads, so there is exactly one id"),
    ("", "landing.js", "on a puzzle answers page, marks the clue a search visitor came for (Google's text fragment, or #12-across) and offers the rest of the crossword with hints under it"),
    ("", "appnav.js", "the home-screen app's bottom tab bar (Puzzle, Puzzles, Stats, Learn) and back link, shown only when the site runs standalone with no browser around it"),
    ("", "quotes.js", "curls the straight quotes clue text is stored with, for display (tools/quotes.py stores them straight)"),
    ("", "qr.js", "the QR encoder, drawn in the page: the sync code is the account, so it is never handed to an image service"),
    ("", "inflate.js", "gunzip for the browsers without DecompressionStream, loaded only when one has to inflate a gzipped puzzle by hand"),
    ("", "vendor/", "the one dependency shipped to the browser: jsQR, pinned by filename and sha256, fetched only when someone scans a code"),
    ("", "learn/", "the “How cryptic clues work” lesson, built from tools/tutorial.html — generated, not committed"),
    ("", "abbreviations/", "the glossary of standard abbreviations the blocks rung links into — generated, not committed"),
    ("", "indicators/", "every indicator the blogs and our annotations use, by type and by how many clues use it, from tools/data/lexicons/indicators.json — generated, not committed"),
    ("", "difficulty/", "how the difficulty badge is worked out and checked, built from tools/difficulty_page.html — generated, not committed"),
    ("", "og/", "one 1200x630 social card per puzzle, drawn from one of its clues — generated, not committed"),
    ("", "puzzles/index.json, puzzles/index.js",
     "manifest: one row per puzzle, latest first, and the same as a script so file:// works — built by tools/fetch_puzzle.py --reindex, not committed"),
    ("", "puzzles/<series>/<year>/<series>-<n>.json", "one puzzle per file, plain JSON: the whole file is the payload; <year> is the UTC year of its date, or a book puzzle's `year`, or `undated` — tools/puzzle_paths.py owns the rule"),
    ("", "clues_only/<series>/<id>.json", "a puzzle held as its clues alone until the backfill's answers derive its grid; tools/clues_only.py owns the shape and the hand-off to puzzles/"),
    ("", "puzzles/<series>-<n>.js", "the same puzzle as a script, so app.js can inject it from file:// — flat, so its URL does not move with the source's year; built by tools/fetch_puzzle.py --reindex, not committed. The site ships it gzipped, as puzzles/<series>-<n>.js.gz (tools/stage_site.py), which app.js fetches and inflates"),

    ("the rest of the site", "site.webmanifest", "PWA name, icons and display mode"),
    ("the rest of the site", "robots.txt", "crawler policy, and where the sitemap is — the sitemap itself is generated by the build, not committed"),
    ("the rest of the site", "f95c3e3037390dda228633f7d76588f2.txt", "the IndexNow key, served from the site root so IndexNow can check tools/indexnow.py's pings are ours"),
    ("the rest of the site", "CNAME", "the domain GitHub Pages answers on"),
    ("the rest of the site", "og.png", "the default social card, for pages that aren’t one puzzle"),
    ("the rest of the site", "favicon.*, icon-*.png, apple-touch-icon.png",
     "the icon set, all rendered from one source by tools/make_icons.py"),

    ("fetching", "tools/fetch_puzzle.py", "fetch/convert the Guardian cryptic, Saturday prize and Quiptic, --latest/--backfill/--extend/--reindex"),
    ("fetching", "tools/fetch_independent.py", "the Independent’s daily and Sunday"),
    ("fetching", "tools/test_fetch_independent.py", "drives that parser over the days whose title is empty or is the setter’s own scratch note, and proves each one lands on the right number AND the right series — the two sequences both ran under 10,000, so the number never gets a vote"),
    ("fetching", "tools/test_privateeye_scans_vlm.py", "does tools/privateeye_scans.py put a Cyclops clue the readers leave blank to the desktop VLM (ocr_clues.vlm_pick), and leave it blank, the page deferred, with the VLM down?"),
    ("fetching", "tools/test_enumeration_separators.py", "holds the word breaks Metro and the Private Eye get from each clue’s printed enumeration, single lights and linked groups"),
    ("fetching", "tools/fetch_telegraph.py", "the Telegraph’s four series from its puzzle app’s data bucket, grids and answers as printed, since 2015; fills the numbers bigdave44.com hinted only in part"),
    ("fetching", "tools/test_fetch_telegraph.py", "proves the bucket parser files a Sunday under the Sunday Telegraph, reads grid, clues and word breaks, and drops calendar numbers that break the running order"),
    ("fetching", "tools/fetch_observer.py", "the Observer’s Everyman"),
    ("fetching", "tools/fetch_wayback.py", "recovers Guardian puzzles older than the live site keeps, out of the Wayback Machine’s captures"),
    ("fetching", "tools/fetch_globeandmail.py", "the Globe and Mail’s cryptic, its reprint of the Times Quick Cryptic, decoded from its Amuse Labs player and recorded on the Quick it reprints (tools/reprints.py)"),
    ("fetching", "tools/fetch_times_feed.py", "the Times Quick Cryptic from the Times’s own web player feed, grids and answers as printed, back to No 1; fills the numbers the blog wrote no clues for"),
    ("fetching", "tools/test_fetch_times_feed.py", "proves the Times feed's data.json becomes a puzzle with its lights placed and enumerations kept, and that a light with no clue is refused"),
    ("fetching", "tools/fetch_privateeye.py", "Private Eye’s Cyclops — the grid from the paper, the answers joined from fifteensquared, which is the only place they are published"),
    ("fetching", "tools/file_cyclops_christmas.py", "the Cyclops Christmas specials, which have no .puz: the grid read off the Eye's image by pixel sampling, clues and answers from fifteensquared, the shaded quotation as an unclued light checked against the preamble's letter list"),
    ("fetching", "tools/fetch_metro.py", "the Metro’s cryptic; today’s only, because the paper keeps no archive"),
    ("fetching", "tools/fetch_trove.py", "Canberra Times crosswords from Trove (London Times 1967-85, Guardian 1986-95): OCR text and the grid cut from the page scan, anonymously, past its Anubis proof of work; `zones` also caches the clue columns of articles left pending"),
    ("fetching", "tools/file_trove_puzzles.py", "files the Canberra Times cryptics fetch_trove.py cached as puzzles/canberra/ (numbered YYMMDD by print date): clues from the OCR, the grid read off the scan where every clue agrees with it, else rebuilt from the clues; unsolved, for the nightly cold solve; resumable through a per-article ledger"),
    ("fetching", "tools/trove_grid.py", "reads a crossword's black squares off a scanned grid image: walled white cells, a lattice fitted to them through any skew, solid ink for blocks; refuses rather than guesses"),
    ("fetching", "tools/test_fetch_trove.py", "fetch_trove.py with a stubbed opener: a timeout and a 500 retried to success, a persistent 500 named by URL, a 4xx not retried, no retry past an article's ITEM_SECONDS, a run of failures stopping the run, and `zones` fetching only pending articles that lack them"),
    ("fetching", "tools/test_file_trove_puzzles.sh", "files three real Trove articles: the grid read cell for cell, the solution grid skipped, a count the OCR misread held back by name, a second run touching nothing, and the clues alone filing a puzzle whose picture is missing"),
    ("fetching", "tools/test_desktop_offload.py", "do the Trove clue vote and the solution image match take the desktop's answer when ocr_remote gives one, the same answer here when it gives none, and do CALLS name the functions that run there?"),
    ("fetching", "tools/clue_repair.py", "repairs the clues a newspaper OCR loses (a number read as junk, a broken bracket, \"(S)\") from the other readings of the page's clue columns (ocr_clues.py's readers and the VLM, the ones that vote on its words); both scan filers apply it, anchored on text both readings share. It reads nothing itself"),
    ("fetching", "tools/clue_text.py", "single-reading clue-text OCR fixes shared by every filer: today the ACROSS / DOWN list heading read however badly (\"DOW'N\", \"AROSS\", \"D0WN\", spaced letters), a clue count torn or misread (\"(5\", \"(S)\", \"(l0)\"), a cross-reference or clue number whose digits came out as letters (\"SeeI3\", \"lO\")"),
    ("fetching", "tools/fixtures/archive-org-grids/", "archive.org page crops whose grid lies far under, over, left or right of its title, touches its title or has text touching its foot (cases.json: scan, title box, and the FT one's words), the grids test_file_archive_org_puzzles.py locates"),
    ("fetching", "tools/fixtures/archive-org-clues/", "real clue-column readings of archive.org Times editions with each one's scanned grid (cases.json; 16,960 also RapidOCR's words), the blank, cut-off and misnumbered clues test_file_archive_org_puzzles.py files whole"),
    ("fetching", "tools/fixtures/archive-org-titles/", "five archive.org page crops whose title archive.org's own text lacks (cases.json: scan, paper, date, and our readers' words in each title band), the titles test_file_archive_org_puzzles.py reads"),
    ("fetching", "tools/fixtures/trove-repair/", "the 14 July 1967 cryptic, whose OCR glued 6-down onto 5-down, with our three readers' text of its clue columns: the repair and vote test_file_trove_puzzles.sh checks"),
    ("fetching", "tools/fixtures/trove-clues/", "our three OCR readers' text of the 1 June 1972 article's clue zones, the other voters test_file_trove_puzzles.sh puts Trove's text to"),
    ("fetching", "tools/fixtures/trove-solution/", "the 2 June 1972 cryptic as first filed, whose grid test_file_trove_puzzles.sh reads that day's printed solution against"),
    ("fetching", "tools/fixtures/trove/", "three Canberra Times articles as fetch_trove.py caches them (meta.json, ocr.txt, grid.jpg), the fixtures test_file_trove_puzzles.sh reads"),
    ("fetching", "tools/repair_fetched.py", "applies the fetchers’ current rules to puzzles already on disk — bare-capital solutions, a masked prize answer, a group that is really a cross-reference in the wordplay, a linked answer the paper never grouped — and reports the dates their own neighbours contradict"),
    ("fetching", "tools/test_repair_fetched.py", "builds a puzzle file with each of those defects and proves the repair fixes it, leaves a clean file and a real Cyclops per-light group byte-identical, and is clean on the second run"),
    ("fetching", "tools/downloads.py", "where every fetcher keeps what it downloads, one folder per source under a single root: the one place each source's folder is named, and `python3 tools/downloads.py` prints the root for shell scripts"),
    ("fetching", "tools/puzzle_paths.py", "where a puzzle's file lives, puzzles/<series>/<year>/<id>.json: the one place the layout is spelled, and `python3 tools/puzzle_paths.py ID...` prints a held puzzle's path for shell scripts and prompts"),
    ("fetching", "tools/puzzle_paths.js", "the same rule for node, for the harnesses that read the puzzle sources"),
    ("fetching", "tools/puzzle_schema.py", "checks every puzzle file against tools/data/puzzle.schema.json, and prunes null and empty values on every write: an absent key means empty"),
    ("fetching", "tools/enumeration.py", "a clue's printed enumeration: split() cuts a printed line into the clue's `text` and `enumeration` for every writer, printed() joins them back"),
    ("fetching", "tools/definitions.py", "where each of an annotation's definitions sits in its clue: fills `at` from the text on every write, by the whole-word, no-overlap, clue-end rules, and refuses to guess past them"),
    ("fetching", "tools/annotation.py", "an annotation's two groups, read one way by every tool: `explanation` (the prose rung) and `assembly` (the machine-checkable rebuild), which of `assembly.anagrams` gives the whole answer, and `view()`: the fields a stored wordplay tree implies"),
    ("fetching", "tools/groups.py", "linked answers: the leader carries `group`, its lights in order, and the other lights nothing; maps each light to its group or leader, and spreads/collapses the per-light claims the Guardian ships"),
    ("fetching", "tools/test_definitions.py", "holds each of those rules, the refusal, and the validator's check that `at` points at its text"),
    ("fetching", "tools/puzzle_integrity.py", "checks the puzzles themselves: two puzzles that are the same puzzle, an answer that does not fit its clue’s printed length, two entries that cross and disagree"),
    ("fetching", "tools/quotes.py", "clue text is stored with straight quotes: straightens every write, converts held files, and curls for the static pages and social cards"),
    ("fetching", "tools/quotes_cases.json", "the one table of curl cases that quotes.js and tools/quotes.py are both run over"),
    ("fetching", "tools/punctuation.py", "the marks no clue's print breaks (\"by.clever\", \"''\" for a double quote, \",.\", \"word , word\"): faults() for the OCR write gate, the vote and edition_commit.strayed; mend() makes the certain mends, offsets moved"),
    ("fetching", "tools/test_quotes.js", "a clue stored with straight quotes shows curled ones, apostrophes and leading elisions included"),
    ("fetching", "tools/dashes.py", "clue text spells a dash between words \" \u2014 \" and an ellipsis \"\u2026\": normalises every write with its offsets moved, converts held files"),
    ("fetching", "tools/test_dashes.py", "every spelling of a dash between words becomes \" \u2014 \" and of an ellipsis \"\u2026\"; hyphens, blanks and leaders stay; offsets move with the text; DASH refuses the rest"),
    ("fetching", "tools/test_puzzle_integrity.py", "proves the two LENGTH exception tables match by nothing looser than the exact sentence they’re keyed on, and that baselining one finding never silences the rest of its puzzle"),
    ("fetching", "tools/test_puzzle_invariants.py", "proves every puzzle write refuses what the corpus sweep would report"),
    ("fetching", "tools/fetch_ia_book.py", "borrows a lending-restricted archive.org book, saves its OCR text outside the repo, returns the loan, and hands back on startup any loan a killed run left out \u2014 a finally clause does not run when the process is killed by a signal"),
    ("fetching", "tools/parse_penguin_book.py", "segments that book's OCR text into puzzles, clues and enumerations, and reports per-puzzle what OCR destroyed"),
    ("fetching", "tools/file_penguin_puzzle.py", "turns one solved Penguin-book puzzle into a puzzle file: the book's own number, its book's imprint year as `year` in place of a date, and answers marked as a model's with no official key ever coming"),
    ("fetching", "tools/normalise_linked_enumerations.py", "puts a solve record’s linked answers into the shape the corpus stores them in — the whole answer’s count on the leader, none on the continuation — reading the words off the answer rather than off the per-light numbers, and refusing when a “See N” names two lights it cannot choose between"),
    ("fetching", "tools/acquire_book.py", "takes a book from an archive.org identifier to filed puzzles with no model in the loop: public text layer, split, light spec, reconstructed grid, filed unsolved for the nightly solve queue (a leaf whose clues are a held puzzle's, a Times anthology reprinting the daily, is kept as a reading that votes on that puzzle's clues, not filed as a new book-N; a newspaper puzzle whose book copy is held is refused instead, the book file kept and the pair recorded in tools/book_twins.py for the cross-check), and a per-puzzle report of what it got and why the rest failed"),
    ("fetching", "tools/light_spec.py", "turns one OCR'd clue list into the light spec the reconstructor wants, repairing linked fields, clues OCR ran together, and numbers that lost a digit, without ever guessing a number"),
    ("fetching", "tools/grid_verdict.py", "judges a recovered grid by CPU alone — whether the clue list can be a 15x15 at all, and whether the fills that come back are a real puzzle, an ambiguous pair a human must pick between, or a light list the OCR ate clues out of; every threshold carries the share of the corpus it costs"),
    ("fetching", "tools/clues_only.py", "puzzles held as their clues alone in clues_only/<series>/<id>.json, never published: a filer whose grid search did not settle files the clues in printed order with no numbers, positions or answers; the nightly solve answers them and tools/apply_solution.py derives the one grid the answers cross in and files the puzzle in puzzles/"),
    ("fetching", "tools/test_clues_only.py", "strips a solved book puzzle to its clues, has tools/apply_solution.py promote it, and checks the derived grid and numbering are the published ones and that no half state (a number, position or answer on a clues-only light, an id in both states) can be written"),
    ("fetching", "tools/test_acquire_book.py", "gates that pipeline on ten control puzzles from Penguin volume 5, failing if a single recovered grid or a single search node count moves; and is a reprint of a held puzzle kept as its reading, never filed?"),
    ("fetching", "tools/test_ia_borrow.py", "holds the one archive.org refusal string that means two different things apart, so a book whose copies are all out is never read as one that needs no loan, and keeps the account-wide lending limit a third answer that stops the run rather than a twenty-fourth per-book failure"),
    ("fetching", "tools/test_ia_loan_leak.py", "kills a real borrow with SIGTERM and SIGKILL against a stub archive.org to prove the loan does leak, then proves the next run gives it back before borrowing anything of its own"),
    ("fetching", "tools/test_penguin_layout.py", "gates the dotted-number print layout — glued running head, \"13.\" numbers, \"1 & 4 Ac.\" links — whose loss costs a whole book to jigsaw mode and 0% of its clue numbers"),
    ("fetching", "tools/test_linked_enumerations.py", "proves a per-light solve record is converted rather than filed, that a record already in leader form is never re-derived, and that every linked answer in the book series on disk still carries its count on the leader alone"),
    ("fetching", "tools/test_group_order.py", "proves a linked answer's group is written in the order its words read, and that the integrity sweep reports one that is not"),
    ("fetching", "tools/test_blank_clue_carry.py", "proves a re-fetch cannot empty a puzzle whose clues were recovered by hand off the Guardian’s old site, that the paper still wins wherever it prints words, and that the sixteen recovered prize puzzles still carry every clue"),
    ("fetching", "tools/test_alteration.py", "holds an entry's `alteration` (the clue's own word and the steps that turn it into what the grid holds) to its letters at the write gate, every op one mapping accepted and one refused, and an annotation's wordplay to building that word"),
    ("fetching", "tools/test_unclued_printed.py", "holds a puzzle's unclued lights and printed letters to its grid at the write gate: on the board, one letter per square, no square twice, and the same letter as every crossing entry"),
    ("fetching", "tools/test_empty_keys.py", "holds the rule that a puzzle file never writes a key that says nothing: the fetchers omit an empty clue.separators and an un-written annotation, a file without them round-trips, and every reader — app.js, the difficulty scorer, the crawlable pages, the social cards — takes the absence as the empty value it replaced"),
    ("fetching", "tools/test_source_answer_wrong.py", "proves the table of answers the PAPER got wrong still corrects the letters it names, still leaves every other light alone, and names itself stale rather than overriding a key the paper has since fixed"),
    ("fetching", "tools/coverage_report.py", "counts what we hold of every series and names the ones that have gone quiet, were never backfilled, or are full of holes"),
    ("fetching", "tools/test_coverage_waiting.py", "a recent clues-only hold keeps a series from reading as gone quiet; an old one does not"),
    ("fetching", "tools/extend_archive.py", "walks the archives backwards to keep the annotation queue deeper than the job's best week"),
    ("fetching", "tools/first_issue.py", "asks each series' source for its No 1 on every run while we lack it, and says where it looked when that fails"),
    ("fetching", "tools/test_first_issue.sh", "runs first_issue.py's self-test: a row in SOURCES for every series with a first issue, and a 404 reported with where it looked"),
    ("fetching", "tools/fetch_minutecryptic.js", "Minute Cryptic’s daily hints, as a corpus to be measured against"),
    ("fetching", "tools/recover_minutecryptic.py", "refills days that capture missed from Minute Cryptic’s own video titles, dated by clue number because the upload date lags"),
    ("fetching", "tools/fetch_fifteensquared.py", "caches the blog that covers six of our series, and its comments — fetched once each, at their 20-second crawl delay"),
    ("fetching", "tools/blog_facts.py", "joins each cached blog write-up to the puzzle it explains and keeps what its markup states about the clues — the underlined definition, marked indicators, WORD (clue words) building blocks (a homophone's or spoonerism's as the words heard, where they sound like the answer), and a clue type the write-up names or spells out in letters that check against the answer — never the blog's prose; the nightly reruns it only when an input moved"),
    ("fetching", "tools/blog_store.py", "reads and writes the blog facts one sidecar a puzzle (puzzles/<series>/<year>/<id>.blog, a suffix no *.json glob matches): the rows of a series or of one puzzle, the digest of them, and the sync that writes only the sidecars that moved"),
    ("fetching", "tools/letter_facts.py","adds a clue type the blog left out where the letters leave one reading and that reading's class matched the blogs' own types at least 97% of the time on held-out clues (anagram fodder, a hidden answer, one block cut from another), and the type less how a block was taken from its words where that core matched 97% (marked \"typeCore\", a lower bound), all marked \"inferred\" so nothing mistakes it for the blogger's; and the building blocks the blog left out, where the answer splits one way only into the blocks it gave and clue words read as the blogs read them in other puzzles (97% exact against blog blocks hidden from it, held out by puzzle), each marked \"inferred\"; the definition where the blog underlined none, the one span at an end of the clue clear of the wordplay that blogs underlined for the same answer elsewhere (97% exact against blog definitions hidden from it); and the indicator those blocks want where the blog named none, both named in the clue's \"inferred\"; the blocks a write-up gives in prose, where the capitals it prints, the clue words it glosses them with or prints, and the answer's letters agree on one split (read off the leads blog_facts.py keeps beside its cache; 98.6% exact against blog blocks hidden from it, held out by puzzle); a hidden word's carrier, the one run of clue words that spells it (98.4% our annotations' own); and the indicator a homophone's or spoonerism's heard blocks want; blog_facts.py runs it after each write, the lexicons built here and the clues read on the OCR host (over ssh, the code shipped as tools/ocr_remote.py ships it) unless it is busy or off, else in a local pool; --coverage says what the written facts cover and why the rest fall short"),
    ("fetching", "tools/indicator_keys.py", "the one spelling of an indicator phrase indicators.json is keyed by, and the one type each indicator is credited to, its own `for`; the /indicators/ page and the burn's indicator cover both match through it"),
    ("fetching", "tools/test_indicator_keys.py", "holds which (type, key) pairs a clue's indicators give: a phrase links the longest key inside it only in a one-type clue, never through link words alone; and which clue /indicators/ links, ours over a blog's"),
    ("fetching", "tools/test_letter_facts.sh", "holds letter_facts.py to one reading per clue: a literal word is not an anagram, a lone word's initial not an abbreviation unless listed, fodder less blocks is left undecided, a write-up's prose read into blocks only where it gives one split, a word beside a block left out only where blogs seldom take it in, fodder apart in the clue anagrammed as one, a hidden word's carrier only where one run spells it"),
    ("fetching", "tools/test_blog_facts.sh", "holds that reader to hand-built posts, so a definition or a block's source is only ever words of our clue and a type only one the write-up names unambiguously or its letters bear out"),
    ("fetching", "tools/blog_facts_gold.jsonl", "hand-read truth for clues across the three blogs, their series and markup eras: what each post says the definition, blocks, indicators and type are; blog_facts.py --score measures precision and recall per field against it"),
    ("fetching", "tools/post_index.py", "a local index (~/.cache) of each cached blog's posts — title, link, slug — topped up from a listing, so a one-puzzle lookup opens only its own posts instead of the 20k+ on the media share"),
    ("fetching", "tools/corroborate.py", "checks every puzzle written against the other sources we cache for it — georgeho's scrape, fifteensquared's posts, the Times listing — filling an empty setter, date or clue, settling an answer they disagree on by the grid, the print sequence, independent votes and a measured rank, and ledgering every call; never refuses a write"),
    ("fetching", "tools/test_corroborate.py", "decides one case by each of corroboration's rules, and proves a fill never overwrites, a disagreement never raises, and every write goes through it"),
    ("fetching", "tools/fetch_wp_blog.py", "caches the two WordPress blogs that cover the Times and the Telegraph, the only archives that print their clues — each post fetched once, at the blog's crawl delay"),
    ("fetching", "tools/parse_timesforthetimes.py", "reads that cache into clue, answer and light-length records — the input a withheld Times grid is rebuilt from"),
    ("fetching", "tools/test_parse_timesforthetimes.sh", "holds that parser to one fixture per era of the blog's markup, because a misread answer becomes a wrong light length"),
    ("fetching", "tools/parse_bigdave44.py", "reads the bigdave44.com cache into one Telegraph clue, answer and light-length record per puzzle, with its series, setter and print date, through the Times parser's clue-list reader"),
    ("fetching", "tools/test_parse_bigdave44.py", "holds that parser to hand-built posts: each era's answer markup, the setter never the blogger, and a print date only from what the posts or the cadence prove"),
    ("fetching", "tools/times_grids.py", "runs the numbering backwards on either blog's records to rebuild the grids the Times and the Telegraph withhold, narrowing a shortlist by where the answers cross; each attempt keeps its light list's digest, so a parser fix re-tries the posts it changes; --budget-seconds stops starting posts when the nightly's time is spent"),
    ("fetching", "tools/test_times_grids.py", "holds that rebuilder to a hand-built grid, because a wrong grid looks exactly like a right one"),
    ("fetching", "tools/barred_grid.py", "rebuilds a barred grid's bars (the Mephisto) from the blog's numbered answers, where every cell holds a letter"),
    ("fetching", "tools/test_barred_grid.py", "holds that rebuilder to a hand-built barred grid: the bars that come back are the bars it was numbered from"),
    ("fetching", "tools/fetch_times_listing.py", "caches the Wayback Machine's copies of the Times's own puzzle listing, the one first-party record of the day each number was printed; what dates the prize puzzles the blog writes up a week late"),
    ("fetching", "tools/file_blog_puzzles.py", "files a blog's rebuilt grids as puzzles with the blog's answers — only complete, correctly numbered ones — and never rewrites a filed one but for its date; what the blog filers share"),
    ("fetching", "tools/file_times_puzzles.py", "files the Times grids through it, dated by print day; the nightly top-up"),
    ("fetching", "tools/file_telegraph_puzzles.py", "files the Telegraph grids through it, with the setter and print date the parser read; the nightly top-up"),
    ("fetching", "tools/test_file_times_puzzles.py", "holds that filer to a hand-built grid: what it refuses, what it dates, and that a second run touches nothing"),
    ("fetching", "tools/test_times_dates.py", "holds every filed Times, Jumbo and Sunday Times date to its paper's weekday and number order, so a prize puzzle dated by its blog post fails"),
    ("fetching", "tools/ft_puzzles.py", "files the Financial Times cryptic from fifteensquared's cached write-ups: reads each era of their markup, rebuilds the grid ft.com will not serve a script with the Times' search, and files what passes the Times filer's checks; the nightly top-up"),
    ("fetching", "tools/indy_puzzles.py", "the same pipeline on fifteensquared's Independent category: files the daily and Sunday puzzles older than the paper's feed, routed by title and number, never a number already on disk"),
    ("fetching", "tools/test_indy_puzzles.py", "holds its title routing to both papers' post titles and its Sunday dates to their order"),
    ("fetching", "tools/ft_pdf_puzzles.py", "files the FT cryptic of 2007-2012 from the FT's own printable PDFs, found through Wayback's copies of ft.com/arts/crossword: clues and the grid's black squares read from the PDF, answers from fifteensquared, filed only when the grid's numbering matches the clue list and every answer crosses"),
    ("fetching", "tools/azed_puzzles.py", "files the Observer's barred Azed from fifteensquared's cached write-ups: reads the clues and numbered answers with the FT's reader and rebuilds the bars from them, so a special whose answers go in altered is not filed"),
    ("fetching", "tools/andlit_azed.py", "files the Azed from the Guardian's own printable copies, found through andlit.org.uk's index: reads the clues and the barred grid off the HTML print page's bordered table or the PDF's ruled lines, checks the numbering against the numbers printed in the grid and the clue list, and takes fifteensquared's answers where a post has them; the azed unit fetches until andlit's index is drained"),
    ("fetching", "tools/test_andlit_azed.py", "holds that reader to hand-drawn lattices, stroked and filled, beside a smaller solution grid, a bordered HTML table, cell numbers run together, and a clue list with notes and form lines between clues"),
    ("fetching", "tools/genius_puzzles.py", "files the Guardian's monthly Genius from its printable PDFs on uploads.guim.co.uk (clues and preamble read as text, the grid from its image) with fifteensquared's answers, filed only when the grid's numbering matches the clue list and every answer crosses; an entry altered by the preamble's rule carries its answer, a jigsaw's clues are placed (JIGSAW), and a puzzle with no post files unsolved"),
    ("fetching", "tools/tls_puzzles.py", "files the newest Times Literary Supplement crossword unsolved off the TLS's own page image (WordPress listing on www.the-tls.com): the grid read from its pixels, the clues by the en5 OCR reader, filed only when every light has a clue of its length"),
    ("fetching", "tools/listener_puzzles.py", "files the Listener crossword from the Listener Team's archive PDFs (clues, bars and letters read from the vector pages) and from Wayback copies of the Times' pages, the grid rebuilt from the solution notes' answers; an answer entered altered files the entry, the clue's word in its `alteration`"),
    ("fetching", "tools/test_listener_puzzles.py", "holds that reader to hand-drawn cell sides and a two-column clue page whose right-hand numbers sit on the left's lines, and the Times side to its preamble rules (a run moved, S and N out and T in), bar symmetry and the notes' answer column"),
    ("fetching", "tools/test_ft_pdf_puzzles.py", "holds that reader to a hand-drawn grid of content-stream rectangles, a wrapped clue list and an answers-only post, because a misread block renumbers the whole grid"),
    ("fetching", "tools/test_ft_puzzles.py", "holds that parser to each layout fifteensquared prints an FT post in, and the filer to a hand-built grid, because a misread answer becomes a wrong light length"),
    ("fetching", "tools/fetch_lexicon.sh", "downloads the Lufz/Exet lexicon the grid filler needs"),

    ("annotating", "tools/annotate_prompt.md", "the prompt the daily Claude Code job follows to annotate"),
    ("fetching", "tools/vlm_solution_prompt.md", "the prompt the vision model gets to read one row of a printed solution grid"),
    ("fetching", "tools/vlm_report_prompt.md", "the prompt the vision model gets to read one light of a Listener report's typewritten filled grid"),
    ("annotating", "tools/build_annotate_prompt.py", "regenerates that prompt’s wordplay grammar from tools/wordplay.py, and its worked examples from the corpus in the shape the run writes"),
    ("annotating", "STYLE.md", "the standing style rules, read whole by every annotating run"),
    ("annotating", "APP.md", "how the app presents an annotation and how it ships — separate from style"),
    ("annotating", "BACKFILLS.md", "the sweeps over already-published clues, worth doing only with inference to spare; every item is already handled going forward, so none of it blocks a puzzle"),
    ("annotating", "tools/blog_post.py", "prints the cached blog post and comments that explain a puzzle, for an annotation run stuck on a clue"),
    ("annotating", "tools/annotate_check.py", "the one command an annotation run needs after every edit: applies, validates, audits, reindexes, and says everything wrong at once"),
    ("annotating", "tools/test_annotate_disclosure.py", "proves each rule cut from the annotation prompt still arrives through its check, and that the blog lookup is disclosed only once the last few clues are null — never earlier, never blind"),
    ("annotating", "tools/validate_annotations.py", "proves every annotation actually spells its answer, plus the other rules about what a rung may and may not say"),
    ("annotating", "tools/test_indicator_note_letters.py", "an indicator note may not write a block's letters, since its rung comes before the blocks"),
    ("annotating", "tools/test_selector_indicator.py", "a letter selector (\"capital of\", \"initially\") is an indicator, so a new or changed block holds only the words it selects from"),
    ("annotating", "tools/test_anagram_fodder.py", "an anagram's fodder is drawn from the clue's wordplay and its blocks' letters"),
    ("annotating", "tools/test_wordplay_shape_rules.py", "each wordplay shape rule is counted by validate_annotations against its own wordplay.* allowance (a charade inside a charade, an op with no indicator, a cryptic definition's extra leaves, wrong arity, clue words claimed twice, a leaf folding its own words, a selection repeated word by word, one-leaf wordplay, bare letters in a charade, an anagram around a container), and tidy_wordplay_shapes.py joins a charade inside a charade once"),
    ("annotating", "tools/test_walkthrough_follows.py", "a hint can be followed: findings (not errors) when a walkthrough never names an indicator or shows an intermediate result of the wordplay tree, or an anagram, reversal or hidden indicator is separated from its fodder by content words"),
    ("annotating", "tools/test_flatten_anagram_fodder.py", "an anagram's pieces are its own parts: ana(x + y) stores them there, a join with its own indicator inside ana() is refused, the validator counts a charade directly under an anagram against the wordplay.anagramCharade allowance, and flatten_anagram_fodder.py rewrites a filed one in clue order without changing view(), and changes nothing on a second run"),
    ("annotating", "tools/test_setter_error.py", "a clue the setter printed wrong is annotated as printed: the anagram mismatch tools/data/setter_error.json names for that light passes, with a walkthrough saying so, every other mismatch still fails, and a row that is neither a whole-answer nor a partial anagram of what the clue prints is refused"),
    ("annotating", "tools/test_indicator_straddle.py", "an indicator may sit inside a definition but not across its edge"),
    ("annotating", "tools/test_indicator_repeats.py", "an indicator may repeat in `indicators` only as often as the clue prints it"),
    ("annotating", "tools/blog_compare.py", "compares every annotated clue's definition, type and blocks with what its blog marked, using the validator's own blog checks; writes the rates per series and the puzzles still disagreeing (due) to tools/data/blog_compare.json, which the burn re-checks; --keep files a clue checked and kept"),
    ("annotating", "tools/test_blocks_against_blog.py", "holds the blog block and type checks to their fixtures: a piece we spell, reverse, hear, delete from or anagram is silent, and one we lack is reported; a type in another family (double definition against charade) is reported, a label within one is not, and a clue filed in blog_disagree.json is silent"),
    ("annotating", "tools/hidden_messages.py", "hidden-letter devices: checks each annotation's `hiddenLetter` against its clue and each `messages` phrase against its clues' letters, flags preambles that name a device, and converts existing annotations whose blocks already carry the letters"),
    ("annotating", "tools/test_hidden_messages.py", "holds `hiddenLetter` to its clue's blocks or text, `messages` to its clues' letters in order, the preamble detection's hits and misses, and the converter"),
    ("annotating", "tools/test_theme_clue.py", "holds `themeClue`, the hand-filed clue that states a themed puzzle's gimmick, to standing in for a preamble for clue-word-less blocks, naming a worded entry, re-queuing a recorded annotate failure, surviving clues-only promotion, and never being set or changed by an annotation"),
    ("annotating", "tools/test_defined_by_preamble.py","holds `definedByPreamble` to standing in for `definition` only where the puzzle prints a preamble, and never beside a definition"),
    ("annotating", "tools/apply_annotations.py", "translates a run’s annotation JSON (def, wp, notes) and writes it into the puzzle file in that file’s shape, and validates the result"),
    ("annotating", "tools/annotation_backlog.json", "how many clues of each OLD puzzle predate a required field; a puzzle not listed is allowed none, so new rules bind new puzzles"),
    ("annotating", "tools/check_annotation_loss.py", "shouts when an annotation run leaves clues it could not solve, so a weak night can't pass for a good one"),
    ("annotating", "tools/find_answer_leaks.py", "finds a block note that says the answer out loud, a rung before the walkthrough sells it"),
    ("annotating", "tools/find_renarration.py", "flags a walkthrough that only restates the blocks instead of teaching past them"),
    ("annotating", "tools/clue_quality.py", "warns about the clue shapes that lost to human setters in blind grading"),
    ("annotating", "tools/clue_types.py", "the closed list of clue types an annotation's `type` array names, with their labels and families, for the Python tools"),
    ("annotating", "tools/clue_shapes.py", "the census of every whole-clue wordplay tree shape (op tree, leaves abstracted to V/F/A/S/B/U) over the annotated corpus: counts, families, op nesting, mix by series, three examples each, and each shape's verdict from tools/data/clue_shape_verdicts.json; writes docs/CLUE_SHAPES.md (nice -n 19, about ten minutes; --dump writes every skeleton)"),
    ("annotating", "tools/test_clue_shapes.py", "does tools/clue_shapes.py reduce hand-built trees to the right skeleton and verdict (a redundant anagram-of-charade, a repeating cryptic definition, a mislabelled anagram-over-container), and is the verdict file valid?"),
    ("tables everything else reads", "tools/data/shape_suspects.json", "ranked clues whose wordplay tree tools/shape_suspects.py judges probably wrong (id, clue, skeleton, reasons, score from hand-measured detector precision); a work list for re-annotation, not read by anything"),
    ("tables everything else reads", "tools/data/burn_requests.json", "puzzle ids Paul wants the burn to hint first (rebus puzzles), a hand list; tools/prereset_plan.py puts the queued ones ahead of everything but a lockout's pins and drops an id once its puzzle is fully annotated"),
    ("tables everything else reads", "tools/data/shape_reannotate.json", "the shape suspects tools/fix_shape_suspects.py could not repair mechanically, one row per clue ({id: puzzle#clue, reason}); the burn's last queue tier and the clues an annotate run rewrites (tools/shape_queue.py prunes a row once its clue is re-filed)"),
    ("tables everything else reads", "tools/data/clue_shape_verdicts.json", "the judgements tools/clue_shapes.py applies to wordplay shapes, keyed by exact skeleton or by regular expression with depth and mechanism bounds: ok, rare, redundant, mislabelled, implausible or unverified, why, and the right shape; the tool never writes it"),
    ("annotating", "tools/app_tables.py", "the rung ladder and series blurbs, read out of app.js by the tools so there is no copy of the app’s order or wording to keep in step"),

    ("setting our own puzzles", "tools/AUTHORING.md", "how an original puzzle gets set: the grid is filled first, the clues written by hand after"),
    ("setting our own puzzles", "tools/grid_rules.py", "what makes a British blocked grid legal, in one place"),
    ("setting our own puzzles", "tools/reconstruct_grid.py", "recovers a puzzle’s black squares from its clue list alone, for grids we have no readable picture of"),
    ("setting our own puzzles", "tools/test_reconstruct_grid.py", "scores that reconstruction against real grids, with and without the clue numbers, and re-counts the conventions it leans on"),
    ("setting our own puzzles", "tools/grid_fill.py", "fills a legal grid with answers you can actually write clues for"),
    ("setting our own puzzles", "tools/clueability.py", "scores how easy a fair cryptic clue for a word would be"),
    ("setting our own puzzles", "tools/build_lexicon.js", "extracts the fillable word list (rank, region, family, phonetics) from the lexicon"),
    ("setting our own puzzles", "tools/build_authored_puzzle.py", "merges a fill and its hand-written clues into a publishable puzzle file"),
    ("setting our own puzzles", "tools/test_build_authored_puzzle.py", "builds A001 through the real write path into a scratch tree and holds it to the schema, the integrity checks and the annotation rules, since no corpus sweep ever sees it; and does a book copy of a newspaper puzzle become a reading of it whichever was filed first, by one job or by two"),
    ("setting our own puzzles", "tools/test_hidden_edges.py", "holds the builder's refusal of a hidden answer that sits inside one word or starts or ends on a word boundary, forwards or reversed"),

    ("solving the puzzles whose answers aren’t published yet",
     "tools/solve_packet.py", "the clues and the grid’s crossing map, for a cold solve"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/solve_prompt.md", "the method the model follows"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/apply_solution.py", "writes a blind solve in only if every crossing letter agrees"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/reopen_answers.py", "blanks the model answers an annotate run found no parse for, once each, so the burn solves them again instead of parking the puzzle"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/test_model_answers.py", "an annotator’s correction of a model answer lands only if every crossing and printed answer still agrees; a reopen happens once and never to a printed answer"),
    ("solving the puzzles whose answers aren’t published yet", "tools/fixtures/times-17379-model-solved.json", "times-17379 as the model first solved it, frozen so tools/test_model_answers.py does not move with the live corpus file"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/solve_misses.py", "lists the graded misses no diagnosis has looked at, packs one up for it, records the verdict, and keeps each cold solve’s output until its key arrives"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/solve_miss_prompt.md", "the prompt the nightly job follows for each graded miss: name the mechanism, fix the class in the solve prompt or the checker, or record that nothing generalises"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/test_solve_misses.py", "holds that each graded miss is pending until a verdict is recorded, and never after"),
    ("solving the puzzles whose answers aren’t published yet",
     "tools/test_blog_grade.py", "a model’s solve is graded once, through the paper’s grader, when a solver’s blog or another copy arrives with answers: the copy’s answer takes over unless the crossings refute it, and each miss lands in blind_misses.json"),

    ("building and checking the site", "tools/build_seo_pages.py", "one static page per puzzle, for search engines and unfurls"),
    ("building and checking the site", "tools/test_build_shards.py", "holds the sharded page render to one stable split in every process, an unmoved page-cache fingerprint, and a tail that refuses a missing shard, since a shard that drops or doubles a page breaks the site silently"),
    ("building and checking the site", "tools/build_clue_joints.py", "measures clue_joints.json from published annotations; the nightly reruns it"),
    ("building and checking the site", "tools/build_fill_floors.py", "measures fill_floors.json from published answers; the nightly reruns it"),
    ("building and checking the site", "tools/build_abbreviations.py", "publishes the abbreviations table to the browser as abbreviations.js, so the solver’s glossary can’t drift from the clue-writer’s"),
    ("building and checking the site", "tools/build_readme.py", "this: rewrites the generated regions of README.md, docs/NIGHTLY.md and docs/LAYOUT.md, --check fails on drift"),
    ("building and checking the site", "tools/make_og_card.py", "picks a puzzle’s best clue and lays out its social card"),
    ("building and checking the site", "tools/make_og.sh", "screenshots those cards with headless Chrome"),
    ("building and checking the site", "tools/og_list.py", "prunes the cards no puzzle gets and lists the stale ones for make_og.sh, in one pass"),
    ("building and checking the site", "tools/test_og_card_key.py", "is a social card redrawn only when what it shows could change? Its key is the hash of the page Chrome is handed, so an edit to the drawing code or the site card moves no key, a reworded clue or a template change does, and a card the old scheme drew is adopted rather than redrawn"),
    ("building and checking the site", "tools/parallel.py", "pmap(): a map over the corpus on every core, results in order, for the build’s per-puzzle passes"),
    ("building and checking the site", "tools/test_shim_format.py", "holds the packed puzzle shims to unpacking into exactly the puzzle the browser should hold"),
    ("building and checking the site", "tools/og_palette.py", "rewrites each card as a 64-colour palette PNG, under a third of the size"),
    ("building and checking the site", "tools/stage_site.py", "links the published files into _site/ for Pages and fails on any link to a file left out"),
    ("building and checking the site", "tools/make_icons.py", "renders every favicon and PWA icon from one source of truth"),
    ("building and checking the site", "tools/stamp_assets.py", "cache-busting ?v= stamps; the smoke test fails on a stale one"),
    ("building and checking the site", "tools/puzzle_tags.py", "what is unusual about each puzzle (pangram, barred grid, special rules…), read off its file: TAGS defines each feature once, its name, blurb and test; reindex writes the tags into the index, the app badges them and filters the picker by them, and /showcase/ gives each a section"),
    ("building and checking the site", "tools/puzzle_style.py", "whether a puzzle is a cryptic at all: `style` \"straight\" when its clues are definitions with no wordplay (the 1930 Listeners and Times, a 1970 Guardian run), by its annotation, or for a pre-1960 puzzle by its short clues; reindex writes it, the app notes it and drops the indicator, clue-type and blocks rungs, difficulty and the family counts skip it, and the hinting queues take it last"),
    ("building and checking the site", "tools/test_puzzle_style.py", "is each real puzzle read by eye as straight called straight, and its cryptic look-alike (an Azed special, a terse 2021 Guardian, 1967 cryptic definitions) not; is a straight puzzle unrated and behind every cryptic in the hinting queue?"),
    ("building and checking the site", "tools/test_straight_ladder.js", "does Listener No 1, a straight puzzle, say so above its clues and offer no indicator, clue-type or blocks rung, while a 1930 Times puzzle with wordplay keeps them?"),
    ("building and checking the site", "tools/test_puzzle_tags.py","is each tag on a real puzzle that has it and off the look-alike that does not (a feed that lost its clues is not unclued, an erratum is not special rules, a model's solve is never a pangram)?"),
    ("building and checking the site", "tools/showcase.py", "the puzzles /showcase/ picks out and why: a section per feature in puzzle_tags.TAGS, with its label, blurb and tag test, so the showcase and the app's feature filter cannot drift, then rankings (longest, hardest, most clues…); facts come from build_seo_pages as it renders each page; only annotated puzzles are shown, and wanted() tells the burn which to annotate first"),
    ("building and checking the site", "tools/test_showcase.py", "is each showcase detector on a real puzzle that has the feature and off the look-alike (hidden in the clue is not hidden in the grid, a book's year is not a print date), is each section on /showcase/ the head of its own page, are only annotated puzzles shown, does every filter feature have a section named, explained and picked by its tag (or a stated reason it has none), and does no reader page link a puzzle's answer page?"),
    ("building and checking the site", "tools/test_puzzle_tag_badges.js", "does a tagged puzzle's title badge its tag, and does the picker's feature menu list exactly the puzzles with that tag, the double pangrams under pangram?"),
    ("building and checking the site", "tools/test_jigsaw.js", "does a jigsaw (tools/puzzle_tags.is_jigsaw) list its clues alphabetically with no numbers, and does picking one leave the grid unlit, so nothing says where an answer goes?"),
    ("building and checking the site", "tools/smoke_test.js", "the whole app driven headless against the real corpus"),
    ("building and checking the site", "tools/test_app_tab_pages.js", "holds the home-screen app's Puzzles and Stats tabs to full pages with their own #picker/#stats history entries, so the back gesture walks between tabs, while a browser tab keeps the old panels"),
    ("building and checking the site", "tools/test_phone_scroll.js", "drives a real headless Chromium as an iPhone home-screen app: the Puzzles list scrolls itself, never the page behind it after a puzzle visit, and touching rows paints no highlight"),
    ("building and checking the site", "tools/mobile_browser.js", "the iPhone-emulating headless Chromium (touch swipes, standalone display mode) the scroll test drives over the DevTools protocol"),
    ("building and checking the site", "tools/fake_dom.js", "the fake DOM that boots the real app.js under Node, shared by every harness"),
    ("building and checking the site", "tools/reindex.js", "rebuilds the puzzle manifest before a node harness reads it, through the same --reindex the site's build runs"),
    ("building and checking the site", "tools/e2e_analytics.py", "drives a real browser through a solve and checks every event lands in KV"),
    ("building and checking the site", "tools/wait_for_deploy.py", "blocks until Pages is serving the pushed commit, so nobody is told to reload early"),
    ("building and checking the site", "tools/last_deploy.py", "the commit the live site was last deployed from, read off the github-pages deployments (one gh call); pages.yml's scope job and build path diff against it, and pages-schedule.yml's 15-minute clock asks it whether master has moved (--moved) before it dispatches a build of the puzzle-only pushes"),
    ("building and checking the site", "tools/test_wait_for_deploy.py", "proves that check reads the live page before it calls a deploy failed, and finds its expected hashes in the assets rather than in an index.html the nightly has already unstamped"),
    ("building and checking the site", "tools/test_webpush.js", "runs the RFC 8291 test vector through sync/webpush.js, so the encryption is checked against something other than itself"),
    ("building and checking the site", "tools/test_push_hold.js", "runs the cron fan-out over a fake night, so a puzzle held until morning is proved to arrive exactly once"),
    ("building and checking the site", "tools/test_notify_race.js", "ticks two papers over a slow network, so a tick that lands during a save is proved to be kept"),
    ("building and checking the site", "tools/test_solve_clock.js", "walks away from a puzzle and comes back, so the time spent elsewhere is proved never to be counted as solving"),
    ("building and checking the site", "tools/test_save_grid.js", "a save loads only into the grid it was typed into, and a sync merge never unions two grids"),
    ("building and checking the site", "tools/test_paper_mode.js", "paper mode hides every right/wrong signal until \"I'm done\", then hands it all back"),
    ("building and checking the site", "tools/test_share_url.js", "picking a puzzle points the address bar at it, from whatever the bar said before; the picker's menus are still set when you come back to it; and ?p=<bare number> navigates to its puzzle's own address"),
    ("building and checking the site", "tools/test_unclued_squares.js", "a square only an unclued light covers can be revealed, and the picker asks for it"),
    ("building and checking the site", "tools/test_anagram_line.js", "the anagram ring stands its tiles in a line, in answer order, once a letter from the grid fixes one"),
    ("building and checking the site", "tools/test_free_wheel.js", "the free letter wheel: offered on every clue, costs no hint, shows what the solver types"),
    ("building and checking the site", "tools/test_free_elimination_blocks.js", "the building blocks rung is free when its piece is only the last unlit words and adds no new letters"),
    ("building and checking the site", "tools/ci_shards.js", "splits the test scripts across the workflow’s parallel jobs, so the suite takes as long as its slowest single script rather than all of them added up"),
    ("building and checking the site", "tools/code_checks.py", "the code lint CI runs: ruff's syntax and undefined-name rules, no `| grep -q` under pipefail, and the scratch-copy check (a test that copies a tools/ module copies what it imports)"),
    ("building and checking the site", "tools/test_ci_coverage.js", "checks every test in tools/ is run, in exactly one shard, by the workflow a later push cannot cancel, so no check is quietly optional"),
    ("building and checking the site", "tools/test_no_noqa.sh", "refuses a noqa lint suppression in any tracked Python file: fix what the rule flags; a broad catch or lazy import that is right says why in a plain comment"),
    ("building and checking the site", "tools/test_ci_cache_deps.js", "checks the smoke test's declared cache dependencies cover every file it reaches, so a cached pass is never served after one of them changes"),
    ("building and checking the site", "tools/qr_check.py", "decodes qr.js’s own output with a real decoder — a wrong QR code draws perfectly and simply never scans"),
    ("building and checking the site", "tools/tutorial.html", "source of the learn/ lesson"),
    ("building and checking the site", "tools/difficulty_page.html", "the prose of the difficulty/ page; every number in it is filled in at build time"),
    ("building and checking the site", "tools/og_card.html", "source and type for og.png, the site card, and every puzzle’s clue card"),
    ("building and checking the site", "tools/og_page_card.html", "source for og/page/<slug>.png, the card of every page that is not a puzzle"),
    ("building and checking the site", "tools/page_card.py", "fills og_page_card.html from a page’s title and description; build_seo_pages.head() links one for every page"),
    ("building and checking the site", "tools/test_og_tags.js", "every generated page carries a full, valid social card, and no non-puzzle page borrows the site card"),
    ("building and checking the site", "tools/test_clue_landing.js", "does a search visitor land on the clue they typed? landing.js must mark the clue Google's text fragment scrolled to (or a #12-across anchor) and put the solve-with-hints line under it, leave reloads, other referrers and readers who scrolled first alone, and report only names on sync/events.js's list"),
    ("building and checking the site", "tools/test_app_nav.js", "can a home-screen app user get back to their puzzle? Standalone, every page must carry the tab bar with its own section lit and a Puzzle tab that reopens the last puzzle, a page reached from the app or another page must offer a back link that is history.back(), and a browser tab must get none of it"),
    ("building and checking the site", "tools/test_difficulty_page.py", "can /difficulty/ describe a rating other than the one the badges show? It must refuse to build when its prose and difficulty.WEIGHTS name different components, quote the scorecard only while it matches today's weights, and leave no {{placeholder}} unfilled"),
    ("building and checking the site", "tools/progress.py", "per series and per day, how many puzzles are known, acquired, filed, solved and hinted, and how many are downloaded and still unread: the history /progress/ draws, read without touching the corpus"),
    ("building and checking the site", "tools/edition_backlog.py", "the read queue's size without planning it: per series, the editions, Listener pages and Trove articles on the data disk and how many no ledger row has read, in puzzles; progress_record.py records it nightly"),
    ("building and checking the site", "tools/progress_record.py", "writes that history: `record` nightly, and a one-off `backfill` from the files, the commit history and the saved coverage ledgers; the page build overlays today's filed, solved and hinted from its own index at every deploy"),
    ("building and checking the site", "tools/data/progress.json", "tools/progress.py's history, one day a line"),
    ("building and checking the site", "tools/data/progress_fetching.json", "where the Gale downloader is (paper, year, pages left), saved nightly by progress_record.py for the /progress queues line"),
    ("building and checking the site", "tools/test_progress.py", "does /progress/ date each phase, carry the ledger's counts to today, pace by days rather than points, and draw every chart?"),
    ("building and checking the site", "tools/test_series_hub.py", "does /puzzles/ describe each series without counting it? A series blurb with a count or puzzle number must be refused, the hub must not print a series' puzzle total, and each series with enough rated puzzles gets a difficulty strip whose median sits where its middle puzzle is"),
    ("building and checking the site", "tools/test_sitemaps.py", "do new puzzles get found fast? /sitemap.xml must be a sitemap index (the URL Search Console holds) over a small sitemap-recent.xml, carrying the last RECENT_DAYS of puzzles and every page that changes daily, and the archive parts holding the rest, each puzzle in exactly one. The homepage links every series page and each printing paper's newest puzzle, /puzzles/ links no puzzle; and a puzzle page pages Newer/Older within its own series and links the series' landing page"),
    ("building and checking the site", "tools/step_budgets.py", "holds every deploy step to its time budget: check-run fails the last step of pages.yml's build job (after the deploy) on a step over budget or unbudgeted; lint is the rule test_step_budgets.sh runs"),
    ("building and checking the site", "tools/test_step_budgets.sh", "every pages.yml step is named and budgeted, and a step reading the whole corpus names its cache, how it is incremental, or why it is neither"),
    ("building and checking the site", "tools/validate_scope.py", "what the deploy's validate job must check: the full check only when a change touches code the validator reaches (computed with code_reach) or a data file those modules name, else just the changed puzzle files"),
    ("building and checking the site", "tools/test_validate_scope.py", "does a puzzle edit or an unrelated tools/ edit stay incremental, a rule, table or workflow change force the full check, and the core-parallel full check print what the serial one does?"),
    ("building and checking the site", "tools/test_page_cache.py", "does the deploy keep last build's puzzle pages through a fetcher, test, doc or hub-page edit, and re-render them all when the page's own code or a table it reads changes?"),
    ("building and checking the site", "tools/indexnow.py", "tells IndexNow (Bing and the engines it feeds) which pages a deploy changed: hashes each staged page without its ?v= stamps against the last deploy's, and posts the difference once the deploy is live"),
    ("building and checking the site", "tools/renamed_ids.py", "every puzzle id a commit renamed, read from git history into tools/data/renamed_ids.json; --check-staged refuses a staged rename without its row, --stage adds the row"),
    ("building and checking the site", "tools/puzzle_rows.py", "the per-puzzle tables' rows follow their file: retire carries a renamed id's rows to its new id and discards a dropped one's; --check-staged refuses a staged deletion or rename that leaves rows, --check that every row names a file on disk"),
    ("building and checking the site", "tools/test_puzzle_rows.sh", "do a puzzle's table rows go where its file goes? retire discards and carries, --check-staged refuses a drop or rename leaving rows, durable.sh commits a drop with its rows gone, and every real row names a file"),
    ("building and checking the site", "tools/test_renamed_ids.sh", "does a renamed puzzle's old id keep resolving? A rename inside a commit that moves every file is still paired, a staged rename the map lacks is refused until --stage adds it, --check agrees with history, a chain lands on its last id, an old id a live puzzle holds and one whose puzzle was deleted get no page, and the page at an old id is canonical to the new one with a refresh indexnow.py never sends"),
    ("building and checking the site", "tools/test_indexnow.py", "does a deploy tell IndexNow only what changed? A page whose only difference is its ?v= stamps is unchanged, a redirect page is never sent, a cold cache sends the recent sitemap rather than the site, and the key file is served from the site root"),
    ("building and checking the site", "tools/test_date_numbers.py", "is a date-keyed puzzle number (Metro, the Canberra Times) named by its day? Their papers print no number, so the stored number is the print date, and formatting it as a number gave \"Cryptic 20,260,922 answers explained\". Renders every numberIsDate series' page and refuses a separated number in the title, heading, description or archive row"),

    ("syncing between devices and telling them about new puzzles, with no login and no accounts",
     "sync/worker.js", "the Cloudflare Worker: merges saves and events in KV, and pushes each new puzzle to whoever asked for its paper"),
    ("syncing between devices and telling them about new puzzles, with no login and no accounts",
     "sync/merge.js", "union rules, so two devices combine instead of asking which one wins"),
    ("syncing between devices and telling them about new puzzles, with no login and no accounts",
     "sync/events.js", "the exhaustive list of milestones the app and the Worker may report"),
    ("syncing between devices and telling them about new puzzles, with no login and no accounts",
     "sync/wrangler.toml", "the Worker’s deploy config, KV binding, VAPID public key and the cron that watches for new puzzles"),
    ("syncing between devices and telling them about new puzzles, with no login and no accounts",
     "sync/webpush.js", "web push encryption and sender identity (RFC 8291, RFC 8292), written out so the Worker needs no dependency"),
    ("syncing between devices and telling them about new puzzles, with no login and no accounts",
     "sync/notify.js", "what a notification is called and whether this device wants it yet — the two decisions the fan-out makes before it encrypts anything"),
    ("syncing between devices and telling them about new puzzles, with no login and no accounts",
     "sw.js", "the service worker: delivers pushes and keeps the app shell and opened or saved puzzles for offline use"),

    ("scheduling", "tools/daily_update.sh", "the nightly as a queue of units: a tick every ten minutes chooses the puzzles to annotate under the usage gates and starts what is due; `unit <key>` is one fetcher, blog chain, filer, check, graded miss or puzzle's annotation, run in a tree of its own and committing and pushing its own work"),
    ("scheduling", "tools/unit_queue.py", "scheduled work as small units: a tick starts each due unit detached, each with its own lock, time limit, ledger row and tree slot; cadence, retry with backoff, `after` and `trigger` dependencies and per-class caps; `status` and `plan` show it"),
    ("scheduling", "tools/daily_units.py", "the nightly's units for tools/unit_queue.py: their cadences, limits and dependencies, the day's backlog budget, the backfills that rerun until drained, the job name in a unit's commit subject (`job`), and the puzzles a refetch gave a key (`keyed`)"),
    ("scheduling", "tools/test_unit_queue.sh", "drives a fake queue through tools/unit_queue.py: a tick returns at once, an overrun is killed and alerted, a failure waits out its retry, a class cap and a running unit hold starts back, `after` and `trigger` order them"),
    ("scheduling", "tools/test_daily_units.py", "pins which daily unit kinds get the generated files rebuilt as their tree is set up (daily_units.py GENERATED): a unit that reads none of them skips the whole-corpus pass"),
    ("scheduling", "tools/nightly_worktree.sh", "sourced first: re-execs a scheduled job in its own worktree, never the editor’s"),
    ("scheduling", "tools/durable.sh", "sourced by a long job that files into git: commits and pushes what it filed every few minutes, and on SIGTERM ends the job and commits first; nightly_worktree.sh's CT_SALVAGE_PATHS pushes what a SIGKILL left"),
    ("scheduling", "tools/unstage_unparsable.sh", "sourced by durable.sh and nightly_worktree.sh: unstages a .json a kill cut off, and a puzzle puzzle_integrity.py --refused names, held in the tree and named, so no commit carries one and one bad puzzle strands no checkpoint"),
    ("scheduling", "tools/commit_puzzles.sh", "commits each staged puzzle or clues-only file on its own (`File <id>`, a rename's two paths together), so no writer batches a run's puzzles into one commit; sourced by durable.sh and nightly_worktree.sh, run by the daily update, the pre-reset backfill, extend_archive.py and sweep_series.py"),
    ("scheduling", "tools/json_merge.py", "git merge driver: the keyed JSON data files several writers append to merge per key, so a rebase never stops on a ledger row"),
    ("scheduling", "tools/claude_path.sh", "sourced: finds the `claude` CLI wherever this machine keeps it, SDK-bundled copy included"),
    ("scheduling", "tools/alert.sh", "posts a run’s failures to Discord instead of burying them in a log"),
    ("scheduling", "tools/claude_session.sh", "sourced: session ids, so a run that dies is resumed rather than paid for twice"),
    ("scheduling", "tools/weekly_usage.py", "how much of a Claude quota window is spent, and when it resets"),
    ("scheduling", "tools/prereset_backfill.sh", "burns the tail of the weekly quota on backfills, ungated"),
    ("scheduling", "tools/puzzle_worker.sh", "sourced by the nightly and the burn: everything done to one puzzle — the annotation, solving the puzzle cold first in that same run when it has no key, the fill checked again before it ships, the validation-fix rerun, the per-puzzle commit and push"),
    ("scheduling", "tools/test_puzzle_worker.sh", "holds the solve and annotate prompts, the validate-commit-push of a puzzle, to that one file, and every cold solve to the run that annotates it"),
    ("scheduling", "household-plugins/<name>/plugin.toml", "when and where the household bridge runs each scheduled job (daily, prereset, books, annotate audit, corpus queue, archive coverage, Gale inbox, VLM health); symlinked from ~/.config/household/plugins/<name>, then `tools/plugins.py --write` in the household repo"),
    ("scheduling", "tools/test_annotate_retry.sh", "drives that resume, and a cold solve's run, with a fake CLI, so it is not first tried on a night it is needed"),
    ("scheduling", "tools/test_apply_refusal.py", "a refused annotation write names clue ids and no traceback, so the model does not map entries[N] by hand"),
    ("scheduling", "tools/annotate_postmortem.py", "why an annotation run died, read off its transcript — sent WITH the alert, so the report is not a pointer to a log"),
    ("scheduling", "tools/test_annotate_postmortem.sh", "checks that post-mortem reports the right shape and that the nightly actually sends it"),
    ("scheduling", "tools/failed_inputs.py", "records a failed annotation or cold solve with a hash of its inputs, so it is skipped until they change"),
    ("scheduling", "tools/test_failed_inputs.sh", "drives that ledger out of daily_update.sh itself: a failed puzzle is skipped, a transient failure is not, a changed input brings it back"),
    ("scheduling", "tools/test_solve_queue_clues.sh", "drives the cold-solve queue out of daily_update.sh against made-up clue counts, so a grid with nothing to read is never bought a model run"),
    ("scheduling", "tools/test_push_conflict.sh","proves the nightly push rebuilds a generated file the remote also rebuilt, and refuses to resolve anything else"),
    ("scheduling", "tools/test_push_race.sh", "a push that loses the shared ref-lock race to another worktree is retried; any other failure is not"),
    ("scheduling", "tools/prereset_plan.py", "how many annotations the burn runs at once, and the order it takes the queue in"),
    ("scheduling", "tools/indicator_cover.py", "puts first the backlog puzzles whose blog-named indicators no annotation of ours links yet on /indicators/: a greedy set cover weighted by each indicator's clue count, re-planned at every pool checkpoint through prereset_plan.py --cover-first"),
    ("scheduling", "tools/backlog_burndown.py", "the annotation backlog over time, rebuilt from git history, and how long the rest will take at that pace"),
    ("scheduling", "tools/test_prereset_paths.sh", "resolves the bridge path the burn's alerts build at runtime, instead of matching the text of the line that builds it"),
    ("scheduling", "tools/test_prereset_plan.sh", "runs the burn planner's self-test: the bridge's measured spend coming off the need, the idle cores capping the width, and the queue order"),
    ("scheduling", "tools/test_prereset_pool.sh", "drives the burn's rolling pool with a stub run: never past the width, a freed slot refilled at once, launches spaced, a width change taking effect"),
    ("scheduling", "tools/discard_clue_rows.py", "the burn's discard: drops a puzzle's SOURCE_CLUE_WRONG rows its reverted file does not show"),
    ("scheduling", "tools/test_discard_clue_rows.sh", "a discarded run takes its SOURCE_CLUE_WRONG rows with it, and the table agrees with the file"),
    ("scheduling", "tools/own_rows.py", "a burn puzzle's commit stages its own rows of fetch_puzzle.py's SOURCE_* tables and no sibling's; its discard puts them back"),
    ("scheduling", "tools/test_own_rows.sh", "two puzzles in flight: one commits only its own rows, the other's discard leaves the tree clean"),
    ("scheduling", "tools/test_alert_claimed.sh", "runs a real failing run past alert.sh, so the catch-all cannot report a failure somebody already alerted on a second time"),

    ("finding out whether any of it is working", "tools/reports.py", "reads and clears the bad-hint reports solvers sent in"),
    ("finding out whether any of it is working", "tools/report_fix_prompt.md", "the prompt the nightly job follows to work that queue — a report is evidence to check, not an instruction to carry out"),
    ("finding out whether any of it is working", "tools/rung_report.py", "where on the ladder solvers give up, from synced hintsShown data"),
    ("finding out whether any of it is working", "tools/usage_report.py", "counts the solving milestones in KV, with no way to identify who did what"),
    ("finding out whether any of it is working", "tools/ga_report.py", "the same milestones as Google Analytics counts them, to see what a blocker hides"),
    ("finding out whether any of it is working", "tools/ga_wire_check.py", "watches the wire to confirm GA hits actually leave the browser"),
    ("finding out whether any of it is working", "tools/difficulty.py", "rates a puzzle from what its own file contains, banded against the corpus"),
    ("finding out whether any of it is working", "tools/snitch_report.py", "the difficulty index and each component against the SNITCH, raw and minus its weekday mean, by date third, and per clue against the clues commenters found hard; run nightly"),
    ("finding out whether any of it is working", "tools/difficulty_check.py", "the shipped difficulty rating's held-out scorecard against the SNITCH, and the gentle-series margin; run nightly"),
    ("finding out whether any of it is working", "tools/data/difficulty_check.json", "tools/difficulty_check.py's output, which the difficulty/ page quotes only while it matches the current weights and baseline"),
    ("finding out whether any of it is working", "tools/data/snitch_report.txt", "tools/snitch_report.py's output, rewritten nightly, so its git history shows each number moving as ratings and annotations arrive"),
    ("finding out whether any of it is working", "tools/craft_report.py", "reports the four things about how a puzzle is set that the fifteensquared threads argue about and our fields can actually measure — separately, because the composite it replaced turned out to be thread size"),
    ("finding out whether any of it is working", "tools/favourites_survey.py", "joins the favourite clues commenters name back to our own clues, so craft_report.py has something outside this project to be tested against"),
    ("finding out whether any of it is working", "tools/suggest_demand.py", "asks Google autocomplete which puzzle numbers people search for, for the puzzles no page of ours ranks for yet"),
    ("finding out whether any of it is working", "tools/turn_cost.py", "how many turns an annotation session takes, from the transcripts — logged nightly so the figure can’t go stale unnoticed"),
    ("finding out whether any of it is working", "tools/annotate_audit.py", "ranks what annotation runs spend turns on — first-check failures by check, refused tool calls, cost and turn trend — from the transcripts; daily, and wakes the room with one fix target, rotating past items woken in the last 7 days"),
    ("finding out whether any of it is working", "tools/annotate_ledger.py", "the burn's own cost meter: each checkpoint appends a row (sessions, $/clue, turns/clue, top causes) to ~/.cache/annotate_cost_ledger.jsonl and queues one quiet wake to the room when $/clue drifts up or a new cause is #1"),
    ("finding out whether any of it is working", "tools/security_alert_watch.py", "once an hour from the burn: lists open GitHub code-scanning, dependabot and secret-scanning alerts and queues one quiet wake to the room for each alert not seen before"),
    ("finding out whether any of it is working", "tools/test_security_alert_watch.py", "tests tools/security_alert_watch.py with a fake gh: new alert wakes once, repeat does not, a 404 source is skipped"),
    ("finding out whether any of it is working", "tools/test_annotate_ledger.py", "tests tools/annotate_ledger.py: fake ledger rows give wake and no-wake decisions (regression, new top cause, cooldown, target)"),
    ("finding out whether any of it is working", "tools/recover_fp_drafts.py", "dry run: for clues an annotate session rewrote after a validator false positive, replays the first rejected draft through today's validator and buckets it against the committed wordplay — writes nothing to puzzles"),
    ("finding out whether any of it is working", "tools/annotate_audit.sh","the scheduled entry: runs the audit from a worktree at origin/master"),
    ("finding out whether any of it is working", "tools/test_annotate_audit.py", "tests tools/annotate_audit.py: rule naming from the validator's AST, and that each run picks one fix target, rotating down the ranking on cooldown"),
    ("finding out whether any of it is working", "tools/make_hint_packets.js", "blind solve-packets, to grade a hint by whether it gets a solver unstuck"),
    ("finding out whether any of it is working", "tools/grade_clues.py", "blind A/B/C/D packets of our clues against real setters’ for the same answers"),
    ("finding out whether any of it is working", "tools/author_trial.py", "clue-writing trial: an isolated author writes five candidates per answer, a separate run picks one, grade_clues.py judges the picks"),
    ("finding out whether any of it is working", "tools/author_trial_author.md", "author_trial.py's author prompt: five candidate clues for one answer"),
    ("finding out whether any of it is working", "tools/author_trial_select.md", "author_trial.py's selector prompt: pick one clue per answer"),
    ("finding out whether any of it is working", "tools/surface_judge.md", "author_trial.py's clue judge: is each clue a sentence a native speaker would say or write, does it lean on nothing a general solver would look up, and does one word mislead"),
    ("finding out whether any of it is working", "tools/test_surface_gate.py", "proves author_trial.py refuses a candidate only when both clue-judge calls do, and, where claude is on PATH, that the judge refuses \"Hacks are on the stouts\" and the nerazzurri INTER and passes A001"),
    ("finding out whether any of it is working", "tools/grade_clues_judge.sh", "runs the blind judges over one round of grade_clues.py packets"),
    ("finding out whether any of it is working", "tools/grade_clues_judge.md", "the judge prompt grade_clues_judge.sh sends: rubric, then packets"),
    ("finding out whether any of it is working", "tools/score_grading.py", "joins the blind scores back to provenance: the ours-vs-human head-to-head"),
    ("finding out whether any of it is working", "tools/favourite_grading.py", "blind matched pairs of a clue commenters named as a favourite against one from the same puzzle they did not, scored on the five rubric axes; the run finished null, so nothing downstream reads the scores"),
    ("finding out whether any of it is working", "tools/favourite_grading.sh", "grades those packets one claude -p per batch, skipping any batch whose score file already parses"),
    ("finding out whether any of it is working", "tools/favourite_grading_prompt.md", "what the judge is told each axis means"),
    ("finding out whether any of it is working", "tools/ctc_transcripts.py", "reads YouTube solve transcripts (Cracking the Cryptic, then every channel in its CHANNELS table, each tagged with its solver's skill), finds each praised or disliked clue, ties it to our annotated copy, and counts device and feature lift against the same puzzles; times when each clue is read and solved, and tests our per-clue difficulty ingredients against it; checks our parses against how the solvers explain each clue; classifies what unlocked each hard solve and scores the hint ladder's rung order against it; --channel all compares our difficulty and the unlocks across solver skill"),
    ("finding out whether any of it is working", "tools/ctc_reasons_prompt.md", "what the judge is told when naming why a solver reacted to a clue"),
    ("finding out whether any of it is working", "tools/compare_mc.py", "word-count and shape comparison of our hints against Minute Cryptic’s"),

    ("tables everything else reads", "tools/data/ctc_moments.json", "every reaction ctc_transcripts.py found: video, puzzle, trigger words, a minute of transcript, and the clue it was tied to"),
    ("tables everything else reads", "tools/data/ctc_solve_times.json", "per clue of each timed Cracking the Cryptic solve video: when it was read and solved, seconds since the previous solve, solve rank 0-1 within the video, and a stuck flag"),
    ("tables everything else reads", "tools/data/ctc_parse_check.json", "per annotated clue CtC solved on video: agree, disagree or unknown for its definition, type, anagram fodder and short pieces against what the solver said explaining it, with the words that disagreed; a summary by field and type on top"),
    ("tables everything else reads", "tools/data/ninas.json", "tools/ninas.py's output: per puzzle, the hidden message a blog points out, where it runs in our grid and the post; puzzle_tags reads it for the nina tag"),
    ("tables everything else reads", "tools/data/ctc_unstick.json", "per stuck or long-waited clue CtC solved on video: what the solver said in the 20 seconds before the solve that unlocked it (definition, indicator, device, short piece, crossing letters, other sense) and the ladder rungs that show it; a summary by clue type against quick solves, with every rung order scored"),
    ("tables everything else reads", "tools/data/ctc_hint_check.json", "per annotated clue CtC solved on video: each hint rung we show beside what the solver said explaining the same clue, and whether the two agree; a summary on top"),
    ("tables everything else reads", "tools/data/yt_solvers/", "the same moments, solve times, parse check and unstick tables for each other solve channel, as <slug>_<kind>.json, plus skill_check.json (our per-clue difficulty against each channel's waits, pooled by solver skill, and the solvers against each other) and unstick_by_skill.json (what unlocked hard solves at each skill level)"),
    ("tables everything else reads", "tools/data/ctc_reasons.json", "the judge's verdict, reasons and the solver's own words for each reacted-to clue"),
    ("tables everything else reads", "tools/series.py", "the one table of facts about each series: publisher, naming, URL shape"),
    ("fetching", "tools/fold_reprints.py", "folds each held Globe and Mail file into the Times Quick it reprints: its grid, clues and annotations under timesquick-N, dated off the timesforthetimes blog and checked against the blog's answers, shrinking tools/data/reprints_pending.json as it goes"),
    ("tables everything else reads", "tools/data/renamed_ids.json", "every puzzle id renamed, {old id: new id}, one line per id and merged per key (tools/renamed_ids.py); build_seo_pages.py writes a redirect page at each old id no live puzzle holds"),
    ("tables everything else reads", "tools/data/bare_number_urls.json", "the 222 numbers /puzzles/<number>/ was a real page at before ids carried their series; build_seo_pages.py writes a redirect stub only at these"),
    ("tables everything else reads", "tools/data/book_twins.json", "{held book id: newspaper id}: tools/book_twins.py's table, written by the write path when it refuses a newspaper copy of a held book file"),
    ("tables everything else reads", "tools/data/reprints_pending.json", "the reprint files held before tools/reprints.py's rule, still to fold into their originals; puzzle_integrity.py's REPRINT check forgives these alone, and the list only shrinks"),
    ("tables everything else reads", "tools/book_twins.py", "the newspaper id of each held book file a filer tried to file a copy of: fetch_puzzle.check_not_copy refuses the copy and keeps the book, and corroborate.georgeho reads the book under that id, so the blog post cross-checks it"),
    ("tables everything else reads", "tools/reprints.py", "a reprint is filed as its original: the reprinting paper's number and print date go on the original as source.reprintedIn, and puzzle_integrity.py refuses a reprint file (tools/data/reprints_pending.json lists the held ones still to fold)"),
    ("tables everything else reads", "tools/kv.py", "the one helper for reaching the sync KV namespace through wrangler"),
    ("tables everything else reads", "tools/vote_tally_backfill.py", "rebuilds each puzzle's `t:` vote tally, which GET /v reads, from the raw `v:` vote keys"),
    ("", "docs/LAYOUT.md", "this page: every tracked file and what it is for, generated by tools/build_readme.py"),
    ("", "docs/AI_SOLVING.md", "how the AI solves and hints the puzzles: the models by role, how the procedure evolved, the current pipeline, its shortcomings and future work"),
    ("", "docs/ARCHIVE_COVERAGE.md", "the goal (archive years as full as modern ones) and how the coverage tracker, the job queue, the nightly wake and the coverage ledger keep it moving"),
    ("", "docs/FEATURES.md", "how the hint ladder behaves, and the site's other features"),
    ("", "docs/PUZZLE_FORMAT.md", "the puzzle file format, the annotation rules the validator enforces, and the provenance blocks"),
    ("", "docs/findings_triage.md", "the annotation backlog by finding class (a fixable by code, b needs a model, c validator false positive), and the plan for clearing it"),
    ("", "docs/CLUE_SHAPES.md","every whole-clue wordplay shape in the corpus, counted and judged: which shapes make sense as a cryptic mechanism and which are redundant, mislabelled or unverified (generated by tools/clue_shapes.py)"),
    ("", "docs/ADDING_PUZZLES.md", "running the site locally, fetching and annotating puzzles, checking your work, and the generated regions of the docs"),
    ("", "docs/NIGHTLY.md", "the scheduled jobs: the unit queue, the quota split (generated), durability, cold solving, scheduling and the claude credential"),

    ("tables everything else reads", "tools/data/README.md", "what in tools/data is committed, what is fetched, and under what licence"),
    ("tables everything else reads", "tools/data/deploy_budgets.json", "seconds each pages.yml step may take, and how each corpus-wide step skips unchanged work; read by step_budgets.py"),
    ("tables everything else reads", "tools/data/clue_joints.json", "link words and reversal-axis words published clues use, measured by build_clue_joints.py and read by the authoring checks in validate_annotations.py"),
    ("tables everything else reads", "tools/data/fill_floors.json", "grid_fill.py's clueability and familiarity floors per entry length, the 25th percentile of published answers, measured by build_fill_floors.py"),
    ("tables everything else reads", "tools/data/lexicons/abbreviations.json", "clue word -> letters, every abbreviation English Wiktionary or Wikipedia's crossword abbreviation list gives (CC BY-SA), written by fetch_abbreviations.py; build_abbreviations.table() holds the ones clues use"),
    ("tables everything else reads", "tools/data/lexicons/abbreviations_corpus.json", "letters -> clue word -> counts: the abbreviations our annotations attest in >=10 puzzles, >=4 series, >=5 setters (D for deserted, US for american); table() holds them all. Written by build_corpus_abbreviations.py"),
    ("tables everything else reads", "tools/build_corpus_abbreviations.py", "counts every leaf whose note calls it an abbreviation over puzzles/ (read only) and writes lexicons/abbreviations_corpus.json; --check"),
    ("tables everything else reads", "tools/test_corpus_abbreviations.py", "build_corpus_abbreviations keeps a widely used pair, drops one setter's habit and a thin one, and the committed file holds deserted D"),
    ("tables everything else reads", "tools/fetch_abbreviations.py", "streams kaikki.org's Wiktionary abbreviation, initialism, acronym, contraction and symbol extracts, and Wikipedia's Crossword abbreviations list, into lexicons/abbreviations.json"),
    ("tables everything else reads", "tools/test_fetch_abbreviations.py", "fetch_abbreviations.senses() reads what a wiktextract entry says an abbreviation stands for, and nothing it only mentions; list_senses() reads the crossword list's readings and skips the synonyms it mentions"),
    ("tables everything else reads", "tools/data/lexicons/blocks.json", "clue word -> letters -> clues, off the blogs and our annotations (tools/letter_facts.py --lexicons); the abbreviations/ page lists its short conventions"),
    ("tables everything else reads", "tools/data/cmudict.txt.gz", "the CMU Pronouncing Dictionary, stress dropped; tools/letter_facts.py hears a homophone block by it"),
    ("tables everything else reads", "tools/data/lexicons/indicators.json", "type -> indicator -> clues, from the same sources; the indicators/ page is built from it"),
    ("tables everything else reads", "tools/data/indicator_roles.json", "indicator word -> op type -> uses, counted over the annotation trees by build_indicator_roles.py; validate_annotations.wrong_role_indicators flags an indicator the corpus files under one other op and almost never under the op it sits on"),
    ("tables everything else reads", "tools/data/indicator_kinds.json", "indicator word -> kind of letter selection (first, last, middle, outer, alternate, nth) or deletion (head, tail, heart, outer, named) -> uses, counted by build_indicator_roles.py; the /indicators/ page splits those two types by it"),
    ("annotating", "tools/build_indicator_roles.py", "counts, for every indicator word used 20+ times, how many times each op type (and each selection or deletion kind) carries it across the published annotations, and writes tools/data/indicator_roles.json and indicator_kinds.json"),
    ("tables everything else reads", "tools/data/unclueable.json", "words rejected as answers, with reasons; grid_fill.py vetoes them"),
    ("tables everything else reads", "tools/data/corroboration_ledger.json", "every disagreement tools/corroborate.py settled or could not, and every field it filled: the puzzle, the field, each candidate with its sources, the winner and the rule that picked it"),
    ("tables everything else reads", "tools/data/blog_answers.json", "blog answers (Times, bigdave44) settled from the clue's wordplay; times_grids.py applies them before rebuilding"),
    ("tables everything else reads", "tools/data/difficulty_baseline.json", "the frozen distribution difficulty.py normalises against"),
    ("tables everything else reads", "tools/data/lexicon.tsv", "192,738 British-cryptic words by frequency rank; difficulty.py scores rarity off it"),
    ("tables everything else reads", "tools/data/grading_rubric.md", "the five axes a blind judge scores a clue on"),
    ("tables everything else reads", "tools/data/books.json", "the shelf: one row per physical book, with the archive.org scan it was read from, the volume its cover prints, the label a reader sees and a book_index that is never reused \u2014 tools/series.py reads it, and tools/fetch_puzzle.py --reindex copies the browser\u2019s half into puzzles/index.json for app.js, so no other file holds a copy"),
    ("tables everything else reads", "tools/data/book_candidates.json", "which archive.org crossword books are worth acquiring in full, measured one short loan at a time; a measurement, not a permanent fact"),
    ("tables everything else reads", "tools/data/book_acquisition_plan.json", "the crossword books still to acquire, in the order to take them: archive.org identifier, series and volume, the puzzle count and clean fraction measured off a sample, and the evidence for every volume number \u2014 including the ones marked INVENTED"),
    ("tables everything else reads", "tools/data/book_pins.json", "books to acquire before the ranking's order, which tools/book_queue.py reads and the ranking tool never rewrites"),
    ("tables everything else reads", "tools/data/book_reads.json", "each archive.org book's last read by tools/acquire_book.py (date, puzzles found and filed); tools/book_queue.py re-reads a book whose read predates its REREAD_BEFORE"),
    ("tables everything else reads", "tools/data/penguin5_control.json", "the ten-puzzle Penguin volume 5 control tools/test_acquire_book.py gates on: light specs, black-square patterns and a digest of the parser's output, and none of the book's words"),
    ("tables everything else reads", "tools/data/sample_fill_11.json", "the worked 11x11 fill tools/AUTHORING.md walks through"),
    ("tables everything else reads", "tools/data/authored_A001_clues.json", "the hand-written clues for that fill"),
    ("tables everything else reads", "tools/data/puzzle.schema.json", "the puzzle file's shape as a JSON Schema (2020-12): every key, its type, and the closed lists it draws from"),
    ("tables everything else reads", "tools/data/clue_types.json", "the clue types and the nine families they fall in, with the labels and blurbs the app and the tools show; the seven commoner families are the type picker's buttons, and a rarer one names the `picker` family it folds into"),
    ("tables everything else reads", "tools/data/blog_facts/", "inputs.sha256, the digest of what the blog facts were written from; the facts themselves are one sidecar a puzzle, puzzles/<series>/<year>/<id>.blog (tools/blog_store.py), the blog facts tools/blog_facts.py read off the write-ups, each clue in the annotation's keys and shapes ($defs/blogFacts in puzzle.schema.json), with the site's hints and the validator's definition and block checks reading them"),
    ("tables everything else reads", "tools/data/snitch.json", "the SNITCH's rating of every Times and Sunday Times puzzle it has rated, written nightly by tools/fetch_snitch.py; tools/difficulty.py scores against it and shows each band's range"),
    ("tables everything else reads", "tools/fixtures/snitch_archive.html", "a saved copy of the SNITCH's archive page, the fixture tools/test_fetch_snitch.sh reads"),
    ("tables everything else reads", "tools/data/penguin_partial_fills/", "answers from a Penguin-book solve that stopped short; the puzzle itself is filed unsolved for the nightly cold solve to finish"),
    ("tables everything else reads", "tools/data/diagnosed_misses.json", "every graded miss the nightly diagnosis has looked at, with its verdict and what it changed, so none is diagnosed twice"),
    ("tables everything else reads", "tools/data/blind_misses.json", "which entries a blind solve got wrong once the paper’s key or a solver’s write-up arrived, the one blank check_every_clue_is_annotated will not fail on"),
    ("tables everything else reads", "tools/data/favourite_grading/key.json", "which packet label is which pair, and which side of it was voted for: the only thing that un-blinds a packet"),
    ("tables everything else reads", "tools/data/favourite_grading/packets/", "one blind batch of clues per file, labels only"),
    ("tables everything else reads", "tools/data/favourite_grading/scores/", "the judge’s five scores per label, same batch numbering as the packets"),
    ("tables everything else reads", "tools/suggest_demand.json", "the last autocomplete reading, advisory only: nothing downstream sorts on it"),
    ("tables everything else reads", "tools/backfill_provenance.py", "write `source` and `solutions` blocks into every puzzle that hasn't got them"),
    ("tables everything else reads", "tools/provenance.py", "where a puzzle came from \u2014 and, the part that matters, where its ANSWERS came from"),
    ("tables everything else reads", "tools/test_provenance.py", "does provenance actually REFUSE a puzzle that lies about where it came from?"),
    ("tables everything else reads", "tools/test_puzzle_source.py", "holds where a puzzle came from to `source`, whose answers it holds to `solutions` and who wrote its hints to `annotatedBy`: a write lands all three and nothing that repeats them, the detail keys decide the origin, a key printed later replaces a model fill and remembers it, and provenance.check refuses detail that does not back its origin"),
    ("tables everything else reads", "tools/rank_book_candidates.py", "judge each candidate archive.org crossword book from one short loan and a sample of its leaves, rank the ones worth acquiring in full, and record why each refusal is one"),
    ("tables everything else reads", "tools/acquire_books.sh", "the archive.org books as a queue of units: a tick every ten minutes; `unit borrow:<id>` takes one loan and fetches its text, `unit read:<id>` reads one book from disk"),
    ("tables everything else reads", "tools/book_units.py", "the books' units for tools/unit_queue.py: the next loan (one at a time, an hour after a refusal, three an hour), each due book's read, two at once"),
    ("tables everything else reads", "tools/book_queue.py", "which registered archive.org books have not been read yet, best first"),
    ("tables everything else reads", "tools/test_book_queue.sh", "does tools/book_queue.py still offer the right book to tools/acquire_books.sh?"),
    ("tables everything else reads", "tools/test_plan_off_samba.py", "does planning answer from manifests and the pickle rather than scanning the media disk over samba?"),
    ("tables everything else reads", "tools/test_build_readme.sh", "does tools/build_readme.py still read the header of every file it is asked about?"),
    ("tables everything else reads", "tools/test_public_docs.py", "do the public docs name hosts by role (the OCR host, the GPU host, the data disk) rather than by a local path, home directory, LAN address or whose machine it is?"),
    ("tables everything else reads", "tools/test_doc_staleness.py", "do the hand-written docs, outside generated regions, stay free of live counts (\"about N puzzles\") and snapshot words (\"currently\", \"as of\") that go stale, with dated history exempt?"),
    ("tables everything else reads", "tools/test_downloads.py", "does every fetcher keep its downloads under tools/downloads.py's root: fails on a home path, ~/.cache folder or container path spelled anywhere else in tools/"),
    ("tables everything else reads", "tools/test_doc_pointers.py", "does every backticked path and function in the prose docs still exist?"),
    ("tables everything else reads", "tools/test_prereset_lock.sh", "does the pre-reset backfill still take over a lock nobody is holding?"),
    ("tables everything else reads", "tools/test_nightly_worktree.sh", "which tree does a scheduled job end up running in? checked by running one"),
    ("tables everything else reads", "tools/test_durable.sh", "does a long job keep what it filed when left running, sent SIGTERM, or SIGKILLed and restarted, without filing anything twice; does a checkpoint hold back a puzzle puzzle_integrity.py --refused names and push the rest; does corpus_queue.py stop let the pass commit; does every long scheduled job use tools/durable.sh, committing all of puzzles/ so a file a write moved between folders is deleted on origin too?"),
    ("tables everything else reads", "tools/data/source_answer_wrong.json", "answers a source's key got wrong, keyed puzzle id/entry id: what it serves, the corrected letters, the evidence; read as fetch_puzzle.SOURCE_ANSWER_WRONG, merged per key"),
    ("tables everything else reads", "tools/data/source_clue_wrong.json", "clues a source serves or OCRs wrong, keyed puzzle id/entry id: how the served text opens, the clue as printed, the evidence; read as fetch_puzzle.SOURCE_CLUE_WRONG, merged per key"),
    ("tables everything else reads", "tools/data/blog_disagree.json", "clues a run checked against its blog's reading and kept ours, keyed puzzle id/entry id: the fields (definition, type, blocks) and one sentence why ours stands; filed by annotate_check's blogDisagree or blog_compare.py --keep; the validator's blog checks and blog_compare.py skip them; merged per key"),
    ("tables everything else reads", "tools/data/annotate_ab.json", "the 2026-10-12 A/B of the burn's annotate model: Opus medium, Opus low and Sonnet on the same 20 queued puzzles; tokens, check retries, validation and two blind judges' rankings per arm, read when the burn's ANNOTATE_MODEL/ANNOTATE_EFFORT is reconsidered"),
    ("tables everything else reads", "tools/data/blog_compare.json", "our annotations against the blogs' marked facts (tools/blog_compare.py): unhinted clues the blogs cover, disagreement rates per series, examples, and the puzzles due a re-check"),
    ("tables everything else reads", "tools/data/setter_error.json", "clues the setter printed wrong, keyed puzzle id/entry id: the anagram fodder (words the clue prints, or a block's gives), the letters it should give (the answer or the part the anagram supplies), the evidence; validate_annotations.setter_error_problems refuses any other row; validate_annotations.SETTER_ERROR lets that one mismatch pass with a walkthrough saying so; merged per key"),
    ("tables everything else reads", "tools/test_source_tables_merge.sh", "do two writers adding different rows to the source-correction tables merge without a conflict?"),
    ("tables everything else reads", "tools/test_json_merge.sh", "do the keyed JSON data files merge per key in a real rebase?"),
    ("tables everything else reads", "tools/test_refresh_window.py", "does refresh_unsolved ever stop asking for an answer that is never coming?"),
    ("tables everything else reads", "tools/test_privateeye_dates.py", "does tools/fetch_privateeye.py read the issue off every title shape the archive ships, and take the Eye's Christmas cover date as it prints it?"),
    ("tables everything else reads", "tools/test_clue_repair_one_reading.py", "does tools/clue_repair.py split a clue the OCR ran into the one before it only at a number the lists skip, and put misnumbered clues in order, for every filer that parses clue lists?"),
    ("tables everything else reads", "tools/test_privateeye_missing_size.py", "does tools/clue_repair.fill_missing_sizes size a plain light whose count the OCR lost from the answer the next issue printed?"),
    ("tables everything else reads", "tools/test_fetch_puzzle_misfiled.py", "does fetch_puzzle.convert() refuse a mis-filed Guardian page and accept a re-published one?"),
    ("tables everything else reads", "scratch/snitch_tune.py", "collect every SNITCH-rated puzzle's raw components into scratch/snitch_rows.json, for snitch_weights.py"),
    ("tables everything else reads", "scratch/snitch_weights.py", "held-out refit of difficulty.WEIGHTS against the SNITCH, split by date"),
    ("tables everything else reads", "tools/fetch_snitch.py", "fetch the SNITCH's ratings of The Times and Sunday Times cryptics into tools/data/snitch.json, keyed by our puzzle id"),
    ("tables everything else reads", "tools/test_fetch_snitch.sh", "does tools/fetch_snitch.py read the SNITCH's week table into the right puzzle ids, and drop the cells that are not a rating of that puzzle?"),
    ("tables everything else reads", "tools/test_comment_blend.py", "does tools/difficulty.py blend() move only puzzles with enough stated solve times, re-rate one as its comments arrive, and keep each series' mean and spread?"),
    ("tables everything else reads", "tools/blog_comment_difficulty.py", "which clues human solvers found hard, read off Times for the Times comments"),
    ("tables everything else reads", "tools/data/blog_comment_difficulty.json", "per Times puzzle, the comment count, the median solve time its commenters state, and per clue how many comments name the answer, flag it hard, and call it their last one in"),
    ("tables everything else reads", "scratch/snitch_stage4.py", "the SNITCH adoption harness: each candidate component held out by date on the annotated and fresh sets"),
    ("tables everything else reads", "scratch/comment_blend.py", "the blog-comment blend measured held out: clue index, blend and comments alone, by date third"),
    ("tables everything else reads", "tools/build_wordnet.py", "writes tools/data/wordnet.json.gz, the slice of WordNet difficulty.py's definition_unrelated reads"),
    ("tables everything else reads", "tools/data/wordnet.json.gz", "WordNet synsets and hypernyms for lexicon words and corpus definitions; committed so scoring needs no nltk"),
    ("tables everything else reads", "tools/push_puzzle_commit.sh", "publish one local commit to origin/master without touching the working tree"),
    ("tables everything else reads", "tools/test_push_puzzle_commit.sh", "does tools/push_puzzle_commit.sh publish a commit while another process keeps writing into the same working tree, where fetch + rebase --autostash + push fails? The burn (tools/prereset_backfill.sh) commits and pushes each puzzle while the rest of its wave is still writing into that tree"),
    ("tables everything else reads", "tools/clobber_guard.py", "refuses a commit made from a stale tree: most of its changed paths hold an older ancestor's content, not its parent's (456d5a0397 reverted 61 files); run by the push tools"),
    ("tables everything else reads", "tools/test_clobber_guard.py", "a stale-tree commit is refused and names the older commit; an ordinary edit, a small deletion, a Revert or Restore subject and CLOBBER_OK=1 pass"),
    ("tables everything else reads", "tools/push_checked.sh", "push local commits to origin/master after tools/clobber_guard.py clears each; for code a session commits itself"),
    ("tables everything else reads", "tools/publish_fetched.sh", "run a fetch, then commit and publish every puzzle file it wrote at once, so none is left untracked to block the burn's rebase"),
    ("tables everything else reads", "tools/test_publish_fetched.sh", "can a puzzle the burn fetched ever block its sync's rebase? Checked against a real origin, with origin filing the same path first and without"),
    ("tables everything else reads", "tools/test_link_words.py", "does tools/validate_annotations.py refuse a link word that app.js would place on top of an indicator, wholly or in part, and pass one with a free copy? The placement is app.js placedFragments(), which would otherwise show a bought indicator half-erased"),
    ("tables everything else reads", "tools/test_abbreviations_rank.py", "/abbreviations/ ranks every list by clue count and shows the count: the most common list, the families and the members of each, and each A-to-Z row's readings. A reading no clue uses keeps its place, last, with no count"),
    ("tables everything else reads", "tools/test_clue_number_residue.py", "does puzzle_integrity refuse a blog clue that opens with what is left of the blog's clue number, and pass the clues that only look like one?"),
    ("tables everything else reads", "tools/cross_validate.py", "check our puzzles against another copy of the same puzzle, class by class; `all --model` grades each model-solved file against every cached copy that answers it"),
    ("tables everything else reads", "tools/test_cross_validate.py", "does tools/cross_validate.py name each way two copies of a puzzle differ?"),
    ("tables everything else reads", "tools/test_clue_counts.py", "does a clue that carries its own letter count, or a stray letter, get refused?"),
    ("tables everything else reads", "tools/trove_solution_ocr.py", "read a Canberra Times puzzle's answers off the paper's printed solution grid"),
    ("fetching", "tools/solution_cells.py", "harvest labelled cell glyphs off printed Times solution grids and train trove_solution_ocr's cell classifier on them"),
    ("fetching", "tools/data/solution_cells.npz", "the cell classifier's weights (float16, 1024-384-128-26) that read a Times solution grid's letters again beside RapidOCR; trove_solution_ocr.CELL_MODEL_SHA pins it, tools/solution_cells.py trains it"),
    ("tables everything else reads", "tools/file_georgeho_puzzles.py", "file the puzzles only georgeho's ODbL clue database holds into puzzles/"),
    ("tables everything else reads", "tools/test_file_georgeho_puzzles.py", "does tools/file_georgeho_puzzles.py read georgeho's rows into the record the grid rebuild and file_blog_puzzles.build take?"),
    ("tables everything else reads", "tools/fetch_archive_org_editions.py", "fetch archive.org newspaper editions' OCR, word positions and crossword page scans"),
    ("tables everything else reads", "tools/test_fetch_archive_org_editions.py", "fetch_archive_org_editions.py with urlopen stubbed: 500s retried within an edition's ITEM_SECONDS, none past it, so one bad edition cannot hold the queue; an edition whose text shows no daily crossword title also fetches its last leaf and the leaves its item's other editions print it on"),
    ("fetching", "tools/file_archive_org_puzzles.py", "files the daily Times, FT, Guardian and Telegraph cryptics in the editions fetch_archive_org_editions.py cached as times-<No>, ftcryptic-<No>, cryptic-<No> and telegraph-<No> (--paper): clues voted on by archive.org's OCR, RapidOCR's two recognisers, Tesseract, the GPU host's VLM and the Canberra Times reprint's readings (the Times pages saved by hand from Gale, staged by gale_inbox.py, and the Telegraph, FT, Independent and Sunday Times pages gale_fetch.py lays out, read the same way), the grid read off the scan or rebuilt, answers off the next edition's solution grid; every reading kept for cross_validate.py's archiveorg adapter; names the Times puzzle each canberra file reprints"),
    ("fetching", "tools/test_file_archive_org_puzzles.py", "does tools/file_archive_org_puzzles.py find the Times cryptic's title and not its neighbours', read the clue columns in order, keep only the clues both readings agree on, and match a Canberra reprint only when it is one?"),
    ("fetching", "tools/measure_archive_org_ocr.py", "measure how many clue words and marks file_archive_org_puzzles.py misreads, against the hand transcriptions in tools/data/archive_org_ocr_gold.json"),
    ("fetching", "tools/data/archive_org_ocr_gold.json", "Times, Listener, Jumbo, FT, Guardian and Telegraph clues transcribed by hand off archive.org's scans, each edition marked tune or held out (heldout, ft-heldout, ...); the misread rate is reported on the held-out ones and never gates filing"),
    ("fetching", "tools/build_clue_compounds.py", "count how the corpus's clues print two-word compounds: hyphenated or closed"),
    ("fetching", "tools/data/answer_breaks.json", "the word breaks other puzzles print for each answer, and the answers printed both ways with neither settled; fetch_puzzle.py restores lost breaks from it (repair_fetched.py --write-breaks)"),
    ("fetching", "tools/data/word_break_flags.json", "archive.org puzzles whose word breaks the repair could not settle, left for a read of the print; the archive.org queue never skips an edition holding one (repair_fetched.py)"),
    ("fetching", "tools/data/clue_compounds.tsv", "how often the corpus's clues print each two-word compound hyphenated and closed (build_clue_compounds.py)"),
    ("fetching", "tools/build_clue_lm.py", "count the words and word pairs of every clue in the corpus, and its answers"),
    ("fetching", "tools/data/clue_lm.tsv.gz", "how often the corpus's clues print each word and word pair, and its answers each word; settles OCR readings that differ (build_clue_lm.py)"),
    ("fetching", "tools/data/archive_org_tess.traineddata", "Tesseract's English LSTM fine-tuned on Times clue lines; the archive.org filer's Tesseract reader (train_archive_org_tesseract.py)"),
    ("fetching", "tools/train_archive_org_tesseract.py", "fine-tune Tesseract's English LSTM on Times clue lines, for the archive.org filer"),
    ("fetching", "tools/archive_org_listener.py", "read the Listener crosswords in archive.org's scans of The Times' Saturday editions"),
    ("fetching", "tools/test_archive_org_listener.py", "does tools/archive_org_listener.py find the Listener's own heading (not the coupon's), split the clue columns at DOWN (not the title's \"8 DOWN\"), carry across clues that run into the second column, read a list past a line that does not parse, read an uncounted list a clue a line past a stray count, and blank a clue no two readings agree on or that runs on?"),
    ("fetching", "tools/archive_org_jumbo.py", "file the Times Jumbo cryptics in archive.org's scans of The Times' Saturday editions"),
    ("fetching", "tools/test_archive_org_jumbo.py", "does tools/archive_org_jumbo.py take the Jumbo's number from the prize text (the banner's is cut short), read \"SOLUTION TO JUMBO 17 8\" as 178, look for an unheaded solution in the edition two weeks on, blank a light whose count is short of it, keep the clue columns left of the Times Two's, and match a solution grid by its blocks when its middle prints grey?"),
    ("fetching", "tools/test_difficulty_barred.py", "is a barred grid's checking rated against barred grids, not blocked ones?"),
    ("fetching", "tools/test_difficulty_one_scale.py", "is every paper scored by the same function on the same scale? Two identical puzzles under different series ids must measure identically, and no function that measures or rates a puzzle may name a series"),
    ("fetching", "tools/test_no_doubled_paper.py", "does any series' page say the same word twice running (\"Listener Listener\")? Renders a crawlable page for every series in tools/series.py and refuses a repeated adjacent word in the title, heading, description or series name; and each title leads with the paper and the number as searched (\"Guardian Cryptic 30111 answers\"), no thousands comma"),
    ("fetching", "tools/test_strip_over.py", "does file_archive_org_puzzles.py find the clue strip printed between the title and the grid on 1945-49 Gale Times pages, split it into columns and read only its own words into them?"),
    ("fetching", "tools/test_vlm_reader.py", "does tools/vlm_reader.py stay out of the way when the GPU host's VLM does not answer, cache what it asks, crop each clue column alone, and does file_archive_org_puzzles.py fill a blank clue with its reading and re-read an edition once it answers?"),
    ("fetching", "tools/vlm_reader.py", "a vision-language model as one more reader of scanned clue columns"),
    ("fetching", "tools/vlm_column_prompt.md", "what the VLM reader is told when transcribing a clue column verbatim"),
    ("fetching", "tools/vlm_pick_prompt.md", "what the VLM reader is told when the readers disagree on one clue"),
    ("fetching", "tools/test_drop_derived_keys.py", "a clue written with wp and a derived key (assembly, type) is applied with the key dropped, not refused"),
    ("fetching", "tools/test_annotate_drafts.py", "the annotate run's view carries the mechanical hidden-word drafts for the run to complete"),
    ("fetching", "tools/test_annotate_partial.py","a puzzle that has hints and lacks some is annotated only where it lacks them"),
    ("fetching", "tools/test_resolve_task_puzzle.py", "a worker run's bare number resolves to its own puzzle when papers share the number, and is still an error otherwise"),
    ("fetching", "tools/test_annotate_filed_rows.py", "an _ann entry's printedClue, setterError and answerTypo are filed as their source-table rows by annotate_check (answerTypo's letters into the grid, refused against a crossing), and the run's view carries source.retrievedFrom and the grid"),
    ("fetching", "tools/errata.py", "a paper's erratum is a fix to the puzzle, not a preamble"),
    ("fetching", "tools/test_errata.py", "a paper's erratum in the preamble fixes its clue and leaves the preamble; the instructions beside it stay, and the write gate refuses one left behind"),
    ("fetching", "tools/boilerplate.py", "a preamble's publishing boilerplate is not something a solver needs"),
    ("fetching", "tools/test_clue_page_instructions.py", "a 2005-08 Guardian prize's special instructions are read off the old-site clue page its note links to and filed with the note"),
    ("fetching", "tools/test_boilerplate.py", "a paper's publishing boilerplate in the preamble goes; a puzzle's instructions, tributes and kept errata stay; the write gate refuses it"),
    ("fetching", "tools/ocr_clues.py", "the clue-text OCR every scan filer shares: the readers, the vote, the check"),
    ("fetching", "tools/test_clue_record_shift.py", "does every Guardian clue record land on the light its number names?"),
    ("fetching", "tools/test_shared_continuation.py", "does a light whose clue names two leaders end both answers?"),
    ("fetching", "tools/ocr_full_pass.sh", "the one standing corpus job: read every archive.org edition, Gale page and Trove article the scan filers find due (never read, inputs changed, read without the VLM that now answers, read before REREAD_BEFORE) and the re-reads annotation asked for, to the end: the editions through tools/edition_queue.py's per-edition units, the Trove articles' and Gale Listener pages' reads and the archive.org and Trove fetches units of that queue too, then stop; the only OCR runner, its queue starting the editions just laid out (a fetch, a Gale page) ahead of everything planned, within a minute or two"),
    ("fetching", "tools/edition_queue.py", "the archive.org and Gale editions as a queue of small units: one edition's scan or read each, in its own forked process with its own time limit and edition lock, appending its own ledger row; Gale pages saved by hand first, then never read and annotation's asks, then inputs moved, then REREAD_BEFORE; the Trove articles' reads (one unit an article, a pool of their own); with --fetch archive.org / trove, one unit an edition, article or article's zones fetched too, each source in a pool of its own (Trove paced to 1 req/s across units); planned again every minute; `plan` prints what is due by rank"),
    ("fetching", "tools/hot_reload.py", "hot reload for the long-running queues (tools/edition_queue.py): re-exec on new tools/ code or SIGHUP"),
    ("fetching", "tools/edition_commit.py", "an archive.org or Gale edition read whose request the edition queue made (file_archive_org_puzzles.brief, from its loaded ledger, scans and corpus): the unit only sends it to the OCR host, waits, writes what the OCR host decided and appends the edition's row, loading none of the reader's code; the shared filing pieces (filer_path, the row, the inputs' stray-clue part)"),
    ("fetching", "tools/test_edition_commit.py", "does a prepared read write what the OCR host decided and append its row, loading no tree module past its MODULES, hand an undecided title, a lost OCR host or an edition read since to the whole unit, and keep ocr_remote's code hash only for the commit it was made from?"),
    ("fetching", "tools/test_edition_queue.py", "does the edition queue append rows (the last standing, a half-written line skipped), keep one unit per edition, take Gale pages saved by hand first, read only after the scans its solution needs, kill a slow unit at its own limit without holding up the rest, say what a capped run left, pass a TERM on, run a batch filer beside, run fetch units in pools of their own (a 429 shrinking one, an outage stopping it), read Trove articles and Listener pages as units, hand a slice's running units to the next slice, and pace Trove across processes?"),
    ("fetching", "tools/code_reach.py", "a cache key for only the code a cached result runs: the definitions its roots reach, across this repo's modules, a class's methods only when called, comments and docstrings left out (the archive.org scan key, the Listener grid and letter caches)"),
    ("fetching", "tools/scan_queue.py", "the read queue the scan filers share: the append-only ledgers (the last row a source standing), per-source locks, and the re-reads annotation asks of them"),
    ("fetching", "tools/archive_coverage.py", "per series and year: editions printed, scanned on archive.org and filed, and every unfiled edition's reason off the filer's ledger, recoverable classes first (docs/ARCHIVE_COVERAGE.md)"),
    ("fetching", "tools/canberra_london_numbers.py", "the London Times number of each cached Canberra Times reprint (to Jan 1982): matched by clue words, or bracketed between two matched days with as many days as numbers; file_trove_puzzles.py stamps reprintOf from it"),
    ("fetching", "tools/test_canberra_london_numbers.py", "does canberra_london_numbers.py number a reprint only by a clue match or an exact bracket, refuse a span whose counts disagree and a re-run out of order, and date a bracket only when the London days agree?"),
    ("fetching", "tools/corpus_queue.py", "keeps the full pass running: one corpus job at a time (pid file, ledger locks), starts ocr_full_pass.sh whenever none runs (hourly, and from gale_inbox.py sync when a fresh page waits) and straight after a pass that fetched, wakes the room on a stall, holds it and tells the room after DEAD_LAUNCHES (2) in a row end unfinished having read and fetched nothing"),
    ("fetching", "tools/corpus_queue.sh", "the scheduled entry point for corpus_queue.py tick, from a worktree"),
    ("fetching", "tools/coverage.py", "the coverage ledger: every series' puzzles that exist (print dates, numbers back to issue one, Trove articles, book positions), the ones filed, and each missing puzzle in one (source, cause) bucket naming the module that owns its fix, read off the pipelines' own fields; daily it saves, diffs against the last run and queues the top recoverable buckets and any regression for the room"),
    ("fetching", "tools/coverage.sh", "the scheduled entry point for coverage.py daily, from a worktree"),
    ("fetching", "tools/test_coverage.py", "does every ledger bucket name a module that exists, every filer refusal have a bucket, every missing puzzle land in exactly one bucket, and the daily run queue a note only when it carries work?"),
    ("fetching", "tools/test_corpus_queue.py", "does corpus_queue.py take a recycled pid for a dead job, see a filer's ledger lock, kill all of a dead job's session, start the full pass with no edition list, hold it after two dead launches (unfinished, nothing read or fetched), chain the next pass on after one that fetched, and refuse any edition-list job; does archive_coverage.py count the Times' printed days and class an unfiled edition by its ledger row?"),
    ("fetching", "tools/test_scan_reread.py", "does an annotation that meets a misread clue on an OCR'd puzzle queue its scan for a re-read, once per reading of its clues, does the burn leave the puzzle alone until the re-read lands, and take it back after?"),
    ("fetching", "tools/test_scan_queue.py", "does tools/scan_queue.py read the never-read first, never send the queue back to the start, keep N sources in flight, stop at its deadline, and let only one run hold a ledger; do both scan filers read again, once the VLM answers, the sources read while it was down, mid-run outages included?"),
    ("fetching", "tools/test_ann_normalize.py", "what apply_annotations.normalize computes, so the run need not write it"),
    ("fetching", "tools/budget.py", "a unit's soft deadline (CT_DEADLINE, 70% of its limit): long passes that keep their progress stop there cleanly, backlog left, and the next tick resumes them, so no unit is killed at its limit"),
    ("fetching", "tools/row_cache.py", "a per-file pass over the corpus that parses only the files it has not seen: rows stored by code key, path and git blob under the git common dir (reindex's index rows, difficulty's history and clue rows)"),
    ("fetching", "tools/page_cache.py", "last build's puzzle pages, reused when their own inputs, the stamped assets they link and the tracked code and data are unmoved (build_seo_pages; the deploy restores the store with actions/cache)"),
    ("fetching", "tools/clue_index.py", "which puzzle files share clues: normalised clue text -> puzzle ids"),
    ("fetching", "tools/test_placeholder_clues.py", "a puzzle whose clues are pointers at clues printed elsewhere has no clues"),
    ("fetching", "tools/sweep_series.py", "probe every number of a Guardian series between two bounds, file what is served"),
    ("fetching", "tools/ocr_gpu.py", "one shared RapidOCR server on the GPU host that its OCR sessions hand reads to, each reading on its own CPU when the server is busy or away; yields while the host is busy and keeps 4 GB of VRAM free"),
    ("fetching", "tools/ocr_remote.py", "the clue OCR, whole scan editions, image-PDF page searches, Gale page matches, Listener page reads and Trove grid searches run on the OCR host over ssh; what runs here instead shares LOCAL_SLOTS"),
    ("fetching", "tools/test_sync_skip_published.sh", "the burn's sync with runs in flight: publishes or drops each local commit, brings origin's code in, keeps a run's uncommitted edit, and refuses whole over a file origin changed"),
    ("fetching", "tools/scan_crop.py", "the printed clues of an archive.org scan, cut out for the annotator"),
    ("fetching", "tools/test_scan_crop.py", "does the annotator get the printed clues of a puzzle filed off a scan?"),
    ("fetching", "tools/test_ocr_remote.py", "does tools/ocr_remote.py compare every reader model a read can load, send back an edition whose read on the OCR host opened a file it was not sent, give the same grids from a search run there, and cap reads here at LOCAL_SLOTS?"),
    ("fetching", "tools/gale_inbox.py", "every 1930-2019 Times edition with no puzzle filed (wanted), fetched from Gale's Times Digital Archive by gale_fetch.py: lays out each fetched page as a GaleTimes<year>UKEnglish edition for file_archive_org_puzzles.py --paper gale (lay_out_fetched), and the other papers' Gale archives' unfiled dates (OTHERS, other_wanted: Telegraph to 2000, FT 1966-2010, Independent 1986-2016, Sunday Times to 2006, TLS 1992-2014) as Gale<Paper><year>UKEnglish editions file_archive_org_puzzles.py reads (the Telegraph and FT in those papers' runs, --paper galeindependent, galesundaytimes and galetls), publishes the Times progress page (nothing to click), and starts the full pass when a page is laid out while none runs (kick)"),
    ("fetching", "tools/gale_inbox.sh", "the scheduled entry point for gale_inbox.py sync, every minute, from a worktree"),
    ("fetching", "tools/gale_listener.py", "the Listener crosswords of 1930-91, read from the pages gale_fetch.py downloads from Gale's Listener Historical Archive: what to fetch (wanted: every printed puzzle not filed or read, from the Listener Team's year index, numbers and dates only, and each one's solution report page, earliest first), each downloaded page saved for the reader (lay_out_fetched), and each saved page matched to its puzzle (file name, Gale citation title or date, page title) and to the past puzzles whose solution report it prints, its clue lists read once (a ledger keyed by file hash) with ocr_clues' readers and archive_org_listener's vote into a clues-only reading, then file_gale_listener.py run, each page a unit of the full pass's edition queue (read_unit, its ledger rows appended), read on the OCR host but for its whole-page Tesseract read (ocr_remote's listener_read) and filed here"),
    ("fetching", "tools/gale_docs.py", "Gale's document and PDF Download link for a date (portal session, the month's issues, the issue's contents), cached, misses too, in ~/.cache/gale_inbox/docs.json: the Times, Listener (its puzzles and their solution reports) and other papers' rows looked up by gale_fetch.py as it goes, 2 s apart"),
    ("fetching", "tools/gale_fetch.py", "downloads every wanted Times edition itself, in next-up order, then once fewer than a plan's worth of Times rows are left the Listener's puzzles and solution report pages (gale_listener.wanted, saved for gale_listener's reader), then the other papers' (gale_inbox.OTHERS), at a hand's pace (8-22 s apart, at most 15 in 3 minutes) and lays each out at once as its date's edition (no inbox, match or set-aside), the PDF kept on the data disk; counts downloads per window across sessions and papers (the browser's included; no cap until the first refusal), retries a logged-out session at once, records each Gale refusal with its count and pace and probes every 30 min to time the reset (~/.cache/gale_inbox/limits.json), learning the cap and window from them; stops and wakes the room at a captcha, a wrong PDF, a refusal no probe gets past, or repeated errors (Paul, 2026-10-11)"),
    ("fetching", "tools/gale_fetch.sh", "gale_fetch.py's long run from its own worktree, launched through track-job --restart"),
    ("fetching", "tools/test_gale_fetch.py", "on a fake clock: does gale_fetch keep its pace, wait out the window at its cap (counting downloads made elsewhere), take a page a fresh session gets past for a logout, record a refusal (login page, HTML, non-PDF, 429, in a fresh session too) and the 30-min probes until one works, stop at a captcha, short PDF, a refusal no probe gets past or repeated errors (riding out one), skip what was got, wait a bounded number of times, open another paper's session through its own portal link and count its downloads in the one window, plan the Times first and the Listener before the other papers, and look up and save a Listener report from its own issue?"),
    ("fetching", "tools/test_gale_docs.py", "with Gale stood in: is the day's crossword found in an issue's contents (not the Concise or a competition), its Download link's citation naming its document, a Listener report found in the weeks after its puzzle, and a miss looked up again only when an older matcher made it?"),
    ("fetching", "tools/test_gale_listener.py", "is a saved Listener page matched by its name, citation title, citation date (across a line break) or title, not by a browser's \"(1)\" copy suffix, a \"Competition No.\" or a week with no crossword; is a \"Report on Crossword No. N\" page kept as N's solution; are its lists read in column order, the 1930s lists by their numbers in bands across two columns with a heading unread or DOWN first, a heading centred over its column, a number set wide of its words, read in old-style letters (\"I.\", \"Io.\") or run into them, a list broken by a gap or run on into the next after a heading's space, no report's prose, a clue a line when uncounted, a clue's number lost (put back when the gap counts it), a line under a short one or a footnote no run-on, a grid's numbers beside a list and a footnote's dagger read as a letter; does a page say the page its clues or diagram are on; is each file read once, a read on the OCR host the read here (its OCR and grids kept here), and does wanted() ask for each puzzle not filed or read and each missing solution report?"),
    ("fetching", "tools/listener_grid.py", "reads a 1930s Listener grid off a scanned Gale page: every grid on the page found as a lattice of long rules (prose, column rules and boxes are not), rows x cols, blocks by ink fill, bars by rule width against the thin rule (a row mostly blocks is a band whose edges are rules), numbered by reconstruct_grid.light_cells; match() checks the numbers against gale_listener's clue lists; fit() sets each unsure bar so the numbering agrees with the cells' printed numbers (read with the shared clue readers, only the rules at a corner's edges painted out) and says whether it is exact, barring 2-cell runs shut when the page leaves them unnumbered; no symmetry assumed"),
    ("fetching", "tools/test_listener_grid.py", "does listener_grid read a drawn, slightly turned, non-square barred grid with a block back exactly, among prose, a column rule and a boxed advert, and number it as light_cells does, a grid with a row of blocks too; do printed numbers put a faint bar back, a corner keep a number's strokes, and a grid without numbers on its 2-cell runs fit with them barred shut, and a number read in two cells the run could each hold kept in neither?"),
    ("fetching", "tools/test_gale_inbox.py", "is a page gale_fetch.py downloaded laid out as its date's edition, another paper's under its own item, read first by the full pass (fresh_unread, kick); does next_up keep its order and wanted() stop at 2014; does the Times progress page count what is wanted, fetched, read and not on Gale, with nothing to click?"),
    ("fetching", "tools/test_canberra_reprint_vote.py", "does a Canberra Times reprint vote on the archive.org scan's clues like any other reading, only for the London number canberra_london_numbers.py maps it to and only in the Times series, and does a reprint downloaded or read later make that edition due again, and no other?"),
    ("fetching", "tools/test_fold_reprints.py", "does fold_reprints.rekeyer rename a folded id both as a whole JSON string and as the lead of one, and leave a longer number, a mid-string mention and other ids alone?"),
    ("fetching", "tools/test_punctuation.py", "does tools/punctuation.py flag only the marks a reader made and mend only the certain ones, offsets moved, and do the OCR write gate, the write path, strayed(), corrects() and the vote use it?"),
    ("fetching", "tools/test_ocr_vote_checks.py", "does the clue vote file each word, count, capital and hyphen as the readings print them, and settle a word they all misread on the known word their slips point to; does a reading that lost the clue stay out of its vote, words run together part, and a figure run onto a word go?"),
    ("fetching", "tools/test_prereset_index_lock.sh", "do the pool's concurrent runs commit only their own puzzle?"),
    ("fetching", "tools/test_anagram_ring.py", "a clue typed anagram gets the anagram ring: app.js deals the whole-answer anagram's fodder, else the longest part-anagram's, and the validator warns (ratcheted as assembly.anagrams) when a clue typed anagram names no fodder"),
    ("fetching", "tools/test_discard_alert.sh", "does a rejected annotation alert only when the puzzle is parked?"),
    ("fetching", "tools/test_annotation_loss.sh", "does the annotation loss check stay quiet on a blank solved twice with no parse, and still fail on one never retried?"),
    ("fetching", "tools/check_shapes.js", "the corpus-wide half of tools/smoke_test.js's shape() checks"),
    ("fetching", "tools/ninas.py", "unannounced messages in finished grids that blogs point out, each checked against our grid"),
    ("fetching", "tools/ci_cache.js", "the per-puzzle result cache that lets every push check the whole corpus"),
    ("fetching", "tools/desktop_busy.py", "whether the OCR host is busy with its own foreground work, so the work we send there yields"),
    ("fetching", "tools/desktop_probe.ps1", "the OCR host's foreground processes, 3D load (the VLM's own left out), OCR sessions and free memory, as JSON, for tools/desktop_busy.py"),
    ("fetching", "tools/test_desktop_busy.py", "does OCR and VLM work on the OCR host yield while the host is busy, and resume after?"),
    ("fetching", "tools/vlm_health.py", "wake the room when the GPU host's VLM has been down for DOWN_FOR while the host was not busy"),
    ("fetching", "tools/vlm_health.sh", "the scheduled entry point for tools/vlm_health.py (the cryptic-vlm-health plugin), run from a worktree at origin/master (tools/nightly_worktree.sh)."),
    ("fetching", "tools/vlm_health_probe.ps1", "what tools/vlm_health.py reports when the GPU host's VLM is down, as one JSON line. Its busy flag uses the host's own guard script's rule, because that guard is what takes llama-swap down"),
    ("fetching", "tools/file_gale_listener.py", "files the 1930s Listeners saved from Gale into puzzles/listener/ (run by gale_listener.read_unit): gale_listener's clue reading joined with the page's grid when listener_grid's fit is exact and its lights are the clue list's (one unsure side flipped where that alone makes them so), filed unsolved for the nightly solve, through the shared validators only when every clue reads true; the later report's filled grid, found by its bars, read for answers (a cell settled by sure reads or by the letter both its lights' whole reads share, an entry with an unsettled cell left unanswered) that are never filed: the copy with them goes to cross_validate.py's listenerreport adapter, where a solve it disagrees with is a lead; each puzzle's verdict, or what it lacks, in filed.json"),
    ("fetching", "tools/test_file_gale_listener.py", "does the Gale Listener filer put back a faint bar the numbering hides, file the puzzle unsolved through the validators (with no report too), find the report by its bars, settle a cell from its crossings and leave a cell nothing settles unanswered, keep the report's answers as listenerreport's copy and never in the file, and say what a puzzle short of a step lacks (with the page its page sends the grid to), and are a blocked grid's blocks no bars?"),
    ("fetching", "tools/test_listener_letters.py", "does trove_solution_ocr.read_grid_letters read the letters of a drawn, filled Listener report grid back through listener_grid's lattice?"),
    ("fetching", "tools/test_ann_layout.py", "annotate_check's fix-ups rewrite only the values they change in tools/_ann_<ID>.json, so the run's next Edit of text it wrote still matches"),
    ("fetching", "tools/commit_subject.py", "a commit subject naming the puzzles staged, for jobs that commit as they go"),
    ("fetching", "tools/mem_gate.py", "memory gate: a queue starts a unit only while available RAM stays above a floor"),
    ("fetching", "tools/test_hidden_message.js", "a solved clue shows its hidden letter, and the message fills in under the grid"),
    ("fetching", "tools/test_blocks_link_word.py", "when a clue's blocks are short by exactly the letters of a word filed under linkWords, that word is fodder, and the warning says the edit to make"),
    ("fetching", "tools/test_blocks_surplus.py", "when a clue's blocks give too many letters and none too few, the warning names the single-block edits that take exactly the surplus away"),
    ("fetching", "tools/test_move.py", "a letter move is one wordplay step: move<dropping>([England]ALBION, [ball]O) gives ALBINO, renders back as written, and views as clue type move with the fodder and the moved letter as its blocks"),
    ("fetching", "tools/test_reprints.js", "a paper that reprints another's puzzle is listed, and every way in opens the original; a book, Globe and Mail or Canberra Times puzzle renamed to the puzzle it reprints stays listed and counted in its series at its own number"),
    ("fetching", "tools/deleted_paths.py", "the commit that last deleted a path, read from a cache"),
    ("fetching", "tools/test_deleted_paths.py", "does deleted_paths.last_deletion() give what `git log -1 --diff-filter=D -- <path>` gives, as HEAD moves forward, back, sideways and is rewritten?"),
    ("fetching", "tools/test_row_cache.py", "does row_cache re-parse exactly the files whose row could change (an edited file, a changed dependency, new code), and is every data file a cached row reads in its key?"),
    ("fetching", "tools/test_row_cache_stale.py", "row_cache.cached_map(stale_ok=True): a code change keeps the rows of unchanged files until fresh ones are made, never-made rows come first, and a deadline mid-build returns a complete answer with backlog marked, so puzzle_integrity's 55k-row rebuild finishes across runs"),
    ("fetching", "tools/test_clue_index.py", "does StoredClueIndex answer exactly what ClueIndex.build() answers, as files are added, edited and deleted, and when its store is corrupt?"),
    ("fetching", "tools/test_worker_resume.sh", "does a run stopped from outside resume its own conversation, with its edits back when that is honest and a note saying so when not?"),
    ("fetching", "tools/test_session_ids.sh", "does every `claude -p` in tools/ name its conversation, so a run stopped from outside is resumed rather than bought again?"),
    ("fetching", "tools/load_watch.py", "wake the room when the machine is overloaded, with who is using the CPU"),
    ("fetching", "tools/test_load_watch.py", "does load_watch.py rank CPU by job, charge exited children to their parent, and wake only on two high runs in a row, once an hour unless the top consumer changes?"),
    ("fetching", "tools/dir_cache.py", "what a planner re-reads every minute off a slow disk, kept until it moves"),
    ("fetching", "tools/test_trove_articles_index.py", "does tools/trove_solution_ocr.py's _articles keep what it read in a file, reread only an article whose files changed, and return the same list warm?"),
    ("fetching", "tools/await_preamble.py", "hold back a puzzle that cannot be explained without the preamble we lack"),
    ("fetching", "tools/test_reconstruct_grid_cli.sh", "tools/reconstruct_grid.py's command line: several --lights run as separate searches (on the OCR host under OCR_REMOTE; here, with it unset, in-process), and --words reaches the search"),
    ("fetching", "tools/track_prereset.sh", "register the pre-reset burn as a status lane for the cryptic room. The label names the job only: which meter it is pacing (weekly or five-hour) changes with `prereset_plan.py --five-hour`, so the lane's text is the last line of .prereset.log, which states the mode, never a label typed here"),
    ("fetching", "tools/test_writeup_keyed.py", "a blank light on a puzzle whose answer key is a blog's write-up is never offered for a solve"),
    ("fetching", "tools/test_post_index.sh", "does a single-puzzle write find its fifteensquared posts off the local post index, opening only the posts it lacks, and do corroborate, blog_post and other_setters find what a full read found?"),
    ("fetching", "tools/test_fifteensquared_index.py", "do the fifteensquared readers find a category's posts off the index, without opening every cached post, and does tools/ft_puzzles.py's budget count its parse?"),
    ("fetching", "tools/collapse_clue_spaces.py", "one-shot migration (2026-10-11): cut each run of spaces in held clue text"),
    ("fetching", "tools/test_block_confirm.js", "a building block that would cost a hint takes two taps; a free one takes one"),
    ("fetching", "tools/mend_clue_punctuation.py", "one-shot migration (2026-10-11): punctuation's certain mends in held book clue text, the faults left listed"),
    ("fetching", "tools/resolve_promotion_conflict.py", "settle the one conflict a promotion races into, for tools/push_puzzle_commit.sh"),
    ("fetching", "tools/leading_quote.py", "an OCR'd clue opens with a quote mark only when it is a quotation"),
    ("fetching", "tools/test_leading_quote.py", "an OCR'd clue opens with a quote only when it is a quotation (tools/leading_quote.py): a stray unclosed quote and a clue number leaked after one go, an attributed quotation that lost its closing quote is closed, a matched quotation, an elision and a dropped h stand, offsets move with the text, a publisher's clue is never touched, both OCR readers finish a clue through it, and the write gate refuses what it would still mend"),
    ("fetching", "tools/gale_http.py", "the Chrome-like browsing of Gale and its portal, shared by gale_fetch.py"),
    ("fetching", "tools/test_gale_page_cap.py", "is a Gale page laid out within gale_inbox.MAX_PAGE_PIXELS however small the grid it is scaled by (a crossword-centenary article's printed grid scaled the 2013-12-17 page to 363 MP), is a leaf staged before that cap shrunk to fit (its edition's input_hash moved, so its scan and read come due) and left alone the second time, and does a scan unit past its memory ceiling (edition_queue.UNIT_MEMORY_MB, RLIMIT_AS) end a failure naming it?"),
    ("fetching", "tools/test_ctc_title_date.py", "does a CtC video title's date pin its puzzle when the year is short or absent?"),
    ("fetching", "tools/fetch_nation.py", "the Nation's weekly cryptic, from the magazine's own article pages"),
    ("fetching", "tools/test_genius_puzzles.py", "does tools/genius_puzzles.py read an old Guardian article page's text without markup, keep the Genius's printed pair of counts, and does the write gate refuse a tag's remnant in any string?"),
    ("fetching", "tools/test_light_spec_shared_light.py", "is a light two linked groups share one light, not two?"),
    ("fetching", "tools/test_linked_group_sums.py", "does the grid search use a linked answer's printed total?"),
    ("fetching", "tools/test_self_clued.py", "can a light with a clue of its own also finish another linked answer (cryptic-21893's THERE and PUBLIC in BATTLE HYMN OF THE REPUBLIC)? the holder's selfClued through the schema, groups.py, the shape checks and the length check"),
    ("fetching", "tools/test_shared_leader.py", "can one light start two linked answers (Genius 209's IVOR)? the entry's alsoLeads through the schema, groups.py, the shape checks, the annotate run and the Genius parser"),
    ("fetching", "tools/jigsaw_fit.py", "fit a jigsaw's answers into the one blocked grid they interlock in"),
    ("fetching", "tools/test_jigsaw_fit.py", "does a jigsaw held as its clues alone become a filed puzzle once answered?"),
    ("fetching", "tools/unit_more.py", "a unit's backlog_left(): it stopped with work left, so tools/unit_queue.py starts it again next tick; its own module so a unit loads none of the queue runner"),
    ("fetching", "tools/test_blog_clues_only.py", "is a blog post whose answers fit no grid held as its clues alone, and does the solve's fill file it on the grid those answers cross in?"),
    ("fetching", "tools/test_session_model.sh", "does apply_annotations find who wrote the hints when the model never ran it?"),
    ("fetching", "tools/salvaged.sh", "lists or restores what tools/puzzle_worker.sh salvaged from a discarded run"),
    ("fetching", "tools/test_wordplay.py", "does wordplay.py parse and check every op of the wordplay expression, and does annotation.view() derive today's fields from the tree?"),
    ("fetching", "tools/wordplay.py", "a clue's wordplay as one line the model writes, and the tree a puzzle stores"),
    ("fetching", "tools/test_annotate_model_shape.py", "does a run's output in the model's shape (def, wp, notes) translate to the stored annotation, name the part of a parse that breaks, and refuse a clue that writes a derived key (type, blocks)?"),
    ("fetching", "tools/fixtures/quiptic-619.json", "quiptic-619 frozen in the format, so tools/test_annotate_model_shape.py has stored trees to render back to the model's shape whatever the corpus copy becomes"),
    ("fetching", "tools/fixtures/times-18.json", "times-18 frozen in the format with its annotations, so tools/test_puzzle_style.py judges an annotated puzzle whatever the corpus copy becomes"),
    ("fetching", "tools/fixtures/telegraph-31356.json", "telegraph-31356 frozen in the format, so tools/test_selector_indicator.py has letter selections to check whatever the corpus copy becomes"),
    ("fetching", "tools/test_puzzle_format.py", "do the schema and validator refuse every derived field (top-level name and series included), evaluate the trees and ratchet their unchecked steps, and does series.name_facts turn a fetched name into the prize, title or label it needs?"),
    ("fetching", "tools/fixtures/format-puzzles/", "three Guardian cryptics and a book puzzle frozen in the format, read by test_puzzle_format.py, test_shim_format.py and smoke_test.js"),
    ("fetching", "tools/test_see_pointer.py", "is a \"See N\" continuation the pointer and nothing else, in every reader?"),
    ("fetching", "tools/tidy_wordplay_shapes.py", "joins each indicator-less charade inside a charade corpus-wide where annotation.view() is unchanged, and records every other wordplay shape fault as that rule's validate_annotations allowance"),
    ("fetching", "tools/flatten_anagram_fodder.py", "rewrites each indicator-less charade filed under a checked anagram as the anagram's own parts, in clue order, corpus-wide in one migration commit, and records what it leaves (a join with its own indicator, or one under an unchecked step) as validate_annotations' wordplay.anagramCharade allowance"),
    ("fetching", "tools/strip_abbreviation_notes.py", "drops the leaf notes that only restate the abbreviation table (annotation.view() shows that gloss from build_abbreviations.table()), corpus-wide in one migration commit, and turns on validate_annotations' refusal of them"),
    ("fetching", "tools/test_abbreviation_notes.py", "is an abbreviation gloss derived from the table, never stored: view shows it, the validator refuses a note that only restates it, from_model drops one, and a note that adds anything stays?"),
    ("fetching", "tools/test_validate_shard.py", "the deploy's full annotation check runs as 6 shards (`--shard i/n`), one step each: the shards are disjoint, their union is the whole corpus, the split is stable, and a malformed or mixed-up --shard is refused"),
    ("fetching", "tools/test_validate_speed.py", "the deploy's \"Check every annotation\" step runs validate_annotations over the whole corpus (~51,000 files), so a per-file cost that creeps up becomes minutes (124s -> 247s in a day, 2026-10-13, budget 200s). The guard is the cost of 40 annotated puzzles in CPU seconds on one core, with 4x headroom over today's ~45ms a puzzle; a regression of that size fails here, long before the deploy. And the two caches the speed rests on are in place"),
    ("fetching", "tools/test_ci_checkout.sh", "the deploy's checkout (.github/workflows/pages.yml, build/Check out) run twice against a local origin: once cold, then on what Restore the git store brings back, where it must fetch only what the new commit added rather than the whole tree again (that refetch was ~58s a run). Then that every cache the build restores is saved again with the same paths and key, and that tools/trim_codeql_caches.py keeps the newest CodeQL entry per language and touches nothing else"),
    ("fetching", "tools/trim_codeql_caches.py", "delete all but the newest CodeQL overlay database per language from the repo's Actions cache, so CodeQL default setup stops evicting the deploy's caches"),
    ("fetching", "tools/test_fetch_nation_clue_list.py", "does fetch_nation read a Nation clue list whole, through the sidebars and typesetting slips the site drops into it?"),
    ("fetching", "tools/test_fetch_nation_dates.sh", "does fetch_nation date a page printing no issue on the issue clock, so it sorts between its neighbours instead of before the number below it?"),
    ("fetching", "tools/test_genius_instructions.py", "is a puzzle whose clues point at instructions we do not hold kept from the annotators, and does filing a preamble later let a parked failure retry?"),
    ("fetching", "tools/discard_alert.py", "decide whether a discarded annotation run is worth waking anyone for"),
    ("fetching", "tools/test_discard_verdict.sh", "does a discarded annotation run wake someone only when they can act on it? (tools/discard_alert.py; wired into _worker_finish in tools/puzzle_worker.sh.)"),
    ("fetching", "tools/test_withdrawn_run.sh", "does a run that takes back its own work (annotate_check.py --withdraw, or last words asking for a git revert) ship none of it, the harness putting the puzzle back? (genius-268, 10-13)"),
    ("fetching", "tools/reapply_annotation.py", "re-apply a commit's annotation onto origin's copy of its puzzle when push_puzzle_commit.sh's replay conflicts"),
    ("fetching", "tools/desktop_hosts.py", "the desktop's LAN and tailnet addresses, read once from the local config by python and shell callers"),
    ("fetching", "tools/local_config.py", "this machine's own details (the GPU host's addresses and user, the media host's login, the media disk's mount, the sibling household checkout) read from an untracked per-machine JSON file or CT_* environment variables, so none is committed to this public repo"),
    ("fetching", "tools/test_local_config.py", "does tools/local_config.py read a machine's details from the untracked file, let CT_* variables win, and fall back to values naming no real machine?"),
    ("fetching", "tools/test_clue_repair.py","does tools/clue_repair.py give a clue whose bracket its own reading lost the count another reading prints, in its parts, so the scan filers file \"3,6,5\" and not the bare letter total \"14\"?"),
    ("fetching", "tools/test_off_start_leader.py", "a leader that prints its clue on a later light, and a count the paper printed wrong"),
    ("fetching", "tools/test_failed_backoff.py", "does a code-only edit re-buy a failed run only after a cooldown that doubles (1, 2, 4... days), while a puzzle change still releases at once?"),
    ("fetching", "tools/test_clue_text.py","does tools/clue_text.py read every ACROSS / DOWN heading spelling, torn count and numeral slip the filers' old copies accepted?"),
    ("fetching", "tools/test_ocr_text_central.py","does any source reader or fetcher hold an OCR text fix (a translate table, dash/quote/ellipsis normalisation, a letter-for-digit confusion table) instead of tools/clue_text.py?"),
    ("building and checking the site", "tools/test_inflate.js", "does inflate.js, the gunzip app.js falls back on where a browser has no DecompressionStream, give back exactly what zlib compressed? Over every block type zlib writes (stored at level 0, fixed for short input, dynamic otherwise), header flags, and real shims when the checkout has them built"),
    ("building and checking the site", "tools/cache_tar.sh", "the deploy's caches of files that live directly in puzzles/, carried as one tar file each instead of an actions/cache glob over puzzles/"),
    ("building and checking the site", "tools/test_cache_tar.sh", "tools/cache_tar.sh round trip on a small tree: pack takes exactly the files each deploy cache carried as a glob (puzzles/*/index.html and the page store; puzzles/*.js, *.js.gz, shims.gz.json) with their mtimes, unpack puts them back and removes the tar, and a missing tar is a cold cache, not an error"),
    ("building and checking the site", "tools/privateeye_wayback.py", "private Eye Cyclops crosswords the Eye no longer serves, from the Wayback Machine"),
    ("building and checking the site", "tools/file_livejournal_puzzles.py", "file the Club Monthly posts only times-for-the-times' old LiveJournal holds"),
    ("building and checking the site", "tools/nation_key.py", "the Nation's answers, from the setters' own solution printed a week later"),
    ("building and checking the site", "tools/test_nation_key.py", "does nation_key read The Nation's answers from the setters' printed solution and Braze's posts, and only the letters they really spell?"),
    ("building and checking the site", "tools/nation_images.py", "the Nation's own pictures of its grids: the blank grid every page prints"),
    ("building and checking the site", "tools/test_fetch_nation_build_one.sh", "does one bad page fail on its own in fetch_nation's worker pool?"),
    ("building and checking the site", "tools/test_pct.sh", "does the site's progress percent floor, and only say 100% when it is?"),
    ("building and checking the site", "tools/media_manifest.py", "what the media disk holds, kept on the SSD so no scheduled job walks it"),
    ("building and checking the site", "tools/test_trove_grid_asymmetric.py", "does trove_grid.read_grid keep a block whose 180-degree mirror is a light, instead of averaging the pair into a light"),
    ("building and checking the site", "tools/test_no_media_scans.py", "does no scheduled tick walk the media disk?"),
    ("building and checking the site", "tools/privateeye_scans.py", "read a Cyclops crossword's clues off the page image of archive.org's Private Eye scan"),
    ("building and checking the site", "tools/test_privateeye_scans.py", "does tools/privateeye_scans.py find a Private Eye page's clue columns from its djvu words, take the crossword's number and not the entry address's, read a linked head and a cross-reference, and hand privateeye_wayback's read_capture a list it parses? And does the shared tidy read RapidOCR's full-width bracket as a round one?"),
    ("building and checking the site", "tools/test_read_scans.py", "does read_scans report a Private Eye number whose issue was already read for the one before by what that reading said, not as 'not read'?"),
    ("building and checking the site", "tools/cyclops_jumbos.py", "Cyclops jumbos with a preamble: carries the preamble, unclued lights and a perimeter ring read from the page's caption"),
    ("building and checking the site", "tools/data/cyclops_jumbos.json", "per Cyclops jumbo number, the preamble and unclued/perimeter entries tools/cyclops_jumbos.py adds to the filed puzzle"),
    ("building and checking the site", "tools/test_sync_retry.js", "a sync push that fails must never lose a save, and must retry on its own"),
    ("building and checking the site", "tools/test_pdf_edition_broken.py", "does tools/fetch_archive_org_editions.py read the pages of an image PDF that archive.org holds zero-filled past some page (FT 1981-06-29/30), listing the broken ones in \"unreadable\" instead of raising; and does fetch_pdf fetch a PDF whose md5 is not the metadata's once more, keep a second copy equal to the first (archive.org's file as it stands), and raise when the two differ?"),
    ("building and checking the site", "tools/test_desktop_hosts.py", "does tools/desktop_hosts.py find the desktop's live address itself (its LAN lease flaps), probing every address at once, keeping the order a TTL, probing afresh after forget(), and do ocr_remote.by_path and vlm_reader.resolve use it, so one dead LAN address stalls nothing?"),
    ("building and checking the site", "tools/gale_idle.py", "exit 0 when a cryptic-gale-inbox tick would do nothing, so tools/gale_inbox.sh"),
    ("building and checking the site", "tools/test_gale_idle.py", "does tools/gale_idle.py let a cryptic-gale-inbox tick skip its worktree setup only when the tick would do nothing: the progress page rendered within the hour and no download since (or one, but the page under RENDER_MIN old), and no fresh edition waiting with no full pass running; and does it force a full tick MAX_SKIP after the last? Does tools/vlm_health.py --quick skip only an up VLM that was not down?"),
    ("building and checking the site", "tools/test_abbreviations_cache.py", "does build_abbreviations.table() give the same table from its disk cache as from a build, and rebuild the moment an input's bytes change?"),
    ("building and checking the site", "tools/test_unit_idle.py", "does unit_queue.why_run let the books and daily ticks skip their worktree setup only when the tick would start nothing: a SELF_PLANNING queue (books) with nothing due, or any queue while the memory or CPU gate holds every unit back; never a queue whose shell plans the tick (daily) past the gates; and a full tick at least every FULL_EVERY?"),
    ("building and checking the site", "tools/test_parallel.py", "does tools/parallel.py size its pool to the box? CT_JOBS wins; a process at nice 0 (the deploy's build) takes every core; a niced one (the daily units, the corpus job) takes only the cores the load leaves idle, down to one, and pmap then runs serially with no fork; and pmap's results are the serial loop's either way"),
    ("annotating", "tools/shape_suspects.py", "rank clues whose wordplay tree is probably wrong, from shape signals (read-only on puzzles/)"),
    ("annotating", "tools/fix_shape_suspects.py", "repair the shape suspects whose right tree follows from the clue, answer and tree alone (dry run by default; --apply writes puzzles, one sweep commit), and list the rest per clue in tools/data/shape_reannotate.json"),
    ("annotating", "tools/tidy_cdef_repeat.py", "rewrite cryptic definitions stored as several leaves, corpus-wide (wordplay.cdefRepeat)"),
    ("annotating", "tools/shape_queue.py", "the clues whose wordplay tree tools/shape_suspects.py flags and"),
    ("annotating", "tools/prune_shape_queue.py", "drop the shape re-annotation rows no detector their reason names fires on now (--write to rewrite; shape_queue.flagged skips the same rows)"),
    ("annotating", "tools/test_fix_shape_suspects.py", "the ins_split repair of fix_shape_suspects.py: a container over a flat 3-part charade becomes part 2 inside parts 1+3 when the letters say so and no other nesting spells the answer"),
    ("annotating", "tools/test_shape_queue.py", "the shape re-annotation list (tools/shape_queue.py): a listed clue is written by a run on its hinted puzzle, the old hint is never lost, and a filed clue leaves the list. The queue tier's ordering is in prereset_plan.py --self-test"),
    ("annotating", "tools/test_annotate_note_skeleton.py", "annotate_check prints every missing block note as one --patch file, so the commonest first-check failure is one Write and one command"),
    ("annotating", "tools/hintless_overdue.py", "a newly filed puzzle that is still hintless long after it should have been annotated"),
    ("annotating", "tools/test_hintless_overdue.py", "hintless_overdue.overdue() on fixtures: only a recent, solved, hintless, unblocked puzzle past the threshold"),
    ("annotating", "tools/test_corpus_queue_yield.py", "corpus_queue.yield_collapse() on fixture logs: the last 100 scans with under 5 puzzles wake the room, a healthy or short window does not"),
    ("annotating", "tools/test_times_four_digit_title.py", "the Times title and solution headings of the four-digit numbers (before No 10,000, May 1962) read as puzzles, five-digit ones as before"),
    ("annotating", "tools/test_resume_not_redo.py", "pins the two fixes for burn waste found in the 10-16 audit of .prereset.log"),
    ("annotating", "tools/drop_failed_clues.py", "blank just the clues whose annotations fail validation, so the rest ship"),
    ("annotating", "tools/clue_bag.py", "which tail puzzles one annotate session takes together: a bag"),
    ("annotating", "tools/annotate_bag_prompt.md", "the task a bagged session (several tail puzzles at once) is given"),
    ("annotating", "tools/test_annotate_bag.py", "the bag's one view and one annotations file"),
    ("annotating", "tools/test_clue_bag.py","which tail puzzles share one annotate session, and which never do"),
    ("annotating", "tools/build_spellings.py", "writes tools/data/lexicons/spellings.json: answer letters mapped to the spelling with an apostrophe or accent, for the lesson checks"),
    ("annotating", "tools/clear_unchecked.py", "drops the unchecked flag from wordplay trees that evaluate to their answer without it, one commit per puzzle (wordplay.unchecked)"),
    ("annotating", "tools/fill_spellings.py", "writes the `spelling` that tools/lesson_checks.py flags as unsaid (spelling.unsaid), where the answer letters give only one"),
    ("annotating", "tools/hidden_mechanical.py", "the hidden words a clue gives away mechanically"),
    ("annotating", "tools/lesson_checks.py", "annotation findings that tools/validate_annotations.py counts, each under its own ratchet: a double definition hiding the answer, a spelling left unsaid"),
    ("annotating", "tools/prefill_hidden.py", "write the annotation of a near-certain hidden word without a model run"),
    ("annotating", "tools/test_lesson_checks.py", "proves the double-definition and unsaid-spelling findings of tools/lesson_checks.py"),
    ("annotating", "tools/test_clear_unchecked.py", "proves tools/clear_unchecked.py drops the flag only where the tree gives the answer without it and the validator finds nothing new"),
    ("annotating", "tools/test_fill_spellings.py", "proves tools/fill_spellings.py writes the spelling only where unambiguous, with grace for the lesson-check ratchets"),
    ("annotating", "tools/test_hidden_mechanical.py", "proves the near-certain hidden words of tools/hidden_mechanical.py and the annotation tools/prefill_hidden.py builds from one"),
    ("annotating", "tools/data/lexicons/spellings.json", "answer letters mapped to their spelling with apostrophe or accent, built by tools/build_spellings.py"),
    ("annotating", "tools/test_reconstruct_budget.py", "reconstruct_grid's node budget covers every path, and its pruning is sound"),
    ("annotating", "tools/test_ctc_hintcheck.py", "does hintcheck's per-clue comparison classify what it should, and stay silent otherwise?"),
    ("annotating", "tools/hint_rungs.js", "the hint rungs the app shows, as JSON, for tools that compare them with something"),
    ("annotating", "tools/prereset_watch.sh", "what the */5 fire of the pre-reset burn checks before it tries to start one"),
    ("annotating", "tools/test_prereset_watch.sh", "does tools/prereset_watch.sh see a burn that is alive but stuck, and one that is dead with orphans holding its tree lease?"),
    ("annotating", "tools/test_reindex_changed.py", "does fetch_puzzle.reindex_changed() re-read only the puzzle files newer than the index, and fall back to the full reindex when there is no index?"),
    ("annotating", "tools/test_spelling_kept.py", "does a re-annotation that drops the spelling HEAD's annotation of the same answer carries (book-26021 22D lost APERÇU) get refused by the run's check against HEAD?"),
    ("annotating", "tools/unchecked_repairs.py", "mechanical repairs for an unchecked wordplay tree (wordless leaves, unscrambled fodder), each kept only when the evaluator then finds the answer, so tools/clear_unchecked.py can clear more flags"),
    ("annotating", "tools/test_unchecked_repairs.py", "is each mechanical repair of an unchecked tree kept only when the evaluator then finds the answer, on clues from the corpus?"),
    ("annotating", "tools/test_worker_commit.sh", "does worker_commit commit only its own paths, and say why when it cannot?"),
    ("annotating", "tools/fix_scrambled_gives.py", "drop the made-up `gives` of a fodder leaf inside an anagram (shape round 3, 10-17)"),
    ("annotating", "tools/test_shape_detector_false_positives.py", "the shape detectors (shape_suspects, via shape_queue.findings) must not flag clues no"),
    ("annotating", "tools/test_validator_gap_rules.py", "tests for the validator-gap rules: folded indicators, fake substitution parts, padding leaves and the redo regression gate"),
    ("annotating", "tools/test_og_prose_family.py", "does the og card's own-prose family check ignore words quoted from the clue?"),
    ("annotating", "tools/test_repair_padding.py", "tests that repair_fetched takes link words out of the wordplay, and only those"),
    ("annotating", "tools/test_ci_cache_partial.js", "a cold result cache must be able to refill over several runs"),
    ("annotating", "tools/annotate_bag.py", "the files a bag session (tools/annotate_bag_prompt.md) works from and writes"),
    ("annotating", "tools/queue_unchecked.py", "queue every clue that still carries an `unchecked` wordplay step for the burn's redo"),
    ("annotating", "tools/run_clear_full.sh", "the full clear_unchecked --write sweep, resumable and published as it goes"),
    ("annotating", "tools/test_refetch_curly_apostrophe.py", "a re-fetch serving curly apostrophes must not strip the annotations of the"),
    ("annotating", "tools/requeue_drift.py", "queue what a rule change or a lexicon rebuild newly flags, instead of letting it turn CI red"),
    ("annotating", "tools/test_requeue_drift.py", "tools/requeue_drift.py: a puzzle past its allowance gets its flagged clues queued once"),
    ("annotating", "tools/prune_shims.py", "remove the puzzles/*.js shims (and their .gz) that the index no longer names"),
    ("annotating", "tools/test_tree_normalize.py", "tree_normalize: canonical rewrites by code, letters proved unchanged (r10 sample rows)"),
    ("annotating", "tools/tree_normalize.py", "rewrite wordplay trees into Paul's canonical forms by code, before any clue goes to a model"),
    ("annotating", "tools/ci_scope.py", "what tests.yml has to run for a push: the whole suite, or the puzzle fast path"),
    ("annotating", "tools/test_ci_scope.py", "tools/ci_scope.py: which pushes may skip the sharded suite, and how tests.yml wires that in"),
    ("annotating", "tools/test_clue_tokens.js", "the word chips under a clue and the highlights in its heading cut a hyphenated word at the same places: a compound is one chip (\"Drug-free\") unless an annotation fragment starts or ends at its hyphen (the indicator \"free\" in \"Drug-free period\"), and then both are cut there. Reads clueTokens and clueCuts out of app.js, so it cannot drift from the app"),
    ("annotating", "tools/test_drop_restores_hint.py", "a failed redo of a clue that already had a committed hint gets that hint back from drop_failed_clues.py; only never-hinted clues are blanked"),
    ("annotating", "tools/test_redo_unchanged.py", "a re-annotation scoped to some clues writes only those, and a redo of the same tree and letters in other words leaves the old hint as it was"),
    ("annotating", "tools/test_batch_subject.sh", "a batch commit's subject names only the puzzles whose file the commit changes (164738e46f2 listed 20 ids and changed just the queue file)"),
    ("annotating", "tools/test_trimmed_lead.py", "the 1945-49 Times' clue column stands right of a column of small ads, and"),
    ("annotating", "tools/audit_crops.py", "dry-run audit of the archive filer's clue-column crops, per year"),
    ("annotating", "tools/crop_window.py", "clue-column windows chosen from the page's own ink, and the check that a"),
    ("annotating", "tools/test_crop_window.py", "crop_window finds the gutters between columns of print from the ink"),
    ("annotating", "tools/det_solve.py", "a code-only (no model) cryptic solver prototype, built to answer \"can the corpus solve or validate clues?\""),
    ("annotating", "tools/det_leaf_audit.py", "why does the corpus leaf table miss a held-out leaf?  python3 tools/det_leaf_audit.py [--show N]"),
    ("annotating", "tools/det_synonyms.py", "the synonym dictionary of tools/det_solve.py: clue phrase -> {letters it can give: score}, from many sources"),
    ("annotating", "tools/fetch_moby.py", "download the Moby Thesaurus II (public domain, Grady Ward) as data only: fetch_moby.py OUT_FILE [URL ...]"),
    ("fetching", "tools/ocr_retry.py", "a clue the scan's readers leave blank or unsettled, read again line by line with Tesseract variants (scale, binarisation, model) on spare CPU before the VLM is asked about it: opt-in (CT_OCR_RETRY=1, it spared no ask in the A/B), it fills the clue only where two variants print every line alike and a scan reader prints the whole too; always appends each clue the VLM answered, beside the OCR's readings, to the VLM corpus (~/.cache/corpus_queue/vlm_corpus.jsonl)"),
    ("fetching", "tools/test_ocr_retry.py", "does tools/ocr_retry.py settle a weak clue only from lines two variants print alike and only when a scan reader prints the whole too, find a clue's lines by number and direction, read each line once (cached per page), and append one corpus row a call?"),
    ("fetching", "tools/apply_blog_answers.py", "fill a held puzzle's missing answers from the blog that wrote it up"),
    ("fetching", "tools/fill_checked_lights.py", "fill a blog-keyed puzzle's blank lights that the crossings or the write-up's own word settle"),
    ("fetching", "tools/test_fill_checked_lights.py", "fill_checked_lights fills only what the grid or the write-up settles"),
    ("fetching", "tools/test_apply_blog_answers.py", "apply_blog_answers reads an answer off a write-up line however the era prints it"),
    ("fetching", "tools/bigdave_layout.py", "helpers for apply_blog_answers' bigdave44 source: the two-paragraph clue layout"),
    ("fetching", "tools/blog_comment_rows.py", "answer rows read from the comments under a Times for the Times post"),
    ("fetching", "tools/test_push_batch.sh", "does tools/push_puzzle_commit.sh batch pushes that come inside its window, and does the batch always reach origin, with every commit kept as its own?"),
    ("fetching", "tools/refusal_replay.py", "replay the wordplay refusals annotation runs hit, through today's evaluator"),
    ("fetching", "tools/test_refusal_replay.py", "does the wake's refusal section replay, group, count retries and name a cause?"),
    ("fetching", "tools/learn_postproc.py", "mine the clue-text rewrites in \"Update ...\" commits for post-processor rules"),
    ("fetching", "tools/test_learn_postproc.py", "does learn_postproc class each clue rewrite and score a rule's hits, worse and fixpoint breaks?"),
    ("fetching", "tools/audit_updates.py", "audit the clue text each reread (\"Update ...\" commit) wrote: glitches it brought in or took out"),
    ("fetching", "tools/test_audit_updates.py", "does audit_updates class each reread change introduced, fixed or neutral, and alert on a new class?"),
]

# Files that are deliberately absent from the layout table: scratch, data the
# table already covers as a glob, and things nobody reading the README needs to
# be shown. Anything else under tools/ must be described or the build fails.
LAYOUT_EXEMPT = re.compile(r"""
      ^tools/_                      # scratch scripts, named with a leading underscore
    | ^tools/__pycache__/
    | ^puzzles/                     # covered by the <series>/<year>/<series>-<n>.json line
    | ^clues_only/                  # covered by the clues_only/<series>/<id>.json line
    | ^tools/data/favourite_grading/(packets|scores)/  # covered by the two directory lines
    | ^tools/data/penguin_partial_fills/            # covered by the directory line
    | ^tools/data/blog_facts/                       # covered by the directory line
    | ^tools/data/yt_solvers/                       # covered by the directory line
    | ^tools/fixtures/trove/                        # covered by the directory line
    | ^tools/fixtures/archive-org-grids/            # covered by the directory line
    | ^tools/fixtures/archive-org-titles/           # covered by the directory line
    | ^tools/fixtures/archive-org-clues/            # covered by the directory line
    | ^tools/fixtures/trove-repair/                 # covered by the directory line
    | ^tools/fixtures/trove-clues/                  # covered by the directory line
    | ^tools/fixtures/trove-solution/               # covered by the directory line
    | ^tools/fixtures/format-puzzles/               # covered by the directory line
    | ^household-plugins/           # covered by the <name>/plugin.toml line
    | ^og/                          # covered by the og/ line
    | ^vendor/                      # covered by the vendor/ line
    | ^learn/ | ^abbreviations/ | ^indicators/
    | ^favicon | ^icon- | ^apple-touch-icon   # covered by the icon-set line
    | ^\. | /\.                     # dotfiles: .nojekyll, .gitignore, .github/
    | ^README\.md$ | ^LICENSE
    | ^index\.html$ | ^style\.css$ | ^app\.js$
""", re.X)

# Where each scheduling default really lives. docs/NIGHTLY.md quotes these numbers in
# prose; parsing them from the script is what keeps the prose honest, and a knob
# that gets renamed fails the build instead of leaving a plausible wrong number
# on the page.
KNOB_FILES = {
    "ANNOTATE_MAX": "tools/daily_update.sh",
    "ANNOTATE_MAX_WEEKLY_PCT": "tools/daily_update.sh",
    "ANNOTATE_MAX_SESSION_PCT": "tools/daily_update.sh",
    "SOLVE_MAX": "tools/daily_update.sh",
}


def fail(msg):
    print(f"build_readme: {msg}", file=sys.stderr)
    raise SystemExit(1)


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def read_knobs():
    """Every default in KNOB_FILES, as {name: value}, straight from the shell."""
    knobs = {}
    for name, rel in KNOB_FILES.items():
        text = (REPO / rel).read_text(encoding="utf-8")
        m = re.search(rf'^{name}="\$\{{{name}:-([^}}]*)\}}"', text, re.M)
        if not m:
            fail(f"{rel} no longer sets a default for {name}. Either it was "
                 f"renamed — update KNOB_FILES — or docs/NIGHTLY.md should stop "
                 f"quoting it.")
        knobs[name] = m.group(1)
    return knobs


def build_layout():
    described = {path for _, path, _ in LAYOUT}
    tracked = set(tracked_files())
    # Every file that has to be named individually: the exempt ones are the ones a
    # directory or glob line already stands for.
    on_disk = {p for p in tracked if not LAYOUT_EXEMPT.search(p)}

    missing = sorted(on_disk - described)
    if missing:
        fail("these tracked files have no line in the layout table:\n  "
             + "\n  ".join(missing)
             + "\nRun `python3 tools/build_readme.py --add-missing` to write a row "
               "for each from its own docstring, or add one to LAYOUT in this "
               "script by hand (or to LAYOUT_EXEMPT if a reader genuinely does "
               "not need to know).")
    # A line that names several files, or a directory, or a glob, stands for a set
    # the exempt list covers; only the lines naming exactly one path can be checked
    # for having outlived it.
    gone = sorted(d for d in described - tracked
                  if not any(c in d for c in "<*,") and not d.endswith("/"))
    if gone:
        fail("the layout table describes files that no longer exist:\n  "
             + "\n  ".join(gone) + "\nRemove them from LAYOUT in this script.")

    width = max(len(path) for _, path, _ in LAYOUT) + 2
    lines, section = [], None
    for sec, path, desc in LAYOUT:
        if sec != section:
            if section is not None or sec:
                lines.append("")
            if sec:
                lines.append(sec)
            section = sec
        head = f"{path.ljust(width)}{desc}"
        # Wrapped to the same column the descriptions start in, so a long line
        # reads as one entry rather than as a new file.
        wrapped, line = [], head
        while len(line) > 96:
            cut = line.rfind(" ", 0, 96)
            wrapped.append(line[:cut])
            line = " " * width + line[cut + 1:]
        wrapped.append(line)
        lines.extend(wrapped)
    return "```\n" + "\n".join(lines) + "\n```"


def _first_summary_line(text):
    """The one-line summary out of a docstring or comment-header paragraph.

    PEP 257 docstrings put the summary on the first line; comment headers put
    it in the first sentence of the first paragraph. Either way we want one
    line, not the worked example or the second paragraph that follows it.
    """
    first_line = text.strip().splitlines()[0].strip().rstrip(".")
    if not first_line:
        return None
    # "Take a book ..." reads as a row title elsewhere in LAYOUT; the table's
    # own voice is "takes a book ...". Lowercase the lead word unless it looks
    # like an acronym or a name (a second capital right after the first).
    if first_line[0].isupper() and not (len(first_line) > 1 and first_line[1].isupper()):
        first_line = first_line[0].lower() + first_line[1:]
    return first_line


def derive_description(path):
    """The one-line description --add-missing writes for `path`, or None.

    Python files: the module docstring's summary line. Shell and JS files:
    the first paragraph of the leading comment block (after a shebang, if
    any), which is where every existing tools/*.sh and tools/*.js file puts
    its own explanation. JS is read in both of its spellings — `//` lines and
    a `/* */` block — because both are in use here and a reader that knows
    only one silently reports the other as having no description at all.
    Returns None rather than guessing when a file has neither — a data file,
    an image, a generated artifact — so the caller can refuse to invent a
    description for it.
    """
    try:
        text = (REPO / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        doc = ast.get_docstring(tree)
        return _first_summary_line(doc) if doc else None
    lines = text.splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    if path.endswith(".js") and lines and lines[0].lstrip().startswith("/*"):
        paragraph = _block_comment_paragraph(lines)
    else:
        paragraph = _line_comment_paragraph(
            lines, "//" if path.endswith(".js") else "#")
    if not paragraph:
        return None
    return _first_summary_line(" ".join(paragraph))


def _line_comment_paragraph(lines, prefix):
    """The first blank-line-delimited paragraph of a leading `prefix` block."""
    paragraph = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            break
        body = stripped[len(prefix):].strip()
        if not body:
            if paragraph:
                break
            continue
        paragraph.append(body)
    return paragraph


def _block_comment_paragraph(lines):
    """The first paragraph of a leading `/* ... */` block.

    The block ends at `*/` wherever it falls, so a one-line `/* x */` header
    reads the same as a boxed one; the decorative leading `*` that most of
    them carry is not part of the sentence and comes off.
    """
    paragraph = []
    for line in lines:
        body = line.strip()
        if body.startswith("/*"):
            body = body[2:]
        end = body.find("*/")
        if end != -1:
            body = body[:end]
        body = body.strip()
        if body.startswith("*"):
            body = body[1:].strip()
        if not body:
            if paragraph:
                break
        else:
            paragraph.append(body)
        if "*/" in line:
            break
    return paragraph


def add_missing_layout_rows():
    """Write a LAYOUT row for every tracked file that lacks one.

    Only ever adds rows — an existing description, however stale-looking, is
    left exactly as the person who wrote it phrased it. A file whose docstring
    or header comment yields nothing usable (a data file, an image, a
    generated artifact) is reported and skipped rather than given a made-up
    description; the caller still gets rows for everything that could be
    derived, but exits non-zero so the leftover file does not go quiet.
    """
    described = {path for _, path, _ in LAYOUT}
    tracked = set(tracked_files())
    on_disk = {p for p in tracked if not LAYOUT_EXEMPT.search(p)}
    missing = sorted(on_disk - described)
    if not missing:
        print("every tracked file already has a layout row")
        return 0

    section = LAYOUT[-1][0] if LAYOUT else ""
    added, unresolved = [], []
    for path in missing:
        desc = derive_description(path)
        if desc is None:
            unresolved.append(path)
        else:
            added.append((section, path, desc))

    if added:
        src_path = Path(__file__).resolve()
        text = src_path.read_text(encoding="utf-8")
        start = text.index("LAYOUT = [\n") + len("LAYOUT = [\n")
        close = text.index("\n]\n", start)
        new_lines = "".join(
            f"    ({json.dumps(sec)}, {json.dumps(p)}, {json.dumps(d)}),\n"
            for sec, p, d in added)
        text = text[:close + 1] + new_lines + text[close + 1:]
        src_path.write_text(text, encoding="utf-8")
        for _, p, d in added:
            print(f"added: {p} — {d}")
        # docs/LAYOUT.md carries the table, and --check-layout fails until it
        # does; its region needs only the file list, not the generated site.
        LAYOUT.extend(added)
        LAYOUT_DOC.write_text(render(LAYOUT_DOC), encoding="utf-8")

    if unresolved:
        fail("no usable docstring or header comment, so no row was written "
             "for these tracked files:\n  " + "\n  ".join(unresolved)
             + "\nAdd a docstring/header comment to each, or a row to LAYOUT "
               "in tools/build_readme.py by hand.")
    return 0


def build_knobs(k):
    return (
        f"The two scheduled jobs split the quota deliberately: the nightly's "
        f"units, started by a tick every ten minutes, annotate every puzzle from "
        f"the last two days plus at most {k['ANNOTATE_MAX']} a day from the "
        f"backlog, and only below {k['ANNOTATE_MAX_WEEKLY_PCT']}% of the week "
        f"(and {k['ANNOTATE_MAX_SESSION_PCT']}% of the rolling five-hour window, "
        f"re-checked as each puzzle starts), while the hourly one spends everything "
        f"else with no gate: as many runs as land the weekly meter at its limit "
        f"right at the weekly reset, net of the bridge's own spend, waiting out "
        f"any five-hour lockout, until the weekly meter is spent or the week "
        f"resets. When Paul has weekly resets to spend, "
        f"`tools/prereset_plan.py --five-hour` paces each five-hour window to "
        f"its own reset instead, until the week resets or `--weekly` is run."
    )


# What each rung is FOR. The name beside it is not written here: app.js owns the
# labels, because they are what the buttons say, and a README that renamed them
# in prose would be describing a site that does not exist. A rung added to app.js with no line here fails this
# script rather than quietly going undescribed.
RUNG_NOTES = {
    "type": "anagram? charade? container? hidden word? …",
    "definition": "the definition part of the clue is highlighted",
    "indicators": "the anagram, container, reversal and homophone signal words "
                  "are highlighted",
    "blocks": "the fodder and the synonym breakdown, a piece at a time "
              "(\u201chost = ARMY; part of TV duo = ANT\u201d). A double "
              "definition has none: its halves are the definition rung's",
    "walkthrough": "the whole assembly, step by step",
}


def build_ladder():
    """The ladder, named with app.js's own button labels and in its own order."""
    app = (REPO / "app.js").read_text(encoding="utf-8")
    import app_tables
    # The numbering is app.js's own: `ladder()` reads the ordered LABELS map the
    # app sorts its rungs by, and raises if app.js stops deriving the order from
    # it. A copy of the order here would keep printing the old order after the
    # app reordered its rungs.
    labels = app_tables.ladder(app)
    missing = [k for k, _ in labels if k not in RUNG_NOTES]
    if missing:
        fail("these rungs are in app.js but have no line in RUNG_NOTES in this "
             "script, so the README would not say what they teach: "
             + ", ".join(missing))
    fill = re.search(r'const FILL_LABEL = "([^"]+)"', app)
    if not fill:
        fail("app.js has no `const FILL_LABEL`, which names the way out of a clue.")
    # No full stop after a note that already ends in one — "hidden word? \u2026."
    # is what writing a sentence in two places looks like.
    lines = [f"{i}. **{name}** \u2014 {RUNG_NOTES[key]}"
             + ("" if RUNG_NOTES[key][-1] in ".?\u2026" else ".")
             for i, (key, name) in enumerate(labels, 1)]
    lines.append("")
    lines.append(f"**{fill.group(1)}** writes the solution into the grid. It is the "
                 "way out of a clue rather than a step in it, so it is offered "
                 "alongside the rungs once the building blocks are up, and it is "
                 "not counted as one.")
    return "\n".join(lines)


# Which generated region lives in which file. The README is for a visitor, so it
# carries only the ladder and the corpus line; the quota split belongs with the
# nightly jobs it describes, and the layout table is 300 lines of inventory with
# a page of its own.
REGIONS = {
    README: {"LADDER": build_ladder},
    NIGHTLY_DOC: {"KNOBS": lambda: build_knobs(read_knobs())},
    LAYOUT_DOC: {"LAYOUT": build_layout},
}


def render(path):
    text = path.read_text(encoding="utf-8")
    blocks = dict(REGIONS[path])
    for name, build in blocks.items():
        pattern = re.compile(
            rf"(<!-- {name}-START[^>]*-->).*?(<!-- {name}-END -->)", re.S)
        if not pattern.search(text):
            fail(f"{path.name} has no <!-- {name}-START --> … <!-- {name}-END --> "
                 f"markers. They are what makes this region generated; put them "
                 f"back rather than hand-writing the block.")
        text = pattern.sub(
            lambda m: f"{m.group(1)}\n{build()}\n{m.group(2)}", text, count=1)
    # Deliberately no substitution outside the markers. A placeholder anywhere
    # else would be consumed the first time this ran — the number would replace
    # it in the file, and the next run would have nothing left to substitute and
    # would happily agree with a value that had since changed. Inside the markers
    # the block is rebuilt from nothing every time, which is what makes the check
    # meaningful; so a knob is quoted once, there, and the prose points at it.
    return text


def main():
    # An unknown flag (--help included) must not fall through to the full
    # rebuild: that is a multi-process corpus pass on a shared host.
    unknown = [a for a in sys.argv[1:]
               if a not in ("--check", "--check-layout", "--add-missing")]
    if unknown:
        print(__doc__, file=sys.stderr)
        print(f"unknown argument: {' '.join(unknown)}", file=sys.stderr)
        return 2
    # The layout table alone, and nothing generated. Every tracked file needs a
    # row or build_readme refuses to run at all, and it is run by the nightly
    # rebuild and by test_push_conflict.sh's -- so a new tool with no row does
    # not fail its own check, it fails whatever ran the rebuild. This says it
    # in one line, in CI, naming the file.
    if "--check-layout" in sys.argv[1:]:
        build_layout()
        # And that docs/LAYOUT.md carries that table as it now stands. The doc is
        # generated output that is committed, and only a rebuild rewrites it, so
        # a tool given a row here and never rebuilt into the file rots there with
        # nothing failing. This region is the one that cannot drift on its own:
        # it is a function of the tracked file list, not of the corpus, so unlike
        # --check it stays true between annotations and belongs in CI.
        if render(LAYOUT_DOC) != LAYOUT_DOC.read_text(encoding="utf-8"):
            print(f"{LAYOUT_DOC.name} out of date — run tools/build_readme.py",
                  file=sys.stderr)
            return 1
        print("every tracked file has a layout row, and docs/LAYOUT.md has them all")
        return 0
    if "--add-missing" in sys.argv[1:]:
        return add_missing_layout_rows()
    check = "--check" in sys.argv[1:]
    stale = []
    for path in REGIONS:
        new = render(path)
        if new == path.read_text(encoding="utf-8"):
            print(f"{path.name} is up to date")
            continue
        if check:
            stale.append(path.name)
            continue
        path.write_text(new, encoding="utf-8")
        print(f"{path.name} rewritten")
    if stale:
        print(f"{', '.join(stale)} out of date — run tools/build_readme.py",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
